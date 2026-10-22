"""Coding survey answers by hand on the desktop (Surveys, step 3, third choice)."""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QThreadPool
from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QGroupBox, QLabel, QPushButton, QToolButton)

from core import hand_coding as hc
from core.model import Code
from core.project import Project
from core.ux import progress, words
from qualsafe_qt.services.project_service import ProjectService
from qualsafe_qt.views.answers_view import PAGE, HandCodingView
from qualsafe_qt.views.pipeline_view import PipelineView
from qualsafe_qt.widgets.more_options import MAX_VISIBLE_CONTROLS, visible_controls

SAMPLE = Path(__file__).resolve().parents[1] / "data" / "sample_survey_education.csv"
FRAME = pd.DataFrame({
    "id": [f"r{n}" for n in range(1, 7)],
    "answer": ["Cost of books is huge", "Made friends late", "Too many hours at work",
               "Advisor helped a lot", "Rent is high", "Nothing major"],
})


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def settle(app):
    for _ in range(5):
        QThreadPool.globalInstance().waitForDone(60000)
        app.processEvents()


@pytest.fixture()
def service(app, tmp_path):
    svc = ProjectService()
    path = tmp_path / "p.qnw"
    with Project.create(path) as proj:
        proj.add_code(Code(code_id="", name="Money"))
        proj.add_code(Code(code_id="", name="Belonging"))
    svc.open(path)
    svc.set_analyst_name("Test Analyst")
    yield svc
    svc.close()


def make_view(app, service, tmp_path, frame=FRAME):
    v = HandCodingView(service, output_root=lambda: tmp_path / "out")
    v.resize(1100, 800)
    v.show()
    v.set_source(frame, "answer", "id")
    v.begin()
    settle(app)
    return v


@pytest.fixture()
def view(app, service, tmp_path):
    v = make_view(app, service, tmp_path)
    yield v
    v.close()


def mains(v):
    return [b for b in v.findChildren(QPushButton) if b.property("main") and b.isVisibleTo(v)]


def code_item(v, name):
    return next(v.codes_list.item(i) for i in range(v.codes_list.count())
                if v.codes_list.item(i).data(0x0100) == name)


# ── getting started ─────────────────────────────────────────────────────────

def test_without_answers_it_says_what_to_do_and_offers_nothing_to_click(app, service):
    v = HandCodingView(service)
    v.show()
    assert "privacy check" in v.message.text()
    assert not v.save_button.isEnabled() and not v.search_edit.isEnabled()


def test_the_answers_are_put_in_the_project_and_listed(view, service):
    assert view.answers_tree.topLevelItemCount() == 6
    assert service.project.count_sources(hc.SURVEY) == 6
    assert "0 of 6" in view.progress_label.text()
    assert view.answer_label.text()                        # the first answer is showing


def test_a_project_is_made_when_none_is_open(app, tmp_path):
    svc = ProjectService()
    v = make_view(app, svc, tmp_path)
    assert svc.is_open and v.answers_tree.topLevelItemCount() == 6
    svc.close()


# ── few controls, one main button ───────────────────────────────────────────

def test_it_shows_at_most_seven_controls_and_one_filled_button(view, app):
    app.processEvents()
    assert len(visible_controls(view)) <= MAX_VISIBLE_CONTROLS, \
        [(type(w).__name__, getattr(w, "text", lambda: "")()) for w in visible_controls(view)]
    assert mains(view) == [view.save_button]


def test_the_extra_options_are_folded_and_still_there(view):
    assert not view.more.is_expanded()
    assert not view.unjudged_check.isVisibleTo(view) and not view.skip_button.isVisibleTo(view)
    assert view.more.toggle.text() == "More options (2)"


# ── coding ──────────────────────────────────────────────────────────────────

def test_ticking_codes_and_saving_records_them_and_moves_to_the_next_answer(view, service):
    first = view.current_answer_id()
    code_item(view, "Money").setCheckState(Qt_checked())
    view.save_button.click()
    saved = hc.get(service.project, first)
    assert saved.judged and saved.codes == ["Money"]
    assert view.current_answer_id() != first                      # on to the next one
    assert "1 of 6" in view.progress_label.text() and "Saved: 1 code" in view.message.text()


