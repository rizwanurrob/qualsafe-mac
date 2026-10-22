"""Surveys, step 1 (Load): one main action, few controls, and nothing chosen for you."""

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import QApplication, QCheckBox, QLabel, QPushButton, QToolButton

from core.ux import words
from qualsafe_qt.services.project_service import ProjectService
from qualsafe_qt.views.pipeline_view import PipelineView
from qualsafe_qt.widgets.more_options import MAX_VISIBLE_CONTROLS, MoreOptions, visible_controls

DATA = Path(__file__).resolve().parents[1] / "data"
LONG = DATA / "sample_survey_education.csv"
WIDE = DATA / "synthetic_entering_student_survey_wide.csv"


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def view(app):
    v = PipelineView(ProjectService(), QUndoStack())
    v.resize(1300, 800)
    v.show()
    app.processEvents()
    yield v
    v.close()


def step_one(view):
    return view.tabs.widget(0)


# ── the rule: at most seven controls, one main action ───────────────────────

def test_an_empty_step_shows_few_controls_and_says_what_to_do(view):
    shown = visible_controls(step_one(view))
    assert 1 <= len(shown) <= MAX_VISIBLE_CONTROLS
    assert "Open a spreadsheet" in view.file_label.text()          # the empty state says what to do
    assert view.load_button.isVisible()                            # ...and offers the button


@pytest.mark.parametrize("path", [LONG, WIDE], ids=["long", "wide"])
def test_a_loaded_file_still_shows_at_most_seven_controls(view, app, path):
    view._load(path)
    app.processEvents()
    assert len(visible_controls(step_one(view))) <= MAX_VISIBLE_CONTROLS


def test_the_other_options_are_folded_away_until_asked_for(view, app):
    view._load(LONG)
    app.processEvents()
    folded = {view.mode, view.question_column, view.question_manual, view.id_column, view.descriptors}
    assert not view.more_options.is_expanded()
    assert all(not w.isVisibleTo(step_one(view)) for w in folded)
    before = len(visible_controls(step_one(view)))

    view.more_options.toggle.click()
    app.processEvents()
    assert view.more_options.is_expanded()
    assert all(w.isVisibleTo(step_one(view)) for w in folded)
    assert len(visible_controls(step_one(view))) == before + len(folded)    # nothing was removed

    view.more_options.toggle.click()
    app.processEvents()
    assert all(not w.isVisibleTo(step_one(view)) for w in folded)


def test_there_is_exactly_one_filled_button_on_the_step(view):
    mains = [b for b in step_one(view).findChildren(QPushButton) if b.property("main")]
    assert mains == [view.load_button]


def test_more_options_says_how_many_it_holds_and_is_a_labelled_button(view):
    assert view.more_options.toggle.text() == "More options (5)"
    assert view.more_options.toggle.accessibleName() == "More options"
    assert isinstance(view.more_options.toggle, QToolButton) and view.more_options.toggle.isCheckable()


# ── nothing is chosen for you ───────────────────────────────────────────────

def test_the_answers_column_is_suggested_but_never_pre_selected(view, app):
    view._load(LONG)
    app.processEvents()
    assert view.text_column.currentData() == ""                    # still blank
    assert view.suggestion_button.isVisible() and view.suggestion_label.isVisible()
    text = view.suggestion_label.text()
    assert "response_text" in text and "question_text" in text
    assert "Honestly the cost of everything" in text               # an example, so a wrong pick shows
    assert any("text column" in b for b in view.blockers())        # the run is still blocked


def test_one_click_fills_in_what_was_suggested_and_nothing_more(view, app):
    view._load(LONG)
    view.suggestion_button.click()
    app.processEvents()
    assert view.text_column.currentData() == "response_text"
    assert view.question_column.currentData() == "question_text"
    assert view.id_column.currentData() == "response_id"
    assert not view.suggestion_button.isVisible()
    assert "Using:" in view.suggestion_label.text()
    assert view.labels_edit.toPlainText() == ""                    # no themes made up
    assert not any("text column" in b for b in view.blockers())


def test_the_privacy_gate_is_untouched_by_the_suggestion(view, app):
    view._load(LONG)
    view.suggestion_button.click()
    assert not view.pii_confirm.isChecked() and view._confirmed_for == ""
    assert any("confirm" in b for b in view.blockers())
    view.labels_edit.setPlainText("Money")
    assert not view.run_button.isEnabled()                         # still needs the gate
    view.pii_confirm.setChecked(True)
    assert view.run_button.isEnabled()


def test_the_layout_is_worked_out_from_the_file(view, app):
    view._load(WIDE)
    app.processEvents()
    assert view.mode.currentData() == "wide"
    assert view.text_columns.isVisible() and not view.text_column.isVisible()
    assert view.text_columns.isEnabled()
    view.suggestion_button.click()
    from qualsafe_qt.views.pipeline_view import _checked
    assert len(_checked(view.text_columns)) >= 2
    assert "Q1_success" in _checked(view.text_columns)

    view._load(LONG)                                               # and back again
    app.processEvents()
    assert view.mode.currentData() == "long" and view.text_column.isVisible()


def test_a_file_with_no_written_answers_suggests_nothing(view, app, tmp_path):
    path = tmp_path / "numbers.csv"
    path.write_text("age,year\n19,1\n20,2\n21,1\n", encoding="utf-8")
    view._load(path)
    assert not view.suggestion_button.isVisible() and not view.suggestion_label.isVisible()


def test_starting_over_and_restoring_leave_no_stale_suggestion(view, app):
    view._load(LONG)
    assert view.suggestion_button.isVisible()
    view.reset_session()
    app.processEvents()
    assert not view.suggestion_button.isVisible() and "Open a spreadsheet" in view.file_label.text()
    state = {"resume_path": str(LONG), "text_column": "response_text", "ingestion_mode": "long"}
    view.restore_progress(state)
    assert view.text_column.currentData() == "response_text"
    assert not view.suggestion_button.isVisible()


def test_the_suggestion_example_is_not_saved_in_progress(view):
    view._load(LONG)
    saved = repr(view.progress_state())
    assert "Honestly" not in saved and "For example" not in saved


# ── plain words ─────────────────────────────────────────────────────────────

def test_no_banned_or_model_words_are_visible_on_the_step(view, app):
    view._load(LONG)
    view.more_options.toggle.click()
    app.processEvents()
    root = step_one(view)
    # The interface's own words. The suggestion and the scan result quote the
    # person's file (its column names, such as response_id, and a sample answer),
    # so they are checked for hype words only, not for internal-name patterns.
    from_the_file = {view.suggestion_label, view.pii_summary, view.file_label}
    texts = [w.text() for kind in (QLabel, QPushButton, QCheckBox, QToolButton)
             for w in root.findChildren(kind)
             if w.isVisibleTo(root) and w not in from_the_file]
    for shown in from_the_file:
        assert words.find_never(shown.text()) == [], shown.text()
    for text in texts:
        assert words.find_never(text) == [], text
        assert words.find_replace(text) == [], text


def test_more_options_widget_counts_rows_and_starts_closed(app):
    box = MoreOptions("More options")
    assert not box.is_expanded() and box.toggle.text() == "More options"
    from PySide6.QtWidgets import QLineEdit
    box.add_row("A", QLineEdit())
    box.add_row("B", QLineEdit())
    assert box.toggle.text() == "More options (2)"
    seen = []
    box.toggled.connect(seen.append)
    box.set_expanded(True)
    assert seen == [True] and box.is_expanded()
