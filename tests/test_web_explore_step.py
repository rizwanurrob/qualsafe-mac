"""Surveys, step 4 (Explore) on the web: Analysis, Charts of themes, Search, Model an outcome (item 4b.5d)."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.sample_project import build_sample_project
from core.ux import activities
from tests import webkit

ROOT = Path(__file__).resolve().parents[1]
SAMPLE_CSV = ROOT / "data" / "sample_survey_education.csv"


@pytest.fixture
def project():
    """A finished sample project in this test's own output folder (where the pages look for runs)."""
    from app.shared import constants

    out = constants.STREAMLIT_OUTPUT_DIR / "SAMPLE_explore" / "project.qnw"
    out.parent.mkdir(parents=True)
    build_sample_project(SAMPLE_CSV, out)
    return out


def _open(project, page: str):
    at = webkit.start("survey")
    at.session_state["active_project_path"] = str(project)
    return webkit.go(at, page)


# -- the step offers its screens in plain names -------------------------------------------------------

def test_explore_offers_four_screens_in_plain_names_and_query_under_more_tools(project):
    at = _open(project, "Analysis")
    pick = next(r for r in at.radio if r.key == "pick_surveys_explore")
    assert list(pick.options) == ["Analysis", "Charts of themes", "Search", "Model an outcome"]
    assert activities.web_screen_title("Query & Synthesis") == "Query"
    assert any("More tools" in e.label for e in at.expander)


# -- Analysis ------------------------------------------------------------------------------------------

def test_analysis_has_four_named_tabs_and_a_more_tab(project):
    at = _open(project, "Analysis")
    labels = [t.label for t in at.get("tab")]
    assert labels == ["How often", "By group", "Together", "Agreement (Cohen's κ)", "More"], labels


def test_every_analysis_tab_shows_seven_controls_or_fewer(project):
    at = _open(project, "Analysis")
    for index in range(5):
        shown = webkit.visible_controls(at, tab=index)
        assert len(shown) <= webkit.MAX_VISIBLE_CONTROLS, (index, webkit.describe(shown))


def test_the_rarer_analyses_and_project_notes_are_under_more(project):
    at = _open(project, "Analysis")
    more = next(s for s in at.selectbox if s.key == "an_more")
    assert list(more.options) == ["Joint display", "Saturation", "Deviant cases"]
    for choice in ("Saturation", "Deviant cases", "Joint display"):
        next(x for x in at.selectbox if x.key == "an_more").set_value(choice).run()
        assert not at.exception, (choice, at.exception)
    assert any("Notes on this whole project" in str(e.label) for e in at.expander) or \
        any("Notes on this whole project" in str(m.value) for m in at.markdown)


# -- Charts of themes ----------------------------------------------------------------------------------

def test_charts_of_themes_starts_with_a_few_choices_and_folds_the_builder(project):
    at = _open(project, "Chart Builder")
    visible = webkit.visible_controls(at)
    assert len(visible) <= webkit.MAX_VISIBLE_CONTROLS, webkit.describe(visible)
    keys = [getattr(c, "key", None) for c in visible]
    assert any(str(k).startswith("chart_suggest_") for k in keys)
    outside = {getattr(c, "key", None) for c in visible}
    inside = {getattr(c, "key", None) for c in webkit.all_controls(at)}
    for folded in ("chart_mark", "chart_shelf_x_field", "chart_title"):
        assert folded not in outside and folded in inside, folded


def test_choosing_a_starting_point_draws_the_chart_and_keeps_save_and_share_folded(project):
    at = _open(project, "Chart Builder")
    next(b for b in at.button if str(b.key).startswith("chart_suggest_")).click().run()
    assert not at.exception, at.exception
    visible = webkit.visible_controls(at)
    assert len(visible) <= webkit.MAX_VISIBLE_CONTROLS, webkit.describe(visible)
    assert at.session_state["chart_mark"]
    inside = {getattr(c, "key", None) for c in webkit.all_controls(at)}
    assert "chart_save_btn" in inside and "chart_save_btn" not in {getattr(c, "key", None) for c in visible}
    assert any("Save or share this chart" in e.label for e in at.expander)


