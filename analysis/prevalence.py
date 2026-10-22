#!/usr/bin/env python
"""
Prevalence of a code within groups, with honest intervals (V7 Update 2, U1).

"Is financial stress more common among Pell students?" and "is it rising
across survey waves?" are the commonest questions an institutional researcher
asks of coded open-ended data, and until now the answer was a bare percentage.
With groups of 30-300 respondents, the difference between 29% and 34% is
mostly sampling noise, and a table that doesn't say so invites a finding.

Two standard, well-behaved intervals:

* **Wilson score interval** for one proportion. Unlike the textbook "Wald"
  interval it stays inside [0, 1] and keeps close to nominal coverage at the
  small n and extreme proportions qualitative data produces (Wilson 1927;
  Newcombe 1998a, method 3).
* **Newcombe's hybrid score interval** for a difference of two independent
  proportions, built from the two Wilson intervals (Newcombe 1998b,
  method 10). It is what a between-group or between-wave comparison needs.

The unit is the **respondent** (distinct source), matching the Code ×
Descriptor tab's "% within group": k respondents with the code out of n
respondents in the group.

What these intervals do not cover, stated with every table: they describe
sampling variation only. A machine-coded prevalence also moves when the coder
changes (a new model, new thresholds, drift in how people write), and no
interval sees that; a human-coded sample per group or wave is the check.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple

import pandas as pd

Z_95 = 1.959963984540054
#: Below this many respondents in a group, an interval is shown but flagged.
SMALL_GROUP = 30
#: Below this many respondents *with* the code, the same flag.
SMALL_COUNT = 5

CAVEATS = [
    "Intervals are 95% Wilson score intervals: they describe sampling variation "
    "only, for respondents like these.",
    "A change in a machine-coded prevalence can be a change in the coder (a new "
    "model or threshold) rather than in respondents. A human-coded sample from "
    "each group or wave is the check; no interval can see it.",
    f"Groups under {SMALL_GROUP} respondents, or with fewer than {SMALL_COUNT} "
    f"respondents coded, are flagged: their intervals are wide and the "
    f"percentage alone is misleading.",
]


def wilson_interval(k: int, n: int, z: float = Z_95) -> Tuple[float, float]:
    """95% Wilson score interval for k successes out of n. (nan, nan) if n == 0."""
    if n <= 0:
        return float("nan"), float("nan")
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def newcombe_difference(k1: int, n1: int, k2: int, n2: int,
                        z: float = Z_95) -> Tuple[float, float, float]:
    """p1 - p2 with Newcombe's hybrid score (method 10) 95% interval."""
    if n1 <= 0 or n2 <= 0:
        return float("nan"), float("nan"), float("nan")
    p1, p2 = k1 / n1, k2 / n2
    l1, u1 = wilson_interval(k1, n1, z)
    l2, u2 = wilson_interval(k2, n2, z)
    d = p1 - p2
    lower = d - math.sqrt((p1 - l1) ** 2 + (u2 - p2) ** 2)
    upper = d + math.sqrt((u1 - p1) ** 2 + (p2 - l2) ** 2)
    return d, lower, upper


