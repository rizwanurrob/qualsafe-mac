#!/usr/bin/env python
"""
Ingestion reshaping helpers (v3).

Survey exports come in two common shapes:

- LONG: one column holds response text, another holds the question. This is what
  the v2.1 pipeline already consumes directly.
- WIDE: each question is its own column; the column header IS the question and
  responses fill the column. Multi-question surveys usually export this way.

`reshape_wide_to_long` melts a wide frame into the long shape the pipeline
expects, turning each selected question column into rows tagged with that
question, while carrying an id column and any descriptor columns through so they
remain attached to every response (feeding the descriptor/mixed-methods work).

Pure functions, no model dependencies — tested offline.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence

import pandas as pd

RESPONSE_TEXT_COL = "response_text"
QUESTION_TEXT_COL = "question_text"
RESPONDENT_ID_COL = "respondent_id"


def reshape_wide_to_long(
    df: pd.DataFrame,
    question_columns: Sequence[str],
    id_column: Optional[str] = None,
    descriptor_columns: Optional[Sequence[str]] = None,
    question_labels: Optional[Dict[str, str]] = None,
) -> pd.DataFrame:
    """Melt a wide survey frame into long (one row per response per question).

    Parameters
    ----------
    df : DataFrame
        The wide survey frame.
    question_columns : sequence of str
        Columns each holding responses to one question; the header (or its
        `question_labels` override) becomes the question text.
    id_column : str, optional
        A respondent/row id to carry through (so a wide row stays linkable).
    descriptor_columns : sequence of str, optional
        Non-text columns (demographics etc.) to carry onto every melted row.
    question_labels : dict, optional
        {column_name: display_question} to rename headers to full question text.

    Returns
    -------
    DataFrame with columns: [id_column?] + descriptor_columns + [question_text, response_text].

    Raises
    ------
    ValueError if none of `question_columns` are present in `df`.
    """
    descriptor_columns = list(descriptor_columns or [])
    question_labels = dict(question_labels or {})

    present_q = [c for c in question_columns if c in df.columns]
    if not present_q:
        raise ValueError(
            "None of the selected question columns are in the data: "
            f"{list(question_columns)}"
        )

    # id_vars carried through the melt: id first (if any), then descriptors,
    # de-duplicated and restricted to columns that actually exist.
    id_vars: List[str] = []
    for col in ([id_column] if id_column else []) + descriptor_columns:
        if col and col in df.columns and col not in id_vars and col not in present_q:
            id_vars.append(col)

    # A wide row IS one respondent, so a respondent id is available even without an
    # explicit id column (the row index). Carry it as `respondent_id` so downstream
    # can group a person's answers across questions (Feature B). This is distinct
    # from response_id, which must stay unique *per answer* — using the (repeated)
    # respondent id as response_id is exactly the wide-form collision the ingestion
    # warning flags.
    work = df.copy()
    if id_column and id_column in work.columns:
        work[RESPONDENT_ID_COL] = work[id_column].astype(str)
    else:
        work[RESPONDENT_ID_COL] = [f"resp_{i}" for i in range(len(work))]
    if RESPONDENT_ID_COL not in id_vars:
        id_vars = [RESPONDENT_ID_COL] + id_vars

    melted = work.melt(
        id_vars=id_vars,
        value_vars=present_q,
        var_name=QUESTION_TEXT_COL,
        value_name=RESPONSE_TEXT_COL,
    )

    # Map header -> full question text where an override was provided.
    if question_labels:
        melted[QUESTION_TEXT_COL] = melted[QUESTION_TEXT_COL].map(
            lambda c: question_labels.get(c, c)
        )

    # A unique per-answer response_id: respondent + question. Keeps the coding /
    # agreement / store join keys unique while respondent_id enables grouping.
    melted["response_id"] = (
        melted[RESPONDENT_ID_COL].astype(str) + "__" + melted[QUESTION_TEXT_COL].astype(str)
    )

    # Stable column order: response_id, respondent_id, other ids/descriptors, then
    # question, then response.
    lead = ["response_id", RESPONDENT_ID_COL]
    rest = [c for c in id_vars if c not in lead]
    ordered = lead + rest + [QUESTION_TEXT_COL, RESPONSE_TEXT_COL]
    return melted[ordered]


def strip_qualtrics_metadata(df: "pd.DataFrame") -> tuple:
    """Remove Qualtrics's extra header rows if present. Returns (df, n_removed).

    A standard Qualtrics CSV carries the machine header on row 1, then 1–2
    metadata rows: the human-readable question text and an ``{"ImportId": …}``
    row. Read naively, those become "responses" — the ImportId JSON gets coded as
    a student's answer. Detection: any cell containing ``ImportId`` within the
    first three rows marks it and everything above it as metadata.

    No-op (0 removed) for normal files, so it's safe to run on every load.
    """
    n_scan = min(3, len(df))
    metadata_end = -1
    for i in range(n_scan):
        row_text = " ".join(str(v) for v in df.iloc[i].tolist())
        if "ImportId" in row_text:
            metadata_end = i
    if metadata_end < 0:
        return df, 0
    out = df.iloc[metadata_end + 1:].reset_index(drop=True)
    return out, metadata_end + 1


def parse_label_overrides(text: str) -> Dict[str, str]:
    """Parse a `key :: value` block into a mapping.

    Used for wide-format question-header overrides ("Q1 :: Full question text?").
    Blank lines and lines without `::` are ignored.
    """
    out: Dict[str, str] = {}
    for line in (text or "").splitlines():
        line = line.strip()
        if "::" not in line:
            continue
        left, right = line.split("::", 1)
        key, value = left.strip(), right.strip()
        if key and value:
            out[key] = value
    return out
