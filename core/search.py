#!/usr/bin/env python
"""
Corpus search (v4, Phase 1.1).

Find a word or pattern anywhere in the project's text and see it in context —
the first thing a researcher does with a new corpus, and the thing QualSafe could
not do at all before v4 (every analysis was over *codes*).

**Design: FTS narrows, Python locates.** SQLite's FTS5 index says *which sources*
contain a term, very fast, but it does not give character offsets. Offsets are
what everything downstream needs — KWIC display, jumping to a passage, and
auto-coding a hit as an excerpt. So the index is used only to shortlist candidate
sources, and the exact positions are then found in Python. That keeps offsets
exact, keeps regex and literal search on the same code path, and makes FTS a pure
accelerator that can be absent (a SQLite without FTS5 falls back to a paged scan
— slower, same answers).

Consequently the user-facing modes are just **text** and **regex**; there is no
"FTS syntax" mode, because a query the index understands but Python cannot locate
would produce hits with no positions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from analysis.lexical import kwic_line

# Sources scanned per batch when falling back (or when the query can't be indexed).
_SCAN_PAGE = 200
# Safety valve: a pathological regex over a huge corpus should stop, not hang.
_MAX_HITS_PER_SOURCE = 500


@dataclass
class SearchHit:
    """One occurrence of a query in one source, with exact offsets."""
    source_id: str
    source_label: str
    source_type: str
    char_start: int
    char_end: int
    match_text: str
    left: str = ""
    right: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def kwic(self) -> str:
        return f"{self.left}[{self.match_text}]{self.right}"


def _build_pattern(query: str, *, mode: str, case_sensitive: bool, whole_word: bool):
    """Compile the query into a regex, or raise ValueError with a readable message."""
    if not (query or "").strip():
        raise ValueError("Enter something to search for.")
    flags = 0 if case_sensitive else re.IGNORECASE
    if mode == "regex":
        try:
            return re.compile(query, flags)
        except re.error as exc:
            raise ValueError(f"Invalid regular expression: {exc}") from exc
    pattern = re.escape(query.strip())
    if whole_word:
        pattern = rf"\b{pattern}\b"
    return re.compile(pattern, flags)


def _fts_query_for(query: str, *, whole_word: bool) -> Optional[str]:
    """An FTS5 phrase query that can shortlist candidates, or None if unsuitable.

    **Only valid for whole-word search.** FTS5 indexes *tokens*, so it can answer
    "which sources contain the word `cost`" but not "which contain the substring
    `advis`" — the latter occurs inside `advisor` and `advising`, which the index
    stores under different tokens. Shortlisting a substring search through the
    index therefore drops real matches silently, which is worse than being slow,
    so substring queries fall back to a full scan.

    Returns None for substring mode, empty queries, and queries with no word
    characters at all.
    """
    if not whole_word:
        return None
    words = re.findall(r"[A-Za-z0-9]+", query or "")
    if not words:
        return None
    # Require the words adjacent, as a phrase.
    return '"' + " ".join(words) + '"'


def search(
    project: Any,
    query: str,
    *,
    mode: str = "text",
    case_sensitive: bool = False,
    whole_word: bool = False,
    source_type: Optional[str] = None,
    case_id: Optional[str] = None,
    code_name: Optional[str] = None,
    limit: int = 200,
    kwic_width: int = 60,
) -> List[SearchHit]:
    """Search the project's source text. Returns hits with exact offsets.

    `project` is an open `Project`. Filters (`source_type`, `case_id`,
    `code_name`) narrow the corpus before searching; `limit` caps total hits so a
    common word on a big corpus stays responsive.
    """
    if mode not in ("text", "regex"):
        raise ValueError(f"Unknown search mode: {mode!r} (expected 'text' or 'regex').")
    pattern = _build_pattern(query, mode=mode, case_sensitive=case_sensitive,
                             whole_word=whole_word)

    allowed = _allowed_source_ids(project, source_type=source_type, case_id=case_id,
                                  code_name=code_name)

    # Shortlist via the index when we can; otherwise scan. (Whole-word text
    # search only — see _fts_query_for for why substring search cannot use it.)
    candidates: Optional[List[str]] = None
    if mode == "text" and project.fts_available():
        fts_q = _fts_query_for(query, whole_word=whole_word)
        if fts_q:
            try:
                candidates = project.fts_match_source_ids(fts_q, limit=5000)
            except ValueError:
                candidates = None  # malformed for FTS → just scan

    hits: List[SearchHit] = []
    for source in _iter_candidate_sources(project, candidates, allowed):
        text = source.raw_text or ""
        found = 0
        for m in pattern.finditer(text):
            if m.start() == m.end():        # zero-width match: don't spin
                continue
            left, match_text, right = kwic_line(text, m.start(), m.end(), width=kwic_width)
            hits.append(SearchHit(
                source_id=source.source_id, source_label=source.label or "",
                source_type=source.type, char_start=m.start(), char_end=m.end(),
                match_text=match_text, left=left, right=right,
                metadata=source.metadata or {},
            ))
            found += 1
            if len(hits) >= limit or found >= _MAX_HITS_PER_SOURCE:
                break
        if len(hits) >= limit:
            break
    return hits


def _allowed_source_ids(
    project: Any, *, source_type: Optional[str], case_id: Optional[str],
    code_name: Optional[str],
) -> Optional[set]:
    """The id set the filters permit, or None when unfiltered (= everything)."""
    allowed: Optional[set] = None

    def _intersect(ids):
        nonlocal allowed
        allowed = set(ids) if allowed is None else (allowed & set(ids))

    if case_id:
        _intersect(project.case_sources(case_id))
    if code_name:
        coding = project.coding_table()
        if coding.empty:
            _intersect([])
        else:
            matched = coding[coding["code_name"] == code_name]["source_id"].tolist()
            _intersect(matched)
    if source_type:
        # Applied during iteration too, but intersecting here keeps the shortlist tight.
        _intersect([s.source_id for s in _all_sources(project, source_type=source_type)])
    return allowed


def _all_sources(project: Any, *, source_type: Optional[str] = None) -> List[Any]:
    """Every source, read a page at a time so a large corpus isn't loaded at once."""
    out: List[Any] = []
    offset = 0
    while True:
        page = project.iter_sources(source_type=source_type, limit=_SCAN_PAGE, offset=offset)
        if not page:
            break
        out.extend(page)
        offset += _SCAN_PAGE
    return out


def _iter_candidate_sources(project: Any, candidates: Optional[List[str]], allowed: Optional[set]):
    """Sources to search: the FTS shortlist if there is one, else a paged scan."""
    if candidates is not None:
        for sid in candidates:
            if allowed is not None and sid not in allowed:
                continue
            source = project.get_source(sid)
            if source is not None:
                yield source
        return
    offset = 0
    while True:
        page = project.iter_sources(limit=_SCAN_PAGE, offset=offset)
        if not page:
            return
        for source in page:
            if allowed is not None and source.source_id not in allowed:
                continue
            yield source
        offset += _SCAN_PAGE


def search_store(store_path: Union[str, Path], query: str, **kwargs) -> List[SearchHit]:
    """Convenience: open a store by path, search it, close it."""
    from core.project import Project

    with Project.open(Path(store_path)) as proj:
        return search(proj, query, **kwargs)
