#!/usr/bin/env python
"""
Agreement on span-coded documents, on a declared unit (V4 decision; review F4).

Kappa needs one set of items that both raters judged. Survey mode has that for
free: one response, one excerpt. Span coding does not. Two coders highlighting
the same idea almost never choose identical character ranges, so keyed on
excerpts their codings share no items and kappa is empty, or computed over the
few spans that happen to coincide.

The answer V4 settled on: project each coder's spans onto a **declared unit**
(sentence or paragraph, from `core.span_coding.codeable_units`), over documents
both coders have said they finished, and give those units to the existing
`per_code_kappa`. The statistic stays kappa (the locked decision); the unit and
the overlap rule become part of the result, and results at different units are
never compared (`analysis.agreement.assert_comparable_units`).

Two overlap rules, because a highlight that runs a few characters into the next
sentence is common and the choice matters:

* ``any_overlap`` -- a unit carries a code if any coded span touches it. Lenient;
  the default, and the rule most readers assume.
* ``majority`` -- only if coded spans cover at least half of the unit's
  characters. Stricter; a stray tail no longer codes the next sentence.

Pure function over plain inputs: no store, no Streamlit.
"""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

import pandas as pd

OVERLAP_RULES = ("any_overlap", "majority")

#: (unit_start, unit_end) per unit, in document order.
Units = Sequence[Tuple[int, int]]


def unit_id(source_id: str, index: int) -> str:
    """Stable item id for the `index`-th unit of a document."""
    return f"{source_id}#{index}"


def _covered_chars(spans: List[Tuple[int, int]], start: int, end: int) -> int:
    """Characters of [start, end) covered by the union of `spans` (overlaps once)."""
    clipped = sorted((max(s, start), min(e, end)) for s, e in spans if s < end and e > start)
    total, cursor = 0, start
    for s, e in clipped:
        s = max(s, cursor)
        if e > s:
            total += e - s
            cursor = e
    return total


def project_spans_to_units(
    codings: pd.DataFrame,
    units_by_source: Dict[str, Units],
    *,
    rule: str = "any_overlap",
    raters: Optional[Iterable[str]] = None,
) -> Dict[str, Dict[str, Set[str]]]:
    """Map each rater's coded spans onto units.

    `codings` needs columns ``rater_id, source_id, code_name, char_start,
    char_end``. `units_by_source` lists the units of every document to compare;
    codings on other documents are ignored. Every unit of every listed document
    is an item for every rater -- an uncoded sentence is the rater saying no
    code applies, not a missing value -- so the item sets are identical and
    kappa is over all of them.

    Returns ``{rater_id: {unit_id: set(code_names)}}``.
    """
    if rule not in OVERLAP_RULES:
        raise ValueError(f"Unknown overlap rule {rule!r} (expected one of {OVERLAP_RULES}).")

    rater_list = list(raters) if raters is not None else sorted(
        codings["rater_id"].dropna().unique().tolist()) if not codings.empty else []

    # spans[rater][source][code] -> [(start, end), ...]
    spans: Dict[str, Dict[str, Dict[str, List[Tuple[int, int]]]]] = {}
    for row in codings.itertuples(index=False):
        if row.source_id not in units_by_source:
            continue
        spans.setdefault(row.rater_id, {}).setdefault(row.source_id, {}).setdefault(
            row.code_name, []).append((int(row.char_start), int(row.char_end)))

    out: Dict[str, Dict[str, Set[str]]] = {}
    for rater in rater_list:
        items: Dict[str, Set[str]] = {}
        for source_id, units in units_by_source.items():
            by_code = spans.get(rater, {}).get(source_id, {})
            for index, (start, end) in enumerate(units):
                codes: Set[str] = set()
                length = max(end - start, 1)
                for code, code_spans in by_code.items():
                    covered = _covered_chars(code_spans, start, end)
                    if (rule == "any_overlap" and covered > 0) or (
                            rule == "majority" and covered * 2 >= length):
                        codes.add(code)
                items[unit_id(source_id, index)] = codes
        out[rater] = items
    return out
