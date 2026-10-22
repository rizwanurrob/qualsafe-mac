#!/usr/bin/env python
"""
Whole-project archive: export a project folder as one .zip, import it elsewhere
(v3.9.1).

A `.qnw` is already a single self-contained SQLite file, but a *project* is the
folder around it — the store plus its run outputs (scored CSVs, the run report,
run manifests, any exported JSON/YAML). This packages that folder into one zip an
analyst can hand to a colleague or carry to another installation, and unpacks it
on the far side ready to open.

Deliberately excluded from the archive:
- `project_backups/` — may hold a *pre-erasure* copy of a respondent who has since
  been erased; shipping it would re-introduce data the analyst deleted.
- embedding caches (`.embedding_cache/`, `*.npy`) — large and regenerable.
- `__pycache__` / `*.pyc` — build noise.

Everything else (the store and its human-readable outputs) travels, so the
recipient gets the same analysis, and — via `core/reconstruct.py` — can rebuild
the responses to code independently.
"""

from __future__ import annotations

import io
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Optional, Union

# Directory / file names never included in an archive, matched at any depth.
EXCLUDE_NAMES = {
    "project_backups", ".embedding_cache", "__pycache__", ".DS_Store",
}
EXCLUDE_SUFFIXES = {".npy", ".pyc"}


def _excluded(rel_parts: tuple[str, ...], name: str) -> bool:
    if name in EXCLUDE_NAMES or any(part in EXCLUDE_NAMES for part in rel_parts):
        return True
    return any(name.endswith(sfx) for sfx in EXCLUDE_SUFFIXES)


def export_project_archive(store_path: Union[str, Path]) -> bytes:
    """Zip the project folder that contains `store_path`; return the zip bytes.

    The archive's single top-level folder is the project directory's name, so it
    extracts to a self-describing folder. Raises FileNotFoundError if the store
    (or its folder) is missing.
    """
    store_path = Path(store_path)
    if not store_path.exists():
        raise FileNotFoundError(f"Project store not found: {store_path}")
    project_dir = store_path.parent
    top = project_dir.name or "project"

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(project_dir.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(project_dir)
            if _excluded(rel.parts[:-1], path.name):
                continue
            zf.write(path, arcname=str(Path(top) / rel))
    return buf.getvalue()


def _safe_extract(zf: zipfile.ZipFile, dest: Path) -> None:
    """Extract `zf` into `dest`, refusing any member that escapes it (zip-slip)."""
    dest = dest.resolve()
    for member in zf.namelist():
        target = (dest / member).resolve()
        if dest != target and dest not in target.parents:
            raise ValueError(f"Unsafe path in archive: {member}")
    zf.extractall(dest)


def import_project_archive(
    archive: Union[str, Path, bytes], dest_parent: Union[str, Path],
    *, name_hint: str = "project",
) -> Path:
    """Extract a project archive under `dest_parent`; return the `.qnw` path.

    Creates ``dest_parent / imported_<name_hint>_<timestamp>/`` and unpacks into
    it, then locates the store. Works whether the zip wraps its files in a top
    folder (as `export_project_archive` writes) or holds them at the root. Raises
    ValueError if no `.qnw` is found, or on an unsafe (zip-slip) archive.
    """
    dest_parent = Path(dest_parent)
    dest_parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_hint = "".join(ch if ch.isalnum() else "_" for ch in name_hint).strip("_") or "project"
    target = dest_parent / f"imported_{safe_hint}_{stamp}"
    target.mkdir(parents=True, exist_ok=False)

    data = archive if isinstance(archive, bytes) else Path(archive).read_bytes()
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        _safe_extract(zf, target)

    stores = sorted(target.rglob("*.qnw"))
    if not stores:
        raise ValueError("No project store (.qnw) found in the archive.")
    # Prefer a store literally named project.qnw when several exist (e.g. an odd
    # nested export); otherwise the first by path.
    preferred: Optional[Path] = next((s for s in stores if s.name == "project.qnw"), None)
    return preferred or stores[0]
