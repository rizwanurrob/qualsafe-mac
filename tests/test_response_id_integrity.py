"""
Regression tests for response_id corruption in the Labeling Lab (bug fix).

Two compounding failures were mangling the training CSV:
1. A blank/missing id column value stringified to the literal "nan"/"None",
   colliding across rows.
2. Reloading coding_sample.csv let pandas infer a numeric id column as float, so
   "101" came back as 101.0 -> "101.0" — a different key than the widgets and the
   save mapping used, so codes vanished and ids duplicated as "nan".

These pin both at their boundaries: prepare_dataset (id creation) and
load_coding_sample_df (the round-trip read).
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analyze_survey import clean_id_series, clean_id_str, prepare_dataset


class TestCleanIdStr:
    def test_whole_float_drops_the_dot_zero(self):
        # The core bug: 101.0 must become "101", not "101.0".
        assert clean_id_str(101.0) == "101"

    def test_real_fraction_kept(self):
        assert clean_id_str(1.5) == "1.5"

    def test_missing_becomes_empty(self):
        assert clean_id_str(float("nan")) == ""
        assert clean_id_str(None) == ""
        assert clean_id_str("nan") == ""
        assert clean_id_str("None") == ""
        assert clean_id_str("  ") == ""

    def test_real_string_id_preserved(self):
        assert clean_id_str("R001") == "R001"
        assert clean_id_str(" 42 ") == "42"


class TestPrepareDatasetIds:
    def _cfg(self):
        return {
            "input": {"text_column": "txt", "question_column": "q", "id_column": "sid"},
            "preprocessing": {"min_chars": 1, "drop_duplicates": False, "max_rows": None},
        }

    def test_missing_ids_get_positional_fallback_not_nan(self):
        df = pd.DataFrame({
            "sid": ["101", "102", None, "104", np.nan, "106"],
            "q": ["Q1"] * 6, "txt": list("abcdef"),
        })
        ids = prepare_dataset(df, self._cfg())["response_id"].tolist()
        assert "nan" not in ids and "None" not in ids
        assert len(set(ids)) == len(ids), "ids must stay unique"
        # The two blanks became distinct positional ids.
        assert ids[2].startswith("row_") and ids[4].startswith("row_")

    def test_float_ids_render_without_dot_zero(self):
        df = pd.DataFrame({"sid": [101.0, 102.0, 103.0], "q": ["Q1"] * 3, "txt": list("abc")})
        ids = prepare_dataset(df, self._cfg())["response_id"].tolist()
        assert ids == ["101", "102", "103"]

    def test_clean_id_series_vectorized(self):
        s = pd.Series([101.0, np.nan, "R2", "nan"])
        assert clean_id_series(s).tolist() == ["101", "", "R2", ""]


class TestCodingSampleRoundTrip:
    def _write_sample(self, d: Path, ids):
        pd.DataFrame({
            "response_id": ids,
            "question_text": ["Q1"] * len(ids),
            "response_text": [f"text {i}" for i in ids],
            "human_labels": [""] * len(ids),
            "coder_notes": [""] * len(ids),
        }).to_csv(d / "coding_sample.csv", index=False)

    def test_numeric_ids_stay_stable_on_reload(self, tmp_path):
        import streamlit_app as app

        self._write_sample(tmp_path, [101, 102, 103, 104, 105])
        back = app.load_coding_sample_df(tmp_path)
        # Read as string, no float-coercion, no ".0".
        assert back["response_id"].tolist() == ["101", "102", "103", "104", "105"]

    def test_empty_label_cells_are_empty_string_not_nan(self, tmp_path):
        import streamlit_app as app

        self._write_sample(tmp_path, [1, 2, 3])
        back = app.load_coding_sample_df(tmp_path)
        assert list(back["human_labels"]) == ["", "", ""]
        assert not back["human_labels"].isna().any()

    def test_code_save_reload_preserves_labels(self, tmp_path):
        import streamlit_app as app

        self._write_sample(tmp_path, [101, 102, 103])
        back = app.load_coding_sample_df(tmp_path)

        # Code two rows, save the way the Lab does.
        iter_labels = {"101": ["cost"], "103": ["belonging"]}
        out = back.copy()
        out["human_labels"] = out["response_id"].map(
            lambda r: "|".join(iter_labels.get(r, [])))
        out.to_csv(tmp_path / "coding_sample.csv", index=False)

        reloaded = app.load_coding_sample_df(tmp_path)
        labels = dict(zip(reloaded["response_id"], reloaded["human_labels"]))
        assert labels == {"101": "cost", "102": "", "103": "belonging"}

    def test_ids_do_not_duplicate_across_reloads(self, tmp_path):
        import streamlit_app as app

        # Include a blank that previously collapsed to a duplicate "nan".
        pd.DataFrame({
            "response_id": ["101", "102", "", "104"],
            "question_text": ["Q1"] * 4,
            "response_text": list("abcd"),
            "human_labels": [""] * 4, "coder_notes": [""] * 4,
        }).to_csv(tmp_path / "coding_sample.csv", index=False)
        back = app.load_coding_sample_df(tmp_path)
        non_blank = [r for r in back["response_id"] if r]
        assert len(set(non_blank)) == len(non_blank)  # no "nan" collisions
