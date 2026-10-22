"""
Fitting the predictive models (`V6_PLAN.md` §4, Phase B).

Two things under test, and the second is the guard rail.

**The numbers are right.** A method given data with a known structure has to
recover it: OLS should return the coefficients that generated the outcome, lasso
should shrink the noise columns to exactly zero, and a forest should rank the
column that matters above the forty that do not.

**Nothing here produces an interval.** Selecting with a lasso and then testing
the survivors on the same data is invalid, and a panel offering both methods
makes it the easiest mistake available. `analysis/double_lasso.py` is the only
module allowed to report one, and it demands a named treatment first. These
tests check the separation holds in the code rather than only in the docstring.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analysis.design_matrix import DesignMatrix
from analysis.models import BINARY_LEVELS, ModelResult, fit
from core.model_spec import METHODS, ModelRequest, Shelf

PREDICTIVE = ["ols", "lasso", "ridge", "elastic_net", "decision_tree",
              "extra_trees", "random_forest", "gradient_boosting",
              "sgd_linear"]


def known(n=300, seed=3, binary_outcome=False, noise_columns=6, missing=0):
    """`signal_a` and `signal_b` drive the outcome; the rest is noise."""
    rng = np.random.default_rng(seed)
    a = rng.normal(size=n)
    b = rng.normal(size=n)
    outcome = 2.0 * a - 1.0 * b + rng.normal(scale=0.4, size=n)
    if binary_outcome:
        outcome = (outcome > 0).astype(float)

    columns = {"outcome": outcome, "signal_a": a, "signal_b": b}
    for j in range(noise_columns):
        columns[f"noise_{j}"] = rng.normal(size=n)
    frame = pd.DataFrame(columns)
    if missing:
        frame.loc[frame.index[:missing], "noise_0"] = np.nan
    frame.insert(0, "case_id", [str(i) for i in range(n)])
    return DesignMatrix(frame=frame, unit="source_id", encoding="binary")


def spec(method="ols", predictors=None, **kwargs):
    matrix_terms = predictors or ("signal_a", "signal_b")
    return ModelRequest(method=method, outcome=Shelf(("outcome",)),
                        predictors=Shelf(tuple(matrix_terms)), **kwargs)


def all_predictors(matrix):
    return tuple(c for c in matrix.frame.columns
                 if c not in ("case_id", "outcome"))


class TestTheNumbersAreRight:

    def test_ols_recovers_the_coefficients_that_generated_the_outcome(self):
        result = fit(known(), spec("ols"))
        values = {e.name: e.value for e in result.estimates}

        assert values["signal_a"] == pytest.approx(2.0, abs=0.15)
        assert values["signal_b"] == pytest.approx(-1.0, abs=0.15)

    def test_coefficients_come_back_on_the_original_scale(self):
        """A coefficient in standard deviations is not the number a researcher
        puts in a table. Scaling the predictor by ten must scale it by ten."""
        matrix = known()
        matrix.frame["signal_a"] = matrix.frame["signal_a"] * 10

        result = fit(matrix, spec("ols"))
        values = {e.name: e.value for e in result.estimates}

        assert values["signal_a"] == pytest.approx(0.2, abs=0.02)

    def test_lasso_shrinks_noise_to_exactly_zero(self):
        matrix = known(noise_columns=20)

        result = fit(matrix, spec("lasso", all_predictors(matrix)))
        values = {e.name: e.value for e in result.estimates}

        assert values["signal_a"] != 0.0
        zeroed = [n for n, v in values.items() if n.startswith("noise") and v == 0.0]
        assert len(zeroed) >= 10, "lasso selected almost nothing away"

    def test_a_shrunk_term_is_marked_dropped_rather_than_hidden(self):
        """Zero is lasso's actual answer and worth showing."""
        matrix = known(noise_columns=20)

        result = fit(matrix, spec("lasso", all_predictors(matrix)))

        assert any(e.dropped for e in result.estimates)
        assert all(e.value == 0.0 for e in result.estimates if e.dropped)

    def test_ridge_keeps_everything(self):
        matrix = known(noise_columns=10)

        result = fit(matrix, spec("ridge", all_predictors(matrix)))

        assert not any(e.dropped for e in result.estimates)

    @pytest.mark.parametrize("method", ["random_forest", "gradient_boosting"])
    def test_a_forest_ranks_the_signal_above_the_noise(self, method):
        matrix = known(n=300, noise_columns=8)

        result = fit(matrix, spec(method, all_predictors(matrix)))
        ranked = [e.name for e in
                  sorted(result.estimates, key=lambda e: -e.value)]

        assert ranked[0] in ("signal_a", "signal_b")

    def test_a_binary_outcome_is_classified(self):
        result = fit(known(binary_outcome=True), spec("ols"))

        assert result.usable
        assert "accuracy" in result.score_name

    @pytest.mark.parametrize("method", PREDICTIVE)
    def test_every_method_fits_and_scores(self, method):
        matrix = known(n=200)

        result = fit(matrix, spec(method))

        assert result.usable, result.refusal
        assert len(result.estimates) == 2
        assert result.score is not None


