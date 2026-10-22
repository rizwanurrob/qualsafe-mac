#!/usr/bin/env python
"""
Interview document parsing: load + segment into speaker turns (v3.1, I1).

Stage [1]: load a .txt / .docx / .pdf transcript to raw text, preserving line
breaks (they are the speaker-turn signal).
  - DOCX via python-docx; PDF via pdfplumber. pdfplumber was chosen over PyMuPDF
    deliberately: PyMuPDF is AGPL-licensed, which conflicts with this project's
    MIT release; pdfplumber is MIT and adequate for digital-text transcripts.
    (Scanned/OCR PDFs are out of scope for v3.1 — documented limitation.)

Stage [2]: segment raw text into ordered `Turn`s using a small LIBRARY of
regex-based speaker-label detectors (not one regex — transcript formats vary):
  - interviewer_respondent : "Interviewer: ..." / "Respondent: ..."
  - q_a                    : "Q: ..." / "A: ..."
  - timestamped            : "[00:03:12] Speaker 1: ..."
  - name_colon             : "JD: ..." / "Maria: ..." / "Dr. Smith: ..."
Each detector is scored against the document; the best valid one wins, with a
confidence signal. When nothing matches confidently, the whole document becomes a
single UNKNOWN turn with confidence 0.0 — the analyst sees this at the mandatory
review checkpoint instead of the tool silently guessing. (LLM-assisted
segmentation is a later enhancement; the seam is `segment_turns`.)

Offset guarantee: every Turn's `text` equals raw_text[char_start:char_end]
verbatim, so downstream excerpts/quotes stay verifiable against the source.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple, Union


@dataclass
class Turn:
    index: int
    speaker_raw: str              # label exactly as it appeared in the document
    text: str                     # == raw_text[char_start:char_end]
    char_start: int
    char_end: int
    speaker_role: Optional[str] = None   # "interviewer" | "interviewee" | "other" | None


@dataclass
class SpeakerPattern:
    name: str
    regex: re.Pattern
    priority: int                 # lower = preferred on equal match counts


# Ordered detector library. Specific formats first; generic name-colon last.
PATTERNS: List[SpeakerPattern] = [
    SpeakerPattern(
        name="interviewer_respondent",
        regex=re.compile(
            r"^\s*(?P<label>interviewer|respondent|interviewee|moderator|participant|facilitator)\s*:\s?",
            re.IGNORECASE,
        ),
        priority=0,
    ),
    SpeakerPattern(
        name="q_a",
        regex=re.compile(r"^\s*(?P<label>[QA])\s*[:.]\s"),
        priority=1,
    ),
    SpeakerPattern(
        name="timestamped",
        regex=re.compile(
            r"^\s*\[?(?:\d{1,2}:)?\d{1,2}:\d{2}\]?\s+(?P<label>[^:\n]{1,40}?)\s*:\s?"
        ),
        priority=2,
    ),
    SpeakerPattern(
        name="name_colon",
        regex=re.compile(
            r"^\s*(?P<label>[A-Z][A-Za-z.]{0,15}(?:\s[A-Z][A-Za-z.]{0,15})?)\s*:\s"
        ),
        priority=3,
    ),
]

# A pattern is trusted outright at this many matched label-lines (with >=2 labels).
_MIN_STRONG_MATCHES = 4
_MIN_WEAK_MATCHES = 2


def load_document(path: Union[str, Path]) -> str:
    """Load a transcript to raw text. Supports .txt, .docx, .pdf.

    Paragraph/page breaks become newlines so turn boundaries survive extraction.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Interview document not found: {path}")
    ext = path.suffix.lower()

    if ext == ".txt":
        return path.read_text(encoding="utf-8")

    if ext == ".docx":
        import docx  # python-docx; local import keeps the dep optional at import time
        document = docx.Document(str(path))
        return "\n".join(p.text for p in document.paragraphs)

    if ext == ".pdf":
        import pdfplumber  # MIT license (chosen over AGPL PyMuPDF)
        pages: List[str] = []
        with pdfplumber.open(str(path)) as pdf:
            for page in pdf.pages:
                pages.append(page.extract_text() or "")
        return "\n".join(pages)

    raise ValueError(f"Unsupported interview document type '{ext}' (use .txt, .docx, or .pdf)")


