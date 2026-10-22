"""Surveys, step 2 (Themes): write your themes or start from a ready-made set."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import QApplication, QCheckBox, QLabel, QMessageBox, QPushButton, QToolButton

from core.model import Code
from core.project import Project
from core.ux import words
from qualsafe_qt.services.project_service import ProjectService
from qualsafe_qt.views.pipeline_view import PipelineView
from qualsafe_qt.widgets.more_options import MAX_VISIBLE_CONTROLS, visible_controls


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def view(app):
    v = PipelineView(ProjectService(), QUndoStack())
    v.resize(1300, 800)
    v.tabs.setCurrentIndex(1)
    v.show()
    app.processEvents()
    yield v
    v.close()


def step(view):
    return view.tabs.widget(1)


def _project_with_codes(tmp_path, names):
    path = tmp_path / "p.qnw"
    with Project.create(path) as proj:
        for name in names:
            proj.add_code(Code(code_id="", name=name, definition=""))
    return path


# ── few controls, one main action ───────────────────────────────────────────

def test_the_step_shows_at_most_seven_controls_and_the_rare_one_is_folded(view, app):
    shown = visible_controls(step(view))
    assert 1 <= len(shown) <= MAX_VISIBLE_CONTROLS
    assert not view.themes_more.is_expanded() and not view.per_question.isVisibleTo(step(view))
    view.themes_more.toggle.click()
    app.processEvents()
    assert view.per_question.isVisibleTo(step(view))
    assert len(visible_controls(step(view))) == len(shown) + 1       # nothing was removed


def test_exactly_one_filled_button(view):
    mains = [b for b in step(view).findChildren(QPushButton) if b.property("main")]
    assert mains == [view.pack_button]


def test_the_per_question_box_still_feeds_the_run(view):
    view.per_question.setPlainText("What was hardest? :: Cost | Belonging")
    assert view.settings().per_question_labels_text == "What was hardest? :: Cost | Belonging"


# ── the empty state and the count ───────────────────────────────────────────

def test_an_empty_list_says_what_to_do(view):
    assert "Write one per line" in view.labels_summary.text()
    assert "ready-made set" in view.labels_summary.text()


@pytest.mark.parametrize("text,expected", [("Money", "1 theme."), ("Money\nTime", "2 themes."),
                                           ("Money\n\n  \nTime\nBelonging", "3 themes.")])
def test_the_count_is_plain_and_ignores_blank_lines(view, text, expected):
    view.labels_edit.setPlainText(text)
    assert expected in view.labels_summary.text()


# ── ready-made sets ─────────────────────────────────────────────────────────

def test_a_set_is_previewed_before_it_is_used_and_can_be_edited_after(view, app):
    view.showEvent(None) if view.pack_pick.count() == 0 else None
    app.processEvents()
    assert view.pack_pick.count() > 0
    labels = view.pack_pick.currentData()
    assert f"{len(labels)} themes" in view.pack_preview.text()
    assert labels[0] in view.pack_preview.text()
    assert view.labels_edit.toPlainText() == ""                    # previewing changes nothing

    view.pack_button.click()
    assert view.labels_edit.toPlainText().split("\n") == list(labels)
    view.labels_edit.appendPlainText("My own theme")                # still editable
    assert view.labels_edit.toPlainText().endswith("My own theme")


def test_the_preview_follows_the_choice(view, app):
    if view.pack_pick.count() < 2:
        pytest.skip("needs two sets")
    view.pack_pick.setCurrentIndex(0)
    first = view.pack_preview.text()
    view.pack_pick.setCurrentIndex(1)
    assert view.pack_preview.text() != first


# ── the project's own codes ─────────────────────────────────────────────────

def test_with_no_project_the_button_is_off_and_says_why_without_a_pop_up(view, monkeypatch):
    monkeypatch.setattr(QMessageBox, "information",
                        lambda *a, **k: pytest.fail("no pop-up: the note says why"))
    assert not view.codebook_button.isEnabled()
    assert "No project is open" in view.codebook_note.text()
    view.codebook_button.click()                                    # a disabled button does nothing
    view._labels_from_codebook()                                    # and a direct call is safe too
    assert view.labels_edit.toPlainText() == ""


def test_a_project_with_no_codes_says_so(view, tmp_path):
    view._service.open(_project_with_codes(tmp_path, []))
    assert not view.codebook_button.isEnabled()
    assert "no codes yet" in view.codebook_note.text()


def test_a_project_with_codes_offers_them_and_they_fill_the_box(view, tmp_path):
    view._service.open(_project_with_codes(tmp_path, ["Money", "Time", "Belonging"]))
    assert view.codebook_button.isEnabled()
    assert "3 codes" in view.codebook_note.text()
    view.codebook_button.click()
    assert view.labels_edit.toPlainText().split("\n") == ["Belonging", "Money", "Time"]


def test_the_button_follows_the_project_closing(view, tmp_path):
    view._service.open(_project_with_codes(tmp_path, ["Money"]))
    assert view.codebook_button.isEnabled()
    view._service.close()
    assert not view.codebook_button.isEnabled()


# ── plain words ─────────────────────────────────────────────────────────────

def test_no_banned_or_model_words_on_the_step(view, app):
    view.themes_more.toggle.click()
    app.processEvents()
    root = step(view)
    texts = [w.text() for kind in (QLabel, QPushButton, QCheckBox, QToolButton)
             for w in root.findChildren(kind) if w.isVisibleTo(root)]
    texts += [view.pack_pick.itemText(i) for i in range(0)]
    for text in texts:
        assert words.find_never(text) == [], text
        assert words.find_replace(text) == [], text
    assert "model" not in " ".join(texts).lower()


# ── Start over and saved places still reach this step ───────────────────────

def test_start_over_clears_the_themes_and_the_extra_box(view):
    view.labels_edit.setPlainText("Money")
    view.per_question.setPlainText("Q :: A | B")
    view.reset_session()
    assert view.labels_edit.toPlainText() == "" and view.per_question.toPlainText() == ""
    assert "Write one per line" in view.labels_summary.text()


def test_the_saved_place_keeps_the_themes(view):
    view.labels_edit.setPlainText("Money\nTime")
    state = view.progress_state()
    assert state["theme_labels_text"] == "Money\nTime"
    view.reset_session()
    view.restore_progress(state)
    assert view.labels_edit.toPlainText() == "Money\nTime"
