"""Tests for codebook health checks (v3.9.6, F3)."""

from __future__ import annotations

from analysis.codebook_health import codebook_health
from core.model import Code


def _c(cid, name, definition="", parent_id=None):
    return Code(code_id=cid, name=name, definition=definition, parent_id=parent_id)


def test_flags_dead_singleton_and_undefined():
    codes = [
        _c("c1", "Applied often", "def"),
        _c("c2", "Never used", "def"),
        _c("c3", "Used once", "def"),
        _c("c4", "No definition"),
    ]
    freq = {"c1": 10, "c2": 0, "c3": 1, "c4": 5}
    h = codebook_health(codes, freq)
    assert [d["code_id"] for d in h["dead"]] == ["c2"]
    assert [d["code_id"] for d in h["singletons"]] == ["c3"]
    assert [d["code_id"] for d in h["undefined"]] == ["c4"]
    assert h["is_clean"] is False
    assert h["total_codes"] == 4


def test_missing_from_freq_counts_as_dead():
    codes = [_c("c1", "Orphaned-count", "def")]
    h = codebook_health(codes, {})  # c1 absent → 0 applications
    assert [d["code_id"] for d in h["dead"]] == ["c1"]


def test_flags_orphan_parent():
    codes = [_c("c1", "Child", "def", parent_id="ghost")]
    h = codebook_health(codes, {"c1": 3})
    assert h["orphans"][0]["missing_parent"] == "ghost"


def test_flags_excessive_depth():
    # Chain c0<-c1<-...<-c6 (depth 6 > MAX_SANE_DEPTH 5).
    codes = [_c("c0", "root", "def")]
    for i in range(1, 7):
        codes.append(_c(f"c{i}", f"n{i}", "def", parent_id=f"c{i-1}"))
    freq = {c.code_id: 2 for c in codes}
    h = codebook_health(codes, freq)
    assert "c6" in [d["code_id"] for d in h["too_deep"]]
    assert "c4" not in [d["code_id"] for d in h["too_deep"]]  # depth 4, fine


def test_clean_codebook_reports_clean():
    codes = [_c("c1", "A", "def"), _c("c2", "B", "def", parent_id="c1")]
    h = codebook_health(codes, {"c1": 4, "c2": 3})
    assert h["is_clean"] is True
    assert h["counts"] == {"dead": 0, "singletons": 0, "undefined": 0,
                           "orphans": 0, "too_deep": 0}


def test_depth_check_is_cycle_safe():
    # A malformed parent cycle must not hang the depth walk.
    codes = [_c("c1", "A", "def", parent_id="c2"), _c("c2", "B", "def", parent_id="c1")]
    h = codebook_health(codes, {"c1": 1, "c2": 1})
    assert isinstance(h["too_deep"], list)  # returns, doesn't hang
