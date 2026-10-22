#!/usr/bin/env python
"""
Validation metrics for structured (Laya-assisted) coding, over a human-coded
calibration sample (Alt Survey Flow).

`analysis/agreement.py::per_code_kappa` already gives the right reliability
number (kappa, with percent agreement and prevalence as the kappa-paradox
guardrail) -- this module does not reimplement it, and does not add a second
notion of "agreement". What it adds is what a *supervised-coding* workflow also
needs and kappa does not answer on its own: **which class of mistake** the model
is making. A code with kappa 0.55 could be missing real instances (low recall)
or over-applying itself (low precision), and those imply opposite fixes --
tighten the threshold, or write a narrower inclusion_criteria. Precision/recall/
F1 are standard classification-evaluation metrics with well-known chance-
agreement problems of their own (a rare code gets high precision from doing
almost nothing), which is exactly why they are reported ALONGSIDE kappa here,
never instead of it.

Same convention as `analysis/agreement.py`: pure functions over
`{item_id: set(code_names)}` dicts, a per-code binary decision, `min_support`
guarding against a number computed from too few items to mean anything.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence, Set

import pandas as pd

from analysis.agreement import DEFAULT_MIN_SUPPORT, per_code_kappa


def _binary_prf(human: List[bool], model: List[bool]) -> Dict[str, float]:
    """Precision/recall/F1 for one binary code, treating the human sample as
    ground truth and the model as the classifier being evaluated -- the
    conventional framing (unlike kappa, which is symmetric between two coders;
    here the direction matters and is stated in every docstring downstream)."""
    n = len(human)
    tp = sum(1 for i in range(n) if human[i] and model[i])
    fp = sum(1 for i in range(n) if not human[i] and model[i])
    fn = sum(1 for i in range(n) if human[i] and not model[i])
    precision = tp / (tp + fp) if (tp + fp) else float("nan")
    recall = tp / (tp + fn) if (tp + fn) else float("nan")
    if math.isnan(precision) or math.isnan(recall) or (precision + recall) == 0:
        f1 = float("nan")
    else:
        f1 = 2 * precision * recall / (precision + recall)
    return {"tp": tp, "fp": fp, "fn": fn, "precision": precision, "recall": recall, "f1": f1}


def per_code_validation(
    human: Dict[str, Set[str]], model: Dict[str, Set[str]],
    *, codes: Optional[Sequence[str]] = None, min_support: int = DEFAULT_MIN_SUPPORT,
) -> pd.DataFrame:
    """Per-code precision/recall/F1 (human = ground truth) PLUS kappa/percent
    agreement/prevalence from `per_code_kappa`, joined into one table -- so a
    reviewer sees both the reliability number and the error breakdown for the
    same code without cross-referencing two calls with potentially different
    item sets. Same `min_support` gate as kappa: below it, precision/recall/F1
    are left NaN with the same 'insufficient_support' note, because a code seen
    twice cannot have a meaningful precision either.
    """
    kappa_df = per_code_kappa(human, model, codes=codes, min_support=min_support)
    if kappa_df.empty:
        return kappa_df.assign(precision=[], recall=[], f1=[], tp=[], fp=[], fn=[])

    items = sorted(set(human) & set(model))
    prf_rows = []
    for code in kappa_df["code"]:
        h = [code in human[it] for it in items]
        m = [code in model[it] for it in items]
        reliable = bool(kappa_df.loc[kappa_df["code"] == code, "reliable"].iloc[0])
        if not reliable:
            prf_rows.append({"code": code, "tp": 0, "fp": 0, "fn": 0,
                             "precision": float("nan"), "recall": float("nan"), "f1": float("nan")})
            continue
        stats = _binary_prf(h, m)
        prf_rows.append({"code": code, **{k: (round(v, 4) if isinstance(v, float) else v)
                                          for k, v in stats.items()}})

    prf_df = pd.DataFrame(prf_rows)
    return kappa_df.merge(prf_df, on="code", how="left")


def validation_summary(validation_df: pd.DataFrame) -> Dict[str, float]:
    """Macro-averaged precision/recall/F1 over reliable codes, alongside the
    mean/weighted-mean kappa `agreement_summary` already reports -- kept
    separate rather than merged into that function so a caller that only wants
    kappa (most callers) is unaffected by this module existing."""
    reliable = validation_df[validation_df["reliable"] & validation_df["f1"].notna()]
    if reliable.empty:
        return {"n_codes": int(len(validation_df)), "n_reliable": 0,
                "macro_precision": float("nan"), "macro_recall": float("nan"),
                "macro_f1": float("nan")}
    return {
        "n_codes": int(len(validation_df)),
        "n_reliable": int(len(reliable)),
        "macro_precision": round(float(reliable["precision"].mean()), 4),
        "macro_recall": round(float(reliable["recall"].mean()), 4),
        "macro_f1": round(float(reliable["f1"].mean()), 4),
    }


def calibration_curve(
    scores: Sequence[float], outcomes: Sequence[bool], *, n_bins: int = 10,
) -> pd.DataFrame:
    """Reliability diagram data: for each score bin, the model's mean predicted
    score vs. the human-confirmed rate in that bin -- the actual empirical check
    for whether a Laya score may be shown to a user as a probability.

    This is deliberately NOT called anywhere in engines/laya_engine.py or the UI
    layer that would eventually consume it. Per this project's stated rule
    (engines/laya_engine.py's module docstring), a score is labelled a model
    score, never a probability, UNTIL this curve has actually been computed
    against a real human-coded sample and shown to track the diagonal --
    Laya's own docs report its base checkpoints do NOT, out of the box (Expected
    Calibration Error 0.466 before per-question-type temperature scaling). A
    caller who has run this and wants to fit a temperature-scaling correction
    should do so explicitly and change the labelling deliberately, not as a side
    effect of this function existing.
    """
    n = len(scores)
    if n == 0 or n != len(outcomes):
        return pd.DataFrame(columns=["bin_low", "bin_high", "n", "mean_score", "observed_rate"])
    rows = []
    for i in range(n_bins):
        low, high = i / n_bins, (i + 1) / n_bins
        in_bin = [j for j in range(n) if low <= scores[j] < high or (i == n_bins - 1 and scores[j] == high)]
        if not in_bin:
            continue
        rows.append({
            "bin_low": round(low, 2), "bin_high": round(high, 2), "n": len(in_bin),
            "mean_score": round(sum(scores[j] for j in in_bin) / len(in_bin), 4),
            "observed_rate": round(sum(1 for j in in_bin if outcomes[j]) / len(in_bin), 4),
        })
    return pd.DataFrame(rows)
