#!/usr/bin/env python
"""
Post-double-selection lasso — an effect for one named variable (`V6_PLAN.md` §4).

The headline of v6 and the one method here no rival ships. NVivo, ATLAS.ti and
Dedoose have no regression at all; MAXQDA Stats stops at OLS. Double lasso is
mainstream applied econometrics — `pdslasso` in Stata, `hdm` in R
(Belloni, Chernozhukov and Hansen) — and has never been available beside the
coding that generated the variables.

**Kept in its own file on purpose.** Everything in `analysis/models.py` predicts
and reports no interval; this estimates and reports one. Fitting a lasso,
reading which variables survived, and then testing the survivors on the same
data is invalid, and it is the easiest mistake to make in a panel offering both.
The separation is the guard rail, and it is why the spec demands a named
treatment before this can run at all.

The procedure, and the step naive versions drop
-----------------------------------------------
1. Lasso the **outcome** on the controls. Keep what survives.
2. Lasso the **treatment** on the controls. Keep what survives.
3. Take the **union**, plus anything the analyst forced onto the Controls shelf,
   which is never penalised.
4. OLS the outcome on treatment + that union, with heteroskedasticity-robust
   (HC1) standard errors. Report the treatment coefficient.

**Step 2 is the whole method.** A control that predicts the treatment strongly
but the outcome only weakly is exactly the confounder single-selection lasso
discards — and discarding it is what biases the estimate. Implementations that
lasso only the outcome and call it double selection get this wrong; a test
builds a fixture where that shortcut gives a visibly wrong answer.

What the interval is, and what it is not
----------------------------------------
The interval is valid **despite the selection** — that is the entire reason the
method exists, and it is what a lasso-then-OLS workflow cannot give.

It is **not a causal claim**. It is a defensible number under the assumption
that the confounders are among the controls. In survey data, coded by the
analyst, that assumption is doing enormous work, and `caveats()` says so every
time rather than leaving it to a footnote somebody removes.

Two honest departures from the paper
------------------------------------
- **The penalty is chosen by cross-validation,** not by the theoretical plug-in
  rule of the original papers. CV is the practical default in most software and
  is defensible; the plug-in penalty has better guarantees under the paper's
  assumptions. Stated here rather than left for a reader to discover.
- **A binary outcome is fitted as a linear probability model.** Common in
  applied work, and it keeps the final stage a linear projection with a robust
  standard error, which is what makes the interval interpretable. The
  coefficient reads as a change in probability, and `caveats()` says so.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from analysis.models import BINARY_LEVELS, Estimate, ModelResult, _prepare, _standardised

#: The interval reported. 95% because that is what a paper prints.
CONFIDENCE = 0.95

#: Normal critical value at `CONFIDENCE`. Hard-coded rather than pulled from
#: scipy so this module keeps working in a lite install; the difference from a
#: t critical value is negligible at the sample sizes this method allows, and
#: the degrees-of-freedom correction is in the HC1 factor.
_Z = 1.959963984540054


@dataclass(frozen=True)
class EffectEstimate:
    """The number this method exists to produce."""

    treatment: str
    coefficient: float
    std_error: float
    #: Lower and upper bound of the confidence interval.
    interval: Tuple[float, float]
    #: Controls chosen by the outcome lasso, the treatment lasso, and forced.
    selected_by_outcome: List[str] = field(default_factory=list)
    selected_by_treatment: List[str] = field(default_factory=list)
    forced: List[str] = field(default_factory=list)

    @property
    def union(self) -> List[str]:
        seen = list(self.forced)
        for name in self.selected_by_outcome + self.selected_by_treatment:
            if name not in seen:
                seen.append(name)
        return seen

    @property
    def only_from_treatment(self) -> List[str]:
        """Controls the treatment lasso caught and the outcome lasso missed.

        The method's whole justification, made visible: these are the confounders
        a single-selection workflow would have dropped.
        """
        return [n for n in self.selected_by_treatment
                if n not in self.selected_by_outcome and n not in self.forced]

    def crosses_zero(self) -> bool:
        return self.interval[0] <= 0.0 <= self.interval[1]


def estimate_effect(matrix, request) -> ModelResult:
    """Estimate the effect of the treatment on the outcome.

    `matrix` is a `DesignMatrix`, `request` a `ModelRequest` whose Treatment
    shelf names one variable. Returns a `ModelResult` whose `effect` carries the
    estimate; the estimates list holds the final-stage coefficients so the whole
    model can be shown, with the treatment first.
    """
    outcome = request.outcome.first
    treatment = request.treatment.first
    forced = [c for c in request.controls.fields if c != treatment]
    candidates = [c for c in request.right_hand_side()
                  if c != treatment and c not in forced]

    frame = matrix.frame
    terms = [treatment] + forced + candidates
    y, X, kept, n_before = _prepare(frame, outcome, terms)

    if len(y) < 3 or X.shape[1] == 0:
        return ModelResult(
            method="double_lasso", outcome=outcome,
            n_cases=len(y), n_cases_before=n_before,
            refusal=("Not enough complete cases to estimate an effect. Missing "
                     "descriptor values drop a whole case."))

    index = {name: i for i, name in enumerate(kept)}
    d = X[:, index[treatment]]
    if float(np.std(d)) == 0.0:
        return ModelResult(
            method="double_lasso", outcome=outcome,
            n_cases=len(y), n_cases_before=n_before,
            refusal=(f"“{treatment}” has the same value on every complete case, "
                     "so it has no effect to estimate."))

    forced_idx = [index[name] for name in forced if name in index]
    candidate_names = [name for name in candidates if name in index]
    candidate_idx = [index[name] for name in candidate_names]
    Z = X[:, candidate_idx] if candidate_idx else np.empty((len(y), 0))

    # -- the two selection steps --------------------------------------------
    by_outcome = _select(Z, y, candidate_names, seed=request.seed,
                         folds=request.folds)
    by_treatment = _select(Z, d, candidate_names, seed=request.seed,
                           folds=request.folds)

    keep_names: List[str] = []
    for name in candidate_names:
        if name in by_outcome or name in by_treatment:
            keep_names.append(name)

    # -- the final stage -----------------------------------------------------
    columns = [index[treatment]] + forced_idx + [index[n] for n in keep_names]
    design = np.column_stack([np.ones(len(y)), X[:, columns]])

    # Drop controls that are exact linear combinations of what is already in.
    # This is not hypothetical: `n_codes` in the design matrix is the SUM of the
    # code columns, so selecting it alongside every code makes the design
    # singular by construction, and the estimate was being refused for a
    # redundant control rather than for anything about the treatment. The
    # treatment is at position 1 and the intercept at 0, so both survive by
    # construction — a redundant control must never cost the effect.
    keep_columns, dropped_columns = _independent_columns(design)
    design = design[:, keep_columns]

    coefficients, errors = _ols_hc1(design, y)
    if coefficients is None:
        return ModelResult(
            method="double_lasso", outcome=outcome,
            n_cases=len(y), n_cases_before=n_before,
            refusal=("The selected controls are collinear with the treatment, "
                     "so its effect cannot be separated from theirs. Remove one "
                     "of the forced controls and try again."))

    # index 0 is the intercept, 1 is the treatment
    coefficient, std_error = float(coefficients[1]), float(errors[1])
    half = _Z * std_error
    effect = EffectEstimate(
        treatment=treatment, coefficient=coefficient, std_error=std_error,
        interval=(coefficient - half, coefficient + half),
        selected_by_outcome=list(by_outcome),
        selected_by_treatment=list(by_treatment),
        forced=[n for n in forced if n in index])

    all_names = [treatment] + [n for n in forced if n in index] + keep_names
    # keep_columns indexes the design, whose column 0 is the intercept.
    names = [all_names[position - 1] for position in keep_columns if position]
    estimates = [Estimate(name, float(value))
                 for name, value in zip(names, coefficients[1:])]
    redundant = [all_names[position - 1] for position in dropped_columns
                 if position]

    levels = int(frame[outcome].nunique())
    notes = list(matrix.caveats()) + _caveats(effect, y, levels, len(y),
                                              n_before, len(candidate_names))
    if redundant:
        # Number agreement matters here because this sentence goes into a Word
        # document and then into a chapter. "was dropped ... each is" read
        # wrong in the first exported report, which is where it was caught.
        one = len(redundant) == 1
        notes.append(
            f"{_listed(redundant)} dropped from the final model: "
            + ("it is an exact combination of the other terms, so it carries "
               "no information of its own"
               if one else
               "each is an exact combination of the other terms, so they carry "
               "no information of their own")
            + " and would make the estimate unidentifiable."
            + ("" if "n_codes" in redundant else
               " “n_codes”, the total of the code columns, is the "
               "usual cause."))

    result = ModelResult(
        method="double_lasso", outcome=outcome, kind="coefficient",
        estimates=estimates, n_cases=len(y), n_cases_before=n_before,
        chosen={"selected": len(keep_names),
                "candidates": len(candidate_names)},
        seed=request.seed, effect=effect, notes=notes)
    return result


def _select(Z: np.ndarray, target: np.ndarray, names: Sequence[str], *,
            seed: int, folds: int) -> List[str]:
    """Lasso `target` on `Z`; return the columns with a non-zero coefficient.

    Standardised first, because a penalty is scale-dependent: without it a 0/1
    code and a 0–4 GPA are penalised differently for no reason but their units,
    and the selection would partly reflect measurement scale.
    """
    if Z.shape[1] == 0 or len(target) < 5:
        return []

    from sklearn.linear_model import LassoCV
    from sklearn.model_selection import KFold

    Zs, _ = _standardised(Z)
    splitter = KFold(max(2, min(folds, len(target) // 5 or 2)),
                     shuffle=True, random_state=seed)
    model = LassoCV(cv=splitter, random_state=seed, max_iter=20000)
    model.fit(Zs, target - target.mean())
    return [name for name, coefficient in zip(names, model.coef_)
            if coefficient != 0.0]


def _listed(names: List[str]) -> str:
    quoted = [f"“{name}”" for name in names]
    if len(quoted) == 1:
        return f"{quoted[0]} was"
    return f"{', '.join(quoted[:-1])} and {quoted[-1]} were"


def _independent_columns(design: np.ndarray, tolerance: float = 1e-9):
    """Split columns into those that add information and those that do not.

    QR **without** pivoting, on the columns in the order given. Pivoting would
    reorder by magnitude and could discard the treatment; here a small diagonal
    entry of R means "this column is a combination of the ones before it", so
    earlier columns win and the intercept and treatment — positions 0 and 1 —
    are safe by construction.
    """
    if design.shape[1] == 0:
        return [], []
    _, r = np.linalg.qr(design)
    diagonal = np.abs(np.diag(r))
    scale = float(diagonal.max()) if diagonal.size else 0.0
    threshold = max(tolerance, scale * tolerance)

    keep = [i for i in range(design.shape[1]) if diagonal[i] > threshold]
    dropped = [i for i in range(design.shape[1]) if diagonal[i] <= threshold]
    return keep, dropped


def _ols_hc1(design: np.ndarray, y: np.ndarray):
    """Least squares with heteroskedasticity-robust (HC1) standard errors.

    Twenty lines of numpy rather than a dependency on statsmodels, which is not
    installed and is not being added for this.

    HC1 rather than plain OLS errors because the final stage is a linear
    projection, often of a binary outcome, and homoskedasticity is not a
    defensible assumption there. `lstsq` rather than a normal-equation inverse
    because the selected controls are frequently near-collinear.
    """
    n, k = design.shape
    if n <= k:
        return None, None

    coefficients, *_ = np.linalg.lstsq(design, y, rcond=None)
    residuals = y - design @ coefficients

    gram = design.T @ design
    try:
        inverse = np.linalg.inv(gram)
    except np.linalg.LinAlgError:                       # pragma: no cover
        return None, None
    if not np.all(np.isfinite(inverse)):                # pragma: no cover
        return None, None

    meat = design.T @ (design * (residuals ** 2)[:, None])
    covariance = inverse @ meat @ inverse * (n / (n - k))   # HC1 correction
    variances = np.diag(covariance)
    if np.any(variances < 0):                           # pragma: no cover
        return None, None
    return coefficients, np.sqrt(variances)


def _caveats(effect: EffectEstimate, y: np.ndarray, levels: int,
             n_cases: int, n_before: int, n_candidates: int) -> List[str]:
    """What has to be said alongside an effect estimate, every time."""
    notes = [
        "This interval is valid despite the variable selection — that is what "
        "double lasso is for, and what selecting with a lasso and then testing "
        "the survivors cannot give you.",
        "It is not a causal claim. It is a defensible estimate under the "
        "assumption that the things confounding "
        f"“{effect.treatment}” and the outcome are among the controls offered "
        "here. In coded survey data that assumption is doing a great deal of "
        "work, and nothing in the arithmetic checks it.",
        f"{len(effect.union)} control(s) entered the final model out of "
        f"{n_candidates} offered: {len(effect.selected_by_outcome)} chosen for "
        f"predicting the outcome, {len(effect.selected_by_treatment)} for "
        f"predicting the treatment.",
    ]
    if effect.only_from_treatment:
        listed = ", ".join(effect.only_from_treatment[:4])
        notes.append(
            f"Kept only because they predict the treatment: {listed}. A "
            "single-selection lasso would have dropped these, and dropping them "
            "is what biases the estimate — this is the method working.")
    if effect.crosses_zero():
        notes.append(
            "The interval includes zero. That is not evidence of no effect; on "
            "a sample this size it is usually evidence that the data cannot "
            "resolve one.")
    if levels <= BINARY_LEVELS:
        notes.append(
            "The outcome is binary and fitted as a linear probability model, so "
            "the coefficient reads as a change in probability. Predictions "
            "outside 0–1 are possible and are a known limitation of doing it "
            "this way.")
    if n_before - n_cases:
        notes.append(
            f"{n_before - n_cases} case(s) were dropped for missing values. "
            "Cases are dropped whole, so one sparse descriptor can cost many.")
    notes.append(
        "The penalty was chosen by cross-validation rather than by the "
        "theoretical plug-in rule of the original papers. That is the common "
        "practical default; the plug-in rule has better guarantees under the "
        "paper's assumptions.")
    return notes
