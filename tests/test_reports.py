"""Tests for the Phase 5 reporting exports: codebook, methods appendix, framework."""

from __future__ import annotations

import zipfile

import pytest

from analysis.framework import set_cell_summary
from core.documents import add_document
from core.model import (
    Case, Code, CodeApplication, Excerpt, Rater, RunManifest, Source,
)
from core.project import Project
from exports.codebook_report import build_codebook_report, codebook_rows
from exports.framework_export import build_framework_docx, build_framework_workbook
from exports.methods_appendix import build_methods_appendix, methods_facts, reliability_tables

SECRET = "my landlord raised the rent again"


@pytest.fixture()
def proj(tmp_path):
    """A project with a hierarchy, two human coders, a model, and an adjudication."""
    project = Project.create(tmp_path / "p.qnw")
    parent = project.add_code(Code(code_id="", name="Money", definition="Financial matters"))
    child = project.add_code(Code(code_id="", name="Cost", definition="Direct costs",
                                  parent_id=parent, origin="emergent"))
    project.add_code(Code(code_id="", name="Belonging"))     # no definition, unused

    project.add_rater(Rater(rater_id="human_alice", kind="human", name="Alice"))
    project.add_rater(Rater(rater_id="human_bob", kind="human", name="Bob"))
    project.add_rater(Rater(rater_id="transformer", kind="transformer",
                            model_id="facebook/bart-large-mnli"))
    project.add_run(RunManifest(run_id="", package_version="4.3.1", mode="survey",
                                engine="transformer", model="facebook/bart-large-mnli",
                                thresholds={"top1_min_score": 0.6}))

    sid = add_document(project, "Interview 1", f"Cost is hard. {SECRET}.")
    case_id = project.add_case(Case(case_id="", name="Alice's case"))
    project.assign_source_to_case(case_id, sid)
    eid = project.add_excerpt(Excerpt(excerpt_id="", source_id=sid, text=SECRET,
                                      char_start=14, char_end=14 + len(SECRET)))
    for rater in ("human_alice", "human_bob", "transformer"):
        project.apply_code(CodeApplication(application_id="", excerpt_id=eid,
                                           code_id=child, coder="human", rater_id=rater))
    project.case_id = case_id                                # convenience for tests
    yield project
    project.close()


def _docx_text(path) -> str:
    """All text in a .docx, for asserting on content without opening Word."""
    with zipfile.ZipFile(path) as zf:
        return zf.read("word/document.xml").decode("utf-8")


# ── codebook report ─────────────────────────────────────────────────────────
def test_codebook_rows_are_hierarchical_with_counts(proj):
    rows = codebook_rows(proj)
    by_name = {r["name"]: r for r in rows}
    assert by_name["Money"]["depth"] == 0
    assert by_name["Cost"]["depth"] == 1 and by_name["Cost"]["parent"] == "Money"
    assert by_name["Cost"]["applications"] == 3
    assert by_name["Belonging"]["applications"] == 0
    # Children follow their parent.
    assert list(by_name).index("Money") < list(by_name).index("Cost")


def test_codebook_report_excludes_quotes_by_default(proj, tmp_path):
    out = build_codebook_report(proj, tmp_path / "cb.docx")
    text = _docx_text(out)
    assert "Cost" in text and "Direct costs" in text
    assert SECRET not in text, "verbatim response text must not leak by default"


def test_codebook_report_can_include_examples(proj, tmp_path):
    out = build_codebook_report(proj, tmp_path / "cb2.docx", include_examples=True)
    assert SECRET in _docx_text(out)


def test_codebook_report_flags_undefined_codes(proj, tmp_path):
    assert "no definition" in _docx_text(build_codebook_report(proj, tmp_path / "cb3.docx"))


def test_codebook_report_on_empty_project(tmp_path):
    path = tmp_path / "empty.qnw"
    with Project.create(path):
        pass
    out = build_codebook_report(path, tmp_path / "cb4.docx")
    assert "no codes" in _docx_text(out)


