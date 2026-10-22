"""
Tests for the analytical core (Phase 3): frequency, co-occurrence, code×descriptor.

Pure functions tested on hand-built frames, plus an integration test that feeds
them from a populated Project (Project.coding_table / descriptor_table).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analysis.frequency import code_frequency
from analysis.cooccurrence import cooccurrence_matrix, cooccurrence_jaccard
from analysis.crosstab import code_by_descriptor
from core.model import (
    Code, CodeApplication, Descriptor, DescriptorField, Source,
)
from core.project import Project


def _coding_df():
    # excerpt/source e1/s1: A,B ; e2/s2: A ; e3/s3: B,C ; e4/s4: A,B
    rows = [
        ("e1", "s1", "A"), ("e1", "s1", "B"),
        ("e2", "s2", "A"),
        ("e3", "s3", "B"), ("e3", "s3", "C"),
        ("e4", "s4", "A"), ("e4", "s4", "B"),
    ]
    return pd.DataFrame(
        [{"excerpt_id": e, "source_id": s, "code_id": c, "code_name": c} for e, s, c in rows]
    )


def _descriptor_df():
    return pd.DataFrame([
        {"source_id": "s1", "key": "program", "value": "Nursing"},
        {"source_id": "s2", "key": "program", "value": "Nursing"},
        {"source_id": "s3", "key": "program", "value": "Finance"},
        {"source_id": "s4", "key": "program", "value": "Finance"},
    ])


class TestFrequency:
    def test_counts_and_drillback(self):
        out = code_frequency(_coding_df())
        by_code = out.set_index("code_name")
        assert by_code.loc["A", "n"] == 3 and by_code.loc["B", "n"] == 3 and by_code.loc["C", "n"] == 1
        assert sorted(by_code.loc["A", "excerpt_ids"]) == ["e1", "e2", "e4"]
        # sorted descending
        assert out.iloc[0]["n"] >= out.iloc[-1]["n"]

    def test_empty(self):
        out = code_frequency(pd.DataFrame(columns=["code_id", "code_name", "excerpt_id"]))
        assert out.empty


class TestCooccurrence:
    def test_matrix_diagonal_and_pairs(self):
        m, drill = cooccurrence_matrix(_coding_df())
        assert m.at["A", "A"] == 3 and m.at["B", "B"] == 3 and m.at["C", "C"] == 1
        assert m.at["A", "B"] == 2 and m.at["B", "A"] == 2      # e1, e4
        assert m.at["B", "C"] == 1                                # e3
        assert m.at["A", "C"] == 0
        assert sorted(drill[("A", "B")]) == ["e1", "e4"]

    def test_jaccard(self):
        m, _ = cooccurrence_matrix(_coding_df())
        j = cooccurrence_jaccard(m)
        assert j.at["A", "A"] == 1.0
        # A-B: 2 / (3 + 3 - 2) = 0.5
        assert abs(j.at["A", "B"] - 0.5) < 1e-9
        # A-C: 0 / (3 + 1 - 0) = 0.0
        assert j.at["A", "C"] == 0.0


class TestCrosstab:
    def test_distinct_source_counts_by_program(self):
        table, drill = code_by_descriptor(_coding_df(), _descriptor_df(), "program")
        # A: Nursing s1,s2 = 2 ; Finance s4 = 1
        assert table.loc["A", "Nursing"] == 2 and table.loc["A", "Finance"] == 1
        assert sorted(drill[("A", "Nursing")]) == ["s1", "s2"]

    def test_group_size_normalization(self):
        # group sizes: Nursing = {s1,s2}=2, Finance = {s3,s4}=2
        table, _ = code_by_descriptor(_coding_df(), _descriptor_df(), "program", normalize="group_size")
        assert table.loc["A", "Nursing"] == 100.0   # 2/2
        assert table.loc["A", "Finance"] == 50.0     # 1/2

    def test_ordinal_field_orders_columns(self):
        coding = pd.DataFrame([
            {"excerpt_id": "e1", "source_id": "s1", "code_id": "A", "code_name": "A"},
            {"excerpt_id": "e2", "source_id": "s2", "code_id": "A", "code_name": "A"},
        ])
        desc = pd.DataFrame([
            {"source_id": "s1", "key": "class_year", "value": "Senior"},
            {"source_id": "s2", "key": "class_year", "value": "Freshman"},
        ])
        field = DescriptorField(key="class_year", dtype="ordinal",
                                ordered_levels=["Freshman", "Sophomore", "Junior", "Senior"])
        table, _ = code_by_descriptor(coding, desc, "class_year", field=field)
        assert list(table.columns) == ["Freshman", "Senior"]  # ordinal order, not alphabetical


class TestAnalysisFromProject:
    def test_end_to_end_via_project_tables(self, tmp_path):
        with Project.create(tmp_path / "a.qnw") as p:
            for sid, prog in [("s1", "Nursing"), ("s2", "Finance")]:
                src = Source(source_id=sid, type="survey_response", raw_text="text " + sid)
                p.add_source(src)
                eid = p.add_whole_response_excerpt(src)
                p.set_descriptor(Descriptor(source_id=sid, key="program", value=prog))
                for code in ("A", "B"):
                    if not any(c.code_id == code for c in p.get_codebook()):
                        p.add_code(Code(code_id=code, name=code))
                    p.apply_code(CodeApplication(application_id="", excerpt_id=eid, code_id=code))
            coding = p.coding_table()
            desc = p.descriptor_table()

        freq = code_frequency(coding)
        assert set(freq["code_name"]) == {"A", "B"}
        m, _ = cooccurrence_matrix(coding)
        assert m.at["A", "B"] == 2  # both codes on both sources' excerpts
        table, _ = code_by_descriptor(coding, desc, "program")
        assert table.loc["A", "Nursing"] == 1 and table.loc["A", "Finance"] == 1


class TestJoinDescriptors:
    """The mixed-methods frame: every coding with every descriptor beside it.

    `code_by_descriptor` answers one question about one descriptor; this is what
    a general chart builder needs to plot a theme against several at once.
    """

    def _codings(self):
        return pd.DataFrame({
            "source_id": ["s1", "s1", "s2", "s3"],
            "code_name": ["Cost", "Advising", "Cost", "Belonging"],
            "weight": [1.0, 1.0, 2.0, 1.0],
        })

    def _descriptors(self):
        return pd.DataFrame({
            "source_id": ["s1", "s1", "s2", "s2"],
            "key": ["class_year", "first_gen", "class_year", "first_gen"],
            "value": ["First-year", "Yes", "Senior", "No"],
        })

    def test_each_descriptor_becomes_a_column(self):
        from analysis.crosstab import join_descriptors

        joined = join_descriptors(self._codings(), self._descriptors())

        assert {"class_year", "first_gen"} <= set(joined.columns)
        first_year = joined[joined["source_id"] == "s1"]
        assert set(first_year["class_year"]) == {"First-year"}

    def test_a_source_with_no_descriptors_keeps_its_codings(self):
        """A left join, deliberately — an inner one would silently shrink a
        frequency chart by dropping respondents who skipped the demographics."""
        from analysis.crosstab import join_descriptors

        joined = join_descriptors(self._codings(), self._descriptors())

        assert len(joined) == 4
        s3 = joined[joined["source_id"] == "s3"].iloc[0]
        assert pd.isna(s3["class_year"])

    def test_a_descriptor_named_like_a_coding_column_does_not_overwrite_it(self):
        from analysis.crosstab import join_descriptors

        descriptors = pd.DataFrame({
            "source_id": ["s1"], "key": ["weight"], "value": ["heavy"]})

        joined = join_descriptors(self._codings(), descriptors)

        assert joined["weight"].tolist() == [1.0, 1.0, 2.0, 1.0]
        assert joined["descriptor_weight"].tolist()[0] == "heavy"

    def test_no_descriptors_returns_the_codings_unchanged(self):
        from analysis.crosstab import join_descriptors

        codings = self._codings()
        joined = join_descriptors(codings, pd.DataFrame(columns=["source_id", "key", "value"]))

        pd.testing.assert_frame_equal(joined, codings)
