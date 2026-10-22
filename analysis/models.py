#!/usr/bin/env python
"""
Fitting a `ModelRequest` against a `DesignMatrix` (`V6_PLAN.md` §4, Phase B).

`core/model_spec.py` says what a model *is* and refuses specs that cannot be
fitted. `analysis/design_matrix.py` says what the data *is*. This does the
fitting, and returns one shape — `ModelResult` — whatever method ran, so a front
end renders results without knowing which model produced them.

Everything from scikit-learn, already a declared dependency in
`requirements.txt`, `requirements-light.txt` and `pyproject.toml`. No new
dependency, which matters for a program whose selling point is that it installs
and runs offline.

Prediction, not inference
-------------------------
**Nothing in this module reports a p-value or a confidence interval.** That is
deliberate and is the point of `analysis/double_lasso.py` being a separate file.
Fitting a lasso, reading which variables survived, and then reporting a
significance test on the survivors is invalid — the selection used the same data
— and it is the single easiest mistake to make in a panel that offers both. So
the two live apart, the inferential one demands a named treatment, and this one
does not have the machinery to print an interval even if asked.

`ModelResult.estimates` are coefficients where the method has them and
importances where it does not, and `ModelResult.kind` says which. They are not
interchangeable and the interface must not present them as though they were: a
coefficient is a direction and a magnitude in the outcome's units; a permutation
importance is "the model got this much worse when I shuffled this column".

Reproducibility
---------------
Every fit takes its seed from the request, every cross-validation is seeded, and
the seed comes back in the result so it reaches the run manifest and the methods
appendix. A model whose numbers move between runs is not admissible in a program
that sells reproducibility.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from core.model_spec import METHODS, ModelRequest, can_run, problems

#: Distinct outcome values at or below which the outcome is treated as a
#: classification. Two is a yes/no; three or more is treated as continuous,
#: which is a simplification an ordinal outcome deserves better than — stated in
#: the caveats rather than hidden.
BINARY_LEVELS = 2

#: Permutation-importance repeats. Enough to be stable, few enough to stay
#: instant on the sample sizes this program sees.
PERMUTATION_REPEATS = 10

#: Trees in a forest. Was 400, which cost about thirty seconds a fit and
#: bought nothing: measured across 100/200/400/800 trees at n = 100 and
#: n = 300, cross-validated accuracy was IDENTICAL to four decimals up to
#: 400, and 800 differed only by noise in both directions. A forest's
#: variance reduction saturates long before this on data this small, and
#: `n_jobs=-1` measured *slower* here than `n_jobs=1` — at a few hundred
#: rows the thread overhead is larger than the work.
FOREST_TREES = 200


@dataclass(frozen=True)
class Estimate:
    """One variable's number, whatever kind of number the method produces."""

    name: str
    value: float
    #: True when the method shrank this term to exactly zero — lasso's actual
    #: answer, and worth showing rather than filtering away.
    dropped: bool = False


@dataclass(frozen=True)
class ModelResult:
    """What one fit produced, and everything needed to read it honestly."""

    method: str
    outcome: str
    #: "coefficient" or "importance". Never mix them in one table.
    kind: str = "coefficient"
    estimates: List[Estimate] = field(default_factory=list)
    #: Cases the model actually saw, after dropping rows with missing values.
    n_cases: int = 0
    #: Cases the matrix had before that, so the loss is visible.
    n_cases_before: int = 0
    #: Cross-validated score, on the metric named in `score_name`.
    score: Optional[float] = None
    score_name: str = ""
    #: Whatever the method chose for itself, e.g. the lasso penalty.
    chosen: Dict[str, Any] = field(default_factory=dict)
    seed: int = 0
    #: Set only by the decision tree: its splits as readable text. The rules
    #: are the point of that method — a forest predicts better and explains
    #: nothing — so they are a field rather than a line buried in the notes.
    rules: Optional[str] = None
    #: Set only by double lasso: the effect estimate with its interval. A
    #: declared field rather than an attribute bolted on afterwards, so a
    #: renderer can ask `result.effect is not None` and know whether it is
    #: looking at an inferential result — and so that nothing else can quietly
    #: acquire one.
    effect: Optional[Any] = None
    #: Caveats from the design matrix, plus any this fit added.
    notes: List[str] = field(default_factory=list)
    refusal: str = ""

    @property
    def usable(self) -> bool:
        return not self.refusal

    def frame(self) -> pd.DataFrame:
        """The estimates as a table, largest first, ready to export."""
        if not self.estimates:
            return pd.DataFrame(columns=["term", self.kind, "dropped"])
        rows = [{"term": e.name, self.kind: e.value, "dropped": e.dropped}
                for e in self.estimates]
        out = pd.DataFrame(rows)
        return out.reindex(out[self.kind].abs().sort_values(ascending=False).index)

    def describe(self) -> str:
        label = METHODS[self.method].label if self.method in METHODS else self.method
        score = "" if self.score is None else f", {self.score_name} {self.score:.3f}"
        return (f"{label}: {self.outcome} on {len(self.estimates)} term(s), "
                f"{self.n_cases} case(s){score}")


