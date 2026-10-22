"""Surveys, step 4 (Explore): few controls per screen, plain names, a chart on arrival."""

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import QApplication, QCheckBox, QLabel, QPushButton, QToolButton

from core.sample_project import build_sample_project
from core.ux import words
from qualsafe_qt.services.project_service import ProjectService
from qualsafe_qt.views.analysis_view import AnalysisView
from qualsafe_qt.views.charts_view import ChartsView
from qualsafe_qt.views.query_view import QueryView
from qualsafe_qt.views.search_view import SearchView
from qualsafe_qt.widgets.more_options import MAX_VISIBLE_CONTROLS, visible_controls

SAMPLE = Path(__file__).resolve().parents[1] / "data" / "sample_survey_education.csv"


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def project(tmp_path_factory):
    path = tmp_path_factory.mktemp("explore") / "sample.qnw"
    build_sample_project(SAMPLE, path)
    return path


@pytest.fixture()
def service(app, project):
    svc = ProjectService()
    svc.open(project)
    app.processEvents()
    yield svc
    svc.close()


@pytest.fixture()
def charts(app, service):
    view = ChartsView(service, QUndoStack())
    view.resize(1300, 900)
    view.show()
    app.processEvents()
    yield view
    view.close()


# ── Charts: pick a chart and see it ─────────────────────────────────────────

def test_the_charts_screen_shows_few_controls_with_or_without_a_project(app):
    view = ChartsView(ProjectService(), QUndoStack())
    view.show()
    app.processEvents()
    assert len(visible_controls(view)) <= MAX_VISIBLE_CONTROLS
    assert "Open a project" in view.canvas._message
    view.close()


def test_with_a_project_it_shows_at_most_seven_controls(charts):
    assert len(visible_controls(charts)) <= MAX_VISIBLE_CONTROLS


def test_the_builder_is_folded_away_and_nothing_was_removed(charts, app):
    folded = [charts.mark, charts.fields, charts.show_technical, charts.shelf_row,
              charts.saved_charts, charts.save_name, charts.scale,
              charts.source_codings, charts.source_descriptors]
    assert not charts.more.is_expanded()
    assert all(not w.isVisibleTo(charts) for w in folded)
    before = len(visible_controls(charts))
    charts.more.toggle.click()
    app.processEvents()
    assert all(w.isVisibleTo(charts) for w in folded)
    assert len(visible_controls(charts)) > before


def test_a_chart_is_drawn_on_arrival_without_a_click(charts):
    assert charts.suggestions.currentText() == "How often each Theme occurs"
    assert not charts._plotted.empty
    assert charts.save_image.isEnabled() and charts.save_data.isEnabled()
    assert charts.title.text() == "How often each Theme occurs"


def test_choosing_another_chart_draws_it_at_once(charts, app):
    charts.suggestions.setCurrentIndex(2)
    app.processEvents()
    assert charts.suggestions.currentText() == "Theme broken down by Coder"
    assert charts.shelf_row.assignment()["color"]["field"] == "coder"
    assert not charts._plotted.empty


def test_the_first_chart_is_about_themes_not_coders(charts):
    titles = [charts.suggestions.itemText(i) for i in range(charts.suggestions.count())]
    assert titles[0].startswith("How often each Theme")
    assert all("code_name" not in t and "_" not in t for t in titles)


def test_a_chart_built_by_hand_is_not_replaced_by_a_reload(charts, app):
    charts.shelf_row.shelves()["x"].set_field("coder")
    app.processEvents()
    assert charts.suggestions.currentIndex() == -1                 # no ready-made chart selected
    charts._service.notify_changed()                                # the project changed under it
    app.processEvents()
    assert charts.shelf_row.assignment()["x"]["field"] == "coder"   # still the person's chart
    assert charts.suggestions.currentIndex() == -1


def test_a_ready_made_chart_stays_selected_through_a_reload(charts, app):
    charts.suggestions.setCurrentIndex(1)
    charts._service.notify_changed()
    app.processEvents()
    assert charts.suggestions.currentText().startswith("Total Confidence by Theme")


