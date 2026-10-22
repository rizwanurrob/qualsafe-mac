#!/usr/bin/env python
"""
Template matching (v3.1, I2) — the analytical heart of interview mode.

Maps each Q/A pair onto the template themes (handoff §5.4[6]) using:
- embedding similarity of the interviewer's QUESTION vs each theme's guide
  questions, and
- embedding similarity of the RESPONSE vs the same guide questions — weighted
  equally, deliberately: interviews wander, and a response about belonging counts
  toward "belonging" even if it followed a question about something else (that's
  what makes regrouping more than a linear read), plus
- a bounded KEYWORD boost (secondary signal only — keywords can nudge a
  borderline match over the gate but can never confirm a theme alone).

A confidence gate (min_similarity) routes weak pairs to the unclassified bucket
instead of force-fitting — the same honest-uncertainty philosophy as strict
coding. Multi-theme matches are allowed (and expected) by default.

Embeddings are injected as `embed_fn(texts) -> np.ndarray` so tests run with
deterministic vectors and production reuses build_embeddings (see
default_embed_fn). LLM confirmation of matches is a later enhancement; this
module is fully deterministic.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence

import numpy as np

from interview.questions import QAPair
from interview.template import InterviewTemplate

EmbedFn = Callable[[Sequence[str]], np.ndarray]

DEFAULT_MIN_SIMILARITY = 0.45
DEFAULT_KEYWORD_BOOST = 0.05          # per distinct keyword hit
DEFAULT_MAX_KEYWORD_BOOST = 0.15      # cap — keywords stay a secondary signal


@dataclass
class ThemeMatch:
    theme_id: str
    similarity: float
    confident: bool
    source: str                        # "embedding_question" | "embedding_response" (+ "+keyword")


@dataclass
class MatchedPair:
    pair: QAPair
    matches: List[ThemeMatch] = field(default_factory=list)   # confident, similarity-desc
    scores: Dict[str, float] = field(default_factory=dict)    # every theme's final score (transparency)

    @property
    def is_unclassified(self) -> bool:
        return not self.matches


def default_embed_fn(
    model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
    batch_size: int = 32,
) -> EmbedFn:
    """Production embedder: wraps the shared build_embeddings (normalized)."""
    def _embed(texts: Sequence[str]) -> np.ndarray:
        from analyze_survey import build_embeddings  # local: keeps import light for tests
        return build_embeddings(
            texts=list(texts), model_name=model_name,
            batch_size=batch_size, normalize_embeddings=True,
        )
    return _embed


def _unit(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    return v / n if n > 0 else v


def _max_cosine(vec: Optional[np.ndarray], refs: List[np.ndarray]) -> float:
    if vec is None or not refs:
        return 0.0
    u = _unit(vec)
    return max(float(np.dot(u, _unit(r))) for r in refs)


def _keyword_hits(text: str, keywords: List[str]) -> int:
    hits = 0
    low = text.lower()
    for kw in keywords:
        kw = kw.strip().lower()
        if kw and re.search(r"\b" + re.escape(kw) + r"\b", low):
            hits += 1
    return hits


def response_text(pair: QAPair) -> str:
    """The pair's full interviewee response as one string."""
    return " ".join(t.text for t in pair.response_turns).strip()


def match_qa_pairs(
    qa_pairs: List[QAPair],
    template: InterviewTemplate,
    embed_fn: EmbedFn,
    config: Optional[Dict[str, Any]] = None,
) -> List[MatchedPair]:
    """Score every (pair, theme) and gate into confident matches.

    Config keys: min_similarity (default 0.45), allow_multi_theme (default True),
    keyword_boost / max_keyword_boost.
    """
    cfg = config or {}
    min_similarity = float(cfg.get("min_similarity", DEFAULT_MIN_SIMILARITY))
    allow_multi = bool(cfg.get("allow_multi_theme", True))
    kw_boost = float(cfg.get("keyword_boost", DEFAULT_KEYWORD_BOOST))
    kw_cap = float(cfg.get("max_keyword_boost", DEFAULT_MAX_KEYWORD_BOOST))

    if not qa_pairs:
        return []

    # Embed all guide questions once; remember each theme's row indices.
    guide_texts: List[str] = []
    guide_rows_by_theme: Dict[str, List[int]] = {}
    for theme in template.themes:
        rows = []
        for gq in theme.guide_questions:
            rows.append(len(guide_texts))
            guide_texts.append(gq)
        guide_rows_by_theme[theme.id] = rows
    guide_vecs = embed_fn(guide_texts) if guide_texts else np.zeros((0, 1))

    # Embed pair questions, and non-empty responses.
    q_texts = [p.question.text for p in qa_pairs]
    q_vecs = embed_fn(q_texts)
    r_texts = [response_text(p) for p in qa_pairs]
    nonempty_rows = [i for i, t in enumerate(r_texts) if t]
    r_vec_by_row: Dict[int, np.ndarray] = {}
    if nonempty_rows:
        r_vecs = embed_fn([r_texts[i] for i in nonempty_rows])
        r_vec_by_row = {row: r_vecs[k] for k, row in enumerate(nonempty_rows)}

    out: List[MatchedPair] = []
    for i, pair in enumerate(qa_pairs):
        candidates: List[ThemeMatch] = []
        scores: Dict[str, float] = {}
        for theme in template.themes:
            refs = [guide_vecs[r] for r in guide_rows_by_theme[theme.id]]
            q_sim = _max_cosine(q_vecs[i], refs)
            r_sim = _max_cosine(r_vec_by_row.get(i), refs)
            base, source = (q_sim, "embedding_question") if q_sim >= r_sim else (r_sim, "embedding_response")

            hits = _keyword_hits(f"{q_texts[i]} {r_texts[i]}", theme.keywords)
            boost = min(kw_cap, kw_boost * hits)
            if boost > 0:
                source += "+keyword"
            final = min(1.0, base + boost)

            scores[theme.id] = round(final, 4)
            if final >= min_similarity:
                candidates.append(ThemeMatch(
                    theme_id=theme.id, similarity=round(final, 4),
                    confident=True, source=source,
                ))

        candidates.sort(key=lambda m: -m.similarity)
        if not allow_multi and candidates:
            candidates = candidates[:1]
        out.append(MatchedPair(pair=pair, matches=candidates, scores=scores))
    return out
