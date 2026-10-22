"""Progress per activity: where a person was, saved and put back.

The rules under test (HANDOFF section 5): the privacy gate is asked again on
every load and never saved; nothing derived from a response goes into the
progress file; a missing file is reported, not crashed on.
"""

import csv
import json
import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from core.documents import add_document
from core.project import Project
from core.ux import progress
from qualsafe_qt.windows.main_window import MainWindow

SAMPLE = Path(__file__).resolve().parents[1] / "data" / "sample_survey_education.csv"


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def windows(app):
    """Make windows; close them all afterwards."""
    made = []

    def make():
        win = MainWindow()
        win.resize(1200, 800)
        win.show()
        app.processEvents()
        made.append(win)
        return win

    yield make
    for win in made:
        win.close()


def _raw() -> str:
    return progress.progress_path().read_text(encoding="utf-8")


def _answers() -> list:
    with open(SAMPLE, newline="", encoding="utf-8") as handle:
        return [row["response_text"] for row in csv.DictReader(handle)]


# ── Switching activity and coming back ───────────────────────────────────────

def test_coming_back_to_an_activity_opens_the_step_you_left(windows):
    win = windows()
    win.open_activity("surveys", "explore")
    win.open_activity("charts")
    win.open_activity("interviews", "codebook")
    win.open_activity("surveys")
    assert (win.activity.activity_key, win.activity.step_key) == ("surveys", "explore")
    win.open_activity("interviews")
    assert win.activity.step_key == "codebook"


def test_the_place_is_written_when_you_leave(windows):
    win = windows()
    win.open_activity("surveys", "code")
    win.go_home()
    saved = progress.load("surveys")
    assert saved["step"] == "code"


def test_each_activity_keeps_its_own_place(windows):
    win = windows()
    win.open_activity("surveys", "themes")
    win.open_activity("charts", "adjust")
    win.go_home()
    assert progress.load("surveys")["step"] == "themes"
    assert progress.load("charts")["step"] == "adjust"
    assert progress.load("interviews") is None


def test_nothing_is_written_again_when_nothing_changed(windows, monkeypatch):
    win = windows()
    win.open_activity("surveys", "code")
    calls = []
    real = progress.save
    monkeypatch.setattr(progress, "save", lambda *a, **k: calls.append(a) or real(*a, **k))
    win.save_progress()
    win.save_progress()
    assert calls == []


def test_a_timer_saves_every_thirty_seconds_and_stops_with_the_window(windows):
    win = windows()
    assert win._progress_timer.interval() == 30_000 and win._progress_timer.isActive()
    win.close()
    assert not win._progress_timer.isActive()


