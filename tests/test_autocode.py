"""Tests for text-search auto-coding (v4, Phase 1.4)."""

from __future__ import annotations

import pytest

from core.autocode import AUTOCODE_RATER, autocode_hits, remove_autocoded
from core.model import CodeApplication, Rater, Source
from core.project import Project
from core.search import search

TEXTS = {
    "s0": "Tuition cost is a worry, and the cost of books too.",
    "s1": "The advisor helped me a great deal.",
}


@pytest.fixture()
def proj(tmp_path):
    path = tmp_path / "p.qnw"
    project = Project.create(path)
    for sid, text in TEXTS.items():
        src = Source(source_id=sid, type="document", raw_text=text, label=sid, metadata={})
        project.add_source(src)
        project.add_whole_response_excerpt(src)
    yield project
    project.close()


def test_codes_every_hit_as_an_exact_span(proj):
    hits = search(proj, "cost", whole_word=True)
    result = autocode_hits(proj, hits, "Cost", query="cost")
    assert result["applications"] == 2
    assert result["excerpts_created"] == 2

    coding = proj.coding_table()
    assert set(coding["rater_id"]) == {AUTOCODE_RATER}
    # Each new excerpt covers exactly the matched word.
    for excerpt in proj.list_excerpts("s0"):
        if excerpt.char_start != 0:
            assert excerpt.text.lower() == "cost"
            assert TEXTS["s0"][excerpt.char_start:excerpt.char_end] == excerpt.text


def test_rerunning_does_not_duplicate(proj):
    hits = search(proj, "cost", whole_word=True)
    autocode_hits(proj, hits, "Cost")
    second = autocode_hits(proj, hits, "Cost")
    assert second["applications"] == 0
    assert second["skipped"] == 2
    assert second["excerpts_created"] == 0      # spans reused, not duplicated
    assert len(proj.coding_table()) == 2


def test_auto_rater_is_not_human_so_irr_is_unaffected(proj):
    """The safety property: auto-coding must never look like human coding."""
    hits = search(proj, "cost", whole_word=True)
    autocode_hits(proj, hits, "Cost")

    rater = next(r for r in proj.list_raters() if r.rater_id == AUTOCODE_RATER)
    assert rater.kind != "human"                    # excluded from store_merge
    assert not AUTOCODE_RATER.startswith("human")   # excluded from human-vs-human kappa
    human_raters = [r for r in proj.rater_ids() if r.startswith("human")]
    assert human_raters == []


def test_creates_a_new_code_when_needed_and_reuses_existing(proj):
    hits = search(proj, "cost", whole_word=True)
    autocode_hits(proj, hits, "Brand New")
    assert [c.name for c in proj.get_codebook()] == ["Brand New"]
    # Applying the same name again must not create a second code.
    autocode_hits(proj, search(proj, "advisor", whole_word=True), "Brand New")
    assert [c.name for c in proj.get_codebook()] == ["Brand New"]


def test_remove_autocoded_is_scoped_to_the_auto_rater(proj):
    hits = search(proj, "cost", whole_word=True)
    autocode_hits(proj, hits, "Cost")
    # A human codes something too; it must survive the undo.
    proj.add_rater(Rater(rater_id="human_primary", kind="human"))
    human_excerpt = proj.list_excerpts("s1")[0]
    code_id = proj.find_code_by_name("Cost").code_id
    proj.apply_code(CodeApplication(application_id="", excerpt_id=human_excerpt.excerpt_id,
                                    code_id=code_id, coder="human", rater_id="human_primary"))

    removed = remove_autocoded(proj)
    assert removed == 2
    remaining = proj.coding_table()
    assert list(remaining["rater_id"]) == ["human_primary"]


def test_remove_autocoded_can_target_one_code(proj):
    autocode_hits(proj, search(proj, "cost", whole_word=True), "Cost")
    autocode_hits(proj, search(proj, "advisor", whole_word=True), "Advising")
    assert remove_autocoded(proj, code_name="Cost") == 2
    remaining = proj.coding_table()
    assert set(remaining["code_name"]) == {"Advising"}


def test_empty_hits_and_blank_code_name(proj):
    assert autocode_hits(proj, [], "Cost")["applications"] == 0
    with pytest.raises(ValueError):
        autocode_hits(proj, search(proj, "cost", whole_word=True), "   ")


def test_remove_on_empty_store_is_zero(proj):
    assert remove_autocoded(proj) == 0
