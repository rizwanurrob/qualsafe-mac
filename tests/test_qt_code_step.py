"""Surveys, step 3 (Code): choose how to code, run it, keep the details folded away."""

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QLabel, QPushButton, QRadioButton, QToolButton,
)

from core.ux import progress, words
from qualsafe_qt.services.project_service import ProjectService
from qualsafe_qt.views.pipeline_view import CODING_CHOICES, PipelineView
from qualsafe_qt.widgets.more_options import MAX_VISIBLE_CONTROLS, visible_controls

SAMPLE = Path(__file__).resolve().parents[1] / "data" / "sample_survey_education.csv"


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def view(app):
    v = PipelineView(ProjectService(), QUndoStack())
    v.resize(1300, 900)
    v.tabs.setCurrentIndex(2)
    v.show()
    app.processEvents()
    yield v
    v.close()


def step(view):
    return view.tabs.widget(2)


# ── few controls, one main action ───────────────────────────────────────────

def test_the_step_shows_at_most_seven_controls(view):
    shown = visible_controls(step(view))
    assert len(shown) <= MAX_VISIBLE_CONTROLS
    kinds = sorted(type(w).__name__ for w in shown)
    assert kinds == ["QPushButton", "QPushButton", "QRadioButton", "QRadioButton",
                     "QRadioButton", "QToolButton"]


def test_exactly_one_filled_button(view):
    assert [b for b in step(view).findChildren(QPushButton)
            if b.property("main") and b.isVisibleTo(step(view))] == [view.run_button]


def test_every_detail_is_folded_away_and_nothing_was_removed(view, app):
    folded = [view.engine, view.use_sentiment, view.use_zero_shot, view.use_question_theme,
              view.use_question_zero_shot, view.save_store, view.strict_enabled,
              view.strict_top1, view.strict_margin]
    assert not view.code_more.is_expanded()
    assert all(not w.isVisibleTo(step(view)) for w in folded)
    before = len(visible_controls(step(view)))
    view.code_more.toggle.click()
    app.processEvents()
    assert all(w.isVisibleTo(step(view)) for w in folded)
    assert len(visible_controls(step(view))) >= before + len(folded)


# ── the three-way choice ────────────────────────────────────────────────────

def test_the_three_ways_to_code_are_shown_in_order_with_when_to_use_each(view):
    assert [c[0] for c in CODING_CHOICES] == ["suggest", "codebook", "hand"]
    assert [view.choice_buttons[k].text() for k in view.choice_buttons] == [
        "Suggest codes for me to check", "Code with a written codebook", "I'll code by hand"]
    labels = " ".join(w.text() for w in step(view).findChildren(QLabel))
    assert "no coded examples" in labels                         # when to use suggest
    assert "definition" in labels and "preview" in labels.lower()  # the codebook method, flagged
    assert "small sample" in labels                              # when to code by hand


def test_all_three_ways_to_code_can_be_chosen(view):
    assert view.choice_buttons["suggest"].isChecked() and view.code_choice() == "suggest"
    assert all(view.choice_buttons[k].isEnabled() for k in ("suggest", "codebook", "hand"))


def test_choosing_the_written_codebook_replaces_the_suggest_controls(view, app):
    view.choice_buttons["codebook"].setChecked(True)
    app.processEvents()
    assert view.code_choice() == "codebook"
    assert view.written.isVisibleTo(step(view)) and not view.run_button.isVisibleTo(step(view))
    assert not view.choice_buttons["suggest"].isVisibleTo(step(view))
    assert len(visible_controls(step(view))) <= MAX_VISIBLE_CONTROLS


def test_back_from_the_first_stage_returns_to_the_choices(view, app):
    view.choice_buttons["codebook"].setChecked(True)
    view.written.back_button.click()
    app.processEvents()
    assert view.code_choice() == "suggest" and view.run_button.isVisibleTo(step(view))
    assert not view.written.isVisibleTo(step(view))


# ── the run is unchanged ────────────────────────────────────────────────────

def test_the_options_still_reach_the_run_settings(view):
    view.use_sentiment.setChecked(False)
    view.use_question_zero_shot.setChecked(True)
    view.strict_enabled.setChecked(True)
    s = view.settings()
    assert s.use_sentiment is False and s.use_question_zero_shot is True


