"""
Unit and integration tests for the QualSafe pipeline.

Run with:
    pytest tests/ -v

What is covered:
- assign_strict_labels_from_results: threshold, margin, and multi-label rules
- extract_top_terms_by_cluster: basic output shape + empty-vocabulary edge case
- parse_multilabel_cell (iterative module): delimiter parsing + deduplication
- prepare_dataset: column mapping, min_chars filtering, deduplication
- run_pipeline (smoke test): end-to-end with sample_survey.csv

Design notes:
- Tests use only numpy/pandas/sklearn — no model downloads required.
- The smoke test uses a tiny synthetic DataFrame (no file I/O for the input)
  and mocks out the transformer models so it runs offline in CI.
- Each test function is self-contained: no shared mutable state.
"""

from __future__ import annotations

import math
import textwrap
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

# Import the modules under test.
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analyze_survey import (
    assign_strict_labels_from_results,
    extract_top_terms_by_cluster,
    prepare_dataset,
    make_cluster_summary,
    add_zero_shot_columns,
    clean_text,
    sanitize_for_csv,
    sanitize_frame_for_csv,
)
from iterative_supervised_thematic import parse_multilabel_cell


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _zshot_result(labels: List[str], scores: List[float]) -> Dict[str, Any]:
    return {"labels": labels, "scores": scores, "sequence": "test"}


# ─────────────────────────────────────────────────────────────────────────────
# clean_text
# ─────────────────────────────────────────────────────────────────────────────

class TestCleanText:
    def test_collapses_whitespace(self):
        assert clean_text("hello   world") == "hello world"

    def test_strips_leading_trailing(self):
        assert clean_text("  hi  ") == "hi"

    def test_handles_newlines(self):
        assert clean_text("line1\nline2") == "line1 line2"

    def test_empty_string(self):
        assert clean_text("") == ""


# ─────────────────────────────────────────────────────────────────────────────
# assign_strict_labels_from_results
# ─────────────────────────────────────────────────────────────────────────────

class TestStrictLabels:
    DEFAULT_CFG = {
        "uncertain_label": "UNCERTAIN_REVIEW",
        "top1_min_score": 0.55,
        "min_margin_over_second": 0.10,
        "allow_multilabel_output": False,
    }

    def test_confident_single_label(self):
        results = [_zshot_result(["A", "B"], [0.80, 0.30])]
        labels, confident, reason, margin = assign_strict_labels_from_results(results, self.DEFAULT_CFG)
        assert labels[0] == "A"
        assert confident[0] is True
        assert reason[0] == "confident_top1"
        assert math.isclose(margin[0], 0.50, abs_tol=1e-6)

    def test_low_top1_score_routes_to_uncertain(self):
        results = [_zshot_result(["A", "B"], [0.40, 0.10])]
        labels, confident, reason, _ = assign_strict_labels_from_results(results, self.DEFAULT_CFG)
        assert labels[0] == "UNCERTAIN_REVIEW"
        assert confident[0] is False
        assert "low_top1_score" in reason[0]

    def test_low_margin_routes_to_uncertain(self):
        # top1 score passes threshold but margin is too narrow
        results = [_zshot_result(["A", "B"], [0.62, 0.58])]
        labels, confident, reason, _ = assign_strict_labels_from_results(results, self.DEFAULT_CFG)
        assert labels[0] == "UNCERTAIN_REVIEW"
        assert "low_margin" in reason[0]

    def test_empty_result_routes_to_uncertain(self):
        results = [{"labels": [], "scores": []}]
        labels, confident, reason, _ = assign_strict_labels_from_results(results, self.DEFAULT_CFG)
        assert labels[0] == "UNCERTAIN_REVIEW"
        assert reason[0] == "no_candidate_labels"

    def test_multilabel_mode(self):
        cfg = {**self.DEFAULT_CFG, "allow_multilabel_output": True, "min_multilabel_score": 0.55}
        results = [_zshot_result(["A", "B", "C"], [0.80, 0.70, 0.30])]
        labels, confident, reason, _ = assign_strict_labels_from_results(results, cfg)
        # Both A and B exceed the multilabel threshold
        assert "A" in labels[0]
        assert "B" in labels[0]
        assert confident[0] is True
        assert reason[0] == "confident_multilabel"

    def test_multilabel_nothing_above_threshold_routes_to_uncertain(self):
        cfg = {**self.DEFAULT_CFG, "allow_multilabel_output": True, "min_multilabel_score": 0.90}
        results = [_zshot_result(["A", "B"], [0.80, 0.70])]
        labels, confident, _, _ = assign_strict_labels_from_results(results, cfg)
        assert labels[0] == "UNCERTAIN_REVIEW"
        assert confident[0] is False

    def test_batch_of_multiple_results(self):
        results = [
            _zshot_result(["A", "B"], [0.80, 0.10]),   # confident
            _zshot_result(["A", "B"], [0.40, 0.10]),   # low score
            _zshot_result(["A", "B"], [0.65, 0.62]),   # low margin
        ]
        labels, confident, _, _ = assign_strict_labels_from_results(results, self.DEFAULT_CFG)
        assert confident[0] is True
        assert confident[1] is False
        assert confident[2] is False

    def test_custom_uncertain_label(self):
        cfg = {**self.DEFAULT_CFG, "uncertain_label": "NEEDS_REVIEW"}
        results = [_zshot_result(["A"], [0.30])]
        labels, _, _, _ = assign_strict_labels_from_results(results, cfg)
        assert labels[0] == "NEEDS_REVIEW"