def fit(matrix, request: ModelRequest) -> ModelResult:
    """Fit `request` against `matrix`, or refuse in a sentence.

    `matrix` is a `DesignMatrix`. Its caveats are carried into the result rather
    than left behind: a coefficient on a machine-coded variable has to say so
    wherever it is shown, and the front end should not have to remember to
    fetch them from somewhere else.
    """
    if not getattr(matrix, "usable", False):
        return ModelResult(method=request.method, outcome=request.outcome.first,
                           refusal=matrix.refusal or "There is no data to model.")

    frame = matrix.frame
    outcome = request.outcome.first
    levels = int(frame[outcome].nunique()) if outcome in frame.columns else None

    blocking = problems(request, list(frame.columns), n_cases=len(frame),
                        outcome_levels=levels)
    if not can_run(request, list(frame.columns), n_cases=len(frame),
                   outcome_levels=levels):
        return ModelResult(
            method=request.method, outcome=outcome,
            refusal=" ".join(blocking) or "This model cannot be fitted as specified.")

    if request.method == "double_lasso":
        from analysis.double_lasso import estimate_effect

        return estimate_effect(matrix, request)

    terms = request.right_hand_side()
    y, X, kept, n_before = _prepare(frame, outcome, terms)
    required = METHODS[request.method].required_cases(len(terms))
    if len(y) < required:
        return ModelResult(
            method=request.method, outcome=outcome,
            n_cases=len(y), n_cases_before=n_before,
            refusal=(
                f"{len(y)} case(s) are complete on every variable in this model, "
                f"below the {required} this method needs. "
                "Missing descriptor values drop a whole case; removing the "
                "sparsest variable usually recovers most of them."))

    classify = levels is not None and levels <= BINARY_LEVELS
    notes = list(matrix.caveats())
    if n_before - len(y):
        notes.append(
            f"{n_before - len(y)} case(s) were dropped for missing values on "
            "one or more variables in this model. Cases are dropped whole, so a "
            "single sparse descriptor can cost a lot of them.")
    if levels is not None and BINARY_LEVELS < levels <= 5:
        notes.append(
            f"“{outcome}” has {levels} distinct values and is being modelled as "
            "a continuous number. If it is an ordered scale, the model is "
            "assuming its steps are equal.")

    fitter = _FITTERS[request.method]
    result = fitter(y, X, kept, request=request, classify=classify)
    return ModelResult(
        rules=result.get("rules"),
        method=request.method, outcome=outcome, kind=result["kind"],
        estimates=result["estimates"], n_cases=len(y), n_cases_before=n_before,
        score=result.get("score"), score_name=result.get("score_name", ""),
        chosen=result.get("chosen", {}), seed=request.seed,
        notes=notes + result.get("notes", []))


# ── preparation ──────────────────────────────────────────────────────────────