def prevalence_table(
    coding_df: pd.DataFrame,
    descriptor_df: pd.DataFrame,
    descriptor_key: str,
    *,
    rater_id: Optional[str] = None,
) -> pd.DataFrame:
    """One row per (code, group): k, n, prevalence, Wilson interval, flag.

    `coding_df` needs ``code_name, source_id`` (and ``rater_id`` when filtering);
    `descriptor_df` is long ``[source_id, key, value]``. n is every respondent
    with that descriptor value -- coded or not -- so a group where nobody used
    the code still appears, at 0%.
    """
    cols = ["code", "group", "k", "n", "prevalence", "ci_low", "ci_high", "flag"]
    groups = descriptor_df[descriptor_df["key"] == descriptor_key][["source_id", "value"]]
    if groups.empty:
        return pd.DataFrame(columns=cols)
    coding = coding_df
    if rater_id is not None and "rater_id" in coding.columns:
        coding = coding[coding["rater_id"] == rater_id]
    n_by_group = groups.groupby("value")["source_id"].nunique()
    coded = coding.merge(groups, on="source_id", how="inner")
    k_by = coded.groupby(["code_name", "value"])["source_id"].nunique()

    rows: List[Dict] = []
    for code in sorted(coding["code_name"].dropna().unique()):
        for group, n in n_by_group.items():
            k = int(k_by.get((code, group), 0))
            lo, hi = wilson_interval(k, int(n))
            flag = ""
            if n < SMALL_GROUP:
                flag = f"small group (n<{SMALL_GROUP})"
            elif k < SMALL_COUNT:
                flag = f"few coded (k<{SMALL_COUNT})"
            rows.append({"code": code, "group": group, "k": k, "n": int(n),
                         "prevalence": k / n if n else float("nan"),
                         "ci_low": lo, "ci_high": hi, "flag": flag})
    return pd.DataFrame(rows, columns=cols)


def compare_groups(table: pd.DataFrame, code: str, group_a, group_b) -> Dict:
    """Difference in prevalence for one code between two groups (a - b)."""
    def _row(group):
        match = table[(table["code"] == code) & (table["group"] == group)]
        if match.empty:
            raise KeyError(f"no row for code {code!r} in group {group!r}")
        return match.iloc[0]

    a, b = _row(group_a), _row(group_b)
    d, lo, hi = newcombe_difference(int(a["k"]), int(a["n"]), int(b["k"]), int(b["n"]))
    return {"code": code, "group_a": group_a, "group_b": group_b,
            "prevalence_a": a["prevalence"], "prevalence_b": b["prevalence"],
            "difference": d, "ci_low": lo, "ci_high": hi,
            "excludes_zero": bool(lo > 0 or hi < 0),
            "flag": "; ".join(f for f in (a["flag"], b["flag"]) if f)}


def pooling_caveat(coding_df: pd.DataFrame) -> str:
    """Say so when the codings come from more than one coder (none if one)."""
    if "rater_id" not in coding_df.columns:
        return ""
    raters = sorted(coding_df["rater_id"].dropna().unique())
    if len(raters) <= 1:
        return ""
    return (f"{len(raters)} coders contributed ({', '.join(raters)}): a respondent counts "
            f"as coded if any of them applied the code. Choose one coder to report a "
            f"prevalence someone actually asserted.")


def display_table(table: pd.DataFrame) -> pd.DataFrame:
    """The interval table as both front ends show it: percentages as text, the
    interval beside its estimate, counts kept so the base is never hidden."""
    if table.empty:
        return pd.DataFrame(columns=["code", "group", "coded / group", "prevalence",
                                     "95% interval", "flag"])
    return pd.DataFrame({
        "code": table["code"],
        "group": table["group"].astype(str),
        "coded / group": [f"{k} / {n}" for k, n in zip(table["k"], table["n"])],
        "prevalence": [f"{p:.1%}" for p in table["prevalence"]],
        "95% interval": [f"{lo:.1%} – {hi:.1%}" for lo, hi in zip(table["ci_low"], table["ci_high"])],
        "flag": table["flag"],
    }).reset_index(drop=True)


def describe_difference(result: Dict) -> str:
    """One sentence for a group comparison, in the analyst's words."""
    verdict = ("the interval excludes zero" if result["excludes_zero"]
               else "the interval includes zero, so sampling noise alone could produce it")
    text = (f"{result['code']}: {result['prevalence_a']:.1%} in {result['group_a']} vs "
            f"{result['prevalence_b']:.1%} in {result['group_b']}, a difference of "
            f"{result['difference'] * 100:+.1f} points (95% interval "
            f"{result['ci_low'] * 100:+.1f} to {result['ci_high'] * 100:+.1f}); {verdict}.")
    if result["flag"]:
        text += f" Flagged: {result['flag']}."
    return text
