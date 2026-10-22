#!/usr/bin/env python
"""
Long-text segmentation for structured coding engines with a finite context
window (Alt Survey Flow).

A survey response is almost always well inside any model's context window and
needs no segmentation at all. An interview turn or a long open-ended answer can
exceed it, and Laya's English checkpoint budgets only 512 tokens total -- state
plus every candidate code's instructions -- with roughly 192-256 of those
reserved for the questions themselves (see docs/ALT_SURVEY_FLOW_PLAN.md, "What
Laya actually is"). Silently truncating the state is worse than segmenting it:
a code decided from the first 400 tokens of a 2,000-token answer is a decision
the engine was never actually asked to make on the material that mattered.

This module does NOT call a tokenizer. QualSafe's whole coding stack (transformer
engine, LLM engine) already estimates length in *characters* rather than adding a
tokenizer dependency for a rough budget, and Laya is isolated in its own process
(engines/laya_engine.py) specifically so the base app never needs its tokenizer
either. `chars_per_token` is a conservative, overridable constant; a caller who
has the real tokenizer (inside the isolated Laya process) can pass an exact
budget in characters instead.

**Offset guarantee, same invariant as everywhere else in this codebase.** Every
returned segment satisfies ``text[start:end] == segment`` exactly, built by
grouping `core.text_units.split_sentences` spans rather than re-splitting text --
so a code assigned to segment 3 still traces back to the exact source characters
(the interview quote-verifier and the survey excerpt model both depend on this
same guarantee holding).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

from core.text_units import split_sentences

#: English text averages under 4.5 characters per token (word plus space) for
#: GPT/BERT-family tokenizers; 4 is a deliberately conservative (i.e. an
#: UNDER-estimate of tokens per char, so this OVER-estimates token count and
#: segments a bit early rather than a bit late) round number chosen without
#: measuring Laya's actual tokenizer, which is not available outside its
#: isolated process. Revisit once engines/laya_engine.py's real client can
#: report token counts back (see its module docstring, "Open questions").
DEFAULT_CHARS_PER_TOKEN = 4


@dataclass
class Segment:
    """One chunk of a longer text, with the offsets that tie it back to the
    original. `index`/`total` let a UI show "segment 2 of 5" and let a
    resumed/cancelled run know which segments are already done."""
    text: str
    char_start: int
    char_end: int
    index: int
    total: int


def needs_segmentation(text: str, *, token_budget: int,
                       chars_per_token: int = DEFAULT_CHARS_PER_TOKEN) -> bool:
    """True if `text` is estimated to exceed `token_budget`. Cheap pre-check so
    the common case (a survey response) skips segmentation entirely."""
    return len(text) > token_budget * chars_per_token


def segment_for_coding(
    text: str, *, token_budget: int, chars_per_token: int = DEFAULT_CHARS_PER_TOKEN,
    overlap_sentences: int = 1,
) -> List[Segment]:
    """Split `text` into offset-exact chunks that each fit `token_budget`.

    Groups whole sentences (never splits mid-sentence, since a code decision
    made on half a sentence is not a decision made on the text) up to the
    character budget implied by `token_budget * chars_per_token`. A single
    sentence longer than the whole budget is kept whole anyway and returned as
    its own oversized segment -- truncating a codeable unit invents a boundary
    the source doesn't have, which this codebase's offset guarantee forbids
    everywhere else, so an oversized final segment must be handled by the
    caller (e.g. flag for manual review) rather than silently cut here.

    `overlap_sentences` repeats the last N sentences of each segment at the
    start of the next one, so a theme stated right at a chunk boundary isn't
    invisible to whichever segment "owns" the sentence before or after it. Set
    to 0 for no overlap. Overlapping text is coded in both segments; a caller
    that de-duplicates candidate codes across segments (engines/laya_engine.py
    does, by (code_id, excerpt) — an overlapping sentence becomes two
    excerpts, not one code applied twice to the same excerpt) will not double
    an application.

    Returns a single whole-text Segment (index=0, total=1) when no
    segmentation is needed, so callers can always iterate the result the same
    way regardless of length.
    """
    budget_chars = token_budget * chars_per_token
    if not needs_segmentation(text, token_budget=token_budget, chars_per_token=chars_per_token):
        return [Segment(text=text, char_start=0, char_end=len(text), index=0, total=1)]

    sentences = split_sentences(text)
    if not sentences:
        # No detectable sentence boundary in an over-budget text (e.g. one huge
        # run-on). Return it whole; the caller's oversized-segment handling
        # applies exactly as it would to one long sentence.
        return [Segment(text=text, char_start=0, char_end=len(text), index=0, total=1)]

    chunks: List[List[tuple]] = [[]]
    length = 0
    for sentence, start, end in sentences:
        span_len = end - start
        if chunks[-1] and length + span_len > budget_chars:
            chunks.append([])
            length = 0
            if overlap_sentences > 0:
                carry = chunks[-2][-overlap_sentences:]
                chunks[-1].extend(carry)
                length = sum(e - s for _, s, e in carry)
        chunks[-1].append((sentence, start, end))
        length += span_len

    segments: List[Segment] = []
    total = len(chunks)
    for index, group in enumerate(chunks):
        seg_start = group[0][1]
        seg_end = group[-1][2]
        segments.append(Segment(
            text=text[seg_start:seg_end], char_start=seg_start, char_end=seg_end,
            index=index, total=total,
        ))
    return segments
