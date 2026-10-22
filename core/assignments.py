#!/usr/bin/env python
"""
Team coding distribution (v3.6, Feature A).

Splitting a coding job across several people means two different things, and the
tool is explicit about which:

- **Partition (throughput).** Disjoint slices — coder A codes rows 1–100, B codes
  101–200. Faster coverage, but no overlap, so there is *no* inter-rater
  reliability to compute and the UI must not imply there is one.
- **Overlap (reliability).** A shared "calibration" subset that everyone codes on
  purpose, to measure agreement. This is the IRR path.

Most projects want both: a small overlapping calibration set plus a partitioned
remainder. `split_coding_sample` produces exactly that.

Collaboration topology is **copy + merge** (the safe default from the design
notes): each coder gets their own CSV, codes it, and the filled files are merged
back — each coder mapped to a distinct rater in the store. No shared-file locking,
works over email/USB, and the merge reconciles on ``response_id`` (never on the
store's internal source ids, which differ between copies).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Sequence, Union

import pandas as pd


def rater_id_for(coder_name: str) -> str:
    """Deterministic, safe rater_id for a coder's display name."""
    slug = re.sub(r"[^a-z0-9]+", "_", str(coder_name).strip().lower()).strip("_")
    return f"human_{slug or 'coder'}"


def split_coding_sample(
    sample_df: pd.DataFrame,
    coders: Sequence[str],
    *,
    mode: str = "partition",
    overlap_n: int = 0,
    random_state: int = 42,
) -> Dict[str, pd.DataFrame]:
    """Split a coding sample into one frame per coder.

    - ``mode="partition"``: rows are divided disjointly (round-robin) among coders.
    - ``mode="overlap"``: the first `overlap_n` rows (a shuffled calibration set)
      go to *every* coder; the remainder is partitioned. `overlap_n` rows are the
      only ones that yield inter-rater agreement.

    Returns ``{coder_name: DataFrame}``. Each frame is a copy with a fresh
    ``human_labels``/``coder_notes`` pair cleared for that coder to fill.
    """
    coders = list(coders)
    if not coders:
        raise ValueError("At least one coder is required.")
    if sample_df.empty:
        return {c: sample_df.copy() for c in coders}

    df = sample_df.reset_index(drop=True)
    shuffled = df.sample(frac=1.0, random_state=random_state).reset_index(drop=True)

    overlap_rows = pd.DataFrame(columns=df.columns)
    remainder = shuffled
    if mode == "overlap" and overlap_n > 0:
        overlap_n = min(overlap_n, len(shuffled))
        overlap_rows = shuffled.iloc[:overlap_n]
        remainder = shuffled.iloc[overlap_n:]

    # Round-robin the remainder so slice sizes differ by at most one.
    buckets: Dict[str, List[int]] = {c: [] for c in coders}
    for i, idx in enumerate(remainder.index.tolist()):
        buckets[coders[i % len(coders)]].append(idx)

    out: Dict[str, pd.DataFrame] = {}
    for coder in coders:
        part = remainder.loc[buckets[coder]]
        frame = pd.concat([overlap_rows, part]).sort_values("response_id").reset_index(drop=True)
        frame = frame.copy()
        frame["human_labels"] = ""
        frame["coder_notes"] = ""
        out[coder] = frame
    return out


def merge_coder_samples(
    store_path: Union[str, Path],
    coder_files: Dict[str, Union[str, Path]],
    *,
    question_text: str = None,
    delimiter: str = "|",
) -> Dict[str, Dict[str, int]]:
    """Import each coder's filled coding_sample into the store under its own rater.

    ``coder_files`` maps a coder's display name to their filled CSV. Each import is
    idempotent per rater (re-importing replaces that rater's codes), so merging is
    safe to repeat. Returns per-coder result dicts from ``record_human_codings``.
    """
    from core.backups import backup_store
    from core.populate import import_second_coder_sample

    backup_store(store_path, reason="pre_team_merge")

    results: Dict[str, Dict[str, int]] = {}
    for coder, path in coder_files.items():
        results[coder] = import_second_coder_sample(
            store_path, path, rater_id=rater_id_for(coder), rater_name=str(coder),
            question_text=question_text, delimiter=delimiter,
        )
    return results


def coverage_report(store_path: Union[str, Path]) -> Dict[str, object]:
    """How much of the coding is done, and how much is double-coded (for IRR).

    Returns ``{"per_rater": {rater: n_excerpts}, "n_excerpts_coded",
    "n_double_coded", "double_coded_excerpts"}``. Double-coded excerpts (≥2 human
    raters) are the overlap set the Agreement tab can compute kappa over.
    """
    from core.project import Project

    with Project.open(store_path) as proj:
        human_raters = [r for r in proj.rater_ids() if r and r.startswith("human")]
        labels_by_rater = {r: proj.rater_labels(r) for r in human_raters}

    excerpt_raters: Dict[str, set] = {}
    per_rater: Dict[str, int] = {}
    for rater, labels in labels_by_rater.items():
        coded = {exc for exc, codes in labels.items() if codes}
        per_rater[rater] = len(coded)
        for exc in coded:
            excerpt_raters.setdefault(exc, set()).add(rater)

    double = [exc for exc, raters in excerpt_raters.items() if len(raters) >= 2]
    return {
        "per_rater": per_rater,
        "n_excerpts_coded": len(excerpt_raters),
        "n_double_coded": len(double),
        "double_coded_excerpts": double,
    }
