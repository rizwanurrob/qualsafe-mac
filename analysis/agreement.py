#!/usr/bin/env python
"""
Human-vs-AI inter-rater reliability (v3, Phase 4).

Reframes Dedoose's inter-rater apparatus for the AI era: treat the model as one
coder and the analyst's human-coded sample (the iterative workflow's
`human_labels`) as the other, and compute **per-code Cohen's kappa** over the
shared set of items. This gives a rigorous, publishable number for how much the
automated coding can be trusted — and a per-code breakdown of where it's reliable
vs. where it needs human review.

Methodology (agreed with the project owner):
- Qualitative coding is multi-label, so kappa is computed **per code** as a binary
  present/absent decision across the shared items (not one multinomial kappa).
- Kappa-only — no Gwet's AC1 / Krippendorff's alpha in v3.0. BUT percent agreement
  and prevalence fall directly out of the same 2×2, so they're reported as adjacent
  columns: if a reviewer questions a low kappa on a rare code, the answer
  (the kappa paradox) is already visible in the table.
- Codes with support below `min_support` are marked *insufficient-N* (kappa left as
  NaN) rather than emitting an unstable, misleading number.
- Low-kappa (and insufficient) codes are exactly what to route to human review.

Pure functions over dict inputs (item_id -> set of labels), plus a small adapter
from the delimited label columns the tool already produces.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence, Set

import pandas as pd

DEFAULT_MIN_SUPPORT = 5


class CrossUnitComparisonError(ValueError):
    """Raised when agreement is requested across different units of analysis."""


def assert_comparable_units(unit_a: str, unit_b: str) -> None:
    """Refuse to compare agreement computed at different units of analysis (v4).

    A kappa over response-level codings and one over sentence-level codings measure
    different things — the item sets aren't the same objects — so they must never
    be compared or pooled. Callers that know both runs' `unit` (from the manifest)
    pass them here before comparing.
    """
    if str(unit_a) != str(unit_b):
        raise CrossUnitComparisonError(
            f"Cannot compare agreement across units: '{unit_a}' vs '{unit_b}'. "
            f"Kappa at the response level and at the sentence level are not "
            f"comparable — re-run both at the same unit."
        )


def labels_from_delimited(
    df: pd.DataFrame,
    id_col: str = "response_id",
    label_col: str = "human_labels",
    delimiter: str = "|",
    drop_values: Sequence[str] = ("UNCERTAIN_REVIEW",),
) -> Dict[str, Set[str]]:
    """Build {item_id: set(labels)} from a delimited label column.

    Works for the human sample (`human_labels` in coding_sample.csv) and for the
    model (`zshot_strict_label` in responses_scored.csv). `drop_values` removes
    sentinel non-labels like UNCERTAIN_REVIEW.
    """
    drop = set(drop_values)
    out: Dict[str, Set[str]] = {}
    for _, row in df.iterrows():
        rid = str(row[id_col])
        raw = row.get(label_col, "")
        if raw is None or (isinstance(raw, float) and math.isnan(raw)):
            raw = ""
        labels = {p.strip() for p in str(raw).split(delimiter) if p.strip() and p.strip() not in drop}
        out[rid] = labels
    return out


def _binary_kappa(h: List[bool], m: List[bool]) -> Dict[str, float]:
    """Cohen's kappa for one binary code across aligned items."""
    n = len(h)
    a = sum(1 for i in range(n) if h[i] and m[i])       # both applied
    b = sum(1 for i in range(n) if h[i] and not m[i])   # human only
    c = sum(1 for i in range(n) if not h[i] and m[i])   # model only
    d = n - a - b - c                                    # neither
    po = (a + d) / n if n else float("nan")
    p_h = (a + b) / n if n else 0.0                      # human positive rate
    p_m = (a + c) / n if n else 0.0                      # model positive rate
    pe = p_h * p_m + (1 - p_h) * (1 - p_m)               # chance agreement
    denom = 1 - pe
    if n == 0:
        kappa = float("nan")
    elif denom <= 1e-12:
        # A coder never varies -> chance correction undefined. Degenerate:
        # perfect observed agreement is 1.0, otherwise 0.0.
        kappa = 1.0 if po >= 1.0 - 1e-12 else 0.0
    else:
        kappa = (po - pe) / denom
    return {"po": po, "p_h": p_h, "p_m": p_m, "n_both": a, "kappa": kappa}


