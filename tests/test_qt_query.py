"""
Query & Synthesis: boolean queries, matrices, the framework matrix, cases.

`analysis.query` and `analysis.framework` are tested upstream. What this file
guards is the view's own work, and two claims that matter methodologically:

* **The query unit changes the answer**, so the control must really reach the
  engine — a query whose unit the analyst did not choose is a finding they
  cannot defend.
* **A drafted cell is a draft.** The LLM path verifies every quote against the
  source, reports what it dropped, and saves nothing until the analyst does.
  Tested with an injected generator, so no Ollama is involved.
"""

from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6", reason="Qt front end not installed")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pandas as pd  # noqa: E402
from PySide6.QtGui import QUndoStack  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core.documents import add_document  # noqa: E402
from core.model import Case, Code, CodeApplication, Descriptor, Excerpt, Rater  # noqa: E402
from core.project import Project  # noqa: E402
from qualsafe_qt.services.project_service import ProjectService  # noqa: E402
from qualsafe_qt.views.query_view import SAVED_QUERY_TYPE, QueryView  # noqa: E402

DOC_A = ("The tuition was the hard part. "                       # 0-31
         "I made friends in the spring though. "                 # 31-68
         "My advisor was hard to reach.")                        # 68-97
DOC_B = ("Money was never the issue for me. "
         "But I never found a group I belonged to.")


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def project(tmp_path):
    """Two documents in two cases, coded so queries have something to bite on."""
    path = tmp_path / "query.qnw"
    with Project.create(path) as proj:
        a = add_document(proj, "Interview 01", DOC_A)
        b = add_document(proj, "Interview 02", DOC_B)
        proj.add_rater(Rater(rater_id="human_primary", kind="human"))
        codes = {n: proj.add_code(Code(code_id="", name=n))
                 for n in ("Cost", "Belonging", "Advising")}

        case_a = proj.add_case(Case(case_id="", name="Ama"))
        case_b = proj.add_case(Case(case_id="", name="Ben"))
        proj.assign_source_to_case(case_a, a)
        proj.assign_source_to_case(case_b, b)
        proj.set_descriptor(Descriptor(source_id=a, key="Program", value="Nursing"))
        proj.set_descriptor(Descriptor(source_id=b, key="Program", value="Business"))

        def code(source_id, start, end, names):
            excerpt_id = proj.add_excerpt(Excerpt(
                excerpt_id="", source_id=source_id,
                text=(DOC_A if source_id == a else DOC_B)[start:end],
                char_start=start, char_end=end))
            for name in names:
                proj.apply_code(CodeApplication(
                    application_id="", excerpt_id=excerpt_id, code_id=codes[name],
                    coder="human", rater_id="human_primary"))
            return excerpt_id

        code(a, 0, 31, ["Cost"])                 # "The tuition was the hard part."
        code(a, 31, 68, ["Belonging"])           # friends, same document, not same passage
        code(a, 68, 97, ["Advising"])
        code(b, 0, 34, ["Cost", "Belonging"])    # both codes on ONE passage
    return path


@pytest.fixture
def service(qapp, project):
    svc = ProjectService()
    svc.open(project)
    yield svc
    svc.close()


@pytest.fixture
def view(qapp, service):
    return QueryView(service, QUndoStack())


# -- the unit really changes the answer --------------------------------------
def test_and_at_passage_level_needs_one_passage(view):
    view.query_edit.setText("Cost AND Belonging")
    view.unit.setCurrentIndex(0)                 # the same passage
    view.run_query()
    assert "1</b> passage(s) match" in view.query_summary.text()


def test_the_same_query_at_document_level_matches_more(view):
    """In Interview 01 the two codes are on different passages of one document —
    invisible at passage level, a match at document level. This is why the unit
    control is prominent."""
    view.query_edit.setText("Cost AND Belonging")
    view.unit.setCurrentIndex(1)                 # the same document
    view.run_query()
    assert "2</b> document(s) match" in view.query_summary.text()


def test_not_excludes(view):
    view.query_edit.setText("Cost AND NOT Belonging")
    view.unit.setCurrentIndex(1)
    view.run_query()
    assert "0</b> document(s) match" in view.query_summary.text()


def test_an_unknown_code_is_warned_about_not_silently_empty(view):
    view.query_edit.setText("Nonexistent")
    view.run_query()
    assert not view.query_warning.isHidden()
    assert "Nonexistent" in view.query_warning.text()


def test_a_malformed_query_reports_the_problem(view):
    view.query_edit.setText("Cost AND")
    view.run_query()
    assert not view.query_warning.isHidden()
    assert view.results_model.frame.empty


