#!/usr/bin/env python
"""
Saturation — the question every reviewer asks and no package answers.

"Was saturation reached?" is the most common methodological challenge to a
qualitative study, and NVivo, MAXQDA, ATLAS.ti and Dedoose all leave the
researcher to assert it in prose. The inputs have been sitting in this project's
store the whole time: which codes were applied to which sources, and the order
the sources were worked through.

What this computes is **code saturation** — the point after which reading more
sources stopped producing new codes. That is a real, reportable, checkable
quantity, and it is *not* the same as meaning saturation, which is about whether
the existing codes are richly enough understood. The distinction is the first
caveat, and the module refuses to be read without them.

Design decisions
----------------
- **A curve, and the sentences a methods section actually writes.** A chart alone
  invites eyeballing. `saturation_summary` returns the numbers a Methods
  paragraph quotes: how many sources, how many codes, where the last new code
  appeared, and how many sources were read after it without finding another.

- **The caveats are load-bearing and are returned with the result**, not left to
  a UI to remember. Three of them are disqualifying often enough to matter:

    1. **An a-priori codebook makes the curve meaningless.** If every code was
       defined before coding began, the curve measures how fast the analyst
       applied a fixed list — it says nothing about the data. The module detects
       this from `Code.origin` and says so.
    2. **Coding order is not collection order** unless the project recorded it.
       Sources are ordered by id, which is ingestion order, which is usually but
       not always the order interviews happened.
    3. **Code saturation is not meaning saturation.** A flat curve means no new
       labels appeared, not that the phenomenon is understood.

- **No threshold is enforced, and none is offered as a verdict.** "Saturated at
  n=17" is a claim only a researcher can make. `plateau_length` reports the run
  of sources since the last new code; whether that is enough is a judgement that
  depends on the design, and a tool that printed "SATURATED ✓" would be
  laundering that judgement.

- **Machine coding is excluded by default.** A model applying a fixed label set
  produces a curve that saturates almost immediately and means nothing about
  discovery. The rater filter defaults to human coders only, consistent with the
  agreement screen's rule.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

import pandas as pd

#: Raters whose codings count as discovery. Everything else is a model applying
#: a list it was given, which cannot discover anything.
HUMAN_RATER_PREFIX = "human"


@dataclass(frozen=True)
class SaturationSummary:
    """The numbers a Methods paragraph quotes."""

    sources_coded: int
    codes_found: int
    #: 1-based position of the source at which the last new code appeared.
    last_new_code_at: int
    #: Sources coded after that without a new code appearing.
    plateau_length: int
    #: Position by which 90% of the codes had been seen — the "most of it early"
    #: number people mean when they say a curve flattened.
    ninety_percent_at: int

    def as_sentence(self) -> str:
        """The finding in the form a methods section states it."""
        if self.sources_coded == 0:
            return "No sources have been coded, so there is no saturation curve."
        if self.codes_found == 0:
            return f"{self.sources_coded} source(s) coded, and no codes applied."
        return (
            f"{self.codes_found} codes emerged across {self.sources_coded} coded "
            f"source(s). The last new code appeared at source {self.last_new_code_at}; "
            f"{self.plateau_length} further source(s) were coded without a new code "
            f"appearing. 90% of codes had been seen by source {self.ninety_percent_at}."
        )


def saturation_curve(
    coding_df: pd.DataFrame,
    *,
    source_order: Optional[Sequence[str]] = None,
    humans_only: bool = True,
) -> pd.DataFrame:
    """New and cumulative codes against sources coded.

    Returns one row per coded source, in order:
    ``[position, source_id, new_codes, cumulative_codes]``.

    `source_order` is the sequence the analyst worked through. Without it the
    order is first-appearance in `coding_df`, which is the store's own order —
    see caveat 2 in the module docstring before reporting anything from it.
    """
    frame = _filtered(coding_df, humans_only)
    if frame.empty:
        return pd.DataFrame(columns=["position", "source_id", "new_codes",
                                     "cumulative_codes"])

    by_source = _codes_by_source(frame)
    order = _resolve_order(by_source, source_order)

    seen: set = set()
    rows: List[Dict[str, Any]] = []
    for position, source_id in enumerate(order, start=1):
        codes = by_source.get(source_id, set())
        fresh = codes - seen
        seen |= codes
        rows.append({
            "position": position,
            "source_id": source_id,
            "new_codes": len(fresh),
            "cumulative_codes": len(seen),
        })
    return pd.DataFrame(rows)


def saturation_summary(curve: pd.DataFrame) -> SaturationSummary:
    """Reduce a curve to the numbers a methods paragraph quotes."""
    if curve.empty:
        return SaturationSummary(0, 0, 0, 0, 0)

    total = int(curve["cumulative_codes"].iloc[-1])
    sources = int(curve["position"].iloc[-1])
    if total == 0:
        return SaturationSummary(sources, 0, 0, 0, 0)

    with_new = curve[curve["new_codes"] > 0]
    last_new = int(with_new["position"].iloc[-1])

    # The first position at which 90% of the eventual codebook had been seen.
    threshold = 0.9 * total
    reached = curve[curve["cumulative_codes"] >= threshold]
    ninety = int(reached["position"].iloc[0]) if not reached.empty else sources

    return SaturationSummary(
        sources_coded=sources,
        codes_found=total,
        last_new_code_at=last_new,
        plateau_length=sources - last_new,
        ninety_percent_at=ninety,
    )


def saturation_caveats(
    curve: pd.DataFrame,
    *,
    codes: Optional[Sequence[Any]] = None,
    order_is_collection_order: bool = False,
) -> List[str]:
    """What must be said alongside this curve. Plain sentences, always non-empty.

    `codes` are `core.model.Code` objects (or anything with `.origin`); passing
    them lets the first and most disqualifying caveat be checked rather than
    merely stated.
    """
    notes: List[str] = []

    if codes is not None:
        origins = [getattr(c, "origin", "a_priori") for c in codes]
        emergent = sum(1 for o in origins if o == "emergent")
        if origins and emergent == 0:
            notes.append(
                "Every code in this project was defined before coding began, so "
                "this curve measures how quickly a fixed list was applied — not "
                "what the data contained. Saturation is not a meaningful claim "
                "over an a-priori codebook.")
        elif origins and emergent < len(origins):
            notes.append(
                f"{len(origins) - emergent} of {len(origins)} codes were defined "
                "before coding began. Only the emergent ones can saturate; the "
                "curve mixes both.")

    if not order_is_collection_order:
        notes.append(
            "Sources are in the order they were ingested, which is not "
            "necessarily the order the data was collected or coded. Saturation "
            "is a claim about sequence, so it only holds if that order is real.")

    notes.append(
        "This is code saturation: no new labels appeared. It is not meaning "
        "saturation, which is about whether the codes you have are richly enough "
        "understood — that is a judgement, not a curve.")

    if not curve.empty:
        summary = saturation_summary(curve)
        if summary.sources_coded < 10:
            notes.append(
                f"Only {summary.sources_coded} source(s) are coded. A curve this "
                "short cannot show a plateau, whatever its shape.")
        elif summary.plateau_length < 3 and summary.codes_found:
            notes.append(
                f"A new code appeared as recently as source "
                f"{summary.last_new_code_at} of {summary.sources_coded}. The "
                "curve has not flattened; coding more would likely find more.")

    return notes


# ── internals ────────────────────────────────────────────────────────────────

def _filtered(coding_df: pd.DataFrame, humans_only: bool) -> pd.DataFrame:
    """Drop machine codings unless asked to keep them.

    A model applying a fixed label set saturates almost immediately and has
    discovered nothing, so pooling it in flatters the curve for the wrong reason.
    """
    if coding_df is None or coding_df.empty:
        return pd.DataFrame(columns=["source_id", "code_name"])
    if not humans_only or "rater_id" not in coding_df.columns:
        return coding_df
    mask = coding_df["rater_id"].astype(str).str.startswith(HUMAN_RATER_PREFIX)
    return coding_df[mask]


def _codes_by_source(frame: pd.DataFrame) -> Dict[str, set]:
    out: Dict[str, set] = {}
    for source_id, group in frame.groupby("source_id", sort=False):
        out[str(source_id)] = set(group["code_name"].astype(str))
    return out


def _resolve_order(by_source: Dict[str, set],
                   source_order: Optional[Sequence[str]]) -> List[str]:
    """The sequence to walk, restricted to sources that were actually coded.

    An uncoded source contributes nothing and would flatten the curve by sitting
    in it as a zero — which reads as evidence of saturation and is not.
    """
    if source_order is None:
        return list(by_source)
    ordered = [str(s) for s in source_order if str(s) in by_source]
    # Anything coded but absent from the given order still belongs on the curve.
    ordered += [s for s in by_source if s not in set(ordered)]
    return ordered
