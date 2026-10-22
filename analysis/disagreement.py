#!/usr/bin/env python
"""
Coder disagreement drill-down (v3.9.6, F2).

Per-code kappa tells you *how much* two coders agree; it doesn't show you *which
items* they disagree on, so you can't reconcile them. This turns the reliability
number into a workflow: list the responses where two raters coded differently,
with each side's codes, so an analyst can adjudicate a decision (written back as a
distinct `human_adjudicated` rater by `core/adjudication.py`).

Pure functions over the `{excerpt_id: set(code_name)}` shape that
`Project.rater_labels` already returns — no I/O, no Streamlit. The UI joins the
excerpt text and offers the resolve control.
"""

from __future__ import annotations

from typing import Dict, List, Set


def _overlap(labels_a: Dict[str, Set[str]], labels_b: Dict[str, Set[str]]) -> List[str]:
    """Excerpt ids both raters coded (the only items agreement is defined on)."""
    return sorted(set(labels_a) & set(labels_b))


def disagreements(
    labels_a: Dict[str, Set[str]],
    labels_b: Dict[str, Set[str]],
) -> List[dict]:
    """Items in the shared set where the two raters' code sets differ.

    Returns one dict per disagreeing excerpt, in stable excerpt-id order::

        {"excerpt_id",
         "a_codes", "b_codes",   # full sets, sorted lists
         "a_only", "b_only",     # codes one applied and the other didn't
         "agreed"}               # codes both applied

    An item both coded identically (including both leaving it uncoded) is not a
    disagreement and is omitted.
    """
    out: List[dict] = []
    for eid in _overlap(labels_a, labels_b):
        a = set(labels_a.get(eid) or set())
        b = set(labels_b.get(eid) or set())
        if a == b:
            continue
        out.append({
            "excerpt_id": eid,
            "a_codes": sorted(a),
            "b_codes": sorted(b),
            "a_only": sorted(a - b),
            "b_only": sorted(b - a),
            "agreed": sorted(a & b),
        })
    return out


def disagreement_summary(
    labels_a: Dict[str, Set[str]],
    labels_b: Dict[str, Set[str]],
) -> Dict[str, int]:
    """Counts over the shared item set: overlap / agree / disagree."""
    overlap = _overlap(labels_a, labels_b)
    disagree = len(disagreements(labels_a, labels_b))
    return {
        "overlap_items": len(overlap),
        "agree_items": len(overlap) - disagree,
        "disagree_items": disagree,
    }
