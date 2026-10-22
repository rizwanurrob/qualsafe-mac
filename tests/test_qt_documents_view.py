"""
The coding surface, driven end to end (Qt fork).

`tests/test_app_smoke.py` renders every Streamlit page and catches wiring
breakage; this is the beginning of its replacement for the Qt front end, and it
covers the claim the fork is built on: **drag across text, get an excerpt whose
stored offsets slice the passage the analyst actually selected.**

Everything here is offline, deterministic, and uses a real `.qnw` in a tmp_path
-- no mocks of the store, because the store is exactly what must not break.
"""

from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6", reason="Qt front end not installed")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QTextCursor, QUndoStack  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core.documents import add_document  # noqa: E402
from core.model import Code  # noqa: E402
from core.project import Project  # noqa: E402
from core.span_coding import HUMAN_RATER  # noqa: E402
from qualsafe_qt.services.project_service import ProjectService  # noqa: E402
from qualsafe_qt.views.documents_view import DocumentsView  # noqa: E402
from qualsafe_qt.widgets.document_view import DocumentView, _assign_lanes  # noqa: E402

CR = chr(0x0D)
LF = chr(0x0A)
CRLF = CR + LF

TRANSCRIPT = (
    "Interviewer: what has been hardest this term?" + LF
    + "Respondent: honestly the cost. I did not expect the textbooks to be so much."
    + LF
    + "Interviewer: and outside of money?" + LF
    + "Respondent: making friends took a while. I commute, so I miss a lot."
)


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def project_path(tmp_path):
    path = tmp_path / "project.qnw"
    with Project.create(path) as proj:
        add_document(proj, "Interview 01", TRANSCRIPT)
        proj.add_code(Code(code_id="", name="Financial concerns",
                           definition="Cost, tuition, books."))
        proj.add_code(Code(code_id="", name="Sense of belonging",
                           definition="Friends, fitting in."))
    return path


@pytest.fixture
def service(qapp, project_path):
    svc = ProjectService()
    svc.open(project_path)
    svc.set_analyst_name("Test Analyst")
    yield svc
    svc.close()


@pytest.fixture
def view(qapp, service):
    widget = DocumentsView(service, QUndoStack())
    widget.refresh()
    return widget


# -- the thesis --------------------------------------------------------------
def test_dragging_across_text_codes_exactly_that_passage(view, service):
    """Select a passage with a real cursor, code it, and check the stored
    excerpt slices back to precisely what was selected."""
    assert view.library.rowCount() == 1
    view.library.selectRow(0)

    passage = "the textbooks to be so much"
    start = TRANSCRIPT.index(passage)
    end = start + len(passage)
    view.reader.select_span(start, end)

    assert view.reader.selected_span() == (start, end)
    assert view.reader.selected_text() == passage

    view.code_list.item(0).setSelected(True)
    view._apply_selected_codes()

    excerpts = service.project.list_excerpts(view.reader.source_id)
    assert len(excerpts) == 1
    excerpt = excerpts[0]
    assert (excerpt.char_start, excerpt.char_end) == (start, end)
    assert excerpt.text == passage
    # The invariant, checked the way the engine checks it.
    assert excerpt.verify_offsets(TRANSCRIPT)


def test_selection_made_with_a_real_mouse_cursor_maps_back(view):
    """The same claim, but driving `QTextCursor` directly rather than the
    convenience API -- this is the path a mouse drag actually takes."""
    view.library.selectRow(0)
    editor = view.reader.editor
    word = "commute"
    qt_index = editor.toPlainText().index(word)

    cursor = editor.textCursor()
    cursor.setPosition(qt_index)
    cursor.setPosition(qt_index + len(word), QTextCursor.MoveMode.KeepAnchor)
    editor.setTextCursor(cursor)

    assert view.reader.selected_span() == (TRANSCRIPT.index(word),
                                           TRANSCRIPT.index(word) + len(word))
    assert view.reader.selected_text() == word


