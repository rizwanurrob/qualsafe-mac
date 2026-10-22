#!/usr/bin/env python
"""
Adapters: ResponseCoding lists -> the v2.1 DataFrame column layout.

These mirror analyze_survey.add_zero_shot_columns / add_strict_coding_columns
exactly (same column names, same value formatting, same assignment order), so
routing the survey pipeline's coding through an engine leaves outputs
byte-identical. Kept separate from the engine so the engine stays free of pandas.
"""

from __future__ import annotations

from typing import List, Sequence

import pandas as pd

from engines.base import ResponseCoding


def add_zero_shot_columns_from_codings(
    df: pd.DataFrame,
    codings: Sequence[ResponseCoding],
    prefix: str,
) -> pd.DataFrame:
    """Reproduce add_zero_shot_columns() from a list of ResponseCoding.

    Column order and formatting match the v2.1 function:
      <prefix>_top_label, <prefix>_top_score, <prefix>_all_labels, <prefix>_all_scores
    """
    top_label: List[str] = [c.top_label for c in codings]
    top_score: List[float] = [c.top_score for c in codings]
    all_labels: List[str] = [c.all_labels_str() for c in codings]
    all_scores: List[str] = [c.all_scores_str() for c in codings]
    return df.assign(**{
        f"{prefix}_top_label": top_label,
        f"{prefix}_top_score": top_score,
        f"{prefix}_all_labels": all_labels,
        f"{prefix}_all_scores": all_scores,
    })


def add_strict_coding_columns_from_codings(
    df: pd.DataFrame,
    codings: Sequence[ResponseCoding],
    prefix: str,
) -> pd.DataFrame:
    """Reproduce add_strict_coding_columns() from a list of ResponseCoding.

    Expects the codings to already carry strict-gate outputs (the engine
    populates them when a strict_coding config is supplied). Column order matches
    the v2.1 function:
      <prefix>_strict_label, <prefix>_strict_confident, <prefix>_strict_reason,
      <prefix>_strict_margin
    """
    return df.assign(**{
        f"{prefix}_strict_label": [c.strict_label for c in codings],
        f"{prefix}_strict_confident": [c.strict_confident for c in codings],
        f"{prefix}_strict_reason": [c.strict_reason for c in codings],
        f"{prefix}_strict_margin": [c.strict_margin for c in codings],
    })
