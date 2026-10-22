#!/usr/bin/env python
"""
Document corpus: import, library, and the reader's coding view (v4, Phase 2a).

QualSafe could hold one interview transcript at a time or a table of survey
responses. A qualitative project is usually neither: it is a folder of
transcripts, field notes, and reports that the researcher reads and codes. This
module makes that a first-class shape.

A document needs no new table — it is a `Source` with ``type='document'``, its
title/path/word-count in `metadata`. Coding a document produces ordinary
`Excerpt`s with character offsets, exactly like interview mode, so everything
downstream (frequency, co-occurrence, kappa, exports) already works on documents
with no changes.

One deliberate difference from survey ingestion: a document does **not** get an
automatic whole-source excerpt. A whole-response excerpt is the coding unit for a
survey answer; a whole-*document* excerpt would be a meaningless 40-page quote.
Documents get excerpts only where the analyst codes them.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Union

import pandas as pd

SUPPORTED_SUFFIXES = (".txt", ".md", ".docx", ".pdf")
DOCUMENT_TYPE = "document"


# ── reading files ───────────────────────────────────────────────────────────
def read_document_bytes(filename: str, data: bytes) -> str:
    """Extract text from an in-memory document. Mirrors `interview.parse.load_document`.

    Works on bytes rather than a path so an upload never has to be written to
    disk first — one less copy of sensitive text lying around.
    """
    suffix = Path(filename).suffix.lower()
    if suffix in (".txt", ".md"):
        return data.decode("utf-8", errors="replace")
    if suffix == ".docx":
        import docx

        return "\n".join(p.text for p in docx.Document(BytesIO(data)).paragraphs)
    if suffix == ".pdf":
        import pdfplumber

        with pdfplumber.open(BytesIO(data)) as pdf:
            return "\n".join(page.extract_text() or "" for page in pdf.pages)
    raise ValueError(
        f"Unsupported document type '{suffix}' (use {', '.join(SUPPORTED_SUFFIXES)})")


def read_document(path: Union[str, Path]) -> str:
    """Extract text from a document on disk."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Document not found: {path}")
    return read_document_bytes(path.name, path.read_bytes())


def list_documents_in_folder(folder: Union[str, Path]) -> List[Path]:
    """Supported document files directly inside `folder` (not recursive)."""
    folder = Path(folder).expanduser()
    if not folder.exists() or not folder.is_dir():
        return []
    return sorted(p for p in folder.iterdir()
                  if p.is_file() and p.suffix.lower() in SUPPORTED_SUFFIXES)


