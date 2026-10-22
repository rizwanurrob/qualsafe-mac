"""
The first thing a new user sees (Qt fork).

`RELEASE_READINESS.md` §2.3 recorded this as a gap and understated it. With no
project open, the Documents screen rendered its three-pane layout empty: an
empty corpus list, an empty reader, an empty code list, an empty codebook. Five
blank boxes, no heading saying what to do, and nothing clickable to any effect.

For a research tool asking people to trust it with interview data, that is an
unpromising first impression, and it is the one every new user got.

What is tested here is the behaviour, not the pixels: that the welcome appears
exactly when there is nothing else to show, that it disappears the moment there
is, and that the sample button produces a project with real content in it. The
last one matters most — the Help walkthroughs are written against that project,
so a sample that fails to build breaks the documentation as well as the button.
"""

from __future__ import annotations

import os
import shutil

import pytest

pytest.importorskip("PySide6", reason="Qt front end not installed")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QElapsedTimer, QThreadPool  # noqa: E402
from PySide6.QtGui import QUndoStack  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core.project import Project  # noqa: E402
from qualsafe_qt.services.project_service import ProjectService  # noqa: E402
from qualsafe_qt.views.documents_view import DocumentsView  # noqa: E402
from qualsafe_qt.widgets.welcome import WelcomePanel  # noqa: E402

WELCOME, CORPUS = 0, 1


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def documents(app):
    service = ProjectService()
    return DocumentsView(service, QUndoStack()), service


class TestTheEmptyState:

    def test_the_welcome_shows_when_no_project_is_open(self, documents):
        view, _service = documents
        assert view._stack.currentIndex() == WELCOME

    def test_the_corpus_replaces_it_when_a_project_opens(self, documents, tmp_path):
        view, service = documents
        path = tmp_path / "p.qnw"
        Project.create(path).close()

        service.open(path)

        assert view._stack.currentIndex() == CORPUS

    def test_it_comes_back_if_the_project_closes(self, documents, tmp_path):
        view, service = documents
        path = tmp_path / "p.qnw"
        Project.create(path).close()
        service.open(path)

        service.close()

        assert view._stack.currentIndex() == WELCOME

    def test_it_is_a_panel_not_a_dialog(self, documents):
        """A modal would have to be dismissed before the program could be looked
        at, which teaches a new user that the first thing this software does is
        get in the way."""
        view, _service = documents
        assert view.welcome.parent() is not None
        assert not view.welcome.isWindow()


class TestItOffersExactlyThreeThings:
    """Open, create, or try the sample. Those are the only three things a person
    can usefully do with no project, so a fourth would be a menu."""

    def test_the_three_actions_are_present(self, app):
        panel = WelcomePanel()
        assert panel.sample_button.text() == "Try the sample project"
        assert panel.open_button.text().startswith("Open a project")
        assert panel.create_button.text().startswith("Create a new project")

    def test_the_sample_is_offered_first(self, app):
        """Reading a guide teaches the vocabulary; opening a project that
        already has coding in it teaches the shape."""
        panel = WelcomePanel()
        buttons = panel.findChildren(type(panel.sample_button))
        labels = [b.text() for b in buttons]
        assert labels.index("Try the sample project") < labels.index("Open a project…")

    def test_each_button_emits_its_own_request(self, app):
        panel = WelcomePanel()
        fired = []
        panel.open_requested.connect(lambda: fired.append("open"))
        panel.create_requested.connect(lambda: fired.append("create"))
        panel.sample_requested.connect(lambda: fired.append("sample"))
        panel.guide_requested.connect(lambda: fired.append("guide"))

        panel.open_button.click()
        panel.create_button.click()
        panel.sample_button.click()

        assert fired == ["open", "create", "sample"]


class TestTheSampleProject:
    """The Help walkthroughs are written against this project, so a sample that
    fails to build breaks the documentation as well as the button."""

    @pytest.fixture()
    def window(self, app, tmp_path, monkeypatch):
        from qualsafe_qt.windows import main_window as module

        samples = tmp_path / "samples"
        monkeypatch.setattr(
            module.Path, "home", staticmethod(lambda: tmp_path), raising=False)
        shutil.rmtree(samples, ignore_errors=True)
        return module.MainWindow()

    def _wait_for_project(self, app, window, seconds: int = 60) -> bool:
        timer = QElapsedTimer()
        timer.start()
        while not window._service.is_open and timer.elapsed() < seconds * 1000:
            app.processEvents()
            QThreadPool.globalInstance().waitForDone(50)
        app.processEvents()
        return window._service.is_open

    def test_one_click_produces_a_project_with_coding_in_it(self, app, window):
        window.documents.welcome.sample_button.click()

        assert self._wait_for_project(app, window), "the sample never opened"
        project = window._service.project
        assert len(project.list_sources()) > 10
        assert len(project.get_codebook()) >= 3
        assert len(project.coding_table()) > 10

    def test_the_welcome_gives_way_to_the_corpus(self, app, window):
        window.documents.welcome.sample_button.click()
        assert self._wait_for_project(app, window)

        assert window.documents._stack.currentIndex() == CORPUS

    def test_the_sample_data_ships_with_the_program(self):
        """The project is built on demand rather than shipped as a `.qnw` — a
        store carries a schema version, and a stale one in the installer would
        need migrating on first run to prove nothing. The CSV it is built from
        does have to be there."""
        from qualsafe_qt.windows.main_window import PROJECT_ROOT

        assert (PROJECT_ROOT / "data" / "sample_survey_education.csv").exists()

    def test_a_missing_csv_warns_rather_than_crashing(self, app, window,
                                                      monkeypatch):
        from qualsafe_qt.windows import main_window as module

        warned = []
        monkeypatch.setattr(module.QMessageBox, "warning",
                            lambda *a, **k: warned.append(a[2]))
        monkeypatch.setattr(module, "PROJECT_ROOT", module.Path("nowhere"))

        # Close first: MainWindow reopens the last project from QSettings, and
        # an earlier test in this class left one there. That reopening is
        # correct behaviour — it is only in the way of this assertion.
        window._service.close()

        window._open_sample_project()

        assert warned and "sample survey" in warned[0]
        assert not window._service.is_open, (
            "a missing sample should leave the program where it was")
