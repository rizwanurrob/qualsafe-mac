#!/usr/bin/env python
"""
Code × descriptor cross-tabs (v3, Phase 3) — the mixed-methods analysis.

How a code's prevalence distributes across subgroups (theme by class year, by
program, by first-gen status, ...). Counts are **distinct sources** per (code,
value), so a respondent isn't double-counted. Normalization by group size gives
the apples-to-apples comparison across unequal groups (prevalence per respondent),
and a DescriptorField orders ordinal/numeric columns correctly.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import pandas as pd

from core.model import DescriptorField


def join_descriptors(coding_df: pd.DataFrame, descriptor_df: pd.DataFrame,
                     *, prefix: str = "") -> pd.DataFrame:
    """Widen the long descriptor table and join it onto codings, one row per coding.

    `code_by_descriptor` answers one question about one descriptor. This returns
    the whole analysable frame — every coding with every descriptor beside it —
    which is what a general chart builder needs to plot a theme against class
    year, program, and first-generation status without three separate calls.

    A left join, deliberately: a source with no descriptors keeps its codings and
    gets nulls, because dropping it would silently shrink a frequency chart.

    `prefix` guards the one real collision risk — a descriptor called `weight` or
    `coder` would otherwise overwrite a coding column.
    """
    if coding_df.empty or descriptor_df.empty or "source_id" not in coding_df.columns:
        return coding_df.copy()

    wide = descriptor_df.pivot_table(
        index="source_id", columns="key", values="value", aggfunc="first")
    wide.columns = [f"{prefix}{column}" for column in wide.columns]
    wide = wide.reset_index()

    clashes = (set(wide.columns) & set(coding_df.columns)) - {"source_id"}
    if clashes:
        wide = wide.rename(columns={c: f"descriptor_{c}" for c in clashes})

    return coding_df.merge(wide, on="source_id", how="left")


def code_by_descriptor(
    coding_df: pd.DataFrame,
    descriptor_df: pd.DataFrame,
    descriptor_key: str,
    *,
    field: Optional[DescriptorField] = None,
    normalize: Optional[str] = None,   # None | "group_size" | "column" | "row"
) -> Tuple[pd.DataFrame, Dict[Tuple[str, str], List[str]]]:
    """Cross-tabulate distinct-source code counts by a descriptor's values.

    - coding_df: needs code_name, source_id (one row per application).
    - descriptor_df: long [source_id, key, value].
    - normalize="group_size": each cell becomes % of that subgroup's sources coded
      with the code (recommended for comparing unequal groups); "column"/"row"
      give share-of-applications percentages; None gives raw distinct-source counts.

    Returns (table[code_name × value], drill{(code_name, value): [source_ids]}).
    """
    dvals = descriptor_df[descriptor_df["key"] == descriptor_key][["source_id", "value"]].copy()
    merged = coding_df.merge(dvals, on="source_id", how="inner")
    if merged.empty:
        return pd.DataFrame(), {}

    counts = merged.groupby(["code_name", "value"])["source_id"].nunique().reset_index(name="n")
    table = counts.pivot(index="code_name", columns="value", values="n").fillna(0).astype(int)

    drill: Dict[Tuple[str, str], List[str]] = {}
    for (code, val), grp in merged.groupby(["code_name", "value"]):
        drill[(code, val)] = sorted(set(grp["source_id"].tolist()))

    # Order columns: DescriptorField-aware if provided, else lexicographic.
    if field is not None:
        ordered = sorted(table.columns, key=field.sort_key)
    else:
        ordered = sorted(table.columns, key=lambda v: str(v))
    table = table[ordered]

    if normalize == "group_size":
        group_sizes = dvals.groupby("value")["source_id"].nunique()
        table = (table.div(group_sizes.reindex(table.columns), axis=1) * 100).round(2)
    elif normalize == "column":
        table = (table.div(table.sum(axis=0), axis=1) * 100).round(2)
    elif normalize == "row":
        table = (table.div(table.sum(axis=1), axis=0) * 100).round(2)

    return table, drill
