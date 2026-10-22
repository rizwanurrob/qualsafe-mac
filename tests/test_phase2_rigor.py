"""
Tests for Phase 2 — rigor upgrades (v3.2).

Sampling (2.1), tiny-sample cross-validated quality (2.3), per-engine strict
thresholds (2.4), and multi-coder groundwork (2.5). The training-row flag (2.2)
is exercised where it feeds agreement.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analysis.quality import choose_cv_scheme, cross_val_per_code, format_quality_report
from analysis.sampling import (
    SAMPLING_CAVEATS,
    order_ids_by_uncertainty,
    row_uncertainty,
    stratified_sample_indices,
)


# ── 2.1 sampling ─────────────────────────────────────────────────────────────

class TestUncertainty:
    def test_row_uncertainty_is_min_distance_to_half(self):
        # 0.55 is closest to 0.5 -> distance 0.05.
        assert row_uncertainty({"a": 0.9, "b": 0.55, "c": 0.1}) == pytest.approx(0.05)

    def test_empty_prediction_is_maximally_uncertain(self):
        assert row_uncertainty({}) == 0.0

    def test_order_most_uncertain_first(self):
        probs = {
            "sure": {"a": 0.98},          # distance 0.48
            "unsure": {"a": 0.52},        # distance 0.02
            "middling": {"a": 0.7},       # distance 0.20
        }
        assert order_ids_by_uncertainty(probs) == ["unsure", "middling", "sure"]

    def test_order_skips_already_coded(self):
        probs = {"a": {"x": 0.5}, "b": {"x": 0.51}}
        assert order_ids_by_uncertainty(probs, already_coded=["a"]) == ["b"]

    def test_order_is_deterministic_on_ties(self):
        probs = {"z": {"x": 0.5}, "a": {"x": 0.5}}
        assert order_ids_by_uncertainty(probs) == ["a", "z"]  # tie broken by id


class TestStratifiedSample:
    def test_returns_requested_count(self):
        labels = [0] * 10 + [1] * 10 + [2] * 10
        assert len(stratified_sample_indices(labels, 9)) == 9

    def test_spreads_across_clusters(self):
        labels = [0] * 30 + [1] * 30 + [2] * 30
        idx = stratified_sample_indices(labels, 9, random_state=1)
        chosen_clusters = {labels[i] for i in idx}
        assert chosen_clusters == {0, 1, 2}  # every cluster represented

    def test_proportional_allocation(self):
        # Cluster 0 is 80% of the data -> should get ~80% of a large sample.
        labels = [0] * 80 + [1] * 20
        idx = stratified_sample_indices(labels, 10, random_state=1)
        from_cluster_0 = sum(1 for i in idx if labels[i] == 0)
        assert from_cluster_0 == 8

    def test_handles_cluster_smaller_than_allocation(self):
        labels = [0] * 2 + [1] * 50  # cluster 0 can't fill a proportional share
        idx = stratified_sample_indices(labels, 20, random_state=1)
        assert len(idx) == 20  # tops up from the larger cluster

    def test_n_larger_than_data_returns_all(self):
        labels = [0, 1, 2]
        assert sorted(stratified_sample_indices(labels, 99)) == [0, 1, 2]

    def test_caveats_exist_for_every_strategy(self):
        for key in ("uncertainty", "stratified", "random"):
            assert key in SAMPLING_CAVEATS and "sample" in SAMPLING_CAVEATS[key].lower()


# ── 2.3 tiny-sample quality ──────────────────────────────────────────────────

class TestCvScheme:
    def test_too_small(self):
        assert choose_cv_scheme(4)["scheme"] == "too_small"

    def test_leave_one_out_under_30(self):
        s = choose_cv_scheme(15)
        assert s["scheme"] == "leave_one_out"
        assert s["n_splits"] == 15

    def test_k_fold_at_30_plus(self):
        assert choose_cv_scheme(50)["scheme"] == "k_fold"


class TestCrossValPerCode:
    def _separable(self, n_per_class=10):
        """Two codes, each perfectly separable in feature space."""
        rng = np.random.default_rng(0)
        X_a = np.hstack([rng.normal(5, 0.3, (n_per_class, 1)), rng.normal(0, 0.3, (n_per_class, 1))])
        X_b = np.hstack([rng.normal(0, 0.3, (n_per_class, 1)), rng.normal(5, 0.3, (n_per_class, 1))])
        X = np.vstack([X_a, X_b])
        labels = [["A"]] * n_per_class + [["B"]] * n_per_class
        return X, labels

    def test_separable_codes_score_well(self):
        X, labels = self._separable(10)
        result = cross_val_per_code(X, labels, classes=["A", "B"], min_support=3)
        by_code = {c["code"]: c for c in result["codes"]}
        assert by_code["A"]["f1"] > 0.8
        assert by_code["B"]["f1"] > 0.8

    def test_low_support_codes_are_suppressed(self):
        X, labels = self._separable(10)
        labels[0] = ["A", "Rare"]  # 'Rare' appears once
        result = cross_val_per_code(X, labels, classes=["A", "B", "Rare"], min_support=5)
        rare = next(c for c in result["codes"] if c["code"] == "Rare")
        assert rare["f1"] is None
        assert "insufficient_support" in rare["note"]

    def test_loo_used_for_small_sample(self):
        X, labels = self._separable(7)  # 14 rows -> LOO
        result = cross_val_per_code(X, labels, classes=["A", "B"], min_support=3)
        assert result["scheme"] == "leave_one_out"

    def test_fixed_classes_survive_a_fold_missing_a_label(self):
        """A label absent from a fold's train set must not shift columns."""
        X, labels = self._separable(8)
        # Report should still contain both codes with aligned metrics.
        result = cross_val_per_code(X, labels, classes=["A", "B"], min_support=3)
        assert {c["code"] for c in result["codes"]} == {"A", "B"}

    def test_report_formats(self):
        X, labels = self._separable(8)
        text = format_quality_report(cross_val_per_code(X, labels, classes=["A", "B"], min_support=3))
        assert "cross-validated" in text.lower()