def _prepare(frame: pd.DataFrame, outcome: str,
             terms: Sequence[str]) -> Tuple[np.ndarray, np.ndarray, List[str], int]:
    """Complete cases only, as a float matrix.

    Listwise deletion, and the count of what it cost is returned so the caller
    can say so. Imputing would be the alternative and is worse here: a missing
    descriptor in a survey is usually missing for a reason connected to the
    respondent, and filling it in would invent the very thing the model is
    being asked about.
    """
    columns = [outcome] + [t for t in terms if t in frame.columns]
    subset = frame[columns].apply(pd.to_numeric, errors="coerce")
    n_before = len(subset)
    subset = subset.dropna()

    y = subset[outcome].to_numpy(dtype=float)
    kept = [c for c in columns[1:]]
    X = subset[kept].to_numpy(dtype=float) if kept else np.empty((len(y), 0))
    return y, X, kept, n_before


def _logistic_penalty(penalty: Optional[str]) -> Dict[str, Any]:
    """`LogisticRegression` penalty arguments, for every supported sklearn.

    `penalty=` was deprecated in scikit-learn 1.8 and is **removed in 1.10**,
    replaced by `l1_ratio` and `C`. The project pins `scikit-learn>=1.3,<2.0`
    (and `requirements-compat.txt` allows `>=1.0`), so 1.10 is already inside
    the permitted range: writing either spelling alone would break an install
    the requirements explicitly allow. The old one raises on new sklearn, the
    new one is unknown to old sklearn, so the version decides.

    Caught by a `FutureWarning` in the test output rather than by a failure —
    the suite was green and the code was already scheduled to break.
    """
    import sklearn

    parts = []
    for piece in str(sklearn.__version__).split(".")[:2]:
        digits = "".join(c for c in piece if c.isdigit())
        parts.append(int(digits) if digits else 0)
    modern = tuple(parts) >= (1, 8)

    if not modern:
        if penalty in ("l1", "elasticnet"):
            return {"penalty": penalty, "solver": "saga",
                    **({"l1_ratio": 0.5} if penalty == "elasticnet" else {})}
        return {"penalty": "l2" if penalty == "l2" else None}

    if penalty == "l1":
        return {"l1_ratio": 1.0, "solver": "saga"}
    if penalty == "elasticnet":
        return {"l1_ratio": 0.5, "solver": "saga"}
    if penalty == "l2":
        return {"l1_ratio": 0.0}
    return {"C": np.inf}