def test_coding_a_crlf_document_stores_the_right_passage(qapp, tmp_path):
    """The regression the offset map exists for: in a Windows-newline document
    a naive 1:1 assumption slices the wrong characters."""
    text = ("Interviewer: how was the cost?" + CRLF
            + "Respondent: the tuition was the hard part." + CRLF
            + "Interviewer: thank you.")
    path = tmp_path / "crlf.qnw"
    with Project.create(path) as proj:
        add_document(proj, "CRLF transcript", text)
        proj.add_code(Code(code_id="", name="Financial concerns"))

    service = ProjectService()
    service.open(path)
    try:
        view = DocumentsView(service, QUndoStack())
        view.refresh()
        view.library.selectRow(0)
        assert view.reader.is_codeable

        passage = "the tuition was the hard part"
        start = text.index(passage)
        view.reader.select_span(start, start + len(passage))
        assert view.reader.selected_text() == passage

        view.code_list.item(0).setSelected(True)
        view._apply_selected_codes()

        excerpt = service.project.list_excerpts(view.reader.source_id)[0]
        assert text[excerpt.char_start:excerpt.char_end] == passage
        assert excerpt.verify_offsets(text)
    finally:
        service.close()


# -- undo --------------------------------------------------------------------
def test_undo_removes_the_coding_and_redo_puts_it_back(view, service):
    view.library.selectRow(0)
    start = TRANSCRIPT.index("making friends")
    view.reader.select_span(start, start + len("making friends"))
    view.code_list.item(1).setSelected(True)      # Sense of belonging
    view._apply_selected_codes()

    spans = service.coding_spans(view.reader.source_id, rater_id=HUMAN_RATER)
    assert [s["codes"] for s in spans] == [["Sense of belonging"]]

    view._undo.undo()
    assert service.coding_spans(view.reader.source_id, rater_id=HUMAN_RATER) == []

    view._undo.redo()
    spans = service.coding_spans(view.reader.source_id, rater_id=HUMAN_RATER)
    assert [s["codes"] for s in spans] == [["Sense of belonging"]]


def test_undo_does_not_remove_a_coding_it_did_not_apply(view, service):
    """Re-coding a passage that already carries the code is a no-op, so undoing
    that no-op must leave the original coding alone."""
    view.library.selectRow(0)
    start = TRANSCRIPT.index("the cost")
    view.reader.select_span(start, start + len("the cost"))
    view.code_list.item(0).setSelected(True)
    view._apply_selected_codes()                  # first, real application

    view.reader.select_span(start, start + len("the cost"))
    view._apply_selected_codes()                  # second, skipped as duplicate
    view._undo.undo()                             # undo the no-op

    spans = service.coding_spans(view.reader.source_id, rater_id=HUMAN_RATER)
    assert [s["codes"] for s in spans] == [["Financial concerns"]], \
        "undoing a duplicate application must not delete the original coding"


def test_the_chosen_code_stays_ticked_after_coding_a_passage(view, service):
    """Coding is mostly "apply this same code to the next passage too".

    The code list rebuilds on every store change; an earlier version restored
    the tick by matching the row's *label*, which carries a "1. " shortcut
    prefix, so the selection silently vanished after each application and the
    next Apply did nothing.
    """
    view.library.selectRow(0)
    view.reader.select_span(0, 10)
    view.code_list.item(0).setSelected(True)
    view._apply_selected_codes()

    still_ticked = [item.data(Qt.ItemDataRole.UserRole)
                    for item in view.code_list.selectedItems()]
    assert still_ticked == ["Financial concerns"]

    # ...and the next passage codes without re-ticking anything.
    start = TRANSCRIPT.index("the textbooks")
    view.reader.select_span(start, start + len("the textbooks"))
    view._apply_selected_codes()
    assert len(service.coding_spans(view.reader.source_id, rater_id=HUMAN_RATER)) == 2


def test_removing_a_coding_is_undoable(view, service):
    view.library.selectRow(0)
    start = TRANSCRIPT.index("the cost")
    view.reader.select_span(start, start + len("the cost"))
    view.code_list.item(0).setSelected(True)
    view._apply_selected_codes()

    view.my_codings.setCurrentRow(0)
    view._remove_selected_coding()
    assert service.coding_spans(view.reader.source_id, rater_id=HUMAN_RATER) == []

    view._undo.undo()
    spans = service.coding_spans(view.reader.source_id, rater_id=HUMAN_RATER)
    assert [s["codes"] for s in spans] == [["Financial concerns"]]