def test_choosing_the_language_model_shows_its_row_and_its_own_limits(view, app):
    view.code_more.toggle.click()
    view.engine.setCurrentIndex(view.engine.findData("llm"))
    app.processEvents()
    assert not view.llm_row.isHidden() and view.llm_row.isVisibleTo(step(view))
    assert view.strict_top1.value() == pytest.approx(0.70)
    view.engine.setCurrentIndex(view.engine.findData("transformer"))
    assert view.llm_row.isHidden() and view.strict_top1.value() == pytest.approx(0.55)


def test_the_run_is_still_blocked_until_data_columns_themes_and_the_gate(view):
    assert not view.run_button.isEnabled()
    assert "load a data file" in view.blockers()
    view._load(SAMPLE)
    view.suggestion_button.click()
    view.labels_edit.setPlainText("Money")
    assert not view.run_button.isEnabled()                        # still needs the privacy gate
    view.pii_confirm.setChecked(True)
    assert view.run_button.isEnabled()


# ── saved place and Start over ──────────────────────────────────────────────

def test_the_options_are_part_of_the_saved_place_and_are_only_small_values(view):
    view.use_sentiment.setChecked(False)
    view.strict_enabled.setChecked(True)
    view.strict_top1.setValue(0.65)
    state = view.progress_state()
    assert state["code_choice"] == "suggest"
    saved = state["code_settings"]
    assert saved["sentiment"] is False and saved["flag"] is True and saved["confidence"] == 0.65
    assert all(isinstance(v, (bool, int, float, str)) for v in saved.values())
    assert set(progress.clean_state("surveys", state)) >= {"code_choice", "code_settings"}


def test_the_options_come_back_and_start_over_puts_the_defaults_back(view):
    view.use_sentiment.setChecked(False)
    view.engine.setCurrentIndex(view.engine.findData("llm"))
    view.strict_top1.setValue(0.8)
    state = view.progress_state()
    view.reset_session()
    assert view.use_sentiment.isChecked() and view.engine.currentData() == "transformer"
    assert view.strict_top1.value() == pytest.approx(0.55) and not view.code_more.is_expanded()
    view.restore_progress(state)
    assert not view.use_sentiment.isChecked() and view.engine.currentData() == "llm"
    assert view.strict_top1.value() == pytest.approx(0.8)


def test_a_bad_saved_option_is_ignored_not_a_crash(view):
    view.restore_progress({"code_settings": {"engine": "nope", "sentiment": "yes", "seed": "x",
                                             "confidence": "high"}})
    assert view.engine.currentData() == "transformer" and view.use_sentiment.isChecked()


# ── plain words ─────────────────────────────────────────────────────────────

def test_no_banned_or_model_words_on_the_step_or_in_its_tips(view, app):
    view.code_more.toggle.click()
    view.engine.setCurrentIndex(view.engine.findData("llm"))
    view._load(SAMPLE)                                            # so the estimate shows
    app.processEvents()
    root = step(view)
    shown = []
    for kind in (QLabel, QPushButton, QCheckBox, QToolButton, QRadioButton):
        shown += [w.text() for w in root.findChildren(kind) if w.isVisibleTo(root)]
    shown += [view.engine.itemText(i) for i in range(view.engine.count())]
    for widget in (view.engine, view.run_button, view.preview_button, view.use_sentiment,
                   view.use_zero_shot, view.use_question_theme, view.use_question_zero_shot,
                   view.save_store, view.strict_enabled, view.strict_top1, view.strict_margin,
                   view.llm_temperature, view.llm_seed):
        shown.append(widget.toolTip())
    for text in shown:
        assert words.find_never(text) == [], text
        assert words.find_replace(text) == [], text
    assert "graphics card" in view.estimate_label.text()


def test_the_estimate_reads_cleanly(view):
    view._load(SAMPLE)
    text = view.estimate_label.text()
    assert "about about" not in text and "Rough estimate:" in text
    assert text.count("about") <= 2                      # one per figure, from the estimate itself