def test_there_is_one_filled_button_and_it_saves_the_picture(charts):
    mains = [b for b in charts.findChildren(QPushButton) if b.property("main")]
    assert mains == [charts.save_image]


def test_a_warning_has_an_icon_and_words(charts, app):
    charts.shelf_row.shelves()["x"].clear_field()
    app.processEvents()
    assert charts._problem.text().strip() and charts._problem_icon.isVisibleTo(charts)
    assert not charts.save_image.isEnabled()
    charts.suggestions.setCurrentIndex(0)
    app.processEvents()
    assert not charts._problem_icon.isVisibleTo(charts)


# ── plain field names (UX-4) ────────────────────────────────────────────────

def _field_texts(view):
    return [view.fields.item(i).text() for i in range(view.fields.count())]


def test_the_field_list_uses_plain_names_and_hides_identifiers(charts):
    shown = _field_texts(charts)
    assert shown, "there should be fields"
    assert all("_" not in t for t in shown), shown
    assert any(t.startswith("Theme") for t in shown) and any(t.startswith("Coder") for t in shown)
    assert not any("(ID)" in t for t in shown)                      # identifiers are hidden
    assert all(t.endswith(("(category)", "(number)", "(date)", "(ordered category)")) for t in shown)


def test_identifiers_can_be_shown_on_request_and_still_have_plain_names(charts):
    charts.show_technical.setChecked(True)
    shown = _field_texts(charts)
    assert any("(ID)" in t for t in shown)
    assert all("_" not in t for t in shown), shown
    charts.show_technical.setChecked(False)
    assert not any("(ID)" in t for t in _field_texts(charts))


def test_dragging_still_sends_the_stored_name_not_the_label(charts):
    item = next(charts.fields.item(i) for i in range(charts.fields.count())
                if charts.fields.item(i).text().startswith("Theme"))
    for shelf in charts.shelf_row.shelves().values():
        shelf.clear_field()
    charts._send_to_first_empty(item)
    filled = [s for s in charts.shelf_row.shelves().values() if s.field()]
    assert [s.field() for s in filled] == ["code_name"]             # the stored name travels
    assert "Theme" in filled[0].field_label.text() and "code_name" not in filled[0].field_label.text()


def test_shelves_show_plain_names(charts):
    labels = " ".join(s.field_label.text() for s in charts.shelf_row.shelves().values())
    assert "code_name" not in labels and "Theme" in labels


def test_no_internal_name_or_banned_word_is_visible_on_the_charts_screen(charts, app):
    charts.more.toggle.click()
    app.processEvents()
    texts = [w.text() for kind in (QLabel, QPushButton, QCheckBox, QToolButton)
             for w in charts.findChildren(kind) if w.isVisibleTo(charts)]
    texts += _field_texts(charts)
    texts += [charts.suggestions.itemText(i) for i in range(charts.suggestions.count())]
    texts += [charts.mark.itemText(i) for i in range(charts.mark.count())]
    for text in texts:
        assert words.find_never(text) == [], text
        assert words.find_replace(text) == [], text


def test_the_respondent_detail_fields_are_tidied_not_hidden(charts, app):
    charts.source_descriptors.setChecked(True)
    app.processEvents()
    shown = _field_texts(charts)
    assert shown and all("_" not in t for t in shown), shown


# ── the saved place for charts of results is unchanged ──────────────────────

def test_a_chart_can_still_be_kept_with_the_project(charts, app):
    charts.save_name.setText("Themes this term")
    charts.save_chart.click()
    app.processEvents()
    assert [charts.saved_charts.itemText(i) for i in range(charts.saved_charts.count())] == [
        "Themes this term"]


# ── Analysis: plain tab names, in the order the questions are asked ─────────

def test_the_analysis_tabs_are_plain_and_in_reading_order(service, app):
    view = AnalysisView(service, QUndoStack())
    names = [view.tabs.tabText(i) for i in range(view.tabs.count())]
    assert names == ["How often", "By group", "Together", "Agreement (Cohen's κ)", "More: Network",
                     "More: Deviant cases", "More: Saturation"]
    for name in names:
        assert words.find_replace(name) == [], name


