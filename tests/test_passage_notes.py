"""Notes on one coded passage (book-audit F6): the store kept them since v4; both screens now offer them."""

from __future__ import annotations

import os

import pytest

from core import passage_notes
from core.model import Code
from core.project import Project
from core.span_coding import HUMAN_RATER, apply_codes_to_span


def _coded_project(tmp_path):
    from core.model import Source

    project = Project.create(tmp_path / "n.qnw")
    sid = project.add_source(Source(source_id="", type="document", label="Interview 1",
                                    raw_text="The cost of books was the hardest part of my first term."))
    project.add_code(Code(code_id="", name="Cost"))
    result = apply_codes_to_span(project, sid, 4, 20, ["Cost"], rater_id=HUMAN_RATER)
    return project, sid, result["excerpt_id"]


def test_a_note_is_kept_listed_counted_and_deleted(tmp_path):
    project, _sid, ex = _coded_project(tmp_path)
    assert passage_notes.notes_for(project, ex) == []
    nid = passage_notes.add(project, ex, "  Clearest statement of the cost theme.  ")
    notes = passage_notes.notes_for(project, ex)
    assert [n.text for n in notes] == ["Clearest statement of the cost theme."]
    assert passage_notes.counts(project, [ex, "nope"]) == {ex: 1}
    project.delete_annotation(nid)
    assert passage_notes.notes_for(project, ex) == []
    project.close()


def test_an_empty_note_is_refused_and_a_long_one_is_cut(tmp_path):
    project, _sid, ex = _coded_project(tmp_path)
    with pytest.raises(ValueError):
        passage_notes.add(project, ex, "   ")
    passage_notes.add(project, ex, "x" * 5000)
    assert len(passage_notes.notes_for(project, ex)[0].text) == passage_notes.MAX_CHARS
    project.close()


pytest.importorskip("PySide6", reason="Qt front end not installed")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QUndoStack  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from qualsafe_qt.services.project_service import ProjectService  # noqa: E402
from qualsafe_qt.views.documents_view import DocumentsView  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_the_desktop_list_marks_a_noted_passage_and_puts_the_note_in_its_tooltip(app, tmp_path):
    from core.model import Source

    service = ProjectService()
    service.create(tmp_path / "d.qnw")
    sid = service.project.add_source(Source(source_id="", type="document", label="Interview 1",
                                            raw_text="The cost of books was the hardest part of my first term."))
    service.project.add_code(Code(code_id="", name="Cost"))
    ex = apply_codes_to_span(service.project, sid, 4, 20, ["Cost"], rater_id=HUMAN_RATER)["excerpt_id"]
    view = DocumentsView(service, QUndoStack())
    view._source_id = sid
    view.reader.set_document(service.project.get_source(sid).raw_text, sid)
    view._refresh_my_codings()
    assert view.my_codings.count() == 1
    assert passage_notes.MARK not in view.my_codings.item(0).text()
    view._add_note(ex, "Clearest statement of the cost theme.")
    item = view.my_codings.item(0)
    assert item.text().startswith(passage_notes.MARK)
    assert "Clearest statement" in item.toolTip()
    view._add_note(ex, "   ")                       # an empty note changes nothing
    assert len(service.passage_notes(ex)) == 1
    view._delete_note(service.passage_notes(ex)[0].annotation_id)
    assert not view.my_codings.item(0).text().startswith(passage_notes.MARK)
    view.close()
    service.close()


# -- the web build ---------------------------------------------------------------------------------------
def test_the_web_box_adds_shows_and_deletes_a_note(tmp_path):
    from streamlit.testing.v1 import AppTest

    store = str(tmp_path / "w.qnw")

    def script():
        import streamlit as st

        from app.documents_page import _render_passage_notes
        from core.model import Code, Source
        from core.project import Project
        from core.span_coding import HUMAN_RATER, apply_codes_to_span

        path = st.session_state["store"]
        import os

        if not os.path.exists(path):
            p = Project.create(path)
            sid = p.add_source(Source(source_id="", type="document", label="I1",
                                      raw_text="The cost of books was the hardest part."))
            p.add_code(Code(code_id="", name="Cost"))
            st.session_state["ex"] = apply_codes_to_span(p, sid, 4, 20, ["Cost"], rater_id=HUMAN_RATER)["excerpt_id"]
            p.close()
        with Project.open(path) as proj:
            _render_passage_notes(proj, st.session_state["ex"])

    at = AppTest.from_function(script)
    at.session_state["store"] = store
    at.run(timeout=60)
    assert not at.exception
    ex = at.session_state["ex"]
    at.text_area(key=f"pn_text_{ex}").set_value("Clearest statement of the cost theme.").run(timeout=60)
    next(b for b in at.button if b.key == f"pn_add_{ex}").click().run(timeout=60)
    assert any("Clearest statement" in str(m.value) for m in at.markdown)
    delete = next(b for b in at.button if b.key.startswith("pn_del_"))
    delete.click().run(timeout=60)
    assert not any("Clearest statement" in str(m.value) for m in at.markdown)
