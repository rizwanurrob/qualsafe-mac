#!/usr/bin/env python
"""
Lexical exploration — word frequency, KWIC, and context profiles (v4, Phase 1).

Every analysis in QualSafe up to now has been *over codes*: you can ask how often
a code was applied, but not what words the corpus actually uses. That is backwards
for the first hour of a project, when the codebook does not exist yet and the
analyst is trying to find out what is in the data.

Pure functions over text — no store, no I/O, no Streamlit — so they are trivially
testable and reusable by the search page, the document reader, and exports.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import pandas as pd

# A deliberately small, general English stop list. Kept short and visible rather
# than pulling in NLTK's: an analyst can read this one and understand exactly what
# was removed from their counts, and extend it per project. Domain words ("student",
# "course") are NOT here — removing those is a project decision, not a default.
DEFAULT_STOPWORDS = frozenset("""
a about above after again against all am an and any are aren't as at be because
been before being below between both but by can cannot could couldn't did didn't
do does doesn't doing don't down during each few for from further had hadn't has
hasn't have haven't having he her here hers herself him himself his how i i'm if
in into is isn't it it's its itself just me more most my myself no nor not of off
on once only or other ought our ours ourselves out over own really same shan't she
should shouldn't so some such than that that's the their theirs them themselves
then there these they this those through to too under until up very was wasn't we
were weren't what when where which while who whom why will with won't would
wouldn't you your yours yourself yourselves
""".split())

# A "word" for counting purposes: letters/digits with internal apostrophes or
# hyphens (so "don't" and "first-year" survive as single tokens).
_TOKEN_RE = re.compile(r"[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)*")


def tokenize(text: str) -> List[Tuple[str, int, int]]:
    """Split text into ``(token_lowercased, start, end)`` with exact offsets.

    Offsets are kept because callers need to point back at the source (KWIC,
    highlighting, auto-coding) — a token list without positions cannot do that.
    """
    return [(m.group(0).lower(), m.start(), m.end()) for m in _TOKEN_RE.finditer(text or "")]


def word_frequency(
    texts: Iterable[str],
    *,
    stopwords: Optional[Iterable[str]] = None,
    min_length: int = 3,
    top_n: Optional[int] = 50,
) -> pd.DataFrame:
    """Count words across a corpus.

    Returns a DataFrame ``[term, count, documents]`` sorted by count desc then
    term asc (deterministic). ``documents`` is how many of the input texts contain
    the term at least once — the number that separates "said a lot by one person"
    from "said by everyone", which raw counts hide.

    Pass ``stopwords=[]`` to disable filtering entirely.
    """
    stops = DEFAULT_STOPWORDS if stopwords is None else frozenset(s.lower() for s in stopwords)
    counts: Counter = Counter()
    doc_counts: Counter = Counter()
    for text in texts:
        seen_here = set()
        for token, _s, _e in tokenize(text):
            if len(token) < min_length or token in stops:
                continue
            counts[token] += 1
            seen_here.add(token)
        for token in seen_here:
            doc_counts[token] += 1

    rows = [{"term": t, "count": n, "documents": doc_counts[t]} for t, n in counts.items()]
    df = pd.DataFrame(rows, columns=["term", "count", "documents"])
    if df.empty:
        return df
    df = df.sort_values(["count", "term"], ascending=[False, True], kind="stable")
    if top_n:
        df = df.head(int(top_n))
    return df.reset_index(drop=True)


def kwic_line(
    text: str, start: int, end: int, *, width: int = 60,
) -> Tuple[str, str, str]:
    """Keyword-in-context around ``text[start:end]`` → ``(left, match, right)``.

    The match is taken from the source by offset, never reconstructed, so what is
    displayed is exactly what is in the document. Ellipses mark truncation so a
    reader can tell a clipped context from a document edge.
    """
    text = text or ""
    left_start = max(0, start - width)
    right_end = min(len(text), end + width)
    left = text[left_start:start].replace("\n", " ")
    right = text[end:right_end].replace("\n", " ")
    if left_start > 0:
        left = "…" + left
    if right_end < len(text):
        right = right + "…"
    return left, text[start:end], right


def context_profile(
    contexts: Sequence[Tuple[str, str]],
    *,
    top_n: int = 10,
    stopwords: Optional[Iterable[str]] = None,
) -> Dict[str, pd.DataFrame]:
    """What words tend to sit either side of a search term.

    ``contexts`` is a sequence of ``(left_text, right_text)`` pairs — one per hit.
    Returns ``{"before": df, "after": df}``, each ``[term, count]``. This is the
    cheap, legible core of a word tree: "cost" is preceded by *tuition*, *rising*,
    *hidden* and followed by *worry*, *barrier*, *concern* — which is usually the
    insight the full branching diagram is used to find.

    Stopwords are NOT removed by default here: function words ("cost of", "worried
    about") are often exactly the pattern of interest. Pass a list to filter.
    """
    stops = frozenset() if stopwords is None else frozenset(s.lower() for s in stopwords)
    before: Counter = Counter()
    after: Counter = Counter()
    for left, right in contexts:
        left_tokens = [t for t, _s, _e in tokenize(left) if t not in stops]
        right_tokens = [t for t, _s, _e in tokenize(right) if t not in stops]
        if left_tokens:
            before[left_tokens[-1]] += 1      # the word immediately before
        if right_tokens:
            after[right_tokens[0]] += 1       # the word immediately after

    def _frame(counter: Counter) -> pd.DataFrame:
        rows = [{"term": t, "count": n} for t, n in counter.items()]
        df = pd.DataFrame(rows, columns=["term", "count"])
        if df.empty:
            return df
        return (df.sort_values(["count", "term"], ascending=[False, True], kind="stable")
                  .head(int(top_n)).reset_index(drop=True))

    return {"before": _frame(before), "after": _frame(after)}