# ── Search and Query: the rest of the step ──────────────────────────────────

def test_search_shows_at_most_seven_controls_with_the_options_folded(service, app):
    view = SearchView(service, QUndoStack())
    view.resize(1300, 900)
    view.show()
    app.processEvents()
    page = view.tabs.widget(0)
    assert len(visible_controls(page)) <= MAX_VISIBLE_CONTROLS
    folded = [view.mode, view.whole_word, view.match_case, view.type_filter, view.case_filter,
              view.code_filter, view.limit, view.autocode_name, view.autocode_button,
              view.undo_pick, view.undo_button]
    assert not view.search_more.is_expanded()
    assert all(not w.isVisibleTo(page) for w in folded)
    view.search_more.toggle.click()
    app.processEvents()
    assert all(w.isVisibleTo(page) for w in folded)                 # nothing was removed
    assert [b for b in page.findChildren(QPushButton) if b.property("main")] == [view.search_button]
    view.close()


def test_search_still_finds_and_the_plain_search_type_names_are_used(service, app):
    view = SearchView(service, QUndoStack())
    view.show()
    assert [view.mode.itemText(i) for i in range(view.mode.count())] == [
        "Words as typed", "A pattern (for advanced searches)"]
    assert [view.mode.itemData(i) for i in range(view.mode.count())] == ["text", "regex"]
    view.query_edit.setText("cost")
    view.run_search()
    app.processEvents()
    assert view.hits_tree.topLevelItemCount() > 0
    view.close()


def test_query_stays_within_seven_controls(service, app):
    view = QueryView(service, QUndoStack())
    view.resize(1300, 900)
    view.show()
    app.processEvents()
    assert len(visible_controls(view)) <= MAX_VISIBLE_CONTROLS
    view.close()


# ── value labels on the bars are readable ───────────────────────────────────

@pytest.mark.parametrize("mode", ["dark", "light"])
def test_a_bars_value_is_readable_on_every_colour_the_charts_use(mode):
    from PySide6.QtGui import QColor

    from core import theme
    from qualsafe_qt.widgets.chart_canvas import readable_on
    from tests.test_ux_colours import contrast

    for colour in theme.get_palette(mode)["category"]:
        text = readable_on(QColor(colour)).name()
        assert contrast(text, colour) >= 4.5, (mode, colour, text)


# ── agreement: folded, not changed (κ-only, locked) ─────────────────────────

def test_every_analysis_tab_shows_at_most_seven_controls(service, app):
    view = AnalysisView(service, QUndoStack())
    view.resize(1300, 900)
    view.show()
    app.processEvents()
    for i in range(view.tabs.count()):
        view.tabs.setCurrentIndex(i)
        app.processEvents()
        page = view.tabs.widget(i)
        assert len(visible_controls(page)) <= MAX_VISIBLE_CONTROLS, view.tabs.tabText(i)
    view.close()


def test_the_agreement_tab_folds_the_reconciling_and_keeps_the_kappa_rules(service, app):
    view = AnalysisView(service, QUndoStack())
    view.resize(1300, 900)
    view.show()
    view.tabs.setCurrentIndex(3)
    app.processEvents()
    page = view.tabs.widget(3)
    assert not view.reconcile_more.is_expanded()
    assert not view.disagreement_list.isVisibleTo(page)
    view.reconcile_more.toggle.click()
    app.processEvents()
    assert view.disagreement_list.isVisibleTo(page)                  # nothing was removed
    text = " ".join(w.text() for w in page.findChildren(QLabel))
    # The locked rules stay on the screen: per-code Cohen's κ, beside percent agreement
    # and prevalence; coders are people, the engine has its own mode.
    assert "Cohen's κ" in text and "percent agreement" in text and "prevalence" in text
    assert "coder vs engine" in text
    assert "Fewest answers per theme" in text and "Min. support" not in text
    view.close()
