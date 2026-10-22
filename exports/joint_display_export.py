#!/usr/bin/env python
"""
Joint display exports — Word and Excel (v4.6).

A joint display is built to leave the program. Its whole purpose is to be the
table in a findings chapter or the figure in a methods paper, so the export is
not an afterthought here — it is the deliverable, and the on-screen view is the
draft of it.

Two shapes, for the same reason `exports/framework_export.py` has two. **Word**
is the publishable table: subgroups across, themes down, an evidence column and
the analyst's integration statement, with the caveats printed beneath it rather
than left in the software. **Excel** is the working shape, and like every other
workbook here it never carries verbatim response text, so it stays email-safe.

**The caveats travel with the table.** Small cells, very unequal subgroups, and a
counts-only display are all printed under the Word table, because this document
is going into a chapter and the person reading it there will not have the
software open to be warned by it.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Union

import pandas as pd

from analysis.joint_display import JointDisplay, display_caveats
from core.manifest import PACKAGE_VERSION


def build_joint_display_docx(
    display: JointDisplay,
    out_path: Union[str, Path],
    *,
    include_quotes: bool = True,
    title: str = "Joint Display",
) -> Path:
    """Write the joint display as a Word table. Returns the path.

    Quotes are verbatim response text, so they are opt-in — the same rule every
    other export here follows. Turning them off leaves a crosstab, which the
    caveats will say.
    """
    from docx import Document
    from docx.shared import Pt

    out_path = Path(out_path)
    doc = Document()
    doc.add_heading(title, level=0)

    stamp = doc.add_paragraph()
    run = stamp.add_run(
        f"Generated {datetime.now().strftime('%B %d, %Y')} · QualSafe "
        f"{PACKAGE_VERSION} · themes by {display.descriptor_key} · "
        f"{len(display.codes)} theme(s) × {len(display.values)} subgroup(s) · "
        f"{'percentages within subgroup' if display.normalized else 'raw counts'}")
    run.font.size = Pt(9)

    if not display.codes:
        doc.add_paragraph(
            "No themes overlap this descriptor, so there is nothing to display.")
        doc.save(out_path)
        return out_path

    columns = ["Theme"] + [str(v) for v in display.values]
    if include_quotes:
        columns.append("Illustrative quote")
    columns.append("Integration")

    table = doc.add_table(rows=1, cols=len(columns))
    table.style = "Light Grid Accent 1"
    for cell, heading in zip(table.rows[0].cells, columns):
        cell.text = heading
        for paragraph in cell.paragraphs:
            for piece in paragraph.runs:
                piece.bold = True

    for code in display.codes:
        row = table.add_row().cells
        row[0].text = code
        for index, value in enumerate(display.values, start=1):
            row[index].text = display.cell(code, value).quantitative()
        offset = len(display.values) + 1
        if include_quotes:
            row[offset].text = _first_quote(display, code)
            offset += 1
        row[offset].text = display.inferences.get(code, "")

    totals = display.group_totals()
    if totals:
        note = doc.add_paragraph()
        piece = note.add_run(
            "Subgroup sizes: "
            + ", ".join(f"{value} n={totals[value]}" for value in display.values))
        piece.font.size = Pt(9)

    caveats = display_caveats(display)
    if include_quotes:
        # "No quotes attached" is about the display, not this document.
        caveats = [c for c in caveats if "No quotes are attached" not in c]
    if caveats:
        doc.add_heading("Read alongside", level=2)
        for caveat in caveats:
            doc.add_paragraph(caveat, style="List Bullet")

    doc.save(out_path)
    return out_path


def build_joint_display_workbook(
    display: JointDisplay,
    out_path: Union[str, Path],
) -> Path:
    """Write the display to Excel: the table, the subgroup sizes, the caveats.

    Never contains verbatim response text — the email-safe shape, consistent
    with `exports/excel_workbook.py`.
    """
    out_path = Path(out_path)

    frame = display.to_frame()
    if "Evidence" in frame.columns:
        frame = frame.drop(columns=["Evidence"])

    totals = display.group_totals()
    sizes = pd.DataFrame(
        [{"subgroup": value, "respondents": totals.get(value, 0)}
         for value in display.values],
        columns=["subgroup", "respondents"])

    caveats = pd.DataFrame(
        {"read alongside": display_caveats(display) or ["None."]})

    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        if frame.empty:
            pd.DataFrame({"note": ["No themes overlap this descriptor."]}).to_excel(
                writer, sheet_name="Joint display", index=False)
        else:
            frame.to_excel(writer, sheet_name="Joint display", index=False)
        sizes.to_excel(writer, sheet_name="Subgroup sizes", index=False)
        caveats.to_excel(writer, sheet_name="Caveats", index=False)
    return out_path


def _first_quote(display: JointDisplay, code: str) -> str:
    """One quote for the theme's row, labelled with the subgroup it came from.

    A quote with no subgroup attached is unreadable in a joint display: the whole
    device is about which group said what.
    """
    for value in display.values:
        quotes = display.cell(code, value).quotes
        if quotes:
            return f"[{value}] {quotes[0]}"
    return ""