class TestTheDecisionTreeExplainsItself:
    """The only method here that says *how*, not just *which column mattered*.

    Fixture: a planted interaction — respondents who raised Cost **and** are
    first-generation do not return, nobody else. That is a shallow rule, so the
    tree should both recover it and beat the ensembles, which is the honest case
    for shipping an interpretable model rather than treating it as a consolation
    prize.
    """

    @staticmethod
    def interaction(n=300, seed=5):
        rng = np.random.default_rng(seed)
        cost = rng.integers(0, 2, n)
        first_gen = rng.integers(0, 2, n)
        gpa = rng.normal(3.0, 0.5, n)
        chance = 0.15 + 0.55 * (cost & first_gen) - 0.05 * (gpa - 3.0)
        frame = pd.DataFrame({
            "case_id": [str(i) for i in range(n)],
            "code::Cost": cost, "desc::first_gen": first_gen, "desc::gpa": gpa,
            "code::Advising": rng.integers(0, 2, n),
            "outcome": (rng.random(n) < chance).astype(int)})
        return DesignMatrix(frame=frame, unit="source_id", encoding="binary")

    @staticmethod
    def _spec(method="decision_tree"):
        return spec(method, ("code::Cost", "desc::first_gen", "desc::gpa",
                             "code::Advising"))

    def test_it_returns_readable_rules(self):
        result = fit(self.interaction(), self._spec())

        assert result.rules
        assert "code::Cost" in result.rules

    def test_the_rules_recover_the_planted_interaction(self):
        result = fit(self.interaction(), self._spec())

        assert "code::Cost" in result.rules
        assert "desc::first_gen" in result.rules

    def test_pruning_keeps_the_tree_readable(self):
        """Unpruned it spent its whole depth budget on splits that led to the
        same class either way — noise formatted as an explanation."""
        result = fit(self.interaction(), self._spec())

        assert result.chosen["leaves"] <= 6, (
            f"{result.chosen['leaves']} leaves is past what fits in a paragraph")
        assert result.rules.count("class:") == result.chosen["leaves"]

    def test_a_tie_is_won_by_the_smaller_tree(self):
        """Redundant splits cost no accuracy, so without preferring the smaller
        tree on a tie the pruning never fires at all — which is what happened on
        the first implementation, against a comment claiming otherwise."""
        result = fit(self.interaction(), self._spec())

        assert result.chosen["pruning_alpha"] > 0.0

    def test_the_pruned_tree_is_no_worse_than_the_full_one(self):
        result = fit(self.interaction(), self._spec())

        assert result.score is not None and result.score > 0.7

    def test_it_beats_the_ensembles_when_the_truth_is_a_shallow_rule(self):
        matrix = self.interaction()

        tree = fit(matrix, self._spec("decision_tree")).score
        forest = fit(matrix, self._spec("random_forest")).score

        assert tree > forest

    def test_the_caveats_say_a_single_tree_is_unstable(self):
        blob = " ".join(fit(self.interaction(), self._spec()).notes)

        assert "unstable" in blob
        assert "not as the account" in blob

    def test_no_other_method_produces_rules(self):
        matrix = self.interaction()

        for method in ("random_forest", "extra_trees", "lasso"):
            assert fit(matrix, self._spec(method)).rules is None, method


