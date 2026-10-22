"""Coding with a written codebook on the desktop (Surveys, step 3, second choice).

Offline: the demo engine stands in for Laya, and the install is stubbed.
"""

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

from core.model import Code
from core.project import Project
from core.ux import words
from engines import laya_setup
from qualsafe_qt.services.project_service import ProjectService
from qualsafe_qt.views.pipeline_view import PipelineView
from qualsafe_qt.views.written_codebook_view import STAGES, WrittenCodebookView, _plain
from qualsafe_qt.widgets.more_options import MAX_VISIBLE_CONTROLS, visible_controls

ANSWERS = pd.DataFrame({
    "id": ["a", "b", "c", "d"],
    "answer": ["I cannot afford the books", "Advisors were kind", "Rent is too high", "Great staff"],
})
NOT_INSTALLED = {"state": "not_installed", "python": None, "laya_version": None}
READY = {"state": "ready", "python": "C:/nowhere/python.exe", "laya_version": "0.3.3"}


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def settle(app):
    for _ in range(5):
        QThreadPool.globalInstance().waitForDone(60000)
        app.processEvents()


@pytest.fixture(autouse=True)
def engine_missing(monkeypatch):
    monkeypatch.setattr(laya_setup, "installation_status", lambda *a, **k: dict(NOT_INSTALLED))


@pytest.fixture()
def service(app, tmp_path):
    svc = ProjectService()
    path = tmp_path / "p.qnw"
    with Project.create(path) as proj:
        proj.add_code(Code(code_id="", name="Money", definition="", inclusion_criteria="trouble paying",
                           exclusion_criteria="praise for aid"))
        proj.add_code(Code(code_id="", name="Support", definition="", inclusion_criteria="helpful staff"))
    svc.open(path)
    svc.set_analyst_name("Test Analyst")
    yield svc
    svc.close()


@pytest.fixture()
def view(app, service, tmp_path):
    v = WrittenCodebookView(service, output_root=lambda: tmp_path / "out")
    v.resize(1000, 800)
    v.show()
    v.set_source(ANSWERS, "answer", "id")
    app.processEvents()
    yield v
    v.close()


def mains(v):
    return [b for b in v.findChildren(QPushButton) if b.property("main") and b.isVisibleTo(v)]


# ── four stages, few controls, one main button ──────────────────────────────

def test_it_has_six_stages_and_starts_on_the_codebook(view):
    assert STAGES == ("codebook", "engine", "run", "review", "sample", "compare")
    assert view.current_stage() == "codebook" and "Step 1 of 6" in view.stage_label.text()


@pytest.mark.parametrize("stage", STAGES)
def test_every_stage_shows_at_most_seven_controls_and_one_filled_button(view, app, stage):
    view.go_stage(stage)
    app.processEvents()
    assert len(visible_controls(view)) <= MAX_VISIBLE_CONTROLS, \
        [(type(w).__name__, getattr(w, "text", lambda: "")()) for w in visible_controls(view)]
    assert len(mains(view)) == 1, [b.text() for b in mains(view)]


def test_it_says_it_is_a_preview_and_that_a_score_is_not_a_probability(view):
    assert "Preview" in view.preview_note.text() and "not a probability" in view.preview_note.text()


# ── 1 · the codebook ────────────────────────────────────────────────────────

def test_the_codes_are_listed_with_whether_their_rules_are_written(view):
    rows = [view.codes_list.topLevelItem(i).text(0) for i in range(view.codes_list.topLevelItemCount())]
    assert len(rows) == 2 and all("rules written" in r for r in rows)


def test_a_code_needs_a_name(view):
    view.save_code_button.click()
    assert "Name the code" in view.message.text()


def test_adding_a_code_stores_its_rules(view, service):
    view.name_edit.setText("Belonging")
    view.include_edit.setPlainText("feeling part of campus")
    view.exclude_edit.setPlainText("only clubs")
    view.examples_edit.setPlainText("I made friends\nI feel at home")
    view.save_code_button.click()
    code = next(c for c in service.project.get_codebook() if c.name == "Belonging")
    assert code.inclusion_criteria == "feeling part of campus" and code.exclusion_criteria == "only clubs"
    assert code.examples == ["I made friends", "I feel at home"]
    assert view.name_edit.text() == ""                       # ready for the next one


def test_picking_a_code_loads_it_and_saving_changes_it(view, service):
    view.codes_list.setCurrentItem(view.codes_list.topLevelItem(0))
    name = view.name_edit.text()
    assert name and view.save_code_button.text() == "Save this code"
    view.include_edit.setPlainText("a changed rule")
    view.save_code_button.click()
    code = next(c for c in service.project.get_codebook() if c.name == name)
    assert code.inclusion_criteria == "a changed rule"