def test_results_list_the_passages_with_their_codes(view):
    view.query_edit.setText("Cost")
    view.unit.setCurrentIndex(0)
    view.run_query()
    frame = view.results_model.frame
    assert not frame.empty
    assert set(frame.columns) == {"passage", "codes"}, \
        "navigation columns must not be shown to the reader"
    assert any("tuition" in p for p in frame["passage"])


def test_double_clicking_a_result_opens_it_in_the_reader(view, service):
    emitted = []
    view.open_in_reader.connect(lambda s, a, b: emitted.append((s, a, b)))
    view.query_edit.setText("Cost")
    view.unit.setCurrentIndex(0)
    view.run_query()

    class _Index:
        def row(self):
            return 0

    view._open_result(_Index())
    assert len(emitted) == 1
    source_id, start, end = emitted[0]
    text = service.document_text(source_id)
    assert text[start:end].strip(), "the offsets should slice real text"


# -- saved queries -----------------------------------------------------------
def test_a_query_can_be_saved_and_loaded(view, service, monkeypatch):
    import qualsafe_qt.views.query_view as module

    monkeypatch.setattr(module.QInputDialog, "getText",
                        staticmethod(lambda *a, **k: ("Cost without belonging", True)))
    view.query_edit.setText("Cost AND NOT Belonging")
    view._save_query()

    saved = service.list_memos(SAVED_QUERY_TYPE)
    assert len(saved) == 1
    assert saved[0].text.startswith("Cost without belonging\n")

    view.refresh()
    view.query_edit.clear()
    view.saved_queries.setCurrentIndex(0)
    view._load_saved_query()
    assert view.query_edit.text() == "Cost AND NOT Belonging"


# -- matrix ------------------------------------------------------------------
def test_code_by_code_matrix(view):
    index = view.matrix_axis.findData("code")
    view.matrix_axis.setCurrentIndex(index)
    frame = view.matrix_model.frame
    assert not frame.empty
    assert frame.loc["Cost", "Belonging"] == 1, "they share one passage"


def test_code_by_case_matrix(view):
    view.matrix_axis.setCurrentIndex(view.matrix_axis.findData("case"))
    frame = view.matrix_model.frame
    assert not frame.empty
    assert set(frame.columns) == {"Ama", "Ben"}


def test_code_by_descriptor_matrix(view):
    view.matrix_axis.setCurrentIndex(view.matrix_axis.findData("descriptor"))
    frame = view.matrix_model.frame
    assert not frame.empty
    assert set(frame.columns) == {"Nursing", "Business"}


# -- framework matrix --------------------------------------------------------
def test_the_framework_grid_has_a_row_per_case(view):
    frame = view.fw_grid_model.frame
    assert not frame.empty
    assert set(frame["case"]) == {"Ama", "Ben"}
    assert "Cost" in frame.columns


def test_a_cell_lists_the_passages_behind_it(view):
    view.fw_case.setCurrentIndex(view.fw_case.findText("Ama"))
    view.fw_code.setCurrentText("Cost")
    assert "1</b> passage(s)" in view.fw_cell_label.text()
    assert "tuition" in view.fw_passages.toPlainText()


def test_saving_a_cell_summary_persists_it(view, service):
    view.fw_case.setCurrentIndex(view.fw_case.findText("Ama"))
    view.fw_code.setCurrentText("Cost")
    view.fw_summary.setPlainText("Ama framed cost as the decisive barrier.")
    view._save_cell()

    case_id = view.fw_case.currentData()
    stored = service.cell_summary(case_id, "Cost")
    assert stored is not None
    assert "decisive barrier" in stored.text


def test_clicking_the_grid_selects_that_cell(view):
    frame = view.fw_grid_model.frame
    column = list(frame.columns).index("Cost")

    class _Index:
        def row(self):
            return 0

        def column(self):
            return column

    view._select_cell_from_grid(_Index())
    assert view.fw_code.currentText() == "Cost"
    assert view.fw_case.currentText() == str(frame.iat[0, 0])


def test_uncased_material_can_be_included(view, service):
    """Material in no case must not be silently invisible."""
    source_id = add_document(service.project, "Orphan", "A stray note about cost.")
    excerpt_id = service.project.add_excerpt(Excerpt(
        excerpt_id="", source_id=source_id, text="cost", char_start=20, char_end=24))
    service.project.apply_code(CodeApplication(
        application_id="", excerpt_id=excerpt_id,
        code_id=service.project.find_code_by_name("Cost").code_id,
        coder="human", rater_id="human_primary"))
    service.notify_changed()

    view.fw_uncased.setChecked(True)
    from analysis.framework import UNCASED

    assert UNCASED in set(view.fw_grid_model.frame["case"])


