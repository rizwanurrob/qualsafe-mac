"""
The model spec — drag-and-drop shelves for a model (`V6_PLAN.md` §3, Phase A).

This module holds what the analyst chose and says what is wrong with it. It fits
nothing, so what is under test is the refusing, not the modelling.

Two things get most of the attention.

**Treatment is what turns prediction into inference.** The interface could offer
a *p*-value beside every lasso coefficient and nobody would immediately notice
it was invalid. Requiring a named treatment first makes the analyst state a
hypothesis before the program will give them an interval, which is what the
method demands anyway.

**The refusals are sentences, and they carry their number.** "n=34 < 100" is a
fact; "double lasso needs about 100 cases and this project has 34" is an answer
somebody can disagree with.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.model_spec import (
    COMFORTABLE_CASES_PER_PREDICTOR, METHODS, SHELVES, ModelRequest, Shelf,
    can_run, describe, problems, request_from_dict, request_to_dict)

COLUMNS = ["code::Cost", "code::Access", "code::Belonging", "desc::gpa",
           "desc::program=Business", "n_codes", "retention"]


def spec(method="ols", outcome=("retention",), treatment=(), predictors=(),
         controls=(), **kwargs):
    return ModelRequest(
        method=method,
        outcome=Shelf(tuple(outcome)),
        treatment=Shelf(tuple(treatment)),
        predictors=Shelf(tuple(predictors)),
        controls=Shelf(tuple(controls)),
        **kwargs)


def issues(request, n_cases=500, **kwargs):
    return problems(request, COLUMNS, n_cases=n_cases, **kwargs)


class TestTheShelves:

    def test_the_four_shelves_are_the_documented_ones(self):
        assert SHELVES == ("outcome", "treatment", "predictors", "controls")

    def test_a_valid_spec_has_nothing_wrong_with_it(self):
        assert issues(spec(predictors=("code::Cost", "desc::gpa"))) == []

    def test_an_outcome_is_required(self):
        found = issues(spec(outcome=(), predictors=("code::Cost",)))

        assert any("needs something to explain" in p for p in found)

    def test_only_one_outcome(self):
        found = issues(spec(outcome=("retention", "n_codes"),
                            predictors=("code::Cost",)))

        assert any("Outcome takes one field" in p for p in found)

    def test_predictors_are_required(self):
        found = issues(spec())

        assert any("nothing for the model to explain" in p for p in found)

    def test_the_right_hand_side_puts_treatment_first(self):
        request = spec(method="double_lasso", treatment=("code::Cost",),
                       predictors=("desc::gpa",), controls=("n_codes",))

        assert request.right_hand_side() == ["code::Cost", "desc::gpa", "n_codes"]

    def test_a_field_on_two_shelves_is_not_counted_twice(self):
        request = spec(predictors=("code::Cost",), controls=("code::Cost",))

        assert request.right_hand_side() == ["code::Cost"]


class TestTreatmentIsWhatTurnsPredictionIntoInference:
    """The design's one real opinion."""

    def test_double_lasso_without_a_treatment_is_refused(self):
        found = issues(spec(method="double_lasso",
                            predictors=("code::Cost", "desc::gpa")))

        assert any("Drop the variable you want a defensible number for"
                   in p for p in found)
        assert not can_run(spec(method="double_lasso",
                                predictors=("code::Cost",)), COLUMNS, n_cases=500)

    def test_double_lasso_with_a_treatment_runs(self):
        request = spec(method="double_lasso", treatment=("code::Cost",),
                       predictors=("desc::gpa", "n_codes"))

        assert issues(request) == []
        assert can_run(request, COLUMNS, n_cases=500)

    def test_a_treatment_on_a_predictive_method_is_flagged_and_redirected(self):
        """Silently ignoring it would leave the analyst thinking they had asked
        for an effect estimate."""
        found = issues(spec(method="lasso", treatment=("code::Cost",),
                            predictors=("desc::gpa",)))

        assert any("Switch to double lasso" in p for p in found)

    def test_only_one_treatment(self):
        found = issues(spec(method="double_lasso",
                            treatment=("code::Cost", "code::Access"),
                            predictors=("desc::gpa",)))

        assert any("Treatment takes one field" in p for p in found)

    def test_the_treatment_may_not_also_be_a_control(self):
        found = issues(spec(method="double_lasso", treatment=("code::Cost",),
                            controls=("code::Cost",), predictors=("desc::gpa",)))

        assert any("would make its effect uninterpretable" in p for p in found)

    def test_exactly_one_method_is_inferential(self):
        """If a second one appears, the p-value rule in V6_PLAN §6 needs
        revisiting rather than quietly extending."""
        inferential = [k for k, m in METHODS.items() if m.inferential]

        assert inferential == ["double_lasso"]


