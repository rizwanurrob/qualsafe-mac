"""Tests for semantic code merge suggestions (v3.9.6, F1)."""

from __future__ import annotations

import numpy as np
import pytest

from analysis.code_similarity import code_text, similar_code_pairs
from core.model import Code


def _code(cid, name, definition=""):
    return Code(code_id=cid, name=name, definition=definition)


# A toy embedding: each code text maps to a fixed vector by keyword, so cosines
# are known. "cost"/"financial" point the same way; "belonging" is orthogonal.
_VECS = {
    "cost": np.array([1.0, 0.0, 0.0]),
    "financial": np.array([0.98, 0.20, 0.0]),   # ~0.98 cosine with "cost"
    "belonging": np.array([0.0, 0.0, 1.0]),     # orthogonal
}


def _embed(texts):
    out = []
    for t in texts:
        low = t.lower()
        if "cost" in low:
            out.append(_VECS["cost"])
        elif "financ" in low:
            out.append(_VECS["financial"])
        else:
            out.append(_VECS["belonging"])
    return np.array(out)


def test_surfaces_semantically_similar_pair():
    codes = [_code("c1", "Cost worry"), _code("c2", "Financial stress"),
             _code("c3", "Belonging")]
    pairs = similar_code_pairs(codes, _embed, threshold=0.80)
    assert len(pairs) == 1
    p = pairs[0]
    assert {p["code_id_a"], p["code_id_b"]} == {"c1", "c2"}
    assert p["similarity"] >= 0.80


def test_unrelated_pair_below_threshold_excluded():
    codes = [_code("c1", "Cost worry"), _code("c3", "Belonging")]
    assert similar_code_pairs(codes, _embed, threshold=0.5) == []


def test_fewer_than_two_codes_returns_empty():
    assert similar_code_pairs([_code("c1", "Only one")], _embed) == []
    assert similar_code_pairs([], _embed) == []


def test_ordering_is_deterministic_by_similarity_then_name():
    # Three mutually "cost-like" codes so several pairs clear the threshold.
    codes = [_code("c3", "Cost B"), _code("c1", "Cost A"), _code("c2", "Cost C")]
    pairs = similar_code_pairs(codes, _embed, threshold=0.5)
    sims = [p["similarity"] for p in pairs]
    assert sims == sorted(sims, reverse=True)
    # Equal similarity → tie-broken by name_a then name_b (case-insensitive).
    top = pairs[0]
    assert top["name_a"].lower() <= top["name_b"].lower()


def test_top_k_caps_results():
    codes = [_code("c1", "Cost A"), _code("c2", "Cost B"), _code("c3", "Cost C")]
    assert len(similar_code_pairs(codes, _embed, threshold=0.5, top_k=1)) == 1


def test_bad_embed_shape_raises():
    codes = [_code("c1", "a"), _code("c2", "b")]
    with pytest.raises(ValueError):
        similar_code_pairs(codes, lambda texts: np.zeros((1, 3)), threshold=0.5)


def test_code_text_includes_definition():
    assert code_text(_code("c", "Cost", "worry about money")) == "Cost. worry about money"
    assert code_text(_code("c", "Cost")) == "Cost"