def test_a_project_is_made_when_none_is_open(app, tmp_path):
    svc = ProjectService()
    v = WrittenCodebookView(svc, output_root=lambda: tmp_path / "made")
    v.name_edit.setText("First code")
    v.include_edit.setPlainText("a rule")
    v.save_code_button.click()
    assert svc.is_open and Path(svc.path).exists()
    assert [c.name for c in svc.project.get_codebook()] == ["First code"]
    svc.close()


def test_the_extra_fields_are_folded_and_still_there(view):
    assert not view.codebook_more.is_expanded()
    for name in ("definition_edit", "examples_edit", "parent_combo", "type_combo", "new_code_button"):
        assert hasattr(view, name) and not getattr(view, name).isVisibleTo(view)


# ── 2 · the engine ──────────────────────────────────────────────────────────

def test_without_the_engine_it_offers_the_install_and_warns_about_the_demo(view):
    view.go_stage("engine")
    assert view.install_button.isVisibleTo(view) and mains(view) == [view.install_button]
    assert "demo engine" in view.engine_label.text() and "MB" in view.engine_detail.text()


def test_with_the_engine_ready_next_is_the_main_button(view, monkeypatch):
    monkeypatch.setattr(laya_setup, "installation_status", lambda *a, **k: dict(READY))
    view.go_stage("engine")
    assert not view.install_button.isVisibleTo(view) and mains(view) == [view.next_button]
    assert "ready" in view.engine_label.text()


def test_declining_the_install_downloads_nothing(view, monkeypatch):
    called = []
    monkeypatch.setattr(laya_setup, "install", lambda **k: called.append(1) or {"ok": True})
    monkeypatch.setattr(view, "_confirm_install", lambda: False)
    view.go_stage("engine")
    view.install_button.click()
    assert called == []


def test_accepting_the_install_runs_it_and_rechecks(view, app, monkeypatch):
    called = []
    monkeypatch.setattr(laya_setup, "install", lambda **k: called.append(1) or {"ok": True})
    monkeypatch.setattr(view, "_confirm_install", lambda: True)
    view.go_stage("engine")
    view.install_button.click()
    settle(app)
    assert called == [1] and "installed" in view.message.text()


def test_a_failed_install_says_so(view, app, monkeypatch):
    monkeypatch.setattr(laya_setup, "install", lambda **k: {"ok": False, "error": "no network"})
    monkeypatch.setattr(view, "_confirm_install", lambda: True)
    view.go_stage("engine")
    view.install_button.click()
    settle(app)
    assert "did not finish" in view.message.text() and "no network" in view.message.text()


# ── 3 · run ─────────────────────────────────────────────────────────────────

def test_the_run_stage_names_the_column_and_warns_when_the_engine_is_missing(view):
    view.go_stage("run")
    assert "answer" in view.source_label.text() and "4 answers" in view.source_label.text()
    assert "demo engine" in view.demo_note.text()


def test_with_the_real_engine_the_run_stage_says_how_long_it_will_take(view, monkeypatch):
    monkeypatch.setattr(laya_setup, "installation_status", lambda *a, **k: dict(READY))
    view.go_stage("engine")
    view.go_stage("run")
    assert "Expect" in view.estimate_label.text() and "4 answers" in view.estimate_label.text()
    assert "minutes" in view.estimate_label.text() or "under two" in view.estimate_label.text()


def test_the_demo_engine_shows_no_time_estimate(view):
    view.go_stage("run")
    assert view.estimate_label.text() == ""


def test_running_needs_answers_a_code_and_a_sensible_band(app, service, tmp_path):
    v = WrittenCodebookView(service, output_root=lambda: tmp_path / "o")
    v.go_stage("run")
    v.run_button.click()
    assert "privacy check" in v.message.text()
    v.set_source(ANSWERS, "answer", "id")
    v.low_spin.setValue(0.8)
    v.high_spin.setValue(0.4)
    v.run_button.click()
    assert "low score must be below" in v.message.text()


def test_a_demo_run_codes_every_answer_and_says_the_scores_mean_nothing(view, app):
    view.go_stage("run")
    view.run_button.click()
    settle(app)
    text = view.run_summary.text()
    assert "Coded 4 answers" in text and "demo engine" in text and "mean nothing" in text
    assert view.remove_demo_button.isVisibleTo(view)
    assert view.run_button.isEnabled() and not view.cancel_button.isEnabled()


def test_the_demo_codings_can_be_removed(view, app, service):
    view.go_stage("run")
    view.run_button.click()
    settle(app)
    view.remove_demo_button.click()
    assert "Removed" in view.message.text() and not view.remove_demo_button.isVisibleTo(view)


# ── 4 · review ──────────────────────────────────────────────────────────────

def _run_everything_to_review(view, app):
    view.low_spin.setValue(0.0)
    view.high_spin.setValue(1.0)
    view.go_stage("run")
    view.run_button.click()
    settle(app)
    view.go_stage("review")