class TestExplainingAThingWithItself:

    def test_the_outcome_cannot_be_a_predictor(self):
        found = issues(spec(predictors=("retention", "code::Cost")))

        assert any("explains a thing with itself" in p for p in found)

    def test_the_outcome_cannot_be_the_treatment(self):
        found = issues(spec(method="double_lasso", treatment=("retention",),
                            predictors=("code::Cost",)))

        assert any("explains a thing with itself" in p for p in found)

    def test_a_constant_outcome_is_refused(self):
        found = issues(spec(predictors=("code::Cost",)), outcome_levels=1)

        assert any("nothing to explain" in p for p in found)


class TestFieldsThatAreNotThere:
    """A code dropped for having no variation must be caught here, not surface
    as a KeyError mid-fit."""

    def test_a_missing_predictor_is_named(self):
        found = issues(spec(predictors=("code::VeryRare",)))

        assert any("code::VeryRare" in p and "design matrix" in p for p in found)

    def test_a_missing_outcome_suggests_why(self):
        found = issues(spec(outcome=("code::Gone",), predictors=("code::Cost",)))

        assert any("too little variation" in p for p in found)

    def test_several_missing_fields_read_as_a_sentence(self):
        found = issues(spec(predictors=("code::A", "code::B")))

        assert any("and" in p and "are not in the design matrix" in p
                   for p in found)

    def test_an_unknown_method_is_the_only_thing_reported(self):
        found = issues(spec(method="deep_learning", predictors=("code::Cost",)))

        assert len(found) == 1
        assert "not a method this program knows" in found[0]


class TestSampleSize:

    def test_a_method_below_its_floor_is_refused_with_the_number(self):
        request = spec(method="double_lasso", treatment=("code::Cost",),
                       predictors=("desc::gpa",))
        required = METHODS["double_lasso"].required_cases(
            len(request.right_hand_side()))

        found = issues(request, n_cases=34)

        assert any(str(required) in p and "34" in p for p in found)

    def test_the_double_lasso_floor_grows_with_the_candidate_count(self):
        """Measured by `tools/simulate_project.py --calibrate`: with 8 candidate
        controls the interval reaches nominal coverage at n = 60, with 40 not
        until n ≈ 120. A flat floor was both too strict at small p and too lenient
        at large p, which is the dangerous direction."""
        method = METHODS["double_lasso"]

        assert method.required_cases(8) == 60
        assert method.required_cases(41) == 123
        assert method.required_cases(80) > method.required_cases(40)

    def test_a_method_with_no_growth_term_keeps_a_flat_floor(self):
        for key in ("ols", "lasso", "random_forest"):
            method = METHODS[key]
            assert method.required_cases(2) == method.required_cases(200) == method.floor

    def test_the_growth_is_explained_in_the_refusal(self):
        """Only when growth actually binds. With five candidates the rule gives
        max(60, 12.5) = 60, which is the flat floor and needs no explanation —
        the first version of this test asserted the sentence appeared there and
        was simply wrong about its own arithmetic."""
        wide = [f"code::C{i}" for i in range(30)] + ["retention"]
        request = ModelRequest(
            method="double_lasso", outcome=Shelf(("retention",)),
            treatment=Shelf(("code::C0",)),
            predictors=Shelf(tuple(wide[1:30])))

        found = problems(request, wide, n_cases=40)

        assert any("per candidate predictor" in p for p in found)

    def test_no_growth_clause_when_the_flat_floor_already_binds(self):
        request = spec(method="double_lasso", treatment=("code::Cost",),
                       predictors=("desc::gpa",))

        found = issues(request, n_cases=40)

        assert not any("per candidate predictor" in p for p in found)

    def test_the_floor_blocks_rather_than_advises(self):
        request = spec(method="random_forest", predictors=("code::Cost",))

        assert not can_run(request, COLUMNS, n_cases=40)

    def test_each_method_gives_its_own_reason(self):
        inferential = issues(spec(method="double_lasso",
                                  treatment=("code::Cost",),
                                  predictors=("desc::gpa",)), n_cases=10)
        forest = issues(spec(method="random_forest",
                             predictors=("code::Cost",)), n_cases=10)

        assert any("interval is optimistic" in p for p in inferential)
        assert any("which cases landed in which split" in p for p in forest)

    def test_too_many_predictors_for_plain_regression_is_advice_not_a_block(self):
        request = spec(method="ols", predictors=tuple(COLUMNS[:5]))

        found = problems(request, COLUMNS, n_cases=40)
        assert any("cases each" in p for p in found)
        assert can_run(request, COLUMNS, n_cases=40), "advice must not block"

    def test_the_advice_points_at_a_method_that_is_actually_available(self):
        """Found by walking realistic specs through the panel, not by a test.

        The advice used to say "this is what lasso and ridge are for"
        unconditionally. At n = 42 lasso is below its own floor of 50, so the
        program recommended a method it then refused to run — a circle, with
        every test passing.
        """
        found = problems(spec(method="ols", predictors=tuple(COLUMNS[:5])),
                         COLUMNS, n_cases=42)
        advice = next(p for p in found if "cases each" in p)

        assert "lasso" not in advice.lower() or "at this sample size" in advice
        assert "fewer predictors" in advice

    def test_at_a_workable_size_it_names_the_shrinkage_methods(self):
        found = problems(spec(method="ols", predictors=tuple(COLUMNS[:6])),
                         COLUMNS, n_cases=55)
        advice = next(p for p in found if "cases each" in p)

        assert "Lasso" in advice or "Ridge" in advice

    def test_every_method_the_advice_names_clears_its_floor(self):
        """The property the bug violated, checked across sample sizes rather
        than at one."""
        for n in (30, 42, 49, 50, 80, 400):
            found = problems(spec(method="ols", predictors=tuple(COLUMNS[:6])),
                             COLUMNS, n_cases=n)
            advice = [p for p in found if "cases each" in p]
            if not advice:
                continue
            for key in ("lasso", "ridge", "elastic_net"):
                if METHODS[key].label in advice[0]:
                    assert n >= METHODS[key].floor, (
                        f"at n={n} the advice names {key}, floor "
                        f"{METHODS[key].floor}")

    def test_regularised_methods_do_not_get_the_ratio_advice(self):
        """Relaxing that ratio is the reason they exist."""
        found = problems(spec(method="lasso", predictors=tuple(COLUMNS[:5])),
                         COLUMNS, n_cases=60)

        assert not any("cases each" in p for p in found)

    def test_too_many_folds_for_the_sample_is_advice(self):
        request = spec(predictors=("code::Cost",), folds=10)

        found = problems(request, COLUMNS, n_cases=30)
        assert any("per fold" in p for p in found)
        assert can_run(request, COLUMNS, n_cases=30)

    def test_no_sample_size_means_no_sample_size_complaints(self):
        """A panel with no project open should not scold about n."""
        found = problems(spec(method="double_lasso", treatment=("code::Cost",),
                              predictors=("desc::gpa",)), COLUMNS)

        assert not any("cases" in p for p in found)

    def test_every_method_states_a_floor(self):
        assert all(m.floor > 0 for m in METHODS.values())

    def test_the_ratio_rule_of_thumb_is_a_stated_number(self):
        assert COMFORTABLE_CASES_PER_PREDICTOR >= 5