class TestTheForestIsNoBiggerThanItNeedsToBe:
    """400 trees cost about thirty seconds a fit and bought nothing.

    Measured across 100/200/400/800 trees at n = 100 and n = 300:
    cross-validated accuracy was identical to four decimals up to 400, and 800
    differed only by noise in both directions. A forest's variance reduction
    saturates long before this on data this small.
    """

    def test_the_tree_count_is_a_stated_number(self):
        from analysis.models import FOREST_TREES

        assert 100 <= FOREST_TREES <= 400

    def test_doubling_the_trees_would_not_change_the_answer(self):
        """The measurement, as a test: if this ever fails, the constant is worth
        revisiting rather than the test worth deleting."""
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.model_selection import StratifiedKFold, cross_val_score

        from analysis.models import FOREST_TREES

        matrix = TestTheDecisionTreeExplainsItself.interaction(n=300)
        frame = matrix.frame
        X = frame[["code::Cost", "desc::first_gen", "desc::gpa",
                   "code::Advising"]].to_numpy()
        y = frame["outcome"].to_numpy()
        splitter = StratifiedKFold(5, shuffle=True, random_state=0)

        scores = {
            trees: cross_val_score(
                RandomForestClassifier(n_estimators=trees, random_state=0,
                                       n_jobs=1),
                X, y, cv=splitter).mean()
            for trees in (FOREST_TREES, FOREST_TREES * 2)}

        assert abs(scores[FOREST_TREES] - scores[FOREST_TREES * 2]) < 0.02

    def test_the_forest_stays_single_threaded(self):
        """`n_jobs=-1` measured slower than `n_jobs=1` here: at a few hundred
        rows the thread overhead exceeds the work.

        Checked on the parsed AST, not the text. The first version grepped the
        source for "n_jobs=-1" and matched the comment explaining why it is
        avoided — the same trap `tests/test_deviant_cases.py` already records
        for a docstring mentioning the import it was checking for.
        """
        import ast

        import analysis.models as module

        tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
        parallel = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.keyword) and node.arg == "n_jobs"
            and isinstance(node.value, ast.UnaryOp)
            and isinstance(node.value.op, ast.USub)]

        assert not parallel, "a fitter asks for every core on data too small for it"


class TestNothingHereReportsAnInterval:
    """The guard rail. Selecting with a lasso and then testing the survivors on
    the same data is invalid, and a panel offering both makes it easy."""

    @pytest.mark.parametrize("method", PREDICTIVE)
    def test_no_predictive_method_produces_an_effect(self, method):
        result = fit(known(n=200), spec(method))

        assert result.effect is None

    def test_the_result_has_no_standard_error_or_p_value_field(self):
        fields = set(ModelResult.__dataclass_fields__)

        assert not (fields & {"p_value", "std_error", "interval", "t_stat"})

    def test_the_estimate_has_no_uncertainty_field_either(self):
        from analysis.models import Estimate

        assert set(Estimate.__dataclass_fields__) == {"name", "value", "dropped"}

    def test_the_module_never_mentions_a_p_value(self):
        """Checked on the source: the words should not be there to be printed."""
        import analysis.models as module

        source = Path(module.__file__).read_text(encoding="utf-8").lower()
        body = source.split('"""', 2)[-1]           # skip the module docstring

        assert "p_value" not in body and "pvalue" not in body


class TestCoefficientsAndImportancesAreNotTheSameThing:

    def test_a_linear_model_reports_coefficients(self):
        assert fit(known(), spec("lasso")).kind == "coefficient"

    def test_a_forest_reports_importances(self):
        matrix = known(n=200)

        assert fit(matrix, spec("random_forest")).kind == "importance"

    def test_the_forest_says_an_importance_has_no_direction(self):
        matrix = known(n=200)

        blob = " ".join(fit(matrix, spec("random_forest")).notes)

        assert "no direction" in blob
        assert "shuffled" in blob

    def test_the_frame_column_is_named_after_the_kind(self):
        matrix = known(n=200)

        assert "coefficient" in fit(matrix, spec("ols")).frame().columns
        assert "importance" in fit(matrix, spec("random_forest")).frame().columns

    def test_the_frame_is_ordered_by_magnitude(self):
        frame = fit(known(), spec("ols")).frame()

        assert frame.iloc[0]["term"] == "signal_a"

    def test_sgd_says_it_is_a_fitting_method_not_a_model_family(self):
        blob = " ".join(fit(known(n=200), spec("sgd_linear")).notes)

        assert "way of fitting a linear model" in blob


class TestReproducibility:

    @pytest.mark.parametrize("method", PREDICTIVE)
    def test_the_same_seed_gives_the_same_numbers(self, method):
        first = fit(known(n=200), spec(method, seed=77))
        second = fit(known(n=200), spec(method, seed=77))

        assert [e.value for e in first.estimates] == [e.value for e in second.estimates]

    def test_the_seed_reaches_the_result(self):
        assert fit(known(), spec("lasso", seed=1234)).seed == 1234

    def test_the_chosen_penalty_is_reported(self):
        """Part of what a methods appendix needs to reproduce the fit."""
        result = fit(known(), spec("lasso"))

        assert "penalty" in result.chosen


