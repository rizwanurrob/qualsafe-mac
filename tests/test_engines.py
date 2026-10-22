"""
Tests for the v3 engine abstraction and shared project model (Phase 0a).

Discipline matches tests/test_pipeline.py: offline, deterministic, and the
transformer engine's model calls are mocked at `analyze_survey.pipeline`
(no downloads). These tests assert the engine reproduces the *exact* values the
v2.1 functions produce, so the upcoming run_pipeline rewire can be proven
byte-identical.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analyze_survey import assign_strict_labels_from_results
from engines.base import (
    ResponseCoding,
    ThemeEngine,
    SCORE_KIND_NLI_INDEPENDENT,
    SCORE_KIND_NLI_SOFTMAX,
)
from engines.transformer_engine import TransformerEngine
from core.model import (
    Excerpt, Source, Code, CodeApplication, Descriptor, DescriptorField,
    Rater, WeightScale, ancestors, expand_with_ancestors,
)


# ─────────────────────────────────────────────────────────────────────────────
# Mock pipelines (mirrors tests/test_pipeline.py TestRunPipelineSmoke)
# ─────────────────────────────────────────────────────────────────────────────

def _mock_zshot_pipeline():
    def _call(texts, candidate_labels, **kw):
        if isinstance(texts, str):
            texts = [texts]
        return [
            {"labels": list(candidate_labels),
             "scores": [0.7, 0.2, 0.1][: len(candidate_labels)],
             "sequence": t}
            for t in texts
        ]
    return _call


def _mock_sentiment_pipeline():
    def _call(texts, **kw):
        if isinstance(texts, str):
            texts = [texts]
        return [{"label": "POSITIVE", "score": 0.9} for _ in texts]
    return _call


def _pipeline_factory(task, *args, **kwargs):
    if task == "zero-shot-classification":
        return _mock_zshot_pipeline()
    if task == "sentiment-analysis":
        return _mock_sentiment_pipeline()
    return MagicMock()


# ─────────────────────────────────────────────────────────────────────────────
# ResponseCoding
# ─────────────────────────────────────────────────────────────────────────────

class TestResponseCoding:
    def test_top_label_and_score(self):
        rc = ResponseCoding(labels=["A", "B"], scores=[0.8, 0.2])
        assert rc.top_label == "A"
        assert rc.top_score == 0.8

    def test_empty_top_label_and_nan_score(self):
        rc = ResponseCoding(labels=[], scores=[])
        assert rc.top_label == ""
        assert math.isnan(rc.top_score)

    def test_all_labels_and_scores_strings_match_v21_format(self):
        rc = ResponseCoding(labels=["A", "B", "C"], scores=[0.7, 0.2, 0.1])
        assert rc.all_labels_str() == "A|B|C"
        assert rc.all_scores_str() == "0.7000|0.2000|0.1000"

    def test_transformer_engine_satisfies_protocol(self):
        eng = TransformerEngine(zero_shot_model="m")
        assert isinstance(eng, ThemeEngine)

    def test_length_invariant_enforced(self):
        with pytest.raises(ValueError, match="length mismatch"):
            ResponseCoding(labels=["A", "B"], scores=[0.5])

    def test_empty_is_valid(self):
        rc = ResponseCoding()  # 0 labels, 0 scores — equal lengths
        assert rc.top_label == ""


# ─────────────────────────────────────────────────────────────────────────────
# TransformerEngine — faithful reproduction of the v2.1 path
# ─────────────────────────────────────────────────────────────────────────────

class TestTransformerEngine:
    LABELS = ["A", "B", "C"]

    def test_reproduces_zero_shot_top_label_and_scores(self):
        with patch("analyze_survey.pipeline", side_effect=_pipeline_factory):
            eng = TransformerEngine(zero_shot_model="m")
            out = eng.code_responses(["text one", "text two"], self.LABELS, {"multi_label": True})
        assert len(out) == 2
        assert out[0].top_label == "A"
        assert out[0].scores == [0.7, 0.2, 0.1]
        assert out[0].all_labels_str() == "A|B|C"

    def test_records_score_provenance(self):
        with patch("analyze_survey.pipeline", side_effect=_pipeline_factory):
            eng = TransformerEngine(zero_shot_model="facebook/bart-large-mnli")
            multi = eng.code_responses(["t"], self.LABELS, {"multi_label": True})
            single = eng.code_responses(["t"], self.LABELS, {"multi_label": False})
        assert multi[0].source_engine == "transformer"
        assert multi[0].model_id == "facebook/bart-large-mnli"
        assert multi[0].score_kind == SCORE_KIND_NLI_INDEPENDENT
        # multi_label=False is a softmax over labels — different semantics.
        assert single[0].score_kind == SCORE_KIND_NLI_SOFTMAX

    def test_strict_gate_parity_with_v21_function(self):
        """Engine strict_* fields must equal assign_strict_labels_from_results."""
        strict_cfg = {"enabled": True, "uncertain_label": "UNCERTAIN_REVIEW",
                      "top1_min_score": 0.55, "min_margin_over_second": 0.10}
        with patch("analyze_survey.pipeline", side_effect=_pipeline_factory):
            eng = TransformerEngine(zero_shot_model="m")
            out = eng.code_responses(["t1", "t2"], self.LABELS,
                                     {"multi_label": True, "strict_coding": strict_cfg})

        # Recompute expected strict outcome directly from the same mocked scores.
        z_results = [{"labels": self.LABELS, "scores": [0.7, 0.2, 0.1]}] * 2
        e_labels, e_conf, e_reason, e_margin = assign_strict_labels_from_results(z_results, strict_cfg)
        for i in range(2):
            assert out[i].strict_label == e_labels[i]
            assert out[i].strict_confident == e_conf[i]
            assert out[i].strict_reason == e_reason[i]
            assert math.isclose(out[i].strict_margin, e_margin[i], abs_tol=1e-9)
        # top1=0.7 >= 0.55 and margin 0.5 >= 0.10 → confident on "A"
        assert out[0].strict_label == "A"
        assert out[0].strict_confident is True

    def test_no_strict_config_leaves_strict_fields_unset(self):
        with patch("analyze_survey.pipeline", side_effect=_pipeline_factory):
            eng = TransformerEngine(zero_shot_model="m")
            out = eng.code_responses(["t"], self.LABELS, {"multi_label": True})
        assert out[0].strict_label is None
        assert out[0].strict_confident is None

    def test_sentiment_populated_when_requested(self):
        with patch("analyze_survey.pipeline", side_effect=_pipeline_factory):
            eng = TransformerEngine(zero_shot_model="m", sentiment_model="s")
            out = eng.code_responses(["t1", "t2"], self.LABELS,
                                     {"multi_label": True, "run_sentiment": True})
        assert out[0].sentiment_label == "POSITIVE"
        assert math.isclose(out[0].sentiment_score, 0.9, abs_tol=1e-9)

    def test_sentiment_absent_when_not_requested(self):
        with patch("analyze_survey.pipeline", side_effect=_pipeline_factory):
            eng = TransformerEngine(zero_shot_model="m", sentiment_model="s")
            out = eng.code_responses(["t"], self.LABELS, {"multi_label": True})
        assert out[0].sentiment_label is None
        assert out[0].sentiment_score is None


# ─────────────────────────────────────────────────────────────────────────────
# core.model — construction + the offset-verification (anti-hallucination) helper
# ─────────────────────────────────────────────────────────────────────────────

class TestProjectModel:
    def test_source_and_whole_response_excerpt(self):
        src = Source(source_id="r1", type="survey_response", raw_text="hello world")
        exc = Excerpt(excerpt_id="e1", source_id="r1", text="hello world",
                      char_start=0, char_end=len(src.raw_text))
        assert exc.verify_offsets(src.raw_text) is True

    def test_offset_verification_catches_mismatch(self):
        raw = "the advisor was great but the portal is broken"
        # Claims to be a span that does not actually sit at these offsets.
        exc = Excerpt(excerpt_id="e1", source_id="r1", text="portal is broken",
                      char_start=0, char_end=16)
        assert exc.verify_offsets(raw) is False

    def test_offset_verification_true_for_real_subspan(self):
        raw = "the advisor was great but the portal is broken"
        start = raw.index("the portal is broken")
        exc = Excerpt(excerpt_id="e1", source_id="r1", text="the portal is broken",
                      char_start=start, char_end=start + len("the portal is broken"))
        assert exc.verify_offsets(raw) is True

    def test_offset_verification_out_of_bounds_is_false(self):
        exc = Excerpt(excerpt_id="e1", source_id="r1", text="x", char_start=5, char_end=99)
        assert exc.verify_offsets("short") is False

    def test_tolerant_whitespace_match(self):
        raw = "I   really  liked   the   course"
        # An LLM might return the quote with normalized single spaces.
        exc = Excerpt(excerpt_id="e1", source_id="r1", text="I really liked the course",
                      char_start=0, char_end=len(raw))
        assert exc.verify_offsets(raw, tolerant_whitespace=True) is True
        assert exc.verify_offsets(raw, tolerant_whitespace=False) is False

    def test_code_hierarchy_and_application(self):
        parent = Code(code_id="wellbeing", name="Wellbeing")
        child = Code(code_id="stress", name="stress_mental_health", parent_id="wellbeing")
        app = CodeApplication(application_id="a1", excerpt_id="e1", code_id="stress",
                              coder="llm", confidence=0.82, weight=-0.6, rationale="mentions anxiety")
        assert child.parent_id == parent.code_id
        assert app.code_id == "stress"
        assert app.weight == -0.6

    def test_descriptor_holds_metadata(self):
        d = Descriptor(source_id="r1", key="First_Generation", value="Yes")
        assert d.key == "First_Generation" and d.value == "Yes"


# ─────────────────────────────────────────────────────────────────────────────
# Schema refinements (V3_PLAN.md items 1-5): descriptor typing, weight scale,
# rater/run provenance, and codebook roll-up semantics.
# ─────────────────────────────────────────────────────────────────────────────

class TestSchemaRefinements:
    def test_ordinal_descriptor_sorts_by_declared_levels_not_alphabetically(self):
        field = DescriptorField(
            key="Age_Band", dtype="ordinal",
            ordered_levels=["Under 18", "18-19", "20-21", "22-24", "25+"],
        )
        values = ["25+", "18-19", "Under 18", "20-21"]
        ordered = sorted(values, key=field.sort_key)
        assert ordered == ["Under 18", "18-19", "20-21", "25+"]

    def test_numeric_descriptor_sorts_numerically(self):
        field = DescriptorField(key="GPA", dtype="numeric")
        assert sorted(["10", "2", "1.5"], key=field.sort_key) == ["1.5", "2", "10"]

    def test_unknown_ordinal_level_sorts_after_known(self):
        field = DescriptorField(key="Band", dtype="ordinal", ordered_levels=["low", "high"])
        assert sorted(["high", "???", "low"], key=field.sort_key) == ["low", "high", "???"]

    def test_weight_scale_on_code_and_range_check(self):
        scale = WeightScale(kind="valence", min_value=-1.0, max_value=1.0)
        code = Code(code_id="advisor", name="Advisor experience", weight_scale=scale)
        assert code.weight_scale.kind == "valence"
        assert code.weight_scale.contains(-0.6) is True
        assert code.weight_scale.contains(1.5) is False

    def test_application_carries_rater_and_run_provenance(self):
        rater = Rater(rater_id="model_bart", kind="transformer",
                      model_id="facebook/bart-large-mnli")
        app = CodeApplication(application_id="a1", excerpt_id="e1", code_id="belonging",
                              coder="transformer", rater_id=rater.rater_id, run_id="run_2026_07_01")
        assert app.rater_id == "model_bart"
        assert app.run_id == "run_2026_07_01"

    def _wellbeing_codebook(self):
        codes = {
            "wellbeing": Code(code_id="wellbeing", name="Wellbeing"),
            "stress": Code(code_id="stress", name="stress_mental_health", parent_id="wellbeing"),
            "resilience": Code(code_id="resilience", name="resilience", parent_id="wellbeing"),
            "academics": Code(code_id="academics", name="Academics"),
        }
        return codes

    def test_ancestors_walks_to_root(self):
        codes = self._wellbeing_codebook()
        assert ancestors("stress", codes) == ["wellbeing"]
        assert ancestors("wellbeing", codes) == []

    def test_ancestors_is_cycle_safe(self):
        # Malformed codebook: a <-> b cycle must not loop forever.
        codes = {
            "a": Code(code_id="a", name="A", parent_id="b"),
            "b": Code(code_id="b", name="B", parent_id="a"),
        }
        result = ancestors("a", codes)
        assert "b" in result and len(result) <= 2  # stops at the cycle

    def test_rollup_dedupes_siblings_at_parent(self):
        codes = self._wellbeing_codebook()
        # An excerpt coded with BOTH children of "wellbeing" rolls up to ONE parent.
        rolled = expand_with_ancestors({"stress", "resilience"}, codes)
        assert rolled == {"stress", "resilience", "wellbeing"}
        assert list(rolled).count("wellbeing") == 1
