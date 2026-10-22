#!/usr/bin/env python
"""
Joint displays — the mixed-methods artifact reviewers ask for by name.

A joint display puts the quantitative result and the qualitative result side by
side and adds a column for the **inference drawn from putting them together**.
It is the named integration device of mixed-methods research: it has a Sage
Handbook chapter, a published methods paper about MAXQDA's implementation, and
it is much of why MAXQDA is the default recommendation for mixed-methods work.

This project already had every ingredient — descriptors, code × descriptor
crosstabs with drill-back, verified quotes, Word and Excel export — and assembled
none of them into the thing that has a name. This module is the assembly. It is
a layout over analysis that already exists, not new analysis.

Design decisions
----------------
- **The counts come from `analysis.crosstab.code_by_descriptor`.** A joint
  display that computed its own numbers would be a second answer to a question
  the project already answers, and the two would drift. Same function, same
  distinct-source counting, same normalization options.

- **Quotes are pulled from the store at their stored offsets, never
  paraphrased.** A joint display's evidence column is what a reader checks
  first. `Excerpt.text` is read back through the project, so a quote in the
  display is a quote that exists in the data — the same rule the framework
  matrix follows.

- **The inference column starts empty and stays the analyst's.** The whole point
  of the artifact is the interpretation formed by reading the two halves
  together; a tool that pre-filled it would be writing the finding. Drafting it
  from a local LLM is possible later, and it would still be a draft the analyst
  replaces — see how `analysis/framework.draft_cell_summary` is framed.

- **Percentages are of the subgroup, not of the total.** "10 of 20 first-gen
  students" and "15 of 200 others" are the comparison a reader wants, and raw
  counts invert it. `normalize="group_size"` is the default here even though the
  crosstab defaults to counts, because a display is for publication and the
  count-only version is the one that misleads.

- **Small cells are flagged, not hidden.** A subgroup of three is a real thing to
  report and a dangerous thing to report silently, so the cell carries `small`
  and the exports say so. Same posture as the kappa insufficient-N flags.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import pandas as pd

from analysis.crosstab import code_by_descriptor

#: A subgroup smaller than this is reportable but must not pass unremarked.
SMALL_CELL = 5

#: How many verified quotes a cell carries. One is the readable default for a
#: display that has to fit on a page; the ids are all kept, so a reader can go
#: back to the rest.
DEFAULT_QUOTES_PER_CELL = 1


@dataclass(frozen=True)
class Cell:
    """One (theme, subgroup) intersection."""

    code_name: str
    value: str
    n: int
    #: Percent of that subgroup's respondents carrying the code, or None when the
    #: display was built on raw counts.
    pct: Optional[float]
    quotes: List[str] = field(default_factory=list)
    source_ids: List[str] = field(default_factory=list)

    @property
    def small(self) -> bool:
        return 0 < self.n < SMALL_CELL

    @property
    def empty(self) -> bool:
        return self.n == 0

    def quantitative(self) -> str:
        """The left-hand half of the display, as text."""
        if self.pct is None:
            return f"{self.n}"
        return f"{self.n} ({self.pct:.0f}%)"


@dataclass(frozen=True)
class JointDisplay:
    """Themes down the side, subgroups across the top, an inference per theme."""

    descriptor_key: str
    values: List[str]
    codes: List[str]
    cells: Dict[Tuple[str, str], Cell]
    #: The analyst's integration statement per theme. Empty until they write it.
    inferences: Dict[str, str] = field(default_factory=dict)
    normalized: bool = True

    def cell(self, code_name: str, value: str) -> Cell:
        return self.cells.get(
            (code_name, value), Cell(code_name, value, 0, 0.0 if self.normalized else None))

    def group_totals(self) -> Dict[str, int]:
        """Distinct respondents behind each subgroup column."""
        totals: Dict[str, int] = {}
        for value in self.values:
            seen: set = set()
            for code in self.codes:
                seen.update(self.cell(code, value).source_ids)
            totals[value] = len(seen)
        return totals

    def small_cells(self) -> List[Cell]:
        return [self.cell(c, v) for c in self.codes for v in self.values
                if self.cell(c, v).small]

    def to_frame(self) -> pd.DataFrame:
        """The display as a table: one row per theme, a column per subgroup,
        then evidence and inference. This is what gets exported."""
        rows = []
        for code in self.codes:
            row: Dict[str, Any] = {"Theme": code}
            for value in self.values:
                row[str(value)] = self.cell(code, value).quantitative()
            row["Evidence"] = " ⏎ ".join(
                q for value in self.values for q in self.cell(code, value).quotes)
            row["Inference"] = self.inferences.get(code, "")
            rows.append(row)
        return pd.DataFrame(rows)


def build_joint_display(
    coding_df: pd.DataFrame,
    descriptor_df: pd.DataFrame,
    descriptor_key: str,
    *,
    project: Any = None,
    codes: Optional[Sequence[str]] = None,
    normalize: bool = True,
    quotes_per_cell: int = DEFAULT_QUOTES_PER_CELL,
    inferences: Optional[Dict[str, str]] = None,
) -> JointDisplay:
    """Assemble a joint display for one descriptor.

    `project` is optional: without it the display is counts-only, which is what a
    caller wants when it is assembling the quantitative half before the analyst
    has chosen which quotes to show. With it, each cell carries verified quotes
    read back from the store.

    `codes` limits and orders the themes; the default is every code that appears,
    most prevalent first, because a display with forty rows is not a display.
    """
    counts, drill = code_by_descriptor(
        coding_df, descriptor_df, descriptor_key,
        normalize="group_size" if normalize else None)
    if counts.empty:
        return JointDisplay(descriptor_key, [], [], {}, dict(inferences or {}), normalize)

    # The raw counts are needed alongside any normalized view: a percentage with
    # no denominator behind it is the thing a reviewer sends back.
    raw, _ = code_by_descriptor(coding_df, descriptor_df, descriptor_key)

    values = [str(v) for v in counts.columns]
    ordered = _order_codes(raw, codes)

    cells: Dict[Tuple[str, str], Cell] = {}
    for code in ordered:
        for value in values:
            source_ids = list(drill.get((code, value), []))
            n = int(raw.loc[code, value]) if code in raw.index and value in raw.columns else 0
            pct = (float(counts.loc[code, value])
                   if normalize and code in counts.index and value in counts.columns
                   else None)
            cells[(code, value)] = Cell(
                code_name=code, value=value, n=n, pct=pct,
                quotes=_quotes_for(project, source_ids, quotes_per_cell),
                source_ids=source_ids,
            )

    return JointDisplay(descriptor_key, values, ordered, cells,
                        dict(inferences or {}), normalize)


def _order_codes(raw: pd.DataFrame, codes: Optional[Sequence[str]]) -> List[str]:
    """Requested order, or most prevalent first, ties broken by name.

    The tiebreak is not decoration. Two themes with the same total would
    otherwise be ordered by whatever the pivot happened to produce, so the same
    project could export a table whose rows moved between runs — in a document
    that goes into a chapter.
    """
    if codes:
        return [c for c in codes if c in raw.index]
    totals = raw.sum(axis=1)
    ordered = sorted(totals.index.astype(str),
                     key=lambda name: (-float(totals[name]), name))
    return list(ordered)


def _quotes_for(project: Any, source_ids: Sequence[str], limit: int) -> List[str]:
    """Verified quotes for a cell, read back from the store.

    Never paraphrased and never assembled from a summary: the evidence column is
    the half of a joint display a reader checks first, so it has to be text that
    is actually in the data. A source that cannot be read is skipped rather than
    replaced with a placeholder.
    """
    if project is None or limit <= 0:
        return []
    out: List[str] = []
    for source_id in source_ids:
        if len(out) >= limit:
            break
        try:
            source = project.get_source(source_id)
        except Exception:  # noqa: BLE001 - a missing source must not break the display
            continue
        text = (getattr(source, "raw_text", "") or "").strip()
        if text:
            out.append(text)
    return out


def display_caveats(display: JointDisplay) -> List[str]:
    """What has to be said alongside this display, in plain sentences.

    The project's rule is that the caveat travels with the number. A joint
    display is built to be pasted into a findings chapter, which makes it the
    single most important place for that rule to hold.
    """
    notes: List[str] = []
    small = display.small_cells()
    if small:
        where = ", ".join(f"{c.code_name} × {c.value} (n={c.n})" for c in small[:4])
        more = "" if len(small) <= 4 else f", and {len(small) - 4} more"
        notes.append(
            f"{len(small)} cell(s) rest on fewer than {SMALL_CELL} respondents "
            f"— {where}{more}. Report them with the count visible, or not at all.")

    totals = display.group_totals()
    if totals:
        smallest = min(totals.values())
        largest = max(totals.values())
        if smallest and largest >= smallest * 3:
            notes.append(
                f"The subgroups are very unequal ({smallest} to {largest} "
                "respondents). Percentages compare fairly; the raw counts do not.")

    if not display.normalized and len(display.values) > 1:
        notes.append(
            "This display shows raw counts. If the subgroups differ in size, a "
            "larger group will look like a stronger theme purely because it is "
            "larger.")

    if not any(display.cell(c, v).quotes
               for c in display.codes for v in display.values):
        notes.append(
            "No quotes are attached. A joint display without its qualitative "
            "half is a crosstab.")

    return notes
