#!/usr/bin/env python
"""
Hardened quote verification (v3.1, I3) — the anti-hallucination gate.

Interview mode surfaces verbatim quotes as evidence, and LLMs both hallucinate
quotes and *lightly rewrite* real ones (straightening curly apostrophes, changing
dashes, collapsing whitespace, shifting case). Naive equality would reject those
legitimate quotes and silently skew which themes look well-supported — the
Phase 0a review flagged exactly this. This module locates an LLM-proposed quote
in the source transcript through three tiers:

  1. exact       — plain substring.
  2. normalized  — match after NFKC + curly-quote/dash folding + casefold +
                   whitespace collapse, with an index map so offsets are
                   recovered in the ORIGINAL text.
  3. fuzzy       — bounded sliding-window SequenceMatcher (default ratio >= 0.90)
                   over the normalized text, for one-word slips.

Whatever the tier, the returned quote text is ALWAYS the source's own characters
(`text == source[char_start:char_end]`), never the model's version — a fuzzy
match surfaces the source's words, not a paraphrase. Quotes that fail all tiers
are dropped and counted: the hallucination rate is itself a trust statistic worth
reporting alongside the kappa.
"""

from __future__ import annotations

import logging
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import List, Optional, Sequence, Tuple

LOGGER = logging.getLogger("survey_nlp")

DEFAULT_MIN_FUZZY_RATIO = 0.90

# Character folds an LLM commonly applies when echoing text back.
_FOLD = {
    "‘": "'", "’": "'", "‚": "'", "′": "'",   # curly/prime apostrophes
    "“": '"', "”": '"', "„": '"', "″": '"',   # curly double quotes
    "–": "-", "—": "-", "−": "-", "‐": "-",   # en/em dash, minus, hyphen
    "…": "...",                                              # ellipsis
}


@dataclass
class LocatedQuote:
    text: str            # verbatim from SOURCE: == source[char_start:char_end]
    char_start: int
    char_end: int
    match_kind: str      # "exact" | "normalized" | "fuzzy"
    similarity: float    # 1.0 unless fuzzy


@dataclass
class QuoteVerification:
    located: List[LocatedQuote] = field(default_factory=list)
    dropped: List[str] = field(default_factory=list)

    @property
    def n_proposed(self) -> int:
        return len(self.located) + len(self.dropped)

    @property
    def hallucination_rate(self) -> float:
        return len(self.dropped) / self.n_proposed if self.n_proposed else 0.0


def normalize_with_map(text: str) -> Tuple[str, List[int]]:
    """Normalized text + an index map (normalized pos -> original pos).

    Normalization: NFKC, quote/dash folding, casefold, whitespace runs -> one
    space, stripped. The map lets a match in normalized space recover offsets in
    the original text.
    """
    chars: List[str] = []
    imap: List[int] = []
    for i, ch in enumerate(text):
        for nk in unicodedata.normalize("NFKC", ch):
            for cc in _FOLD.get(nk, nk):
                cc = cc.lower()
                if cc.isspace():
                    if chars and chars[-1] == " ":
                        continue
                    chars.append(" ")
                    imap.append(i)
                else:
                    chars.append(cc)
                    imap.append(i)
    while chars and chars[0] == " ":
        chars.pop(0)
        imap.pop(0)
    while chars and chars[-1] == " ":
        chars.pop()
        imap.pop()
    return "".join(chars), imap


def _fuzzy_find(norm_source: str, norm_quote: str, min_ratio: float) -> Optional[Tuple[float, int]]:
    """Best (ratio, start) of a quote-sized window in the normalized source."""
    n, m = len(norm_source), len(norm_quote)
    if m == 0 or n == 0:
        return None
    if n <= m:
        ratio = SequenceMatcher(None, norm_source, norm_quote).ratio()
        return (ratio, 0) if ratio >= min_ratio else None

    step = max(1, m // 4)
    best_ratio, best_start = 0.0, -1
    for s in range(0, n - m + 1, step):                       # coarse scan
        ratio = SequenceMatcher(None, norm_source[s:s + m], norm_quote).ratio()
        if ratio > best_ratio:
            best_ratio, best_start = ratio, s
    if best_start < 0:
        return None
    lo, hi = max(0, best_start - step), min(n - m, best_start + step)
    for s in range(lo, hi + 1):                               # fine scan around best
        ratio = SequenceMatcher(None, norm_source[s:s + m], norm_quote).ratio()
        if ratio > best_ratio:
            best_ratio, best_start = ratio, s
    return (best_ratio, best_start) if best_ratio >= min_ratio else None


def locate_quote(
    quote: str,
    source: str,
    *,
    min_fuzzy_ratio: float = DEFAULT_MIN_FUZZY_RATIO,
    allow_fuzzy: bool = True,
) -> Optional[LocatedQuote]:
    """Locate an LLM-proposed quote in the source; None if unverifiable."""
    quote = (quote or "").strip()
    if not quote or not source:
        return None

    # Tier 1: exact substring.
    pos = source.find(quote)
    if pos >= 0:
        return LocatedQuote(text=quote, char_start=pos, char_end=pos + len(quote),
                            match_kind="exact", similarity=1.0)

    norm_source, imap = normalize_with_map(source)
    norm_quote, _ = normalize_with_map(quote)
    if not norm_quote or not imap:
        return None

    # Tier 2: exact in normalized space -> original offsets via the map.
    p = norm_source.find(norm_quote)
    if p >= 0:
        s0 = imap[p]
        e0 = imap[p + len(norm_quote) - 1] + 1
        return LocatedQuote(text=source[s0:e0], char_start=s0, char_end=e0,
                            match_kind="normalized", similarity=1.0)

    # Tier 3: bounded fuzzy.
    if allow_fuzzy:
        hit = _fuzzy_find(norm_source, norm_quote, min_fuzzy_ratio)
        if hit is not None:
            ratio, start = hit
            end_n = min(start + len(norm_quote), len(imap))
            s0 = imap[start]
            e0 = imap[end_n - 1] + 1
            return LocatedQuote(text=source[s0:e0], char_start=s0, char_end=e0,
                                match_kind="fuzzy", similarity=round(ratio, 4))
    return None


def verify_quotes(
    quotes: Sequence[str],
    source: str,
    *,
    min_fuzzy_ratio: float = DEFAULT_MIN_FUZZY_RATIO,
    allow_fuzzy: bool = True,
) -> QuoteVerification:
    """Locate every proposed quote; drop (and log) what can't be verified."""
    result = QuoteVerification()
    for q in quotes:
        located = locate_quote(q, source, min_fuzzy_ratio=min_fuzzy_ratio,
                               allow_fuzzy=allow_fuzzy)
        if located is not None:
            result.located.append(located)
        else:
            result.dropped.append(q)
            LOGGER.warning("Dropped unverifiable LLM quote (not found in source): %.80r", q)
    return result