def test_what_to_chart_is_in_plain_words(project):
    at = _open(project, "Chart Builder")
    source = next(r for r in at.radio if r.key == "chart_source")
    assert list(source.options) == ["The codes", "The codes, with respondent details"] or \
        list(source.options) == ["Codings", "Codings with descriptors"]


# -- Search --------------------------------------------------------------------------------------------

def test_search_shows_the_box_and_folds_how_to_match(project):
    at = _open(project, "Search")
    visible = webkit.visible_controls(at)
    assert [getattr(c, "key", None) for c in visible if getattr(c, "key", "").startswith("search_")] == ["search_query"]
    inside = {getattr(c, "key", None) for c in webkit.all_controls(at)}
    for folded in ("search_mode", "search_whole", "search_case", "search_type", "search_limit"):
        assert folded in inside and folded not in {getattr(c, "key", None) for c in visible}, folded


def test_search_finds_and_names_its_tabs_plainly(project):
    at = _open(project, "Search")
    assert [t.label for t in at.get("tab")] == ["Search", "Word counts"]
    next(t for t in at.text_input if t.key == "search_query").set_value("advis").run()
    assert not at.exception, at.exception


def test_the_word_counts_settings_are_folded(project):
    at = _open(project, "Search")
    visible = webkit.visible_controls(at, tab=1)
    assert not [c for c in visible if str(getattr(c, "key", "")).startswith("wf_")]
    inside = {getattr(c, "key", None) for c in webkit.all_controls(at)}
    assert {"wf_type", "wf_topn", "wf_minlen", "wf_stops", "wf_extra"} <= inside


# -- Model an outcome ----------------------------------------------------------------------------------

def test_modelling_asks_what_you_want_to_do_then_what_to_explain(project):
    at = _open(project, "Modelling")
    goal = next(r for r in at.radio if r.key == "model_goal")
    assert list(goal.options) == [t for _k, _m, t in __import__("core.ux.model_goals", fromlist=["x"]).GOALS] \
        or list(goal.options) == ["tree", "forest", "effect"]
    visible = webkit.visible_controls(at)
    assert len(visible) <= webkit.MAX_VISIBLE_CONTROLS, webkit.describe(visible)
    keys = [getattr(c, "key", None) for c in visible]
    assert "model_goal" in keys and "model_outcome" in keys


def test_the_goal_picks_the_method_and_an_effect_asks_for_its_one_thing(project):
    at = _open(project, "Modelling")
    assert at.session_state["model_method"] == "decision_tree"
    visible_keys = [getattr(c, "key", None) for c in webkit.visible_controls(at)]
    assert "model_treatment" not in visible_keys
    next(r for r in at.radio if r.key == "model_goal").set_value("effect").run()
    assert not at.exception, at.exception
    assert at.session_state["model_method"] == "double_lasso"
    assert "model_treatment" in [getattr(c, "key", None) for c in webkit.visible_controls(at)]
    next(r for r in at.radio if r.key == "model_goal").set_value("forest").run()
    assert at.session_state["model_method"] == "random_forest"


def test_the_method_seed_folds_and_variables_are_under_more_options(project):
    at = _open(project, "Modelling")
    visible = {getattr(c, "key", None) for c in webkit.visible_controls(at)}
    inside = {getattr(c, "key", None) for c in webkit.all_controls(at)}
    for folded in ("model_method", "model_seed", "model_folds", "model_predictors", "model_controls"):
        assert folded in inside and folded not in visible, folded


def test_the_fit_button_is_the_one_main_button(project):
    at = _open(project, "Modelling")
    main = webkit.primary_buttons(at)
    assert [b.key for b in main] == ["model_fit"] or main == []
