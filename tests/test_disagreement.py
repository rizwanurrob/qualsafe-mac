"""Tests for coder disagreement drill-down (v3.9.6, F2)."""

from __future__ import annotations

from analysis.disagreement import disagreement_summary, disagreements


def test_flags_only_differing_shared_items():
    a = {"e1": {"Cost"}, "e2": {"Belonging"}, "e3": {"Cost", "Prep"}}
    b = {"e1": {"Cost"}, "e2": {"Prep"}, "e3": {"Cost"}}
    out = disagreements(a, b)
    ids = [d["excerpt_id"] for d in out]
    assert ids == ["e2", "e3"]  # e1 agrees; sorted order


def test_records_a_only_b_only_and_agreed():
    a = {"e3": {"Cost", "Prep"}}
    b = {"e3": {"Cost"}}
    d = disagreements(a, b)[0]
    assert d["a_only"] == ["Prep"]
    assert d["b_only"] == []
    assert d["agreed"] == ["Cost"]
    assert d["a_codes"] == ["Cost", "Prep"]


def test_both_uncoded_is_agreement_not_disagreement():
    a = {"e1": set()}
    b = {"e1": set()}
    assert disagreements(a, b) == []


def test_non_overlapping_items_ignored():
    a = {"e1": {"Cost"}}
    b = {"e2": {"Prep"}}
    assert disagreements(a, b) == []


def test_summary_counts():
    a = {"e1": {"Cost"}, "e2": {"Belonging"}, "e3": {"Cost"}, "e9": {"Only A"}}
    b = {"e1": {"Cost"}, "e2": {"Prep"}, "e3": {"Prep"}, "e8": {"Only B"}}
    s = disagreement_summary(a, b)
    assert s == {"overlap_items": 3, "agree_items": 1, "disagree_items": 2}
