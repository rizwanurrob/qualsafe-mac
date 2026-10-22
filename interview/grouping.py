#!/usr/bin/env python
"""
Regrouping by theme + coverage + off-template (v3.1, I2). Handoff stage [7].

Inverts the transcript: for each template theme, gather every matched Q/A pair —
no matter where in the interview it appeared. This is the deliverable a linear
read can't produce. Also surfaces:

- OFF-TEMPLATE material: pairs that matched no theme (often the most interesting
  findings — never silently dropped), and
- TEMPLATE COVERAGE: which guide questions were actually addressed and which were
  skipped, so the analyst can see the guide's blind spots for this interview.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple

import numpy as np

from interview.matching import EmbedFn, MatchedPair, _max_cosine
from interview.questions import QAPair
from interview.template import InterviewTemplate

DEFAULT_COVERAGE_MIN_SIMILARITY = 0.45


@dataclass
class ThemeGroup:
    theme_id: str
    label: str
    items: List[MatchedPair] = field(default_factory=list)   # transcript order

    def similarity_for(self, item: MatchedPair) -> float:
        return item.scores.get(self.theme_id, 0.0)


def group_by_theme(
    matched: List[MatchedPair],
    template: InterviewTemplate,
) -> Tuple[List[ThemeGroup], List[MatchedPair]]:
    """Regroup matched pairs under each template theme (template order); return
    (groups, off_template). A multi-theme pair appears in every theme it matched."""
    groups: List[ThemeGroup] = []
    for theme in template.themes:
        items = [m for m in matched if any(t.theme_id == theme.id for t in m.matches)]
        items.sort(key=lambda m: m.pair.question.turn_index)
        groups.append(ThemeGroup(theme_id=theme.id, label=theme.label, items=items))
    off_template = [m for m in matched if m.is_unclassified]
    return groups, off_template


def guide_question_coverage(
    qa_pairs: List[QAPair],
    template: InterviewTemplate,
    embed_fn: EmbedFn,
    min_similarity: float = DEFAULT_COVERAGE_MIN_SIMILARITY,
) -> List[Dict[str, Any]]:
    """Per guide question: was it addressed in this interview?

    A guide question counts as addressed when some asked question reaches
    `min_similarity` cosine against it. Returns one row per guide question:
    {theme_id, guide_question, best_similarity, addressed}.
    """
    asked = [p.question.text for p in qa_pairs]
    asked_vecs = embed_fn(asked) if asked else np.zeros((0, 1))
    asked_refs = [asked_vecs[i] for i in range(len(asked))]

    rows: List[Dict[str, Any]] = []
    for theme in template.themes:
        if not theme.guide_questions:
            continue
        gq_vecs = embed_fn(theme.guide_questions)
        for j, gq in enumerate(theme.guide_questions):
            best = _max_cosine(gq_vecs[j], asked_refs) if asked_refs else 0.0
            rows.append({
                "theme_id": theme.id,
                "guide_question": gq,
                "best_similarity": round(best, 4),
                "addressed": best >= min_similarity,
            })
    return rows