# -- keyboard coding ---------------------------------------------------------
def test_number_key_applies_the_nth_code(view, service):
    view.library.selectRow(0)
    start = TRANSCRIPT.index("I commute")
    view.reader.select_span(start, start + len("I commute"))

    view._apply_quick_code(2)                     # "2" -> Sense of belonging

    spans = service.coding_spans(view.reader.source_id, rater_id=HUMAN_RATER)
    assert [s["codes"] for s in spans] == [["Sense of belonging"]]


def test_in_vivo_names_the_code_after_the_passage(view, service):
    view.library.selectRow(0)
    passage = "making friends took a while"
    start = TRANSCRIPT.index(passage)
    view.reader.select_span(start, start + len(passage))
    view.in_vivo_check.setChecked(True)

    view._apply_selected_codes()

    assert passage in service.code_names()


def test_typing_a_new_code_creates_it(view, service):
    view.library.selectRow(0)
    start = TRANSCRIPT.index("I commute")
    view.reader.select_span(start, start + len("I commute"))
    view.new_code_edit.setText("Commuting")

    view._apply_selected_codes()

    assert "Commuting" in service.code_names()
    assert view.new_code_edit.text() == "", "the box should clear after applying"


# -- guards ------------------------------------------------------------------
def test_apply_is_disabled_without_a_selection(view):
    view.library.selectRow(0)
    assert not view.apply_button.isEnabled()
    view.reader.select_span(0, 10)
    assert view.apply_button.isEnabled()


def test_coding_with_no_codes_chosen_is_refused(view, service):
    view.library.selectRow(0)
    view.reader.select_span(0, 20)
    view._apply_selected_codes()                  # nothing ticked, nothing typed
    assert service.coding_spans(view.reader.source_id, rater_id=HUMAN_RATER) == []


def test_a_document_whose_offsets_cannot_be_verified_is_not_codeable(qapp):
    """`is_codeable` is the refusal switch: an unverified map must disable
    coding rather than risk attaching a code to the wrong passage."""
    reader = DocumentView()
    reader.set_document("src_1", "alpha bravo")
    assert reader.is_codeable

    # Simulate a Qt that normalized something this build does not model.
    from qualsafe_qt.text_offsets import OffsetMap

    reader._offsets = OffsetMap("alpha bravo", qt_text="completely different")
    assert not reader.is_codeable


# -- highlights and stripes --------------------------------------------------
def test_overlapping_codings_both_survive_into_the_highlights(view, service):
    view.library.selectRow(0)
    sentence = "Respondent: honestly the cost. I did not expect the textbooks to be so much."
    outer_start = TRANSCRIPT.index(sentence)
    view.reader.select_span(outer_start, outer_start + len(sentence))
    view.code_list.item(0).setSelected(True)
    view._apply_selected_codes()

    inner = "the textbooks"
    inner_start = TRANSCRIPT.index(inner)
    view.reader.select_span(inner_start, inner_start + len(inner))
    view.code_list.clearSelection()
    view.code_list.item(1).setSelected(True)
    view._apply_selected_codes()

    spans = service.coding_spans(view.reader.source_id)
    assert len(spans) == 2
    # Every extra selection is one segment; the nested passage must produce its
    # own segment rather than being swallowed by the outer one.
    selections = view.reader.editor.extraSelections()
    assert len(selections) >= 3, "nesting should split into before / inner / after"


def test_overlapping_spans_get_separate_stripe_lanes():
    spans = [
        {"excerpt_id": "a", "char_start": 0, "char_end": 100, "codes": ["A"]},
        {"excerpt_id": "b", "char_start": 50, "char_end": 150, "codes": ["B"]},
        {"excerpt_id": "c", "char_start": 200, "char_end": 250, "codes": ["C"]},
    ]
    lanes = _assign_lanes(spans)
    assert lanes["a"] != lanes["b"], "overlapping codings need separate lanes"
    assert lanes["c"] == lanes["a"], "a free lane should be reused"


def test_non_overlapping_codings_all_share_one_lane():
    spans = [
        {"excerpt_id": str(i), "char_start": i * 10, "char_end": i * 10 + 5, "codes": ["A"]}
        for i in range(6)
    ]
    assert set(_assign_lanes(spans).values()) == {0}


