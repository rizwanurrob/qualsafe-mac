#!/usr/bin/env python
"""
Code co-occurrence (v3, Phase 3).

Which codes land on the same excerpt — the analysis researchers reach for to see
conceptual relationships and spot redundant codes to merge.

IMPORTANT interpretation note: in survey mode the excerpt is the WHOLE response,
so "co-occurrence" here means two codes were applied to the same respondent's
answer (co-mention within a respondent), which is a looser association than
Dedoose's same-span co-occurrence. Read the heatmap accordingly. (Sub-response
excerpts, which would tighten this, are a v3.1 item.)
"""

from __future__ import annotations

from typing import Dict, List, Tuple

import pandas as pd


def cooccurrence_matrix(
    coding_df: pd.DataFrame, label_col: str = "code_name", group_col: str = "excerpt_id",
) -> Tuple[pd.DataFrame, Dict[Tuple[str, str], List[str]]]:
    """Symmetric code × code co-occurrence over a grouping unit.

    Diagonal = number of units containing that code; off-diagonal = number of
    units where both codes co-occur. `group_col` chooses the unit:
    ``excerpt_id`` (default; whole-response co-mention in survey mode),
    ``source_id`` (per response), or ``respondent_id`` (all of one person's
    answers together — the wide-form cross-question view, Feature B). Returns
    (matrix, drill) where drill[(a, b)] with a < b lists the unit ids behind that
    pair's count. Required columns: `group_col`, `label_col`.
    """
    codes = sorted(coding_df[label_col].dropna().unique().tolist())
    matrix = pd.DataFrame(0, index=codes, columns=codes, dtype=int)
    drill: Dict[Tuple[str, str], List[str]] = {}
    if coding_df.empty or group_col not in coding_df.columns:
        return matrix, drill

    for unit_id, grp in coding_df.groupby(group_col):
        present = sorted(set(grp[label_col].dropna().tolist()))
        for i, a in enumerate(present):
            matrix.at[a, a] += 1
            for b in present[i + 1:]:
                matrix.at[a, b] += 1
                matrix.at[b, a] += 1
                drill.setdefault((a, b), []).append(str(unit_id))
    return matrix, drill


def cooccurrence_jaccard(matrix: pd.DataFrame) -> pd.DataFrame:
    """Normalize a co-occurrence matrix to Jaccard similarity.

    jaccard(a, b) = co(a, b) / (n_a + n_b - co(a, b)); diagonal is 1.0. This is
    the size-independent view — high off-diagonal Jaccard + high embedding
    similarity is the signal for a merge suggestion (that pairing lands in v3.1).
    """
    diag = {c: float(matrix.at[c, c]) for c in matrix.index}
    out = matrix.astype(float).copy()
    for a in matrix.index:
        for b in matrix.columns:
            co = float(matrix.at[a, b])
            denom = diag[a] + diag[b] - co
            out.at[a, b] = (co / denom) if denom > 0 else 0.0
    return out
