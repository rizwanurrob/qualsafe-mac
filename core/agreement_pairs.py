#!/usr/bin/env python
"""
Which two raters an agreement table compares, decided in one place (review F5).

Every export used to choose for itself, alphabetically: "the first rater id
starting with `human`" and "the first engine". That broke three ways. After one
adjudication, `human_adjudicated` (a handful of disputed items) sorted ahead of
`human_primary`. The bundle's "model" could be the text-search auto-coder. And
on a real project, where every pipeline run registers a fresh `rater_…` id,
the lookups for a rater *named* `transformer` never matched, so the Word
report, the Excel workbook and the methods appendix all said no human-vs-engine
agreement existed.

So the choice is made here, by role, and the reasons travel with the numbers:

* the **primary human** is `human_primary` when present, otherwise the first
  human coder -- never the adjudicator;
* an **engine** is a rater of kind `transformer` or `llm` that belongs to a
  pipeline run -- never the text-search auto-coder, an imported coder, a Laya
  run or a simulation -- and the most recent run's engine is the one compared;
  runs are never pooled, because two runs are two different coders;
* the **item set** is what each rater reviewed (store format v8,
  `Project.rater_item_set`). A rater coded before v8 has no review record, and
  the table then says agreement is likely overstated;
* human-vs-engine κ always says it describes the responses the person coded,
  and measures whether those look chosen for difficulty (`selection_caveat`):
  the store does not record how they were picked, and a review queue holds the
  hard cases.

None of the engines here was trained on the project's human coding (the
pipeline writes zero-shot codings to the store; the supervised model's labels
never reach it), so comparing them with a person is not scoring a model on its
own training items.

Returns plain data (`Comparison`); the kappa itself is still
`analysis.agreement.per_code_kappa`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from core.adjudication import ADJUDICATED_RATER

ENGINE_KINDS = ("transformer", "llm")
#: Machine raters that are not the pipeline's engine.
NOT_AN_ENGINE_PREFIXES = ("auto_textsearch", "laya", "simulated", "imported_")

UNCERTAIN_CAVEAT = ("Responses the engine left uncertain (UNCERTAIN_REVIEW) count as the "
                    "engine applying no code.")


@dataclass
class Comparison:
    kind: str                         # "human_vs_engine" | "human_vs_human" | "span_units"
    label: str
    rater_a: str
    rater_b: str
    labels_a: Dict[str, Set[str]]
    labels_b: Dict[str, Set[str]]
    caveats: List[str] = field(default_factory=list)
    unit: str = "response"
    rule: str = ""


def _is_engine(rater) -> bool:
    return (rater.kind in ENGINE_KINDS
            and not any(rater.rater_id.startswith(p) for p in NOT_AN_ENGINE_PREFIXES))


def engine_raters(project) -> List[str]:
    """Engine rater ids, most recent run first."""
    order = project.rater_run_order()
    engines = [r.rater_id for r in project.list_raters() if _is_engine(r)]
    return sorted(engines, key=lambda rid: order.get(rid, ("", -1)), reverse=True)


def human_raters(project) -> List[str]:
    """Human coders who can be compared: ids starting `human`, not the adjudicator."""
    return sorted(r.rater_id for r in project.list_raters()
                  if r.kind == "human" and r.rater_id.startswith("human")
                  and r.rater_id != ADJUDICATED_RATER)


def selectable_raters(project) -> List[str]:
    """Coders an analyst may pick to compare: the human coders, then the
    adjudicated set last when there is one.

    Never chosen automatically (exports and `comparisons` leave it out), but a
    legitimate pick: checking yourself against the reconciled set is how the
    adjudicated coding serves as a gold standard. `compare_raters` says what
    such a figure is and is not.
    """
    humans = human_raters(project)
    has_adjudicator = any(r.rater_id == ADJUDICATED_RATER for r in project.list_raters())
    return humans + ([ADJUDICATED_RATER] if has_adjudicator else [])


def span_raters(project) -> List[str]:
    """Coders whose span coding can be compared: every human coder except the
    adjudicator -- including `imported_<name>`, because a colleague's span
    coding usually arrives in a .qdpx from NVivo, MAXQDA or ATLAS.ti."""
    return sorted(r.rater_id for r in project.list_raters()
                  if r.kind == "human" and r.rater_id != ADJUDICATED_RATER)


def primary_human(project) -> Optional[str]:
    humans = human_raters(project)
    if "human_primary" in humans:
        return "human_primary"
    return humans[0] if humans else None


def _item_set_caveats(rater_id: str, item_set) -> List[str]:
    out = []
    if not item_set.recorded:
        out.append(
            f"Which responses {rater_id} reviewed was not recorded (the coding predates "
            f"project format v8), so responses {rater_id} read and left uncoded are missing "
            f"from this table and agreement is likely overstated. Re-saving {rater_id}'s "
            f"coding sample records it.")
    elif item_set.uncovered_applied:
        out.append(
            f"{item_set.uncovered_applied} response(s) {rater_id} coded before reviews were "
            f"recorded are left out. Re-save that coding sample to include them.")
    return out


def _pair(project, kind, a, b, extra_caveats=()) -> Optional[Comparison]:
    set_a, set_b = project.rater_item_set(a), project.rater_item_set(b)
    if not set(set_a.labels) & set(set_b.labels):
        return None
    caveats = _item_set_caveats(a, set_a) + _item_set_caveats(b, set_b) + list(extra_caveats)
    return Comparison(kind=kind, label=f"{a} vs {b}", rater_a=a, rater_b=b,
                      labels_a=set_a.labels, labels_b=set_b.labels, caveats=caveats)


def compare_raters(project, rater_a: str, rater_b: str) -> Optional[Comparison]:
    """Two chosen coders on survey responses, with item-set caveats; None when
    they reviewed no response in common."""
    extra = []
    if ADJUDICATED_RATER in (rater_a, rater_b):
        extra.append(
            f"{ADJUDICATED_RATER} holds only the items that were reconciled, so this "
            f"compares a coder with the resolution on those items: a check against a "
            f"gold standard, not an inter-rater reliability figure.")
    return _pair(project, "human_vs_human", rater_a, rater_b, extra)


def selection_caveat(project, human: str, engine: str) -> str:
    """What κ between a person and an engine describes, and a measured check on
    whether the responses the person coded were chosen for difficulty.

    The store records who coded a response, not how it came to be coded: a
    random sample, a review queue of the engine's uncertain cases, or whatever
    the analyst opened. κ describes those responses; it stands for the dataset
    only if they were a random draw. The check: among the responses the engine
    coded, compare how often it applied no code on the ones the person also
    coded against the ones they did not (Newcombe interval on the difference).
    An uncertainty-selected sample shows up as a clear excess.
    """
    from analysis.prevalence import newcombe_difference

    base = (f"The store does not record how the responses {human} coded were chosen. "
            f"This κ describes those responses; it stands for the whole dataset only "
            f"if they were a random sample. A review queue or an uncertainty sample "
            f"holds the hard cases, so κ there reads lower than across all responses.")
    engine_set = project.rater_item_set(engine)
    human_set = project.rater_item_set(human)
    if not engine_set.recorded:
        return base
    shared = set(engine_set.labels) & set(human_set.labels)
    rest = set(engine_set.labels) - shared
    if not shared:
        return base
    if not rest:
        return (f"{human} coded every response the engine coded, so no selection "
                f"is involved: this κ covers the whole run.")
    k1 = sum(1 for e in shared if not engine_set.labels[e])
    k2 = sum(1 for e in rest if not engine_set.labels[e])
    n1, n2 = len(shared), len(rest)
    diff, low, high = newcombe_difference(k1, n1, k2, n2)
    measured = (f" Of the {n1} response(s) {human} coded, the engine left {k1 / n1:.0%} "
                f"without a code, against {k2 / n2:.0%} of the other {n2}")
    if low > 0:
        verdict = (f" (difference {diff:+.0%}, 95% CI {low:+.0%} to {high:+.0%}): these "
                   f"responses are harder than the rest, not a random sample, and κ on "
                   f"them understates agreement across the run.")
    elif high < 0:
        verdict = (f" (difference {diff:+.0%}, 95% CI {low:+.0%} to {high:+.0%}): these "
                   f"responses are easier than the rest, not a random sample, and κ on "
                   f"them likely overstates agreement across the run.")
    else:
        verdict = (f" (difference {diff:+.0%}, 95% CI {low:+.0%} to {high:+.0%}): no "
                   f"sign they were chosen for difficulty, though this check cannot "
                   f"show they were random.")
    return base + measured + verdict


def compare_with_engine(project, human: str, engine: str) -> Optional[Comparison]:
    """A chosen human coder against a chosen engine run, with every caveat the
    exports carry; None when they reviewed no response in common."""
    engines = engine_raters(project)
    extra = [UNCERTAIN_CAVEAT, selection_caveat(project, human, engine)]
    if engine in engines and len(engines) > 1:
        if engine == engines[0]:
            extra.append(f"Compared with the most recent run's engine ({engine}); "
                         f"{len(engines) - 1} earlier run(s) are not pooled with it.")
        else:
            extra.append(f"{engine} is an earlier run, not the most recent; runs are "
                         f"never pooled.")
    return _pair(project, "human_vs_engine", human, engine, extra)


def human_vs_engine(project) -> Optional[Comparison]:
    """The primary human against the most recent run's engine, or None."""
    human = primary_human(project)
    engines = engine_raters(project)
    if not human or not engines:
        return None
    return compare_with_engine(project, human, engines[0])


