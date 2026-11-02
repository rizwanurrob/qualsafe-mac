"""Notes on one coded passage: the jotting a researcher writes beside a line while reading it.

Update 3, book-audit item F6 (Saldaña 2013, p. 20: "jottings" beside the data). The store has kept these
since format v4 (the `annotations` table, one row per note, tied to an excerpt); neither screen offered them.
This is the thin, front-end-free layer both screens use. A note is the analyst's own text, so it is treated
like a memo: never sent anywhere, and not added to any export unless that export says it carries notes.
"""

from __future__ import annotations

from typing import Dict, Iterable, List

#: One jotting, not an essay (memos are for essays).
MAX_CHARS = 1000

MARK = "\u270e"          # a pencil, shown beside a passage that has a note


def clean(text: str) -> str:
    return str(text or "").strip()[:MAX_CHARS]


def notes_for(project, excerpt_id: str) -> List[object]:
    """The notes on one passage, oldest first."""
    return list(project.list_annotations(excerpt_id))


def add(project, excerpt_id: str, text: str, *, author: str = "human") -> str:
    """Add a note to a passage that already has an excerpt. Raises ValueError on empty text."""
    kept = clean(text)
    if not kept:
        raise ValueError("A note needs some text.")
    from core.model import Annotation

    return project.add_annotation(Annotation(annotation_id="", excerpt_id=excerpt_id, text=kept, author=author))


def counts(project, excerpt_ids: Iterable[str]) -> Dict[str, int]:
    """How many notes each of these passages has (passages with none are left out)."""
    wanted = set(excerpt_ids)
    out: Dict[str, int] = {}
    for note in project.list_annotations():
        if note.excerpt_id in wanted:
            out[note.excerpt_id] = out.get(note.excerpt_id, 0) + 1
    return out
