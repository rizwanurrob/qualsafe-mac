"""Tests for manual span coding (v4, Phase 2b)."""

from __future__ import annotations

import pytest

from core.documents import add_document
from core.model import Code, CodeApplication, Rater
from core.project import Project
from core.span_coding import (
    HUMAN_RATER, apply_codes_to_span, apply_codes_to_units, codeable_units,
    locate_passage, remove_coding,
)

TEXT = ("The cost of housing is the hardest part. My advisor helped a lot.\n\n"
        "Second paragraph about belonging.")


@pytest.fixture()
def proj(tmp_path):
    project = Project.create(tmp_path / "p.qnw")
    yield project
    project.close()


@pytest.fixture()
def doc(proj):
    return add_document(proj, "Interview 1", TEXT)


# ── units ───────────────────────────────────────────────────────────────────
def test_sentence_units_have_exact_offsets():
    units = codeable_units(TEXT, "sentence")
    assert len(units) >= 3
    for text, start, end in units:
        assert TEXT[start:end] == text


def test_paragraph_units_have_exact_offsets():
    units = codeable_units(TEXT, "paragraph")
    assert len(units) == 2
    for text, start, end in units:
        assert TEXT[start:end] == text
    assert "Second paragraph" in units[1][0]


def test_units_on_empty_and_unknown_unit():
    assert codeable_units("", "sentence") == []
    assert codeable_units("   ", "paragraph") == []
    with pytest.raises(ValueError):
        codeable_units("text", "chapter")


# ── locating a pasted passage ───────────────────────────────────────────────
def test_locate_exact_passage(proj, doc):
    found = locate_passage(proj, doc, "cost of housing")
    assert found["match_kind"] == "exact"
    assert TEXT[found["char_start"]:found["char_end"]] == "cost of housing"


def test_locate_tolerates_smart_quotes_and_whitespace(proj):
    sid = add_document(proj, "D", 'She said "the cost is high" to me.')
    found = locate_passage(proj, sid, '“the  cost is high”')
    assert found is not None
    # Stored text comes from the SOURCE, not from what was pasted.
    src = proj.get_source(sid).raw_text
    assert src[found["char_start"]:found["char_end"]] == found["text"]
    assert "“" not in found["text"]


def test_locate_refuses_a_passage_that_is_not_there(proj, doc):
    assert locate_passage(proj, doc, "a sentence never written", allow_fuzzy=False) is None


# ── applying codes ──────────────────────────────────────────────────────────
def test_apply_creates_excerpt_with_source_text(proj, doc):
    result = apply_codes_to_span(proj, doc, 4, 19, ["Cost"])
    assert result["applied"] == 1 and result["new_codes"] == ["Cost"]
    excerpt = proj.get_excerpt(result["excerpt_id"])
    assert excerpt.text == TEXT[4:19] == "cost of housing"


def test_apply_is_idempotent_per_rater(proj, doc):
    apply_codes_to_span(proj, doc, 4, 19, ["Cost"])
    again = apply_codes_to_span(proj, doc, 4, 19, ["Cost"])
    assert again["applied"] == 0 and again["skipped"] == 1
    assert len(proj.coding_table()) == 1


def test_multiple_and_overlapping_codes_on_one_span(proj, doc):
    apply_codes_to_span(proj, doc, 4, 19, ["Cost", "Housing"])
    codes = set(proj.coding_table()["code_name"])
    assert codes == {"Cost", "Housing"}


def test_in_vivo_coding_creates_the_code_from_the_passage(proj, doc):
    passage = TEXT[4:19]
    result = apply_codes_to_span(proj, doc, 4, 19, [passage])
    assert result["new_codes"] == [passage]
    assert proj.find_code_by_name(passage) is not None


def test_existing_code_is_reused_not_duplicated(proj, doc):
    proj.add_code(Code(code_id="", name="Cost", origin="a_priori"))
    apply_codes_to_span(proj, doc, 4, 19, ["Cost"])
    assert [c.name for c in proj.get_codebook()] == ["Cost"]


def test_out_of_range_and_empty_inputs_are_refused(proj, doc):
    with pytest.raises(ValueError, match="outside"):
        apply_codes_to_span(proj, doc, 0, 10_000, ["Cost"])
    with pytest.raises(ValueError, match="outside"):
        apply_codes_to_span(proj, doc, 10, 10, ["Cost"])
    with pytest.raises(ValueError, match="at least one code"):
        apply_codes_to_span(proj, doc, 0, 5, ["   "])


def test_unknown_source_is_refused(proj):
    with pytest.raises(ValueError, match="No such source"):
        apply_codes_to_span(proj, "nope", 0, 3, ["Cost"])


# ── coding picked units ─────────────────────────────────────────────────────
def test_adjacent_units_merge_into_one_passage(proj, doc):
    units = codeable_units(TEXT, "sentence")[:2]
    result = apply_codes_to_units(proj, doc, [(s, e) for _t, s, e in units], ["Theme"])
    assert len(result["excerpts"]) == 1, "a contiguous run should be one excerpt"
    excerpt = proj.get_excerpt(result["excerpts"][0])
    assert excerpt.text == TEXT[units[0][1]:units[1][2]]


def test_non_adjacent_units_stay_separate(proj, doc):
    units = codeable_units(TEXT, "sentence")
    picked = [(units[0][1], units[0][2]), (units[-1][1], units[-1][2])]
    result = apply_codes_to_units(proj, doc, picked, ["Theme"])
    assert len(result["excerpts"]) == 2


def test_merge_can_be_disabled(proj, doc):
    units = codeable_units(TEXT, "sentence")[:2]
    result = apply_codes_to_units(proj, doc, [(s, e) for _t, s, e in units], ["Theme"],
                                  merge_adjacent=False)
    assert len(result["excerpts"]) == 2


def test_no_units_picked_is_refused(proj, doc):
    with pytest.raises(ValueError, match="at least one passage"):
        apply_codes_to_units(proj, doc, [], ["Theme"])


# ── uncoding ────────────────────────────────────────────────────────────────
def test_remove_coding_is_scoped_to_the_rater(proj, doc):
    result = apply_codes_to_span(proj, doc, 4, 19, ["Cost"])
    eid = result["excerpt_id"]
    # A colleague codes the same span.
    proj.add_rater(Rater(rater_id="human_bob", kind="human"))
    code_id = proj.find_code_by_name("Cost").code_id
    proj.apply_code(CodeApplication(application_id="", excerpt_id=eid, code_id=code_id,
                                    coder="human", rater_id="human_bob"))

    assert remove_coding(proj, eid, rater_id=HUMAN_RATER) == 1
    remaining = proj.coding_table()
    assert list(remaining["rater_id"]) == ["human_bob"]
    # The excerpt survives — the colleague is still coding it.
    assert proj.get_excerpt(eid) is not None


def test_remove_one_code_leaves_the_others(proj, doc):
    result = apply_codes_to_span(proj, doc, 4, 19, ["Cost", "Housing"])
    remove_coding(proj, result["excerpt_id"], code_name="Cost")
    assert set(proj.coding_table()["code_name"]) == {"Housing"}


def test_remove_on_uncoded_span_is_zero(proj, doc):
    result = apply_codes_to_span(proj, doc, 4, 19, ["Cost"])
    remove_coding(proj, result["excerpt_id"])
    assert remove_coding(proj, result["excerpt_id"]) == 0