# ── 2.4 per-engine strict thresholds ─────────────────────────────────────────

class TestPerEngineThresholds:
    def _config(self):
        return {
            "strict_thresholds": {
                "transformer": {"top1_min_score": 0.55, "min_margin_over_second": 0.10},
                "llm": {"top1_min_score": 0.70, "min_margin_over_second": 0.15},
            },
            "zero_shot": {"strict_coding": {"enabled": True, "top1_min_score": 0.0,
                                            "min_margin_over_second": 0.0}},
        }

    def test_active_engine_overlays_thresholds(self):
        from analyze_survey import apply_engine_strict_thresholds

        cfg = self._config()
        apply_engine_strict_thresholds(cfg, "llm")
        sc = cfg["zero_shot"]["strict_coding"]
        assert sc["top1_min_score"] == 0.70
        assert sc["min_margin_over_second"] == 0.15

    def test_transformer_gets_its_own_pair(self):
        from analyze_survey import apply_engine_strict_thresholds

        cfg = self._config()
        apply_engine_strict_thresholds(cfg, "transformer")
        assert cfg["zero_shot"]["strict_coding"]["top1_min_score"] == 0.55

    def test_legacy_flat_config_is_untouched(self):
        from analyze_survey import apply_engine_strict_thresholds

        cfg = {"zero_shot": {"strict_coding": {"enabled": True, "top1_min_score": 0.42,
                                               "min_margin_over_second": 0.08}}}
        apply_engine_strict_thresholds(cfg, "transformer")
        assert cfg["zero_shot"]["strict_coding"]["top1_min_score"] == 0.42  # unchanged

    def test_disabled_strict_block_not_overlaid(self):
        from analyze_survey import apply_engine_strict_thresholds

        cfg = self._config()
        cfg["zero_shot"]["strict_coding"]["enabled"] = False
        apply_engine_strict_thresholds(cfg, "llm")
        assert cfg["zero_shot"]["strict_coding"]["top1_min_score"] == 0.0  # untouched


# ── 2.5 multi-coder groundwork ───────────────────────────────────────────────

class TestMultiCoder:
    def _store_with_two_coders(self, path):
        from core.model import Source
        from core.populate import record_human_codings
        from core.project import Project, new_id

        with Project.create(path) as p:
            for rid in ("r1", "r2", "r3", "r4", "r5", "r6"):
                src = Source(source_id=new_id("src"), type="survey_response",
                             raw_text=f"text {rid}", label="Q1",
                             metadata={"response_id": rid, "question_text": "Q1"})
                p.add_source(src)
                p.add_whole_response_excerpt(src)

        primary = {"r1": ["A"], "r2": ["A"], "r3": ["B"], "r4": ["B"], "r5": ["A"], "r6": ["B"]}
        secondary = {"r1": ["A"], "r2": ["B"], "r3": ["B"], "r4": ["B"], "r5": ["A"], "r6": ["B"]}
        record_human_codings(path, primary, question_text="Q1", rater_id="human_primary")
        record_human_codings(path, secondary, question_text="Q1", rater_id="human_secondary")
        return path

    def test_rater_labels_shape(self, tmp_path):
        from core.project import Project

        path = self._store_with_two_coders(tmp_path / "mc.qnw")
        with Project.open(path) as p:
            primary = p.rater_labels("human_primary")
            assert len(primary) == 6
            assert all(isinstance(v, set) for v in primary.values())

    def test_human_vs_human_kappa_from_existing_function(self, tmp_path):
        """The whole point: κ falls out of per_code_kappa with no new stats code."""
        from analysis.agreement import per_code_kappa
        from core.project import Project

        path = self._store_with_two_coders(tmp_path / "mc2.qnw")
        with Project.open(path) as p:
            k = per_code_kappa(
                p.rater_labels("human_primary"),
                p.rater_labels("human_secondary"),
                min_support=1,
            )
        assert not k.empty
        assert set(k["code"]) == {"A", "B"}

    def test_second_coder_import_from_csv(self, tmp_path):
        from core.populate import import_second_coder_sample
        from core.project import Project

        path = self._store_with_two_coders(tmp_path / "mc3.qnw")  # already has both
        # A colleague's CSV re-coding the same items.
        csv = tmp_path / "colleague.csv"
        pd.DataFrame({
            "response_id": ["r1", "r2", "r3"],
            "human_labels": ["A", "A", "B"],
        }).to_csv(csv, index=False)

        result = import_second_coder_sample(path, csv, rater_id="human_tertiary", question_text="Q1")
        assert result["applications"] == 3
        with Project.open(path) as p:
            assert "human_tertiary" in p.rater_ids()
