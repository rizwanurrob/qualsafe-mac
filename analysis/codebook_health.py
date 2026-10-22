#!/usr/bin/env python
"""
Codebook health checks (v3.9.6, F3).

A read-only hygiene view over the codebook, most useful right after a multi-coder
merge drops in a batch of emergent codes. It surfaces codes that are never
applied, applied once, undefined, or structurally odd (a parent that doesn't
exist, or nesting deeper than is legible). Pure functions over the codebook +
application counts — no I/O, no Streamlit, no mutation. The UI presents them and
offers the fix (define / merge / delete) through the existing Codebook controls.
"""

from __future__ import annotations

from typing import Any, Dict, List, Sequence

# Codebook hierarchy deeper than this is almost always accidental (a reparent gone
# wrong) rather than intended; flag it for review. Not enforced — just advisory.
MAX_SANE_DEPTH = 5


def _depth(code_id: str, parent_of: Dict[str, str]) -> int:
    """Depth of a code in the hierarchy (root = 0), cycle-safe."""
    depth = 0
    seen = {code_id}
    cur = parent_of.get(code_id)
    while cur:
        depth += 1
        if cur in seen or depth > 1000:  # defensive: a malformed cycle can't hang
            break
        seen.add(cur)
        cur = parent_of.get(cur)
    return depth


def codebook_health(codes: Sequence[Any], freq: Dict[str, int]) -> Dict[str, Any]:
    """Report codebook hygiene issues.

    ``codes`` is a list of Code-like objects (``code_id``, ``name``,
    ``definition``, ``parent_id``); ``freq`` maps ``code_id -> application count``
    (as ``Project.code_frequency`` returns). A code absent from ``freq`` is
    treated as zero applications.

    Returns a dict of issue lists (each a list of ``{"code_id", "name", ...}``)
    plus a ``counts`` summary and ``total_codes``. Empty lists mean a clean bill.
    """
    ids = {c.code_id for c in codes}
    parent_of = {c.code_id: c.parent_id for c in codes if getattr(c, "parent_id", None)}

    dead: List[dict] = []
    singletons: List[dict] = []
    undefined: List[dict] = []
    orphans: List[dict] = []
    too_deep: List[dict] = []

    for c in codes:
        n = int(freq.get(c.code_id, 0))
        if n == 0:
            dead.append({"code_id": c.code_id, "name": c.name})
        elif n == 1:
            singletons.append({"code_id": c.code_id, "name": c.name})
        if not str(getattr(c, "definition", "") or "").strip():
            undefined.append({"code_id": c.code_id, "name": c.name})
        parent = getattr(c, "parent_id", None)
        if parent and parent not in ids:
            orphans.append({"code_id": c.code_id, "name": c.name, "missing_parent": parent})
        depth = _depth(c.code_id, parent_of)
        if depth > MAX_SANE_DEPTH:
            too_deep.append({"code_id": c.code_id, "name": c.name, "depth": depth})

    issues = {
        "dead": dead,
        "singletons": singletons,
        "undefined": undefined,
        "orphans": orphans,
        "too_deep": too_deep,
    }
    return {
        "total_codes": len(codes),
        "counts": {k: len(v) for k, v in issues.items()},
        "is_clean": all(not v for v in issues.values()),
        **issues,
    }
