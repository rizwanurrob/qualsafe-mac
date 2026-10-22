"""
Survey-specific parsing: ordered scales and top/bottom boxes, select-all-that-apply
cells, and free text. No chart is drawn here and no chart type is known.

Three ideas that decide the design
----------------------------------
**Splitting on a delimiter is not safe.** "Relationships with friends, family,
partners, or roommates" is *one* choice that contains three commas. A plain split
turns it into four fake choices, each with its own bar and a percentage that
means nothing, and the chart looks perfectly plausible. So there are two modes.
*Simple* splits and says nothing is protected. *Known-category* matching takes
the real list of choices and reads each cell left to right, longest choice
first, accepting a choice only when it ends at the delimiter or the end of the
cell. Whatever it cannot match is **counted and reported**, never quietly
dropped and never quietly split.

**Suggestions, never assumptions.** `suggest_choices` proposes the choice list
from the data, including choices that look as if a delimiter cut them in pieces
(pieces that always appear together, in order). The analyst confirms; nothing is
merged on the program's say-so.

**Off-scale answers are not scale points.** "No opinion", "Don't know" and "Not
applicable" sit outside an ordered scale, so a top box is taken from the *scale*
categories only, and whether they stay in the box's valid N is a stated choice.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from core.chartbuilder import clean, labels
from core.chartbuilder.aggregate import CANONICAL_COLUMNS, ChartData
from core.chartbuilder.config import ChartConfig, MultiSelect
from core.chartbuilder.themes import _OFF_SCALE, detect_scale

_WS = re.compile(r"\s+")

# ── ordered scales ────────────────────────────────────────────────────────────

#: Lowest to highest. A label matches a key when it equals it or starts with it
#: as whole words ("Very important" matches "very"); longest key first, so
#: "strongly disagree" is not read as "disagree".
SCALE_ORDERS: Dict[str, List[str]] = {
    "agreement": ["strongly disagree", "disagree", "somewhat disagree",
                  "neither agree nor disagree", "neutral", "somewhat agree",
                  "agree", "strongly agree"],
    "importance": ["not at all", "not important", "slightly", "somewhat",
                   "moderately", "important", "very", "extremely"],
    "satisfaction": ["very dissatisfied", "dissatisfied", "somewhat dissatisfied",
                     "neither satisfied nor dissatisfied", "neutral",
                     "somewhat satisfied", "satisfied", "very satisfied"],
    "frequency": ["never", "rarely", "seldom", "sometimes", "occasionally",
                  "often", "frequently", "always"],
}


def _norm(label: str) -> str:
    return _WS.sub(" ", label.strip().lower())


def is_off_scale(label: str) -> bool:
    return _norm(label) in _OFF_SCALE


def scale_rank(label: str, scale: str) -> Optional[int]:
    """Position of `label` on the named scale, or None if it is not on it."""
    low = _norm(label)
    order = SCALE_ORDERS[scale]
    for key in sorted(order, key=len, reverse=True):
        if low == key or re.match(rf"^{re.escape(key)}\b", low):
            return order.index(key)
    return None


def order_by_scale(categories: Sequence[str], scale: Optional[str] = None
                   ) -> Tuple[List[str], Optional[str]]:
    """`categories` in scale order, and the scale used (None when unrecognised).

    Recognised points first by rank, then anything else in the order given, then
    the off-scale answers last. With no recognisable scale the input order is
    returned unchanged: guessing an order would be worse than keeping the data's.
    """
    scale = scale or detect_scale(list(categories))
    if scale not in SCALE_ORDERS:
        return list(categories), None
    ranked, other, off = [], [], []
    for cat in categories:
        if is_off_scale(cat):
            off.append(cat)
            continue
        rank = scale_rank(cat, scale)
        (ranked if rank is not None else other).append((rank, cat))
    ranked.sort(key=lambda item: item[0])
    return [c for _, c in ranked] + [c for _, c in other] + off, scale


def scale_categories(categories: Sequence[str], missing_label: str = "") -> List[str]:
    """The categories that are points on the scale (no off-scale, no blanks)."""
    return [c for c in categories if not is_off_scale(c) and c != missing_label]


def box_summary(data: ChartData, cfg: ChartConfig) -> pd.DataFrame:
    """Top/bottom-box percentages per item, from the canonical table.

    Computed *from* the canonical table (counts already recoded and ordered) so a
    box can never disagree with the bars it summarises. Columns: Item, Box,
    Categories, Count, Valid N, Percent, Label. `Count` is the number in the box,
    `Valid N` the base, and `Label` reads "93% (519/558)".
    """
    boxes = cfg.boxes
    scale = scale_categories(data.categories, cfg.recode.missing_label)
    off = [c for c in data.categories if is_off_scale(c)]
    t = data.table
    defs: List[Tuple[str, List[str]]] = []
    for n in boxes.top:
        if 0 < n < len(scale):
            defs.append((f"Top {n} box" if n == 1 else f"Top {n} boxes", scale[-n:]))
    for n in boxes.bottom:
        if 0 < n < len(scale):
            defs.append((f"Bottom {n} box" if n == 1 else f"Bottom {n} boxes", scale[:n]))
    for merge in boxes.custom:
        members = [m for m in merge.members if m in data.categories]
        if members:
            defs.append((merge.label, members))
    rows = []
    for item in (data.groups or [""]):
        block = t[t["group"] == item]
        if block.empty:
            continue
        base = int(block["valid_n"].iloc[0])
        if boxes.exclude_off_scale:
            base -= int(block[block["category"].isin(off)]["count"].sum())
        for name, members in defs:
            count = int(block[block["category"].isin(members)]["count"].sum())
            pct = 100.0 * count / base if base else float("nan")
            rows.append({"Item": item or cfg.column, "Box": name,
                         "Categories": " + ".join(members), "Count": count,
                         "Valid N": base, "Percent": round(pct, 1),
                         "Label": labels.display_label(
                             count, base, pct, decimals=cfg.display.decimals)})
    return pd.DataFrame(rows, columns=["Item", "Box", "Categories", "Count",
                                       "Valid N", "Percent", "Label"])


# ── select-all-that-apply ─────────────────────────────────────────────────────

def split_simple(cell: str, delim: str) -> List[str]:
    """Split on the delimiter and trim. Protects nothing; see `match_known`."""
    if not delim:
        return [cell.strip()] if cell.strip() else []
    return [p.strip() for p in cell.split(delim) if p.strip()]


def _collapse(text: str) -> str:
    return _WS.sub(" ", text.strip())


def match_known(cell: str, choices: Sequence[str], delim: str
                ) -> Tuple[List[str], List[str]]:
    """(matched canonical choices, unmatched pieces) for one cell.

    A choice matches only as a *complete phrase*: it must begin at the start of
    the cell or right after a delimiter, and end at the delimiter or the end of
    the cell. Longest choices are tried first so "Other, please specify" is not
    eaten by "Other". Matching ignores case and runs of whitespace; the result
    is the canonical spelling from `choices`. The order of the cell is kept and
    repeats are dropped (a respondent selects an option once).
    """
    canon = [(_collapse(c), c) for c in choices if _collapse(c)]
    canon.sort(key=lambda pair: len(pair[0]), reverse=True)
    if not delim.strip():
        # Newline (or space) delimiters: the cell is already a list of lines.
        found, extra = [], []
        lookup = {c.lower(): orig for c, orig in canon}
        for piece in split_simple(cell, delim):
            hit = lookup.get(_collapse(piece).lower())
            (found if hit else extra).append(hit or piece)
        return list(dict.fromkeys(found)), extra

    text = _collapse(cell)
    lowered = text.lower()
    fold = len(lowered) == len(text)         # exotic case folding: compare exactly
    hay = lowered if fold else text
    d = delim.strip()
    n, i = len(text), 0
    found: List[str] = []
    extra: List[str] = []
    while i < n:
        while i < n and (text[i].isspace() or text.startswith(d, i)):
            i += len(d) if text.startswith(d, i) else 1
        if i >= n:
            break
        for key, original in canon:
            needle = key.lower() if fold else key
            if hay.startswith(needle, i):
                k = i + len(needle)
                while k < n and text[k].isspace():
                    k += 1
                if k >= n or text.startswith(d, k):
                    found.append(original)
                    i = k
                    break
        else:
            j = text.find(d, i)
            j = n if j < 0 else j
            piece = text[i:j].strip()
            if piece:
                extra.append(piece)
            i = j
    return list(dict.fromkeys(found)), extra


@dataclass
class ParsedMulti:
    #: One entry per input cell: the choices selected, or None for a blank cell.
    choices: List[Optional[List[str]]]
    #: Pieces that were not on the known list, with how many cells had them.
    unmatched: Counter = field(default_factory=Counter)

    @property
    def n_valid(self) -> int:
        return sum(1 for c in self.choices if c is not None)


def parse_multi(cleaned: pd.Series, multi: MultiSelect) -> ParsedMulti:
    """Turn a cleaned column (NaN for blanks) into per-cell choice lists."""
    delim = multi.delimiter_char()
    out: List[Optional[List[str]]] = []
    unmatched: Counter = Counter()
    for cell in cleaned:
        if not isinstance(cell, str):
            out.append(None)
            continue
        if multi.mode == "simple":
            picked = list(dict.fromkeys(split_simple(cell, delim)))
            out.append(picked)
            continue
        matched, extra = match_known(cell, multi.choices, delim)
        for piece in dict.fromkeys(extra):
            unmatched[piece] += 1
        out.append(list(dict.fromkeys(matched + extra)) if multi.include_unmatched
                   else matched)
    return ParsedMulti(out, unmatched)


@dataclass
class Suggestion:
    choice: str
    count: int                                   # cells containing it
    fragments: List[str] = field(default_factory=list)   # pieces it re-joins


def suggest_choices(cleaned: pd.Series, delim: str = ",",
                    min_count: int = 2) -> List[Suggestion]:
    """A proposed choice list, re-joining pieces a delimiter appears to have cut.

    Two neighbouring pieces are *locked* when nearly every time either appears it
    is next to the other, in the same order, in at least ``min_count`` cells: the
    signature of one choice that contains the delimiter. Chains of locked pieces
    are re-joined using the text as it was written. Choices that merely always
    co-occur will be merged too, which is why this is a suggestion the analyst
    confirms and not something applied on their behalf.
    """
    cells = [c for c in cleaned if isinstance(c, str)]
    pieces_per_cell = [split_simple(c, delim) for c in cells]
    single, pair = Counter(), Counter()
    for pieces in pieces_per_cell:
        for p in set(pieces):
            single[p] += 1
        for a, b in zip(pieces, pieces[1:]):
            pair[(a, b)] += 1

    def locked(a: str, b: str) -> bool:
        both = pair[(a, b)]
        return (both >= min_count and both >= 0.9 * single[a]
                and both >= 0.9 * single[b])

    joined_next: Dict[str, str] = {}
    has_prev = set()
    for (a, b) in list(pair):
        if locked(a, b) and a not in joined_next and b not in has_prev:
            joined_next[a] = b
            has_prev.add(b)

    out: List[Suggestion] = []
    seen = set()
    for piece, count in single.most_common():
        if piece in seen or piece in has_prev:
            continue
        chain = [piece]
        while chain[-1] in joined_next:
            chain.append(joined_next[chain[-1]])
        seen.update(chain)
        if len(chain) == 1:
            out.append(Suggestion(piece, count))
            continue
        pattern = re.compile(
            (r"\s*" + re.escape(delim.strip() or delim) + r"\s*").join(
                re.escape(p) for p in chain))
        text = next((m.group(0) for c in cells if (m := pattern.search(c))),
                    (delim + " ").join(chain))
        out.append(Suggestion(text, single[chain[0]], fragments=chain))
    return out


def ambiguity_warnings(cleaned: pd.Series, multi: MultiSelect) -> List[str]:
    """Sentences about parsing that looks unsafe. Empty when it looks fine."""
    warnings: List[str] = []
    delim = multi.delimiter_char()
    if multi.mode == "simple":
        joined = [s for s in suggest_choices(cleaned, delim) if s.fragments]
        if joined:
            example = joined[0]
            warnings.append(
                f"{len(joined)} choice(s) look as if the delimiter cut them into "
                f"pieces, for example '{example.choice}' (read as "
                f"{len(example.fragments)} separate answers here). Use "
                "known-category matching so each stays one choice.")
    return warnings


# ── free text ─────────────────────────────────────────────────────────────────

STOPWORDS = frozenset("""
a about above after again all also am an and any are as at be because been before
being below between both but by can could did do does doing down during each few
for from further get got had has have having he her here hers him his how i if in
into is it its just like me more most my no nor not of off on once one only or
other our out over own really same she should so some such than that the their
them then there these they this those through to too under until up us very was
we were what when where which while who whom why will with would you your yours
""".split())

_WORD = re.compile(r"[a-z][a-z'’-]*[a-z]|[a-z]")


@dataclass
class TextSummary:
    n_rows: int
    n_responses: int
    n_missing: int
    mean_words: float
    median_words: float
    keywords: pd.DataFrame        # word, mentions, responses, percent


def _tokens(text: str, min_len: int, stop: frozenset) -> List[str]:
    words = []
    for w in _WORD.findall(text.lower()):
        w = re.sub(r"['’]s$", "", w).strip("'’-")
        if len(w) >= min_len and w not in stop:
            words.append(w)
    return words


def text_summary(series: pd.Series, *, missing_tokens: Optional[Iterable[str]] = None,
                 top: int = 25, min_len: int = 3,
                 extra_stopwords: Iterable[str] = ()) -> TextSummary:
    """Response count and a plain keyword frequency table for a text field.

    Deliberately basic: no stemming, no sentiment, no themes. It answers "what
    words come up, and in how many responses", which is what a first look at an
    open-ended question needs; theme coding is what the rest of the program is for.
    """
    stop = STOPWORDS | {w.lower() for w in extra_stopwords}
    cleaned = clean.normalize_series(series, missing_tokens=missing_tokens)
    texts = [t for t in cleaned if isinstance(t, str)]
    mentions, responses = Counter(), Counter()
    lengths = []
    for text in texts:
        words = _tokens(text, min_len, stop)
        lengths.append(len(text.split()))
        mentions.update(words)
        responses.update(set(words))
    n = len(texts)
    rows = [(w, mentions[w], responses[w], 100.0 * responses[w] / n if n else 0.0)
            for w, _ in sorted(responses.items(), key=lambda kv: (-kv[1], kv[0]))[:top]]
    return TextSummary(
        n_rows=int(len(series)), n_responses=n, n_missing=int(len(series)) - n,
        mean_words=float(np.mean(lengths)) if lengths else 0.0,
        median_words=float(np.median(lengths)) if lengths else 0.0,
        keywords=pd.DataFrame(rows, columns=["word", "mentions", "responses", "percent"]))


def keyword_chart_data(summary: TextSummary, cfg: ChartConfig) -> ChartData:
    """The keyword table as a canonical chart table (one bar per word)."""
    kw = summary.keywords
    d = cfg.display
    table = pd.DataFrame({
        "category": kw["word"], "group": "", "count": kw["responses"],
        "denominator": float(summary.n_responses), "percent": kw["percent"],
        "value": kw["percent"] if cfg.aggregation == "percent" else kw["responses"].astype(float),
        "valid_n": summary.n_responses, "missing_n": summary.n_missing,
        "sort_order": range(len(kw)), "color": ""})
    lead = "count" if cfg.aggregation == "count" else "percent"
    table["display_label"] = [
        labels.display_label(c, den, p, show_percent=d.show_percent,
                             show_count=d.show_count, show_valid_n=d.show_valid_n,
                             decimals=d.decimals, thousands=d.thousands_separator,
                             lead=lead)
        for c, den, p in zip(table["count"], table["denominator"], table["percent"])]
    return ChartData(
        table=table[CANONICAL_COLUMNS], categories=list(kw["word"]), groups=[],
        group_fields=[], valid_n=summary.n_responses, missing_n=summary.n_missing,
        n_rows=summary.n_rows, is_percent=cfg.aggregation == "percent",
        value_title=("Percent of responses mentioning the word"
                     if cfg.aggregation == "percent" else "Responses mentioning the word"),
        base_note=(f"Keywords from {summary.n_responses:,} responses; common "
                   "words removed. A word is counted once per response."))


def responses_frame(frame: pd.DataFrame, column: str, id_column: str = "",
                    missing_tokens: Optional[Iterable[str]] = None) -> pd.DataFrame:
    """The non-blank responses (with their row number, or an id) for export."""
    cleaned = clean.normalize_series(frame[column], missing_tokens=missing_tokens)
    keep = cleaned.notna()
    out = pd.DataFrame({"Response": cleaned[keep].values})
    if id_column and id_column in frame.columns:
        out.insert(0, id_column, frame.loc[keep.values, id_column].astype(str).values)
    else:
        out.insert(0, "Row", (np.flatnonzero(keep.values) + 2))   # +2: header, 1-based
    return out
