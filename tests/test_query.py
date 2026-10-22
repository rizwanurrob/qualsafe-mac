"""Tests for boolean coding queries (v4, Phase 3.1)."""

from __future__ import annotations

import pandas as pd
import pytest

from analysis.query import QueryError, evaluate, parse_query, query_codes, run_query

# excerpt e1/e2 in source s1 (case c1); e3 in s2 (case c2); e4 in s3 (no case)
CODING = pd.DataFrame([
    {"excerpt_id": "e1", "source_id": "s1", "code_name": "Cost",
     "char_start": 0, "char_end": 10, "case_id": "c1"},
    {"excerpt_id": "e1", "source_id": "s1", "code_name": "Belonging",
     "char_start": 0, "char_end": 10, "case_id": "c1"},
    {"excerpt_id": "e2", "source_id": "s1", "code_name": "Dropout",
     "char_start": 500, "char_end": 510, "case_id": "c1"},
    {"excerpt_id": "e3", "source_id": "s2", "code_name": "Cost",
     "char_start": 0, "char_end": 10, "case_id": "c2"},
    {"excerpt_id": "e4", "source_id": "s3", "code_name": "Belonging",
     "char_start": 0, "char_end": 10, "case_id": ""},
])


def _ids(text, unit="excerpt", coding=CODING):
    return set(run_query(coding, text, unit=unit)["unit_ids"])


# ── parsing ─────────────────────────────────────────────────────────────────
def test_parses_quoted_multiword_codes():
    tree = parse_query('"Cost worry" AND Belonging')
    assert query_codes(tree) == {"Cost worry", "Belonging"}


def test_operators_are_case_insensitive():
    assert _ids("Cost and Belonging") == _ids("Cost AND Belonging")


def test_parse_errors_are_readable():
    for bad in ("", "AND Cost", "Cost AND", "(Cost", "Cost)", "Cost AND (Belonging"):
        with pytest.raises(QueryError):
            parse_query(bad)


# ── evaluation ──────────────────────────────────────────────────────────────
def test_and_means_same_excerpt_by_default():
    assert _ids("Cost AND Belonging") == {"e1"}


def test_or_unions():
    assert _ids("Cost OR Belonging") == {"e1", "e3", "e4"}


def test_not_excludes():
    assert _ids("Belonging NOT Cost") == {"e4"}
    assert _ids("NOT Cost") == {"e2", "e4"}


def test_brackets_group():
    assert _ids("(Cost OR Dropout) AND NOT Belonging") == {"e2", "e3"}


def test_unit_changes_the_answer():
    """The same query means different things at different units."""
    # Cost and Dropout never share an excerpt...
    assert _ids("Cost AND Dropout") == set()
    # ...but they do share a source, and therefore a case.
    assert _ids("Cost AND Dropout", unit="source") == {"s1"}
    assert _ids("Cost AND Dropout", unit="case") == {"c1"}


def test_case_unit_ignores_uncased_material():
    assert _ids("Belonging", unit="case") == {"c1"}      # e4 has no case


def test_unknown_unit_is_refused():
    with pytest.raises(QueryError):
        evaluate(CODING, parse_query("Cost"), unit="paragraph")


# ── NEAR ────────────────────────────────────────────────────────────────────
def test_near_respects_distance():
    # Cost ends at 10, Dropout starts at 500 -> gap 490.
    assert _ids("Cost NEAR/1000 Dropout", unit="source") == {"s1"}
    assert _ids("Cost NEAR/100 Dropout", unit="source") == set()


def test_near_does_not_match_across_documents():
    coding = pd.DataFrame([
        {"excerpt_id": "a", "source_id": "sA", "code_name": "Cost",
         "char_start": 0, "char_end": 5, "case_id": ""},
        {"excerpt_id": "b", "source_id": "sB", "code_name": "Dropout",
         "char_start": 0, "char_end": 5, "case_id": ""},
    ])
    assert set(run_query(coding, "Cost NEAR/9999 Dropout", unit="source")["unit_ids"]) == set()


def test_near_requires_two_plain_codes():
    with pytest.raises(QueryError, match="NEAR compares two codes"):
        parse_query("(Cost OR Belonging) NEAR/50 Dropout")


# ── result shape ────────────────────────────────────────────────────────────
def test_run_query_resolves_excerpts_for_coarser_units():
    result = run_query(CODING, "Cost AND Dropout", unit="source")
    assert result["unit_ids"] == ["s1"]
    assert result["excerpt_ids"] == ["e1", "e2"]   # every passage in that source


def test_unknown_code_is_reported_not_silently_empty():
    result = run_query(CODING, "Nonexistent", unit="excerpt")
    assert result["unit_ids"] == []
    assert result["unknown_codes"] == ["Nonexistent"]


def test_code_matching_is_case_insensitive():
    assert _ids("cost") == _ids("Cost") == {"e1", "e3"}


def test_empty_coding_table_is_empty_not_an_error():
    empty = pd.DataFrame(columns=CODING.columns)
    result = run_query(empty, "Cost AND Belonging")
    assert result["unit_ids"] == [] and result["excerpt_ids"] == []
