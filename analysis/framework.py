#!/usr/bin/env python
"""
Framework matrix — cases × themes, each cell a summary (v4, Phase 3.3).

The standard instrument for cross-case qualitative synthesis, and the thing
coding is *for*: a grid whose rows are cases (people, sites, groups), whose
columns are themes, and whose cells summarise what that case said about that
theme, with the supporting passages underneath.

QualSafe's advantage over doing this by hand: the local LLM can **draft** each
cell from the passages already coded there, and every quote it offers is
**verified verbatim against the source** with the same matcher used for interview
summaries — an unverifiable quote is dropped, not printed. Drafts are labelled as
drafts and are fully editable; the analyst owns the final text, as everywhere
else in this tool.

Cell text is stored as a `Memo` with ``target_type='framework_cell'`` — memos are
already generic over target type, so the matrix needs no new table.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import pandas as pd

MEMO_TARGET_TYPE = "framework_cell"
UNCASED = "(no case)"


def cell_target_id(case_id: str, code_name: str) -> str:
    """Stable memo target id for one cell. Case id + code *name* (names are the
    analyst's stable handle; a merged code should carry its summary along)."""
    return f"{case_id}::{code_name}"


def framework_cells(
    coding: pd.DataFrame,
    *,
    case_ids: Optional[Sequence[str]] = None,
    code_names: Optional[Sequence[str]] = None,
    include_uncased: bool = False,
) -> Dict[Tuple[str, str], List[str]]:
    """``{(case_id, code_name): [excerpt_id, ...]}`` from a coding-spans frame.

    Rows with no case are skipped unless `include_uncased`, in which case they
    are gathered under a single pseudo-case so material isn't silently invisible.
    """
    cells: Dict[Tuple[str, str], List[str]] = {}
    if coding.empty:
        return cells
    for _, row in coding.iterrows():
        case_id = str(row.get("case_id") or "")
        if not case_id:
            if not include_uncased:
                continue
            case_id = UNCASED
        code = str(row["code_name"])
        if case_ids is not None and case_id not in case_ids:
            continue
        if code_names is not None and code not in code_names:
            continue
        bucket = cells.setdefault((case_id, code), [])
        if row["excerpt_id"] not in bucket:
            bucket.append(row["excerpt_id"])
    return cells


def framework_grid(
    cells: Dict[Tuple[str, str], List[str]],
    case_labels: Dict[str, str],
    code_names: Sequence[str],
) -> pd.DataFrame:
    """Counts grid: one row per case, one column per code, values = passages.

    Deterministic ordering (cases by label, codes as given) so the grid is stable
    between runs and safe to export.
    """
    case_ids = sorted({c for c, _k in cells} | set(case_labels),
                      key=lambda cid: case_labels.get(cid, cid).lower())
    rows = []
    for case_id in case_ids:
        row = {"case": case_labels.get(case_id, case_id)}
        for code in code_names:
            row[code] = len(cells.get((case_id, code), []))
        rows.append(row)
    return pd.DataFrame(rows, columns=["case", *code_names])


def cell_excerpt_texts(project: Any, excerpt_ids: Sequence[str]) -> List[str]:
    """The verbatim text of a cell's passages, in store order."""
    out = []
    for excerpt_id in excerpt_ids:
        excerpt = project.get_excerpt(excerpt_id)
        if excerpt is not None and excerpt.text:
            out.append(excerpt.text)
    return out


# ── stored summaries (memo-backed) ──────────────────────────────────────────
def get_cell_summary(project: Any, case_id: str, code_name: str) -> Optional[Any]:
    """The stored Memo for a cell, or None."""
    target = cell_target_id(case_id, code_name)
    memos = project.list_memos(target_type=MEMO_TARGET_TYPE, target_id=target)
    return memos[0] if memos else None


def set_cell_summary(project: Any, case_id: str, code_name: str, text: str,
                     *, author: str = "human") -> str:
    """Create or replace a cell's summary. Returns the memo id."""
    from core.model import Memo

    existing = get_cell_summary(project, case_id, code_name)
    if existing is not None:
        project.update_memo(existing.memo_id, text)
        return existing.memo_id
    return project.add_memo(Memo(memo_id="", target_type=MEMO_TARGET_TYPE,
                                 target_id=cell_target_id(case_id, code_name),
                                 text=text, author=author))


# ── LLM drafting (injectable; verified quotes only) ─────────────────────────
DRAFT_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "quotes": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary"],
}

_PROMPT = """You are helping a qualitative researcher summarise coded material.

Theme: {code}
Case: {case}

Below are the passages this case contributed to this theme. Write a short,
factual summary (2-3 sentences) of what this case says about this theme, and
select up to {max_quotes} short quotes copied EXACTLY from the passages.

Do not invent anything. Do not generalise beyond these passages.

PASSAGES:
{passages}
"""


def draft_cell_summary(
    passages: Sequence[str],
    *,
    code_name: str,
    case_label: str,
    generate_json: Callable[[str, Dict[str, Any]], Dict[str, Any]],
    max_quotes: int = 3,
) -> Dict[str, Any]:
    """Draft one cell with an LLM, keeping only quotes that are really there.

    `generate_json(prompt, schema) -> dict` is injected, so this is testable with
    no Ollama and swappable for any backend. Returns
    ``{"summary", "quotes", "dropped", "note"}``; every returned quote is a
    verbatim substring of one of the passages — anything the model altered or
    invented is dropped and counted, exactly as interview summaries do it.
    """
    from interview.quotes import locate_quote

    kept = [p for p in passages if str(p).strip()]
    if not kept:
        return {"summary": "", "quotes": [], "dropped": 0, "note": "no_passages"}

    prompt = _PROMPT.format(
        code=code_name, case=case_label, max_quotes=max_quotes,
        passages="\n\n".join(f"- {p}" for p in kept))
    try:
        raw = generate_json(prompt, DRAFT_SCHEMA) or {}
    except Exception as exc:  # noqa: BLE001 - a failed draft must not lose the cell
        return {"summary": "", "quotes": [], "dropped": 0, "note": f"llm_error: {exc}"}

    haystack = "\n\n".join(kept)
    verified, dropped = [], 0
    for quote in (raw.get("quotes") or [])[: max_quotes * 2]:
        found = locate_quote(str(quote), haystack)
        if found is None:
            dropped += 1
            continue
        if found.text not in verified:
            verified.append(found.text)          # the SOURCE's characters
    return {
        "summary": str(raw.get("summary", "")).strip(),
        "quotes": verified[:max_quotes],
        "dropped": dropped,
        "note": "ok",
    }


def format_cell(summary: str, quotes: Sequence[str]) -> str:
    """Render a drafted cell as the markdown stored in the memo."""
    parts = [summary.strip()] if summary.strip() else []
    for quote in quotes:
        parts.append(f"> {quote.strip()}")
    return "\n\n".join(parts)