def test_before_a_run_the_review_stage_says_what_to_do(view):
    view.go_stage("review")
    assert "Run the coding first" in view.review_note.text() and not view.accept_button.isEnabled()


def test_the_queue_lists_what_is_waiting_and_shows_the_answer(view, app):
    _run_everything_to_review(view, app)
    assert view.queue_list.topLevelItemCount() > 0 and "not probabilities" in view.review_note.text()
    assert "the answer is" in view.answer_label.text()


def test_the_reviewer_sees_the_leave_out_rule_beside_the_answer(view, app):
    _run_everything_to_review(view, app)
    for i in range(view.queue_list.topLevelItemCount()):          # a code that has a leave-out rule
        if view.queue_list.topLevelItem(i).text(0).startswith("Money"):
            view.queue_list.setCurrentItem(view.queue_list.topLevelItem(i))
            break
    text = view.answer_label.text()
    assert "Leave it out when: praise for aid" in text


def test_the_leave_out_rule_goes_to_the_engine_only_when_switched_on(view):
    assert view.run_spec()["send_exclusions"] is False
    view.exclusions_check.setChecked(True)
    assert view.run_spec()["send_exclusions"] is True


def test_accepting_one_code_shrinks_the_queue(view, app, service):
    _run_everything_to_review(view, app)
    before = view.queue_list.topLevelItemCount()
    view.accept_button.click()
    assert view.queue_list.topLevelItemCount() == before - 1


def test_rejecting_and_flagging_also_leave_the_queue(view, app):
    _run_everything_to_review(view, app)
    before = view.queue_list.topLevelItemCount()
    view.reject_button.click()
    view.flag_button.click()
    assert view.queue_list.topLevelItemCount() == before - 2


def test_accept_all_clears_the_queue(view, app):
    _run_everything_to_review(view, app)
    view.accept_all_button.click()
    assert view.queue_list.topLevelItemCount() == 0 and "Nothing is waiting" in view.review_note.text()


def test_the_answer_text_is_shown_as_text_not_markup():
    assert _plain("<b>x</b> & y") == "&lt;b&gt;x&lt;/b&gt; &amp; y"


# ── in the Code step ────────────────────────────────────────────────────────

def test_the_screen_only_gets_the_answers_once_the_privacy_check_is_confirmed(app):
    pipe = PipelineView(ProjectService(), QUndoStack())
    pipe._load(Path(__file__).resolve().parents[1] / "data" / "sample_survey_education.csv")
    pipe._refresh_enabled()
    assert pipe.written._frame is None
    pipe.pii_confirm.setChecked(True)
    pipe.text_column.setCurrentIndex(pipe.text_column.findData("response_text"))   # chosen, never assumed
    pipe._refresh_enabled()
    assert pipe.written._frame is not None and pipe.written._text_column == "response_text"


# ── words ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("stage", STAGES)
def test_no_banned_or_model_words_on_any_stage(view, app, stage):
    view.go_stage(stage)
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


# ── 5 and 6 · check it against yourself ─────────────────────────────────────

BIG = pd.DataFrame({"id": [f"r{n}" for n in range(14)],
                    "answer": [f"answer number {n} about money and friends" for n in range(14)]})


@pytest.fixture()
def big_view(app, service, tmp_path):
    v = WrittenCodebookView(service, output_root=lambda: tmp_path / "out")
    v.resize(1000, 800)
    v.show()
    v.set_source(BIG, "answer", "id")
    v.low_spin.setValue(0.0)
    v.high_spin.setValue(1.0)
    v.go_stage("run")
    v.run_button.click()
    settle(app)
    yield v
    v.close()


def _draw(v, app, size=10):
    v.go_stage("sample")
    v.sample_size_spin.setValue(size)
    v.draw_button.click()
    app.processEvents()


def _code_the_sample(v, app, how_many=None):
    hand = v.sample_hand
    count = how_many if how_many is not None else hand.answers_tree.topLevelItemCount()
    for i in range(count):
        if i % 2 == 0:
            hand._toggle_code(1)
        hand.save_button.click()
    app.processEvents()


def test_before_a_run_the_sample_stage_says_to_run_first(view):
    view.go_stage("sample")
    assert "Run the coding first" in view.sample_note.text() and not view.draw_button.isEnabled()


def test_the_demo_engine_is_called_out_on_the_sample_stage(big_view, app):
    big_view.go_stage("sample")
    assert "demo engine" in big_view.sample_note.text()


def test_a_random_sample_is_drawn_and_only_those_answers_are_offered(big_view, app, service):
    _draw(big_view, app, size=8)
    assert big_view.sample_stack.currentIndex() == 1
    assert big_view.sample_hand.answers_tree.topLevelItemCount() == 8
    assert "0 of 8 answers in your sample" in big_view.sample_hand.progress_label.text()
    assert "do not see what the engine chose" in big_view.sample_note.text()