def per_code_kappa(
    human: Dict[str, Set[str]],
    model: Dict[str, Set[str]],
    *,
    codes: Optional[Sequence[str]] = None,
    min_support: int = DEFAULT_MIN_SUPPORT,
) -> pd.DataFrame:
    """Per-code human-vs-AI Cohen's kappa over the shared items.

    Only items present in BOTH `human` and `model` (the overlap set) are used.
    `codes` defaults to the union of labels either coder applied. Returns one row
    per code with kappa, percent agreement, prevalence (human/model), counts, and
    a `reliable` flag (support >= min_support).
    """
    cols = ["code", "n_items", "n_human", "n_model", "n_both", "percent_agreement",
            "prevalence_human", "prevalence_model", "kappa", "reliable", "note"]
    items = sorted(set(human) & set(model))
    if not items:
        return pd.DataFrame(columns=cols)

    if codes is None:
        universe: Set[str] = set()
        for it in items:
            universe |= set(human[it]) | set(model[it])
        codes = sorted(universe)

    n = len(items)
    rows = []
    for code in codes:
        h = [code in human[it] for it in items]
        m = [code in model[it] for it in items]
        stats = _binary_kappa(h, m)
        n_human, n_model = sum(h), sum(m)
        n_either = sum(1 for i in range(n) if h[i] or m[i])
        reliable = n_either >= min_support
        rows.append({
            "code": code, "n_items": n, "n_human": n_human, "n_model": n_model,
            "n_both": stats["n_both"],
            "percent_agreement": round(stats["po"], 4),
            "prevalence_human": round(stats["p_h"], 4),
            "prevalence_model": round(stats["p_m"], 4),
            "kappa": (round(stats["kappa"], 4) if reliable and not math.isnan(stats["kappa"]) else float("nan")),
            "reliable": reliable,
            "note": "" if reliable else f"insufficient_support(<{min_support})",
        })

    df = pd.DataFrame(rows, columns=cols)
    return df.sort_values(["reliable", "kappa"], ascending=[False, True], na_position="last").reset_index(drop=True)


def agreement_summary(kappa_df: pd.DataFrame) -> Dict[str, float]:
    """Aggregate over reliable codes: mean and support-weighted mean kappa.

    Reported explicitly as an average of per-code binary kappas (not a single
    multinomial kappa), so the number is interpreted correctly.
    """
    reliable = kappa_df[kappa_df["reliable"] & kappa_df["kappa"].notna()]
    if reliable.empty:
        return {"n_codes": int(len(kappa_df)), "n_reliable": 0,
                "mean_kappa": float("nan"), "weighted_mean_kappa": float("nan")}
    weights = reliable["n_human"] + reliable["n_model"] - reliable["n_both"]  # n_either
    wmean = (reliable["kappa"] * weights).sum() / weights.sum() if weights.sum() else float("nan")
    return {
        "n_codes": int(len(kappa_df)),
        "n_reliable": int(len(reliable)),
        "mean_kappa": round(float(reliable["kappa"].mean()), 4),
        "weighted_mean_kappa": round(float(wmean), 4),
    }


def low_agreement_codes(kappa_df: pd.DataFrame, threshold: float = 0.6) -> List[str]:
    """Codes to route to human review: reliable codes below `threshold`, plus any
    flagged insufficient (not yet trustworthy). 0.6 ~ the usual 'substantial'
    kappa floor."""
    if kappa_df.empty:
        return []
    low = kappa_df["reliable"] & kappa_df["kappa"].notna() & (kappa_df["kappa"] < threshold)
    insufficient = ~kappa_df["reliable"]
    return kappa_df[low | insufficient]["code"].tolist()