def test_saving_with_nothing_ticked_means_no_code_applies(view, service):
    first = view.current_answer_id()
    view.save_button.click()
    assert hc.get(service.project, first).judged and hc.get(service.project, first).codes == []
    assert "no code applies" in view.message.text()


def test_the_number_keys_tick_and_untick_the_first_codes(view):
    view._toggle_code(1)
    assert code_item(view, "Belonging").checkState() == Qt_checked() or code_item(view, "Money").checkState() == Qt_checked()
    ticked = view._ticked()
    view._toggle_code(1)
    assert view._ticked() != ticked and view._ticked() == []


def test_a_new_code_is_added_ticked_and_created_on_save(view, service):
    first = view.current_answer_id()
    view.new_code_edit.setText("Workload")
    view.new_code_edit.returnPressed.emit()
    assert "Workload" in view._ticked() and view.new_code_edit.text() == ""
    view.save_button.click()
    assert service.project.find_code_by_name("Workload") is not None
    assert hc.get(service.project, first).codes == ["Workload"]


def test_coming_back_to_a_coded_answer_shows_its_ticks(view, service):
    first = view.current_answer_id()
    code_item(view, "Money").setCheckState(Qt_checked())
    view.save_button.click()
    view.show_answer(first)
    assert view._ticked() == ["Money"]


def test_after_the_last_answer_it_says_everything_is_coded(view):
    for _ in range(6):
        view.save_button.click()
    assert "every answer" in view.message.text()
    assert "6 of 6" in view.progress_label.text()


def test_the_list_marks_what_you_have_coded(view):
    view.save_button.click()
    states = [view.answers_tree.topLevelItem(i).text(1) for i in range(6)]
    assert states.count("✓ coded") == 1


# ── finding answers ─────────────────────────────────────────────────────────

def test_search_narrows_the_list(view):
    view.search_edit.setText("advisor")
    assert view.answers_tree.topLevelItemCount() == 1
    view.search_edit.setText("zzz")
    assert view.answers_tree.topLevelItemCount() == 0 and "No answers match" in view.answer_label.text()


def test_only_the_answers_not_yet_coded_can_be_shown(view):
    view.save_button.click()
    view.more.toggle.click()
    view.unjudged_check.setChecked(True)
    assert view.answers_tree.topLevelItemCount() == 5


def test_a_long_list_is_paged_not_loaded_whole(app, service, tmp_path):
    long = pd.DataFrame({"id": [f"r{n}" for n in range(PAGE + 20)],
                         "answer": [f"answer number {n}" for n in range(PAGE + 20)]})
    v = make_view(app, service, tmp_path, long)
    assert v.answers_tree.topLevelItemCount() == PAGE
    assert v.later_button.isVisibleTo(v) and not v.earlier_button.isVisibleTo(v)
    v.later_button.click()
    assert v.answers_tree.topLevelItemCount() == 20 and v.earlier_button.isVisibleTo(v)
    v.close()


# ── where you were (an id, never the answer) ────────────────────────────────

def test_the_place_is_an_id_and_returns_to_the_same_answer(app, service, tmp_path):
    v = make_view(app, service, tmp_path)
    v.search_edit.setText("")
    target = v.answers_tree.topLevelItem(3).data(0, 0x0100)
    v.show_answer(target)
    assert v.current_answer_id() == target
    assert not any(c.isalpha() and " " in target for c in target)       # an id, not prose
    v.close()


# ── in the Code step ────────────────────────────────────────────────────────

def _pipeline(app):
    pipe = PipelineView(ProjectService(), QUndoStack())
    pipe.resize(1300, 900)
    pipe.tabs.setCurrentIndex(2)
    pipe.show()
    pipe._load(SAMPLE)
    pipe.pii_confirm.setChecked(True)
    pipe.text_column.setCurrentIndex(pipe.text_column.findData("response_text"))
    pipe._refresh_enabled()
    app.processEvents()
    return pipe


