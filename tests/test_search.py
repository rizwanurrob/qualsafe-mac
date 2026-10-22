"""Tests for corpus search (v4, Phase 1.1)."""

from __future__ import annotations

import pytest

from core.model import Case, Code, CodeApplication, Source
from core.project import Project
from core.search import search, search_store

TEXTS = {
    "s0": "Tuition cost is my biggest worry, and the cost of books too.",
    "s1": "The advisor helped me. Advising was excellent.",
    "s2": "Rising cost of housing makes it hard to stay enrolled.",
}


@pytest.fixture()
def store(tmp_path):
    path = tmp_path / "p.qnw"
    with Project.create(path) as proj:
        for sid, text in TEXTS.items():
            src = Source(source_id=sid, type="document", raw_text=text,
                         label=f"Doc {sid}", metadata={"title": f"Doc {sid}"})
            proj.add_source(src)
            proj.add_whole_response_excerpt(src)
    return path


def _search(store_path, *args, **kwargs):
    with Project.open(store_path) as proj:
        return search(proj, *args, **kwargs)


def test_finds_every_occurrence_with_exact_offsets(store):
    hits = _search(store, "cost", whole_word=True)
    assert len(hits) == 3
    for hit in hits:
        # The invariant that makes auto-coding safe: offsets address the real text.
        assert TEXTS[hit.source_id][hit.char_start:hit.char_end].lower() == "cost"


def test_substring_search_finds_inside_words(store):
    """The FTS index is token-based and must not be used to shortlist substrings."""
    hits = _search(store, "advis")            # inside 'advisor' and 'Advising'
    assert len(hits) == 2
    assert {h.source_id for h in hits} == {"s1"}


def test_whole_word_excludes_partial_matches(store):
    assert _search(store, "cos", whole_word=True) == []
    assert len(_search(store, "cos", whole_word=False)) == 3


def test_case_sensitivity(store):
    assert len(_search(store, "Advising", case_sensitive=True)) == 1
    assert len(_search(store, "advising", case_sensitive=True)) == 0
    assert len(_search(store, "advising", case_sensitive=False)) == 1


def test_regex_mode(store):
    hits = _search(store, r"cost|advisor", mode="regex")
    assert len(hits) == 4
    assert _search(store, r"\bhousing\b", mode="regex")[0].source_id == "s2"


def test_invalid_regex_raises_valueerror(store):
    with pytest.raises(ValueError):
        _search(store, "cost(", mode="regex")


def test_empty_query_raises(store):
    with pytest.raises(ValueError):
        _search(store, "   ")


def test_unknown_mode_raises(store):
    with pytest.raises(ValueError):
        _search(store, "cost", mode="fts")


def test_kwic_context_is_populated(store):
    hit = _search(store, "housing", whole_word=True)[0]
    assert "Rising cost of" in hit.left
    assert hit.match_text == "housing"
    assert "[housing]" in hit.kwic


def test_limit_caps_results(store):
    assert len(_search(store, "cost", whole_word=True, limit=2)) == 2


def test_zero_width_regex_matches_are_skipped(store):
    """A pattern that can match the empty string must not emit empty hits.

    `x*` still legitimately matches the literal 'x' in 'excellent'; what must not
    appear is a zero-length hit (which would be an excerpt covering nothing).
    """
    hits = _search(store, r"x*", mode="regex", limit=10)
    assert hits, "the literal 'x' in 'excellent' should still be found"
    assert all(h.char_end > h.char_start for h in hits)
    assert all(h.match_text for h in hits)


def test_source_type_filter(store):
    assert len(_search(store, "cost", whole_word=True, source_type="document")) == 3
    assert _search(store, "cost", whole_word=True, source_type="survey_response") == []


def test_case_filter(tmp_path):
    path = tmp_path / "p.qnw"
    with Project.create(path) as proj:
        for sid, text in TEXTS.items():
            src = Source(source_id=sid, type="document", raw_text=text, label=sid, metadata={})
            proj.add_source(src)
            proj.add_whole_response_excerpt(src)
        cid = proj.add_case(Case(case_id="", name="Alice"))
        proj.assign_source_to_case(cid, "s2")
        hits = search(proj, "cost", whole_word=True, case_id=cid)
    assert {h.source_id for h in hits} == {"s2"}


def test_code_filter(tmp_path):
    path = tmp_path / "p.qnw"
    with Project.create(path) as proj:
        code_id = proj.add_code(Code(code_id="", name="Money"))
        for sid, text in TEXTS.items():
            src = Source(source_id=sid, type="document", raw_text=text, label=sid, metadata={})
            proj.add_source(src)
            eid = proj.add_whole_response_excerpt(src)
            if sid == "s0":
                proj.apply_code(CodeApplication(application_id="", excerpt_id=eid,
                                                code_id=code_id, coder="human",
                                                rater_id="human_primary"))
        hits = search(proj, "cost", whole_word=True, code_name="Money")
    assert {h.source_id for h in hits} == {"s0"}


def test_search_store_convenience(store):
    assert len(search_store(store, "cost", whole_word=True)) == 3


def test_results_identical_with_and_without_the_index(store):
    """FTS is an accelerator: turning it off must not change the answers."""
    with Project.open(store) as proj:
        indexed = search(proj, "cost", whole_word=True)
        proj._fts_available = False               # force the scan path
        scanned = search(proj, "cost", whole_word=True)
    assert [(h.source_id, h.char_start) for h in indexed] == \
           [(h.source_id, h.char_start) for h in scanned]