# ── importing into a project ────────────────────────────────────────────────
def _content_key(text: str) -> str:
    """Short hash of the document text, for spotting a re-import of the same file."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def existing_document_keys(project: Any) -> Dict[str, str]:
    """``{content_key: source_id}`` for documents already in the project."""
    out: Dict[str, str] = {}
    offset = 0
    while True:
        page = project.iter_sources(source_type=DOCUMENT_TYPE, limit=200, offset=offset)
        if not page:
            break
        for src in page:
            key = (src.metadata or {}).get("content_key")
            if key:
                out[key] = src.source_id
        offset += 200
    return out


def source_filename(source_path: Any) -> str:
    """The file's name, without the directories that led to it.

    A `.qnw` is the artifact this program tells the analyst they can share, and
    it used to carry the absolute path of every document imported into it. That
    path is not neutral. A real one looks like

        C:/Users/jsmith/OneDrive - State University/IRB-2026-0142/
        Participant Interviews/P07_Maria_Gonzalez_transcript.docx

    and a project file containing it hands the recipient the author's username,
    their institution's tenant, the protocol number, and a participant's name --
    inside the file a FERPA/IRB-safe tool offers up for sharing. Verified by
    searching the bytes of a store: every one of those strings was present.

    Nothing ever read it back. It was written by `add_document`, asserted by one
    test, and consumed by no code anywhere, so the whole leak bought nothing.

    The name is kept because provenance is a fair question -- "which file did
    this come from" -- and because the name is already visible: `import_documents`
    makes the title out of it. The directories are the part nobody chose to
    publish.
    """
    if not source_path:
        return ""
    # Split on both separators explicitly rather than using PurePath. A store
    # written on Windows may well be migrated on Linux -- that is the entire
    # scenario this function exists for -- and PurePosixPath does not treat a
    # backslash as a separator, so it would hand back the whole leaking path.
    text = str(source_path).replace("\\", "/")
    return text.rsplit("/", 1)[-1].strip()


def add_document(
    project: Any,
    title: str,
    text: str,
    *,
    source_path: str = "",
    case_id: Optional[str] = None,
) -> str:
    """Add one document to the project. Returns its source_id."""
    from core.model import Source
    from core.project import new_id

    source = Source(
        source_id=new_id("doc"),
        type=DOCUMENT_TYPE,
        raw_text=text,
        label=title,
        metadata={
            "title": title,
            "source_path": source_filename(source_path),
            "word_count": len(text.split()),
            "char_count": len(text),
            "content_key": _content_key(text),
            "imported_at": datetime.now().isoformat(timespec="seconds"),
        },
    )
    project.add_source(source)
    if case_id:
        project.assign_source_to_case(case_id, source.source_id)
    return source.source_id


def import_documents(
    project: Any,
    items: Sequence[Any],
    *,
    case_id: Optional[str] = None,
    skip_duplicates: bool = True,
) -> Dict[str, Any]:
    """Import many documents.

    `items` may be paths, or ``(filename, bytes)`` pairs for uploads. Returns
    ``{"imported": [...titles], "skipped": [...], "failed": [(name, reason)]}``.
    A document whose text is already in the project is skipped rather than
    duplicated — re-importing a folder after adding one file should add one file.
    Failures are reported per item so one unreadable PDF cannot abort the batch.
    """
    seen = existing_document_keys(project) if skip_duplicates else {}
    result: Dict[str, Any] = {"imported": [], "imported_ids": [], "skipped": [], "failed": []}

    for item in items:
        if isinstance(item, (str, Path)):
            path = Path(item)
            name, loader, origin = path.name, (lambda p=path: read_document(p)), str(path)
        else:
            name, data = item
            loader, origin = (lambda n=name, d=data: read_document_bytes(n, d)), ""
        try:
            text = loader()
        except Exception as exc:  # noqa: BLE001 - one bad file must not stop the batch
            result["failed"].append((name, str(exc)))
            continue
        if not text.strip():
            result["failed"].append((name, "no extractable text (a scanned PDF?)"))
            continue
        key = _content_key(text)
        if skip_duplicates and key in seen:
            result["skipped"].append(name)
            continue
        source_id = add_document(project, Path(name).stem, text, source_path=origin, case_id=case_id)
        seen[key] = name
        result["imported"].append(name)
        result["imported_ids"].append(source_id)
    return result


# ── library + reader views ──────────────────────────────────────────────────
def document_table(project: Any) -> pd.DataFrame:
    """One row per document: title, size, how much of it is coded, its cases."""
    coding = project.coding_table()
    per_source_codings: Dict[str, int] = {}
    if not coding.empty:
        per_source_codings = coding.groupby("source_id").size().to_dict()

    rows = []
    offset = 0
    while True:
        page = project.iter_sources(source_type=DOCUMENT_TYPE, limit=200, offset=offset)
        if not page:
            break
        for src in page:
            meta = src.metadata or {}
            cases = project.source_cases(src.source_id)
            case_names = {c.case_id: c.name for c in project.list_cases()}
            rows.append({
                "source_id": src.source_id,
                "title": meta.get("title") or src.label or src.source_id,
                "words": int(meta.get("word_count") or 0),
                "excerpts": len(project.list_excerpts(src.source_id)),
                "codings": int(per_source_codings.get(src.source_id, 0)),
                "cases": ", ".join(case_names.get(c, c) for c in cases),
                "imported": meta.get("imported_at", ""),
            })
        offset += 200
    return pd.DataFrame(
        rows,
        columns=["source_id", "title", "words", "excerpts", "codings", "cases", "imported"],
    )


def coding_spans(
    project: Any, source_id: str, *, rater_id: Optional[str] = None,
    code_names: Optional[Iterable[str]] = None,
) -> List[Dict[str, Any]]:
    """Coded spans in one document: ``{char_start, char_end, codes, raters}``.

    One entry per excerpt, with every code applied to it. Optionally filtered to
    one rater or a set of codes, which is how the reader lets an analyst look at
    just their own coding, or just one theme.
    """
    coding = project.coding_table()
    wanted = set(code_names) if code_names is not None else None

    by_excerpt: Dict[str, Dict[str, set]] = {}
    if not coding.empty:
        subset = coding[coding["source_id"] == source_id]
        if rater_id:
            subset = subset[subset["rater_id"] == rater_id]
        for _, row in subset.iterrows():
            name = row["code_name"]
            if wanted is not None and name not in wanted:
                continue
            entry = by_excerpt.setdefault(row["excerpt_id"], {"codes": set(), "raters": set()})
            entry["codes"].add(name)
            if row["rater_id"]:
                entry["raters"].add(row["rater_id"])

    spans = []
    for excerpt in project.list_excerpts(source_id):
        entry = by_excerpt.get(excerpt.excerpt_id)
        if not entry:
            continue
        spans.append({
            "excerpt_id": excerpt.excerpt_id,
            "char_start": excerpt.char_start,
            "char_end": excerpt.char_end,
            "codes": sorted(entry["codes"]),
            "raters": sorted(entry["raters"]),
        })
    return sorted(spans, key=lambda s: (s["char_start"], s["char_end"]))


def segment_by_spans(text: str, spans: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Cut `text` into consecutive segments, each carrying the codes covering it.

    Pure. Returns ``[{text, start, end, codes}]`` covering the whole document in
    order, so a reader can render it straight through. Overlapping and nested
    codings are handled by splitting at every span boundary: a passage coded both
    *Cost* and *Belonging* comes back as one segment carrying both, which is what
    lets the reader show layered highlights instead of losing one of them.
    """
    text = text or ""
    if not text:
        return []
    limit = len(text)
    boundaries = {0, limit}
    clean = []
    for span in spans:
        start = max(0, min(limit, int(span.get("char_start", 0))))
        end = max(0, min(limit, int(span.get("char_end", 0))))
        if end <= start:
            continue
        clean.append((start, end, list(span.get("codes") or [])))
        boundaries.add(start)
        boundaries.add(end)

    ordered = sorted(boundaries)
    out: List[Dict[str, Any]] = []
    for a, b in zip(ordered, ordered[1:]):
        if b <= a:
            continue
        codes = sorted({c for s, e, cs in clean if s <= a and e >= b for c in cs})
        out.append({"text": text[a:b], "start": a, "end": b, "codes": codes})
    return out


def coding_density(text_length: int, spans: Sequence[Dict[str, Any]]) -> float:
    """Share of the document covered by at least one coding, 0.0–1.0.

    Union of spans (overlaps counted once), so it answers "how much of this have
    I been through", not "how many codings did I apply".
    """
    if not text_length:
        return 0.0
    merged: List[List[int]] = []
    for span in sorted(spans, key=lambda s: s["char_start"]):
        start, end = int(span["char_start"]), int(span["char_end"])
        if end <= start:
            continue
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return min(1.0, sum(e - s for s, e in merged) / text_length)
