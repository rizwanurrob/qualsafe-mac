#!/usr/bin/env python
"""
Auto-code every hit of a text search (v4, Phase 1.4).

"Code all 40 mentions of *tuition* as **Cost**" — the standard QDA move for
getting a lexically obvious theme onto the board in one action, so the analyst's
hand-coding time goes to the passages that actually need judgement.

Three properties this must have, because it writes codings into the store:

1. **Never mistaken for human coding.** Hits land under a distinct rater
   (`auto_textsearch`) whose `kind` is not ``"human"``. That keeps them out of
   human-vs-human kappa (the Agreement tab lists raters whose id starts with
   ``human``) and out of `core/store_merge`, which merges only ``kind ==
   "human"`` raters. Auto-coding must never inflate a reliability number.
2. **Reversible.** `remove_autocoded` deletes exactly what this created, so a
   regrettable query costs nothing.
3. **Idempotent.** Re-running the same query does not duplicate codings.

Note on `Rater.kind`: the model documents a three-value vocabulary
(human/transformer/llm) that other modules branch on, so this uses
``"transformer"`` — the closed vocabulary's "machine" value — rather than
inventing a fourth value that an existing `kind ==` check might mishandle. The
precise identity lives in `rater_id` and `name`, which say plainly that a text
search did this.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional

AUTOCODE_RATER = "auto_textsearch"


def autocode_hits(
    project: Any,
    hits: Iterable[Any],
    code_name: str,
    *,
    rater_id: str = AUTOCODE_RATER,
    query: str = "",
) -> Dict[str, int]:
    """Apply `code_name` to every search hit, as a span excerpt.

    `hits` are `core.search.SearchHit`s. Each hit becomes (or reuses) an excerpt
    covering exactly the matched characters, then gets one code application.

    Returns ``{"excerpts_created", "excerpts_reused", "applications", "skipped"}``
    where `skipped` counts hits this rater had already coded with this code.
    """
    from core.model import Code, CodeApplication, Excerpt, Rater
    from core.project import Project  # noqa: F401 - documents the expected type

    hits = list(hits)
    result = {"excerpts_created": 0, "excerpts_reused": 0, "applications": 0, "skipped": 0}
    if not hits:
        return result

    label = str(code_name or "").strip()
    if not label:
        raise ValueError("Pick a code name to apply.")

    name = "Text-search auto-coding"
    if query:
        name = f"Text-search auto-coding ({query})"
    project.add_rater(Rater(rater_id=rater_id, kind="transformer", name=name))

    existing_code = project.find_code_by_name(label)
    code_id = existing_code.code_id if existing_code else project.add_code(
        Code(code_id="", name=label, origin="emergent", created_by="human"))

    # Which (excerpt, code) pairs this rater already has → idempotency.
    coding = project.coding_table()
    already = set()
    if not coding.empty:
        mine = coding[(coding["rater_id"] == rater_id) & (coding["code_id"] == code_id)]
        already = set(mine["excerpt_id"].tolist())

    # Existing spans per source, so re-coding the same passage reuses its excerpt
    # rather than laying a duplicate over it.
    spans_by_source: Dict[str, Dict[tuple, str]] = {}

    for hit in hits:
        sid = hit.source_id
        if sid not in spans_by_source:
            spans_by_source[sid] = {
                (e.char_start, e.char_end): e.excerpt_id
                for e in project.list_excerpts(sid)
            }
        key = (hit.char_start, hit.char_end)
        excerpt_id = spans_by_source[sid].get(key)
        if excerpt_id is None:
            excerpt_id = project.add_excerpt(Excerpt(
                excerpt_id="", source_id=sid, text=hit.match_text,
                char_start=hit.char_start, char_end=hit.char_end))
            spans_by_source[sid][key] = excerpt_id
            result["excerpts_created"] += 1
        else:
            result["excerpts_reused"] += 1

        if excerpt_id in already:
            result["skipped"] += 1
            continue
        project.apply_code(CodeApplication(
            application_id="", excerpt_id=excerpt_id, code_id=code_id,
            coder="transformer", rater_id=rater_id,
            rationale=f"text search: {query}" if query else "text search"))
        already.add(excerpt_id)
        result["applications"] += 1

    if result["applications"]:
        project.log_event("auto_coded", f"Text search auto-coded {result['applications']} passage(s)",
                          target_type="rater", target_id=rater_id,
                          detail={"query": query, "applications": result["applications"]})
    return result


def remove_autocoded(
    project: Any,
    *,
    code_name: Optional[str] = None,
    rater_id: str = AUTOCODE_RATER,
) -> int:
    """Delete auto-coded applications (all, or just one code's). Returns the count.

    Only touches this rater's applications — human and model codings on the same
    excerpts are untouched. The excerpts themselves are left in place: another
    rater may have coded the same span, and an orphaned excerpt is harmless.
    """
    coding = project.coding_table()
    if coding.empty:
        return 0
    mine = coding[coding["rater_id"] == rater_id]
    if code_name:
        mine = mine[mine["code_name"] == code_name]
    ids = mine["application_id"].tolist()
    for application_id in ids:
        project.delete_application(application_id)
    return len(ids)
