"""
The Search screen: corpus search, KWIC, auto-coding, word frequency.

`core.search` and `analysis.lexical` are tested upstream; what this file guards
is the view's own work — that filters reach the engine, that a hit carries its
offsets all the way to the reader, and that auto-coding stays clearly separated
from human coding.

The last point is the one with teeth. `core.autocode.AUTOCODE_RATER` is
`auto_textsearch`, which does not start with `human`, so a regex can never be
picked as a coder in the agreement screen. That is invariant #6 applied to
pattern matching for the same reason it applies to models: a regex is not a
second analyst.
"""

from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6", reason="Qt front end not installed")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QUndoStack  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core.autocode import AUTOCODE_RATER  # noqa: E402
from core.documents import add_document  # noqa: E402
from core.model import Case, Code  # noqa: E402
from core.project import Project  # noqa: E402
from qualsafe_qt.services.project_service import ProjectService  # noqa: E402
from qualsafe_qt.views.search_view import SearchView  # noqa: E402

DOC_A = ("Respondent: the cost of textbooks was the hard part. "
         "I worried about cost every month. "
         "My advisor helped me find a payment plan.")
DOC_B = ("Respondent: making friends took a while. "
         "The costume party was where I met people. "
         "An advisor suggested the club fair.")


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def corpus(tmp_path):
    path = tmp_path / "search.qnw"
    with Project.create(path) as proj:
        add_document(proj, "Interview 01", DOC_A)
        add_document(proj, "Interview 02", DOC_B)
        proj.add_code(Code(code_id="", name="Financial concerns"))
    return path


@pytest.fixture
def service(qapp, corpus):
    svc = ProjectService()
    svc.open(corpus)
    yield svc
    svc.close()


@pytest.fixture
def view(qapp, service):
    return SearchView(service, QUndoStack())


def _hit_items(view):
    """Every leaf (hit) row in the results tree."""
    out = []
    for i in range(view.hits_tree.topLevelItemCount()):
        parent = view.hits_tree.topLevelItem(i)
        for j in range(parent.childCount()):
            out.append(parent.child(j))
    return out


# -- searching ---------------------------------------------------------------
def test_a_search_groups_hits_by_source(view):
    view.query_edit.setText("advisor")
    view.run_search()

    assert view.hits_tree.topLevelItemCount() == 2, "one group per document"
    assert len(_hit_items(view)) == 2
    assert "2</b> hit(s)" in view.result_summary.text() \
        or "2 hit(s)" in view.result_summary.text().replace("<b>", "").replace("</b>", "")


def test_whole_word_is_the_difference_between_cost_and_costume(view):
    """The setting that most changes what an analyst sees, so worth pinning."""
    view.query_edit.setText("cost")
    view.whole_word.setChecked(True)
    view.run_search()
    whole = {h.data(0, Qt.ItemDataRole.UserRole).match_text.lower()
             for h in _hit_items(view)}
    assert whole == {"cost"}, "whole-word must not match inside 'costume'"

    view.whole_word.setChecked(False)
    view.run_search()
    substring = [h.data(0, Qt.ItemDataRole.UserRole) for h in _hit_items(view)]
    assert any("costume" in h.left + h.match_text + h.right for h in substring), \
        "substring search should reach 'costume'"


def test_a_malformed_regex_is_reported_not_raised(view, monkeypatch):
    import qualsafe_qt.views.search_view as module

    warned = []
    monkeypatch.setattr(module.QMessageBox, "warning",
                        staticmethod(lambda *a, **k: warned.append(a)))
    view.mode.setCurrentIndex(1)               # Regex
    view.query_edit.setText("cost(")           # unbalanced
    view.run_search()
    assert warned, "a bad pattern is user input, not a crash"


def test_no_matches_says_so(view):
    view.query_edit.setText("zzzznotpresent")
    view.run_search()
    assert "No matches" in view.result_summary.text()
    assert not view.autocode_button.isEnabled()


def test_the_source_type_filter_narrows_the_corpus(view, service):
    view.query_edit.setText("advisor")
    index = view.type_filter.findData("document")
    assert index >= 0, "documents should be an offered source type"
    view.type_filter.setCurrentIndex(index)
    view.run_search()
    assert _hit_items(view), "documents are the only type here, so hits remain"


