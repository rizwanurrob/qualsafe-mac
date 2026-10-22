"""
The codebook screen: the tree, drag-to-reparent, merge/delete, health, history.

The Qt counterpart of the Streamlit codebook page. The parts worth testing are
the ones where this front end does something the Streamlit build cannot (a real
hierarchy you can drag) and the ones where getting it wrong destroys work
(merge, delete, restore).

Offline and deterministic: the similarity check is driven through an injected
embedding function, never a real model.
"""

from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6", reason="Qt front end not installed")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QMimeData, QModelIndex, Qt  # noqa: E402
from PySide6.QtGui import QUndoStack  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core.documents import add_document  # noqa: E402
from core.model import Code  # noqa: E402
from core.project import Project  # noqa: E402
from qualsafe_qt.models.codebook_model import CODE_MIME, CodebookModel  # noqa: E402
from qualsafe_qt.services.project_service import ProjectService  # noqa: E402
from qualsafe_qt.views.codebook_view import CodebookView  # noqa: E402

TEXT = ("Respondent: the tuition was the hard part, and the books on top. "
        "Making friends took most of the first term.")


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def project_path(tmp_path):
    path = tmp_path / "codebook.qnw"
    with Project.create(path) as proj:
        add_document(proj, "Interview 01", TEXT)
        proj.add_code(Code(code_id="c_money", name="Money",
                           definition="Anything financial."))
        proj.add_code(Code(code_id="c_cost", name="Cost worry",
                           definition="Worry about paying for things."))
        proj.add_code(Code(code_id="c_belong", name="Belonging"))
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
    return CodebookView(service, QUndoStack())


def _drop(model, dragged_id, target_id):
    """Simulate dropping `dragged_id` onto `target_id` ("" = the root)."""
    data = QMimeData()
    data.setData(CODE_MIME, dragged_id.encode("utf-8"))
    parent = model.index_for_code(target_id) if target_id else QModelIndex()
    can = model.canDropMimeData(data, Qt.DropAction.MoveAction, -1, -1, parent)
    if can:
        model.dropMimeData(data, Qt.DropAction.MoveAction, -1, -1, parent)
    return can


# -- the tree ----------------------------------------------------------------
def test_the_codebook_renders_as_a_tree(view, service):
    assert view.model.rowCount() == 3, "three top-level codes to start"
    service.set_code_parent("c_cost", "c_money")
    view.refresh()

    money = view.model.index_for_code("c_money")
    assert view.model.rowCount(money) == 1
    assert view.model.rowCount() == 2, "'Cost worry' is no longer top-level"
    assert view.model.data(view.model.index(0, 0, money)) == "Cost worry"


def test_siblings_are_ordered_by_name_not_insertion(view, service):
    """`get_codebook()` returns insertion order, which is meaningless to read."""
    names = [view.model.data(view.model.index(row, 0)) for row in range(view.model.rowCount())]
    assert names == sorted(names, key=str.lower)


def test_a_code_whose_parent_was_deleted_shows_at_the_top_level(view, service):
    """An orphan must stay reachable so it can be fixed, not vanish."""
    service.set_code_parent("c_cost", "c_money")
    service.project.delete_code("c_money")
    view.refresh()

    assert view.model.index_for_code("c_cost").isValid()
    top_level = [view.model.data(view.model.index(r, 0))
                 for r in range(view.model.rowCount())]
    assert "Cost worry" in top_level


def test_the_uses_column_shows_application_counts(view, service):
    from core.span_coding import apply_codes_to_span

    source_id = service.document_table()["source_id"].iloc[0]
    apply_codes_to_span(service.project, source_id, 0, 20, ["Money"])
    view.refresh()

    index = view.model.index_for_code("c_money")
    assert view.model.data(view.model.index(index.row(), 1, index.parent())) == "1"


# -- drag to reparent --------------------------------------------------------
def test_dragging_a_code_onto_another_nests_it(view, service):
    assert _drop(view.model, "c_cost", "c_money")
    assert service.get_code("c_cost").parent_id == "c_money"


def test_dragging_to_empty_space_promotes_a_code_to_the_top_level(view, service):
    service.set_code_parent("c_cost", "c_money")
    view.refresh()
    assert _drop(view.model, "c_cost", "")
    assert service.get_code("c_cost").parent_id is None


