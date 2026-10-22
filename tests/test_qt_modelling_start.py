"""Modelling as a visible Explore tab with a plain three-choice start (Update 3, item 3.10a).

Offline, on the same fake service and matrix as `test_qt_model_view.py`.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import QCheckBox, QGroupBox, QLabel, QPushButton, QRadioButton, QToolButton

from analysis.models import fit
from core.ux import activities, words
from qualsafe_qt.widgets.more_options import MAX_VISIBLE_CONTROLS, visible_controls
from tests.test_qt_model_view import FakeService, matrix


@pytest.fixture()
def view(qapp, monkeypatch):
    import qualsafe_qt.views.model_view as module

    monkeypatch.setattr(module, "matrix_from_project", lambda project, **kwargs: matrix())
    widget = module.ModelView(FakeService(), QUndoStack())
    widget.resize(1200, 800)
    widget.show()
    qapp.processEvents()
    yield widget
    widget.close()


def mains(v):
    return [b for b in v.findChildren(QPushButton) if b.property("main") and b.isVisibleTo(v)]


def pick(combo, key):
    index = combo.findData(key)
    assert index >= 0, key
    combo.setCurrentIndex(index)


# ── it is a visible tab, not a "More tools" item ────────────────────────────

@pytest.mark.parametrize("key", ["surveys", "interviews"])
def test_modelling_is_shown_in_explore_not_under_more_tools(key):
    step = activities.get(key).step("explore")
    for surface in (activities.DESKTOP, activities.WEB):
        assert "Modelling" in step.screens[surface]
        assert "Modelling" not in step.more[surface]


# ── the plain start ─────────────────────────────────────────────────────────

def test_three_plain_choices_in_order_and_the_readable_tree_is_the_start(view):
    texts = [view.goal_buttons[k].text() for k in ("tree", "forest", "effect")]
    assert texts == ["See which themes go with the outcome, as rules I can read",
                     "See which themes matter most for the outcome",
                     "Estimate the effect of one thing, allowing for the others"]
    assert view.goal() == "tree" and view.method.currentData() == "decision_tree"


@pytest.mark.parametrize("goal,method", [("tree", "decision_tree"), ("forest", "random_forest"),
                                         ("effect", "double_lasso")])
def test_each_choice_starts_its_method(view, goal, method):
    view.goal_buttons["forest" if goal != "forest" else "tree"].setChecked(True)     # move off it first
    view.goal_buttons[goal].setChecked(True)
    assert view.method.currentData() == method and view.goal() == goal


def test_a_method_chosen_under_more_options_leaves_the_three_choices_off(view):
    pick(view.method, "ols")
    assert view.goal() == ""
    pick(view.method, "random_forest")
    assert view.goal() == "forest"


def test_only_the_effect_choice_asks_for_the_one_thing_whose_effect_you_want(view, qapp):
    assert not view.treatment_combo.isVisibleTo(view) and not view.treatment_label.isVisibleTo(view)
    view.goal_buttons["effect"].setChecked(True)
    assert view.treatment_combo.isVisibleTo(view) and view.treatment.isEnabled()
    view.goal_buttons["forest"].setChecked(True)
    assert not view.treatment_combo.isVisibleTo(view) and not view.treatment.isEnabled()


# ── picking the outcome in plain words ──────────────────────────────────────

def test_the_outcome_is_picked_from_a_list_and_reaches_the_request(view):
    names = [view.outcome_combo.itemText(i) for i in range(view.outcome_combo.count())]
    assert names[0] == "(choose)" and "Retention" in names
    assert not any("::" in n or n.endswith("_id") for n in names)         # plain names, not internal ones
    assert "Cost" in names and "Gpa" in names
    pick(view.outcome_combo, "retention")
    assert view.outcome.field() == "retention" and view.request().outcome.first == "retention"


def test_a_field_dragged_onto_the_shelf_shows_in_the_picker(view):
    view.outcome.set_field("retention")
    assert view.outcome_combo.currentData() == "retention"
    view.outcome.clear_field()
    assert view.outcome_combo.currentData() == ""


def test_the_codes_it_starts_with_are_the_predictors(view):
    assert view.predictors.fields()            # no need to choose them to get a first result


# ── few controls, one filled button, caveats with the numbers ───────────────

@pytest.mark.parametrize("goal", ["tree", "forest", "effect"])
def test_every_choice_shows_at_most_seven_controls_and_one_filled_button(view, qapp, goal):
    view.goal_buttons[goal].setChecked(True)
    qapp.processEvents()
    assert len(visible_controls(view)) <= MAX_VISIBLE_CONTROLS, \
        [(type(w).__name__, getattr(w, "text", lambda: "")()) for w in visible_controls(view)]
    assert mains(view) == [view.run_button]


def test_after_a_fit_it_still_shows_at_most_seven_controls(view, qapp):
    view.goal_buttons["effect"].setChecked(True)
    pick(view.outcome_combo, "retention")
    pick(view.treatment_combo, "code::Cost")
    view._on_fitted(fit(view._matrix, view.request()))
    qapp.processEvents()
    assert view.caveats.isVisibleTo(view)
    assert len(visible_controls(view)) <= MAX_VISIBLE_CONTROLS


def test_the_caveats_appear_with_the_numbers_not_before(view):
    assert not view.caveats.isVisibleTo(view)
    view.outcome.set_field("retention")
    view._on_fitted(fit(view._matrix, view.request()))
    assert view.caveats.isVisibleTo(view) and "How to read this" in view.caveats.toHtml()


def test_a_refused_fit_shows_no_caveats_pane(view):
    from analysis.models import ModelResult
    view._on_fitted(ModelResult(method="decision_tree", outcome="retention", refusal="Not enough cases."))
    assert not view.caveats.isVisibleTo(view)


# ── everything else is under More options, and nothing was removed ──────────

def test_more_options_holds_the_rest_and_starts_closed(view, qapp):
    assert not view.more.is_expanded()
    hidden = [view.method, view.unit, view.encoding, view.rater, view.seed, view.folds,
              view.export_button, view.predictors, view.controls, view.fields]
    assert all(not w.isVisibleTo(view) for w in hidden)
    view.more.toggle.click()
    qapp.processEvents()
    assert all(w.isVisibleTo(view) for w in hidden)
    assert view.more.toggle.text().startswith("More options (")


def test_every_method_is_still_offered_under_more_options(view):
    from core.model_spec import METHODS
    offered = [view.method.itemData(i) for i in range(view.method.count())]
    assert set(offered) == set(METHODS)


def test_the_seed_and_folds_still_reach_the_request(view):
    view.seed.setValue(7)
    view.folds.setValue(4)
    assert view.request().seed == 7 and view.request().folds == 4


# ── the whole path a user follows: pick, fit, read ────────

@pytest.mark.parametrize("goal", ["tree", "forest", "effect"])
def test_the_path_from_choice_to_a_table_and_caveats(view, goal):
    view.goal_buttons[goal].setChecked(True)
    pick(view.outcome_combo, "retention")
    if goal == "effect":
        pick(view.treatment_combo, "code::Cost")
    assert view.run_button.isEnabled()
    view._on_fitted(fit(view._matrix, view.request()))
    assert view.table_model.rowCount() >= 1 and view.caveats.isVisibleTo(view)
    if goal == "forest":
        assert "no direction" in view.caveats.toHtml()


# ── plain words ─────────────────────────────────────────────────────────────

def test_no_banned_or_technical_words_on_the_screen(view, qapp):
    view.more.toggle.click()
    qapp.processEvents()
    texts = [w.text() for kind in (QLabel, QPushButton, QCheckBox, QRadioButton, QToolButton)
             for w in view.findChildren(kind) if w.isVisibleTo(view)]
    texts += [g.title() for g in view.findChildren(QGroupBox) if g.isVisibleTo(view)]
    for text in texts:
        assert words.find_never(text) == [], text
        assert words.find_replace(text) == [], text


def test_picking_the_outcome_or_the_effect_takes_it_out_of_the_starting_predictors(view):
    assert "code::Cost" in view.predictors.fields()
    view.goal_buttons["effect"].setChecked(True)
    pick(view.treatment_combo, "code::Cost")
    assert "code::Cost" not in view.predictors.fields() and view.treatment.field() == "code::Cost"
    pick(view.outcome_combo, "code::Access")
    assert "code::Access" not in view.predictors.fields()


def test_the_field_list_and_summary_use_plain_names_not_internal_ones(view):
    shown = [view.fields.item(i).text() for i in range(view.fields.count())]
    assert not any("::" in text for text in shown), shown
    assert any(text.startswith("Cost") and "theme" in text for text in shown)
    assert any("respondent detail" in text for text in shown)
    summary = view.empty_label.text()
    assert "descriptor" not in summary and "source_id" not in summary and "one per document" in summary


def test_the_shelves_the_summary_and_the_problems_use_plain_names(view):
    view.goal_buttons["effect"].setChecked(True)
    pick(view.outcome_combo, "retention")
    pick(view.treatment_combo, "code::Cost")
    view.predictors.add_field("code::Cost")                       # a clash, to get a problem sentence
    shelf_text = " ".join([view.treatment.field_label.text(),
                           " ".join(view.predictors.list.item(i).text() for i in range(view.predictors.list.count()))])
    assert "::" not in shelf_text and "Cost" in shelf_text
    assert "::" not in view.summary.text() and "::" not in view.problems.text()
    assert "Cost" in view.problems.text()


def test_nothing_chosen_yet_is_a_note_not_a_red_problem(view):
    view.outcome.clear_field()
    view._validate()
    assert "Note" in view.problems.text() and "Problem" not in view.problems.text()
    assert not view.run_button.isEnabled()
    pick(view.outcome_combo, "retention")
    view._validate()
    assert view.problems.isHidden()                      # nothing left to say once it is chosen
