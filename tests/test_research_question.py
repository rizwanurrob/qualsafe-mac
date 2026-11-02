"""The research question (book-audit F2): kept with the project, edited on the Codebook screen, shown while coding."""

from __future__ import annotations

import os

import pytest

from core import research_question
from core.project import Project


def test_clean_keeps_one_run_of_words_within_the_limit():
    assert research_question.clean("  What   helps\n first-year  students? ") == "What helps first-year students?"
    assert len(research_question.clean("x " * 2000)) == research_question.MAX_CHARS
    assert research_question.clean(None) == ""


def test_the_question_is_kept_in_the_project_file(tmp_path):
    path = tmp_path / "p.qnw"
    project = Project.create(path) if hasattr(Project, "create") else Project(path)
    assert research_question.get(project) == ""
    research_question.set(project, "What gets in the way of belonging?")
    project.close()
    again = Project.open(path) if hasattr(Project, "open") else Project(path)
    assert research_question.get(again) == "What gets in the way of belonging?"
    again.close()


pytest.importorskip("PySide6", reason="Qt front end not installed")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QUndoStack  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from qualsafe_qt.services.project_service import ProjectService  # noqa: E402
from qualsafe_qt.views.codebook_view import CodebookView  # noqa: E402
from qualsafe_qt.views.documents_view import DocumentsView  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_typing_it_on_the_codebook_screen_saves_it_and_the_reader_shows_it(app, tmp_path):
    service = ProjectService()
    service.create(tmp_path / "q.qnw")
    codebook = CodebookView(service, QUndoStack())
    docs = DocumentsView(service, QUndoStack())
    codebook.show()
    docs.show()
    app.processEvents()
    assert docs.question_label.isHidden()
    codebook.question_edit.setText("What helps first-year students stay?")
    codebook.question_edit.editingFinished.emit()
    app.processEvents()
    assert service.research_question() == "What helps first-year students stay?"
    assert not docs.question_label.isHidden() and "stay?" in docs.question_label.text()
    codebook.close()
    docs.close()
    service.close()


def test_the_box_is_off_when_no_project_is_open(app):
    service = ProjectService()
    codebook = CodebookView(service, QUndoStack())
    assert not codebook.question_edit.isEnabled()
    codebook.close()


# -- the web build --------------------------------------------------------------------------------------
from pathlib import Path  # noqa: E402

from tests import webkit  # noqa: E402


def test_the_web_documents_page_shows_the_question_when_there_is_one(tmp_path, monkeypatch):
    monkeypatch.setenv("QNW_SETTINGS_DIR", str(tmp_path / "settings"))
    from app import documents_page

    shown = []
    monkeypatch.setattr(documents_page.st, "markdown", lambda text, *a, **k: shown.append(text))
    store = tmp_path / "w.qnw"
    project = Project.create(store)
    documents_page._show_research_question(project)
    assert shown == []
    research_question.set(project, "What helps students stay?")
    documents_page._show_research_question(project)
    project.close()
    assert shown == ["**Research question:** What helps students stay?"]