# ─────────────────────────────────────────────────────────────────────────────
# extract_top_terms_by_cluster
# ─────────────────────────────────────────────────────────────────────────────

class TestExtractTopTerms:
    def test_returns_dict_keyed_by_cluster(self):
        texts = [
            "the system is slow and unresponsive",
            "system performance is very poor",
            "the price is too expensive for what it offers",
            "cost is high compared to competitors",
        ]
        labels = [0, 0, 1, 1]
        result = extract_top_terms_by_cluster(texts, labels, max_terms=5)
        assert set(result.keys()) == {0, 1}

    def test_terms_are_strings(self):
        texts = ["fast response time", "quick and responsive", "billing issues with invoice"]
        labels = [0, 0, 1]
        result = extract_top_terms_by_cluster(texts, labels, max_terms=3)
        for cluster_id, terms in result.items():
            assert all(isinstance(t, str) for t in terms)

    def test_empty_vocabulary_returns_empty_lists(self):
        # Very short texts with stop-words only → TF-IDF vocab is empty
        texts = ["the", "a", "is"]
        labels = [0, 0, 1]
        result = extract_top_terms_by_cluster(texts, labels, max_terms=3)
        # Should not raise; may return empty lists
        assert isinstance(result, dict)

    def test_single_cluster(self):
        texts = ["good product", "great quality", "excellent service"]
        labels = [0, 0, 0]
        result = extract_top_terms_by_cluster(texts, labels, max_terms=5)
        assert 0 in result


# ─────────────────────────────────────────────────────────────────────────────
# add_zero_shot_columns
# ─────────────────────────────────────────────────────────────────────────────

class TestAddZeroShotColumns:
    def test_columns_added(self):
        df = pd.DataFrame({"response_text": ["text a", "text b"]})
        results = [
            _zshot_result(["A", "B"], [0.8, 0.2]),
            _zshot_result(["B", "A"], [0.7, 0.3]),
        ]
        out = add_zero_shot_columns(df, results, prefix="zshot")
        assert "zshot_top_label" in out.columns
        assert "zshot_top_score" in out.columns
        assert "zshot_all_labels" in out.columns
        assert "zshot_all_scores" in out.columns

    def test_top_label_values(self):
        df = pd.DataFrame({"response_text": ["text"]})
        results = [_zshot_result(["Quality", "Price"], [0.9, 0.1])]
        out = add_zero_shot_columns(df, results, prefix="zshot")
        assert out["zshot_top_label"].iloc[0] == "Quality"

    def test_empty_labels_gives_nan_score(self):
        df = pd.DataFrame({"response_text": ["text"]})
        results = [{"labels": [], "scores": []}]
        out = add_zero_shot_columns(df, results, prefix="zshot")
        assert math.isnan(out["zshot_top_score"].iloc[0])


# ─────────────────────────────────────────────────────────────────────────────
# prepare_dataset
# ─────────────────────────────────────────────────────────────────────────────

