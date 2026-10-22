#!/usr/bin/env python
"""
Respondent erasure across a project's on-disk artifacts (v3.1.1, Phase 1.3).

A subject-access / right-to-erasure request has to remove a person from
*everything*, not just the tidy relational store. The store side is nearly free
because foreign keys cascade — the hard 80% is the derived artifacts a run leaves
around: scored CSVs, the embedding cache, quotes copied into cluster summaries
and the markdown report. This module handles that spread.

Design decisions
----------------
- **Embeddings are deleted, not surgically edited.** `embeddings.npy` and the
  iterative `embeddings_<hash>.npy` caches are row-indexed and aligned to a
  frame; you cannot remove one row's vector and keep the alignment guarantees
  every consumer relies on. They are cheap to regenerate, so delete-and-invalidate
  is the only safe move.
- **Example-quote columns are the sneaky leak.** A deleted respondent's words can
  survive inside `example_quotes` in `cluster_summary.csv` and inside
  `run_report.md`, which have no `response_id` column to filter on. We scrub the
  erased text string out of those rather than pretend a row-drop covered it.
- **The audit log records that an erasure happened, not who.** We store
  `sha256(response_id)` — enough to prove the request was honored, without
  retaining the identifier we were asked to forget.
- **The store is VACUUMed after the delete.** SQLite frees a deleted row's page,
  it does not overwrite it, so the response stayed legible in the `.qnw` bytes —
  `strings project.qnw` printed it back — until the database was rebuilt. That is
  not the usual "unlink is not shred" caveat about disks: it is the *live project
  file* the researcher goes on using, copies to a colleague, and attaches to an
  archive, still holding the words of someone who withdrew consent. VACUUM closes
  that gap. Erasure is rare, so the rewrite cost is worth paying.
- **The pre-erase backup holds the un-erased data, so it is purgeable here.**
  Keeping it is a real safety net for "I erased the wrong id", so the purge is the
  caller's decision (`purge_backups=`) rather than automatic — but the report
  always names the backups that still hold the data, so no front end can omit the
  step silently. The purge runs *after* the erasure, never before: destroying the
  safety net ahead of the risky step is exactly backwards.
- **No promise of secure/overwrite deletion.** `unlink` on an SSD does not
  guarantee the bytes are gone. The honest posture (documented) is "removed from
  the project; keep projects on encrypted institutional volumes."
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from core.inference_cache import CACHE_FILENAME as INFERENCE_CACHE_FILENAME
from core.backups import BACKUP_DIR_NAME, list_backups


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _vacuum(store_path: Path) -> bool:
    """Rebuild the store so freed pages carry no readable remnant. Never raises.

    A failed VACUUM (a locked file, a full disk) must not undo an erasure that
    already succeeded, so the outcome is reported rather than thrown — the caller
    can retry, and the audit event records which it was.
    """
    try:
        conn = sqlite3.connect(str(store_path))
        try:
            conn.execute("VACUUM")
            conn.commit()
        finally:
            conn.close()
        return True
    except Exception:  # noqa: BLE001 - reported, never fatal to the erasure
        return False


def _append_audit(project_dir: Path, event: Dict[str, Any]) -> None:
    """Append one erasure event to the project's audit log (JSON lines)."""
    event = {"timestamp": datetime.now().isoformat(timespec="seconds"), **event}
    log = project_dir / "audit_log.jsonl"
    with log.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event) + "\n")


