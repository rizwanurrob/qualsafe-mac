"""Tests for the document corpus: import, library, and the reader view."""

from __future__ import annotations

import pytest

from core.documents import (
    DOCUMENT_TYPE, add_document, coding_density, coding_spans, document_table,
    import_documents, list_documents_in_folder, read_document, read_document_bytes,
    segment_by_spans,
)
from core.model import Case, Code, CodeApplication, Excerpt
from core.project import Project


@pytest.fixture()
def proj(tmp_path):
    project = Project.create(tmp_path / "p.qnw")
    yield project
    project.close()


# ── reading ─────────────────────────────────────────────────────────────────
def test_read_txt_from_bytes_and_path(tmp_path):
    assert read_document_bytes("a.txt", b"hello world") == "hello world"
    path = tmp_path / "b.txt"
    path.write_text("on disk", encoding="utf-8")
    assert read_document("b.txt" and path) == "on disk"


def test_unsupported_type_raises():
    with pytest.raises(ValueError, match="Unsupported"):
        read_document_bytes("a.xyz", b"data")


def test_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        read_document(tmp_path / "nope.txt")


def test_list_documents_in_folder_filters_and_sorts(tmp_path):
    (tmp_path / "b.txt").write_text("b", encoding="utf-8")
    (tmp_path / "a.md").write_text("a", encoding="utf-8")
    (tmp_path / "skip.csv").write_text("x", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    found = [p.name for p in list_documents_in_folder(tmp_path)]
    assert found == ["a.md", "b.txt"]


def test_list_documents_in_missing_folder_is_empty(tmp_path):
    assert list_documents_in_folder(tmp_path / "nope") == []


# ── importing ───────────────────────────────────────────────────────────────
def test_add_document_records_metadata(proj):
    sid = add_document(proj, "Interview 1", "two words here", source_path="/x/y.txt")
    src = proj.get_source(sid)
    assert src.type == DOCUMENT_TYPE
    assert src.metadata["title"] == "Interview 1"
    assert src.metadata["word_count"] == 3
    # The name, not the path it arrived by. A `.qnw` is offered to the analyst
    # as a file they can share, and the absolute path carried their username,
    # their institution and their folder structure into it -- see
    # `tests/test_store_does_not_leak_the_author.py`. This assertion used to be
    # the only place in the codebase that read the value at all.
    assert src.metadata["source_path"] == "y.txt"


def test_documents_get_no_automatic_whole_source_excerpt(proj):
    """A whole-document excerpt would be a meaningless 40-page quote."""
    sid = add_document(proj, "Doc", "some text")
    assert proj.list_excerpts(sid) == []


def test_import_folder_of_documents(proj, tmp_path):
    (tmp_path / "one.txt").write_text("first document", encoding="utf-8")
    (tmp_path / "two.txt").write_text("second document", encoding="utf-8")
    result = import_documents(proj, list_documents_in_folder(tmp_path))
    assert sorted(result["imported"]) == ["one.txt", "two.txt"]
    assert proj.count_sources(DOCUMENT_TYPE) == 2


def test_import_from_upload_pairs(proj):
    result = import_documents(proj, [("memo.txt", b"uploaded text")])
    assert result["imported"] == ["memo.txt"]
    assert proj.count_sources(DOCUMENT_TYPE) == 1


def test_reimport_skips_identical_content(proj, tmp_path):
    (tmp_path / "one.txt").write_text("same text", encoding="utf-8")
    import_documents(proj, list_documents_in_folder(tmp_path))
    (tmp_path / "two.txt").write_text("new text", encoding="utf-8")
    result = import_documents(proj, list_documents_in_folder(tmp_path))
    assert result["imported"] == ["two.txt"]
    assert result["skipped"] == ["one.txt"]
    assert proj.count_sources(DOCUMENT_TYPE) == 2


def test_one_bad_file_does_not_abort_the_batch(proj, tmp_path):
    (tmp_path / "good.txt").write_text("fine", encoding="utf-8")
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"not really a pdf")
    result = import_documents(proj, [tmp_path / "good.txt", bad])
    assert result["imported"] == ["good.txt"]
    assert len(result["failed"]) == 1 and result["failed"][0][0] == "bad.pdf"


def test_empty_document_is_reported_not_imported(proj):
    result = import_documents(proj, [("blank.txt", b"   \n  ")])
    assert result["imported"] == []
    assert "scanned" in result["failed"][0][1]


