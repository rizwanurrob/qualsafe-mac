"""
Tests for wide->long ingestion reshaping and descriptor retention (v3).

Offline, no models. Covers core/ingest.reshape_wide_to_long,
core/ingest.parse_label_overrides, and the opt-in descriptor_columns retention
added to analyze_survey.prepare_dataset (which must be a no-op when unset).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.ingest import parse_label_overrides, reshape_wide_to_long
from analyze_survey import prepare_dataset


# ─────────────────────────────────────────────────────────────────────────────
# reshape_wide_to_long
# ─────────────────────────────────────────────────────────────────────────────

class TestReshapeWideToLong:
    def _wide(self) -> pd.DataFrame:
        return pd.DataFrame({
            "resp_id": ["r1", "r2"],
            "program": ["Nursing", "Finance"],
            "Q1_success": ["pass my classes", "get an internship"],
            "Q2_worry": ["feeling lost", "time management"],
        })

    def test_melts_each_question_column_to_rows(self):
        out = reshape_wide_to_long(
            self._wide(), question_columns=["Q1_success", "Q2_worry"],
            id_column="resp_id", descriptor_columns=["program"],
        )
        # 2 respondents x 2 questions = 4 rows
        assert len(out) == 4
        assert set(out["question_text"]) == {"Q1_success", "Q2_worry"}
        # v3.6 (Feature B): reshape also emits a unique per-answer response_id and a
        # respondent_id (for cross-question grouping), ahead of the carried columns.
        assert list(out.columns) == [
            "response_id", "respondent_id", "resp_id", "program",
            "question_text", "response_text"]
        # response_id is unique per answer; respondent_id repeats per person.
        assert out["response_id"].nunique() == 4
        assert out["respondent_id"].nunique() == 2

    def test_descriptor_and_id_carried_to_every_row(self):
        out = reshape_wide_to_long(
            self._wide(), question_columns=["Q1_success", "Q2_worry"],
            id_column="resp_id", descriptor_columns=["program"],
        )
        r1 = out[out["resp_id"] == "r1"]
        assert set(r1["program"]) == {"Nursing"}
        assert len(r1) == 2  # one row per question

    def test_question_label_override_renames_header(self):
        out = reshape_wide_to_long(
            self._wide(), question_columns=["Q1_success"],
            question_labels={"Q1_success": "What would a successful year look like?"},
        )
        assert set(out["question_text"]) == {"What would a successful year look like?"}

    def test_missing_columns_are_skipped(self):
        out = reshape_wide_to_long(self._wide(), question_columns=["Q1_success", "nope"])
        assert set(out["question_text"]) == {"Q1_success"}

    def test_no_present_columns_raises(self):
        with pytest.raises(ValueError, match="None of the selected question columns"):
            reshape_wide_to_long(self._wide(), question_columns=["nope", "also_nope"])

    def test_descriptor_not_duplicated_when_also_a_question(self):
        # A column can't be both a question and a descriptor; question wins.
        out = reshape_wide_to_long(
            self._wide(), question_columns=["Q1_success"],
            descriptor_columns=["Q1_success", "program"],
        )
        assert "program" in out.columns
        # Q1_success appears as the melted question, not as a carried descriptor col
        assert list(out.columns).count("Q1_success") == 0


# ─────────────────────────────────────────────────────────────────────────────
# parse_label_overrides
# ─────────────────────────────────────────────────────────────────────────────

class TestParseLabelOverrides:
    def test_parses_key_value(self):
        assert parse_label_overrides("Q1 :: What?") == {"Q1": "What?"}

    def test_ignores_blank_and_malformed_lines(self):
        text = "Q1 :: What?\n\nno delimiter here\nQ2 :: Why?"
        assert parse_label_overrides(text) == {"Q1": "What?", "Q2": "Why?"}

    def test_empty_returns_empty(self):
        assert parse_label_overrides("") == {}
        assert parse_label_overrides(None) == {}


# ─────────────────────────────────────────────────────────────────────────────
# prepare_dataset descriptor retention (opt-in; no-op when unset)
# ─────────────────────────────────────────────────────────────────────────────

class TestPrepareDatasetDescriptors:
    def _df(self) -> pd.DataFrame:
        return pd.DataFrame({
            "response_text": ["a long enough response", "another good response"],
            "program": ["Nursing", "Finance"],
            "pell": ["Yes", "No"],
        })

    def _config(self, descriptor_columns=None):
        cfg = {
            "input": {"text_column": "response_text", "question_column": None,
                      "id_column": None, "file_path": "dummy.csv"},
            "preprocessing": {"min_chars": 3, "drop_duplicates": False, "max_rows": None},
        }
        if descriptor_columns is not None:
            cfg["input"]["descriptor_columns"] = descriptor_columns
        return cfg

    def test_descriptors_retained_when_configured(self):
        out = prepare_dataset(self._df(), self._config(descriptor_columns=["program", "pell"]))
        assert "program" in out.columns and "pell" in out.columns
        assert out["program"].tolist() == ["Nursing", "Finance"]

    def test_no_descriptors_by_default(self):
        # Byte-identity guard: without descriptor_columns, no extra columns appear.
        out = prepare_dataset(self._df(), self._config())
        assert "program" not in out.columns
        assert set(out.columns) == {"response_id", "response_text", "question_text"}

    def test_descriptors_survive_row_filtering(self):
        df = pd.DataFrame({
            "response_text": ["ok", "this one is long enough", "hi"],  # first/last filtered by min_chars
            "group": ["A", "B", "C"],
        })
        cfg = self._config(descriptor_columns=["group"])
        cfg["preprocessing"]["min_chars"] = 5
        out = prepare_dataset(df, cfg)
        assert out["group"].tolist() == ["B"]