def test_the_sample_stage_keeps_to_seven_controls_and_one_filled_button_in_both_states(big_view, app):
    big_view.go_stage("sample")
    app.processEvents()
    assert len(visible_controls(big_view)) <= MAX_VISIBLE_CONTROLS and len(mains(big_view)) == 1
    _draw(big_view, app)
    assert len(visible_controls(big_view)) <= MAX_VISIBLE_CONTROLS,         [(type(w).__name__, getattr(w, "text", lambda: "")()) for w in visible_controls(big_view)]
    assert len(mains(big_view)) == 1


def test_a_different_sample_can_be_picked_from_more_options(big_view, app):
    _draw(big_view, app, size=6)
    assert not big_view.redraw_button.isVisibleTo(big_view)
    big_view.sample_hand.more.toggle.click()
    assert big_view.redraw_button.isVisibleTo(big_view)


def test_compare_says_to_code_a_sample_first_when_there_is_none(big_view):
    big_view.go_stage("compare")
    assert "Code a sample first" in big_view.compare_headline.text() and big_view.compare_table.rowCount() == 0


def test_compare_waits_until_some_of_the_sample_is_coded(big_view, app):
    _draw(big_view, app, size=8)
    big_view.go_stage("compare")
    assert "Code some of them first" in big_view.compare_headline.text()


def test_the_table_shows_kappa_beside_percent_agreement_prevalence_and_the_engine_is_not_a_coder(big_view, app):
    _draw(big_view, app, size=10)
    _code_the_sample(big_view, app)
    big_view.go_stage("compare")
    headers = [big_view.compare_table.horizontalHeaderItem(c).text() for c in range(big_view.compare_table.columnCount())]
    assert headers[:5] == ["Code", "Agreement (κ)", "Same answer", "You applied it", "Engine applied it"]
    assert big_view.compare_table.rowCount() == 2
    assert "not counted as a coder" in big_view.compare_headline.text() and "Demo engine" in big_view.compare_headline.text()
    assert big_view.compare_table.item(0, 2).text().endswith("%") and big_view.compare_table.item(0, 5).text() == "10"


def test_a_figure_with_too_few_answers_has_no_kappa_and_says_why(big_view, app):
    _draw(big_view, app, size=6)
    _code_the_sample(big_view, app, how_many=3)
    big_view.go_stage("compare")
    big_view.compare_table.rowCount()
    assert big_view.compare_table.item(0, 1).text() == "—" and "Applied to too few" in big_view.compare_table.item(0, 6).text()


def test_the_compare_stage_keeps_to_seven_controls_and_one_filled_button(big_view, app):
    _draw(big_view, app)
    _code_the_sample(big_view, app)
    big_view.go_stage("compare")
    app.processEvents()
    assert len(visible_controls(big_view)) <= MAX_VISIBLE_CONTROLS and mains(big_view) == [big_view.save_table_button]


def test_the_error_breakdown_is_in_more_options_not_beside_the_agreement(big_view, app):
    _draw(big_view, app)
    _code_the_sample(big_view, app)
    big_view.go_stage("compare")
    assert not big_view.detail_table.isVisibleTo(big_view)
    big_view.compare_more.toggle.click()
    assert big_view.detail_table.isVisibleTo(big_view) and big_view.detail_table.rowCount() == 2


def test_the_table_is_saved_without_any_answer_text(big_view, app, tmp_path, monkeypatch):
    _draw(big_view, app)
    _code_the_sample(big_view, app)
    big_view.go_stage("compare")
    out = tmp_path / "agreement.csv"
    monkeypatch.setattr(big_view, "_ask_save_path", lambda default: str(out))
    assert big_view.save_table() == str(out)
    text = out.read_text()
    assert "kappa" in text and "answer number" not in text


def test_a_recommended_range_can_be_applied_to_the_next_run(big_view, app):
    _draw(big_view, app, size=12)
    _code_the_sample(big_view, app)
    big_view.go_stage("compare")
    big_view.compare_more.toggle.click()
    if big_view.apply_band_button.isVisibleTo(big_view):
        big_view.apply_band_button.click()
        assert big_view.low_spin.value() <= big_view.high_spin.value()
        assert "next run" in big_view.message.text()
    else:
        assert big_view.band_label.text()


def test_the_engine_run_is_not_listed_among_the_coders(big_view, app, service):
    from core.agreement_pairs import selectable_raters
    _draw(big_view, app)
    _code_the_sample(big_view, app)
    others = {r.rater_id for r in service.project.list_raters() if r.rater_id != "human_primary"}
    assert others and not others & set(selectable_raters(service.project))