# -- interoperability --------------------------------------------------------
def test_coding_done_here_is_attributed_to_the_shared_human_rater(view, service):
    """A project must move between the two front ends without splitting one
    analyst into two raters -- so this app codes as `core.span_coding.HUMAN_RATER`."""
    view.library.selectRow(0)
    view.reader.select_span(0, 12)
    view.code_list.item(0).setSelected(True)
    view._apply_selected_codes()

    raters = {r.rater_id: r for r in service.project.list_raters()}
    assert HUMAN_RATER in raters
    assert raters[HUMAN_RATER].kind == "human"
    assert raters[HUMAN_RATER].name == "Test Analyst"


def test_machine_coding_is_never_shown_as_this_analysts_work(view, service, project_path):
    """Invariant #6: machine coding must not be mistakable for human coding."""
    from core.model import CodeApplication, Excerpt, Rater

    source_id = service.document_table()["source_id"].iloc[0]
    proj = service.project
    proj.add_rater(Rater(rater_id="transformer", kind="transformer", name="model"))
    excerpt_id = proj.add_excerpt(Excerpt(
        excerpt_id="", source_id=source_id, text=TRANSCRIPT[0:20],
        char_start=0, char_end=20))
    code_id = proj.find_code_by_name("Financial concerns").code_id
    proj.apply_code(CodeApplication(application_id="", excerpt_id=excerpt_id,
                                    code_id=code_id, coder="transformer",
                                    rater_id="transformer"))
    service.notify_changed()
    view.library.selectRow(0)

    # It shows in the reader (all raters) but not in "your codings".
    assert len(service.coding_spans(source_id)) == 1
    assert service.coding_spans(source_id, rater_id=HUMAN_RATER) == []
    assert view.my_codings.count() == 0


# -- the PII import gate -----------------------------------------------------
def test_import_gate_scans_before_asking_and_reports_what_it_found(qapp, tmp_path, monkeypatch):
    """The gate must show the scan *before* the attestation, or the attestation
    is theatre. Mirrors `app/documents_page._render_import_gate`."""
    folder = tmp_path / "docs"
    folder.mkdir()
    (folder / "clean.txt").write_text(
        "Respondent: the coursework was harder than I expected.", encoding="utf-8")
    (folder / "identified.txt").write_text(
        "Contact me at jane.doe@example.edu or 617-555-0134.", encoding="utf-8")

    path = tmp_path / "gate.qnw"
    with Project.create(path) as proj:
        proj.add_code(Code(code_id="", name="Academic difficulty"))

    service = ProjectService()
    service.open(path)
    try:
        view = DocumentsView(service, QUndoStack())
        view.refresh()

        seen = {}

        def fake_confirm(_parent, paths, findings, unreadable):
            seen["paths"] = [p.name for p in paths]
            seen["findings"] = findings
            seen["unreadable"] = unreadable
            return False                       # analyst declines

        import qualsafe_qt.views.documents_view as module

        monkeypatch.setattr(module, "_confirm_import", fake_confirm)
        monkeypatch.setattr(
            module.QFileDialog, "getExistingDirectory",
            staticmethod(lambda *a, **k: str(folder)))

        view._on_import_clicked()

        assert sorted(seen["paths"]) == ["clean.txt", "identified.txt"]
        signals = {f["signal"] for f in seen["findings"]}
        assert "email address" in signals, f"the scan should flag the address; got {signals}"
        assert "phone-like number" in signals, f"and the phone number; got {signals}"
        # The gate must never print the value it matched, only a masked example.
        for finding in seen["findings"]:
            assert "jane.doe@example.edu" not in str(finding["example_masked"])
        # Declining must import nothing.
        assert service.document_table().empty
    finally:
        service.close()


def test_declining_the_gate_imports_nothing_and_confirming_imports(qapp, tmp_path, monkeypatch):
    folder = tmp_path / "docs"
    folder.mkdir()
    (folder / "one.txt").write_text("Respondent: the cost was the hard part.",
                                    encoding="utf-8")
    path = tmp_path / "gate2.qnw"
    Project.create(path).close()

    service = ProjectService()
    service.open(path)
    try:
        view = DocumentsView(service, QUndoStack())
        view.refresh()
        import qualsafe_qt.views.documents_view as module

        monkeypatch.setattr(
            module.QFileDialog, "getExistingDirectory",
            staticmethod(lambda *a, **k: str(folder)))

        monkeypatch.setattr(module, "_confirm_import",
                            lambda *a, **k: False)
        view._on_import_clicked()
        assert service.document_table().empty

        monkeypatch.setattr(module, "_confirm_import", lambda *a, **k: True)
        view._on_import_clicked()
        assert list(service.document_table()["title"]) == ["one"]
    finally:
        service.close()