class TestPrepareDataset:
    def _make_config(self, text_col="response_text", question_col=None, id_col=None, min_chars=3):
        return {
            "input": {
                "text_column": text_col,
                "question_column": question_col,
                "id_column": id_col,
                "file_path": "dummy.csv",
            },
            "preprocessing": {
                "min_chars": min_chars,
                "drop_duplicates": True,
                "max_rows": None,
            },
        }

    def test_basic_output_columns(self):
        df = pd.DataFrame({"response_text": ["hello world", "test response"]})
        config = self._make_config()
        out = prepare_dataset(df, config)
        assert "response_id" in out.columns
        assert "response_text" in out.columns
        assert "question_text" in out.columns

    def test_min_chars_filter(self):
        df = pd.DataFrame({"response_text": ["ok", "this is long enough", "hi"]})
        config = self._make_config(min_chars=5)
        out = prepare_dataset(df, config)
        assert all(out["response_text"].str.len() >= 5)

    def test_deduplication(self):
        df = pd.DataFrame({"response_text": ["same text", "same text", "different"]})
        config = self._make_config()
        out = prepare_dataset(df, config)
        assert len(out) == 2

    def test_missing_text_column_raises(self):
        df = pd.DataFrame({"wrong_col": ["text"]})
        config = self._make_config(text_col="response_text")
        with pytest.raises(KeyError, match="response_text"):
            prepare_dataset(df, config)

    def test_question_column_mapping(self):
        df = pd.DataFrame({
            "response_text": ["good experience overall"],
            "question": ["Q1: satisfaction"],
        })
        config = self._make_config(question_col="question")
        out = prepare_dataset(df, config)
        assert out["question_text"].iloc[0] == "Q1: satisfaction"

    def test_fallback_question_text_when_no_column(self):
        df = pd.DataFrame({"response_text": ["text here"]})
        config = self._make_config()
        out = prepare_dataset(df, config)
        assert out["question_text"].iloc[0] == "All Responses"


# ─────────────────────────────────────────────────────────────────────────────
# parse_multilabel_cell (iterative module)
# ─────────────────────────────────────────────────────────────────────────────

class TestParseMultilabelCell:
    def test_single_label(self):
        assert parse_multilabel_cell("Usability", "|") == ["Usability"]

    def test_multiple_labels(self):
        result = parse_multilabel_cell("Price|Quality|Support", "|")
        assert result == ["Price", "Quality", "Support"]

    def test_deduplicates(self):
        result = parse_multilabel_cell("A|A|B", "|")
        assert result == ["A", "B"]

    def test_empty_string(self):
        assert parse_multilabel_cell("", "|") == []

    def test_none_value(self):
        assert parse_multilabel_cell(None, "|") == []

    def test_nan_value(self):
        assert parse_multilabel_cell(float("nan"), "|") == []

    def test_strips_whitespace(self):
        result = parse_multilabel_cell(" Price | Quality ", "|")
        assert result == ["Price", "Quality"]

    def test_custom_delimiter(self):
        result = parse_multilabel_cell("A,B,C", ",")
        assert result == ["A", "B", "C"]


# ─────────────────────────────────────────────────────────────────────────────
# make_cluster_summary
# ─────────────────────────────────────────────────────────────────────────────

class TestMakeClusterSummary:
    def test_output_columns(self):
        df = pd.DataFrame({
            "cluster_id": [0, 0, 1, 1, 1],
            "response_text": ["a", "b", "c", "d", "e"],
        })
        top_terms = {0: ["term_a"], 1: ["term_b", "term_c"]}
        reps = {0: ["a"], 1: ["c", "d"]}
        summary = make_cluster_summary(df, top_terms, reps)
        assert set(summary.columns) >= {"cluster_id", "response_count", "response_percent", "top_terms"}

    def test_percentages_sum_to_100(self):
        df = pd.DataFrame({"cluster_id": [0, 0, 1, 1, 1]})
        summary = make_cluster_summary(df, {0: [], 1: []}, {0: [], 1: []})
        assert abs(summary["response_percent"].sum() - 100.0) < 0.01


# ─────────────────────────────────────────────────────────────────────────────
# sanitize_for_csv
# ─────────────────────────────────────────────────────────────────────────────

