#!/usr/bin/env python
"""
Code frequency (v3, Phase 3).

How often each code was applied, with drill-back excerpt ids behind every count.
Pure function over a coding table (from Project.coding_table()).
"""

from __future__ import annotations

import pandas as pd


def code_frequency(coding_df: pd.DataFrame, *, weighted: bool = False) -> pd.DataFrame:
    """Count applications per code.

    Required columns: code_id, code_name, excerpt_id (+ weight when weighted=True).
    Returns a frame sorted by count desc with columns:
    code_id, code_name, n, excerpt_ids (drill-back), and mean_weight when weighted.
    """
    base_cols = ["code_id", "code_name", "n", "excerpt_ids"]
    cols = base_cols + (["mean_weight"] if weighted else [])
    if coding_df.empty:
        return pd.DataFrame(columns=cols)

    grouped = coding_df.groupby(["code_id", "code_name"], dropna=False)
    out = (grouped["excerpt_id"].agg(list).reset_index()
           .rename(columns={"excerpt_id": "excerpt_ids"}))
    out["n"] = out["excerpt_ids"].map(len)
    if weighted:
        mw = grouped["weight"].mean().reset_index().rename(columns={"weight": "mean_weight"})
        out = out.merge(mw, on=["code_id", "code_name"])
    out = out.sort_values("n", ascending=False).reset_index(drop=True)
    return out[cols]
