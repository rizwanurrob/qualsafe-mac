"""Interviews steps 1-3 on the desktop: Add transcripts, Code, Codebook.

Few controls and one filled button per step; the rest under More options.
Add and Code are one screen shown two ways.
"""

from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6", reason="Qt front end not installed")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QUndoStack  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication, QCheckBox, QGroupBox, QLabel, QPushButton, QToolButton)

from core.documents import add_document  # noqa: E402
from core.model import Code  # noqa: E402
from core.project import Project  # noqa: E402
from core.ux import activities, words  # noqa: E402
from qualsafe_qt.services.project_service import ProjectService  # noqa: E402
from qualsafe_qt.views.codebook_view import CodebookView  # noqa: E402
from qualsafe_qt.views.documents_view import STEP_KEYS, DocumentsView  # noqa: E402
from qualsafe_qt.widgets.more_options import MAX_VISIBLE_CONTROLS, visible_controls  # noqa: E402

TRANSCRIPT = ("Interviewer: what has been hardest this term?\n"
              "Respondent: honestly the cost. I did not expect the textbooks to be so much.\n")


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _project(path, documents=1):
    with Project.create(path) as proj:
        for n in range(documents):
            add_document(proj, f"Interview {n + 1:02d}", TRANSCRIPT)
        proj.add_code(Code(code_id="", name="Financial concerns", definition="Cost, tuition, books."))
        proj.add_code(Code(code_id="", name="Sense of belonging", definition="Friends."))
    return path


@pytest.fixture
def service(qapp, tmp_path):
    svc = ProjectService()
    svc.open(_project(tmp_path / "p.qnw"))
    svc.set_analyst_name("Test Analyst")
    yield svc
    svc.close()


@pytest.fixture
def empty_service(qapp, tmp_path):
    svc = ProjectService()
    svc.open(_project(tmp_path / "e.qnw", documents=0))
    yield svc
    svc.close()


@pytest.fixture
def docs(qapp, service):
    v = DocumentsView(service, QUndoStack())
    v.resize(1300, 800)
    v.show()
    v.refresh()
    qapp.processEvents()
    yield v
    v.close()


def mains(widget):
    return [b for b in widget.findChildren(QPushButton) if b.property("main") and b.isVisibleTo(widget)]


# ── the screen serves two steps ─────────────────────────────────────────────

def test_the_two_steps_are_the_first_two_of_interviews():
    assert list(STEP_KEYS) == [s.key for s in activities.get("interviews").steps][:2]


def test_it_starts_on_add_transcripts_and_shows_only_the_list(docs):
    assert docs.current_step() == "add"
    assert docs.library.isVisibleTo(docs) and docs.import_button.isVisibleTo(docs)
    assert not docs.reader.isVisibleTo(docs) and not docs.apply_button.isVisibleTo(docs)


def test_the_code_step_shows_the_reader_and_hides_the_import_button(docs, qapp):
    docs.set_step("code")
    qapp.processEvents()
    assert docs.reader.isVisibleTo(docs) and docs.apply_button.isVisibleTo(docs)
    assert not docs.import_button.isVisibleTo(docs) and not docs.next_button.isVisibleTo(docs)


def test_an_unknown_step_is_ignored(docs):
    docs.set_step("nonsense")
    assert docs.current_step() == "add"


# ── few controls, one filled button ─────────────────────────────────────────

@pytest.mark.parametrize("step", STEP_KEYS)
def test_each_step_shows_at_most_seven_controls(docs, qapp, step):
    docs.set_step(step)
    qapp.processEvents()
    assert len(visible_controls(docs)) <= MAX_VISIBLE_CONTROLS, \
        [(type(w).__name__, getattr(w, "text", lambda: "")()) for w in visible_controls(docs)]


@pytest.mark.parametrize("step", STEP_KEYS)
def test_each_step_has_exactly_one_filled_button(docs, qapp, step):
    docs.set_step(step)
    qapp.processEvents()
    assert len(mains(docs)) == 1, [b.text() for b in mains(docs)]