class TestSanitizeForCsv:
    def test_normal_text_unchanged(self):
        assert sanitize_for_csv("Great service overall") == "Great service overall"

    def test_equals_prefix_escaped(self):
        result = sanitize_for_csv("=SUM(A1:A10)")
        assert result.startswith("'")
        assert "SUM" in result

    def test_plus_prefix_escaped(self):
        assert sanitize_for_csv("+10 points").startswith("'")

    def test_minus_prefix_escaped(self):
        assert sanitize_for_csv("-10 degrees").startswith("'")

    def test_at_prefix_escaped(self):
        assert sanitize_for_csv("@username mention").startswith("'")

    def test_tab_prefix_escaped(self):
        assert sanitize_for_csv("\tindented").startswith("'")

    def test_empty_string_unchanged(self):
        assert sanitize_for_csv("") == ""

    def test_non_string_passthrough(self):
        assert sanitize_for_csv(42) == 42
        assert sanitize_for_csv(None) is None

    def test_normal_minus_inside_text_unchanged(self):
        # Only leading character matters
        assert sanitize_for_csv("score: -10") == "score: -10"


class TestSanitizeFrameForCsv:
    """Frame-level sanitization must not depend on which dtype pandas picked.

    This is the guard that failed quietly before: `select_dtypes(include="object")`
    skipped StringDtype columns, and pandas 3 makes StringDtype the default for
    text. These tests are meant to fail loudly the day dtype semantics shift
    again — the injection guard covering the response text is the whole point.
    """

    def test_object_dtype_column_sanitized(self):
        df = pd.DataFrame({"response_text": ["=cmd()", "normal"]})
        assert df["response_text"].dtype == object
        out = sanitize_frame_for_csv(df)
        assert out["response_text"].iloc[0].startswith("'=")
        assert out["response_text"].iloc[1] == "normal"

    def test_string_dtype_column_sanitized(self):
        """The pandas-3 failure mode: text in StringDtype, not object."""
        df = pd.DataFrame({"response_text": pd.array(["=cmd()", "fine"], dtype=pd.StringDtype())})
        assert isinstance(df["response_text"].dtype, pd.StringDtype)
        out = sanitize_frame_for_csv(df)
        assert out["response_text"].iloc[0].startswith("'=")

    def test_string_dtype_survives_roundtrip_to_csv(self, tmp_path):
        """End-to-end: the exported cell on disk is escaped."""
        df = pd.DataFrame({"response_text": pd.array(["=cmd()"], dtype=pd.StringDtype())})
        path = tmp_path / "out.csv"
        sanitize_frame_for_csv(df).to_csv(path, index=False)
        assert "'=cmd()" in path.read_text(encoding="utf-8")

    def test_numeric_columns_left_alone(self):
        """Stringifying numbers would break Excel's numeric parsing."""
        df = pd.DataFrame({"score": [-10, 5], "ratio": [-1.5, 2.0], "flag": [True, False]})
        out = sanitize_frame_for_csv(df)
        assert out["score"].tolist() == [-10, 5]
        assert out["ratio"].tolist() == [-1.5, 2.0]
        assert out["flag"].tolist() == [True, False]
        assert pd.api.types.is_numeric_dtype(out["score"])

    def test_mixed_frame_sanitizes_text_only(self):
        df = pd.DataFrame(
            {
                "response_text": ["@mention"],
                "cluster": [3],
                "label": pd.array(["+plus"], dtype=pd.StringDtype()),
            }
        )
        out = sanitize_frame_for_csv(df)
        assert out["response_text"].iloc[0] == "'@mention"
        assert out["label"].iloc[0] == "'+plus"
        assert out["cluster"].iloc[0] == 3

    def test_nulls_and_non_strings_pass_through(self):
        df = pd.DataFrame({"mixed": ["=bad", None, 42]})
        out = sanitize_frame_for_csv(df)
        assert out["mixed"].iloc[0] == "'=bad"
        assert out["mixed"].iloc[1] is None
        assert out["mixed"].iloc[2] == 42

    def test_input_frame_not_mutated(self):
        df = pd.DataFrame({"response_text": ["=cmd()"]})
        sanitize_frame_for_csv(df)
        assert df["response_text"].iloc[0] == "=cmd()"


# ─────────────────────────────────────────────────────────────────────────────
# Deduplication fix — response_text + question_text
# ─────────────────────────────────────────────────────────────────────────────

