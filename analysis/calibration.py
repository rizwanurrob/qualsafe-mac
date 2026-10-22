#!/usr/bin/env python
"""
Calibrating a structured-coding run against a human-coded sample (U4).

The Alt Survey Flow engine gives every (response, code) pair a model score and
routes it by a confidence band: below `low` is a confident no, at or above
`high` a confident yes (auto-assigned), and in between goes to a person. The
band was a guess. This module replaces the guess with a measurement, taken on
a **random** sample of responses a person has coded on every code:

* per code: how often the engine's assignments are right (precision), how many
  real instances it finds (recall), F1, and kappa against the person;
* a **recommended band**: the lowest `high` at which auto-assigned codes reach
  a target precision, and the highest `low` below which almost nothing the
  person coded is lost (the target applied to negative predictive value);
* the reliability table (mean score against observed rate per score bin) --
  the only evidence that could ever justify calling a score a probability.

Why the sample must be random, not the Review Queue: the queue holds exactly
the ambiguous middle, so thresholds fitted on it would be fitted on the hard
cases only, like kappa on an uncertainty sample (analysis/sampling.py).

Why a person must code every code on each sampled response: a threshold is a
statement about scores the engine *didn't* auto-assign too; a sample that only
confirms or rejects suggestions cannot see what the engine missed.
"""

from __future__ import annotations

import math
import random
from typing import Dict, List, Optional, Sequence, Set, Tuple

import pandas as pd

from analysis.agreement import DEFAULT_MIN_SUPPORT
from analysis.coding_validation import calibration_curve, per_code_validation

DEFAULT_TARGET = 0.90
#: The band slider moves in steps of this size.
BAND_STEP = 0.05

CAVEATS = [
    "Measured on a random sample a person coded on every code; the figures hold "
    "for responses like these and for this engine, model and codebook. Change "
    "any of them and calibrate again.",
    "Scores stay 'model scores', not probabilities, unless the reliability table "
    "shows the mean score tracking the observed rate in every well-populated bin.",
    "A code under a parent is only scored when the parent was not a confident no, "
    "so its figures cover those responses only.",
]


def draw_sample(excerpt_ids: Sequence[str], n: int, *, seed: int = 42) -> List[str]:
    """A seeded random sample (sorted for a stable reading order)."""
    ids = sorted(set(excerpt_ids))
    rng = random.Random(seed)
    return sorted(rng.sample(ids, min(n, len(ids))))


def score_pairs(decisions: pd.DataFrame, human: Dict[str, Set[str]]) -> pd.DataFrame:
    """One row per (excerpt, code) the engine scored on a human-coded excerpt.

    `decisions` is `Project.coding_decisions_table(run_id)`; `human` maps
    excerpt_id -> codes the person applied (empty set = none).
    """
    cols = ["excerpt_id", "code_name", "score", "model_assigned", "human"]
    if decisions.empty:
        return pd.DataFrame(columns=cols)
    d = decisions[decisions["excerpt_id"].isin(human.keys()) & decisions["model_score"].notna()]
    return pd.DataFrame({
        "excerpt_id": d["excerpt_id"].values,
        "code_name": d["code_name"].values,
        "score": d["model_score"].astype(float).values,
        "model_assigned": d["model_assigned"].astype(bool).values,
        "human": [c in human[e] for e, c in zip(d["excerpt_id"], d["code_name"])],
    }, columns=cols)


def lowest_threshold_for_precision(scores: Sequence[float], truth: Sequence[bool],
                                   target: float, *, min_count: int = DEFAULT_MIN_SUPPORT
                                   ) -> Tuple[Optional[float], float, float]:
    """(t, precision, recall): the lowest observed score t such that items scored
    >= t are human-positive at least `target` of the time, over at least
    `min_count` items. (None, nan, nan) if no threshold gets there."""
    pairs = sorted(zip(scores, truth), key=lambda x: x[0])
    positives = sum(1 for _, t in pairs if t)
    for i, (s, _t) in enumerate(pairs):
        above = pairs[i:]
        if len(above) < min_count:
            break
        if i > 0 and pairs[i - 1][0] == s:
            continue          # a threshold sits at the first of tied scores
        hits = sum(1 for _, t in above if t)
        if hits / len(above) >= target:
            return s, hits / len(above), (hits / positives if positives else float("nan"))
    return None, float("nan"), float("nan")


