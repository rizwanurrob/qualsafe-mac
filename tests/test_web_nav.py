"""The web app's navigation: Home, activities, Settings, Help (phase 4b). No browser: session state only."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.shared import nav
from core import theme
from core.ux import activities, words
from tests.test_ux_colours import contrast


class State(dict):
    """A stand-in for `st.session_state`: a dict you can also read with attributes' pop/get."""


@pytest.fixture
def state(monkeypatch):
    fake = State()
    monkeypatch.setattr(nav.st, "session_state", fake)
    return fake


# -- starting out -----------------------------------------------------------------------------

def test_the_app_opens_on_home(state):
    nav.init_nav()
    assert nav.view() == nav.HOME and nav.current_activity() == "" and nav.breadcrumb() == "QualSafe"


@pytest.mark.parametrize("mode,activity", [("survey", "surveys"), ("interview", "interviews")])
def test_an_old_style_mode_opens_the_matching_activity(state, mode, activity):
    state["app_mode"] = mode
    nav.init_nav()
    assert nav.view() == nav.ACTIVITY and nav.current_activity() == activity


def test_an_unknown_mode_is_just_home(state):
    state["app_mode"] = "something else"
    nav.init_nav()
    assert nav.view() == nav.HOME


# -- going places -----------------------------------------------------------------------------

def test_going_to_an_activity_remembers_the_step_and_keeps_the_mode_in_step(state):
    nav.init_nav()
    nav.go_activity("surveys", "explore")
    assert (nav.view(), nav.current_activity(), nav.step_of("surveys")) == (nav.ACTIVITY, "surveys", "explore")
    assert state["app_mode"] == "survey" and nav.breadcrumb() == "QualSafe › Surveys › 4 Explore"
    nav.go_activity("charts")
    assert state["app_mode"] == "" and nav.breadcrumb() == "QualSafe › Charts › 1 Open"
    nav.go_home()
    assert nav.step_of("surveys") == "explore"          # leaving does not forget where you were
    nav.go_activity("surveys")
    assert nav.step_of("surveys") == "explore"          # and coming back goes there


def test_an_activity_with_no_step_chosen_starts_at_its_first(state):
    nav.init_nav()
    assert nav.step_of("interviews") == "add"
    state["step_interviews"] = "not-a-step"
    assert nav.step_of("interviews") == "add"


def test_an_unknown_step_is_an_error_not_a_blank_page(state):
    nav.init_nav()
    with pytest.raises(KeyError):
        nav.go_activity("surveys", "no-such-step")


def test_settings_and_help_are_places_too(state):
    nav.init_nav()
    nav.go_settings("Models")
    assert nav.view() == nav.SETTINGS and state["settings_tab"] == "Models"
    assert nav.breadcrumb() == "QualSafe › Settings"
    nav.go_settings("not a tab")
    assert state["settings_tab"] == "Models"
    nav.go_help()
    assert nav.view() == nav.HELP and nav.breadcrumb() == "QualSafe › Help"


# -- screens inside a step ----------------------------------------------------------------------

def test_a_step_with_several_screens_shows_the_first_until_one_is_chosen(state):
    nav.init_nav()
    main, more = nav.screens("surveys", "explore")
    assert main == ["Analysis", "Chart Builder", "Search", "Modelling"] and more == ["Query & Synthesis"]
    assert nav.current_screen("surveys", "explore") == "Analysis"
    nav.set_screen("surveys", "explore", "Query & Synthesis")
    assert nav.current_screen("surveys", "explore") == "Query & Synthesis"
    nav.set_screen("surveys", "explore", "Data Setup")             # not in this step: ignored
    assert nav.current_screen("surveys", "explore") == "Analysis"


def test_every_step_has_at_least_one_screen_on_the_web():
    for activity in activities.ACTIVITIES:
        for step in activity.steps:
            main, more = (list(step.screens.get(nav.SURFACE, ())), list(step.more.get(nav.SURFACE, ())))
            assert main or more, (activity.key, step.key)


# -- turning a page name into a place ----------------------------------------------------------