def test_a_reparent_is_undoable(view, service):
    _drop(view.model, "c_cost", "c_money")
    assert service.get_code("c_cost").parent_id == "c_money"
    view._undo.undo()
    assert service.get_code("c_cost").parent_id is None


def test_a_cyclic_drop_is_refused_before_it_happens(view, service):
    """The cursor should say "no" during the drag, not raise after the drop."""
    service.set_code_parent("c_cost", "c_money")
    view.refresh()
    # Dropping the parent onto its own child would make a cycle.
    assert not _drop(view.model, "c_money", "c_cost")
    assert service.get_code("c_money").parent_id is None


def test_a_code_cannot_be_dropped_onto_itself(view):
    assert not _drop(view.model, "c_money", "c_money")


def test_dropping_a_code_where_it_already_is_does_nothing(view, service):
    service.set_code_parent("c_cost", "c_money")
    view.refresh()
    assert not _drop(view.model, "c_cost", "c_money")


def test_the_model_never_writes_to_the_store_itself(view, service):
    """The model emits a request; the view turns it into an undoable command.

    Keeps the "no widget touches the store" rule and keeps a structural edit on
    the undo stack.
    """
    seen = []
    model = CodebookModel()
    model.set_codebook(service.codebook(), service.code_frequency())
    model.reparent_requested.connect(lambda a, b: seen.append((a, b)))

    _drop(model, "c_cost", "c_money")

    assert seen == [("c_cost", "c_money")]
    assert service.get_code("c_cost").parent_id is None, \
        "the model must not have written anything"


# -- editing -----------------------------------------------------------------
def test_editing_a_code_is_undoable(view, service):
    view._select_code("c_belong")
    view.name_edit.setText("Sense of belonging")
    view.definition_edit.setPlainText("Feeling connected on campus.")
    view._save_code()

    code = service.get_code("c_belong")
    assert code.name == "Sense of belonging"
    assert code.definition == "Feeling connected on campus."

    view._undo.undo()
    code = service.get_code("c_belong")
    assert code.name == "Belonging"
    assert code.definition == ""


def test_adding_a_code_is_undoable(view, service, monkeypatch):
    import qualsafe_qt.views.codebook_view as module

    monkeypatch.setattr(module.QInputDialog, "getText",
                        staticmethod(lambda *a, **k: ("Time pressure", True)))
    view._add_code(None)
    assert "Time pressure" in service.code_names()

    view._undo.undo()
    assert "Time pressure" not in service.code_names()


def test_a_code_cannot_be_saved_with_an_empty_name(view, service, monkeypatch):
    import qualsafe_qt.views.codebook_view as module

    warned = []
    monkeypatch.setattr(module.QMessageBox, "warning",
                        staticmethod(lambda *a, **k: warned.append(a)))
    view._select_code("c_belong")
    view.name_edit.setText("   ")
    view._save_code()

    assert warned, "an empty name should be refused"
    assert service.get_code("c_belong").name == "Belonging"


# -- merge and delete --------------------------------------------------------
def test_merge_moves_applications_and_clears_the_undo_stack(view, service, monkeypatch):
    """Merge is not undoable, and must not leave stale undo entries behind.

    A codebook snapshot restores the *code*, not the applications that were
    reassigned — so an "undo" would be a lie about what came back.
    """
    from core.span_coding import apply_codes_to_span

    import qualsafe_qt.views.codebook_view as module

    source_id = service.document_table()["source_id"].iloc[0]
    apply_codes_to_span(service.project, source_id, 0, 20, ["Cost worry"])
    view.refresh()
    view._undo.push(_NoopCommand())
    assert view._undo.count() == 1

    monkeypatch.setattr(module.QMessageBox, "warning",
                        staticmethod(lambda *a, **k: module.QMessageBox.StandardButton.Yes))
    view._do_merge("c_cost", "c_money")

    assert service.get_code("c_cost") is None
    assert service.code_frequency().get("c_money") == 1, \
        "the application should have moved to the surviving code"
    assert view._undo.count() == 0, "stale undo entries must be cleared"


def test_merge_can_be_cancelled(view, service, monkeypatch):
    import qualsafe_qt.views.codebook_view as module

    monkeypatch.setattr(module.QMessageBox, "warning",
                        staticmethod(lambda *a, **k: module.QMessageBox.StandardButton.Cancel))
    view._do_merge("c_cost", "c_money")
    assert service.get_code("c_cost") is not None


