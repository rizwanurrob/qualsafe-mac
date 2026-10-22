#!/usr/bin/env python
"""
Rebuild a working dataset from a project store (v3.9.1).

A `.qnw` holds every response's text and id (the pipeline records `response_id`
and `question_text` on each Source's metadata, with `raw_text` as the response).
That is enough to regenerate the long-format DataFrame the app's Data Setup and
Labeling Lab expect — so a colleague who receives *only* the project file can
load it, rebuild the responses, and code independently, with no separate copy of
the original data file.

This is the read-side counterpart to `core/populate.py`. It is deliberately a
pure function over the store (no Streamlit, no session state) so it is testable
and reusable; the UI wires it into a "Rebuild working data from active project"
button.

What it reconstructs: `response_id`, `question_text`, `response_text`, plus any
descriptor columns and (wide-form) `respondent_id`. What it does NOT reconstruct:
the model's scored columns (cluster/sentiment live on Source metadata and are not
needed to re-code) — a rebuild is a coding surface, not a re-run of the pipeline.
"""

from __future__ import annotations

from pathlib import Path
from typing import Union

import pandas as pd

# Columns the app's mapping targets, in a stable, readable order.
RESPONSE_ID_COL = "response_id"
QUESTION_COL = "question_text"
TEXT_COL = "response_text"


def dataframe_from_store(store_path: Union[str, Path]) -> pd.DataFrame:
    """Reconstruct a long-format response DataFrame from a `.qnw` store.

    One row per survey-response Source. Columns: ``response_id``,
    ``question_text``, ``response_text``, then ``respondent_id`` (only if any
    source carries one), then one column per descriptor key found in the store.

    Rows are sorted by (question_text, response_id) for a deterministic order.
    Raises FileNotFoundError if the store does not exist; returns an empty frame
    (with the three core columns) if the store has no survey responses.
    """
    from core.project import Project

    store_path = Path(store_path)
    if not store_path.exists():
        raise FileNotFoundError(f"Project store not found: {store_path}")

    rows = []
    descriptor_keys: list[str] = []
    seen_respondent = False

    with Project.open(store_path) as proj:
        for src in proj.list_sources():
            # Only survey responses carry the response_id/question contract this
            # rebuilds. Interview sub-turn sources have a different shape and are
            # skipped rather than mangled.
            if src.type != "survey_response":
                continue
            meta = src.metadata or {}
            response_id = str(meta.get("response_id") or src.source_id)
            question = str(meta.get("question_text") or src.label or "")
            row = {
                RESPONSE_ID_COL: response_id,
                QUESTION_COL: question,
                TEXT_COL: str(src.raw_text or ""),
            }
            respondent_id = meta.get("respondent_id")
            if respondent_id not in (None, ""):
                row["respondent_id"] = str(respondent_id)
                seen_respondent = True
            for key, value in proj.get_descriptors(src.source_id).items():
                row[key] = value
                if key not in descriptor_keys:
                    descriptor_keys.append(key)
            rows.append(row)

    ordered_cols = [RESPONSE_ID_COL, QUESTION_COL, TEXT_COL]
    if seen_respondent:
        ordered_cols.append("respondent_id")
    ordered_cols.extend(descriptor_keys)

    if not rows:
        return pd.DataFrame(columns=ordered_cols)

    df = pd.DataFrame(rows)
    # Every id/descriptor stays string — response_id is a join key and must not be
    # float-coerced (the historical CSV-reload bug), and descriptors are labels.
    for col in df.columns:
        df[col] = df[col].fillna("").astype(str)
    # Reindex to the stable column order (missing descriptor cells become "").
    df = df.reindex(columns=ordered_cols, fill_value="")
    df = df.sort_values([QUESTION_COL, RESPONSE_ID_COL], kind="stable").reset_index(drop=True)
    return df


def descriptor_columns(df: pd.DataFrame) -> list[str]:
    """The descriptor columns in a reconstructed frame (everything past the core)."""
    core = {RESPONSE_ID_COL, QUESTION_COL, TEXT_COL, "respondent_id"}
    return [c for c in df.columns if c not in core]
