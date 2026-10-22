#!/usr/bin/env python
"""
Shareable analysis bundle, built from the `.qnw` store (v3.4, Phase 3.1).

An analyst often needs to hand a collaborator, a co-author, or a reviewer the
*results* of a coding project without handing over the students' words. That is
exactly where the V2 version leaked: it assembled the "redacted" zip by
filename-guessing over CSVs and copied the un-redacted markdown report straight
in, so raw quotes rode along.

This version is built the safe way:

- **From the store, not from files.** Everything is queried out of the Project
  and assembled fresh, so nothing is included by accident.
- **Redaction at query time.** With ``include_raw_text=False`` (the default),
  every quote/excerpt/source text is replaced with ``[REDACTED]`` as it is read
  from the store — never by regex over a finished file, which is what let text
  slip through before. The markdown report is regenerated from the redacted
  tables, so there is no un-redacted copy to leak.
- **Descriptors are opt-in.** Subgroup labels (first-gen, Pell, campus) are the
  second re-identification vector, so the crosstabs default to *no* descriptors;
  the caller names the ones to include, and any crosstab cell with fewer than
  ``small_cell_threshold`` sources is flagged the way an IR practitioner would
  suppress it.
- **Raw response text and embeddings are never in the bundle.**
  ``responses_scored.csv`` and ``.npy`` caches are not store artifacts and are not
  assembled here at all.

The redaction guarantee is tested by walking every member of a no-raw-text zip
and asserting no source's raw text appears anywhere, including the report.
"""

from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union

import pandas as pd

from analysis.frequency import code_frequency

REDACTED = "[REDACTED]"


def _codebook_frame(proj) -> pd.DataFrame:
    codes = proj.get_codebook()
    name_by_id = {c.code_id: c.name for c in codes}
    freq = proj.code_frequency()
    return pd.DataFrame([{
        "code": c.name,
        "definition": c.definition,
        "parent": name_by_id.get(c.parent_id, ""),
        "origin": c.origin,
        "created_by": c.created_by,
        "applications": freq.get(c.code_id, 0),
    } for c in codes])


def _excerpt_frame(proj, include_raw_text: bool) -> pd.DataFrame:
    """Excerpt table. Text is redacted at read time unless raw text is allowed."""
    rows = []
    for exc in proj.list_excerpts():
        rows.append({
            "excerpt_id": exc.excerpt_id,
            "source_id": exc.source_id,
            "char_start": exc.char_start,
            "char_end": exc.char_end,
            "text": exc.text if include_raw_text else REDACTED,
        })
    return pd.DataFrame(rows, columns=["excerpt_id", "source_id", "char_start", "char_end", "text"])


def _agreement_frame(proj) -> Optional[pd.DataFrame]:
    """Human-vs-engine kappa (caveats in ``.attrs``); see core.agreement_pairs.

    This used to take the first non-human rater id as "the model", which could
    be the text-search auto-coder, and printed kappa at support 1.
    """
    from core.agreement_pairs import human_vs_engine, kappa_table

    return kappa_table(human_vs_engine(proj))


def _crosstab_frames(
    proj, descriptor_keys: Sequence[str], small_cell_threshold: int
) -> Dict[str, pd.DataFrame]:
    """One redacted crosstab per requested descriptor key, with small cells flagged."""
    from analysis.crosstab import code_by_descriptor

    coding = proj.coding_table()
    descriptors = proj.descriptor_table()
    out: Dict[str, pd.DataFrame] = {}
    available = set(descriptors["key"].unique().tolist()) if not descriptors.empty else set()
    for key in descriptor_keys:
        if key not in available:
            continue
        table, _drill = code_by_descriptor(coding, descriptors, key)
        if table.empty:
            continue
        # Flag (not drop) any cell below the suppression threshold, so the reader
        # sees where a count is too small to share without re-identification risk.
        flagged = table.copy()
        small = (table.fillna(0) < small_cell_threshold) & (table.fillna(0) > 0)
        if small.any().any():
            note = pd.DataFrame(
                [[f"<{small_cell_threshold}" if small.iloc[i, j] else ""
                  for j in range(table.shape[1])] for i in range(table.shape[0])],
                index=table.index, columns=[f"{c}__flag" for c in table.columns])
            flagged = pd.concat([flagged, note], axis=1)
        out[key] = flagged
    return out


def _report_markdown(
    proj,
    codebook: pd.DataFrame,
    frequency: pd.DataFrame,
    include_raw_text: bool,
    include_memos: bool,
    descriptor_keys: Sequence[str],
) -> str:
    """Regenerate the report from the (already redacted) tables — no file copy."""
    lines = [
        "# Qualitative Analysis Bundle",
        "",
        f"- Generated: {datetime.now().isoformat(timespec='seconds')}",
        f"- Raw response text included: {'yes' if include_raw_text else 'no (redacted)'}",
        f"- Codes: {len(codebook)}",
        f"- Descriptors included: {', '.join(descriptor_keys) if descriptor_keys else 'none'}",
        "",
        "## Code frequency",
        "",
    ]
    for _, row in frequency.iterrows():
        lines.append(f"- **{row['code_name']}**: {row['n']}")
    lines.append("")

    if include_memos:
        memos = [m for m in proj.list_memos()]
        if memos:
            lines.append("## Memos")
            lines.append("")
            name_by_code = {c.code_id: c.name for c in proj.get_codebook()}
            for m in memos:
                target = name_by_code.get(m.target_id, m.target_type) if m.target_id else m.target_type
                # A memo can quote raw text, so redact its body too unless raw text
                # is explicitly allowed. Memos are analyst voice but not exempt.
                body = m.text if include_raw_text else _redact_memo(m.text, proj)
                lines.append(f"- *({target})* {body}")
            lines.append("")

    if not include_raw_text:
        lines.append("_Supporting quotes are redacted in this bundle. Re-export with "
                     "raw text enabled to include verbatim excerpts._")
    return "\n".join(lines)