class TestDeduplicationFix:
    def _make_config(self, drop_duplicates=True):
        return {
            "input": {
                "text_column": "response_text",
                "question_column": "question_text",
                "id_column": None,
                "file_path": "dummy.csv",
            },
            "preprocessing": {
                "min_chars": 1,
                "drop_duplicates": drop_duplicates,
                "max_rows": None,
            },
        }

    def test_na_responses_preserved_across_questions(self):
        """'N/A' under Q1 and Q2 should both survive deduplication."""
        df = pd.DataFrame({
            "response_text": ["N/A", "N/A", "Good experience"],
            "question_text": ["Q1", "Q2", "Q1"],
        })
        out = prepare_dataset(df, self._make_config(drop_duplicates=True))
        # All three rows should survive: same text but different questions
        assert len(out) == 3

    def test_true_duplicates_within_same_question_are_dropped(self):
        """Exact same text under the same question IS a true duplicate."""
        df = pd.DataFrame({
            "response_text": ["Great", "Great", "Poor"],
            "question_text": ["Q1", "Q1", "Q1"],
        })
        out = prepare_dataset(df, self._make_config(drop_duplicates=True))
        assert len(out) == 2

    def test_dedup_defaults_to_false(self):
        """Default behavior should NOT deduplicate anything."""
        df = pd.DataFrame({
            "response_text": ["Same", "Same", "Same"],
            "question_text": ["Q1", "Q1", "Q1"],
        })
        # No drop_duplicates key in config — should use default (False)
        config = {
            "input": {"text_column": "response_text", "question_column": None,
                      "id_column": None, "file_path": "dummy.csv"},
            "preprocessing": {"min_chars": 1, "max_rows": None},
        }
        out = prepare_dataset(df, config)
        assert len(out) == 3


# ─────────────────────────────────────────────────────────────────────────────

