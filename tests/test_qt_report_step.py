"""Surveys, step 5 (Report): the three reports most people want, the rest folded away."""

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import QApplication, QCheckBox, QGroupBox, QLabel, QPushButton, QToolButton

from core.sample_project import build_sample_project
from core.ux import words
from qualsafe_qt.services.project_service import ProjectService
from qualsafe_qt.views import results_view
from qualsafe_qt.views.results_view import MAIN_REPORTS, REPORT_KINDS, ResultsView, _size_text
from qualsafe_qt.widgets.more_options import MAX_VISIBLE_CONTROLS, visible_controls

SAMPLE = Path(__file__).resolve().parents[1] / "data" / "sample_survey_education.csv"


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def project(tmp_path_factory):
    path = tmp_path_factory.mktemp("report") / "sample.qnw"
    build_sample_project(SAMPLE, path)
    return path


@pytest.fixture()
def view(app, project):
    service = ProjectService()
    service.open(project)
    v = ResultsView(service, QUndoStack())
    v.resize(1200, 900)
    v.show()
    app.processEvents()
    yield v
    v.close()
    service.close()


def titles(box_parent):
    return [g.title() for g in box_parent.findChildren(QGroupBox)]


# ── few controls, one main action ───────────────────────────────────────────

def test_the_step_shows_at_most_seven_controls(view):
    assert len(visible_controls(view)) <= MAX_VISIBLE_CONTROLS


def test_the_step_is_calm_with_no_project_too(app):
    v = ResultsView(ProjectService(), QUndoStack())
    v.show()
    app.processEvents()
    assert len(visible_controls(v)) <= MAX_VISIBLE_CONTROLS
    assert v._headline_icon.isVisibleTo(v) and "No project is open" in v.headline.text()
    v.close()


def test_exactly_one_filled_button_and_it_is_the_analysis_report(view):
    mains = [b for b in view.findChildren(QPushButton) if b.property("main")]
    assert mains == [view._buttons["report"]]


# ── the three most-used reports, in order; the rest folded ──────────────────

def test_the_three_main_reports_are_the_analysis_report_the_workbook_and_the_methods(view):
    assert MAIN_REPORTS == ("report", "workbook", "methods")
    by_key = {k.key: k for k in REPORT_KINDS}
    shown = [by_key[k].title for k in MAIN_REPORTS]
    assert shown == ["Analysis report", "Analysis workbook", "Methods && reliability appendix"]
    for key in MAIN_REPORTS:
        assert view._buttons[key].isVisibleTo(view)


def test_the_other_reports_are_folded_and_nothing_was_removed(view, app):
    others = [k.key for k in REPORT_KINDS if k.key not in MAIN_REPORTS]
    assert sorted(others) == ["audit", "audit_xlsx", "bundle", "codebook", "joint"]
    assert not view.more_reports.is_expanded()
    assert all(not view._buttons[k].isVisibleTo(view) for k in others)
    assert view.more_reports.toggle.text() == "More reports (5)"
    view.more_reports.toggle.click()
    app.processEvents()
    assert all(view._buttons[k].isVisibleTo(view) for k in others)
    assert set(view._buttons) == {k.key for k in REPORT_KINDS}       # all eight still exist


def test_every_report_still_says_what_it_contains(view):
    """The plain privacy line stays on every report, main or folded (a caveat that
    travels with the thing it qualifies)."""
    view.more_reports.toggle.click()
    lines = [w.text() for w in view.findChildren(QLabel) if "Contains:" in w.text()]
    assert len(lines) == len(REPORT_KINDS)


def test_verbatim_quotes_stay_off_by_default_and_visible_on_the_report_that_has_them(view):
    assert not view.report_raw_text.isChecked()
    assert view.report_raw_text.isVisibleTo(view)
    assert not view.bundle_raw_text.isChecked() and not view.codebook_examples.isChecked()
    assert not view.audit_memo_text.isChecked()


def test_save_buttons_say_what_kind_of_file_you_get(view):
    assert view._buttons["report"].text() == "Save as Word document…"
    assert view._buttons["workbook"].text() == "Save as spreadsheet…"
    assert view._buttons["methods"].text() == "Save as Word document…"
    assert view._buttons["bundle"].text() == "Save as zip file…"


# ── plain words, plain sizes, a link instead of another button ──────────────

@pytest.mark.parametrize("size,text", [(0, "0 bytes"), (900, "900 bytes"), (24311, "24 KB"),
                                       (5 * 1024 * 1024, "5.0 MB")])
def test_sizes_read_like_sizes(size, text):
    assert _size_text(size) == text


def test_after_writing_the_message_gives_a_plain_size_and_a_link(view, tmp_path, monkeypatch):
    out = tmp_path / "report.docx"
    out.write_bytes(b"x" * 24311)
    view._on_written(out)
    text = view.message.text()
    assert "report.docx" in text and "24 KB" in text and "bytes" not in text
    assert 'href="folder"' in text and "Show in folder" in text
    opened = []
    monkeypatch.setattr(results_view.QDesktopServices, "openUrl", lambda url: opened.append(url.toLocalFile()))
    view.message.linkActivated.emit("folder")
    assert [Path(o) for o in opened] == [tmp_path]


def test_writing_a_report_never_adds_a_visible_control(view, tmp_path):
    before = len(visible_controls(view))
    out = tmp_path / "r.docx"
    out.write_bytes(b"x")
    view._on_written(out)
    assert len(visible_controls(view)) == before <= MAX_VISIBLE_CONTROLS


def test_no_banned_or_model_words_on_the_step(view, app):
    view.more_reports.toggle.click()
    app.processEvents()
    texts = [w.text() for kind in (QLabel, QPushButton, QCheckBox, QToolButton)
             for w in view.findChildren(kind) if w.isVisibleTo(view)]
    texts += [g.title() for g in view.findChildren(QGroupBox)]
    for text in texts:
        assert words.find_never(text) == [], text
        assert words.find_replace(text) == [], text


def test_the_joint_display_still_needs_a_descriptor_and_says_so(view):
    button = view._buttons["joint"]
    if not button.isEnabled():
        assert "no respondent details" in button.toolTip()