def test_a_case_filter_limits_to_that_cases_sources(view, service):
    proj = service.project
    case_id = proj.add_case(Case(case_id="", name="Cohort A"))
    first = service.document_table()["source_id"].iloc[0]
    proj.assign_source_to_case(case_id, first)
    view._refresh_filters()

    view.query_edit.setText("advisor")
    view.case_filter.setCurrentIndex(view.case_filter.findData(case_id))
    view.run_search()

    sources = {h.data(0, Qt.ItemDataRole.UserRole).source_id
               for h in _hit_items(view)}
    assert sources == {first}


def test_context_profile_shows_words_around_the_term(view):
    view.query_edit.setText("cost")
    view.run_search()
    before = view.before_model.frame
    after = view.after_model.frame
    assert not before.empty and not after.empty
    assert "term" in before.columns and "count" in before.columns


# -- the jump to the reader --------------------------------------------------
def test_double_clicking_a_hit_emits_its_exact_offsets(view, service):
    """A hit is a place, not just a line. `SearchHit` has always carried exact
    offsets; this is the first front end with somewhere to send them."""
    emitted = []
    view.open_in_reader.connect(lambda s, a, b: emitted.append((s, a, b)))

    view.query_edit.setText("advisor")
    view.run_search()
    hit_item = _hit_items(view)[0]
    hit = hit_item.data(0, Qt.ItemDataRole.UserRole)
    view._open_hit(hit_item, 0)

    assert emitted == [(hit.source_id, hit.char_start, hit.char_end)]
    # And the offsets really do slice the matched word out of the source.
    text = service.document_text(hit.source_id)
    assert text[hit.char_start:hit.char_end].lower() == "advisor"


def test_clicking_a_group_header_navigates_nowhere(view):
    """Only leaves are places; a source header has no span."""
    emitted = []
    view.open_in_reader.connect(lambda *a: emitted.append(a))
    view.query_edit.setText("advisor")
    view.run_search()
    view._open_hit(view.hits_tree.topLevelItem(0), 0)
    assert emitted == []


def test_the_documents_screen_selects_a_span_handed_to_it(qapp, service):
    from qualsafe_qt.views.documents_view import DocumentsView

    documents = DocumentsView(service, QUndoStack())
    documents.refresh()
    source_id = service.document_table()["source_id"].iloc[0]
    text = service.document_text(source_id)
    start = text.index("advisor")

    assert documents.select_source_span(source_id, start, start + 7)
    assert documents.reader.selected_span() == (start, start + 7)
    assert documents.reader.selected_text() == "advisor"


def test_selecting_a_span_for_a_missing_document_reports_false(qapp, service):
    from qualsafe_qt.views.documents_view import DocumentsView

    documents = DocumentsView(service, QUndoStack())
    documents.refresh()
    assert not documents.select_source_span("doc_does_not_exist", 0, 5)


# -- auto-coding -------------------------------------------------------------
def test_autocoding_uses_a_rater_that_can_never_be_a_coder(view, service, monkeypatch):
    """Invariant #6, applied to pattern matching: a regex is not an analyst."""
    import qualsafe_qt.views.search_view as module

    monkeypatch.setattr(module.QMessageBox, "question",
                        staticmethod(lambda *a, **k: module.QMessageBox.StandardButton.Yes))
    view.query_edit.setText("cost")
    view.run_search()
    view.autocode_name.setCurrentText("Financial concerns")
    view._autocode()

    coding = service.coding_table()
    auto = coding[coding["rater_id"] == AUTOCODE_RATER]
    assert len(auto) >= 1
    assert not AUTOCODE_RATER.startswith("human")
    assert AUTOCODE_RATER not in service.human_rater_ids(), \
        "text-search coding must never be selectable for kappa"


def test_autocoded_excerpts_cover_exactly_the_matched_words(view, service, monkeypatch):
    import qualsafe_qt.views.search_view as module

    monkeypatch.setattr(module.QMessageBox, "question",
                        staticmethod(lambda *a, **k: module.QMessageBox.StandardButton.Yes))
    view.query_edit.setText("advisor")
    view.run_search()
    view.autocode_name.setCurrentText("Advising")
    view._autocode()

    for source_id in service.document_table()["source_id"]:
        raw = service.document_text(source_id)
        for excerpt in service.project.list_excerpts(source_id):
            assert excerpt.verify_offsets(raw)
            assert excerpt.text.lower() == "advisor"