def _standardised(X: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """Centre and scale, returning the scale so coefficients can come back.

    A penalty is scale-dependent: without this, a code (0/1) and a GPA (0–4)
    are penalised differently for no reason but their units, and the lasso's
    selection would partly reflect measurement scale.
    """
    scale = X.std(axis=0, ddof=0)
    scale[scale == 0] = 1.0
    return (X - X.mean(axis=0)) / scale, scale


# ── the fitters ──────────────────────────────────────────────────────────────

def _fit_linear(y, X, names, *, request: ModelRequest, classify: bool,
                penalty: Optional[str] = None):
    """OLS, ridge, lasso and elastic net — one path, four penalties.

    Coefficients are reported on the original scale, because a coefficient in
    standard deviations is not the number a researcher wants to put in a table.
    """
    from sklearn.linear_model import (
        ElasticNetCV, LassoCV, LinearRegression, LogisticRegression, RidgeCV)
    from sklearn.model_selection import KFold, StratifiedKFold, cross_val_score

    Xs, scale = _standardised(X)
    folds = max(2, min(request.folds, len(y) // 5 or 2))
    splitter = (StratifiedKFold(folds, shuffle=True, random_state=request.seed)
                if classify
                else KFold(folds, shuffle=True, random_state=request.seed))
    chosen: Dict[str, Any] = {}

    if classify:
        model = LogisticRegression(max_iter=5000, random_state=request.seed,
                                   **_logistic_penalty(penalty))
        model.fit(Xs, y)
        raw = model.coef_.ravel()
        score_name = "accuracy (CV)"
    else:
        if penalty == "l1":
            model = LassoCV(cv=splitter, random_state=request.seed, max_iter=20000)
        elif penalty == "l2":
            model = RidgeCV(alphas=np.logspace(-3, 3, 25))
        elif penalty == "elasticnet":
            model = ElasticNetCV(cv=splitter, random_state=request.seed,
                                 l1_ratio=[0.1, 0.5, 0.9], max_iter=20000)
        else:
            model = LinearRegression()
        model.fit(Xs, y)
        raw = np.asarray(model.coef_).ravel()
        score_name = "R² (CV)"
        if hasattr(model, "alpha_"):
            chosen["penalty"] = float(model.alpha_)

    try:
        score = float(cross_val_score(model, Xs, y, cv=splitter).mean())
    except Exception:                                   # pragma: no cover
        score = None

    coefficients = raw / scale
    return {
        "kind": "coefficient",
        "estimates": [Estimate(name, float(value), bool(value == 0))
                      for name, value in zip(names, coefficients)],
        "score": score, "score_name": score_name, "chosen": chosen,
    }


#: How deep a tree may go before it stops being readable. Four levels is
#: sixteen leaves, which is about as much as fits in a paragraph of a paper; the
#: point of this method is the rules, and a tree nobody reads has no advantage
#: over a forest that predicts better.
_TREE_DEPTH = 4

#: A leaf standing on fewer cases than this is a story about individuals.
_TREE_MIN_LEAF = 10

#: Pruning penalties to cross-validate over. The path can be long on a wide
#: matrix and each candidate costs a full CV, so it is bounded.
_MAX_PRUNING_CANDIDATES = 20


def _fit_tree(y, X, names, *, request: ModelRequest, classify: bool):
    """One shallow decision tree, and its splits as text.

    The only method here that explains itself. A forest predicts better and can
    say no more than "this column mattered"; a tree says *how* — which is the
    difference between a variable-importance chart and a sentence a researcher
    can put in a paper.

    Constrained on purpose. Depth and leaf size are capped rather than tuned,
    because an unconstrained tree on 200 cases memorises them and produces rules
    that are true of nobody but the sample.
    """
    from sklearn.model_selection import KFold, StratifiedKFold, cross_val_score
    from sklearn.tree import DecisionTreeClassifier, DecisionTreeRegressor, export_text

    maker = DecisionTreeClassifier if classify else DecisionTreeRegressor
    model = _pruned_tree(maker, X, y, request=request, classify=classify)

    folds = max(2, min(request.folds, len(y) // 5 or 2))
    splitter = (StratifiedKFold(folds, shuffle=True, random_state=request.seed)
                if classify
                else KFold(folds, shuffle=True, random_state=request.seed))
    try:
        score = float(cross_val_score(model, X, y, cv=splitter).mean())
    except Exception:                                   # pragma: no cover
        score = None

    return {
        "kind": "importance",
        "estimates": [Estimate(name, float(value))
                      for name, value in zip(names, model.feature_importances_)],
        "score": score,
        "score_name": "accuracy (CV)" if classify else "R² (CV)",
        "rules": export_text(model, feature_names=list(names)),
        "chosen": {"pruning_alpha": float(model.ccp_alpha),
                   "depth": int(model.get_depth()),
                   "leaves": int(model.get_n_leaves())},
        "notes": [
            f"The tree is capped at depth {_TREE_DEPTH} with at least "
            f"{_TREE_MIN_LEAF} cases per leaf, and then pruned back by "
            "cross-validation. Uncapped, it would memorise this sample and "
            "produce rules true of nobody else; unpruned, it would spend "
            "depth on splits that lead to the same answer either way.",
            "A single tree is unstable: change a few cases and the splits can "
            "change entirely. Read the rules as one readable account of the "
            "data, not as the account.",
            "The importances beside the rules are the tree's own, which favour "
            "columns it happened to split on early.",
        ],
    }


def _pruned_tree(maker, X, y, *, request: ModelRequest, classify: bool):
    """A tree grown to the caps, then pruned back to the size the data supports.

    Without this the tree spends its whole depth budget whether or not the
    splits change the answer: on a real fixture it split on GPA four times under
    one branch and predicted the same class at every leaf. Those rules are not
    wrong, they are *noise formatted as an explanation*, and this method exists
    to be read.

    Cost-complexity pruning with the penalty chosen by cross-validation, which
    is the principled version of "make it smaller": `ccp_alpha` trades leaves
    against fit, and the candidates come from the tree's own pruning path rather
    than from a guess.
    """
    from sklearn.model_selection import KFold, StratifiedKFold, cross_val_score

    base = maker(max_depth=_TREE_DEPTH, min_samples_leaf=_TREE_MIN_LEAF,
                 random_state=request.seed)
    base.fit(X, y)

    path = base.cost_complexity_pruning_path(X, y)
    alphas = [a for a in dict.fromkeys(path.ccp_alphas) if a >= 0]
    if len(alphas) < 2:
        return base
    # The largest alpha prunes to a single leaf, which predicts nothing.
    alphas = alphas[:-1][:_MAX_PRUNING_CANDIDATES]

    folds = max(2, min(request.folds, len(y) // 5 or 2))
    splitter = (StratifiedKFold(folds, shuffle=True, random_state=request.seed)
                if classify
                else KFold(folds, shuffle=True, random_state=request.seed))

    # Descending: the strongest pruning is tried first, so the `>` below keeps
    # the SMALLEST tree among ties. Ascending, the first best encountered is the
    # largest tree, and since redundant splits cost no accuracy the pruning
    # would never fire at all — which is exactly what it did on first run,
    # against a comment claiming the opposite.
    best, best_score = base, float("-inf")
    for alpha in sorted(alphas, reverse=True):
        candidate = maker(max_depth=_TREE_DEPTH, min_samples_leaf=_TREE_MIN_LEAF,
                          ccp_alpha=float(alpha), random_state=request.seed)
        try:
            score = float(cross_val_score(candidate, X, y, cv=splitter).mean())
        except Exception:                               # pragma: no cover
            continue
        # `>` not `>=`: with the descending order above, a tie is won by the
        # smaller tree, which is the readable one.
        if score > best_score:
            best, best_score = candidate, score
    best.fit(X, y)
    return best


def _fit_forest(y, X, names, *, request: ModelRequest, classify: bool,
                boosted: bool = False, extra: bool = False, xgb: bool = False):
    """Random forest, gradient boosting or XGBoost, reported by permutation importance.

    Not the built-in `feature_importances_`: impurity importance is biased
    toward high-cardinality columns, which in a matrix mixing 0/1 codes with a
    continuous GPA means it systematically favours the GPA. Permutation
    importance is measured on held-out predictions and does not have that
    problem.
    """
    from sklearn.ensemble import (
        ExtraTreesClassifier, ExtraTreesRegressor,
        GradientBoostingClassifier, GradientBoostingRegressor,
        RandomForestClassifier, RandomForestRegressor)
    from sklearn.inspection import permutation_importance
    from sklearn.model_selection import KFold, StratifiedKFold, cross_val_score, train_test_split

    extra_notes: List[str] = []
    if xgb:
        import xgboost

        # One thread and a fixed seed: with several threads the sums are added in a different
        # order from run to run and the last digits move. Shallow trees and a small learning rate
        # keep it from fitting the training cases too closely on the project sizes seen here.
        model = (xgboost.XGBClassifier if classify else xgboost.XGBRegressor)(
            n_estimators=150, max_depth=3, learning_rate=0.1, subsample=0.8, colsample_bytree=0.8,
            random_state=request.seed, n_jobs=1, tree_method="hist", verbosity=0)
        if classify:
            y = y.astype(int)
        extra_notes.append(
            f"Fitted with XGBoost {xgboost.__version__}, one thread and seed {request.seed}, so the "
            "same project and the same seed give the same numbers.")
    elif boosted:
        # The exact implementation, not HistGradientBoosting. Histogram binning
        # is what makes the Hist variants fast above roughly ten thousand rows
        # and buys nothing at the sizes this program sees, where its default
        # minimum leaf size would instead start refusing to split.
        model = (GradientBoostingClassifier if classify else GradientBoostingRegressor)(
            random_state=request.seed)
    elif extra:
        model = (ExtraTreesClassifier if classify else ExtraTreesRegressor)(
            n_estimators=FOREST_TREES, random_state=request.seed, n_jobs=1)
    else:
        model = (RandomForestClassifier if classify else RandomForestRegressor)(
            n_estimators=FOREST_TREES, random_state=request.seed, n_jobs=1)

    X_fit, X_test, y_fit, y_test = train_test_split(
        X, y, test_size=0.25, random_state=request.seed,
        stratify=y if classify and min(np.bincount(y.astype(int))) > 1 else None)
    model.fit(X_fit, y_fit)

    importance = permutation_importance(
        model, X_test, y_test, n_repeats=PERMUTATION_REPEATS,
        random_state=request.seed)

    folds = max(2, min(request.folds, len(y) // 5 or 2))
    splitter = (StratifiedKFold(folds, shuffle=True, random_state=request.seed)
                if classify
                else KFold(folds, shuffle=True, random_state=request.seed))
    try:
        score = float(cross_val_score(model, X, y, cv=splitter).mean())
    except Exception:                                   # pragma: no cover
        score = None

    return {
        "kind": "importance",
        "estimates": [Estimate(name, float(value))
                      for name, value in zip(names, importance.importances_mean)],
        "score": score,
        "score_name": "accuracy (CV)" if classify else "R² (CV)",
        "notes": [
            "These are permutation importances, not coefficients: each is how "
            "much worse the model predicted when that column was shuffled. An "
            "importance has no direction and no units — it cannot tell you "
            "whether the code makes the outcome more or less likely.",
            "Measured on a held-out quarter of the cases, so on a small project "
            "the ranking is less stable than it looks.",
        ] + extra_notes,
    }


def _fit_sgd(y, X, names, *, request: ModelRequest, classify: bool):
    """A linear model fitted by stochastic gradient descent.

    A *fitting method*, not a model family — the distinction the plan makes in
    §1. Useful when the design matrix is wide and sparse, which a
    codes-as-columns matrix genuinely is.
    """
    from sklearn.linear_model import SGDClassifier, SGDRegressor
    from sklearn.model_selection import KFold, StratifiedKFold, cross_val_score

    Xs, scale = _standardised(X)
    model = (SGDClassifier(random_state=request.seed, max_iter=5000, tol=1e-4)
             if classify else
             SGDRegressor(random_state=request.seed, max_iter=5000, tol=1e-4))
    model.fit(Xs, y)

    folds = max(2, min(request.folds, len(y) // 5 or 2))
    splitter = (StratifiedKFold(folds, shuffle=True, random_state=request.seed)
                if classify
                else KFold(folds, shuffle=True, random_state=request.seed))
    try:
        score = float(cross_val_score(model, Xs, y, cv=splitter).mean())
    except Exception:                                   # pragma: no cover
        score = None

    coefficients = np.asarray(model.coef_).ravel() / scale
    return {
        "kind": "coefficient",
        "estimates": [Estimate(name, float(value))
                      for name, value in zip(names, coefficients)],
        "score": score,
        "score_name": "accuracy (CV)" if classify else "R² (CV)",
        "notes": ["Fitted by stochastic gradient descent, which is a way of "
                  "fitting a linear model rather than a different kind of "
                  "model. Compare it against plain regression, not against a "
                  "forest."],
    }


_FITTERS = {
    "ols": lambda *a, **k: _fit_linear(*a, penalty=None, **k),
    "lasso": lambda *a, **k: _fit_linear(*a, penalty="l1", **k),
    "ridge": lambda *a, **k: _fit_linear(*a, penalty="l2", **k),
    "elastic_net": lambda *a, **k: _fit_linear(*a, penalty="elasticnet", **k),
    "decision_tree": _fit_tree,
    "extra_trees": lambda *a, **k: _fit_forest(*a, extra=True, **k),
    "random_forest": lambda *a, **k: _fit_forest(*a, boosted=False, **k),
    "gradient_boosting": lambda *a, **k: _fit_forest(*a, boosted=True, **k),
    "xgboost": lambda *a, **k: _fit_forest(*a, xgb=True, **k),
    "sgd_linear": _fit_sgd,
}
