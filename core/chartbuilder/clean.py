"""
Cleaning rules for the chart builder: what counts as missing, and how labels are
normalised. Pure functions over pandas objects; the source frame is never
modified, every function returns a new Series.

Decisions worth keeping
-----------------------
- **Missing tokens are matched exactly, case-insensitively, after stripping.**
  ``"None"`` and ``"NA"`` are on the list because survey exports write them for
  "no answer", and they are also real answers ("None of the above" is a
  different string and is not matched). The profile reports which tokens were
  found and how many, so a legitimate "None" is visible rather than silently
  dropped, and the token list is a config field the analyst can change.
- **Similar labels are reported, never merged.** ``similar_label_groups`` finds
  labels that differ only in whitespace or case. Merging them is the analyst's
  call (a checkbox), because "Yes" and "yes" being one category is usually right
  and sometimes a data-entry finding worth seeing.
"""

from __future__ import annotations

import re
from typing import Dict, Iterable, List, Optional, Sequence

import numpy as np
import pandas as pd

#: The tokens the brief names. Blank is the empty string after stripping.
DEFAULT_MISSING_TOKENS: Sequence[str] = (
    "", "NULL", "null", "NaN", "None", "N/A", "NA", "(blank)", "<null>")

_WS = re.compile(r"\s+")


def token_set(tokens: Optional[Iterable[str]] = None) -> frozenset:
    """Lower-cased, stripped tokens, ready for membership tests."""
    source = DEFAULT_MISSING_TOKENS if tokens is None else tokens
    return frozenset(str(t).strip().lower() for t in source)


def label_of(value) -> Optional[str]:
    """One cell as a display label, or None when the cell is empty.

    Whole floats lose their ``.0`` (an Excel column of 1, 2, 3 arrives as
    floats and would otherwise chart as "1.0", "2.0"); booleans read as
    True/False; timestamps as ISO dates.
    """
    if value is None:
        return None
    if isinstance(value, float):
        if np.isnan(value):
            return None
        return str(int(value)) if value.is_integer() else repr(value)
    if isinstance(value, (bool, np.bool_)):
        return "True" if value else "False"
    if isinstance(value, pd.Timestamp):
        return value.isoformat(sep=" ") if value.time() != pd.Timestamp(0).time() \
            else value.date().isoformat()
    if value is pd.NaT or value is pd.NA:
        return None
    return str(value)


def normalize_series(series: pd.Series, *, collapse_whitespace: bool = False,
                     missing_tokens: Optional[Iterable[str]] = None) -> pd.Series:
    """Labels with leading/trailing whitespace stripped and missing as NaN.

    Always strips the ends (a trailing space makes "Yes " a different category
    from "Yes" and is never intended). Collapsing *repeated internal* whitespace
    is optional because it changes what a label says.
    """
    tokens = token_set(missing_tokens)

    def clean(value):
        text = label_of(value)
        if text is None:
            return np.nan
        text = text.strip()
        if collapse_whitespace:
            text = _WS.sub(" ", text)
        if text.lower() in tokens:
            return np.nan
        return text

    return series.map(clean).astype(object)


_THOUSANDS = re.compile(r"^[-+]?[$£€]?\d{1,3}(,\d{3})+(\.\d+)?$")


def to_numbers(series: pd.Series, *, collapse_whitespace: bool = False,
               missing_tokens: Optional[Iterable[str]] = None) -> pd.Series:
    """Cells as floats; NaN for blanks, missing tokens and anything not a number.

    A number written with thousands separators ("1,234.5") or a leading currency
    sign is read as a number; nothing else is guessed at, and text stays NaN. Use
    `count_non_numeric` to tell the analyst how many cells that was.
    """
    labels = normalize_series(series, collapse_whitespace=collapse_whitespace,
                              missing_tokens=missing_tokens)

    def parse(text):
        if not isinstance(text, str):
            return np.nan
        if _THOUSANDS.match(text):
            text = text.replace(",", "").lstrip("$£€")
        try:
            return float(text)
        except ValueError:
            return np.nan

    return labels.map(parse).astype(float)


def count_non_numeric(series: pd.Series, numbers: pd.Series,
                      missing_tokens: Optional[Iterable[str]] = None) -> int:
    """Cells with an answer that `to_numbers` could not read as a number."""
    answered = normalize_series(series, missing_tokens=missing_tokens).notna()
    return int((answered & numbers.isna()).sum())


def missing_mask(series: pd.Series,
                 missing_tokens: Optional[Iterable[str]] = None) -> pd.Series:
    """True where the cell is empty or one of the missing tokens."""
    return normalize_series(series, missing_tokens=missing_tokens).isna()


def token_hits(series: pd.Series,
               missing_tokens: Optional[Iterable[str]] = None) -> Dict[str, int]:
    """How many cells matched each *non-blank* token, by the token as written.

    Lets the profile say "12 cells are 'None'" so a legitimate answer that
    happens to be on the list is visible.
    """
    tokens = token_set(missing_tokens)
    counts: Dict[str, int] = {}
    for value in series:
        text = label_of(value)
        if text is None:
            continue
        stripped = text.strip()
        if stripped and stripped.lower() in tokens:
            counts[stripped] = counts.get(stripped, 0) + 1
    return counts


def similar_label_groups(labels: Iterable[str]) -> List[dict]:
    """Groups of distinct labels that look alike, with the reason.

    ``reason`` is ``"whitespace"`` when the labels are identical once all runs of
    whitespace are collapsed, or ``"case"`` when they also need case folding.
    Nothing is merged; the caller offers it.
    """
    buckets: Dict[str, List[str]] = {}
    for label in dict.fromkeys(labels):
        buckets.setdefault(_WS.sub(" ", label.strip()).casefold(), []).append(label)
    groups = []
    for members in buckets.values():
        if len(members) < 2:
            continue
        folded = {_WS.sub(" ", m.strip()) for m in members}
        groups.append({"labels": members,
                       "reason": "whitespace" if len(folded) == 1 else "case"})
    return groups
