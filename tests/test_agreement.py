"""
Tests for analysis/agreement.py — human-vs-AI per-code Cohen's kappa.

Covers the kappa arithmetic (hand-computed expected values), the kappa paradox
(high percent agreement + low kappa on a rare code, both surfaced), the
insufficient-support flag, overlap handling, the delimited adapter, the summary,
and low-agreement routing.
"""

from __future__ import annotations

import math
from pathlib import Path

import pandas as pd

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analysis.agreement import (
    agreement_summary, labels_from_delimited, low_agreement_codes, per_code_kappa,
)


def _items(human_map, model_map):
    return {k: set(v) for k, v in human_map.items()}, {k: set(v) for k, v in model_map.items()}


class TestPerCodeKappa:
    def test_known_kappa_value(self):
        # code A: human on items 0-4, model on 0-3 and 5 -> po=0.8, pe=0.5, kappa=0.6
        ids = [str(i) for i in range(10)]
        human = {i: (["A"] if int(i) in {0, 1, 2, 3, 4} else []) for i in ids}
        model = {i: (["A"] if int(i) in {0, 1, 2, 3, 5} else []) for i in ids}
        h, m = _items(human, model)
        df = per_code_kappa(h, m, min_support=3)
        row = df[df["code"] == "A"].iloc[0]
        assert row["percent_agreement"] == 0.8
        assert row["prevalence_human"] == 0.5 and row["prevalence_model"] == 0.5
        assert abs(row["kappa"] - 0.6) < 1e-9
        assert row["reliable"]

    def test_perfect_agreement_is_one(self):
        ids = [str(i) for i in range(8)]
        human = {i: (["A"] if int(i) < 3 else []) for i in ids}
        h, m = _items(human, human)  # identical coders
        df = per_code_kappa(h, m, min_support=2)
        assert df[df["code"] == "A"].iloc[0]["kappa"] == 1.0

    def test_kappa_paradox_reported(self):
        # Rare code, coders disagree on the two positives: high %agreement, low kappa.
        ids = [str(i) for i in range(10)]
        human = {i: (["R"] if int(i) == 0 else []) for i in ids}
        model = {i: (["R"] if int(i) == 1 else []) for i in ids}
        h, m = _items(human, model)
        df = per_code_kappa(h, m, min_support=2)  # allow it through to show the paradox
        row = df[df["code"] == "R"].iloc[0]
        assert row["percent_agreement"] == 0.8      # agree on 8 absences
        assert row["kappa"] < 0                       # but chance-corrected is negative
        assert row["reliable"]

    def test_insufficient_support_flagged_not_numbered(self):
        ids = [str(i) for i in range(10)]
        human = {i: (["Q"] if int(i) == 0 else []) for i in ids}
        model = {i: (["Q"] if int(i) == 0 else []) for i in ids}
        h, m = _items(human, model)
        df = per_code_kappa(h, m, min_support=5)  # only 1 positive -> insufficient
        row = df[df["code"] == "Q"].iloc[0]
        assert not row["reliable"]
        assert math.isnan(row["kappa"])
        assert "insufficient_support" in row["note"]

    def test_only_overlap_items_used(self):
        human = {"1": {"A"}, "2": {"A"}, "3": {"A"}}
        model = {"2": {"A"}, "3": {"A"}, "4": {"A"}}  # overlap = {2,3}
        df = per_code_kappa(human, model, min_support=1)
        assert df[df["code"] == "A"].iloc[0]["n_items"] == 2

    def test_empty_overlap_returns_empty(self):
        df = per_code_kappa({"1": {"A"}}, {"2": {"A"}})
        assert df.empty


class TestAdapterAndSummary:
    def test_labels_from_delimited_drops_uncertain(self):
        df = pd.DataFrame([
            {"response_id": "r1", "human_labels": "A|B"},
            {"response_id": "r2", "human_labels": "UNCERTAIN_REVIEW"},
            {"response_id": "r3", "human_labels": None},
        ])
        out = labels_from_delimited(df)
        assert out["r1"] == {"A", "B"}
        assert out["r2"] == set()      # sentinel dropped
        assert out["r3"] == set()      # NaN -> empty

    def test_summary_weighted_mean(self):
        # Two reliable codes with different support/kappa.
        kdf = pd.DataFrame([
            {"code": "A", "n_human": 5, "n_model": 5, "n_both": 5, "kappa": 1.0, "reliable": True},
            {"code": "B", "n_human": 10, "n_model": 8, "n_both": 6, "kappa": 0.5, "reliable": True},
        ])
        s = agreement_summary(kdf)
        assert s["n_reliable"] == 2
        assert s["mean_kappa"] == 0.75
        # weights: A n_either=5, B n_either=12 -> (1.0*5 + 0.5*12)/17
        assert abs(s["weighted_mean_kappa"] - (5 + 6) / 17) < 1e-3

    def test_low_agreement_routing(self):
        kdf = pd.DataFrame([
            {"code": "good", "kappa": 0.85, "reliable": True},
            {"code": "weak", "kappa": 0.4, "reliable": True},
            {"code": "rare", "kappa": float("nan"), "reliable": False},
        ])
        routed = set(low_agreement_codes(kdf, threshold=0.6))
        assert routed == {"weak", "rare"}