# -- the LLM draft -----------------------------------------------------------
def test_a_draft_keeps_only_quotes_that_are_really_in_the_passages():
    """The anti-hallucination check, exercised through the same function the
    view calls — with an injected generator, so no Ollama is involved."""
    from analysis.framework import draft_cell_summary

    passages = ["The tuition was the hard part."]

    def generate(_prompt, _schema):
        return {"summary": "Cost dominated.",
                "quotes": ["The tuition was the hard part.",
                           "I never worried about money."]}   # invented

    out = draft_cell_summary(passages, code_name="Cost", case_label="Ama",
                             generate_json=generate)
    assert out["note"] == "ok"
    assert out["quotes"] == ["The tuition was the hard part."]
    assert out["dropped"] == 1, "the invented quote must be dropped and counted"


def test_a_draft_is_not_saved_until_the_analyst_saves_it(view, service):
    view.fw_case.setCurrentIndex(view.fw_case.findText("Ama"))
    view.fw_code.setCurrentText("Cost")
    case_id = view.fw_case.currentData()

    view._on_draft_ready({"summary": "Cost dominated.",
                          "quotes": ["The tuition was the hard part."],
                          "dropped": 1, "note": "ok"})

    assert "Cost dominated." in view.fw_summary.toPlainText()
    assert service.cell_summary(case_id, "Cost") is None, \
        "a draft must not reach the store until it is saved"


def test_a_failed_draft_changes_nothing(view, service, monkeypatch):
    import qualsafe_qt.views.query_view as module

    shown = []
    monkeypatch.setattr(module.QMessageBox, "information",
                        staticmethod(lambda *a, **k: shown.append(a)))
    view.fw_case.setCurrentIndex(view.fw_case.findText("Ama"))
    view.fw_code.setCurrentText("Cost")
    before = view.fw_summary.toPlainText()

    view._on_draft_ready({"summary": "", "quotes": [], "dropped": 0,
                          "note": "llm_error: connection refused"})

    assert shown, "a failed draft should be explained"
    assert view.fw_summary.toPlainText() == before


# -- cases -------------------------------------------------------------------
def test_creating_a_case(view, service):
    view.case_name.setText("Cohort C")
    view._create_case()
    assert "Cohort C" in {c.name for c in service.list_cases()}


def test_bulk_creating_cases_from_a_descriptor(view, service):
    made = view._bulk_create("Program")
    assert made == 2
    names = {c.name for c in service.list_cases()}
    assert {"Program: Nursing", "Program: Business"} <= names


def test_bulk_creation_is_idempotent(view, service):
    view._bulk_create("Program")
    first = len(service.list_cases())
    view._bulk_create("Program")
    assert len(service.list_cases()) == first, \
        "running it twice must reuse the cases, not duplicate them"


def test_the_cases_table_counts_assigned_sources(view):
    frame = view.cases_model.frame
    assert set(frame["case"]) >= {"Ama", "Ben"}
    assert frame.set_index("case").loc["Ama", "sources"] == 1


# -- empty state -------------------------------------------------------------
def test_an_uncoded_project_says_so(qapp, tmp_path):
    path = tmp_path / "bare.qnw"
    with Project.create(path) as proj:
        add_document(proj, "Uncoded", DOC_A)
    service = ProjectService()
    service.open(path)
    try:
        view = QueryView(service, QUndoStack())
        assert not view.empty_label.isHidden()
        assert "Nothing is coded" in view.empty_label.text()
    finally:
        service.close()


def test_framework_columns_are_checkboxes_not_a_block_of_highlight(view):
    """"Which themes are columns" is a set of independent yes/no choices; a
    fully-selected multi-select list renders as one solid colour that says
    nothing."""
    from PySide6.QtCore import Qt as _Qt

    assert view.fw_codes.count() >= 3
    checked = view._chosen_codes()
    assert checked, "some themes should be ticked by default"
    assert set(checked) <= set(view.fw_grid_model.frame.columns)

    # Unticking one removes its column from the grid.
    for i in range(view.fw_codes.count()):
        item = view.fw_codes.item(i)
        if item.text() == checked[0]:
            item.setCheckState(_Qt.CheckState.Unchecked)
            break
    assert checked[0] not in view.fw_grid_model.frame.columns