# ── methods appendix ────────────────────────────────────────────────────────
def test_methods_facts_gathers_provenance(proj):
    facts = methods_facts(proj)
    assert facts["engine"] == "transformer"
    assert facts["model"] == "facebook/bart-large-mnli"
    assert sorted(facts["human_raters"]) == ["Alice", "Bob"]
    assert facts["n_codes"] == 3
    assert facts["thresholds"]["top1_min_score"] == 0.6


def test_reliability_tables_cover_both_pairings(proj):
    tables = reliability_tables(proj, min_support=1)
    labels = " ".join(tables)
    assert "transformer" in labels          # human vs model
    assert "human_bob" in labels            # human vs human


def test_reliability_is_empty_when_nothing_is_comparable(tmp_path):
    path = tmp_path / "solo.qnw"
    with Project.create(path) as project:
        assert reliability_tables(project) == {}


def test_appendix_states_caveats_and_never_quotes_data(proj, tmp_path):
    out = build_methods_appendix(proj, tmp_path / "m.docx", min_support=1)
    text = _docx_text(out)
    assert "kappa paradox" in text          # the caveats travel with the table
    assert "insufficient-N" in text
    assert "not comparable" in text         # cross-unit warning
    assert SECRET not in text


def test_appendix_reports_absence_of_reliability_honestly(tmp_path):
    path = tmp_path / "solo.qnw"
    with Project.create(path):
        pass
    out = build_methods_appendix(path, tmp_path / "m2.docx")
    assert "No reliability figure is reported" in _docx_text(out)


def test_appendix_includes_sampling_note_when_given(proj, tmp_path):
    out = build_methods_appendix(proj, tmp_path / "m3.docx",
                                 sampling_note="Uncertainty-ordered sample of 30.")
    assert "Uncertainty-ordered sample" in _docx_text(out)


def test_appendix_counts_adjudications(proj, tmp_path):
    from core.adjudication import record_adjudications

    eid = proj.coding_table()["excerpt_id"].iloc[0]
    # record_adjudications takes a store path (not an open Project) — it opens its
    # own connection, and this one sees the committed rows afterwards.
    record_adjudications(proj.path, {eid: ["Cost"]})
    assert methods_facts(proj)["adjudicated_codings"] == 1
    assert "adjudication" in _docx_text(build_methods_appendix(proj, tmp_path / "m4.docx"))


# ── framework exports ───────────────────────────────────────────────────────
def test_framework_docx_has_grid_and_summaries(proj, tmp_path):
    set_cell_summary(proj, proj.case_id, "Cost", "Cost dominates this case.")
    out = build_framework_docx(proj, tmp_path / "fw.docx", code_names=["Cost", "Belonging"])
    text = _docx_text(out)
    assert "Alice's case" in text
    assert "Cost dominates this case." in text
    assert SECRET not in text, "passages are opt-in"


def test_framework_docx_can_include_passages(proj, tmp_path):
    out = build_framework_docx(proj, tmp_path / "fw2.docx", code_names=["Cost"],
                               include_passages=True)
    assert SECRET in _docx_text(out)


def test_framework_docx_marks_cells_with_no_summary(proj, tmp_path):
    out = build_framework_docx(proj, tmp_path / "fw3.docx", code_names=["Cost"])
    assert "no summary written" in _docx_text(out)


def test_framework_workbook_has_both_sheets_and_no_raw_text(proj, tmp_path):
    import openpyxl

    set_cell_summary(proj, proj.case_id, "Cost", "A summary.")
    out = build_framework_workbook(proj, tmp_path / "fw.xlsx", code_names=["Cost"])
    book = openpyxl.load_workbook(out)
    assert set(book.sheetnames) == {"Coverage", "Summaries"}
    everything = " ".join(
        str(c.value) for sheet in book.worksheets for row in sheet.iter_rows()
        for c in row if c.value is not None)
    assert "A summary." in everything
    assert SECRET not in everything, "the workbook must stay email-safe"


def test_framework_workbook_on_empty_selection(proj, tmp_path):
    import openpyxl

    out = build_framework_workbook(proj, tmp_path / "fw2.xlsx", code_names=["Belonging"])
    book = openpyxl.load_workbook(out)
    assert "Summaries" in book.sheetnames