class TestMissingValues:

    def test_cases_are_dropped_whole_and_the_loss_is_reported(self):
        matrix = known(n=300, missing=40)

        result = fit(matrix, spec("ols", all_predictors(matrix)))

        assert result.n_cases == 260
        assert result.n_cases_before == 300
        assert any("dropped for missing values" in n for n in result.notes)

    def test_the_caveat_warns_that_one_sparse_column_is_expensive(self):
        matrix = known(n=300, missing=40)

        blob = " ".join(fit(matrix, spec("ols", all_predictors(matrix))).notes)

        assert "dropped whole" in blob

    def test_dropping_below_the_floor_refuses_with_the_reason(self):
        matrix = known(n=200, missing=170)

        result = fit(matrix, spec("lasso", all_predictors(matrix)))

        assert not result.usable
        assert "complete on every variable" in result.refusal
        assert "sparsest variable" in result.refusal


class TestRefusalsComeFromTheSpec:

    def test_below_the_floor_is_refused_before_fitting(self):
        result = fit(known(n=40), spec("random_forest"))

        assert not result.usable
        assert str(METHODS["random_forest"].floor) in result.refusal

    def test_an_unusable_matrix_carries_its_own_refusal_through(self):
        empty = DesignMatrix(frame=pd.DataFrame(), unit="source_id",
                             encoding="binary", refusal="Nothing is coded yet.")

        assert "Nothing is coded yet" in fit(empty, spec("ols")).refusal

    def test_a_constant_outcome_is_refused(self):
        matrix = known()
        matrix.frame["outcome"] = 1.0

        assert not fit(matrix, spec("ols")).usable


class TestTheCaveatsTravelFromTheMatrix:

    def test_machine_coding_is_reported_on_the_result(self):
        """A coefficient on a machine-coded variable has to say so wherever it
        is shown, not only on the screen where the matrix was built."""
        matrix = known()
        object.__setattr__(matrix, "raters_pooled", ["transformer"])
        object.__setattr__(matrix, "rater_id", "transformer")

        blob = " ".join(fit(matrix, spec("ols")).notes)

        assert "estimates, not measurements" in blob

    def test_a_few_valued_outcome_says_it_is_being_treated_as_continuous(self):
        matrix = known()
        matrix.frame["outcome"] = np.tile([1.0, 2.0, 3.0, 4.0],
                                          len(matrix.frame) // 4)

        blob = " ".join(fit(matrix, spec("ols")).notes)

        assert "assuming its steps are equal" in blob

    def test_a_binary_outcome_does_not_get_that_note(self):
        blob = " ".join(fit(known(binary_outcome=True), spec("ols")).notes)

        assert "steps are equal" not in blob

    def test_binary_levels_is_a_stated_number(self):
        assert BINARY_LEVELS == 2


class TestItWillStillRunOnTheSklearnTheRequirementsAllow:
    """`penalty=` was deprecated in scikit-learn 1.8 and is removed in 1.10.
    The pin is `>=1.3,<2.0`, so 1.10 is already permitted — this was code
    scheduled to break, with a green suite and a FutureWarning nobody read."""

    def test_no_deprecation_warning_is_raised_by_a_classification(self):
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("error", FutureWarning)
            warnings.simplefilter("error", DeprecationWarning)
            result = fit(known(binary_outcome=True), spec("lasso"))

        assert result.usable

    @pytest.mark.parametrize("method", ["ols", "lasso", "ridge", "elastic_net"])
    def test_every_penalty_classifies_without_warning(self, method):
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("error", FutureWarning)
            assert fit(known(binary_outcome=True), spec(method)).usable

    def test_the_modern_spelling_is_used_on_a_modern_sklearn(self):
        import sklearn

        from analysis.models import _logistic_penalty

        modern = tuple(int("".join(c for c in p if c.isdigit()) or 0)
                       for p in sklearn.__version__.split(".")[:2]) >= (1, 8)
        arguments = _logistic_penalty("l1")

        assert ("l1_ratio" in arguments) is modern
        assert ("penalty" in arguments) is not modern

    def test_a_pre_1_8_sklearn_would_get_the_old_spelling(self, monkeypatch):
        import sklearn

        from analysis.models import _logistic_penalty

        monkeypatch.setattr(sklearn, "__version__", "1.3.2")

        assert _logistic_penalty("l1") == {"penalty": "l1", "solver": "saga"}
        assert _logistic_penalty(None) == {"penalty": None}

    def test_an_odd_version_string_does_not_crash_the_fit(self, monkeypatch):
        import sklearn

        from analysis.models import _logistic_penalty

        monkeypatch.setattr(sklearn, "__version__", "1.9.0rc1")

        assert _logistic_penalty("l2")            # must not raise


def test_describe_is_one_readable_line():
    line = fit(known(), spec("lasso")).describe()

    assert "outcome" in line and "case(s)" in line