class TestDescribe:

    def test_an_inferential_model_reads_as_an_effect(self):
        line = describe(spec(method="double_lasso", treatment=("code::Cost",),
                             predictors=("desc::gpa", "n_codes")))

        assert "effect of code::Cost on retention" in line
        assert "2 control(s)" in line

    def test_a_predictive_model_reads_as_a_prediction(self):
        line = describe(spec(method="lasso",
                             predictors=("code::Cost", "desc::gpa")))

        assert "retention on 2 predictor(s)" in line

    def test_an_empty_spec_describes_itself_without_raising(self):
        assert "(no outcome)" in describe(ModelRequest())


class TestSavingAndReopening:

    def test_a_spec_survives_a_round_trip(self):
        request = spec(method="double_lasso", treatment=("code::Cost",),
                       predictors=("desc::gpa",), controls=("n_codes",),
                       title="Cost and retention", seed=7, folds=3)

        assert request_from_dict(request_to_dict(request)) == request

    def test_what_is_stored_is_the_spec_not_a_result(self):
        """A saved model re-run against a project coded further should give the
        newer answer. That is the point of saving it rather than a screenshot."""
        stored = request_to_dict(spec(predictors=("code::Cost",)))

        assert set(stored) == {"method", "shelves", "title", "seed", "folds"}

    def test_it_is_plain_json(self):
        import json

        stored = request_to_dict(spec(method="lasso",
                                      predictors=("code::Cost",)))

        assert json.loads(json.dumps(stored)) == stored

    def test_an_older_saved_model_still_opens(self):
        """Missing keys must not raise in a dialog."""
        request = request_from_dict({"method": "lasso"})

        assert request.method == "lasso"
        assert request.outcome.is_empty

    def test_an_empty_dict_gives_a_usable_default(self):
        assert request_from_dict({}).method == "ols"

    def test_the_seed_is_fixed_and_saved(self):
        """A model whose numbers move between runs is not admissible in a
        program that sells reproducibility."""
        assert ModelRequest().seed == request_from_dict({}).seed
        assert request_to_dict(spec(seed=99))["seed"] == 99


def test_the_module_fits_nothing():
    """`core/` holds what a thing *is*; `analysis/` does it. Importing a model
    library here would also make the spec unimportable in the lite install."""
    import ast

    import core.model_spec as module

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    imported = {(node.module or "").split(".")[0]
                for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    imported |= {alias.name.split(".")[0]
                 for node in ast.walk(tree) if isinstance(node, ast.Import)
                 for alias in node.names}

    assert not ({"sklearn", "scipy", "numpy", "pandas", "statsmodels"} & imported)