def highest_threshold_for_npv(scores: Sequence[float], truth: Sequence[bool],
                              target: float, *, min_count: int = DEFAULT_MIN_SUPPORT
                              ) -> Tuple[Optional[float], float]:
    """(t, npv): the highest threshold t such that items scored < t are
    human-negative at least `target` of the time. (None, nan) if none does."""
    pairs = sorted(zip(scores, truth), key=lambda x: x[0], reverse=True)
    for i, (s, _t) in enumerate(pairs):
        below = [p for p in pairs if p[0] < s]
        if len(below) < min_count:
            continue
        negatives = sum(1 for _, t in below if not t)
        if negatives / len(below) >= target:
            return s, negatives / len(below)
    return None, float("nan")


def per_code_calibration(pairs: pd.DataFrame, *, target: float = DEFAULT_TARGET,
                         min_support: int = DEFAULT_MIN_SUPPORT) -> pd.DataFrame:
    """Per code: the engine's current assignments against the person (P/R/F1,
    kappa), and the lowest `high` that would reach `target` precision."""
    cols = ["code", "n_items", "n_human", "n_model", "precision", "recall", "f1", "kappa",
            "reliable", "recommended_high", "precision_at_high", "recall_at_high"]
    if pairs.empty:
        return pd.DataFrame(columns=cols)
    human = {}
    model = {}
    for row in pairs.itertuples(index=False):
        human.setdefault(row.excerpt_id, set())
        model.setdefault(row.excerpt_id, set())
        if row.human:
            human[row.excerpt_id].add(row.code_name)
        if row.model_assigned:
            model[row.excerpt_id].add(row.code_name)
    validation = per_code_validation(human, model, codes=sorted(pairs["code_name"].unique()),
                                     min_support=min_support).set_index("code")
    rows = []
    for code, group in pairs.groupby("code_name"):
        t, p_at, r_at = lowest_threshold_for_precision(
            group["score"].tolist(), group["human"].tolist(), target, min_count=min_support)
        v = validation.loc[code]
        rows.append({"code": code, "n_items": int(v["n_items"]), "n_human": int(v["n_human"]),
                     "n_model": int(v["n_model"]), "precision": v["precision"],
                     "recall": v["recall"], "f1": v["f1"], "kappa": v["kappa"],
                     "reliable": bool(v["reliable"]), "recommended_high": t,
                     "precision_at_high": p_at, "recall_at_high": r_at})
    return pd.DataFrame(rows, columns=cols)


def agreement_by_code(pairs: pd.DataFrame, *, min_support: int = DEFAULT_MIN_SUPPORT) -> pd.DataFrame:
    """The person against the engine, code by code: Cohen's kappa beside percent agreement,
    each side's prevalence, how many answers, and whether there are enough of them.

    This is the agreement figure (kappa only). Precision, recall and F1 come with it as an
    error breakdown (which kind of mistake), never as a second agreement measure. The engine
    is a labelled side here, not a coder in a pair of coders.

    Columns: code, n_items, n_human, n_model, percent_agreement, prevalence_human,
    prevalence_model, kappa, reliable, note, precision, recall, f1.
    """
    cols = ["code", "n_items", "n_human", "n_model", "percent_agreement", "prevalence_human",
            "prevalence_model", "kappa", "reliable", "note", "precision", "recall", "f1"]
    if pairs.empty:
        return pd.DataFrame(columns=cols)
    human: Dict[str, Set[str]] = {}
    model: Dict[str, Set[str]] = {}
    for row in pairs.itertuples(index=False):
        human.setdefault(row.excerpt_id, set())
        model.setdefault(row.excerpt_id, set())
        if row.human:
            human[row.excerpt_id].add(row.code_name)
        if row.model_assigned:
            model[row.excerpt_id].add(row.code_name)
    table = per_code_validation(human, model, codes=sorted(pairs["code_name"].unique()),
                                min_support=min_support)
    return table[[c for c in cols if c in table.columns]].sort_values("code").reset_index(drop=True)


def decision_run_ids(project) -> List[str]:
    """Every structured-coding run that has a decision record, real runs before demo ones."""
    ids = [r["run_id"] for r in project._conn.execute(
        "SELECT DISTINCT run_id FROM coding_decisions ORDER BY run_id")]
    return sorted(ids, key=lambda r: ("__demo_" in r, r))


def sample_status(project, run_id: str) -> Tuple[int, int]:
    """(answers in this run's calibration sample, how many of them the person has judged)."""
    sample = load_sample(project, run_id)
    reviewed = project.coverage_excerpt_ids(HUMAN_RATER)
    return len(sample), sum(1 for e in sample if e in reviewed)


def run_excerpt_ids(project, run_id: str) -> List[str]:
    """The answers a run scored, in a stable order: what a sample is drawn from."""
    decisions = project.coding_decisions_table(run_id)
    return [] if decisions.empty else sorted(decisions["excerpt_id"].unique().tolist())