def test_delete_can_be_cancelled(view, service, monkeypatch):
    import qualsafe_qt.views.codebook_view as module

    monkeypatch.setattr(module.QMessageBox, "warning",
                        staticmethod(lambda *a, **k: module.QMessageBox.StandardButton.Cancel))
    view._delete_code("c_belong")
    assert service.get_code("c_belong") is not None


def test_merge_snapshots_the_codebook_so_history_can_recover_the_code(view, service,
                                                                     monkeypatch):
    import qualsafe_qt.views.codebook_view as module

    monkeypatch.setattr(module.QMessageBox, "warning",
                        staticmethod(lambda *a, **k: module.QMessageBox.StandardButton.Yes))
    before = len(service.list_codebook_versions())
    view._do_merge("c_cost", "c_money")
    assert len(service.list_codebook_versions()) > before


# -- health ------------------------------------------------------------------
def test_health_reports_undefined_and_unapplied_codes(view):
    view.refresh()
    text = view.health_label.text()
    assert "Never applied" in text
    assert "Belonging" in text, "the code with no definition should be named"
    assert "Missing a definition" in text


def test_health_reports_a_clean_codebook_as_clean(qapp, tmp_path):
    from core.span_coding import apply_codes_to_span

    path = tmp_path / "clean.qnw"
    with Project.create(path) as proj:
        add_document(proj, "D", TEXT)
        proj.add_code(Code(code_id="c1", name="Money", definition="Financial."))

    service = ProjectService()
    service.open(path)
    try:
        source_id = service.document_table()["source_id"].iloc[0]
        # Twice: `codebook_health` flags a code applied exactly once as a
        # singleton ("may be too specific"), so one application is not clean.
        apply_codes_to_span(service.project, source_id, 0, 20, ["Money"])
        apply_codes_to_span(service.project, source_id, 25, 40, ["Money"])
        view = CodebookView(service, QUndoStack())
        view.refresh()
        assert "No issues found" in view.health_label.text()
    finally:
        service.close()


# -- version history ---------------------------------------------------------
def test_restoring_a_version_backs_up_the_project_first(view, service, monkeypatch,
                                                        project_path):
    """Invariant #8: destructive operations back up the `.qnw` first."""
    import qualsafe_qt.views.codebook_view as module
    from core.backups import list_backups

    service.tag_codebook_version("before the change")
    view.refresh()
    version_id = view.version_list.item(0).data(Qt.ItemDataRole.UserRole)

    service.add_code("Added later")
    assert "Added later" in service.code_names()
    backups_before = len(list_backups(project_path))

    monkeypatch.setattr(module.QMessageBox, "warning",
                        staticmethod(lambda *a, **k: module.QMessageBox.StandardButton.Yes))
    view.version_list.setCurrentRow(0)
    # The row may have moved after the refresh; select by the id we captured.
    for row in range(view.version_list.count()):
        if view.version_list.item(row).data(Qt.ItemDataRole.UserRole) == version_id:
            view.version_list.setCurrentRow(row)
    view._restore_version()

    assert len(list_backups(project_path)) > backups_before, \
        "a restore must back up the store first"
    assert "Added later" not in service.code_names()


def test_tagging_records_a_version(view, service, monkeypatch):
    import qualsafe_qt.views.codebook_view as module

    monkeypatch.setattr(module.QInputDialog, "getText",
                        staticmethod(lambda *a, **k: ("spring reorg", True)))
    before = len(service.list_codebook_versions())
    view._tag_version()
    versions = service.list_codebook_versions()
    assert len(versions) == before + 1
    assert versions[0]["note"] == "spring reorg"


# -- similarity suggestions --------------------------------------------------
def test_similar_pairs_are_listed_but_never_merged_automatically(view, service):
    """The suggestion path, driven with a stub embedder — no model involved."""
    import numpy as np

    from analysis.code_similarity import similar_code_pairs

    codes = service.codebook()
    by_name = {c.name: i for i, c in enumerate(codes)}
    # Make 'Money' and 'Cost worry' near-identical vectors, 'Belonging' distant.
    vectors = np.zeros((len(codes), 3))
    vectors[by_name["Money"]] = [1.0, 0.0, 0.0]
    vectors[by_name["Cost worry"]] = [0.99, 0.14, 0.0]
    vectors[by_name["Belonging"]] = [0.0, 0.0, 1.0]

    pairs = similar_code_pairs(codes, lambda _texts: vectors, threshold=0.80)
    view._on_similar_found(pairs)

    assert view.suggestions_list.count() == 1
    listed = view.suggestions_list.item(0).text()
    assert "Money" in listed and "Cost worry" in listed
    # Nothing merged: both codes still there until the analyst confirms.
    assert service.get_code("c_money") is not None
    assert service.get_code("c_cost") is not None


