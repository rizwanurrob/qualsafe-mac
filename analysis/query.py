#!/usr/bin/env python
"""
Boolean coding queries — retrieve, not just count (v4, Phase 3.1).

Co-occurrence tells you *how often* two codes appear together. It cannot answer
"show me the passages coded **Cost** but **not** FirstGen", which is the question
an analyst actually asks when writing up. This adds retrieval by code logic:

    Cost AND Belonging
    "Cost worry" OR Housing
    Cost NOT FirstGen
    Cost NEAR/200 dropout

Pure functions over the frame `Project.coding_spans_table()` returns — no store,
no Streamlit — so the evaluator is testable without a database.

**Unit matters and is explicit.** `Cost AND Belonging` means "both codes on the
same *excerpt*" by default, but at `unit="source"` it means "both somewhere in the
same document", and at `unit="case"` "both somewhere in the same person's
material". Those are different questions with different answers, so the unit is a
parameter rather than a hidden assumption — the same discipline the rest of the
tool applies to response-vs-sentence units.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

import pandas as pd

UNITS = ("excerpt", "source", "case")
_UNIT_COLUMN = {"excerpt": "excerpt_id", "source": "source_id", "case": "case_id"}

# Proximity is measured in characters, not words: excerpts carry character
# offsets, so characters need no re-tokenizing and cannot drift from the text.
_TOKEN_RE = re.compile(r"""
    \s*(?:
        (?P<lparen>\()
      | (?P<rparen>\))
      | (?P<near>NEAR\s*/\s*(?P<near_n>\d+))
      | (?P<op>\bAND\b|\bOR\b|\bNOT\b)
      | "(?P<quoted>[^"]*)"
      | (?P<bare>[^\s()"]+)
    )""", re.VERBOSE | re.IGNORECASE)


class QueryError(ValueError):
    """A query that cannot be parsed or refers to something that can't work."""


@dataclass
class _Node:
    kind: str                      # "code" | "and" | "or" | "not" | "near"
    value: Any = None              # code name, or (left, right)
    distance: int = 0


# ── parsing ─────────────────────────────────────────────────────────────────
def _tokenize(text: str) -> List[Tuple[str, Any]]:
    tokens: List[Tuple[str, Any]] = []
    pos = 0
    while pos < len(text):
        if text[pos].isspace():
            pos += 1
            continue
        match = _TOKEN_RE.match(text, pos)
        if not match or match.end() == pos:
            raise QueryError(f"Could not read the query at position {pos}.")
        pos = match.end()
        if match.group("lparen"):
            tokens.append(("(", None))
        elif match.group("rparen"):
            tokens.append((")", None))
        elif match.group("near"):
            tokens.append(("NEAR", int(match.group("near_n"))))
        elif match.group("op"):
            tokens.append((match.group("op").upper(), None))
        elif match.group("quoted") is not None:
            tokens.append(("CODE", match.group("quoted")))
        else:
            tokens.append(("CODE", match.group("bare")))
    return tokens


def parse_query(text: str) -> _Node:
    """Parse a query string into an evaluable tree. Raises QueryError."""
    tokens = _tokenize(text or "")
    if not tokens:
        raise QueryError("Enter a query, e.g. Cost AND Belonging")
    pos = 0

    def peek() -> Optional[Tuple[str, Any]]:
        return tokens[pos] if pos < len(tokens) else None

    def take() -> Tuple[str, Any]:
        nonlocal pos
        token = tokens[pos]
        pos += 1
        return token

    def parse_or() -> _Node:
        node = parse_and()
        while peek() and peek()[0] == "OR":
            take()
            node = _Node("or", (node, parse_and()))
        return node

    def parse_and() -> _Node:
        node = parse_unary()
        while peek() and peek()[0] in ("AND", "NOT", "NEAR"):
            kind, distance = take()
            if kind == "NEAR":
                right = parse_unary()
                if node.kind != "code" or right.kind != "code":
                    raise QueryError(
                        "NEAR compares two codes, e.g. Cost NEAR/200 dropout — it "
                        "cannot take a bracketed expression.")
                node = _Node("near", (node, right), distance=distance)
            elif kind == "NOT":
                # "A NOT B" is the familiar shorthand for "A AND NOT B".
                node = _Node("and", (node, _Node("not", parse_unary())))
            else:
                node = _Node("and", (node, parse_unary()))
        return node

    def parse_unary() -> _Node:
        token = peek()
        if token is None:
            raise QueryError("The query ends with an operator that needs a code after it.")
        if token[0] == "NOT":
            take()
            return _Node("not", parse_unary())
        if token[0] == "(":
            take()
            node = parse_or()
            if not peek() or peek()[0] != ")":
                raise QueryError("Missing a closing bracket.")
            take()
            return node
        if token[0] == "CODE":
            return _Node("code", take()[1])
        raise QueryError(f"Unexpected '{token[0]}' in the query.")

    tree = parse_or()
    if pos != len(tokens):
        raise QueryError("Unexpected text after the end of the query "
                         "(a missing operator, or an extra bracket?).")
    return tree


def query_codes(node: _Node) -> Set[str]:
    """Every code name mentioned — used to warn about names not in the codebook."""
    if node.kind == "code":
        return {node.value}
    if node.kind == "not":
        return query_codes(node.value)
    left, right = node.value
    return query_codes(left) | query_codes(right)


# ── evaluation ──────────────────────────────────────────────────────────────
def _units_for_code(coding: pd.DataFrame, code: str, unit_col: str) -> Set[str]:
    hits = coding[coding["code_name"].str.lower() == code.lower()]
    return {u for u in hits[unit_col].tolist() if u != ""}


def _near_units(coding: pd.DataFrame, left: str, right: str, distance: int,
                unit_col: str) -> Set[str]:
    """Units where the two codes have spans within `distance` characters.

    Proximity only means something inside one document, so spans are compared
    per source; the qualifying source's unit id is then returned.
    """
    if "char_start" not in coding.columns:
        raise QueryError("NEAR needs character offsets, which this table doesn't carry.")
    lo = coding[coding["code_name"].str.lower() == left.lower()]
    hi = coding[coding["code_name"].str.lower() == right.lower()]
    out: Set[str] = set()
    for source_id, lgroup in lo.groupby("source_id"):
        rgroup = hi[hi["source_id"] == source_id]
        if rgroup.empty:
            continue
        for _, a in lgroup.iterrows():
            for _, b in rgroup.iterrows():
                gap = max(int(a["char_start"]) - int(b["char_end"]),
                          int(b["char_start"]) - int(a["char_end"]), 0)
                if gap <= distance:
                    out.update(u for u in [a[unit_col], b[unit_col]] if u != "")
    return out


def evaluate(
    coding: pd.DataFrame, node: _Node, *, unit: str = "excerpt",
) -> Set[str]:
    """Unit ids matching the parsed query."""
    if unit not in UNITS:
        raise QueryError(f"Unknown unit {unit!r} (expected one of {UNITS}).")
    unit_col = _UNIT_COLUMN[unit]
    if coding.empty:
        return set()
    universe = {u for u in coding[unit_col].tolist() if u != ""}

    def walk(n: _Node) -> Set[str]:
        if n.kind == "code":
            return _units_for_code(coding, n.value, unit_col)
        if n.kind == "not":
            return universe - walk(n.value)
        left, right = n.value
        if n.kind == "and":
            return walk(left) & walk(right)
        if n.kind == "or":
            return walk(left) | walk(right)
        if n.kind == "near":
            return _near_units(coding, left.value, right.value, n.distance, unit_col)
        raise QueryError(f"Unknown query node {n.kind!r}.")

    return walk(node)


def run_query(
    coding: pd.DataFrame, text: str, *, unit: str = "excerpt",
) -> Dict[str, Any]:
    """Parse and evaluate in one step.

    Returns ``{"unit", "unit_ids", "excerpt_ids", "codes_used", "unknown_codes"}``.
    `excerpt_ids` are always resolved (even for source/case units) so the caller
    can show the underlying passages.
    """
    tree = parse_query(text)
    unit_ids = evaluate(coding, tree, unit=unit)
    unit_col = _UNIT_COLUMN[unit]
    excerpt_ids: List[str] = []
    if unit_ids and not coding.empty:
        matched = coding[coding[unit_col].isin(unit_ids)]
        excerpt_ids = sorted(set(matched["excerpt_id"].tolist()))

    used = query_codes(tree)
    known = {c.lower() for c in coding["code_name"].tolist()} if not coding.empty else set()
    unknown = sorted(c for c in used if c.lower() not in known)
    return {
        "unit": unit,
        "unit_ids": sorted(unit_ids),
        "excerpt_ids": excerpt_ids,
        "codes_used": sorted(used),
        "unknown_codes": unknown,
    }
