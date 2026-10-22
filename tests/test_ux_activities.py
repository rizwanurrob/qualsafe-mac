"""The activity layout keeps every screen reachable and stays within its limits."""

import pytest

from core.ux import activities as ac


def test_three_activities_in_order():
    assert [a.key for a in ac.ACTIVITIES] == ["surveys", "charts", "interviews"]


@pytest.mark.parametrize("act", ac.ACTIVITIES, ids=lambda a: a.key)
def test_at_most_five_steps_each_with_an_intro(act):
    assert 1 <= len(act.steps) <= ac.MAX_STEPS
    keys = [s.key for s in act.steps]
    assert len(keys) == len(set(keys))
    for s in act.steps:
        assert s.intro.strip().endswith((".", "?")) and "\n" not in s.intro


def test_step_counts_match_the_plan():
    assert [len(a.steps) for a in ac.ACTIVITIES] == [5, 4, 5]


@pytest.mark.parametrize("surface", ac.SURFACES)
def test_every_current_screen_is_reachable(surface):
    assert ac.unplaced_screens(surface) == ()


@pytest.mark.parametrize("surface", ac.SURFACES)
def test_every_placed_screen_exists(surface):
    known = set(ac.ALL_SCREENS[surface])
    for _a, _s, screen, _m in ac.placements(surface):
        assert ac.top_level(screen) in known, screen


@pytest.mark.parametrize("surface", ac.SURFACES)
def test_a_step_never_lists_a_screen_twice(surface):
    for act in ac.ACTIVITIES:
        for step in act.steps:
            both = step.screens.get(surface, ()) + step.more.get(surface, ())
            assert len(both) == len(set(both)), (act.key, step.key)


def test_chart_tools_are_split_by_data_kind():
    # UX-2: charts of coded themes live in Surveys/Interviews; spreadsheets in Charts.
    assert ac.activity_for(ac.DESKTOP, "Data Charts") == ("charts",)
    assert ac.activity_for(ac.DESKTOP, "Charts") == ("interviews", "surveys")
    assert ac.activity_for(ac.WEB, "Chart Builder") == ("interviews", "surveys")


def test_survey_projects_never_start_on_documents():
    first = ac.SURVEYS.steps[0]
    assert "Documents" not in first.screens[ac.DESKTOP]
    assert "Documents" not in first.screens[ac.WEB]


def test_lookup_helpers():
    assert ac.get("charts").step_number("save") == 4
    with pytest.raises(KeyError):
        ac.get("nope")
    assert ac.top_level("Survey/Data") == "Survey"


def test_locations_say_where_a_screen_lives_in_words():
    assert ac.locations(ac.DESKTOP, "Search") == ("Surveys › 4 Explore", "Interviews › 4 Explore")
    assert "Surveys › 4 Explore (more tools)" in ac.locations(ac.DESKTOP, "Query")
    assert ac.locations(ac.DESKTOP, "Survey") == (
        "Surveys › 1 Load", "Surveys › 2 Themes", "Surveys › 3 Code")
    assert ac.locations(ac.DESKTOP, "Models") == ("Settings › Models",)
    assert ac.locations(ac.DESKTOP, "Data") == ("Settings › Project and backups",)
    assert ac.locations(ac.DESKTOP, "Help") == ("Help (top right)",)
    assert ac.locations(ac.WEB, "Model Manager") == ("Settings › Models",)


@pytest.mark.parametrize("surface", ac.SURFACES)
def test_every_screen_has_a_location(surface):
    for screen in ac.ALL_SCREENS[surface]:
        assert ac.locations(surface, screen), screen
