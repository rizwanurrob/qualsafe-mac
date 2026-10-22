#!/usr/bin/env python
"""
Offline sentence unitization (v4, Phase 4.4).

Coding at the response level answers "which themes did this person touch?"; coding
at the sentence level answers "which themes co-occur *in the same breath*?" — a
tighter, more defensible co-occurrence claim. This module splits a response into
sentence spans so a finer unit of analysis is available.

**Offline by requirement.** The tool must run with the network off, so this uses no
spaCy model, no `nltk.download`, no external data — just a rule-based splitter with
a short abbreviation guard. It is deliberately conservative: survey/interview text
is messy, and over-splitting ("Dr. Chen" → two units) corrupts the analysis worse
than under-splitting.

**Offset guarantee.** Every returned span satisfies ``text[start:end] ==
sentence`` (leading/trailing whitespace excluded from the span), so excerpts built
from these offsets trace back to the exact source characters — the same invariant
the interview quote-verifier relies on.
"""

from __future__ import annotations

import re
from typing import List, Tuple

# Common abbreviations whose trailing period is NOT a sentence end. Lowercased,
# compared case-insensitively. Kept small and high-frequency on purpose.
_ABBREVIATIONS = {
    "mr", "mrs", "ms", "dr", "prof", "sr", "jr", "st", "vs", "etc", "eg", "ie",
    "no", "vol", "dept", "univ", "inc", "ltd", "co", "approx", "fig", "al",
    "a.m", "p.m", "u.s", "u.k",
}

# A sentence terminator (. ! ?) possibly followed by a closing quote/bracket, then
# whitespace, then something that could start a new sentence.
_BOUNDARY = re.compile(r'([.!?]+["\')\]]?)(\s+)')


def _is_abbreviation(text: str, period_index: int) -> bool:
    """True if the period at `period_index` looks like it ends an abbreviation."""
    # Grab the word immediately before the period.
    start = period_index
    while start > 0 and (text[start - 1].isalnum() or text[start - 1] == "."):
        start -= 1
    word = text[start:period_index].lower().strip(".")
    return word in _ABBREVIATIONS


def split_sentences(text: str) -> List[Tuple[str, int, int]]:
    """Split `text` into ``(sentence, char_start, char_end)`` spans.

    Empty/whitespace input returns []. A block with no terminator is one span.
    """
    if not text or not text.strip():
        return []

    spans: List[Tuple[str, int, int]] = []
    cursor = 0  # start of the current sentence
    for match in _BOUNDARY.finditer(text):
        end = match.end(1)  # just after the terminator, before the whitespace
        # Don't split on a period that ends a known abbreviation.
        if match.group(1) == "." and _is_abbreviation(text, match.start(1)):
            continue
        chunk = text[cursor:end]
        stripped_start = cursor + (len(chunk) - len(chunk.lstrip()))
        stripped_end = end - (len(chunk) - len(chunk.rstrip()))
        if stripped_end > stripped_start:
            spans.append((text[stripped_start:stripped_end], stripped_start, stripped_end))
        cursor = match.end()  # skip the whitespace after the boundary

    # The trailing remainder (text after the last boundary, or the whole thing if
    # there were no boundaries).
    if cursor < len(text):
        chunk = text[cursor:]
        stripped_start = cursor + (len(chunk) - len(chunk.lstrip()))
        stripped_end = len(text) - (len(chunk) - len(chunk.rstrip()))
        if stripped_end > stripped_start:
            spans.append((text[stripped_start:stripped_end], stripped_start, stripped_end))

    return spans
