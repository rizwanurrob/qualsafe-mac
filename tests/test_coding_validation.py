"""analysis/coding_validation.py -- precision/recall/F1 layered on the existing
per_code_kappa, plus a calibration curve, over a human-coded calibration sample."""

from __future__ import annotations

import math

from analysis.coding_validation import (
    calibration_curve,
    per_code_validation,
    validation_summary,
)


def test_perfect_agreement_gives_precision_recall_f1_of_one():
    human = {f"i{i}": {"Cost"} for i in range(10)}
    model = {f"i{i}": {"Cost"} for i in range(10)}
    df = per_code_validation(human, model, min_support=1)
    row = df[df["code"] == "Cost"].iloc[0]
    assert row["precision"] == 1.0
    assert row["recall"] == 1.0
    assert row["f1"] == 1.0
    assert row["kappa"] == 1.0   # sanity: kappa agrees this is perfect too


def test_model_over_applies_hurts_precision_not_recall():
    """Model assigns the code to everything; human only assigns it to half."""
    human = {f"i{i}": ({"Cost"} if i < 5 else set()) for i in range(10)}
    model = {f"i{i}": {"Cost"} for i in range(10)}
    df = per_code_validation(human, model, min_support=1)
    row = df[df["code"] == "Cost"].iloc[0]
    assert row["recall"] == 1.0          # every human-coded item was caught
    assert row["precision"] == 0.5       # but half the model's yeses were wrong


def test_model_under_applies_hurts_recall_not_precision():
    """Model assigns the code sparingly; every one it picks is correct."""
    human = {f"i{i}": ({"Cost"} if i < 5 else set()) for i in range(10)}
    model = {f"i{i}": ({"Cost"} if i < 2 else set()) for i in range(10)}
    df = per_code_validation(human, model, min_support=1)
    row = df[df["code"] == "Cost"].iloc[0]
    assert row["precision"] == 1.0
    assert row["recall"] == 0.4


def test_below_min_support_is_left_nan_with_a_note():
    human = {"i1": {"Rare"}, "i2": set()}
    model = {"i1": {"Rare"}, "i2": set()}
    df = per_code_validation(human, model, codes=["Rare"], min_support=5)
    row = df[df["code"] == "Rare"].iloc[0]
    assert math.isnan(row["precision"])
    assert math.isnan(row["recall"])
    assert math.isnan(row["f1"])
    assert not row["reliable"]


def test_empty_input_returns_an_empty_frame_with_the_right_columns():
    df = per_code_validation({}, {})
    assert df.empty
    assert {"precision", "recall", "f1", "kappa"} <= set(df.columns)


def test_kappa_columns_are_still_present_alongside_prf():
    human = {"i1": {"A"}, "i2": {"A"}, "i3": set(), "i4": set(), "i5": {"A"}}
    model = {"i1": {"A"}, "i2": set(), "i3": set(), "i4": set(), "i5": {"A"}}
    df = per_code_validation(human, model, min_support=1)
    assert {"kappa", "percent_agreement", "prevalence_human", "prevalence_model"} <= set(df.columns)


# ── validation_summary ────────────────────────────────────────────────────────

def test_validation_summary_macro_averages_reliable_codes():
    human = {f"i{i}": {"A"} for i in range(10)}
    human.update({f"j{i}": {"B"} for i in range(10)})
    model = dict(human)   # perfect on both codes
    df = per_code_validation(human, model, min_support=1)
    summary = validation_summary(df)
    assert summary["macro_precision"] == 1.0
    assert summary["macro_recall"] == 1.0
    assert summary["macro_f1"] == 1.0
    assert summary["n_reliable"] == 2


def test_validation_summary_on_no_reliable_codes_is_nan_not_a_crash():
    human = {"i1": {"Rare"}}
    model = {"i1": {"Rare"}}
    df = per_code_validation(human, model, codes=["Rare"], min_support=5)
    summary = validation_summary(df)
    assert summary["n_reliable"] == 0
    assert math.isnan(summary["macro_f1"])


# ── calibration_curve ─────────────────────────────────────────────────────────

def test_calibration_curve_well_calibrated_scores_track_the_diagonal():
    # Scores near 0.9 that are usually right, scores near 0.1 that are usually wrong.
    scores = [0.9] * 20 + [0.1] * 20
    outcomes = [True] * 18 + [False] * 2 + [False] * 18 + [True] * 2
    df = calibration_curve(scores, outcomes, n_bins=10)
    high_bin = df[df["bin_low"] == 0.9]
    low_bin = df[df["bin_low"] == 0.1]
    assert not high_bin.empty and high_bin.iloc[0]["observed_rate"] > 0.8
    assert not low_bin.empty and low_bin.iloc[0]["observed_rate"] < 0.2


def test_calibration_curve_overconfident_scores_show_the_gap():
    """A model that says 0.9 but is right only half the time -- exactly the
    'ships over-confident' failure mode Laya's own docs describe."""
    scores = [0.9] * 20
    outcomes = [True] * 10 + [False] * 10
    df = calibration_curve(scores, outcomes, n_bins=10)
    row = df.iloc[0]
    assert row["mean_score"] > row["observed_rate"] + 0.3   # a real, visible gap


def test_calibration_curve_empty_input_returns_empty_frame():
    df = calibration_curve([], [])
    assert df.empty
    assert "observed_rate" in df.columns


def test_calibration_curve_mismatched_lengths_returns_empty_frame():
    df = calibration_curve([0.5, 0.6], [True])
    assert df.empty
