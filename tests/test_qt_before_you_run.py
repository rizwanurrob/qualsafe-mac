"""The desktop "Before you run" card: shown until dismissed, then gone for good (book-audit F4)."""

from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6", reason="Qt front end not installed")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QUndoStack  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core.ux import before_you_run  # noqa: E402
from qualsafe_qt.services.project_service import ProjectService  # noqa: E402
from qualsafe_qt.views.pipeline_view import PipelineView  # noqa: E402
from qualsafe_qt.windows.main_window import open_settings  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _view(app):
    v = PipelineView(ProjectService(), QUndoStack())
    v.resize(1300, 900)
    v.tabs.setCurrentIndex(2)
    v.show()
    app.processEvents()
    return v


def test_the_card_shows_until_the_first_run_and_then_stays_away(app):
    settings = open_settings()
    settings.remove(before_you_run.KEY)
    first = _view(app)
    try:
        assert first.before_card.isVisible()
        first._dismiss_before_you_run()            # what a run or preview does as it starts
        app.processEvents()
        assert not first.before_card.isVisible()
        assert before_you_run.is_hidden(open_settings().value(before_you_run.KEY, ""))
    finally:
        first.close()
    second = _view(app)
    try:
        assert not second.before_card.isVisible()
    finally:
        second.close()
        open_settings().remove(before_you_run.KEY)


def test_the_card_has_no_button_and_gives_way_to_the_written_codebook_screen(app):
    open_settings().remove(before_you_run.KEY)
    view = _view(app)
    try:
        assert view.before_card.isVisible()
        assert not view.before_card.findChildren(type(view.run_button))
        view.choice_buttons["codebook"].setChecked(True)
        app.processEvents()
        assert not view.before_card.isVisible()
    finally:
        view.close()