# -- the refresh path --------------------------------------------------------
def test_coding_updates_the_corpus_row_without_rebuilding_the_list(view, service):
    """Coding is the hot path, so it updates only the current row.

    An earlier version reran the whole corpus list on every application, which
    reloaded every document's full text just to recompute coverage. This checks
    the cheap path still gets the numbers right.
    """
    view.library.selectRow(0)
    assert view.library.item(0, 2).text() == "0"

    passage = "the textbooks to be so much"
    start = TRANSCRIPT.index(passage)
    view.reader.select_span(start, start + len(passage))
    view.code_list.item(0).setSelected(True)
    view._apply_selected_codes()

    assert view.library.item(0, 2).text() == "1", "the passage count should update"
    coverage = view.library.item(0, 3).text()
    assert coverage.endswith("%") and coverage != "0%", f"coverage should update, got {coverage}"
    # And the document is still selected — the row was updated, not replaced.
    assert view.reader.source_id == view.library.item(0, 0).data(Qt.ItemDataRole.UserRole)


def test_importing_rebuilds_the_corpus_list(qapp, tmp_path, monkeypatch):
    """An import adds rows, so it must do the full refresh the coding path skips."""
    folder = tmp_path / "more"
    folder.mkdir()
    (folder / "extra.txt").write_text("Respondent: the advising was helpful.",
                                      encoding="utf-8")
    path = tmp_path / "grow.qnw"
    with Project.create(path) as proj:
        add_document(proj, "Existing", TRANSCRIPT)

    service = ProjectService()
    service.open(path)
    try:
        view = DocumentsView(service, QUndoStack())
        view.refresh()
        assert view.library.rowCount() == 1

        import qualsafe_qt.views.documents_view as module

        monkeypatch.setattr(
            module.QFileDialog, "getExistingDirectory",
            staticmethod(lambda *a, **k: str(folder)))
        monkeypatch.setattr(module, "_confirm_import", lambda *a, **k: True)
        view._on_import_clicked()

        assert view.library.rowCount() == 2, "the new document should appear in the list"
    finally:
        service.close()


def test_your_codings_never_lists_another_raters_codes_on_a_shared_passage(view, service):
    """The sharp edge behind invariant #6.

    When a model and the analyst code the *same* passage, the excerpt carries
    both codes. "Your codings" must list only the analyst's — filtering spans
    by "did the human touch this passage" would show the model's code as the
    analyst's own.
    """
    from core.model import CodeApplication, Rater

    view.library.selectRow(0)
    passage = "making friends took a while"
    start = TRANSCRIPT.index(passage)
    end = start + len(passage)
    view.reader.select_span(start, end)
    view.code_list.item(1).setSelected(True)          # Sense of belonging
    view._apply_selected_codes()

    # The model codes the very same excerpt with a different code.
    excerpt_id, _codes = service.codings_on_span(view.reader.source_id, start, end)
    proj = service.project
    proj.add_rater(Rater(rater_id="transformer", kind="transformer", name="model"))
    proj.apply_code(CodeApplication(
        application_id="", excerpt_id=excerpt_id,
        code_id=proj.find_code_by_name("Financial concerns").code_id,
        coder="transformer", rater_id="transformer"))
    service.notify_changed()

    assert view.my_codings.count() == 1
    listed = view.my_codings.item(0).text()
    assert "Sense of belonging" in listed
    assert "Financial concerns" not in listed, \
        "a model's code on a shared passage must not be listed as the analyst's"


def test_finishing_a_document_is_recorded_for_agreement(view, service):
    """Span-coding agreement compares only finished documents (review F4), so
    the reader records it -- and unticking takes it back out."""
    view.library.selectRow(0)
    source_id = view._source_id
    assert source_id and view.finished_check.isEnabled()
    assert not view.finished_check.isChecked()

    view.finished_check.setChecked(True)
    assert service.document_finished(source_id)
    view.finished_check.setChecked(False)
    assert not service.document_finished(source_id)