def test_choosing_to_code_by_hand_shows_the_answers(app):
    pipe = _pipeline(app)
    pipe.choice_buttons["hand"].setChecked(True)
    settle(app)
    assert pipe.hand.isVisibleTo(pipe) and not pipe.run_button.isVisibleTo(pipe)
    assert pipe.hand.answers_tree.topLevelItemCount() > 0
    pipe.close()


def test_the_privacy_check_must_be_confirmed_before_the_answers_appear(app):
    pipe = PipelineView(ProjectService(), QUndoStack())
    pipe.resize(1300, 900)
    pipe.tabs.setCurrentIndex(2)
    pipe.show()
    pipe._load(SAMPLE)
    pipe.text_column.setCurrentIndex(pipe.text_column.findData("response_text"))
    pipe.choice_buttons["hand"].setChecked(True)
    settle(app)
    assert pipe.hand.answers_tree.topLevelItemCount() == 0 and "privacy check" in pipe.hand.message.text()
    pipe.pii_confirm.setChecked(True)
    pipe._refresh_enabled()
    settle(app)
    assert pipe.hand.answers_tree.topLevelItemCount() > 0
    pipe.close()


def test_a_project_that_already_holds_the_answers_still_waits_for_the_privacy_check(app, tmp_path):
    """Choosing hand coding first, then confirming the check, must show the list (not stay blank)."""
    from core.sample_project import build_sample_project
    svc = ProjectService()
    sample = tmp_path / "sample.qnw"
    build_sample_project(SAMPLE, sample)
    svc.open(sample)
    pipe = PipelineView(svc, QUndoStack())
    pipe.resize(1300, 900)
    pipe.tabs.setCurrentIndex(2)
    pipe.show()
    pipe._load(SAMPLE)
    pipe.text_column.setCurrentIndex(pipe.text_column.findData("response_text"))
    pipe.choice_buttons["hand"].setChecked(True)
    settle(app)
    assert pipe.hand.answers_tree.topLevelItemCount() == 0 and not pipe.hand.is_ready()
    pipe.pii_confirm.setChecked(True)
    pipe._refresh_enabled()
    settle(app)
    assert pipe.hand.answers_tree.topLevelItemCount() > 0 and pipe.hand.is_ready()
    pipe.close()
    svc.close()


def test_saved_place_holds_an_id_and_never_the_answer_text(app):
    pipe = _pipeline(app)
    pipe.choice_buttons["hand"].setChecked(True)
    settle(app)
    state = pipe.progress_state()
    assert state["code_choice"] == "hand" and state["hand_answer"]
    answer_text = pipe.hand.answer_label.text()
    cleaned = progress.clean_state("surveys", state)
    assert "hand_answer" in cleaned
    assert answer_text[:30] not in str(cleaned)
    pipe.close()


def test_back_returns_to_the_choices(app):
    pipe = _pipeline(app)
    pipe.choice_buttons["hand"].setChecked(True)
    settle(app)
    pipe.hand.back_button.click()
    app.processEvents()
    assert pipe.code_choice() == "suggest" and pipe.run_button.isVisibleTo(pipe)
    assert not pipe.hand.isVisibleTo(pipe)
    pipe.close()


# ── words ───────────────────────────────────────────────────────────────────

def test_no_banned_or_model_words(view, app):
    view.more.toggle.setChecked(True)
    app.processEvents()
    texts = [w.text() for kind in (QLabel, QPushButton, QCheckBox, QToolButton)
             for w in view.findChildren(kind) if w.isVisibleTo(view)]
    texts += [g.title() for g in view.findChildren(QGroupBox) if g.isVisibleTo(view)]
    for text in texts:
        assert words.find_never(text) == [], text
        assert words.find_replace(text) == [], text


def Qt_checked():
    from PySide6.QtCore import Qt
    return Qt.CheckState.Checked
