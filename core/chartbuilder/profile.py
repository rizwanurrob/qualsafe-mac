"""
Data profiling: what each column looks like before anything is charted.

Types are *inferred and proposed*, never imposed: the analyst can chart a numeric
1-5 column as categories (a Likert item usually is), and the profile says when
that is probably what they want.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional

import numpy as np
import pandas as pd

from core.chartbuilder import clean

CATEGORICAL = "categorical"
NUMERIC = "numeric"
DATETIME = "datetime"
BOOLEAN = "boolean"
TEXT = "text"
EMPTY = "empty"
KINDS = (CATEGORICAL, NUMERIC, DATETIME, BOOLEAN, TEXT, EMPTY)

#: A categorical column with more distinct values than this draws a warning.
HIGH_CARDINALITY = 30
#: Below this many valid responses a percentage is shown with a caution.
SMALL_N = 30
#: Numeric columns with at most this many whole-number values look like scales.
NUMERIC_AS_CATEGORY_MAX_UNIQUE = 12
#: Mean length above which a string column is free text.
TEXT_MEAN_LENGTH = 60

_BOOL_WORDS = {"true", "false", "t", "f"}
_DATE_HINT = re.compile(
    r"^\s*(\d{4}[-/.]\d{1,2}[-/.]\d{1,2}|\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}|"
    r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}|"
    r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{1,4}|"
    r"\d{1,2}\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec))",
    re.IGNORECASE)

#: Candidate multi-select delimiters and their display names.
DELIMITERS = {"comma": ",", "semicolon": ";", "pipe": "|", "newline": "\n"}


@dataclass
class ColumnProfile:
    name: str
    kind: str
    n_rows: int
    n_missing: int
    n_unique: int
    samples: List[str] = field(default_factory=list)
    missing_tokens_found: Dict[str, int] = field(default_factory=dict)
    numeric_like_scale: bool = False        # numeric, but looks like a coded scale
    multiselect_delimiter: Optional[str] = None
    warnings: List[str] = field(default_factory=list)

    @property
    def n_valid(self) -> int:
        return self.n_rows - self.n_missing

    def as_row(self) -> dict:
        """One line of the field-inspector table."""
        return {"Field": self.name, "Type": self.kind, "Valid": self.n_valid,
                "Missing": self.n_missing, "Unique": self.n_unique,
                "Examples": " | ".join(self.samples[:3])}


@dataclass
class TableProfile:
    n_rows: int
    n_cols: int
    columns: List[ColumnProfile]

    def column(self, name: str) -> ColumnProfile:
        for col in self.columns:
            if col.name == name:
                return col
        raise KeyError(name)

    def by_kind(self, kind: str) -> List[str]:
        return [c.name for c in self.columns if c.kind == kind]

    def as_frame(self) -> pd.DataFrame:
        return pd.DataFrame([c.as_row() for c in self.columns])


def _is_numeric(values: pd.Series) -> bool:
    if values.empty:
        return False
    if pd.api.types.is_numeric_dtype(values) and not pd.api.types.is_bool_dtype(values):
        return True
    if values.map(lambda v: isinstance(v, (int, float, np.number))
                  and not isinstance(v, (bool, np.bool_))).all():
        return True
    strings = values.astype(str).str.strip()
    return not pd.to_numeric(strings, errors="coerce").isna().any()


def _is_boolean(raw: pd.Series, labels: pd.Series) -> bool:
    if pd.api.types.is_bool_dtype(raw):
        return True
    if raw.map(lambda v: isinstance(v, (bool, np.bool_))).all() and len(raw):
        return True
    return bool(len(labels)) and set(labels.str.lower()) <= _BOOL_WORDS


def _is_datetime(raw: pd.Series, labels: pd.Series) -> bool:
    if pd.api.types.is_datetime64_any_dtype(raw):
        return True
    if raw.map(lambda v: isinstance(v, (pd.Timestamp, np.datetime64))).all() and len(raw):
        return True
    if labels.empty or not labels.map(lambda s: bool(_DATE_HINT.match(s))).all():
        return False
    parsed = pd.to_datetime(labels, errors="coerce", format="mixed")
    return bool(parsed.notna().all())


def detect_multiselect_delimiter(labels: pd.Series) -> Optional[str]:
    """The delimiter that makes this look like a select-all column, or None.

    A column is a candidate when a real share of cells split into several short
    pieces *and those pieces repeat across respondents*. Free text splits on
    commas too, but its pieces almost never repeat; a select-all column's do.
    """
    if labels.empty:
        return None
    best, best_score = None, 0.0
    for name, delim in DELIMITERS.items():
        parts = labels.map(lambda s: [p.strip() for p in s.split(delim) if p.strip()])
        multi_share = float((parts.map(len) > 1).mean())
        if multi_share < 0.15:
            continue
        flat = [p for row in parts for p in row]
        if not flat:
            continue
        counts = pd.Series(flat).value_counts()
        distinct = len(counts)
        repeat = len(flat) / distinct
        # In a select-all column nearly every piece is a repeat of a choice;
        # prose that merely contains commas has mostly one-off pieces.
        repeated_share = float(counts[counts >= 2].sum()) / len(flat)
        if repeated_share < 0.8:
            continue
        mean_len = float(np.mean([len(p) for p in flat]))
        if repeat >= 2 and mean_len <= 60 and distinct <= 80:
            score = multi_share * repeat
            if score > best_score:
                best, best_score = name, score
    return best


def profile_column(series: pd.Series, *,
                   missing_tokens: Optional[Iterable[str]] = None) -> ColumnProfile:
    name = str(series.name)
    labels_all = clean.normalize_series(series, missing_tokens=missing_tokens)
    valid_mask = labels_all.notna()
    labels = labels_all[valid_mask].astype(str)
    raw_valid = series[valid_mask]
    n_rows, n_missing = int(len(series)), int((~valid_mask).sum())
    hits = clean.token_hits(series, missing_tokens)
    n_unique = int(labels.nunique())
    samples = [str(v) for v in pd.unique(labels)[:5]]

    profile = ColumnProfile(name=name, kind=CATEGORICAL, n_rows=n_rows,
                            n_missing=n_missing, n_unique=n_unique,
                            samples=samples, missing_tokens_found=hits)
    if labels.empty:
        profile.kind = EMPTY
        profile.warnings.append("Every value in this field is empty.")
        return profile

    if _is_boolean(raw_valid, labels):
        profile.kind = BOOLEAN
    elif _is_datetime(raw_valid, labels):
        profile.kind = DATETIME
    elif _is_numeric(raw_valid):
        profile.kind = NUMERIC
        numbers = pd.to_numeric(labels, errors="coerce")
        profile.numeric_like_scale = bool(
            n_unique <= NUMERIC_AS_CATEGORY_MAX_UNIQUE
            and (numbers % 1 == 0).all())
    else:
        delimiter = detect_multiselect_delimiter(labels)
        if delimiter:
            profile.multiselect_delimiter = delimiter
            profile.warnings.append(
                f"Cells in this field contain several answers separated by "
                f"{delimiter}. Treat it as select-all-that-apply to count each "
                f"choice; charting it as one category per cell counts whole "
                f"combinations.")
        elif float(labels.str.len().mean()) > TEXT_MEAN_LENGTH:
            profile.kind = TEXT
        elif n_unique > HIGH_CARDINALITY and n_unique / len(labels) > 0.5:
            profile.kind = TEXT

    if profile.kind == CATEGORICAL and n_unique > HIGH_CARDINALITY:
        profile.warnings.append(
            f"{n_unique} distinct values: a chart of this many categories is "
            f"hard to read. Filter, group, or keep the top few.")
    if profile.numeric_like_scale:
        profile.warnings.append(
            "Numeric field with few whole-number values. If these are scale "
            "codes (1-5), chart it as categories; otherwise chart it as a "
            "measure.")
    if hits:
        found = ", ".join(f"'{t}' ({n})" for t, n in sorted(hits.items()))
        profile.warnings.append(
            f"Treated as missing, so left out of percentages: {found}. If one "
            f"of these is a real answer, remove it from the missing-value list.")
    return profile


def profile_table(frame: pd.DataFrame, *,
                  missing_tokens: Optional[Iterable[str]] = None) -> TableProfile:
    columns = [profile_column(frame[c], missing_tokens=missing_tokens)
               for c in frame.columns]
    return TableProfile(n_rows=int(len(frame)), n_cols=int(len(frame.columns)),
                        columns=columns)
