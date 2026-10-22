#!/usr/bin/env python
"""
Manual span coding — apply codes to passages of a document (v4, Phase 2b).

The defining act of qualitative analysis: select a passage, give it a code. Every
other coding path in QualSafe is automatic (the model codes a whole response) or
whole-unit (the Labeling Lab codes a whole survey answer). This is the one where
the analyst chooses the boundaries.

**The Streamlit problem, and the tiered answer.** There is no native Streamlit
widget that returns the character offsets of a mouse selection, and offsets are
non-negotiable — they are what ties a code to evidence. So selection is offered
three ways, all of which land the *same* `Excerpt` + `CodeApplication`:

1. **Pick units** — the document is split into sentences or paragraphs with exact
   offsets (`core.text_units.split_sentences`), and the analyst ticks the ones to
   code. No JavaScript, works today, and the unit boundaries are honest.
2. **Paste a passage** — the analyst copies text out of the reader and pastes it;
   it is located in the source with the three-tier matcher already used to verify
   LLM quotes (exact → normalized → bounded fuzzy). Arbitrary boundaries, no
   custom widget.
3. **Exact offsets** — for a caller that already knows them (a future
   selection component plugs in here and nothing else changes).

The invariant throughout: **the excerpt's text is taken from the source by
offset, never from what the user typed.** A pasted passage that differs from the
document by a smart quote is stored as the document's characters, not the
paste's.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

HUMAN_RATER = "human_primary"

_PARAGRAPH_BREAK = re.compile(r"\n\s*\n")


def codeable_units(text: str, unit: str = "sentence") -> List[Tuple[str, int, int]]:
    """Split a document into codeable units of ``(text, char_start, char_end)``.

    ``unit`` is ``"sentence"`` or ``"paragraph"``. Offsets are exact, so a unit
    picked here can be coded without any further matching.
    """
    text = text or ""
    if not text.strip():
        return []
    if unit == "sentence":
        from core.text_units import split_sentences

        spans = split_sentences(text)
        return spans if spans else [(text, 0, len(text))]
    if unit == "paragraph":
        out: List[Tuple[str, int, int]] = []
        pos = 0
        for chunk in _PARAGRAPH_BREAK.split(text):
            start = text.find(chunk, pos)
            if start < 0 or not chunk.strip():
                pos += len(chunk)
                continue
            out.append((chunk, start, start + len(chunk)))
            pos = start + len(chunk)
        return out or [(text, 0, len(text))]
    raise ValueError(f"Unknown unit {unit!r} (expected 'sentence' or 'paragraph').")


def locate_passage(
    project: Any, source_id: str, passage: str, *, allow_fuzzy: bool = True,
) -> Optional[Dict[str, Any]]:
    """Find a pasted passage in a document. Returns offsets, or None if absent.

    Reuses `interview.quotes.locate_quote`, so a paste that differs only in
    whitespace, quote style, or dashes still resolves — and a passage that is not
    really in the document is refused rather than coded to the wrong place.
    """
    from interview.quotes import locate_quote

    source = project.get_source(source_id)
    if source is None:
        return None
    found = locate_quote(passage, source.raw_text or "", allow_fuzzy=allow_fuzzy)
    if found is None:
        return None
    return {
        "char_start": found.char_start,
        "char_end": found.char_end,
        "text": found.text,
        "match_kind": found.match_kind,
        "similarity": found.similarity,
    }


def _excerpt_for_span(project: Any, source_id: str, start: int, end: int) -> str:
    """Reuse the excerpt for this exact span, or create it. Returns excerpt_id."""
    from core.model import Excerpt

    for excerpt in project.list_excerpts(source_id):
        if excerpt.char_start == start and excerpt.char_end == end:
            return excerpt.excerpt_id
    source = project.get_source(source_id)
    text = (source.raw_text or "")[start:end]
    return project.add_excerpt(Excerpt(excerpt_id="", source_id=source_id, text=text,
                                       char_start=start, char_end=end))


def apply_codes_to_span(
    project: Any,
    source_id: str,
    char_start: int,
    char_end: int,
    code_names: Sequence[str],
    *,
    rater_id: str = HUMAN_RATER,
    rater_name: str = "",
) -> Dict[str, Any]:
    """Code one passage. Returns ``{excerpt_id, applied, skipped, new_codes}``.

    Idempotent per rater: re-applying a code this rater already put on this span
    is skipped, not duplicated. Codes are matched by name and created (as
    `emergent`, `created_by='human'`) when new — which is in-vivo coding when the
    caller passes the selected text as the name.
    """
    from core.model import Code, CodeApplication, Rater

    source = project.get_source(source_id)
    if source is None:
        raise ValueError(f"No such source: {source_id}")
    text = source.raw_text or ""
    start, end = int(char_start), int(char_end)
    if not (0 <= start < end <= len(text)):
        raise ValueError(
            f"Span {start}–{end} is outside this document (0–{len(text)}).")

    names = [str(n).strip() for n in code_names if str(n).strip()]
    if not names:
        raise ValueError("Pick at least one code to apply.")

    project.add_rater(Rater(rater_id=rater_id, kind="human", name=rater_name))
    excerpt_id = _excerpt_for_span(project, source_id, start, end)

    coding = project.coding_table()
    already = set()
    if not coding.empty:
        mine = coding[(coding["rater_id"] == rater_id) & (coding["excerpt_id"] == excerpt_id)]
        already = set(mine["code_name"].tolist())

    result = {"excerpt_id": excerpt_id, "applied": 0, "skipped": 0, "new_codes": []}
    for name in names:
        if name in already:
            result["skipped"] += 1
            continue
        existing = project.find_code_by_name(name)
        if existing is None:
            code_id = project.add_code(Code(code_id="", name=name, origin="emergent",
                                            created_by="human"))
            result["new_codes"].append(name)
        else:
            code_id = existing.code_id
        project.apply_code(CodeApplication(
            application_id="", excerpt_id=excerpt_id, code_id=code_id,
            coder="human", rater_id=rater_id))
        already.add(name)
        result["applied"] += 1
    return result


def apply_codes_to_units(
    project: Any,
    source_id: str,
    units: Iterable[Tuple[int, int]],
    code_names: Sequence[str],
    *,
    rater_id: str = HUMAN_RATER,
    rater_name: str = "",
    merge_adjacent: bool = True,
) -> Dict[str, Any]:
    """Code several picked units at once.

    With ``merge_adjacent`` (the default), a contiguous run of picked units is
    coded as **one** passage rather than several — ticking three consecutive
    sentences means "this passage", and storing it as one excerpt keeps the quote
    readable and the co-occurrence counts honest.
    """
    spans = sorted((int(a), int(b)) for a, b in units)
    if not spans:
        raise ValueError("Pick at least one passage to code.")
    if merge_adjacent:
        merged: List[List[int]] = []
        source = project.get_source(source_id)
        text = (source.raw_text or "") if source else ""
        for start, end in spans:
            # Treat units separated only by whitespace as contiguous.
            if merged and not text[merged[-1][1]:start].strip():
                merged[-1][1] = max(merged[-1][1], end)
            else:
                merged.append([start, end])
        spans = [(a, b) for a, b in merged]

    totals = {"excerpts": [], "applied": 0, "skipped": 0, "new_codes": []}
    for start, end in spans:
        one = apply_codes_to_span(project, source_id, start, end, code_names,
                                  rater_id=rater_id, rater_name=rater_name)
        totals["excerpts"].append(one["excerpt_id"])
        totals["applied"] += one["applied"]
        totals["skipped"] += one["skipped"]
        for name in one["new_codes"]:
            if name not in totals["new_codes"]:
                totals["new_codes"].append(name)
    return totals


def remove_coding(
    project: Any, excerpt_id: str, *, code_name: Optional[str] = None,
    rater_id: str = HUMAN_RATER,
) -> int:
    """Uncode a passage: drop this rater's codings on it. Returns the count removed.

    Scoped to one rater so uncoding your own work never touches a colleague's or
    the model's. The excerpt itself stays — another rater may still be coding it.
    """
    coding = project.coding_table()
    if coding.empty:
        return 0
    mine = coding[(coding["excerpt_id"] == excerpt_id) & (coding["rater_id"] == rater_id)]
    if code_name:
        mine = mine[mine["code_name"] == code_name]
    for application_id in mine["application_id"].tolist():
        project.delete_application(application_id)
    return len(mine)