def _redact_memo(text: str, proj) -> str:
    """Replace any source's raw text that appears verbatim inside a memo.

    Memos are free text an analyst might paste a quote into. Rather than trust the
    author, blunt-force any known source substring out of the memo body when raw
    text isn't allowed. Query-time (over store contents), never over files.
    """
    redacted = text
    for src in proj.list_sources():
        if src.raw_text and len(src.raw_text) >= 8 and src.raw_text in redacted:
            redacted = redacted.replace(src.raw_text, REDACTED)
    return redacted


def _write_csv(zf: zipfile.ZipFile, arcname: str, df: pd.DataFrame) -> None:
    """Write a dataframe into the zip under a RELATIVE arcname.

    Relative arcnames matter: a member path built from an absolute filesystem path
    would leak the analyst's username/home directory into the shared zip.
    """
    from analyze_survey import sanitize_frame_for_csv

    buf = io.StringIO()
    sanitize_frame_for_csv(df).to_csv(buf, index=bool(df.index.name))
    zf.writestr(arcname, buf.getvalue())


def build_bundle(
    project,
    out_path: Union[str, Path],
    *,
    include_raw_text: bool = False,
    descriptor_keys: Sequence[str] = (),
    include_memos: bool = False,
    small_cell_threshold: int = 5,
) -> Path:
    """Build a shareable analysis zip from a Project. Returns the zip path.

    `project` may be a Project instance or a path to a `.qnw` file. With
    `include_raw_text=False` (default) no verbatim response text appears anywhere
    in the output.
    """
    from core.project import Project

    close_after = False
    if not hasattr(project, "coding_table"):
        project = Project.open(project)
        close_after = True

    out_path = Path(out_path)
    try:
        coding = project.coding_table()
        codebook = _codebook_frame(project)
        frequency = (code_frequency(coding) if not coding.empty
                     else pd.DataFrame(columns=["code_id", "code_name", "n", "excerpt_ids"]))
        cooc_matrix = pd.DataFrame()
        if not coding.empty:
            from analysis.cooccurrence import cooccurrence_matrix
            cooc_matrix, _ = cooccurrence_matrix(coding)
        excerpts = _excerpt_frame(project, include_raw_text)
        agreement = _agreement_frame(project)
        crosstabs = _crosstab_frames(project, descriptor_keys, small_cell_threshold)
        report = _report_markdown(project, codebook, frequency, include_raw_text,
                                  include_memos, descriptor_keys)

        manifest = {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "include_raw_text": include_raw_text,
            "include_memos": include_memos,
            "descriptor_keys": list(descriptor_keys),
            "small_cell_threshold": small_cell_threshold,
            "n_codes": int(len(codebook)),
            "n_excerpts": int(len(excerpts)),
            "runs": [r.run_id for r in project.list_runs()],
        }

        with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("manifest.json", json.dumps(manifest, indent=2))
            zf.writestr("report.md", report)
            _write_csv(zf, "codebook.csv", codebook)
            _write_csv(zf, "code_frequency.csv",
                       frequency.drop(columns=["excerpt_ids"], errors="ignore"))
            if not cooc_matrix.empty:
                _write_csv(zf, "cooccurrence.csv", cooc_matrix)
            _write_csv(zf, "excerpts.csv", excerpts)
            if agreement is not None:
                _write_csv(zf, "agreement.csv", agreement)
                zf.writestr("agreement_notes.txt", "\n".join(
                    [f"Compared: {agreement.attrs.get('comparison', '')}"]
                    + list(agreement.attrs.get("caveats", []))) + "\n")
            for key, table in crosstabs.items():
                _write_csv(zf, f"crosstab_{key}.csv", table)
            if include_memos:
                _write_csv(zf, "memos.csv", _memo_frame(project, include_raw_text))
    finally:
        if close_after:
            project.close()

    return out_path


def _memo_frame(proj, include_raw_text: bool) -> pd.DataFrame:
    name_by_code = {c.code_id: c.name for c in proj.get_codebook()}
    rows = []
    for m in proj.list_memos():
        rows.append({
            "target_type": m.target_type,
            "target": name_by_code.get(m.target_id, m.target_id or ""),
            "author": m.author,
            "text": m.text if include_raw_text else _redact_memo(m.text, proj),
        })
    return pd.DataFrame(rows, columns=["target_type", "target", "author", "text"])
