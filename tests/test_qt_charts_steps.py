"""The Charts activity as four steps: Open, Pick a question, Adjust, Save.

Each step shows a few controls and one filled button; the rest sit under More options,
and the chart is chosen from the question so nobody has to know chart names.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

pytest.importorskip("PySide6", reason="Qt front end not installed")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication, QCheckBox, QGroupBox, QLabel, QPushButton, QToolButton  # noqa: E402

from core.ux import activities, words  # noqa: E402
from qualsafe_qt.views.data_charts_view import STEP_KEYS, DataChartsView  # noqa: E402
from qualsafe_qt.widgets.more_options import MAX_VISIBLE_CONTROLS, visible_controls  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def view(app, tmp_path):
    v = DataChartsView(storage_root=tmp_path / "cb")
    v.resize(1300, 900)
    v.show()
    app.processEvents()
    yield v
    v.close()
    v.deleteLater()


def pick(combo, key):
    index = combo.findData(key)
    assert index >= 0, f"{key!r} not offered"
    combo.setCurrentIndex(index)


def main_buttons(v):
    return [b for b in v.findChildren(QPushButton) if b.property("main") and b.isVisibleTo(v)]


# ── the steps match the activity definition ─────────────────────────────────

def test_the_four_pages_are_the_four_steps_of_the_activity():
    assert list(STEP_KEYS) == [s.key for s in activities.get("charts").steps]


def test_it_starts_on_the_open_step_and_says_what_to_do(view):
    assert view.current_step() == "open"
    assert "Open a file" in view.problem_label.text()
    assert main_buttons(view) == [view.open_button]


def test_a_step_can_be_shown_by_name_and_unknown_names_are_ignored(view):
    view.set_step("adjust")
    assert view.current_step() == "adjust"
    view.set_step("nonsense")
    assert view.current_step() == "adjust"


# ── few controls, one filled button, on every step ──────────────────────────

@pytest.mark.parametrize("step", STEP_KEYS)
def test_every_step_shows_at_most_seven_controls_with_a_file_open(view, app, step):
    view.load_sample()
    pick(view.field_combo, "Class year")
    view.flush()
    view.set_step(step)
    app.processEvents()
    assert len(visible_controls(view)) <= MAX_VISIBLE_CONTROLS, \
        [(type(w).__name__, w.text() if hasattr(w, "text") else "") for w in visible_controls(view)]


@pytest.mark.parametrize("step", STEP_KEYS)
def test_every_step_has_exactly_one_filled_button(view, app, step):
    view.load_sample()
    pick(view.field_combo, "Class year")
    view.flush()
    view.set_step(step)
    app.processEvents()
    assert len(main_buttons(view)) == 1, [b.text() for b in main_buttons(view)]


def test_the_filled_button_is_open_before_a_file_and_next_after(view, app):
    assert main_buttons(view) == [view.open_button]
    view.load_sample()
    app.processEvents()
    assert main_buttons(view) == [view.next_buttons["open"]]


def test_the_save_step_fills_save_picture(view, app):
    view.load_sample()
    pick(view.field_combo, "Class year")
    view.flush()
    view.set_step("save")
    app.processEvents()
    assert main_buttons(view) == [view.save_picture_button]


def test_nothing_was_removed_the_folded_controls_are_still_there(view, app):
    view.load_sample()
    for name in ("kind_combo", "group_list", "multi_box", "filters_list", "filter_values", "subtitle_edit",
                 "axis_min_edit", "preset_combo", "scale_combo", "default_button", "format_combo",
                 "dpi_combo", "transparent_check", "saved_combo", "export_chart_button",
                 "import_chart_button", "tokens_edit", "reset_button"):
        assert hasattr(view, name), name


def test_the_more_options_panels_start_closed_and_say_how_many_are_inside(view):
    toggles = [t for t in view.findChildren(QToolButton) if t.text().startswith("More options")]
    assert len(toggles) == 4
    assert all(not t.isChecked() for t in toggles)
    assert all("(" in t.text() for t in toggles)


# ── moving between steps ────────────────────────────────────────────────────

def test_next_is_off_until_there_is_something_to_go_on_with(view):
    assert not view.next_buttons["open"].isEnabled()
    assert not view.next_buttons["question"].isEnabled()
    view.load_sample()
    assert view.next_buttons["open"].isEnabled()
    assert not view.next_buttons["question"].isEnabled()        # no question chosen yet
    pick(view.field_combo, "Class year")
    view.flush()
    assert view.next_buttons["question"].isEnabled()


def test_the_sample_button_goes_straight_to_the_question(view, app):
    asked = []
    view.step_requested.connect(asked.append)
    view.sample_button.click()
    app.processEvents()
    assert asked == ["question"] and view.current_step() == "question"


def test_next_asks_the_shell_to_move_and_moves_itself(view, app):
    view.load_sample()
    pick(view.field_combo, "Class year")
    view.flush()
    asked = []
    view.step_requested.connect(asked.append)
    view.next_buttons["question"].click()
    assert asked == ["adjust"] and view.current_step() == "adjust"
    view.next_buttons["adjust"].click()
    assert asked == ["adjust", "save"] and view.current_step() == "save"


def test_the_numbers_show_once_there_is_something_to_adjust(view, app):
    view.load_sample()
    pick(view.field_combo, "Class year")
    view.flush()
    view.set_step("question")
    assert not view.tabs.isVisibleTo(view)
    view.set_step("adjust")
    assert view.tabs.isVisibleTo(view)


# ── the chart is chosen from the question ───────────────────────────────────

def test_picking_a_question_picks_a_chart_that_fits(view):
    view.load_sample()
    pick(view.field_combo, "Class year")
    view.flush()
    assert "suggested" in view.chart_combo.currentText()
    assert view.chart_hint.text()
    pick(view.field_combo, "Hours per week")
    view.flush()
    assert view.chart_combo.currentData() == "histogram"


def test_a_free_text_column_is_read_as_text_without_asking(view):
    view.load_sample()
    pick(view.field_combo, "Respondent")
    view.flush()
    assert view.config().kind == "text"
    assert "free text" in view.kind_hint.text()


def test_a_select_all_column_is_read_as_select_all_with_its_choices(view):
    view.load_sample()
    pick(view.field_combo, "Concerns")
    view.flush()
    cfg = view.config()
    assert cfg.kind == "multi" and cfg.multi.choices
    assert isinstance(view._built, tuple)


def test_a_plain_choice_column_stays_a_single_question(view):
    view.load_sample()
    pick(view.field_combo, "Residence")
    view.flush()
    assert view.config().kind == "single"


def test_what_the_person_chose_is_not_overruled(view):
    view.load_sample()
    pick(view.kind_combo, "text")                   # the person picks the kind first
    pick(view.field_combo, "Concerns")
    view.flush()
    assert view.config().kind == "text"


def test_opening_another_file_gives_the_choice_back_to_the_screen(view):
    view.load_sample()
    pick(view.kind_combo, "text")
    view.load_sample()
    pick(view.field_combo, "Concerns")
    view.flush()
    assert view.config().kind == "multi"


# ── plain words ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("step", STEP_KEYS)
def test_no_banned_or_model_words_on_any_step(view, app, step):
    view.load_sample()
    pick(view.field_combo, "Class year")
    view.flush()
    view.set_step(step)
    for toggle in view.findChildren(QToolButton):
        if toggle.isCheckable() and toggle.text().startswith("More options"):
            toggle.setChecked(True)
    app.processEvents()
    texts = [w.text() for kind in (QLabel, QPushButton, QCheckBox, QToolButton)
             for w in view.findChildren(kind) if w.isVisibleTo(view)]
    texts += [g.title() for g in view.findChildren(QGroupBox) if g.isVisibleTo(view)]
    for text in texts:
        assert words.find_never(text) == [], text
        assert words.find_replace(text) == [], text
