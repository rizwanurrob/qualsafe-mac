"""Tests for the framework matrix (v4, Phase 3.3)."""

from __future__ import annotations

import pandas as pd
import pytest

from analysis.framework import (
    MEMO_TARGET_TYPE, UNCASED, cell_excerpt_texts, cell_target_id, draft_cell_summary,
    format_cell, framework_cells, framework_grid, get_cell_summary, set_cell_summary,
)
from core.documents import add_document
from core.model import Code, CodeApplication, Excerpt, Rater
from core.project import Project

CODING = pd.DataFrame([
    {"excerpt_id": "e1", "source_id": "s1", "code_name": "Cost", "case_id": "c1"},
    {"excerpt_id": "e2", "source_id": "s1", "code_name": "Cost", "case_id": "c1"},
    {"excerpt_id": "e3", "source_id": "s2", "code_name": "Belonging", "case_id": "c2"},
    {"excerpt_id": "e4", "source_id": "s3", "code_name": "Cost", "case_id": ""},
])


def test_cells_group_excerpts_by_case_and_code():
    cells = framework_cells(CODING)
    assert cells[("c1", "Cost")] == ["e1", "e2"]
    assert cells[("c2", "Belonging")] == ["e3"]
    assert ("", "Cost") not in cells       # uncased skipped by default


def test_uncased_material_can_be_included():
    cells = framework_cells(CODING, include_uncased=True)
    assert cells[(UNCASED, "Cost")] == ["e4"]


def test_cells_can_be_filtered():
    cells = framework_cells(CODING, case_ids=["c1"], code_names=["Cost"])
    assert list(cells) == [("c1", "Cost")]


def test_grid_counts_and_is_deterministic():
    cells = framework_cells(CODING)
    labels = {"c1": "Alice", "c2": "Bob"}
    grid = framework_grid(cells, labels, ["Cost", "Belonging"])
    assert list(grid.columns) == ["case", "Cost", "Belonging"]
    assert list(grid["case"]) == ["Alice", "Bob"]
    assert grid.loc[grid["case"] == "Alice", "Cost"].iloc[0] == 2
    assert grid.loc[grid["case"] == "Alice", "Belonging"].iloc[0] == 0
    # Same inputs, same order.
    assert list(framework_grid(cells, labels, ["Cost", "Belonging"])["case"]) == ["Alice", "Bob"]


def test_grid_includes_cases_with_no_codings():
    grid = framework_grid({}, {"c1": "Alice"}, ["Cost"])
    assert list(grid["case"]) == ["Alice"] and grid["Cost"].iloc[0] == 0


def test_empty_coding_gives_no_cells():
    assert framework_cells(pd.DataFrame(columns=CODING.columns)) == {}


def test_cell_target_id_is_stable():
    assert cell_target_id("c1", "Cost") == cell_target_id("c1", "Cost")
    assert cell_target_id("c1", "Cost") != cell_target_id("c2", "Cost")


# ── memo-backed summaries ───────────────────────────────────────────────────
@pytest.fixture()
def proj(tmp_path):
    project = Project.create(tmp_path / "p.qnw")
    yield project
    project.close()


def test_summary_round_trips_and_replaces(proj):
    assert get_cell_summary(proj, "c1", "Cost") is None
    set_cell_summary(proj, "c1", "Cost", "First version")
    assert get_cell_summary(proj, "c1", "Cost").text == "First version"
    set_cell_summary(proj, "c1", "Cost", "Edited")
    assert get_cell_summary(proj, "c1", "Cost").text == "Edited"
    # Replaced, not duplicated.
    assert len(proj.list_memos(target_type=MEMO_TARGET_TYPE)) == 1


def test_summaries_are_per_cell(proj):
    set_cell_summary(proj, "c1", "Cost", "A")
    set_cell_summary(proj, "c2", "Cost", "B")
    assert get_cell_summary(proj, "c1", "Cost").text == "A"
    assert get_cell_summary(proj, "c2", "Cost").text == "B"


def test_cell_excerpt_texts_reads_the_store(proj):
    sid = add_document(proj, "D", "the cost of housing is high")
    eid = proj.add_excerpt(Excerpt(excerpt_id="", source_id=sid, text="cost",
                                   char_start=4, char_end=8))
    assert cell_excerpt_texts(proj, [eid, "missing"]) == ["cost"]


# ── LLM drafting: quotes must be verified ───────────────────────────────────
def _fake_llm(payload):
    return lambda prompt, schema: payload


def test_draft_keeps_only_quotes_that_are_really_there():
    passages = ["The cost of housing is the hardest part.", "I worry about tuition."]
    out = draft_cell_summary(
        passages, code_name="Cost", case_label="Alice",
        generate_json=_fake_llm({
            "summary": "Cost dominates.",
            "quotes": ["cost of housing", "I never said this at all"],
        }))
    assert out["summary"] == "Cost dominates."
    assert out["quotes"] == ["cost of housing"]
    assert out["dropped"] == 1


def test_draft_returns_source_characters_not_the_models():
    """A quote the model retyped with smart quotes still resolves — and what is
    stored is the passage's own characters, not the model's."""
    passages = ['She said "the cost is high" today.']
    out = draft_cell_summary(
        passages, code_name="Cost", case_label="A",
        generate_json=_fake_llm({"summary": "s", "quotes": ['“the  cost is high”']}))
    assert len(out["quotes"]) == 1 and out["dropped"] == 0
    quote = out["quotes"][0]
    assert "the cost is high" in quote
    assert "“" not in quote and "”" not in quote      # the model's characters are gone
    assert quote in passages[0]                        # verbatim from the passage


def test_draft_handles_no_passages_and_llm_failure():
    empty = draft_cell_summary([], code_name="C", case_label="A",
                               generate_json=_fake_llm({}))
    assert empty["note"] == "no_passages"

    def boom(prompt, schema):
        raise RuntimeError("ollama down")

    failed = draft_cell_summary(["text"], code_name="C", case_label="A", generate_json=boom)
    assert failed["note"].startswith("llm_error") and failed["summary"] == ""


def test_draft_respects_max_quotes():
    passages = ["alpha beta gamma delta epsilon"]
    out = draft_cell_summary(
        passages, code_name="C", case_label="A", max_quotes=2,
        generate_json=_fake_llm({"summary": "s",
                                 "quotes": ["alpha", "beta", "gamma", "delta"]}))
    assert len(out["quotes"]) == 2


def test_format_cell_renders_summary_and_quotes():
    text = format_cell("A summary.", ["first", "second"])
    assert text.startswith("A summary.")
    assert "> first" in text and "> second" in text
    assert format_cell("", []) == ""