@pytest.mark.parametrize("page,expected", [
    ("Data Setup", ("surveys", "load")), ("Theme Setup", ("surveys", "themes")),
    ("Run Analysis", ("surveys", "code")), ("Alt Survey Flow", ("surveys", "code")),
    ("Interview Mode", ("interviews", "add")), ("Documents", ("interviews", "add")),
    ("Data Charts", ("charts", "open")), ("Results & Downloads", ("surveys", "report")),
    ("Query & Synthesis", ("surveys", "explore")),
])
def test_a_page_belongs_to_one_place_when_it_belongs_to_one(page, expected):
    assert nav.resolve(page) == expected


def test_a_shared_page_goes_to_the_activity_you_are_in():
    assert nav.resolve("Analysis") == ("surveys", "explore")
    assert nav.resolve("Analysis", prefer="interviews") == ("interviews", "explore")
    assert nav.resolve("Codebook", prefer="interviews") == ("interviews", "codebook")
    assert nav.resolve("Codebook", prefer="surveys") == ("surveys", "themes")


def test_a_page_that_is_nowhere_resolves_to_nothing():
    assert nav.resolve("No Such Page") is None
    assert nav.resolve("Model Manager") is None            # Settings, not an activity


def test_a_pending_target_is_acted_on_once(state):
    nav.init_nav()
    state["nav_target"] = "Run Analysis"
    assert nav.apply_nav_target() == "Run Analysis"
    assert (nav.current_activity(), nav.step_of("surveys"), nav.current_screen("surveys", "code")) == (
        "surveys", "code", "Run Analysis")
    assert "nav_target" not in state and nav.apply_nav_target() == ""


def test_targets_for_settings_and_help_open_those_places(state):
    nav.init_nav()
    state["nav_target"] = "Data Management"
    nav.apply_nav_target()
    assert nav.view() == nav.SETTINGS and state["settings_tab"] == "Project and backups"
    state["nav_target"] = "Help & Troubleshooting"
    nav.apply_nav_target()
    assert nav.view() == nav.HELP
    state["nav_target"] = "Nowhere"
    assert nav.apply_nav_target() == "" and nav.view() == nav.HELP


# -- the colour --------------------------------------------------------------------------------

@pytest.mark.parametrize("mode", ["light", "dark"])
@pytest.mark.parametrize("key", ["", "surveys", "charts", "interviews"])
def test_each_activity_colours_the_header_the_band_and_the_main_button(key, mode):
    css = theme.activity_web_css(key, mode)
    palette = theme.get_palette(mode)
    accent = palette[f"activity.{key}"] if key else palette["text_muted"]
    assert css.count(accent) >= 5                    # header, sidebar edge, band, button, tabs, link, focus
    for part in ('[data-testid="stHeader"]', ".qs-band", '[data-testid="stBaseButton-primary"]',
                 "[data-baseweb=\"tab\"][aria-selected=\"true\"]", "*:focus-visible"):
        assert part in css
    assert "{{" not in css and "}}" not in css


@pytest.mark.parametrize("mode", ["light", "dark"])
@pytest.mark.parametrize("key", ["surveys", "charts", "interviews"])
def test_the_text_on_an_activity_colour_can_be_read(key, mode):
    palette = theme.get_palette(mode)
    assert contrast(palette[f"activity.{key}.on"], palette[f"activity.{key}"]) >= 4.5


@pytest.mark.parametrize("mode", ["light", "dark"])
@pytest.mark.parametrize("key", ["", "surveys", "charts", "interviews"])
def test_the_label_inside_the_main_button_takes_the_readable_colour(key, mode):
    """The label is a <p>, and the page's own paragraph colour beats the button's unless the rule
    names the <p>: in the browser pane it came out dark on the activity colour."""
    palette = theme.get_palette(mode)
    on = palette[f"activity.{key}.on"] if key else palette["bg"]
    css = theme.activity_web_css(key, mode)
    assert '[data-testid="stBaseButton-primary"]:not(:disabled) p' in css
    assert f"{{ color: {on} !important; }}" in css


@pytest.mark.parametrize("mode", ["light", "dark"])
def test_the_main_button_keeps_its_colour_under_the_pointer(mode):
    """Streamlit paints a hovered main button its own red; found in the browser pane. The activity's
    colour is named for hover, focus and press, on the page and on each Home card."""
    for key in ("", "surveys", "charts", "interviews"):
        css = theme.activity_web_css(key, mode)
        assert '[data-testid="stBaseButton-primary"]:hover' in css and ":focus" in css and ":active" in css
    home = theme.home_web_css(mode)
    for key in ("surveys", "charts", "interviews"):
        assert f'.st-key-card_{key} [data-testid="stBaseButton-primary"]:hover' in home