def _rewrite_csv_dropping_response(
    path: Path, response_id: str, erased_texts: List[str]
) -> Dict[str, Any]:
    """Drop matching rows from a run CSV; scrub erased text from quote columns.

    Returns a small report.

    Read and written as text (review finding F3). Read with type inference, id
    "000123" came back as 123, so the filter below compared "123" with "000123"
    and **kept the erased respondent's row**; the rewrite also stripped leading
    zeros from everyone else's ids and turned literal "N/A" answers into blanks.
    Cells this function does not change are written back exactly as read (they
    were guarded against CSV injection when the program first wrote them);
    cells it scrubs go through `sanitize_for_csv` again.
    """
    from analyze_survey import sanitize_for_csv
    from core.encodings import read_csv_as_text

    try:
        read = read_csv_as_text(path)
    except Exception as exc:  # noqa: BLE001 - a malformed artifact must not abort erasure
        return {"file": str(path), "status": f"skipped ({exc})"}
    df = read.frame

    before = len(df)
    dropped = 0
    if "response_id" in df.columns:
        mask = df["response_id"].str.strip() != str(response_id).strip()
        dropped = int((~mask).sum())
        df = df[mask].copy()

    # Scrub erased text from any string cell — covers example-quote columns in
    # files (cluster_summary) that have no response_id to filter on.
    scrubbed_cells = 0
    if erased_texts:
        needles = [t for t in erased_texts if t]

        def _scrub(value: Any) -> Any:
            nonlocal scrubbed_cells
            if isinstance(value, str):
                new = value
                for needle in needles:
                    if needle and needle in new:
                        new = new.replace(needle, "[ERASED]")
                if new != value:
                    scrubbed_cells += 1
                    return sanitize_for_csv(new)
                return new
            return value

        df = df.map(_scrub)

    df.to_csv(path, index=False, encoding=read.encoding)
    return {
        "file": str(path),
        "rows_before": before,
        "rows_dropped": dropped,
        "cells_scrubbed": scrubbed_cells,
    }