def test_a_missing_model_is_explained_not_crashed(view, monkeypatch):
    import qualsafe_qt.views.codebook_view as module

    shown = []
    monkeypatch.setattr(module.QMessageBox, "information",
                        staticmethod(lambda _p, _t, msg, *a, **k: shown.append(msg)))
    view._on_similar_failed("The model 'x' is not in your local cache", "traceback")
    assert shown and "not in your local cache" in shown[0]


# -- YAML exchange -----------------------------------------------------------
def test_codebook_yaml_round_trips_through_the_view(view, service, tmp_path,
                                                    monkeypatch):
    import qualsafe_qt.views.codebook_view as module

    service.set_code_parent("c_cost", "c_money")
    view.refresh()
    out = tmp_path / "cb.yaml"
    monkeypatch.setattr(module.QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(out), "")))
    view._export_yaml()
    assert out.exists() and "Cost worry" in out.read_text(encoding="utf-8")

    # Import into a fresh project and check the hierarchy came with it.
    other = tmp_path / "other.qnw"
    Project.create(other).close()
    second = ProjectService()
    second.open(other)
    try:
        second_view = CodebookView(second, QUndoStack())
        monkeypatch.setattr(module.QFileDialog, "getOpenFileName",
                            staticmethod(lambda *a, **k: (str(out), "")))
        second_view._import_yaml()
        names = second.code_names()
        assert {"Money", "Cost worry", "Belonging"} <= set(names)
        cost = next(c for c in second.codebook() if c.name == "Cost worry")
        money = next(c for c in second.codebook() if c.name == "Money")
        assert cost.parent_id == money.code_id, "the hierarchy should survive"
    finally:
        second.close()


# -- shared state with the documents screen ----------------------------------
def test_a_code_created_while_coding_appears_in_the_codebook(qapp, service):
    """Both screens share one ProjectService, so this needs no manual sync."""
    from qualsafe_qt.views.documents_view import DocumentsView

    undo = QUndoStack()
    documents = DocumentsView(service, undo)
    codebook = CodebookView(service, undo)
    documents.refresh()
    documents.library.selectRow(0)

    documents.reader.select_span(0, 12)
    documents.new_code_edit.setText("Invented while reading")
    documents._apply_selected_codes()

    assert codebook.model.index_for_code(
        next(c.code_id for c in service.codebook()
             if c.name == "Invented while reading")).isValid()


class _NoopCommand:
    """A stand-in undo entry, to prove the stack gets cleared."""

    def __new__(cls):
        from PySide6.QtGui import QUndoCommand

        command = QUndoCommand("noop")
        return command


# -- coding rules (Saldaña 2013, p. 25) --------------------------------------
def test_the_code_editor_shows_and_saves_the_coding_rules(view, service):
    """A codebook entry is more than a definition: when to use the code, when to
    leave it out, and examples. The engine stored them; the desktop never showed
    them, so a desktop-only analyst could not write the line that lets a second
    coder apply the code the same way."""
    view._select_code("c_money")
    assert view.use_when_edit.toPlainText() == ""
    view.use_when_edit.setPlainText("The person says they cannot pay for something.")
    view.leave_out_edit.setPlainText("A general remark about money with no hardship.")
    view.examples_edit.setPlainText("I couldn't pay rent.\n\n  The books cost too much.  \n")
    view._save_code()

    code = service.get_code("c_money")
    assert code.inclusion_criteria == "The person says they cannot pay for something."
    assert code.exclusion_criteria == "A general remark about money with no hardship."
    assert code.examples == ["I couldn't pay rent.", "The books cost too much."]

    # Reselecting reloads them from the store, so they survived the round trip.
    view._select_code("c_cost")
    view._select_code("c_money")
    assert view.leave_out_edit.toPlainText().startswith("A general remark")
    assert view.examples_edit.toPlainText().splitlines() == [
        "I couldn't pay rent.", "The books cost too much."]