def test_import_can_assign_a_case(proj):
    cid = proj.add_case(Case(case_id="", name="Alice"))
    import_documents(proj, [("a.txt", b"text")], case_id=cid)
    assert len(proj.case_sources(cid)) == 1


# ── library + spans ─────────────────────────────────────────────────────────
def _code_span(proj, sid, start, end, code_name, rater="human_primary"):
    from core.model import Rater
    proj.add_rater(Rater(rater_id=rater, kind="human"))
    existing = proj.find_code_by_name(code_name)
    code_id = existing.code_id if existing else proj.add_code(Code(code_id="", name=code_name))
    text = proj.get_source(sid).raw_text[start:end]
    eid = proj.add_excerpt(Excerpt(excerpt_id="", source_id=sid, text=text,
                                   char_start=start, char_end=end))
    proj.apply_code(CodeApplication(application_id="", excerpt_id=eid, code_id=code_id,
                                    coder="human", rater_id=rater))
    return eid


def test_document_table_counts_codings(proj):
    sid = add_document(proj, "Doc", "the cost of housing is high")
    _code_span(proj, sid, 4, 8, "Cost")
    table = document_table(proj)
    row = table.iloc[0]
    assert row["title"] == "Doc" and row["codings"] == 1 and row["excerpts"] == 1


def test_coding_spans_and_rater_filter(proj):
    sid = add_document(proj, "Doc", "the cost of housing is high")
    _code_span(proj, sid, 4, 8, "Cost", rater="human_a")
    _code_span(proj, sid, 12, 19, "Housing", rater="human_b")

    everything = coding_spans(proj, sid)
    assert [s["codes"] for s in everything] == [["Cost"], ["Housing"]]
    only_a = coding_spans(proj, sid, rater_id="human_a")
    assert [s["char_start"] for s in only_a] == [4]
    only_housing = coding_spans(proj, sid, code_names=["Housing"])
    assert [s["codes"] for s in only_housing] == [["Housing"]]


def test_uncoded_excerpts_are_not_spans(proj):
    sid = add_document(proj, "Doc", "some text here")
    proj.add_excerpt(Excerpt(excerpt_id="", source_id=sid, text="some",
                             char_start=0, char_end=4))
    assert coding_spans(proj, sid) == []


# ── segmentation (pure) ─────────────────────────────────────────────────────
def test_segments_cover_the_whole_text_in_order():
    text = "abcdefghij"
    segs = segment_by_spans(text, [{"char_start": 2, "char_end": 5, "codes": ["A"]}])
    assert "".join(s["text"] for s in segs) == text
    assert [s["start"] for s in segs] == sorted(s["start"] for s in segs)
    assert [s["codes"] for s in segs] == [[], ["A"], []]


def test_overlapping_spans_produce_a_shared_segment():
    text = "0123456789"
    segs = segment_by_spans(text, [
        {"char_start": 0, "char_end": 6, "codes": ["A"]},
        {"char_start": 4, "char_end": 10, "codes": ["B"]},
    ])
    assert [(s["start"], s["end"], s["codes"]) for s in segs] == [
        (0, 4, ["A"]), (4, 6, ["A", "B"]), (6, 10, ["B"]),
    ]


def test_nested_span_keeps_both_codes():
    segs = segment_by_spans("0123456789", [
        {"char_start": 0, "char_end": 10, "codes": ["Outer"]},
        {"char_start": 3, "char_end": 6, "codes": ["Inner"]},
    ])
    middle = [s for s in segs if s["start"] == 3][0]
    assert middle["codes"] == ["Inner", "Outer"]


def test_segmentation_edge_cases():
    assert segment_by_spans("", [{"char_start": 0, "char_end": 3, "codes": ["A"]}]) == []
    # No spans -> one uncoded segment covering everything.
    assert segment_by_spans("abc", []) == [{"text": "abc", "start": 0, "end": 3, "codes": []}]
    # Degenerate and out-of-range spans are ignored/clamped, never crash.
    segs = segment_by_spans("abc", [
        {"char_start": 2, "char_end": 2, "codes": ["Z"]},
        {"char_start": -5, "char_end": 99, "codes": ["Y"]},
    ])
    assert "".join(s["text"] for s in segs) == "abc"
    assert all("Z" not in s["codes"] for s in segs)


def test_coding_density_counts_overlap_once():
    spans = [{"char_start": 0, "char_end": 5}, {"char_start": 3, "char_end": 10}]
    assert coding_density(20, spans) == pytest.approx(0.5)
    assert coding_density(0, spans) == 0.0
    assert coding_density(10, []) == 0.0
