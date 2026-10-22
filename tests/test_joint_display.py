"""
Tests for joint displays — the mixed-methods artifact (v4.6).

A joint display is built to leave the program: it is the table in a findings
chapter. That makes two things load-bearing, and both are asserted here.

**The numbers must be the project's own numbers.** A display that computed its
own counts would be a second answer to a question `analysis/crosstab.py` already
answers, and the two would drift silently.

**The caveats must travel with the table.** Small cells and unequal subgroups
are exactly the failures a joint display makes invisible — a percentage in a
published table has no denominator attached unless someone puts one there.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analysis.crosstab import code_by_descriptor
from analysis.joint_display import (
    SMALL_CELL, build_joint_display, display_caveats)


@pytest.fixture()
def coding():
    """Six respondents. Cost is on three of them, Advising on two."""
    return pd.DataFrame({
        "source_id": ["s1", "s2", "s3", "s4", "s1"],
        "code_name": ["Cost", "Cost", "Cost", "Advising", "Advising"],
    })


@pytest.fixture()
def descriptors():
    """s1-s3 are first-year, s4-s6 are seniors."""
    return pd.DataFrame({
        "source_id": ["s1", "s2", "s3", "s4", "s5", "s6"],
        "key": ["year"] * 6,
        "value": ["First", "First", "First", "Senior", "Senior", "Senior"],
    })


class TestTheNumbersAreTheProjectsNumbers:

    def test_counts_match_the_crosstab_exactly(self, coding, descriptors):
        """Not 'close to' — the same function, so the same answer."""
        display = build_joint_display(coding, descriptors, "year", normalize=False)
        raw, _drill = code_by_descriptor(coding, descriptors, "year")

        for code in display.codes:
            for value in display.values:
                assert display.cell(code, value).n == int(raw.loc[code, value])

    def test_a_normalized_display_still_carries_the_raw_count(self, coding, descriptors):
        """A percentage whose denominator has been thrown away is the thing a
        reviewer sends back."""
        display = build_joint_display(coding, descriptors, "year", normalize=True)

        cell = display.cell("Cost", "First")
        assert cell.n == 3
        assert cell.pct == pytest.approx(100.0)
        assert cell.quantitative() == "3 (100%)"

    def test_raw_mode_shows_no_percentage(self, coding, descriptors):
        display = build_joint_display(coding, descriptors, "year", normalize=False)
        assert display.cell("Cost", "First").quantitative() == "3"

    def test_themes_are_ordered_most_prevalent_first(self, coding, descriptors):
        """A display with forty rows in arbitrary order is not a display."""
        display = build_joint_display(coding, descriptors, "year")
        assert display.codes == ["Cost", "Advising"]

    def test_a_tie_is_broken_by_name_so_the_table_does_not_move(self, descriptors):
        """Two themes with the same total must not swap rows between exports of
        the same project — the document goes into a chapter."""
        tied = pd.DataFrame({
            "source_id": ["s1", "s2", "s3", "s4"],
            "code_name": ["Zeta", "Zeta", "Alpha", "Alpha"],
        })
        assert build_joint_display(tied, descriptors, "year").codes == ["Alpha", "Zeta"]

    def test_a_requested_code_order_is_honoured(self, coding, descriptors):
        display = build_joint_display(coding, descriptors, "year",
                                      codes=["Advising", "Cost"])
        assert display.codes == ["Advising", "Cost"]

    def test_an_empty_cell_reads_as_zero_rather_than_missing(self, coding, descriptors):
        display = build_joint_display(coding, descriptors, "year")
        cell = display.cell("Cost", "Senior")
        assert cell.n == 0 and cell.empty

    def test_no_overlap_produces_an_empty_display_not_an_error(self, descriptors):
        coding = pd.DataFrame({"source_id": ["zz"], "code_name": ["Cost"]})
        display = build_joint_display(coding, descriptors, "year")
        assert display.codes == [] and display.values == []


class TestQuotes:

    def test_without_a_project_the_display_is_counts_only(self, coding, descriptors):
        display = build_joint_display(coding, descriptors, "year")
        assert all(not display.cell(c, v).quotes
                   for c in display.codes for v in display.values)

    def test_quotes_come_from_the_store(self, coding, descriptors, tmp_path):
        from core.model import Source
        from core.project import Project

        store = tmp_path / "p.qnw"
        with Project.create(store) as project:
            for sid in ["s1", "s2", "s3", "s4", "s5", "s6"]:
                project.add_source(Source(source_id=sid, type="survey_response",
                                          raw_text=f"the words of {sid}", label="Q1",
                                          metadata={"response_id": sid}))

        with Project.open(store) as project:
            display = build_joint_display(coding, descriptors, "year",
                                          project=project)

        quotes = display.cell("Cost", "First").quotes
        assert quotes and quotes[0].startswith("the words of s")

    def test_a_source_that_cannot_be_read_is_skipped_not_faked(
            self, coding, descriptors):
        class _Broken:
            def get_source(self, source_id):
                raise RuntimeError("gone")

        display = build_joint_display(coding, descriptors, "year", project=_Broken())
        assert display.cell("Cost", "First").quotes == []


class TestCaveatsTravelWithTheTable:

    def test_a_small_cell_is_named_with_its_count(self, coding, descriptors):
        display = build_joint_display(coding, descriptors, "year")
        notes = display_caveats(display)

        assert any(f"fewer than {SMALL_CELL}" in n for n in notes)
        assert any("Cost × First" in n or "Advising" in n for n in notes)

    def test_very_unequal_subgroups_are_called_out(self):
        coding = pd.DataFrame({
            "source_id": [f"s{i}" for i in range(1, 12)],
            "code_name": ["Cost"] * 11,
        })
        descriptors = pd.DataFrame({
            "source_id": [f"s{i}" for i in range(1, 12)],
            "key": ["year"] * 11,
            "value": ["First"] + ["Senior"] * 10,
        })

        notes = display_caveats(build_joint_display(coding, descriptors, "year"))

        assert any("unequal" in n for n in notes)

    def test_a_counts_only_display_warns_that_size_confounds_it(
            self, coding, descriptors):
        notes = display_caveats(
            build_joint_display(coding, descriptors, "year", normalize=False))
        assert any("raw counts" in n for n in notes)

    def test_a_display_with_no_quotes_is_called_a_crosstab(self, coding, descriptors):
        notes = display_caveats(build_joint_display(coding, descriptors, "year"))
        assert any("without its qualitative half" in n for n in notes)


class TestTheTable:

    def test_the_frame_has_a_row_per_theme_and_a_column_per_subgroup(
            self, coding, descriptors):
        frame = build_joint_display(coding, descriptors, "year").to_frame()

        assert list(frame["Theme"]) == ["Cost", "Advising"]
        assert {"First", "Senior", "Evidence", "Inference"} <= set(frame.columns)

    def test_inferences_appear_in_the_table_when_supplied(self, coding, descriptors):
        display = build_joint_display(
            coding, descriptors, "year",
            inferences={"Cost": "concentrated among first-years"})

        frame = display.to_frame()
        assert (frame.loc[frame["Theme"] == "Cost", "Inference"].iloc[0]
                == "concentrated among first-years")

    def test_group_totals_count_distinct_respondents(self, coding, descriptors):
        display = build_joint_display(coding, descriptors, "year")
        assert display.group_totals()["First"] == 3


class TestExports:

    def _display(self, coding, descriptors, tmp_path):
        from core.model import Source
        from core.project import Project

        store = tmp_path / "p.qnw"
        with Project.create(store) as project:
            for sid in ["s1", "s2", "s3", "s4", "s5", "s6"]:
                project.add_source(Source(source_id=sid, type="survey_response",
                                          raw_text=f"the words of {sid}", label="Q1",
                                          metadata={"response_id": sid}))
        with Project.open(store) as project:
            return build_joint_display(
                coding, descriptors, "year", project=project,
                inferences={"Cost": "first-years carry this"})

    def test_the_word_table_is_a_real_docx(self, coding, descriptors, tmp_path):
        from exports.joint_display_export import build_joint_display_docx

        display = self._display(coding, descriptors, tmp_path)
        out = build_joint_display_docx(display, tmp_path / "jd.docx")

        assert out.exists()
        assert out.read_bytes()[:2] == b"PK", "a .docx is a zip archive"

    def test_the_word_table_carries_the_caveats(self, coding, descriptors, tmp_path):
        """The person reading it in a chapter does not have the software open."""
        from docx import Document

        from exports.joint_display_export import build_joint_display_docx

        display = self._display(coding, descriptors, tmp_path)
        build_joint_display_docx(display, tmp_path / "jd.docx")

        text = "\n".join(p.text for p in Document(tmp_path / "jd.docx").paragraphs)
        assert "Read alongside" in text
        assert "Subgroup sizes" in text

    def test_quotes_are_opt_in_in_word(self, coding, descriptors, tmp_path):
        from docx import Document

        from exports.joint_display_export import build_joint_display_docx

        display = self._display(coding, descriptors, tmp_path)
        build_joint_display_docx(display, tmp_path / "with.docx", include_quotes=True)
        build_joint_display_docx(display, tmp_path / "without.docx", include_quotes=False)

        def cells(path):
            return " ".join(c.text for t in Document(path).tables for r in t.rows
                            for c in r.cells)

        assert "the words of" in cells(tmp_path / "with.docx")
        assert "the words of" not in cells(tmp_path / "without.docx")

    def test_the_workbook_never_contains_response_text(
            self, coding, descriptors, tmp_path):
        """Like every other workbook here, it stays safe to email."""
        from exports.joint_display_export import build_joint_display_workbook

        display = self._display(coding, descriptors, tmp_path)
        out = build_joint_display_workbook(display, tmp_path / "jd.xlsx")

        sheets = pd.read_excel(out, sheet_name=None)
        blob = " ".join(frame.to_string() for frame in sheets.values())
        assert "the words of" not in blob
        assert {"Joint display", "Subgroup sizes", "Caveats"} == set(sheets)

    def test_the_workbook_keeps_the_integration_column(
            self, coding, descriptors, tmp_path):
        from exports.joint_display_export import build_joint_display_workbook

        display = self._display(coding, descriptors, tmp_path)
        out = build_joint_display_workbook(display, tmp_path / "jd.xlsx")

        table = pd.read_excel(out, sheet_name="Joint display")
        assert "first-years carry this" in table["Inference"].astype(str).tolist()

    def test_an_empty_display_still_exports(self, descriptors, tmp_path):
        from exports.joint_display_export import (
            build_joint_display_docx, build_joint_display_workbook)

        display = build_joint_display(
            pd.DataFrame({"source_id": ["zz"], "code_name": ["Cost"]}),
            descriptors, "year")

        assert build_joint_display_docx(display, tmp_path / "e.docx").exists()
        assert build_joint_display_workbook(display, tmp_path / "e.xlsx").exists()