def recommend_band(pairs: pd.DataFrame, *, target: float = DEFAULT_TARGET,
                   min_count: int = DEFAULT_MIN_SUPPORT) -> Dict:
    """One (low, high) band for the whole run, pooled over codes, snapped to the
    slider's steps in the safe direction (high up, low down)."""
    if pairs.empty:
        return {"low": None, "high": None, "note": "No human-coded responses were scored."}
    scores, truth = pairs["score"].tolist(), pairs["human"].tolist()
    high, precision, recall = lowest_threshold_for_precision(scores, truth, target,
                                                             min_count=min_count)
    low, npv = highest_threshold_for_npv(scores, truth, target, min_count=min_count)
    # round(x / step, 6) first, so 0.85 / 0.05 = 16.999999... is not ceiled to 18.
    band_high = (None if high is None else
                 round(min(1.0, math.ceil(round(high / BAND_STEP, 6)) * BAND_STEP), 2))
    band_low = (None if low is None else
                round(max(0.0, math.floor(round(low / BAND_STEP, 6)) * BAND_STEP), 2))
    if band_low is not None and band_high is not None and band_low > band_high:
        band_low = band_high
    notes = []
    if high is None:
        notes.append(f"No threshold reaches {target:.0%} precision on this sample: keep "
                     f"routing to review, or write narrower criteria.")
    if low is None:
        notes.append(f"No threshold keeps {target:.0%} of low-scored responses free of "
                     f"the code: nothing can safely be treated as a confident no yet.")
    return {"low": band_low, "high": band_high, "precision_at_high": precision,
            "recall_at_high": recall, "npv_below_low": npv, "note": " ".join(notes)}


def reliability_table(pairs: pd.DataFrame, n_bins: int = 10) -> pd.DataFrame:
    """Mean score against the observed rate, per score bin."""
    if pairs.empty:
        return calibration_curve([], [])
    return calibration_curve(pairs["score"].tolist(), pairs["human"].tolist(), n_bins=n_bins)


# ── the project side: where a calibration sample lives ─────────────────────────
#: A run's calibration sample is stored as a named run configuration (the
#: existing "spec as JSON" table), so it needs no schema change.
SAMPLE_PREFIX = "calibration::"
HUMAN_RATER = "human_primary"


def save_sample(project, run_id: str, excerpt_ids: Sequence[str], *, seed: int = 42) -> None:
    from core.model import CodingRunConfig

    project.save_coding_run_config(CodingRunConfig(
        config_id="", name=f"{SAMPLE_PREFIX}{run_id}",
        spec={"run_id": run_id, "sample": list(excerpt_ids), "seed": seed}))


def load_sample(project, run_id: str) -> List[str]:
    config = project.get_coding_run_config(f"{SAMPLE_PREFIX}{run_id}")
    return list(config.spec.get("sample", [])) if config else []


def calibration_pairs(project, run_id: str) -> pd.DataFrame:
    """Scores and human judgements for the sampled responses the person has
    coded (the v8 review record says which; an unreviewed one is left out)."""
    sample = set(load_sample(project, run_id))
    item_set = project.rater_item_set(HUMAN_RATER)
    human = {e: codes for e, codes in item_set.labels.items() if e in sample} if item_set.recorded else {}
    return score_pairs(project.coding_decisions_table(run_id), human)


def calibrations(project, *, target: float = DEFAULT_TARGET) -> List[Dict]:
    """Every run with a coded calibration sample: its per-code table and band."""
    out = []
    for run_id in sorted({c.name[len(SAMPLE_PREFIX):] for c in _run_configs(project)
                          if c.name.startswith(SAMPLE_PREFIX)}):
        pairs = calibration_pairs(project, run_id)
        if pairs.empty:
            continue
        out.append({"run_id": run_id, "n_responses": int(pairs["excerpt_id"].nunique()),
                    "table": per_code_calibration(pairs, target=target),
                    "band": recommend_band(pairs, target=target), "target": target})
    return out


def _run_configs(project):
    names = [r["name"] for r in project._conn.execute("SELECT name FROM coding_run_configs")]
    return [project.get_coding_run_config(n) for n in names]


def decisions_export(decisions: pd.DataFrame, *, include_text: bool = False) -> pd.DataFrame:
    """The run's full decision record for a spreadsheet: every candidate code,
    its score, what the engine did and what a person decided. Response text
    only on request (it is the data itself)."""
    columns = ["excerpt_id", "source_id", "code_name", "model_score", "model_assigned",
               "review_status", "human_assigned", "reviewer", "reviewed_at", "note"]
    if include_text:
        columns.insert(2, "excerpt_text")
    return decisions.reindex(columns=columns).reset_index(drop=True)
