"""The desktop shell: Home, three activities with steps, Settings and Help."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from core.ux import activities as ac
from qualsafe_qt.version import APP_NAME
from qualsafe_qt.windows.main_window import MainWindow


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def window(app):
    win = MainWindow()
    win.resize(1200, 800)
    win.show()
    app.processEvents()
    yield win
    win.close()


def test_opens_on_home_with_three_activities(window):
    assert window.pages.currentWidget() is window.home
    assert list(window.home.start_buttons) == ["surveys", "charts", "interviews"]
    assert window.top_bar.crumb.text() == APP_NAME
    assert window.top_bar.home_button.isHidden()


@pytest.mark.parametrize("key", ["surveys", "charts", "interviews"])
def test_start_opens_the_first_step(window, key):
    window.home.start_buttons[key].click()
    act = ac.get(key)
    assert window.pages.currentWidget() is window.activity
    assert (window.activity.activity_key, window.activity.step_key) == (key, act.steps[0].key)
    assert window.top_bar.crumb.text().endswith(f"{act.title}  ›  1 {act.steps[0].title}")


def test_the_rail_shows_the_activitys_steps_and_moves_between_them(window):
    window.open_activity("surveys")
    assert window.activity.rail.step_keys() == [s.key for s in ac.SURVEYS.steps]
    window.activity.rail._buttons["explore"].click()
    assert window.activity.step_key == "explore"
    assert window.top_bar.crumb.text().endswith("Surveys  ›  4 Explore")
    window.open_activity("charts")
    assert window.activity.rail.step_keys() == [s.key for s in ac.CHARTS.steps]


def test_the_intro_line_comes_from_the_step_data(window):
    window.open_activity("interviews", "codebook")
    assert window.activity.intro.text() == ac.INTERVIEWS.step("codebook").intro


def test_survey_steps_select_the_matching_inner_tab_and_hide_its_own_tab_row(window):
    for index, step in enumerate(("load", "themes", "code")):
        window.open_activity("surveys", step)
        assert window.pipeline.tabs.currentIndex() == index
    assert window.pipeline.tabs.tabBar().isHidden()


def test_every_desktop_screen_in_the_map_is_mounted_by_its_step(window):
    screens = window.activity._screens
    for act, step, screen, _more in ac.placements(ac.DESKTOP):
        window.open_activity(act, step)
        assert window.activity.content.indexOf(screens[screen]) >= 0, (act, step, screen)


def test_a_shared_screen_moves_between_activities(window):
    window.open_activity("surveys", "explore")
    assert window.activity.content.indexOf(window.analysis) >= 0
    window.open_activity("interviews", "explore")
    assert window.activity.content.indexOf(window.analysis) >= 0
    window.open_activity("charts")
    assert window.activity.content.indexOf(window.analysis) < 0
    assert window.analysis.isHidden()


def test_no_screen_shows_through_unmounted(window, app):
    """Views are children of the window; any not mounted must stay hidden."""
    mounted = {id(window.activity.content.widget(i)) for i in range(window.activity.content.count())}
    for view in (window.documents, window.codebook, window.analysis, window.charts,
                 window.data_charts, window.modelling, window.search, window.query,
                 window.pipeline, window.results):
        assert id(view) in mounted or view.isHidden()
    window.open_activity("charts")
    app.processEvents()
    assert window.documents.isHidden() and window.pipeline.isHidden()


def test_switching_activity_leaves_no_old_step_buttons_behind(window):
    window.open_activity("surveys")
    old = list(window.activity.rail._buttons.values())
    window.open_activity("charts")
    assert all(b.parent() is None or b.isHidden() for b in old)


def test_home_settings_and_help_are_one_click_from_anywhere(window):
    window.open_activity("interviews", "explore")
    window.top_bar.settings_button.click()
    assert window.pages.currentWidget() is window.settings_tabs
    assert window.top_bar.crumb.text().endswith("Settings")
    assert window.settings_tabs.indexOf(window.models) >= 0
    assert window.settings_tabs.indexOf(window.data) >= 0
    window.top_bar.help_button.click()
    assert window.pages.currentWidget() is window.help
    window.top_bar.home_button.click()
    assert window.pages.currentWidget() is window.home


def test_a_search_hit_opens_the_reader(window):
    window.open_activity("charts")
    window._open_in_reader("no-such-source", 0, 5)
    assert (window.activity.activity_key, window.activity.content.currentWidget()) == (
        "interviews", window.documents)


# ── Home: sample, guide, recent projects, activity colour ────────────────────

def test_home_offers_the_sample_the_guide_and_open(window, monkeypatch):
    from qualsafe_qt.windows import main_window as module

    fired = []
    monkeypatch.setattr(window, "_open_sample_project", lambda: fired.append("sample"))

    def cancelled(*_args, **_kwargs):
        fired.append("open")
        return "", ""          # the person pressed Cancel

    monkeypatch.setattr(module.QFileDialog, "getOpenFileName", cancelled)
    window.home.sample_button.click()
    window.home.open_button.click()
    assert fired == ["sample", "open"]
    assert window._land_after_open is False   # a cancelled dialog opens nothing
    window.home.guide_button.click()
    assert window.pages.currentWidget() is window.help


def test_each_card_carries_its_activity_colour(window):
    from core import theme

    for mode in ("dark", "light"):
        window.home.set_theme_mode(mode)
        sheet = window.home.styleSheet()
        for act in ac.ACTIVITIES:
            assert theme.get_palette(mode)[act.colour_token] in sheet
            assert window.home.cards[act.key].property("activity") == act.key
            assert window.home.start_buttons[act.key].property("activity") == act.key


def _make_project(tmp_path, name, survey):
    from core.sample_project import build_sample_project
    from core.project import Project

    path = tmp_path / name
    if survey:
        from pathlib import Path
        build_sample_project(Path("data/sample_survey_education.csv"), path)
    else:
        Project.create(path).close()
    return path


def test_opening_a_project_adds_it_to_recent_tagged_by_activity(window, tmp_path):
    survey = _make_project(tmp_path, "survey.qnw", True)
    window._open_recent(str(survey), "surveys")
    window._service.close()
    docs = _make_project(tmp_path, "talks.qnw", False)
    window._service.open(docs)
    tags = {e["path"].split("\\")[-1].split("/")[-1]: e["activity"] for e in window._recent}
    assert tags == {"survey.qnw": "surveys", "talks.qnw": "interviews"}
    assert [b.text().split("   ·   ")[1] for b in window.home.recent_buttons] == [
        "Interviews", "Surveys"]


def test_recent_list_is_saved_as_paths_and_activity_only(window, tmp_path):
    window._service.open(_make_project(tmp_path, "talks.qnw", False))
    from core.ux import recent as r
    saved = r.parse(window._settings.value("recent_projects", ""))
    assert saved == window._recent and set(saved[0]) == {"path", "activity"}


def test_a_recent_project_opens_in_its_activity(window, tmp_path):
    survey = _make_project(tmp_path, "survey.qnw", True)
    window.go_home()
    window._open_recent(str(survey), "surveys")
    assert window.pages.currentWidget() is window.activity
    assert window.activity.activity_key == "surveys"


def test_a_missing_recent_file_is_not_listed_and_a_bad_open_stays_home(window, tmp_path, monkeypatch):
    window.home.set_recent([{"path": str(tmp_path / "gone.qnw"), "activity": "surveys"}])
    assert window.home.recent_buttons == [] and window.home.recent_heading.isHidden()
    from qualsafe_qt.windows import main_window as module
    monkeypatch.setattr(module.QMessageBox, "critical", lambda *a, **k: None)
    window.go_home()
    window._open_recent(str(tmp_path / "gone.qnw"), "surveys")
    assert window.pages.currentWidget() is window.home and window._land_after_open is False


# ── Activity colour inside an activity ───────────────────────────────────────

@pytest.mark.parametrize("mode", ["dark", "light"])
@pytest.mark.parametrize("act", ac.ACTIVITIES, ids=lambda a: a.key)
def test_activity_stylesheets_use_the_activity_tokens(act, mode):
    from core import theme
    from qualsafe_qt.theme import activity_shell_stylesheet, activity_topbar_stylesheet

    p = theme.get_palette(mode)
    shell = activity_shell_stylesheet(act.key, mode)
    band = activity_topbar_stylesheet(act.key, mode)
    assert p[act.colour_token] in shell and p[act.colour_token + ".on"] in shell
    assert p[act.colour_token] in band and p[act.colour_token + ".on"] in band
    # No other activity's accent leaks in.
    for other in ac.ACTIVITIES:
        if other.key != act.key:
            assert p[other.colour_token] not in shell + band


def test_the_band_and_rail_take_the_activity_colour_and_leave_with_it(window):
    from core import theme

    window.open_activity("surveys", "code")
    blue = theme.get_palette("dark")["activity.surveys"]
    assert blue in window.top_bar.styleSheet() and blue in window.activity.styleSheet()
    window.open_activity("charts")
    teal = theme.get_palette("dark")["activity.charts"]
    assert teal in window.top_bar.styleSheet() and blue not in window.activity.styleSheet()
    for neutral in (window.go_home, window.open_settings_page, window.open_help):
        neutral()
        assert window.top_bar.styleSheet() == ""


def test_switching_theme_recolours_the_open_activity(window):
    from core import theme

    window.open_activity("interviews", "code")
    window._apply_theme("light")
    assert theme.get_palette("light")["activity.interviews"] in window.activity.styleSheet()
    assert theme.get_palette("light")["activity.interviews"] in window.top_bar.styleSheet()


def test_the_main_buttons_are_marked_and_the_rest_are_not(window):
    assert window.pipeline.run_button.property("main") is True
    assert window.documents.apply_button.property("main") is True
    assert window.data_charts.open_button.property("main") is True
    assert not window.pipeline.tabs.property("main")


# ── Opening a project lands where it belongs (UX-5) ──────────────────────────

def _file_dialog_returns(monkeypatch, kind, path):
    from qualsafe_qt.windows import main_window as module

    monkeypatch.setattr(module.QFileDialog, kind, lambda *a, **k: (str(path), ""))


def test_file_open_of_a_survey_project_lands_in_surveys_at_explore(window, tmp_path, monkeypatch):
    path = _make_project(tmp_path, "survey.qnw", True)
    window.go_home()
    _file_dialog_returns(monkeypatch, "getOpenFileName", path)
    window._open_project()
    assert (window.activity.activity_key, window.activity.step_key) == ("surveys", "explore")
    assert window.pages.currentWidget() is window.activity
    assert window.activity.content.indexOf(window.documents) < 0     # not the empty list


def test_a_new_project_opens_in_interviews_at_add_transcripts(window, tmp_path, monkeypatch):
    window.go_home()
    _file_dialog_returns(monkeypatch, "getSaveFileName", tmp_path / "new.qnw")
    window._new_project()
    assert (window.activity.activity_key, window.activity.step_key) == ("interviews", "add")
    # The reader says what is true and what to do, not "No project open." (UX-5).
    heading = window.documents.doc_title.text()
    assert "No documents yet" in heading and "Import a folder" in heading
    assert "No project open" not in heading


def test_a_project_written_by_a_run_opens_to_its_results(window, tmp_path):
    path = _make_project(tmp_path, "run.qnw", True)
    window.open_activity("surveys", "code")
    window._open_written_project(str(path))
    assert (window.activity.activity_key, window.activity.step_key) == ("surveys", "explore")


def test_reopening_the_last_project_at_launch_starts_on_home(window, tmp_path, app):
    from qualsafe_qt.windows.main_window import MainWindow

    window._service.open(_make_project(tmp_path, "survey.qnw", True))
    window.close()
    second = MainWindow()
    try:
        assert second._service.is_open
        assert second.pages.currentWidget() is second.home
    finally:
        second.close()


def test_the_dialog_choice_does_not_leave_a_stale_landing(window, tmp_path, monkeypatch):
    from qualsafe_qt.windows import main_window as module

    monkeypatch.setattr(module.QMessageBox, "critical", lambda *a, **k: None)
    _file_dialog_returns(monkeypatch, "getOpenFileName", tmp_path / "missing.qnw")
    window._open_project()
    assert window._land_after_open is False


# ── Settings: General, Models, Project and backups ───────────────────────────

def test_settings_has_general_first_then_models_then_project_and_backups(window):
    tabs = window.settings_tabs
    assert [tabs.tabText(i) for i in range(tabs.count())] == [
        "General", "Models", "Project and backups"]
    assert tabs.widget(0) is window.general


def test_saving_a_name_reaches_the_project_and_the_preferences(window):
    window.general.name_edit.setText("  Dana Reyes ")
    window.general.name_button.click()
    assert window._service.analyst_name == "Dana Reyes"
    assert str(window._settings.value("analyst_name")) == "Dana Reyes"
    assert window.general.name_edit.text() == "Dana Reyes"


def test_the_menu_and_the_settings_tab_agree_about_the_name(window):
    window._save_analyst_name("Sam Okafor")
    assert window.general.name_edit.text() == "Sam Okafor"
    from qualsafe_qt.windows.main_window import MainWindow
    window.close()
    again = MainWindow()
    try:
        assert again.general.name_edit.text() == "Sam Okafor"
        assert again._service.analyst_name == "Sam Okafor"
    finally:
        again.close()


def test_the_theme_choice_applies_and_follows_the_menu(window):
    window.general.light_radio.setChecked(True)
    assert window._appearance["theme_mode"] == "light"
    window._theme_action.setChecked(False)               # View menu back to dark
    assert window._appearance["theme_mode"] == "dark"
    assert window.general.dark_radio.isChecked() and not window.general.light_radio.isChecked()


def test_the_full_appearance_dialog_is_one_click_away(window, monkeypatch):
    from qualsafe_qt.windows.appearance_dialog import AppearanceDialog

    opened = []
    monkeypatch.setattr(AppearanceDialog, "exec", lambda self: opened.append(True) or 0)
    window.general.more_look_button.click()
    assert opened == [True]


@pytest.mark.parametrize("enforced,word", [(True, "Offline mode is on"), (False, "Offline mode is off")])
def test_offline_status_is_an_icon_and_a_word(window, enforced, word):
    window.general.set_offline(enforced)
    assert word in window.general.offline_label.text()
    assert not window.general.offline_icon.pixmap().isNull()


def test_settings_is_reachable_from_every_screen_and_keeps_its_tab(window):
    window.open_activity("charts")
    window.top_bar.settings_button.click()
    window.settings_tabs.setCurrentWidget(window.models)
    window.top_bar.home_button.click()
    window.top_bar.settings_button.click()
    assert window.settings_tabs.currentWidget() is window.models


# ── Navigation: every screen has a place, and nothing is left on a tab row ───

def test_the_screens_the_window_builds_are_exactly_the_screens_the_map_places(window):
    """Both ways: a view built but never placed would be unreachable; a placed
    name with no view would be a dead step."""
    built = {ac.top_level(name) for name in window.activity._screens}
    built |= {"Models", "Data"}            # Settings
    built |= {"Help"}
    assert built == set(ac.DESKTOP_SCREENS)
    assert ac.unplaced_screens(ac.DESKTOP) == ()


def test_settings_and_help_hold_the_screens_the_map_assigns_to_them(window):
    for name in ac.SETTINGS_SCREENS[ac.DESKTOP]:
        widget = {"Models": window.models, "Data": window.data}[name]
        assert window.settings_tabs.indexOf(widget) >= 0, name
    assert window.pages.indexOf(window.help) >= 0


def test_no_screen_is_reachable_from_two_activities_by_accident(window):
    """Shared tools (Analysis, Search, Query, Modelling, Charts of themes, Reports,
    Codebook, the reader) are named in the map as shared; nothing else is."""
    shared = {"Analysis", "Charts", "Search", "Query", "Modelling", "Reports",
              "Codebook", "Documents"}
    for screen in ac.DESKTOP_SCREENS:
        owners = ac.activity_for(ac.DESKTOP, screen)
        if len(owners) > 1:
            assert screen in shared, (screen, owners)


def test_the_old_thirteen_tab_row_is_gone(window):
    from PySide6.QtWidgets import QTabWidget

    assert not isinstance(window.centralWidget(), QTabWidget)
    top_level_tabs = [w for w in window.centralWidget().findChildren(QTabWidget)
                      if w.count() >= 13]
    assert top_level_tabs == []


# ── Closing phase 1: the guide still gives usable directions, one analyst name ─

def test_the_guide_says_where_every_old_tab_went():
    from qualsafe_qt.views.help_view import HELP_SECTIONS

    first = HELP_SECTIONS[0][1]
    assert "now live inside three activities" in first
    for screen in ac.DESKTOP_SCREENS:
        assert f"**{screen}** →" in first, screen
    assert "Interviews › 1 Add transcripts" in first and "Settings › Models" in first


def test_the_analyst_name_has_one_source_in_the_general_tab_and_the_project_tab(window):
    window.data.analyst_name.setText("Ravi Menon")
    window.data.analyst_name.editingFinished.emit()
    assert window.general.name_edit.text() == "Ravi Menon"
    assert str(window._settings.value("analyst_name")) == "Ravi Menon"      # now saved
    window.general.name_edit.setText("Lee Park")
    window.general.name_button.click()
    assert window.data.analyst_name.text() == "Lee Park"
    assert window._service.analyst_name == "Lee Park"
