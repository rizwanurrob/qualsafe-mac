"""
A project coded in the Qt app must open, unchanged, in the Streamlit build.

This is definition-of-done item 7 in the fork handoff, and the constraint that
makes the fork safe to try: the analyst can code in the desktop app and still
open the same `.qnw` in the tool they have been using for live research. Both
front ends are views over one store, so the store must not acquire a Qt dialect.

The test codes a document through the Qt service, then reads the result back the
way the Streamlit pages do -- `Project.coding_table()`, `core.documents`,
`analysis.frequency`, `analysis.agreement` -- and asserts the schema version is
untouched.
"""

from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6", reason="Qt front end not installed")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from core.documents import add_document, coding_spans, document_table  # noqa: E402
from core.model import Code  # noqa: E402
from core.project import SCHEMA_VERSION, Project  # noqa: E402
from core.span_coding import HUMAN_RATER  # noqa: E402
from qualsafe_qt.services.project_service import ProjectService  # noqa: E402

TEXT = ("Respondent: the tuition was the hard part, and the books on top of it. "
        "Making friends took most of the first term.")


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def qt_coded_store(qapp, tmp_path):
    """A store created and coded entirely through the Qt front end."""
    path = tmp_path / "qt_coded.qnw"
    with Project.create(path) as proj:
        add_document(proj, "Interview 01", TEXT)
        proj.add_code(Code(code_id="", name="Financial concerns",
                           definition="Cost, tuition, books."))
        proj.add_code(Code(code_id="", name="Sense of belonging"))

    service = ProjectService()
    service.open(path)
    service.set_analyst_name("Analyst")
    source_id = document_table(service.project)["source_id"].iloc[0]

    first = TEXT.index("the tuition was the hard part")
    service.apply_codes_to_span(source_id, first, first + len("the tuition was the hard part"),
                                ["Financial concerns"])
    second = TEXT.index("Making friends took most of the first term")
    service.apply_codes_to_span(source_id, second, second + len("Making friends took most of the first term"),
                                ["Sense of belonging"])
    service.close()
    return path


def test_the_store_keeps_the_shared_schema_version(qt_coded_store):
    """Invariant #7: a store this front end writes is a store the engine reads.

    This used to assert `== 4` as well, which encoded "the schema never changes"
    when the rule was only ever "**this fork** never changes it". Upstream took
    the store to v5 (`saved_charts`) with a migration, an old-format test and a
    changelog entry -- exactly the process the assertion existed to force -- and
    a literal version number turned that correct change into a red suite.

    So the check is now the invariant itself: what Qt writes matches what the
    engine expects. The bump-without-a-migration failure mode is caught by the
    test below, which is where it belonged all along.
    """
    import sqlite3

    conn = sqlite3.connect(str(qt_coded_store))
    try:
        found = conn.execute(
            "SELECT value FROM meta WHERE key = 'schema_version'").fetchone()[0]
    finally:
        conn.close()
    assert int(found) == SCHEMA_VERSION


def test_every_schema_version_has_a_migration():
    """A bump with no migration is a project file that cannot be opened again.

    The real content of invariant #7. Version 1 is the original schema and needs
    no migration into itself; every version after it must have one.
    """
    from core.migrations import MIGRATIONS

    missing = [v for v in range(2, SCHEMA_VERSION + 1) if v not in MIGRATIONS]
    assert not missing, (
        f"SCHEMA_VERSION is {SCHEMA_VERSION} but core/migrations.py has no entry "
        f"for version(s) {missing}. An existing project would fail to open.")


def test_qt_codings_read_back_through_the_engine_api(qt_coded_store):
    """Everything the Streamlit pages call must see the Qt coding."""
    with Project.open(qt_coded_store) as proj:
        coding = proj.coding_table()
        assert len(coding) == 2
        assert set(coding["code_name"]) == {"Financial concerns", "Sense of belonging"}
        assert set(coding["rater_id"]) == {HUMAN_RATER}
        assert set(coding["coder"]) == {"human"}

        source_id = document_table(proj)["source_id"].iloc[0]
        spans = coding_spans(proj, source_id)
        assert len(spans) == 2
        # The evidentiary link survives the round trip.
        raw = proj.get_source(source_id).raw_text
        for excerpt in proj.list_excerpts(source_id):
            assert excerpt.verify_offsets(raw)
            assert excerpt.text == raw[excerpt.char_start:excerpt.char_end]


def test_qt_codings_flow_into_the_analysis_layer(qt_coded_store):
    """`analysis/*` are pure functions over the store; Qt codings are ordinary
    rows to them, which is the whole point of not touching the engine."""
    from analysis.cooccurrence import cooccurrence_matrix
    from analysis.frequency import code_frequency

    with Project.open(qt_coded_store) as proj:
        coding = proj.coding_table()
    table = code_frequency(coding)
    assert not table.empty
    assert set(table["code_name"]) == {"Financial concerns", "Sense of belonging"}
    # Co-occurrence too: the two codings are on different passages, so the
    # off-diagonal must be zero rather than the function tripping over the rows.
    matrix, _drill = cooccurrence_matrix(coding)
    assert matrix.loc["Financial concerns", "Sense of belonging"] == 0
    assert matrix.loc["Financial concerns", "Financial concerns"] == 1


def test_the_streamlit_documents_page_renders_a_qt_coded_project(qt_coded_store):
    """The strongest form of the claim: render the actual Streamlit page against
    a store the Qt app wrote, and assert it does not raise.

    Mirrors `tests/test_app_smoke.py` -- the render-smoke that catches wiring
    breakage the engine tests cannot see.
    """
    pytest.importorskip("streamlit", reason="Streamlit build not installed")
    from streamlit.testing.v1 import AppTest

    def page(store_path):
        import streamlit as st  # noqa: F401

        from app.documents_page import render_documents_page

        render_documents_page(store_path)

    at = AppTest.from_function(page, args=(qt_coded_store,), default_timeout=120)
    at.run()
    assert not at.exception, f"Streamlit page raised on a Qt-written store: {at.exception}"


def test_a_streamlit_written_project_opens_in_the_qt_service(qapp, tmp_path):
    """And the other direction -- the sample project the Streamlit build ships
    for onboarding must open here."""
    from pathlib import Path

    from core.sample_project import build_sample_project

    repo_csv = Path(__file__).resolve().parent.parent / "data" / "sample_survey_education.csv"
    store = build_sample_project(repo_csv, tmp_path / "sample.qnw")

    service = ProjectService()
    service.open(store)
    try:
        assert service.is_open
        assert service.code_names(), "the sample codebook should be visible"
        # Survey responses are not documents, so the corpus list is empty --
        # that is correct, not a failure. What matters is that it opened and the
        # codebook read back.
        assert list(service.document_table().columns)[:2] == ["source_id", "title"]
    finally:
        service.close()
