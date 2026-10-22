#!/usr/bin/env python
"""
Excel analysis workbook (v3.8.2, item 8.10).

One .xlsx with the analysis tables an IR analyst pastes into reports — codebook,
frequency, co-occurrence, and agreement — each on its own sheet.

**Never contains response text.** Excerpts and quotes are excluded entirely (not
redacted — absent), so this workbook is always safe to attach to an email. The
bundle and the Word report are the vehicles for (optionally) sharing quotes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Union

import pandas as pd

from analysis.frequency import code_frequency


def build_analysis_workbook(project, out_path: Union[str, Path]) -> Path:
    """Build the workbook from a Project (or a .qnw path). Returns the path."""
    from analyze_survey import sanitize_frame_for_csv
    from core.project import Project

    close_after = False
    if not hasattr(project, "coding_table"):
        project = Project.open(project)
        close_after = True

    out_path = Path(out_path)
    try:
        coding = project.coding_table()
        codes = project.get_codebook()
        name_by_id = {c.code_id: c.name for c in codes}
        codebook = pd.DataFrame([{
            "code": c.name, "definition": c.definition,
            "parent": name_by_id.get(c.parent_id, ""), "origin": c.origin,
        } for c in codes])

        with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
            sanitize_frame_for_csv(codebook).to_excel(writer, sheet_name="Codebook", index=False)

            if not coding.empty:
                freq = code_frequency(coding).drop(columns=["excerpt_ids"], errors="ignore")
                sanitize_frame_for_csv(freq).to_excel(writer, sheet_name="Frequency", index=False)

                from analysis.cooccurrence import cooccurrence_matrix
                matrix, _ = cooccurrence_matrix(coding)
                matrix.to_excel(writer, sheet_name="Co-occurrence")

            agreement = _agreement(project)
            if agreement is not None:
                sanitize_frame_for_csv(agreement).to_excel(
                    writer, sheet_name="Agreement", index=False)
                notes = [f"Compared: {agreement.attrs.get('comparison', '')}"]
                notes += list(agreement.attrs.get("caveats", []))
                pd.DataFrame({"note": notes}).to_excel(
                    writer, sheet_name="Agreement notes", index=False)
    finally:
        if close_after:
            project.close()
    return out_path


def _agreement(project):
    """Human-vs-engine kappa (caveats in ``.attrs``); see core.agreement_pairs."""
    from core.agreement_pairs import human_vs_engine, kappa_table

    return kappa_table(human_vs_engine(project))