@pytest.mark.parametrize("mode", ["light", "dark"])
def test_the_open_list_of_a_select_follows_the_skin(mode):
    """The list is drawn outside the page, in Streamlit's base theme: dark under the light skin."""
    css = theme.activity_web_css("surveys", mode)
    palette = theme.get_palette(mode)
    assert '[data-testid="stSelectboxVirtualDropdown"]' in css and '[role="option"]' in css
    assert f"background-color: {palette['surface']} !important" in css


def test_tables_follow_the_light_skin_and_leave_the_dark_one_alone():
    """Tables are canvases in Streamlit's own (dark) theme; the light skin inverts them."""
    rule = '[data-testid="stDataFrameResizable"] { filter: invert(1) hue-rotate(180deg); }'
    for key in ("", "surveys", "charts", "interviews"):
        assert rule in theme.activity_web_css(key, "light")
        assert "stDataFrameResizable" not in theme.activity_web_css(key, "dark")


@pytest.mark.parametrize("mode", ["light", "dark"])
@pytest.mark.parametrize("key", ["surveys", "charts", "interviews"])
def test_tabs_slider_and_multiselect_chips_take_the_activity_colour(key, mode):
    """Streamlit's own red showed on tab underlines, the slider and chosen items (browser pane)."""
    css = theme.activity_web_css(key, mode)
    accent = theme.get_palette(mode)[f"activity.{key}"]
    assert f'[role="tablist"] [class*="SelectionIndicator"] {{ background-color: {accent} !important; }}' in css
    assert f"hue-rotate({theme._hue_shift(accent)}deg)" in css
    assert f'[data-testid="stMultiSelect"] span[data-tag] {{ background-color: {accent} !important;' in css


def test_the_hue_shift_turns_streamlits_red_onto_the_accent():
    assert theme._hue_shift("#E03846") == 0
    assert 170 < theme._hue_shift("#0F766E") < 190           # teal


@pytest.mark.parametrize("mode", ["light", "dark"])
def test_a_disabled_main_button_stays_readable(mode):
    """The label rule for main buttons must not whiten a disabled one (white on nothing)."""
    css = theme.activity_web_css("surveys", mode)
    muted = theme.get_palette(mode)["text_muted"]
    assert '[data-testid="stBaseButton-primary"]:not(:disabled) *' in css
    assert f'[data-testid="stBaseButton-primary"]:disabled * {{\n    color: {muted} !important;' in css


def test_the_neutral_style_is_used_when_there_is_no_activity():
    css = theme.activity_web_css("", "light")
    assert all(theme.get_palette("light")[f"activity.{k}"] not in css for k in ("surveys", "charts", "interviews"))


def test_home_cards_each_take_their_own_colour():
    css = theme.home_web_css("light")
    for key in ("surveys", "charts", "interviews"):
        assert f".st-key-card_{key}" in css and theme.get_palette("light")[f"activity.{key}"] in css


# -- the words ----------------------------------------------------------------------------------

def test_home_and_settings_use_plain_words():
    from pathlib import Path

    root = Path(words.ROOT)
    for name in ("app/home_page.py", "app/settings_page.py", "app/shared/nav.py"):
        for text in words.ui_strings((root / name).read_text(encoding="utf-8")):
            assert words.find_never(text) == [], (name, text)
            assert words.find_replace(text) == [], (name, text)


def test_the_sample_and_the_output_folders_are_under_the_program_folder_not_inside_app():
    """Found in phase 4b: after the v4.1.0 split, PROJECT_ROOT pointed at app/shared, so the sample
    survey could not be opened (Data Setup's button, and the old wizard's) and runs would have
    been written under app/shared. The sample must exist, and nothing may live inside `app`."""
    from app.shared import constants

    assert constants.SYNTHETIC_FILE.is_file()
    assert (constants.PROJECT_ROOT / "streamlit_app.py").is_file()
    # The folders themselves are swapped for empty ones in every test (tests/conftest.py), so read
    # where they are defined.
    source = Path(constants.__file__).read_text(encoding="utf-8")
    assert 'PROJECT_ROOT / "output_streamlit"' in source and 'PROJECT_ROOT / "data" / "session_inputs"' in source
