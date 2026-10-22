#!/usr/bin/env python
"""
The model spec: drag-and-drop shelves for a statistical model (`V6_PLAN.md` §3).

`core/chart_spec.py` decides what a *chart* is; this decides what a *model* is.
Deliberately the same shape — `SHELVES`, a `Shelf`, a request, `problems()`,
`describe()`, `to_dict`/`from_dict` — because the interaction that already works
for building a figure is the interaction that should build a model, and because
a grammar the two front ends share is what stops the desktop and the web build
answering the same question differently.

Nothing here fits anything. It holds what the analyst chose and says what is
wrong with it. `analysis/models.py` does the fitting; this module imports no
model library, and a test enforces that.

The shelves
-----------
========== ================= ==========================================
shelf      holds             rule
========== ================= ==========================================
outcome    exactly one       the thing being explained
treatment  at most one       double lasso only — the variable you want
                             a defensible number for
predictors any number        what the model may use
controls   any number        forced into the final stage, never
                             penalised out
========== ================= ==========================================

**Dragging a field onto Treatment is what turns prediction into inference.** That
is the design's one real opinion. The interface could offer a *p*-value beside
every lasso coefficient and nobody would immediately notice it was invalid;
requiring a named treatment first makes the analyst state a hypothesis before
the program will give them a confidence interval, which is what the method
demands anyway. `V6_PLAN.md` §6 lists "a *p*-value anywhere on the lasso screen"
as a way this feature fails.

Why `problems()` returns sentences
----------------------------------
Same reason as the chart builder: "n=34 < 100" is a fact, and
"Double lasso needs about 100 cases to give an interval worth reporting; this
project has 34" is an answer. The run button stays disabled while any blocking
problem stands, and the analyst can disagree with a number rather than with a
mood.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field
from typing import Any, Dict, List, Optional, Sequence, Tuple

#: Shelf names, in the order a panel should show them.
SHELVES = ("outcome", "treatment", "predictors", "controls")

_PACKAGE_STATE: Dict[str, bool] = {}


def package_works(name: str) -> bool:
    """Can `name` be imported here? Tried once and remembered: importing a package is slow, and a
    package that is installed but cannot load (a missing system library, for example OpenMP on a
    Mac) must count as not available rather than fail later in the middle of a fit."""
    if name not in _PACKAGE_STATE:
        import importlib

        try:
            importlib.import_module(name)
            _PACKAGE_STATE[name] = True
        except Exception:  # noqa: BLE001 - any failure to load means it cannot be used
            _PACKAGE_STATE[name] = False
    return _PACKAGE_STATE[name]


@dataclass(frozen=True)
class Method:
    """One fittable model, and the honest conditions for using it."""

    key: str
    label: str
    #: Cases below which this method is refused. Printed with the refusal so
    #: it can be argued with.
    floor: int
    #: Extra cases required per candidate predictor, on top of `floor`. Zero
    #: for most methods; non-zero where the honest requirement grows with the
    #: number of candidates rather than sitting at a constant.
    floor_per_predictor: float = 0.0

    def required_cases(self, n_predictors: int) -> int:
        """The floor for a model with this many terms on the right."""
        import math

        return max(self.floor,
                   int(math.ceil(self.floor_per_predictor * max(0, n_predictors))))
    #: True when the method exists to produce an effect estimate for one named
    #: variable rather than to predict the outcome.
    inferential: bool = False
    #: Whether it reports per-variable coefficients (else importances).
    coefficients: bool = True
    blurb: str = ""
    #: A Python package the method needs that is not part of the core install (XGBoost).
    #: The method is listed either way; without the package it is refused in a sentence.
    requires: str = ""

    def available(self) -> bool:
        """Whether the package this method needs can be used on this computer."""
        return not self.requires or package_works(self.requires)

    @property
    def display_label(self) -> str:
        """The label to show in a list: says so when the method cannot be used here."""
        return self.label if self.available() else f"{self.label} (not installed)"


METHODS: Dict[str, Method] = {
    "ols": Method(
        "ols", "Linear / logistic regression", floor=30,
        blurb="The honest baseline. Every other method here should be compared "
              "against it, and often it is enough."),
    "lasso": Method(
        "lasso", "Lasso (L1)", floor=50,
        blurb="Shrinks weak predictors to exactly zero, so it answers “which of "
              "these many codes and descriptors carry signal”. It does not "
              "produce valid confidence intervals for the survivors — that is "
              "what double lasso is for."),
    "ridge": Method(
        "ridge", "Ridge (L2)", floor=50,
        blurb="Keeps every predictor but shrinks them. Better than lasso when "
              "predictors are collinear, which codes usually are."),
    "elastic_net": Method(
        "elastic_net", "Elastic net", floor=50,
        blurb="Lasso and ridge together: selects, but handles groups of "
              "correlated codes without picking one arbitrarily."),
    "double_lasso": Method(
        # Measured with `tools/simulate_project.py --calibrate`, which fits the
        # estimator against simulated projects with a known effect and counts
        # how often the 95% interval actually contains it. At 41 candidates,
        # 120 trials each:
        #
        #     n     coverage   ~SE    reading
        #     40      0.825   0.035   3.6 SE below nominal — over-confident
        #     60      0.883   0.029   2.3 SE below
        #     80      0.900   0.027   1.9 SE below
        #    120      0.950   0.020   nominal
        #
        # So the requirement grows with the candidate count, and 3.0 per
        # candidate puts the threshold at 123 for that case — the first size
        # measured clean. A flat 100 was both too strict at small p and too
        # LENIENT here, which is the dangerous direction.
        #
        # What this does not establish: the coefficient itself, beyond "about
        # three". Runs at 9 and 21 candidates sit within two standard errors of
        # nominal almost everywhere, so they constrain it barely at all, and one
        # data-generating process cannot speak for non-linear effects or several
        # confounders. It errs toward refusing, which is the right direction for
        # a program whose discipline is declining to print numbers it cannot
        # support.
        "double_lasso", "Double lasso (effect of one variable)", floor=60,
        floor_per_predictor=3.0, inferential=True,
        blurb="Post-double-selection. Select controls that predict the outcome, "
              "select controls that predict the treatment, keep the union, then "
              "estimate. The interval stays valid despite the selection, which "
              "is the entire reason the method exists."),
    "decision_tree": Method(
        "decision_tree", "Decision tree (readable rules)", floor=60,
        coefficients=False,
        blurb="One tree, shallow enough to read. Its output is a set of rules — "
              "“coded Cost and first-generation → 70% did not return” — which is "
              "a sentence that can go in a paper. Less accurate than a forest and "
              "unstable on small samples, and worth having anyway because nothing "
              "else here explains itself."),
    "extra_trees": Method(
        "extra_trees", "Extremely randomised trees", floor=80,
        coefficients=False,
        blurb="A forest that also picks its split points at random. Faster, and "
              "usually a little better than a random forest when predictors are "
              "noisy — which codes are."),
    "random_forest": Method(
        "random_forest", "Random forest", floor=80, coefficients=False,
        blurb="Trees on bootstrap samples, in parallel. Finds non-linearities "
              "and interactions; reports importance, not effects."),
    "gradient_boosting": Method(
        "gradient_boosting", "Gradient boosting", floor=80, coefficients=False,
        blurb="Trees fitted in sequence to what the previous ones got wrong. "
              "Usually stronger than a forest and easier to overfit."),
    "xgboost": Method(
        # Fitted with a fixed seed on one thread so the same project gives the same numbers.
        # The floor is 100, above the 80 of the other tree ensembles: boosted trees fit the
        # training cases closely, and below about a hundred the importance ranking mostly
        # reflects which cases landed in the held-out quarter.
        "xgboost", "XGBoost (boosted trees)", floor=100, coefficients=False, requires="xgboost",
        blurb="A fast, regularised kind of gradient boosting. Often the strongest of the tree "
              "methods, and the easiest to over-trust: it reports importance, not effects, and "
              "needs a hundred cases or more."),
    "sgd_linear": Method(
        "sgd_linear", "Linear model (SGD)", floor=50,
        blurb="A linear model fitted by stochastic gradient descent. A fitting "
              "method rather than a model family — useful when the matrix is "
              "wide and sparse, which a codes-as-columns matrix is."),
}

#: Distinct values below which an outcome cannot carry a regression. Two is a
#: classification; one is nothing.
MIN_OUTCOME_LEVELS = 2

#: Cases per predictor below which a linear model is fitting noise. Ten is the
#: usual rule of thumb; regularised methods relax it, which is why they exist,
#: so this is advice rather than a refusal.
COMFORTABLE_CASES_PER_PREDICTOR = 10


@dataclass(frozen=True)
class Shelf:
    """The fields on one shelf, in the order they were dropped."""

    fields: Tuple[str, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not self.fields

    @property
    def first(self) -> str:
        return self.fields[0] if self.fields else ""


@dataclass(frozen=True)
class ModelRequest:
    """Everything the analyst chose. A plain value, comparable and hashable."""

    method: str = "ols"
    outcome: Shelf = dataclass_field(default_factory=Shelf)
    treatment: Shelf = dataclass_field(default_factory=Shelf)
    predictors: Shelf = dataclass_field(default_factory=Shelf)
    controls: Shelf = dataclass_field(default_factory=Shelf)
    title: str = ""
    #: Fixed so a model is reproducible. Recorded in the manifest and the
    #: methods appendix; a model whose numbers move between runs is not
    #: admissible in a program that sells reproducibility.
    seed: int = 20260829
    #: Cross-validation folds where the method uses them.
    folds: int = 5

    def shelf(self, name: str) -> Shelf:
        return getattr(self, name)

    @property
    def method_spec(self) -> Optional[Method]:
        return METHODS.get(self.method)

    def right_hand_side(self) -> List[str]:
        """Every field that enters the model, treatment first, without repeats."""
        ordered: List[str] = []
        for name in ("treatment", "predictors", "controls"):
            for column in self.shelf(name).fields:
                if column and column not in ordered:
                    ordered.append(column)
        return ordered


# ── validation ───────────────────────────────────────────────────────────────

def problems(request: ModelRequest, columns: Sequence[str], *,
             n_cases: int = 0,
             outcome_levels: Optional[int] = None) -> List[str]:
    """Everything wrong with this spec, in plain sentences. Empty means fine.

    `columns` is what the design matrix actually has, so a spec referring to a
    code that was dropped for having no variation is caught here rather than
    surfacing as a `KeyError` mid-fit.

    Blocking and advisory problems are not separated — `can_run` decides what
    blocks, and the analyst should see the whole list either way. Same choice as
    `chart_spec.problems`, for the same reason.
    """
    found: List[str] = []
    available = set(columns)

    method = request.method_spec
    if method is None:
        return [f"“{request.method}” is not a method this program knows."]
    if not method.available():
        found.append(
            f"{method.label} needs an extra component ({method.requires}) that is not installed "
            "in this copy of QualSafe. Pick another method.")

    # -- the outcome ---------------------------------------------------------
    if request.outcome.is_empty:
        found.append("Drop a field on Outcome: a model needs something to "
                     "explain.")
    elif len(request.outcome.fields) > 1:
        found.append("Outcome takes one field. Fit a separate model for each "
                     "thing you want to explain, rather than one model with "
                     "several outcomes.")
    elif request.outcome.first not in available:
        found.append(
            f"“{request.outcome.first}” is not in the design matrix. It may "
            "have been dropped for having too little variation to model.")

    if outcome_levels is not None and outcome_levels < MIN_OUTCOME_LEVELS:
        found.append(
            f"“{request.outcome.first}” has the same value on every case, so "
            "there is nothing to explain.")

    # -- the treatment, and what it means -----------------------------------
    if method.inferential and request.treatment.is_empty:
        found.append(
            f"{method.label} estimates the effect of one named variable. Drop "
            "the variable you want a defensible number for on Treatment.")
    if not method.inferential and not request.treatment.is_empty:
        found.append(
            f"{method.label} does not estimate an effect for a single variable, "
            "so Treatment is ignored. Switch to double lasso if you want a "
            "confidence interval for "
            f"“{request.treatment.first}”, or move it to Predictors.")
    if len(request.treatment.fields) > 1:
        found.append(
            "Treatment takes one field. Estimating several effects at once from "
            "the same selection is exactly what double lasso is designed to "
            "avoid; fit one model per variable of interest.")

    # -- overlaps ------------------------------------------------------------
    outcome_name = request.outcome.first
    if outcome_name and outcome_name in request.right_hand_side():
        found.append(
            f"“{outcome_name}” is both the outcome and a predictor. A model "
            "that explains a thing with itself fits perfectly and means "
            "nothing.")
    overlap = (set(request.treatment.fields)
               & (set(request.predictors.fields) | set(request.controls.fields)))
    if overlap:
        found.append(
            f"{_listed(sorted(overlap))} on Treatment and on another shelf. The "
            "treatment is already in the model; having it twice would make its "
            "effect uninterpretable.")

    # -- fields that are not there ------------------------------------------
    missing = [c for c in request.right_hand_side() if c not in available]
    if missing:
        found.append(
            f"{_listed(missing)} not in the design matrix — dropped for too "
            "little variation, or from a different project.")

    if not request.right_hand_side():
        found.append("Drop at least one field on Predictors: there is nothing "
                     "for the model to explain the outcome with.")

    # -- sample size ---------------------------------------------------------
    if n_cases:
        required = method.required_cases(len(request.right_hand_side()))
        if n_cases < required:
            growth = ""
            if required > method.floor:
                growth = (f" That is {method.floor} plus "
                          f"{method.floor_per_predictor:g} per candidate "
                          f"predictor, because the interval gets over-confident "
                          f"as candidates grow against cases.")
            found.append(
                f"{method.label} needs about {required} cases to say "
                f"anything worth reporting; this project has {n_cases}. "
                + _floor_reason(method) + growth)
        count = len(request.right_hand_side())
        if count and not method.inferential and method.coefficients:
            per = n_cases / count
            if per < COMFORTABLE_CASES_PER_PREDICTOR and request.method == "ols":
                found.append(
                    f"{count} predictors on {n_cases} cases is "
                    f"{per:.1f} cases each. Plain regression will fit noise at "
                    f"that ratio — {_ratio_remedy(n_cases)}")
        if request.folds > max(2, n_cases // 5):
            found.append(
                f"{request.folds}-fold cross-validation on {n_cases} cases "
                f"leaves about {max(1, n_cases // request.folds)} case(s) per "
                "fold. Use fewer folds, or read the result as a guess.")

    return found


def _ratio_remedy(n_cases: int) -> str:
    """Name a fix the analyst can actually take at this sample size.

    The first version said "this is what lasso and ridge are for" unconditionally
    — and at n = 42 lasso is itself below its floor of 50, so the program told
    the analyst to use a method it then refused to run. Found by walking
    realistic specs through the panel rather than by a test: every test passed,
    and the advice sent someone in a circle.

    When no shrinkage method is available either, the honest answer is that the
    project is too small for this many predictors by any route.
    """
    shrinkage = [METHODS[key] for key in ("lasso", "ridge", "elastic_net")
                 if key in METHODS and n_cases >= METHODS[key].floor]
    if not shrinkage:
        return ("and so will lasso or ridge at this sample size. Use fewer "
                "predictors, or gather more cases; there is no method that "
                "makes this many predictors safe on "
                f"{n_cases} cases.")
    names = " or ".join(m.label for m in shrinkage[:2])
    return f"this is what {names} are for."


def _floor_reason(method: Method) -> str:
    if method.inferential:
        return ("Below that the interval is optimistic in a way that is not "
                "visible in the output.")
    if not method.coefficients:
        return ("Below that an importance ranking mostly reflects which cases "
                "landed in which split.")
    return "Below that the coefficients move a lot between samples."


def can_run(request: ModelRequest, columns: Sequence[str], *,
            n_cases: int = 0, outcome_levels: Optional[int] = None) -> bool:
    """Whether the spec is fittable at all.

    Advisory problems — a fold count that is merely unwise, a predictor ratio
    that is merely uncomfortable — do not block. Everything else does, including
    the sample-size floors: a method run below its floor produces a number the
    program would then have to spend its credibility qualifying.
    """
    advisory = ("cases each", "case(s) per")
    for problem in problems(request, columns, n_cases=n_cases,
                            outcome_levels=outcome_levels):
        if not any(marker in problem for marker in advisory):
            return False
    return True


def describe(request: ModelRequest) -> str:
    """One line for a caption, a log, or the methods appendix."""
    method = request.method_spec
    label = method.label if method else request.method
    outcome = request.outcome.first or "(no outcome)"
    if method is not None and method.inferential:
        treatment = request.treatment.first or "(no treatment)"
        others = len(request.right_hand_side()) - 1
        return (f"{label}: effect of {treatment} on {outcome}, "
                f"with {max(0, others)} control(s)")
    return (f"{label}: {outcome} on "
            f"{len(request.right_hand_side())} predictor(s)")


# ── persistence ──────────────────────────────────────────────────────────────

def request_to_dict(request: ModelRequest) -> Dict[str, Any]:
    """Plain JSON, so a model can be saved with the project and re-run later.

    Same contract as `chart_spec.request_to_dict`: what is stored is the
    *specification*, never the fitted result. A saved model re-run against a
    project that has been coded further should give the newer answer — that is
    the point of saving it rather than saving a screenshot.
    """
    return {
        "method": request.method,
        "shelves": {name: list(request.shelf(name).fields) for name in SHELVES},
        "title": request.title,
        "seed": request.seed,
        "folds": request.folds,
    }


def request_from_dict(data: Dict[str, Any]) -> ModelRequest:
    """Rebuild a request. Tolerant of missing keys, so an older saved model
    still opens rather than raising in a dialog."""
    shelves = data.get("shelves", {}) or {}
    fields = {
        name: Shelf(tuple(str(c) for c in (shelves.get(name) or [])))
        for name in SHELVES
    }
    return ModelRequest(
        method=str(data.get("method", "ols")),
        title=str(data.get("title", "")),
        seed=int(data.get("seed", 20260829)),
        folds=int(data.get("folds", 5)),
        **fields,
    )


def _listed(names: Sequence[str]) -> str:
    quoted = [f"“{name}”" if not name.startswith("“") else name for name in names]
    if len(quoted) == 1:
        return f"{quoted[0]} is"
    return f"{', '.join(quoted[:-1])} and {quoted[-1]} are"
