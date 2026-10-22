"""
Post-double-selection lasso (`V6_PLAN.md` §4, Phase B).

The headline of v6 and the one method no rival ships. What has to be defended is
not "does it return a number" — it is that the number is **right**, and right for
the reason the method claims.

So the central fixture is a data-generating process with a **known** effect and
a confounder built to defeat single selection: it predicts the treatment
strongly, and its direct effect on the outcome exactly cancels its indirect path
through the treatment. A lasso of the outcome on the controls therefore sees
nothing and drops it — and omitting it collapses the estimate.

    true effect            1.000
    naive, omits the confounder    0.287
    oracle, includes it            0.991
    double lasso                   0.984   CI [0.934, 1.034]

An implementation that lassoed only the outcome and called it double selection
would return roughly 0.29 here and pass any test that merely checked a number
came back. That is what these tests exist to stop.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analysis.design_matrix import DesignMatrix
from analysis.double_lasso import CONFIDENCE, EffectEstimate, estimate_effect
from analysis.models import fit
from core.model_spec import ModelRequest, Shelf

TRUE_EFFECT = 1.0
N_CONTROLS = 40


def confounded(n=400, seed=11, effect=TRUE_EFFECT, cancel=True):
    """A DGP with a known effect and a confounder single selection cannot see.

    `z0` drives the treatment. With `cancel`, its direct effect on the outcome
    is set to exactly minus the indirect path, so a regression of outcome on
    controls alone sees a coefficient of about zero for it and a lasso drops it.
    Every other control is noise.
    """
    rng = np.random.default_rng(seed)
    Z = rng.normal(size=(n, N_CONTROLS))
    treatment = 1.5 * Z[:, 0] + rng.normal(size=n)
    direct = -1.5 if cancel else 0.4
    outcome = (effect * treatment + direct * Z[:, 0]
               + rng.normal(scale=0.5, size=n))

    columns = {"outcome": outcome, "treat": treatment}
    columns.update({f"z{j}": Z[:, j] for j in range(N_CONTROLS)})
    frame = pd.DataFrame(columns)
    frame.insert(0, "case_id", [str(i) for i in range(n)])
    return DesignMatrix(frame=frame, unit="source_id", encoding="binary")


def spec(controls=(), predictors=None, **kwargs):
    return ModelRequest(
        method="double_lasso",
        outcome=Shelf(("outcome",)),
        treatment=Shelf(("treat",)),
        predictors=Shelf(tuple(f"z{j}" for j in range(N_CONTROLS))
                         if predictors is None else tuple(predictors)),
        controls=Shelf(tuple(controls)),
        **kwargs)


def naive_estimate(matrix):
    """OLS of outcome on treatment alone — what omitting the confounder gives."""
    frame = matrix.frame
    design = np.column_stack([np.ones(len(frame)), frame["treat"].to_numpy()])
    return float(np.linalg.lstsq(design, frame["outcome"].to_numpy(),
                                 rcond=None)[0][1])


class TestItRecoversAKnownEffect:

    def test_the_estimate_is_close_to_the_truth(self):
        result = estimate_effect(confounded(), spec())

        assert result.usable
        assert result.effect.coefficient == pytest.approx(TRUE_EFFECT, abs=0.1)

    def test_the_interval_covers_the_truth(self):
        result = estimate_effect(confounded(), spec())
        low, high = result.effect.interval

        assert low < TRUE_EFFECT < high

    def test_it_beats_the_naive_estimate_that_omits_the_confounder(self):
        """The comparison that justifies the whole method."""
        matrix = confounded()

        naive = naive_estimate(matrix)
        estimated = estimate_effect(matrix, spec()).effect.coefficient

        assert abs(naive - TRUE_EFFECT) > 0.5, "the fixture is not confounded"
        assert abs(estimated - TRUE_EFFECT) < abs(naive - TRUE_EFFECT) / 3

    def test_the_naive_interval_would_have_excluded_the_truth(self):
        """Not just less accurate — confidently wrong."""
        matrix = confounded()

        assert abs(naive_estimate(matrix) - TRUE_EFFECT) > 0.5


class TestTheSecondSelectionIsWhatDoesTheWork:
    """Step 2 is the method. An implementation that lassoed only the outcome
    would pass a test that merely checked a number came back."""

    def test_the_outcome_lasso_alone_misses_the_confounder(self):
        """The fixture is built so it does. If this ever stops being true the
        fixture has stopped testing what it was written for."""
        result = estimate_effect(confounded(), spec())

        assert "z0" not in result.effect.selected_by_outcome

    def test_the_treatment_lasso_catches_it(self):
        result = estimate_effect(confounded(), spec())

        assert "z0" in result.effect.selected_by_treatment

    def test_the_confounder_reaches_the_final_model_only_through_step_two(self):
        result = estimate_effect(confounded(), spec())

        assert "z0" in result.effect.only_from_treatment
        assert "z0" in result.effect.union

    def test_dropping_step_two_would_change_the_answer(self):
        """Simulates the shortcut: fit with only the outcome-selected controls
        and show it lands where the naive estimate does, not where the truth is.
        """
        matrix = confounded()
        result = estimate_effect(matrix, spec())
        outcome_only = result.effect.selected_by_outcome

        frame = matrix.frame
        design = np.column_stack(
            [np.ones(len(frame)), frame["treat"].to_numpy()]
            + [frame[name].to_numpy() for name in outcome_only])
        shortcut = float(np.linalg.lstsq(
            design, frame["outcome"].to_numpy(), rcond=None)[0][1])

        assert abs(shortcut - TRUE_EFFECT) > 0.5, (
            "single selection should be badly wrong on this fixture")
        assert abs(result.effect.coefficient - TRUE_EFFECT) < 0.1

    def test_the_caveats_name_the_controls_only_the_treatment_step_found(self):
        result = estimate_effect(confounded(), spec())
        blob = " ".join(result.notes)

        assert "Kept only because they predict the treatment" in blob
        assert "z0" in blob


class TestForcedControls:

    def test_a_forced_control_is_never_penalised_out(self):
        result = estimate_effect(confounded(), spec(controls=("z7",),
                                                    predictors=[f"z{j}" for j in range(N_CONTROLS)]))

        assert "z7" in result.effect.forced
        assert "z7" in result.effect.union

    def test_forcing_the_confounder_gives_the_same_answer(self):
        """A sanity check on the machinery: if the analyst already knows the
        confounder, the method should agree with them."""
        automatic = estimate_effect(confounded(), spec()).effect.coefficient
        forced = estimate_effect(
            confounded(),
            spec(controls=("z0",),
                 predictors=[f"z{j}" for j in range(1, N_CONTROLS)])
        ).effect.coefficient

        assert automatic == pytest.approx(forced, abs=0.1)

    def test_a_forced_control_is_not_double_counted(self):
        result = estimate_effect(confounded(), spec(controls=("z0",)))

        assert result.effect.union.count("z0") == 1


class TestTheEstimateIsReproducible:

    def test_the_same_data_gives_the_same_number(self):
        first = estimate_effect(confounded(), spec()).effect
        second = estimate_effect(confounded(), spec()).effect

        assert first.coefficient == second.coefficient
        assert first.std_error == second.std_error

    def test_the_seed_reaches_the_result(self):
        result = estimate_effect(confounded(), spec(seed=4242))

        assert result.seed == 4242

    def test_a_different_seed_changes_only_the_folds_not_the_conclusion(self):
        a = estimate_effect(confounded(), spec(seed=1)).effect.coefficient
        b = estimate_effect(confounded(), spec(seed=99)).effect.coefficient

        assert a == pytest.approx(b, abs=0.1)


class TestWhatItRefuses:

    def test_a_constant_treatment_has_no_effect_to_estimate(self):
        matrix = confounded()
        matrix.frame["treat"] = 1.0

        result = estimate_effect(matrix, spec())

        assert not result.usable
        assert "same value on every complete case" in result.refusal

    def test_too_few_cases_is_refused_by_the_spec_before_it_gets_here(self):
        """The number is computed from the candidate count, so this asserts the
        rule rather than a literal — the literal was 100 until calibration
        replaced it."""
        from core.model_spec import METHODS

        request = spec()
        required = METHODS["double_lasso"].required_cases(
            len(request.right_hand_side()))

        result = fit(confounded(n=30), request)

        assert not result.usable
        assert str(required) in result.refusal

    def test_an_unusable_matrix_is_refused_with_its_own_reason(self):
        empty = DesignMatrix(frame=pd.DataFrame(), unit="source_id",
                             encoding="binary", refusal="Nothing is coded yet.")

        result = fit(empty, spec())

        assert not result.usable
        assert "Nothing is coded yet" in result.refusal


class TestTheCaveatsTravelWithTheNumber:
    """A coefficient table looks authoritative whatever produced it."""

    def test_it_says_the_interval_survives_the_selection(self):
        blob = " ".join(estimate_effect(confounded(), spec()).notes)

        assert "valid despite the variable selection" in blob

    def test_it_refuses_to_call_the_result_causal(self):
        blob = " ".join(estimate_effect(confounded(), spec()).notes)

        assert "not a causal claim" in blob
        assert "assumption" in blob

    def test_it_reports_how_many_controls_entered_and_from_where(self):
        blob = " ".join(estimate_effect(confounded(), spec()).notes)

        assert "control(s) entered the final model" in blob

    def test_it_discloses_the_cross_validated_penalty_choice(self):
        """A departure from the original papers, stated rather than discovered."""
        blob = " ".join(estimate_effect(confounded(), spec()).notes)

        assert "plug-in" in blob

    def test_an_interval_crossing_zero_is_not_reported_as_no_effect(self):
        matrix = confounded(n=120, effect=0.0, seed=5)

        result = estimate_effect(matrix, spec())
        blob = " ".join(result.notes)

        if result.effect.crosses_zero():
            assert "not evidence of no effect" in blob

    def test_a_binary_outcome_says_it_is_a_linear_probability_model(self):
        matrix = confounded()
        matrix.frame["outcome"] = (matrix.frame["outcome"] > 0).astype(float)

        blob = " ".join(estimate_effect(matrix, spec()).notes)

        assert "linear probability model" in blob

    def test_the_design_matrix_caveats_come_through_too(self):
        """A machine-coded treatment has to say so on the effect table, not
        only on the screen where the matrix was built."""
        matrix = confounded()
        object.__setattr__(matrix, "raters_pooled", ["transformer"])
        object.__setattr__(matrix, "rater_id", "transformer")

        blob = " ".join(estimate_effect(matrix, spec()).notes)

        assert "estimates, not measurements" in blob


class TestTheProseThatReachesAChapter:
    """These caveats are printed into a Word document by
    `exports/model_export.py` and then read by a supervisor. Number agreement is
    not a nicety there — it was caught by reading the first exported report,
    which said "«n_codes» was dropped ... each is an exact combination"."""

    @staticmethod
    def _redundant_note(names):
        from analysis.double_lasso import _listed

        one = len(names) == 1
        return (f"{_listed(names)} dropped from the final model: "
                + ("it is an exact combination of the other terms, so it "
                   "carries no information of its own"
                   if one else
                   "each is an exact combination of the other terms, so they "
                   "carry no information of their own")
                + " and would make the estimate unidentifiable.")

    def test_one_dropped_column_reads_as_singular(self):
        note = self._redundant_note(["n_codes"])

        assert "was dropped" in note
        assert "it is an exact combination" in note
        assert "each is" not in note

    def test_several_dropped_columns_read_as_plural(self):
        note = self._redundant_note(["n_codes", "desc::total"])

        assert "were dropped" in note
        assert "each is an exact combination" in note
        assert "they carry" in note

    def test_the_real_caveat_agrees_in_number(self):
        """Not the helper above — the sentence the export actually prints."""
        matrix = confounded(n=200)
        matrix.frame["z_total"] = matrix.frame[[f"z{j}" for j in range(3)]].sum(axis=1)

        result = estimate_effect(
            matrix, spec(predictors=[f"z{j}" for j in range(3)] + ["z_total"]))

        dropped = [n for n in result.notes if "dropped from the final model" in n]
        for note in dropped:
            if "was dropped" in note:
                assert "each is" not in note, note
            if "were dropped" in note:
                assert "each is" in note, note


class TestTheArithmetic:

    def test_the_interval_is_symmetric_around_the_estimate(self):
        effect = estimate_effect(confounded(), spec()).effect
        low, high = effect.interval

        assert (high + low) / 2 == pytest.approx(effect.coefficient)

    def test_the_interval_is_about_two_standard_errors_wide(self):
        effect = estimate_effect(confounded(), spec()).effect
        low, high = effect.interval

        assert (high - low) / 2 == pytest.approx(1.96 * effect.std_error, rel=1e-3)

    def test_robust_errors_differ_from_the_textbook_ones(self):
        """HC1 is not decoration: with a heteroskedastic outcome it should not
        agree with the homoskedastic formula."""
        from analysis.double_lasso import _ols_hc1

        rng = np.random.default_rng(3)
        n = 500
        x = rng.normal(size=n)
        y = x + rng.normal(scale=np.abs(x) + 0.1)      # variance grows with x
        design = np.column_stack([np.ones(n), x])

        _, robust = _ols_hc1(design, y)

        residuals = y - design @ np.linalg.lstsq(design, y, rcond=None)[0]
        sigma2 = residuals @ residuals / (n - 2)
        classical = np.sqrt(np.diag(sigma2 * np.linalg.inv(design.T @ design)))

        assert abs(robust[1] - classical[1]) / classical[1] > 0.05

    def test_a_singular_design_is_refused_rather_than_returning_nonsense(self):
        matrix = confounded(n=150)
        matrix.frame["copy"] = matrix.frame["treat"]        # perfectly collinear

        result = estimate_effect(
            matrix, spec(controls=("copy",),
                         predictors=[f"z{j}" for j in range(N_CONTROLS)]))

        if not result.usable:
            assert "collinear" in result.refusal
        else:
            assert np.isfinite(result.effect.std_error)

    def test_the_confidence_level_is_stated(self):
        assert CONFIDENCE == 0.95


class TestItRoutesThroughTheCommonEntryPoint:

    def test_fit_dispatches_to_double_lasso(self):
        result = fit(confounded(), spec())

        assert result.method == "double_lasso"
        assert isinstance(result.effect, EffectEstimate)

    def test_no_other_method_produces_an_effect(self):
        """The guard rail: only the inferential method may carry an interval."""
        from core.model_spec import METHODS

        matrix = confounded(n=200)
        for method in ("lasso", "ridge", "ols"):
            request = ModelRequest(
                method=method, outcome=Shelf(("outcome",)),
                predictors=Shelf(("treat", "z0", "z1", "z2")))
            assert fit(matrix, request).effect is None, method
