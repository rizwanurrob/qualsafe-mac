"""
Mocked end-to-end test of the iterative workflow (v3.2, Phase 2.1/2.2/2.3).

Exercises create_coding_sample -> (human codes) -> train_and_apply with the
embedding builder mocked, so it runs offline. Asserts the Phase 2 additions:
the sampling note, the in_training_sample flag, and the cross-validated quality
report — the wiring the pure-function tests don't cover.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import iterative_supervised_thematic as iter_mod


def _fake_embeddings(texts, model_name, batch_size, normalize_embeddings, dedupe=False):
    """Deterministic separable-ish embeddings keyed on text content."""
    rng = np.random.default_rng(abs(hash(tuple(texts))) % (2**32))
    return rng.standard_normal((len(texts), 16)).astype(np.float32)


def _input_csv(tmp_path, n=24):
    rows = []
    for i in range(n):
        theme = "cost" if i % 2 == 0 else "belonging"
        rows.append({
            "response_id": f"r{i}",
            "question_text": "Q1",
            "response_text": f"{theme} concern number {i}",
        })
    path = tmp_path / "input.csv"
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


def _config(input_csv, out_dir, sampling="auto"):
    return {
        "input": {"file_path": str(input_csv), "text_column": "response_text",
                  "question_column": "question_text", "id_column": "response_id"},
        "preprocessing": {"min_chars": 3, "drop_duplicates": False, "max_rows": None},
        "iterative_supervised": {
            "question_value": "Q1", "sample_size": 12, "random_state": 42,
            "label_delimiter": "|", "minimum_labeled_rows": 6,
            "embedding_model": "fake-model", "embedding_batch_size": 8,
            "probability_threshold": 0.4, "uncertain_label": "UNCERTAIN_REVIEW",
            "sampling": sampling,
            "output_dir": str(out_dir),
            "unsupervised": {"fixed_k": 2, "min_k": 2, "max_k": 3, "random_state": 42,
                             "top_terms_per_cluster": 5, "sample_quotes_per_cluster": 2},
        },
    }


@pytest.fixture
def mocked_embeddings():
    with patch("core.embedding_cache.build_embeddings", side_effect=_fake_embeddings):
        yield


class TestIterativeFlow:
    def test_create_sample_writes_sampling_note(self, tmp_path, mocked_embeddings):
        out = tmp_path / "out"
        iter_mod.create_coding_sample(_config(_input_csv(tmp_path), out, sampling="stratified"))
        assert (out / "coding_sample.csv").exists()
        note = (out / "sampling_note.txt").read_text(encoding="utf-8")
        assert "stratified" in note.lower()

    def test_full_round_produces_training_flag_and_cv_quality(self, tmp_path, mocked_embeddings):
        out = tmp_path / "out"
        cfg = _config(_input_csv(tmp_path), out, sampling="random")
        iter_mod.create_coding_sample(cfg)

        # Human codes the sample.
        sample = pd.read_csv(out / "coding_sample.csv")
        sample["human_labels"] = ["cost" if "cost" in t else "belonging"
                                  for t in sample["response_text"]]
        sample.to_csv(out / "coding_sample.csv", index=False)

        iter_mod.train_and_apply(cfg)

        preds = pd.read_csv(out / "iterative_predictions.csv")
        # 2.2: the training-row flag exists and marks the coded rows.
        assert "in_training_sample" in preds.columns
        assert preds["in_training_sample"].sum() >= 6

        # 2.3: quality report is cross-validated, not a single holdout.
        quality = (out / "supervised_training_quality.txt").read_text(encoding="utf-8")
        assert "cross-validated" in quality.lower()

    def test_uncertainty_sampling_uses_prior_predictions(self, tmp_path, mocked_embeddings):
        """Second sampling round orders by the first round's uncertainty."""
        out = tmp_path / "out"
        cfg = _config(_input_csv(tmp_path, n=24), out, sampling="auto")
        iter_mod.create_coding_sample(cfg)
        sample = pd.read_csv(out / "coding_sample.csv")
        sample["human_labels"] = ["cost" if "cost" in t else "belonging"
                                  for t in sample["response_text"]]
        sample.to_csv(out / "coding_sample.csv", index=False)
        iter_mod.train_and_apply(cfg)

        # Now a fresh sample round should read predictions and go uncertainty-based.
        iter_mod.create_coding_sample(cfg)
        note = (out / "sampling_note.txt").read_text(encoding="utf-8")
        assert "uncertain" in note.lower()