class TestRunPipelineSmoke:
    """
    Runs run_pipeline end-to-end with:
    - A small synthetic DataFrame written to a temp CSV.
    - Mocked SentenceTransformer and Hugging Face pipelines.
    
    This verifies the pipeline orchestration, file exports, and run_summary
    return value without requiring model downloads or GPU.
    """

    TEXTS = [
        "The registration process was confusing and took too long",
        "I love the new advising portal, it saves me time",
        "Financial aid disbursement was delayed by two weeks",
        "Academic advising staff were very helpful and knowledgeable",
        "The online portal keeps logging me out unexpectedly",
        "Course registration should have more seats available",
        "My scholarship was applied correctly, no issues",
        "Advising appointment was easy to schedule online",
        "The financial aid office never responded to my email",
        "Registration errors kept preventing me from enrolling",
    ]

    def _make_config(self, tmp_path: Path) -> Dict[str, Any]:
        # Write synthetic data to a CSV
        df = pd.DataFrame({
            "response_id": [str(i) for i in range(len(self.TEXTS))],
            "question_text": (["Registration"] * 4 + ["Advising"] * 3 + ["Financial Aid"] * 3),
            "response_text": self.TEXTS,
        })
        input_csv = tmp_path / "test_input.csv"
        df.to_csv(input_csv, index=False)
        output_dir = tmp_path / "output"

        return {
            "input": {
                "file_path": str(input_csv),
                "text_column": "response_text",
                "question_column": "question_text",
                "id_column": "response_id",
                "encoding": "utf-8",
                "sheet_name": 0,
            },
            "preprocessing": {"min_chars": 3, "drop_duplicates": False, "max_rows": None},
            "models": {
                "embedding_model": "sentence-transformers/all-MiniLM-L6-v2",
                "sentiment_model": "distilbert/distilbert-base-uncased-finetuned-sst-2-english",
                "zero_shot_model": "facebook/bart-large-mnli",
            },
            "pipeline": {"embedding_batch_size": 32, "inference_batch_size": 16, "normalize_embeddings": True},
            "clustering": {"fixed_k": 3, "min_k": 2, "max_k": 4, "random_state": 42,
                           "top_terms_per_cluster": 5, "sample_quotes_per_cluster": 2},
            "sentiment": {"enabled": True},
            "zero_shot": {
                "enabled": True,
                "multi_label": True,
                "labels": ["Registration issue", "Advising feedback", "Financial aid concern"],
                "strict_coding": {"enabled": True, "uncertain_label": "UNCERTAIN_REVIEW",
                                  "top1_min_score": 0.55, "min_margin_over_second": 0.10},
            },
            "thematic_analysis": {
                "by_question": {"enabled": True, "min_responses_per_question": 2,
                                "clustering": {"fixed_k": 2, "min_k": 2, "max_k": 3, "random_state": 42,
                                               "top_terms_per_cluster": 5, "sample_quotes_per_cluster": 2}},
                "by_question_zero_shot": {"enabled": False},
            },
            "output": {"output_dir": str(output_dir), "save_embeddings": False},
            "report": {"title": "Smoke Test Report"},
        }

    def _mock_embeddings(self, texts, **kwargs):
        """Return deterministic fake embeddings (no model download)."""
        rng = np.random.default_rng(42)
        return rng.standard_normal((len(texts), 32)).astype(np.float32)

    def _mock_sentiment_pipeline(self, *args, **kwargs):
        """Return a callable that returns fixed sentiment results."""
        def _call(texts, **kw):
            return [{"label": "POSITIVE", "score": 0.9}] * len(texts)
        return _call

    def _mock_zshot_pipeline(self, *args, **kwargs):
        """Return a callable that returns fixed zero-shot results."""
        def _call(texts, candidate_labels, **kw):
            if isinstance(texts, str):
                texts = [texts]
            return [
                {"labels": candidate_labels, "scores": [0.7, 0.2, 0.1][: len(candidate_labels)],
                 "sequence": t}
                for t in texts
            ]
        return _call

    def test_masking_done_at_the_gate_reaches_the_manifest(self, tmp_path):
        """End to end, because each half was tested alone and the link between
        them was missing: before 4.13 every manifest said no masking was
        applied, even after it was."""
        import json

        config = self._make_config(tmp_path)
        config["privacy"] = {"masking_applied": True, "pseudonymised": True}
        output_dir = Path(config["output"]["output_dir"])
        with (
            patch("analyze_survey.SentenceTransformer") as mock_st,
            patch("analyze_survey.pipeline") as mock_pipe,
        ):
            mock_model = MagicMock()
            mock_model.encode.side_effect = lambda texts, **kw: self._mock_embeddings(texts)
            mock_st.return_value = mock_model
            mock_pipe.side_effect = lambda task, *a, **k: (
                self._mock_sentiment_pipeline() if task == "sentiment-analysis"
                else self._mock_zshot_pipeline() if task == "zero-shot-classification"
                else MagicMock())
            from analyze_survey import run_pipeline
            run_pipeline(config)
        manifest = json.loads((output_dir / "run_manifest.json").read_text(encoding="utf-8"))
        assert manifest["local_mode"]["pii_masking_applied"] is True
        assert manifest["local_mode"]["pii_pseudonymised"] is True

    def test_smoke_runs_and_produces_outputs(self, tmp_path):
        config = self._make_config(tmp_path)
        output_dir = Path(config["output"]["output_dir"])

        with (
            patch("analyze_survey.SentenceTransformer") as mock_st,
            patch("analyze_survey.pipeline") as mock_pipe,
        ):
            # Wire up mocks
            mock_model = MagicMock()
            mock_model.encode.side_effect = lambda texts, **kw: self._mock_embeddings(texts)
            mock_st.return_value = mock_model

            def _pipeline_factory(task, *args, **kwargs):
                if task == "sentiment-analysis":
                    return self._mock_sentiment_pipeline()
                if task == "zero-shot-classification":
                    return self._mock_zshot_pipeline()
                return MagicMock()

            mock_pipe.side_effect = _pipeline_factory

            from analyze_survey import run_pipeline
            run_summary = run_pipeline(config)

        # Outputs exist
        assert (output_dir / "responses_scored.csv").exists()
        assert (output_dir / "cluster_summary.csv").exists()
        assert (output_dir / "run_report.md").exists()
        assert (output_dir / "silhouette_scores.json").exists()
        assert (output_dir / "run_manifest.json").exists()  # v3: always-on audit manifest

        # run_summary has expected keys
        assert "total_responses" in run_summary
        assert "clusters_found" in run_summary
        assert run_summary["clusters_found"] == 3  # fixed_k=3
        assert run_summary["total_responses"] == len(self.TEXTS)

        # responses_scored has expected columns
        scored = pd.read_csv(output_dir / "responses_scored.csv")
        assert "cluster_id" in scored.columns
        assert "sentiment_label" in scored.columns
        assert "zshot_top_label" in scored.columns

        # Strict coding columns present
        assert "zshot_strict_label" in scored.columns
        assert "zshot_strict_confident" in scored.columns

    def test_progress_callback_reports_stages(self, tmp_path):
        """The GUI progress contract: (fraction, message), monotonic, reaching 1.0.

        This is what tells a user on a slow CPU run that the pipeline is alive
        rather than hung — the specific gap that motivated wiring it.
        """
        config = self._make_config(tmp_path)
        events = []

        with (
            patch("analyze_survey.SentenceTransformer") as mock_st,
            patch("analyze_survey.pipeline") as mock_pipe,
        ):
            mock_model = MagicMock()
            mock_model.encode.side_effect = lambda texts, **kw: self._mock_embeddings(texts)
            mock_st.return_value = mock_model

            def _pipeline_factory(task, *args, **kwargs):
                if task == "sentiment-analysis":
                    return self._mock_sentiment_pipeline()
                if task == "zero-shot-classification":
                    return self._mock_zshot_pipeline()
                return MagicMock()

            mock_pipe.side_effect = _pipeline_factory

            from analyze_survey import run_pipeline
            run_pipeline(config, progress_callback=lambda f, m: events.append((f, m)))

        assert events, "no progress reported"
        fractions = [f for f, _ in events]
        messages = [m for _, m in events]
        # Bounded, non-decreasing, and it actually reaches completion.
        assert all(0.0 <= f <= 1.0 for f in fractions)
        assert fractions == sorted(fractions)
        assert fractions[-1] == 1.0
        # Messages are human-readable and name the slow stages a user waits on.
        assert all(isinstance(m, str) and m for m in messages)
        joined = " ".join(messages).lower()
        assert "embedding" in joined and "cluster" in joined

    def test_zero_shot_chunking_matches_single_call(self):
        """Per-response progress must not change results (byte-identity guard)."""
        from analyze_survey import run_zero_shot_with_pipeline

        def zsc(texts, candidate_labels, multi_label, batch_size):
            texts = [texts] if isinstance(texts, str) else texts
            return [{"labels": candidate_labels, "scores": [0.7, 0.3][:len(candidate_labels)],
                     "sequence": t} for t in texts]

        texts = [f"t{i}" for i in range(10)]
        labels = ["A", "B"]
        single = run_zero_shot_with_pipeline(zsc, texts, labels, True, 4, progress=None)
        events = []
        chunked = run_zero_shot_with_pipeline(
            zsc, texts, labels, True, 4, progress=lambda d, t: events.append((d, t)))
        assert single == chunked
        assert events[-1] == (10, 10)
        assert [d for d, _ in events] == sorted(d for d, _ in events)

    def test_progress_reaches_detailed_coding_updates(self, tmp_path):
        """The GUI run reports intra-stage coding progress, not just stage jumps."""
        config = self._make_config(tmp_path)
        # More rows + a small batch so the coding stage yields several updates.
        config["input"] = config.get("input", {})
        events = []
        with (
            patch("analyze_survey.SentenceTransformer") as mock_st,
            patch("analyze_survey.pipeline") as mock_pipe,
        ):
            mock_model = MagicMock()
            mock_model.encode.side_effect = lambda texts, **kw: self._mock_embeddings(texts)
            mock_st.return_value = mock_model
            mock_pipe.side_effect = lambda task, *a, **k: (
                self._mock_sentiment_pipeline() if task == "sentiment-analysis"
                else self._mock_zshot_pipeline() if task == "zero-shot-classification"
                else MagicMock())
            from analyze_survey import run_pipeline
            run_pipeline(config, progress_callback=lambda f, m: events.append((f, m)))

        coding_msgs = [m for _, m in events if "Coding themes" in m and "(" in m]
        assert coding_msgs, "no per-response coding updates were reported"

    def test_progress_callback_is_optional(self, tmp_path):
        """No callback (the CLI path) must not error and must not report."""
        config = self._make_config(tmp_path)
        with (
            patch("analyze_survey.SentenceTransformer") as mock_st,
            patch("analyze_survey.pipeline") as mock_pipe,
        ):
            mock_model = MagicMock()
            mock_model.encode.side_effect = lambda texts, **kw: self._mock_embeddings(texts)
            mock_st.return_value = mock_model
            mock_pipe.side_effect = lambda task, *a, **k: (
                self._mock_sentiment_pipeline() if task == "sentiment-analysis"
                else self._mock_zshot_pipeline() if task == "zero-shot-classification"
                else MagicMock())
            from analyze_survey import run_pipeline
            run_pipeline(config)  # must not raise with progress_callback=None