def comparisons(project) -> List[Comparison]:
    """Every comparable pair: the primary human vs the engine, then each human pair."""
    out: List[Comparison] = []
    engine = human_vs_engine(project)
    if engine is not None:
        out.append(engine)
    humans = human_raters(project)
    for i, a in enumerate(humans):
        for b in humans[i + 1:]:
            pair = _pair(project, "human_vs_human", a, b)
            if pair is not None:
                out.append(pair)
    return out


def kappa_table(comparison: Optional[Comparison], *, min_support: Optional[int] = None):
    """Per-code kappa for a comparison, with its caveats in ``table.attrs["caveats"]``.

    `min_support` defaults to the project-wide rule (insufficient-N below it),
    never 1: a code seen on two responses gets no kappa, in any export.
    Returns None when there is nothing to compare.
    """
    from analysis.agreement import DEFAULT_MIN_SUPPORT, per_code_kappa

    if comparison is None:
        return None
    table = per_code_kappa(comparison.labels_a, comparison.labels_b,
                           min_support=DEFAULT_MIN_SUPPORT if min_support is None else min_support)
    if table.empty:
        return None
    table.attrs["caveats"] = list(comparison.caveats)
    table.attrs["comparison"] = comparison.label
    return table


def span_comparison(project, rater_a: str, rater_b: str, *, unit: str = "sentence",
                    rule: str = "any_overlap") -> Optional[Comparison]:
    """Two coders' span coding projected onto `unit`s (see analysis.unit_agreement).

    Only documents both coders marked as fully coded are compared: an unmarked
    document may simply be unfinished, and its empty sentences would read as
    "no code applies". Returns None when there is no such document.
    """
    from analysis.unit_agreement import project_spans_to_units
    from core.span_coding import codeable_units

    documents = sorted(project.documents_coded_by(rater_a) & project.documents_coded_by(rater_b))
    if not documents:
        return None
    units = {}
    for source_id in documents:
        source = project.get_source(source_id)
        units[source_id] = [(s, e) for _t, s, e in codeable_units(source.raw_text, unit)]

    spans = project.coding_spans_table()
    spans = spans[spans["rater_id"].isin([rater_a, rater_b])
                  & spans["source_id"].isin(documents)].drop_duplicates("application_id")
    items = project_spans_to_units(spans, units, rule=rule, raters=[rater_a, rater_b])
    n_units = sum(len(u) for u in units.values())
    rule_text = ("any coded passage touches it" if rule == "any_overlap"
                 else "coded passages cover at least half of it")
    caveats = [f"Agreement is on {unit}s: a {unit} carries a code if {rule_text}. "
               f"{len(documents)} document(s) both coders marked as fully coded, "
               f"{n_units} {unit}(s). Not comparable with agreement at any other unit."]
    return Comparison(kind="span_units", label=f"{rater_a} vs {rater_b} ({unit}s)",
                      rater_a=rater_a, rater_b=rater_b, labels_a=items[rater_a],
                      labels_b=items[rater_b], caveats=caveats, unit=unit, rule=rule)