def test_the_filled_button_is_add_until_there_are_transcripts_then_next(qapp, empty_service):
    v = DocumentsView(empty_service, QUndoStack())
    v.resize(1300, 800)
    v.show()
    v.refresh()
    qapp.processEvents()
    assert mains(v) == [v.import_button]
    assert "No transcripts yet" in v.add_note.text() and not v.next_button.isEnabled()
    v.close()


def test_with_transcripts_next_is_the_filled_button(docs):
    assert mains(docs) == [docs.next_button] and docs.next_button.isEnabled()
    assert docs.add_note.text() == "1 transcript added."


def test_next_asks_the_shell_to_move_and_moves_itself(docs):
    asked = []
    docs.step_requested.connect(asked.append)
    docs.next_button.click()
    assert asked == ["code"] and docs.current_step() == "code"


def test_the_coding_tools_still_exist_and_the_rare_ones_are_folded(docs):
    for name in ("in_vivo_check", "finished_check", "apply_button", "new_code_edit", "code_list",
                 "remove_button", "my_codings"):
        assert hasattr(docs, name), name
    docs.set_step("code")
    assert not docs.code_more.is_expanded()
    assert not docs.in_vivo_check.isVisibleTo(docs) and not docs.finished_check.isVisibleTo(docs)
    docs.code_more.toggle.click()
    assert docs.in_vivo_check.isVisibleTo(docs) and docs.finished_check.isVisibleTo(docs)
    assert docs.code_more.toggle.text() == "More options (5)"        # two tick boxes + the three guide buttons


def test_the_guide_note_says_plainly_where_those_features_are(docs):
    assert "web app" in docs.guide_note.text()


# ── the codebook ────────────────────────────────────────────────────────────

@pytest.fixture
def book(qapp, service):
    v = CodebookView(service, QUndoStack())
    v.resize(1300, 800)
    v.show()
    qapp.processEvents()
    yield v
    v.close()


def test_the_codebook_shows_few_controls(book):
    assert len(visible_controls(book)) <= MAX_VISIBLE_CONTROLS


def test_add_a_code_is_the_filled_button_until_a_code_is_chosen_then_save(book, qapp):
    assert mains(book) == [book.add_button]
    book.tree.setCurrentIndex(book.model.index(0, 0))
    qapp.processEvents()
    assert mains(book) == [book.save_button]


def test_everything_else_is_one_closed_panel_and_nothing_was_removed(book, qapp):
    assert not book.code_more.is_expanded()
    names = [book.tabs.tabText(i) for i in range(book.tabs.count())]
    assert names == ["Colour and notes", "Checks", "Similar codes", "Earlier versions", "Research diary", "Share"]
    book.code_more.toggle.click()
    qapp.processEvents()
    for name in ("import_button", "export_button", "color_button", "memo_list", "find_similar_button",
                 "version_list"):
        assert hasattr(book, name)
    assert book.tabs.isVisibleTo(book)


# ── plain words ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("which", ["add", "code", "book"])
def test_no_banned_or_model_words(docs, book, qapp, which):
    root = book if which == "book" else docs
    if which != "book":
        docs.set_step(which)
    for toggle in root.findChildren(QToolButton):
        if toggle.isCheckable() and toggle.text().startswith("More options"):
            toggle.setChecked(True)
    qapp.processEvents()
    texts = [w.text() for kind in (QLabel, QPushButton, QCheckBox, QToolButton)
             for w in root.findChildren(kind) if w.isVisibleTo(root)]
    texts += [g.title() for g in root.findChildren(QGroupBox) if g.isVisibleTo(root)]
    texts += [root.tabs.tabText(i) for i in range(root.tabs.count())] if which == "book" else []
    for text in texts:
        assert words.find_never(text) == [], text
        assert words.find_replace(text) == [], text
