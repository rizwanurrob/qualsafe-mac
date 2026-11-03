"""Review answers by theme: always there on the Explore step, for every way of coding."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPushButton

from core import review_browse as rb
from core.ux import activities
from qualsafe_qt.services.project_service import ProjectService
from qualsafe_qt.views.review_view import ReviewView
from qualsafe_qt.widgets.more_options import MAX_VISIBLE_CONTROLS, visible_controls

from tests.test_qt_analysis import coded_project, qapp  # noqa: F401  (fixtures)


@pytest.fixture()
def service(qapp, coded_project):  # noqa: F811
    svc = ProjectService()
    svc.open(coded_project)
    yield svc
    svc.close()


@pytest.fixture()
def view(qapp, service):  # noqa: F811
    v = ReviewView(service)
    v.resize(1000, 600)
    v.show()
    qapp.processEvents()
    yield v
    v.close()


def test_review_is_the_first_screen_of_the_surveys_explore_step_on_the_desktop():
    step = activities.get("surveys").step("explore")
    assert step.screens[activities.DESKTOP][0] == "Review"
    assert "Review" in activities.DESKTOP_SCREENS
    assert activities.unplaced_screens(activities.DESKTOP) == ()


def test_every_theme_that_was_applied_is_listed_with_its_count(view, service):
    table = rb.browse_table(service.project)
    names = {view.themes.item(i).text().rsplit(" (", 1)[0] for i in range(1, view.themes.count())}
    assert names == set(table["theme"])
    assert view.themes.item(0).text().startswith("All themes (")


def test_picking_a_theme_shows_only_its_answers_and_all_themes_shows_every_row(view, service):
    table = rb.browse_table(service.project)
    assert view.answers.rowCount() == len(table)
    view.themes.setCurrentRow(1)
    theme = view.current_theme()
    assert theme and view.answers.rowCount() == len(table[table["theme"] == theme])


def test_it_says_scores_are_not_probabilities_and_has_the_shortcut(view):
    assert "not a probability" in view.headline.text()
    assert view.review_button.text() == "Review what it was unsure about"


def test_the_shortcut_signal_fires(view, qapp):
    seen = []
    view.review_unsure_requested.connect(lambda: seen.append(1))
    view.review_button.click()
    assert seen == [1]


def test_saving_the_list_writes_a_guarded_spreadsheet(view, monkeypatch, tmp_path):
    out = tmp_path / "list.csv"
    monkeypatch.setattr(view, "_ask_save_path", lambda default: str(out))
    assert view.save_list() == str(out)
    text = out.read_text(encoding="utf-8")
    assert text.splitlines()[0].startswith("theme,answer_id,answer,score")


def test_a_project_with_nothing_coded_says_so_and_saves_nothing(qapp, tmp_path):
    from core.project import Project
    path = tmp_path / "bare.qnw"
    with Project.create(path):
        pass
    svc = ProjectService()
    svc.open(path)
    try:
        v = ReviewView(svc)
        assert "No answer has a theme yet" in v.headline.text()
        assert not v.save_button.isEnabled()
    finally:
        svc.close()


def test_the_screen_keeps_to_seven_controls(view):
    assert len(visible_controls(view)) <= MAX_VISIBLE_CONTROLS


def test_the_main_window_wires_the_shortcut_to_the_review_stage(qapp, monkeypatch):
    from qualsafe_qt.windows.main_window import MainWindow
    monkeypatch.setenv("QUALSAFE_NO_TOUR", "1")
    win = MainWindow()
    try:
        win.review.review_button.click()
        assert win.activity.step_key == "code"
        assert win.pipeline.written.current_stage() == "review"
    finally:
        win.close()
