"""
Transformation layer: filters, and the recode that turns source labels into
display labels. Every function takes a frame or series and returns a new one;
the loaded data is never touched.

The recode order is fixed and documented because it decides what an analyst sees:

    source label -> (excluded?) -> merged into a new category? -> renamed -> shown

Exclusion is checked against the source label *and* the merged label, so the
analyst can drop either "Freshman" or the "Undergraduate" group it became part of.

Nothing here merges silently. Two labels renamed to the same text, or one label
placed in two merges, is reported by `recode_problems` and the build refuses
until it is fixed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional

import numpy as np
import pandas as pd

from core.chartbuilder import clean
from core.chartbuilder.config import FilterRule, Recode


# ── filters ───────────────────────────────────────────────────────────────────

def _numeric(labels: pd.Series) -> pd.Series:
    return pd.to_numeric(labels.astype(object).where(labels.notna()), errors="coerce")


def filter_mask(frame: pd.DataFrame, rules: Iterable[FilterRule], *,
                collapse_whitespace: bool = False,
                missing_tokens: Optional[Iterable[str]] = None) -> pd.Series:
    """Rows that pass every rule. A rule on an unknown column is an error."""
    mask = pd.Series(True, index=frame.index)
    for rule in rules:
        if rule.column not in frame.columns:
            raise KeyError(f"Filter column '{rule.column}' is not in the data.")
        labels = clean.normalize_series(
            frame[rule.column], collapse_whitespace=collapse_whitespace,
            missing_tokens=missing_tokens)
        values = [str(v).strip() for v in rule.values]
        op = rule.op
        if op == "eq":
            hit = labels == (values[0] if values else None)
        elif op == "ne":
            hit = labels.notna() & (labels != (values[0] if values else None))
        elif op == "in":
            hit = labels.isin(values)
        elif op == "not_in":
            hit = labels.notna() & ~labels.isin(values)
        elif op in ("gt", "ge", "lt", "le"):
            number, target = _numeric(labels), float(values[0])
            hit = {"gt": number > target, "ge": number >= target,
                   "lt": number < target, "le": number <= target}[op]
        elif op == "between":
            number = _numeric(labels)
            lo, hi = sorted(float(v) for v in values[:2])
            hit = (number >= lo) & (number <= hi)
        elif op == "contains":
            hit = labels.fillna("").str.contains(values[0], case=False,
                                                 regex=False) if values else labels.notna()
        elif op == "is_missing":
            hit = labels.isna()
        elif op == "not_missing":
            hit = labels.notna()
        else:
            raise ValueError(f"Unknown filter operator '{op}'.")
        mask &= hit.fillna(False).astype(bool)
    return mask


# ── recode ────────────────────────────────────────────────────────────────────

@dataclass
class Recoded:
    """The result of recoding one column."""
    display: pd.Series      # display label per row; NaN for missing/excluded
    source: pd.Series       # cleaned source label per row (NaN when missing)
    missing: pd.Series      # bool: blank or a missing token
    excluded: pd.Series     # bool: valid but excluded by the analyst


def recode_problems(recode: Recode, categories: Iterable[str]) -> List[str]:
    """Sentences for merge/rename collisions. Empty means the recode is safe."""
    out: List[str] = []
    seen: Dict[str, str] = {}
    for merge in recode.merges:
        if not merge.label.strip():
            out.append("A combined category needs a name.")
        for member in merge.members:
            if member in seen and seen[member] != merge.label:
                out.append(f"'{member}' is in both '{seen[member]}' and "
                           f"'{merge.label}'. A category can be combined only once.")
            seen[member] = merge.label
    merged_labels = {m.label for m in recode.merges}
    shown: Dict[str, set] = {}
    for cat in categories:
        key = seen.get(cat, cat)
        shown.setdefault(recode.rename.get(key, key), set()).add(key)
    for label, keys in shown.items():
        if len(keys) > 1:
            out.append(f"'{label}' would be the display name of "
                       f"{', '.join(repr(k) for k in sorted(keys))}. "
                       f"Rename one of them, or combine them deliberately.")
    if recode.missing_label in merged_labels:
        out.append(f"'{recode.missing_label}' is also the name of a combined "
                   f"category; pick a different name for one.")
    return out


def apply_recode(labels: pd.Series, recode: Recode) -> Recoded:
    """Source labels -> display labels under `recode`. `labels` is cleaned."""
    missing = labels.isna()
    member_to_merge = {m: mg.label for mg in reversed(recode.merges)
                       for m in mg.members}
    merged = labels.map(lambda v: member_to_merge.get(v, v) if isinstance(v, str) else v)
    exclude = set(recode.exclude)
    excluded = (~missing) & (labels.isin(exclude) | merged.isin(exclude))
    shown = merged.map(lambda v: recode.rename.get(v, v) if isinstance(v, str) else v)
    shown = shown.where(~excluded, np.nan)
    return Recoded(display=shown.astype(object), source=labels,
                   missing=missing, excluded=excluded)