def test_a_failed_write_never_gets_in_the_way(windows, monkeypatch):
    win = windows()
    monkeypatch.setattr(progress, "save", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    win.open_activity("surveys", "code")
    win.go_home()          # must not raise
    assert win.pages.currentWidget() is win.home


# ── Surveys: file, columns, themes; the gate comes back ──────────────────────

def _set_up_survey(win):
    win.open_activity("surveys", "themes")
    win.pipeline._load(SAMPLE)
    for combo, key in ((win.pipeline.text_column, "response_text"),
                       (win.pipeline.question_column, "question_text"),
                       (win.pipeline.id_column, "response_id")):
        combo.setCurrentIndex(combo.findData(key))
    win.pipeline.labels_edit.setPlainText("Financial concerns\nSense of belonging")
    win.pipeline.pii_confirm.setChecked(True)          # the person ticked the gate
    assert win.pipeline._confirmed_for == str(SAMPLE)


def test_a_survey_comes_back_with_its_file_columns_and_themes(windows):
    first = windows()
    _set_up_survey(first)
    first.go_home()
    first.close()

    second = windows()
    assert second.restore_progress("surveys") == []
    p = second.pipeline
    assert (second.activity.activity_key, second.activity.step_key) == ("surveys", "themes")
    assert p._loaded_from == str(SAMPLE)
    assert p.text_column.currentData() == "response_text"
    assert p.question_column.currentData() == "question_text"
    assert p.id_column.currentData() == "response_id"
    assert p.labels_edit.toPlainText() == "Financial concerns\nSense of belonging"


def test_the_privacy_gate_is_asked_again_after_coming_back(windows):
    first = windows()
    _set_up_survey(first)
    first.go_home()
    first.close()
    assert "pii" not in _raw().lower() and "privacy" not in _raw().lower()

    second = windows()
    second.restore_progress("surveys")
    assert not second.pipeline.pii_confirm.isChecked()
    assert second.pipeline._confirmed_for == ""
    assert not second.pipeline.run_button.isEnabled()      # cannot run until it is ticked


def test_no_response_text_reaches_the_progress_file(windows):
    win = windows()
    _set_up_survey(win)
    win.go_home()
    raw = _raw()
    assert progress.load("surveys")["state"]["resume_path"] == str(SAMPLE)
    for answer in _answers():
        assert answer[:40] not in raw
    # The preview, the scan summary and the file label are on screen but not saved.
    assert "row(s)" not in raw


def test_a_missing_survey_file_is_reported_and_the_themes_still_come_back(windows, tmp_path):
    copy = tmp_path / "answers.csv"
    copy.write_bytes(SAMPLE.read_bytes())
    first = windows()
    first.open_activity("surveys", "themes")
    first.pipeline._load(copy)
    first.pipeline.labels_edit.setPlainText("Money")
    first.go_home()
    first.close()
    copy.unlink()

    second = windows()
    assert second.restore_progress("surveys") == [str(copy)]
    assert second.pipeline.labels_edit.toPlainText() == "Money"
    assert second.pipeline._loaded_from == ""


def test_the_explore_tab_you_were_on_comes_back(windows):
    first = windows()
    first.open_activity("surveys", "explore")
    first.activity.show_named_screen("Search")
    first.go_home()
    first.close()
    second = windows()
    second.restore_progress("surveys")
    assert second.activity.current_screen() == "Search"


# ── Charts ───────────────────────────────────────────────────────────────────

@pytest.fixture()
def spreadsheet(tmp_path):
    from core.chartbuilder.sample import sample_frame

    path = tmp_path / "survey.csv"
    sample_frame(60).to_csv(path, index=False)
    return path


def test_a_chart_comes_back_with_its_file_question_and_title(windows, spreadsheet):
    first = windows()
    first.open_activity("charts")
    first.data_charts.open_path(str(spreadsheet))
    first.data_charts._cfg.column = "Class year"
    first.data_charts._cfg.labels.title = "Where our students are"
    first.data_charts._sync_from_cfg()
    first.go_home()
    first.close()

    second = windows()
    assert second.restore_progress("charts") == []
    view = second.data_charts
    assert str(view._sheet_source) == str(spreadsheet)
    assert view.config().column == "Class year"
    assert view.config().labels.title == "Where our students are"


def test_the_spreadsheet_contents_are_not_saved(windows, spreadsheet):
    import pandas as pd

    first = windows()
    first.open_activity("charts")
    first.data_charts.open_path(str(spreadsheet))
    first.data_charts._cfg.column = "Class year"
    first.go_home()
    raw = _raw()
    frame = pd.read_csv(spreadsheet)
    for value in frame["Class year"].dropna().astype(str).unique():
        assert value not in raw, value
    saved = progress.load("charts")["state"]
    assert set(saved) <= {"file_path", "question", "chart_type", "chart_settings"}


def test_the_built_in_sample_has_no_saved_file(windows):
    win = windows()
    win.open_activity("charts")
    win.data_charts.load_sample()
    assert win.data_charts.progress_state() == {}


def test_a_missing_chart_file_is_reported(windows, spreadsheet):
    first = windows()
    first.open_activity("charts")
    first.data_charts.open_path(str(spreadsheet))
    first.go_home()
    first.close()
    spreadsheet.unlink()
    second = windows()
    assert second.restore_progress("charts") == [str(spreadsheet)]


# ── Interviews ───────────────────────────────────────────────────────────────

TRANSCRIPT = "Interviewer: How was your first term?\n\nStudent: " + (
    "The cost of everything surprised me. " * 40)


def _transcripts(tmp_path):
    path = tmp_path / "talks.qnw"
    with Project.create(path) as proj:
        add_document(proj, "Interview 01", TRANSCRIPT)
        add_document(proj, "Interview 02", TRANSCRIPT + " More.")
    return path


def test_an_interview_comes_back_on_the_same_document(windows, tmp_path):
    path = _transcripts(tmp_path)
    first = windows()
    first._service.open(path)
    first.open_activity("interviews", "code")
    first.documents.library.selectRow(1)
    first.app_processed = None
    chosen = first.documents._source_id
    assert chosen
    first.go_home()
    first.close()

    second = windows()
    assert second.restore_progress("interviews") == []
    assert str(second._service.path) == str(path)
    assert second.documents._source_id == chosen
    assert second.activity.step_key == "code"


def test_no_transcript_text_reaches_the_progress_file(windows, tmp_path):
    first = windows()
    first._service.open(_transcripts(tmp_path))
    first.open_activity("interviews", "code")
    first.documents.library.selectRow(0)
    first.go_home()
    raw = _raw()
    assert "cost of everything" not in raw and "Interviewer" not in raw


def test_a_missing_project_is_reported(windows, tmp_path):
    path = _transcripts(tmp_path)
    first = windows()
    first._service.open(path)
    first.open_activity("interviews", "code")
    first.go_home()
    first.close()
    path.unlink()
    second = windows()
    assert second.restore_progress("interviews") == [str(path)]


def test_restoring_something_never_saved_does_nothing(windows):
    win = windows()
    assert win.restore_progress("surveys") == []
    assert win.pages.currentWidget() is win.home


def test_a_step_remembers_which_of_its_screens_you_were_on(windows):
    win = windows()
    win.open_activity("surveys", "explore")
    win.activity.show_named_screen("Search")
    win.open_activity("charts")
    win.open_activity("surveys")
    assert win.activity.current_screen() == "Search"
    # Another step of the same activity does not borrow it, and the first keeps it.
    win.activity.rail._buttons["report"].click()
    win.activity.rail._buttons["explore"].click()
    assert win.activity.current_screen() == "Search"


def test_the_remembered_screen_is_what_gets_saved(windows):
    win = windows()
    win.open_activity("surveys", "explore")
    win.activity.show_named_screen("Search")
    win.open_activity("charts")
    win.open_activity("surveys")
    win.go_home()
    assert progress.load("surveys")["state"]["explore_tab"] == "Search"


# ── Continue on Home ─────────────────────────────────────────────────────────

def test_home_offers_continue_for_a_saved_survey_and_nothing_for_the_rest(windows):
    first = windows()
    _set_up_survey(first)
    first.go_home()
    first.close()

    second = windows()                       # a new launch: Home reads the saved file
    home = second.home
    assert not home.continue_boxes["surveys"].isHidden()
    assert home.continue_titles["surveys"].text() == "Continue: sample_survey_education.csv"
    assert "Step 1 of 5" in home.continue_details["surveys"].text() or \
        "Step 2 of 5" in home.continue_details["surveys"].text()
    assert home.continue_buttons["surveys"].text() == "Continue"
    assert home.continue_boxes["charts"].isHidden() and home.continue_boxes["interviews"].isHidden()


def test_the_continue_line_never_shows_a_path_or_any_text_from_the_data(windows):
    first = windows()
    _set_up_survey(first)
    first.go_home()
    shown = (first.home.continue_titles["surveys"].text()
             + first.home.continue_details["surveys"].text())
    assert str(SAMPLE.parent) not in shown
    for answer in _answers():
        assert answer[:30] not in shown


def test_continue_puts_the_survey_back(windows):
    first = windows()
    _set_up_survey(first)
    first.go_home()
    first.close()
    second = windows()
    second.home.continue_buttons["surveys"].click()
    assert second.pages.currentWidget() is second.activity
    assert second.pipeline._loaded_from == str(SAMPLE)
    assert not second.pipeline.pii_confirm.isChecked()               # asked again


def test_a_missing_file_says_so_with_an_icon_and_words_and_offers_to_find_it(windows, tmp_path):
    spreadsheet = tmp_path / "Q7.csv"
    spreadsheet.write_text("Class year\nFreshman\n", encoding="utf-8")
    first = windows()
    first.open_activity("charts")
    first.data_charts.open_path(str(spreadsheet))
    first.go_home()
    first.close()
    spreadsheet.unlink()

    second = windows()
    home = second.home
    assert "File not found" in home.continue_warnings["charts"].text()
    assert "Q7.csv" in home.continue_warnings["charts"].text()
    assert not home._warning_rows["charts"].isHidden()
    assert home.continue_buttons["charts"].text() == "Find it…"


def test_find_it_points_the_saved_place_at_the_moved_file_and_continues(windows, tmp_path, monkeypatch):
    from qualsafe_qt.windows import main_window as module

    original = tmp_path / "Q7.csv"
    original.write_text("Class year\nFreshman\nSophomore\n", encoding="utf-8")
    first = windows()
    first.open_activity("charts")
    first.data_charts.open_path(str(original))
    first.go_home()
    first.close()
    moved = tmp_path / "archive" / "Q7.csv"
    moved.parent.mkdir()
    original.rename(moved)

    second = windows()
    asked = []
    monkeypatch.setattr(module.QFileDialog, "getOpenFileName",
                        lambda *a, **k: (asked.append(a[1]) or str(moved), ""))
    second.home.continue_buttons["charts"].click()
    assert asked == ["Find Q7.csv"]
    assert str(second.data_charts._sheet_source) == str(moved)
    assert second.pages.currentWidget() is second.activity
    assert progress.summary("charts").missing == ()


def test_giving_up_on_find_it_changes_nothing(windows, tmp_path, monkeypatch):
    from qualsafe_qt.windows import main_window as module

    gone = tmp_path / "Q7.csv"
    gone.write_text("Class year\nFreshman\n", encoding="utf-8")
    first = windows()
    first.open_activity("charts")
    first.data_charts.open_path(str(gone))
    first.go_home()
    first.close()
    gone.unlink()
    second = windows()
    monkeypatch.setattr(module.QFileDialog, "getOpenFileName", lambda *a, **k: ("", ""))
    second.home.continue_buttons["charts"].click()
    assert second.pages.currentWidget() is second.home
    assert progress.summary("charts").missing == (str(gone),)
    assert second.home.continue_buttons["charts"].text() == "Find it…"


def test_leaving_an_activity_updates_the_continue_line_straight_away(windows):
    win = windows()
    _set_up_survey(win)
    assert win.home.continue_boxes["surveys"].isHidden()      # nothing left behind yet
    win.go_home()
    assert not win.home.continue_boxes["surveys"].isHidden()


# ── Start over ───────────────────────────────────────────────────────────────

def _two_saved_places(win, tmp_path):
    """Surveys with a loaded file and a theme list, Charts with a spreadsheet."""
    spreadsheet = tmp_path / "Q7.csv"
    spreadsheet.write_text("Class year\nFreshman\nSophomore\n", encoding="utf-8")
    _set_up_survey(win)
    win.open_activity("charts")
    win.data_charts.open_path(str(spreadsheet))
    win.go_home()
    return spreadsheet


def test_start_over_forgets_this_activity_and_leaves_the_others(windows, tmp_path, monkeypatch):
    win = windows()
    _two_saved_places(win, tmp_path)
    monkeypatch.setattr(win, "_confirm_start_over", lambda key: True)
    win.home.start_over_buttons["surveys"].click()
    assert progress.load("surveys") is None
    assert progress.load("charts") is not None
    assert win.home.continue_boxes["surveys"].isHidden()
    assert not win.home.continue_boxes["charts"].isHidden()


def test_start_over_clears_the_screen_too_and_the_privacy_gate(windows, tmp_path, monkeypatch):
    win = windows()
    _two_saved_places(win, tmp_path)
    monkeypatch.setattr(win, "_confirm_start_over", lambda key: True)
    win.home.start_over_buttons["surveys"].click()
    p = win.pipeline
    assert p._loaded_from == "" and p._frame is None and p._confirmed_for == ""
    assert p.labels_edit.toPlainText() == "" and p.text_column.currentData() in ("", None)
    assert not p.pii_confirm.isChecked() and not p.run_button.isEnabled()
    assert win.data_charts._table is not None            # Charts untouched


def test_start_over_in_charts_and_interviews(windows, tmp_path, monkeypatch):
    win = windows()
    spreadsheet = _two_saved_places(win, tmp_path)
    win._service.open(_transcripts(tmp_path))
    win.open_activity("interviews", "code")
    win.documents.library.selectRow(0)
    win.go_home()
    monkeypatch.setattr(win, "_confirm_start_over", lambda key: True)

    win.home.start_over_buttons["charts"].click()
    assert win.data_charts._table is None and win.data_charts.progress_state() == {}
    assert progress.load("charts") is None and spreadsheet.exists()

    win.home.start_over_buttons["interviews"].click()
    assert win.documents._source_id == "" and progress.load("interviews") is None
    assert win._service.is_open                           # the project stays open


def test_start_over_never_touches_files_or_the_open_project(windows, tmp_path, monkeypatch):
    win = windows()
    spreadsheet = _two_saved_places(win, tmp_path)
    project = _transcripts(tmp_path)
    win._service.open(project)
    win.open_activity("interviews", "code")
    win.documents.library.selectRow(0)
    win.go_home()
    sizes = {p: p.stat().st_size for p in (SAMPLE, spreadsheet, project)}
    monkeypatch.setattr(win, "_confirm_start_over", lambda key: True)
    for key in ("surveys", "charts", "interviews"):
        win.home.start_over_buttons[key].click()
    assert {p: p.stat().st_size for p in sizes} == sizes
    assert win._service.is_open and str(win._service.path) == str(project)


def test_keeping_your_place_changes_nothing(windows, tmp_path, monkeypatch):
    win = windows()
    _two_saved_places(win, tmp_path)
    monkeypatch.setattr(win, "_confirm_start_over", lambda key: False)
    win.home.start_over_buttons["surveys"].click()
    assert progress.load("surveys") is not None
    assert win.pipeline._loaded_from == str(SAMPLE)
    assert not win.home.continue_boxes["surveys"].isHidden()


def test_start_over_means_start_at_the_first_step_with_no_remembered_tab(windows, tmp_path, monkeypatch):
    win = windows()
    win.open_activity("surveys", "explore")
    win.activity.show_named_screen("Search")
    win.pipeline._load(SAMPLE)
    win.go_home()
    monkeypatch.setattr(win, "_confirm_start_over", lambda key: True)
    win.home.start_over_buttons["surveys"].click()
    win.open_activity("surveys")
    assert win.activity.step_key == "load"
    win.open_activity("surveys", "explore")
    assert win.activity.current_screen() == "Analysis"


def test_a_started_over_activity_is_not_saved_back_by_the_timer(windows, tmp_path, monkeypatch):
    win = windows()
    _two_saved_places(win, tmp_path)
    monkeypatch.setattr(win, "_confirm_start_over", lambda key: True)
    win.home.start_over_buttons["surveys"].click()
    win.save_progress()
    win._progress_timer.timeout.emit()
    assert progress.load("surveys") is None
    assert "surveys" not in _raw()


def test_the_question_says_what_is_forgotten_and_that_files_are_safe(windows, monkeypatch):
    win = windows()
    for key, phrase in (("surveys", "theme list"), ("charts", "chart choices"),
                        ("interviews", "which document")):
        box, start = win._start_over_box(key)
        text = box.text() + " " + box.informativeText()
        assert phrase in text
        assert "files and projects are not changed" in text
        assert box.defaultButton() is not start            # the safe choice is the default
        assert start.text() == "Start over"
        box.deleteLater()


def test_start_over_is_offered_only_where_there_is_something_to_forget(windows):
    win = windows()
    assert all(win.home.continue_boxes[k].isHidden() for k in win.home.continue_boxes)
    _set_up_survey(win)
    win.go_home()
    assert not win.home.start_over_buttons["surveys"].isHidden() or \
        not win.home.continue_boxes["surveys"].isHidden()
    assert win.home.continue_boxes["charts"].isHidden()
