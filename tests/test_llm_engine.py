"""
Tests for engines/llm_engine.py — mocked Ollama client (no live server).

Asserts the LLM engine builds ResponseCoding correctly (sorted scores, provenance,
sentiment, rationale), applies the shared strict-coding gate, ignores invented
labels, defaults missing labels to 0, and degrades a per-row JSON failure to an
uncertain coding rather than failing the batch.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engines.base import SCORE_KIND_LLM_SELFREPORT
from engines.llm_engine import CODING_SCHEMA, LlmEngine
from engines.ollama_client import OllamaJSONError

LABELS = ["Belonging", "Financial concern", "Academic success"]
STRICT = {"enabled": True, "uncertain_label": "UNCERTAIN_REVIEW",
          "top1_min_score": 0.55, "min_margin_over_second": 0.10}


def _engine(generate_return):
    client = MagicMock()
    if isinstance(generate_return, list):
        client.generate_json.side_effect = generate_return
    else:
        client.generate_json.return_value = generate_return
    return LlmEngine(model="llama3.2:3b", client=client), client


class TestLlmEngine:
    def test_builds_sorted_coding_with_provenance(self):
        payload = {"theme_scores": {"Belonging": 0.9, "Financial concern": 0.1, "Academic success": 0.3},
                   "sentiment": "positive", "sentiment_confidence": 0.8, "rationale": "feels at home"}
        eng, _ = _engine(payload)
        out = eng.code_responses(["I belong here"], LABELS, {})
        c = out[0]
        assert c.labels == ["Belonging", "Academic success", "Financial concern"]  # score-desc
        assert c.scores == [0.9, 0.3, 0.1]
        assert c.top_label == "Belonging"
        assert c.score_kind == SCORE_KIND_LLM_SELFREPORT
        assert c.source_engine == "llm" and c.model_id == "llama3.2:3b"
        assert c.sentiment_label == "POSITIVE" and c.sentiment_score == 0.8
        assert c.rationale == "feels at home"

    def test_strict_gate_applied(self):
        confident = {"theme_scores": {"Belonging": 0.8, "Financial concern": 0.2, "Academic success": 0.1},
                     "sentiment": "positive", "rationale": "x"}
        uncertain = {"theme_scores": {"Belonging": 0.4, "Financial concern": 0.35, "Academic success": 0.3},
                     "sentiment": "neutral", "rationale": "y"}
        eng, _ = _engine([confident, uncertain])
        # max_workers=1: this mock returns by call order, so pin the sequential
        # path (the concurrency-order guarantee is tested separately).
        out = eng.code_responses(["a", "b"], LABELS, {"strict_coding": STRICT, "max_workers": 1})
        assert out[0].strict_label == "Belonging" and out[0].strict_confident is True
        assert out[1].strict_label == "UNCERTAIN_REVIEW" and out[1].strict_confident is False

    def test_missing_labels_default_to_zero(self):
        payload = {"theme_scores": {"Belonging": 0.7}, "sentiment": "neutral", "rationale": "z"}
        eng, _ = _engine(payload)
        c = eng.code_responses(["t"], LABELS, {})[0]
        assert set(c.labels) == set(LABELS)  # all candidate labels present
        assert c.scores[0] == 0.7 and c.scores[1] == 0.0 and c.scores[2] == 0.0

    def test_invented_labels_ignored(self):
        payload = {"theme_scores": {"Belonging": 0.6, "Totally Made Up": 0.99},
                   "sentiment": "neutral", "rationale": "z"}
        eng, _ = _engine(payload)
        c = eng.code_responses(["t"], LABELS, {})[0]
        assert "Totally Made Up" not in c.labels
        assert set(c.labels) == set(LABELS)

    def test_json_failure_degrades_to_uncertain(self):
        client = MagicMock()
        client.generate_json.side_effect = OllamaJSONError("bad json")
        eng = LlmEngine(model="m", client=client)
        c = eng.code_responses(["t"], LABELS, {"strict_coding": STRICT})[0]
        # all-zero scores -> strict gate routes to uncertain, batch not broken
        assert c.strict_label == "UNCERTAIN_REVIEW"
        assert c.scores == [0.0, 0.0, 0.0]

    def test_progress_callback_invoked_per_response(self):
        eng, _ = _engine({"theme_scores": {}, "sentiment": "neutral", "rationale": ""})
        seen = []
        eng.code_responses(["a", "b", "c"], LABELS, {"progress_callback": lambda done, total: seen.append((done, total))})
        assert seen == [(1, 3), (2, 3), (3, 3)]

    def test_passes_schema_and_determinism_knobs_to_client(self):
        eng, client = _engine({"theme_scores": {}, "sentiment": "neutral", "rationale": ""})
        eng2 = LlmEngine(model="m", client=client, temperature=0.2, seed=7)
        eng2.code_responses(["t"], LABELS, {})
        kwargs = client.generate_json.call_args.kwargs
        assert kwargs["schema"] is CODING_SCHEMA
        assert kwargs["temperature"] == 0.2 and kwargs["seed"] == 7