def _line_offsets(raw_text: str) -> List[Tuple[int, int, str]]:
    """(start, end, line) for each line, offsets into raw_text."""
    out: List[Tuple[int, int, str]] = []
    pos = 0
    for line in raw_text.split("\n"):
        out.append((pos, pos + len(line), line))
        pos += len(line) + 1
    return out


def _score_pattern(pattern: SpeakerPattern, lines: List[Tuple[int, int, str]]):
    """Return (matches, distinct_labels) where matches = [(line_idx, label, content_start)]."""
    matches = []
    labels = set()
    for i, (start, _end, line) in enumerate(lines):
        m = pattern.regex.match(line)
        if m:
            label = m.group("label").strip()
            matches.append((i, label, start + m.end()))
            labels.add(label)
    return matches, labels


def choose_pattern(raw_text: str) -> Tuple[Optional[SpeakerPattern], list, float]:
    """Pick the best-matching detector for this document.

    Returns (pattern, matches, confidence). Confidence = matched label-lines /
    non-empty lines; 0.0 when no detector produces >=2 matches with >=2 distinct
    labels (a conversation needs at least two voices).
    """
    lines = _line_offsets(raw_text)
    n_nonempty = sum(1 for _s, _e, ln in lines if ln.strip()) or 1

    best = None  # (neg_matches, priority, pattern, matches)
    for pattern in PATTERNS:
        matches, labels = _score_pattern(pattern, lines)
        if len(matches) < _MIN_WEAK_MATCHES or len(labels) < 2:
            continue
        key = (-len(matches), pattern.priority)
        if best is None or key < (best[0], best[1]):
            best = (key[0], key[1], pattern, matches)

    if best is None:
        return None, [], 0.0

    pattern, matches = best[2], best[3]
    confidence = min(1.0, len(matches) / n_nonempty)
    if len(matches) < _MIN_STRONG_MATCHES:
        confidence = min(confidence, 0.4)   # matched, but thin evidence
    return pattern, matches, confidence


def segment_turns(
    raw_text: str,
    pattern_name: str = "auto",
) -> Tuple[List[Turn], str, float]:
    """Segment a transcript into speaker turns.

    Returns (turns, pattern_name_used, confidence). With pattern_name="auto" the
    detector library is scored and the best one used. On no confident match the
    whole document is returned as one UNKNOWN turn with confidence 0.0 — surfaced
    to the analyst at the review checkpoint, never silently guessed.
    """
    lines = _line_offsets(raw_text)

    if pattern_name == "auto":
        pattern, matches, confidence = choose_pattern(raw_text)
    else:
        pattern = next((p for p in PATTERNS if p.name == pattern_name), None)
        if pattern is None:
            raise ValueError(f"Unknown speaker pattern '{pattern_name}'. "
                             f"Available: {[p.name for p in PATTERNS]} or 'auto'.")
        matches, labels = _score_pattern(pattern, lines)
        n_nonempty = sum(1 for _s, _e, ln in lines if ln.strip()) or 1
        confidence = min(1.0, len(matches) / n_nonempty) if len(labels) >= 2 else 0.0

    if pattern is None or not matches:
        text = raw_text.strip()
        start = raw_text.find(text) if text else 0
        return (
            [Turn(index=0, speaker_raw="UNKNOWN", text=text,
                  char_start=start, char_end=start + len(text))],
            "none", 0.0,
        )

    turns: List[Turn] = []
    for k, (line_idx, label, content_start) in enumerate(matches):
        # Block runs from after this label to the start of the next labeled line.
        if k + 1 < len(matches):
            next_line_idx = matches[k + 1][0]
            block_end = lines[next_line_idx][0]           # start of next label line
        else:
            block_end = len(raw_text)

        char_start, char_end = content_start, block_end
        # Trim whitespace while keeping text == raw[start:end] verbatim.
        while char_start < char_end and raw_text[char_start].isspace():
            char_start += 1
        while char_end > char_start and raw_text[char_end - 1].isspace():
            char_end -= 1

        turns.append(Turn(
            index=k, speaker_raw=label,
            text=raw_text[char_start:char_end],
            char_start=char_start, char_end=char_end,
        ))

    return turns, pattern.name, confidence


def parse_interview(path: Union[str, Path], pattern_name: str = "auto"):
    """Convenience: load a document and segment it. Returns (raw_text, turns, pattern, confidence)."""
    raw_text = load_document(path)
    turns, used, confidence = segment_turns(raw_text, pattern_name=pattern_name)
    return raw_text, turns, used, confidence