def test_autocoding_can_be_cancelled(view, service, monkeypatch):
    import qualsafe_qt.views.search_view as module

    monkeypatch.setattr(module.QMessageBox, "question",
                        staticmethod(lambda *a, **k: module.QMessageBox.StandardButton.Cancel))
    view.query_edit.setText("cost")
    view.run_search()
    view.autocode_name.setCurrentText("Financial concerns")
    view._autocode()
    assert service.coding_table().empty


def test_removing_autocoding_leaves_human_coding_alone(view, service, monkeypatch):
    import qualsafe_qt.views.search_view as module

    monkeypatch.setattr(module.QMessageBox, "question",
                        staticmethod(lambda *a, **k: module.QMessageBox.StandardButton.Yes))
    # A human coding on the same document.
    source_id = service.document_table()["source_id"].iloc[0]
    service.apply_codes_to_span(source_id, 0, 20, ["Financial concerns"])

    view.query_edit.setText("cost")
    view.run_search()
    view.autocode_name.setCurrentText("Financial concerns")
    view._autocode()
    assert not service.coding_table()[
        service.coding_table()["rater_id"] == AUTOCODE_RATER].empty

    view.undo_pick.setCurrentIndex(0)          # all auto-coded
    view._remove_autocoded()

    coding = service.coding_table()
    assert coding[coding["rater_id"] == AUTOCODE_RATER].empty
    from core.span_coding import HUMAN_RATER

    assert not coding[coding["rater_id"] == HUMAN_RATER].empty, \
        "removing auto-coding must not touch the analyst's own work"


def test_autocoding_without_a_code_name_is_refused(view, monkeypatch):
    import qualsafe_qt.views.search_view as module

    shown = []
    monkeypatch.setattr(module.QMessageBox, "information",
                        staticmethod(lambda *a, **k: shown.append(a)))
    view.query_edit.setText("cost")
    view.run_search()
    view.autocode_name.setCurrentText("   ")
    view._autocode()
    assert shown


# -- word frequency ----------------------------------------------------------
def test_word_frequency_counts_the_corpus(view, qapp):
    _drain(qapp)
    freq = view.wf_model.frame
    assert not freq.empty
    assert {"term", "count", "documents"} <= set(freq.columns)
    assert "advisor" in set(freq["term"])


def test_stop_words_are_removed_by_default(view, qapp):
    _drain(qapp)
    terms = set(view.wf_model.frame["term"])
    assert "the" not in terms

    view.wf_stops.setChecked(False)
    view.wf_min_len.setValue(1)
    _drain(qapp)
    assert "the" in set(view.wf_model.frame["term"])


def test_extra_ignored_words_are_honoured(view, qapp):
    _drain(qapp)
    assert "advisor" in set(view.wf_model.frame["term"])

    view.wf_extra.setText("advisor")
    view._recount_words()
    _drain(qapp)
    assert "advisor" not in set(view.wf_model.frame["term"])


def test_the_documents_column_separates_one_speaker_from_everyone(view, qapp):
    """`documents` is what distinguishes a word one person repeated from a word
    the whole corpus uses — the reason the column exists."""
    _drain(qapp)
    freq = view.wf_model.frame.set_index("term")
    assert freq.loc["advisor", "documents"] == 2, "advisor appears in both"
    assert freq.loc["textbooks", "documents"] == 1, "textbooks only in the first"


def _drain(app, rounds: int = 60) -> None:
    """Let the word-frequency worker finish and its signal deliver."""
    from PySide6.QtCore import QThreadPool

    for _ in range(rounds):
        app.processEvents()
        if QThreadPool.globalInstance().waitForDone(30):
            break
    for _ in range(10):
        app.processEvents()


def test_hit_groups_open_when_the_result_set_is_readable(view):
    """A screen of collapsed headers hides the KWIC lines that are the point.

    Keyed on total hits rather than on how many documents they fall across —
    the Streamlit page uses source count because its expanders stack vertically,
    a constraint a tree does not have.
    """
    view.query_edit.setText("advisor")
    view.whole_word.setChecked(False)
    view.run_search()
    assert view.hits_tree.topLevelItemCount() >= 1
    for i in range(view.hits_tree.topLevelItemCount()):
        assert view.hits_tree.topLevelItem(i).isExpanded(), \
            "a small result set should show its hits without a click"