def test_saving_a_rename_does_not_log_a_rules_change(view, service):
    """Only changed rules are written, so the audit trail does not fill with
    entries about rules nobody touched."""
    view._select_code("c_belong")
    view.name_edit.setText("Sense of belonging")
    view._save_code()
    kinds = [e["kind"] for e in service.project.list_events()]
    assert "code_criteria_changed" not in kinds

    view.leave_out_edit.setPlainText("Friendly staff with no sense of being included.")
    view._save_code()
    kinds = [e["kind"] for e in service.project.list_events()]
    assert kinds.count("code_criteria_changed") == 1


def test_the_rules_are_logged_without_the_example_text(view, service):
    """Examples are often pasted responses; the log records how many, never the
    words (core/project.py)."""
    view._select_code("c_money")
    view.examples_edit.setPlainText("a very identifying sentence")
    view._save_code()
    events = [e for e in service.project.list_events()
              if e["kind"] == "code_criteria_changed"]
    assert events and "identifying" not in str(events[-1])


def test_the_rules_editors_are_off_until_a_code_is_chosen(view):
    view._select_code("")
    for widget in (view.use_when_edit, view.leave_out_edit, view.examples_edit):
        assert not widget.isEnabled()


# -- the project diary (Saldaña 2013, pp. 43-49; Silverman 2017, Tip 58) -----
def test_a_diary_note_is_kept_as_a_project_memo_and_listed(view, service):
    assert view.diary_list.count() == 0
    service.add_memo("project", None, "My position\nI was first in my family too.")
    assert view.diary_list.count() == 1
    text = view.diary_list.item(0).text()
    assert "My position" in text and "first in my family" in text
    assert view.diary_list.item(0).toolTip().startswith("My position")


def test_adding_a_diary_note_through_the_dialog(view, service, monkeypatch):
    import qualsafe_qt.views.codebook_view as module

    class _Accepted:
        def __init__(self, *_a, **_k):
            pass

        def exec(self):
            return module.QDialog.DialogCode.Accepted

        def topic(self):
            return "An ethical worry"

        def text(self):
            return "Not sure whether to quote the third interview."

    monkeypatch.setattr(module, "_DiaryNoteDialog", _Accepted)
    view._add_diary_note()

    memos = service.list_memos("project")
    assert len(memos) == 1
    assert memos[0].text == "An ethical worry\nNot sure whether to quote the third interview."
    assert memos[0].target_id is None
    assert view.diary_list.count() == 1


def test_an_empty_diary_note_is_not_saved(view, service, monkeypatch):
    import qualsafe_qt.views.codebook_view as module

    class _Blank:
        def __init__(self, *_a, **_k):
            pass

        def exec(self):
            return module.QDialog.DialogCode.Accepted

        def topic(self):
            return "My position"

        def text(self):
            return ""

    monkeypatch.setattr(module, "_DiaryNoteDialog", _Blank)
    view._add_diary_note()
    assert service.list_memos("project") == []


def test_a_diary_note_can_be_deleted(view, service):
    service.add_memo("project", None, "What to do next\nRecode the first six.")
    view.diary_list.setCurrentRow(0)
    view.diary_list.item(0).setSelected(True)
    view._delete_diary_note()
    assert service.list_memos("project") == []
    assert view.diary_list.count() == 0


def test_the_diary_dialog_offers_all_eleven_prompts_and_shows_the_question(qapp):
    import qualsafe_qt.views.codebook_view as module
    from core.ux.guide import MEMO_TOPICS

    dialog = module._DiaryNoteDialog()
    assert dialog.topic_box.count() == len(MEMO_TOPICS) == 11
    dialog.topic_box.setCurrentIndex(2)
    assert MEMO_TOPICS[2][1] in dialog.prompt_label.text()
    dialog.text_edit.setPlainText("  my note  ")
    assert dialog.text() == "my note"


def test_diary_notes_do_not_appear_among_a_codes_memos(view, service):
    service.add_memo("project", None, "My position\nx")
    view._select_code("c_money")
    assert view.memo_list.count() == 0


def test_the_audit_trail_carries_a_diary_note_only_when_text_is_opted_in(service):
    """Memos can quote a participant. The record that a note was written is in the
    log either way; its words only if the analyst ticks the box."""
    from exports.audit_trail import audit_trail_frame

    service.add_memo("project", None, "An ethical worry\nParticipant 3 named a teacher.")
    without = audit_trail_frame(service.project, include_memo_text=False)
    assert "Participant 3 named a teacher" not in without.to_string()
    with_text = audit_trail_frame(service.project, include_memo_text=True)
    assert "Participant 3 named a teacher" in with_text.to_string()