def _scrub_text_file(path: Path, erased_texts: List[str]) -> Dict[str, Any]:
    """Replace erased text spans inside a plain-text/markdown artifact."""
    try:
        content = path.read_text(encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        return {"file": str(path), "status": f"skipped ({exc})"}
    new = content
    for needle in erased_texts:
        if needle and needle in new:
            new = new.replace(needle, "[ERASED]")
    if new != content:
        path.write_text(new, encoding="utf-8")
        return {"file": str(path), "status": "scrubbed"}
    return {"file": str(path), "status": "no match"}


def erase_respondent(
    project_dir: Union[str, Path],
    response_id: str,
    *,
    store_path: Optional[Union[str, Path]] = None,
    purge_backups: bool = False,
) -> Dict[str, Any]:
    """Erase one respondent from a project's store and all its derived artifacts.

    `project_dir` is the run/project directory (holds the .qnw, CSVs, report,
    caches). `store_path` defaults to `project_dir/project.qnw`.

    Steps: capture the respondent's text from the store (needed to scrub quote
    columns), delete from the store (FKs cascade excerpts + applications), rewrite
    run CSVs, scrub the markdown report, delete embedding caches, VACUUM the store
    so the deleted rows leave no readable bytes behind, optionally purge the
    backups that still hold the un-erased data, and append a hashed audit event.
    Returns a report of everything touched.

    `purge_backups=False` (the default) keeps the pre-erase safety net; the report
    still lists it under `backups_retaining_data` so a caller can offer the step.
    """
    from core.project import Project

    project_dir = Path(project_dir)
    store_path = Path(store_path) if store_path else project_dir / "project.qnw"
    report: Dict[str, Any] = {"response_id_hash": _sha256(str(response_id)), "artifacts": []}

    # Safety net (v3.8): erasure is irreversible by design, but "I erased the
    # wrong id" shouldn't be. The backup contains the un-erased data, so a real
    # erasure request must also purge project_backups/ — noted in the UI.
    from core.backups import backup_store
    backup = backup_store(store_path, reason="pre_erase")
    report["backup"] = str(backup) if backup else None

    # 1. Capture the erased text BEFORE deleting, so quote columns can be scrubbed.
    erased_texts: List[str] = []
    store_counts: Dict[str, int] = {}
    if store_path.exists():
        with Project.open(store_path) as proj:
            for src in proj.list_sources():
                if str(src.metadata.get("response_id", "")) == str(response_id):
                    if src.raw_text:
                        erased_texts.append(src.raw_text)
            store_counts = proj.delete_by_response_id(str(response_id))
            # Recorded THAT it happened, by hash, like the audit log file.
            proj.log_event("respondent_erased", "A respondent's data was erased",
                           target_type="respondent", target_id=report["response_id_hash"],
                           detail={"removed": store_counts})
        report["store"] = store_counts

    # 2. Rewrite CSV artifacts.
    for csv_path in sorted(project_dir.glob("*.csv")):
        report["artifacts"].append(
            _rewrite_csv_dropping_response(csv_path, response_id, erased_texts)
        )

    # 3. Scrub the markdown report (quotes have no id to filter on).
    for md_path in sorted(project_dir.glob("*.md")):
        report["artifacts"].append(_scrub_text_file(md_path, erased_texts))

    # 4. Delete derived-data caches — wholesale, never surgically.
    #
    # Embeddings are row-aligned arrays: there is no way to remove one row and
    # keep the file meaningful. The inference cache (sentiment and theme scores,
    # added in v4.9) cannot be filtered either, and for a sharper reason — its
    # keys are SHA-256 hashes of response text. Finding this respondent's rows
    # would mean hashing their text, which is the thing being erased, and a hash
    # of a known string is a lookup rather than anonymisation. So the whole file
    # goes. Deleting it also sidesteps the free-page residue that step 5 exists
    # to handle for the store.
    caches_removed: List[str] = []
    cache_globs = ["embeddings.npy", "embeddings_*.npy", ".embedding_cache/*.npy",
                   INFERENCE_CACHE_FILENAME, f"*/{INFERENCE_CACHE_FILENAME}"]
    for pattern in cache_globs:
        for cache_path in project_dir.glob(pattern):
            try:
                cache_path.unlink()
                caches_removed.append(cache_path.name)
            except Exception:  # noqa: BLE001 - a locked cache is regenerable; keep going
                pass
    report["caches_removed"] = caches_removed

    # 5. VACUUM — this is not housekeeping.
    #
    # SQLite marks a deleted row's page free and reuses it later, if ever. Until
    # then the erased response is still legible in the file: `strings project.qnw`
    # prints it back, and so does anything that reads free pages. Measured on a
    # two-response store — text present in the bytes after the delete, absent
    # after VACUUM. For a feature whose whole purpose is honoring a withdrawal of
    # consent, that is the gap between the claim and the fact.
    report["vacuumed"] = _vacuum(store_path) if store_path.exists() else False

    # 6. Backups — the pre-erase snapshot still holds the un-erased respondent.
    report["backups_retaining_data"] = [str(p) for p in list_backups(store_path)]
    report["backups_purged"] = False
    if purge_backups:
        backup_dir = Path(store_path).parent / BACKUP_DIR_NAME
        if backup_dir.is_dir():
            shutil.rmtree(backup_dir, ignore_errors=True)
        report["backups_purged"] = not backup_dir.is_dir()
        if report["backups_purged"]:
            report["backups_retaining_data"] = []

    # 7. Audit — record THAT it happened, hashed, never the identifier.
    _append_audit(project_dir, {
        "event": "erase_respondent",
        "erased_response_id_hash": report["response_id_hash"],
        "store_counts": store_counts,
        "caches_removed": len(caches_removed),
        "vacuumed": report["vacuumed"],
        "backups_purged": report["backups_purged"],
    })
    report["audit_log"] = str(project_dir / "audit_log.jsonl")
    return report


def purge_project(project_dir: Union[str, Path]) -> Dict[str, Any]:
    """Delete an entire project directory (store, run artifacts, caches).

    The nuclear option behind a typed confirmation in the UI. Same honest posture
    on secure deletion as erase_respondent: this unlinks files, it does not shred
    them.
    """
    import shutil

    project_dir = Path(project_dir)
    if not project_dir.exists():
        return {"status": "not found", "path": str(project_dir)}
    file_count = sum(1 for _ in project_dir.rglob("*") if _.is_file())
    shutil.rmtree(project_dir)
    return {"status": "purged", "path": str(project_dir), "files_removed": file_count}
