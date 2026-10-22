"""
Tests for Feature A (team distribution) and Feature B (wide-form cross-question).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.assignments import (
    coverage_report,
    merge_coder_samples,
    rater_id_for,
    split_coding_sample,
)
from core.ingest import reshape_wide_to_long
from core.model import Code, CodeApplication, Source
from core.project import Project, new_id


def _sample(n=12):
    return pd.DataFrame({
        "response_id": [str(i) for i in range(n)],
        "question_text": ["Q1"] * n,
        "response_text": [f"answer {i}" for i in range(n)],
        "human_labels": [""] * n,
        "coder_notes": [""] * n,
    })


# ── Feature A: team distribution ─────────────────────────────────────────────

class TestSplit:
    def test_partition_is_disjoint_and_complete(self):
        parts = split_coding_sample(_sample(12), ["Alice", "Bob", "Cara"], mode="partition")
        ids = {c: set(df["response_id"]) for c, df in parts.items()}
        # No overlap between any two coders.
        assert ids["Alice"] & ids["Bob"] == set()
        assert ids["Bob"] & ids["Cara"] == set()
        # Every response assigned exactly once.
        union = set().union(*ids.values())
        assert union == {str(i) for i in range(12)}

    def test_partition_balanced(self):
        parts = split_coding_sample(_sample(12), ["A", "B", "C"], mode="partition")
        sizes = sorted(len(df) for df in parts.values())
        assert sizes == [4, 4, 4]

    def test_overlap_shares_calibration_set(self):
        parts = split_coding_sample(_sample(12), ["A", "B"], mode="overlap", overlap_n=4)
        a, b = set(parts["A"]["response_id"]), set(parts["B"]["response_id"])
        shared = a & b
        assert len(shared) == 4  # the calibration set is coded by both
        # The rest is partitioned (disjoint outside the shared set).
        assert (a - shared) & (b - shared) == set()

    def test_labels_cleared_for_each_coder(self):
        parts = split_coding_sample(_sample(6), ["A"], mode="partition")
        assert (parts["A"]["human_labels"] == "").all()

    def test_rater_id_slug(self):
        assert rater_id_for("Alice Smith") == "human_alice_smith"
        assert rater_id_for("  ") == "human_coder"


class TestMergeAndCoverage:
    def _seed_store(self, path, n=6):
        with Project.create(path) as p:
            for i in range(n):
                src = Source(source_id=new_id("src"), type="survey_response",
                             raw_text=f"answer {i}", label="Q1",
                             metadata={"response_id": str(i), "question_text": "Q1"})
                p.add_source(src)
                p.add_whole_response_excerpt(src)
        return path

    def test_merge_imports_each_coder_as_distinct_rater(self, tmp_path):
        store = self._seed_store(tmp_path / "s.qnw")
        # Two coders code overlapping items.
        a = tmp_path / "a.csv"
        b = tmp_path / "b.csv"
        pd.DataFrame({"response_id": ["0", "1"], "human_labels": ["X", "Y"]}).to_csv(a, index=False)
        pd.DataFrame({"response_id": ["0", "2"], "human_labels": ["X", "Z"]}).to_csv(b, index=False)

        merge_coder_samples(store, {"Alice": a, "Bob": b}, question_text="Q1")
        with Project.open(store) as p:
            assert "human_alice" in p.rater_ids()
            assert "human_bob" in p.rater_ids()

    def test_coverage_reports_double_coded(self, tmp_path):
        store = self._seed_store(tmp_path / "s2.qnw")
        a = tmp_path / "a.csv"
        b = tmp_path / "b.csv"
        pd.DataFrame({"response_id": ["0", "1"], "human_labels": ["X", "Y"]}).to_csv(a, index=False)
        pd.DataFrame({"response_id": ["0", "2"], "human_labels": ["X", "Z"]}).to_csv(b, index=False)
        merge_coder_samples(store, {"Alice": a, "Bob": b}, question_text="Q1")

        cov = coverage_report(store)
        assert cov["n_double_coded"] == 1   # response 0 coded by both
        assert cov["n_excerpts_coded"] == 3  # 0, 1, 2
        assert cov["per_rater"]["human_alice"] == 2


# ── Feature B: wide-form cross-question ───────────────────────────────────────

class TestWideRespondentId:
    def _wide(self):
        return pd.DataFrame({
            "student_id": ["S1", "S2"],
            "Q_hard": ["cost was hard", "felt lost"],
            "Q_help": ["more aid", "a mentor"],
        })

    def test_reshape_emits_respondent_and_unique_response_id(self):
        long_df = reshape_wide_to_long(self._wide(), ["Q_hard", "Q_help"], id_column="student_id")
        assert "respondent_id" in long_df.columns
        assert "response_id" in long_df.columns
        # One respondent, two answers -> respondent repeats, response_id unique.
        s1 = long_df[long_df["respondent_id"] == "S1"]
        assert len(s1) == 2
        assert s1["response_id"].nunique() == 2  # no collision

    def test_reshape_without_id_column_uses_positional_respondent(self):
        wide = self._wide().drop(columns=["student_id"])
        long_df = reshape_wide_to_long(wide, ["Q_hard", "Q_help"])
        assert long_df["respondent_id"].nunique() == 2
        assert long_df["response_id"].nunique() == 4

    def test_respondent_id_reaches_store_and_coding_table(self, tmp_path):
        from core.populate import populate_project_store

        long_df = reshape_wide_to_long(self._wide(), ["Q_hard", "Q_help"], id_column="student_id")
        # Minimal coded frame: attach a fake zshot label so codings are created.
        long_df = long_df.assign(zshot_top_label="Theme", zshot_top_score=0.9)
        cfg = {"input": {}, "output": {}, "models": {},
               "zero_shot": {"labels": ["Theme"]}}
        store = populate_project_store(long_df, cfg, tmp_path / "w.qnw")
        with Project.open(store) as p:
            coding = p.coding_table()
            assert "respondent_id" in coding.columns
            assert set(coding["respondent_id"].dropna()) == {"S1", "S2"}
            grouped = p.sources_by_respondent()
            assert set(grouped) == {"S1", "S2"}
            assert len(grouped["S1"]) == 2  # both of S1's answers


class TestRespondentLevelCooccurrence:
    def test_group_col_respondent(self):
        from analysis.cooccurrence import cooccurrence_matrix

        # Two codes on DIFFERENT excerpts but the SAME respondent.
        coding = pd.DataFrame({
            "excerpt_id": ["e1", "e2"],
            "code_name": ["Cost", "Belonging"],
            "respondent_id": ["S1", "S1"],
        })
        # At excerpt level they don't co-occur (different excerpts).
        m_exc, _ = cooccurrence_matrix(coding, group_col="excerpt_id")
        assert m_exc.at["Cost", "Belonging"] == 0
        # At respondent level they do (same person raised both).
        m_resp, _ = cooccurrence_matrix(coding, group_col="respondent_id")
        assert m_resp.at["Cost", "Belonging"] == 1
