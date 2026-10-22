#!/usr/bin/env python
"""
Engine abstraction for theme/sentiment coding (v3, Phase 0a).

Both coding backends implement the same contract so the survey pipeline does
not care which one runs:

- TransformerEngine (engines/transformer_engine.py) wraps the v2.1
  embeddings + zero-shot NLI + sentiment path. Default, deterministic.
- LlmEngine (engines/llm_engine.py, Phase 2) calls a local model via Ollama.

Both return a list of `ResponseCoding` — a superset of the columns the current
zero-shot path emits — which strict coding, review queues, exports, and (later)
the shared project model all consume uniformly. See V3_PLAN.md §2.7.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, Sequence, runtime_checkable


# Score semantics — the same `scores` field means different things by engine, so
# every ResponseCoding records which. Naive cross-engine comparison of raw scores
# (e.g. a shared strict threshold) is only valid within one score_kind.
SCORE_KIND_NLI_INDEPENDENT = "nli_independent"   # zero-shot multi_label=True: per-label, not a simplex
SCORE_KIND_NLI_SOFTMAX = "nli_softmax"           # zero-shot multi_label=False: softmax, sums to 1
SCORE_KIND_LLM_SELFREPORT = "llm_selfreport"     # LLM self-reported, uncalibrated


@dataclass
class ResponseCoding:
    """The per-response result produced by any ThemeEngine.

    `labels` / `scores` are aligned and ordered score-descending, exactly as the
    HF zero-shot pipeline returns them, so the existing `*_all_labels` /
    `*_all_scores` export strings can be reproduced byte-for-byte. The two lists
    are kept in lock-step; __post_init__ enforces equal length.

    Provenance (`score_kind`, `source_engine`, `model_id`) travels with the
    coding so downstream analysis and IRR never naively compare a BART
    entailment score with an LLM's self-reported confidence (V3_PLAN.md
    Decisions 1 & 2). The strict_* fields hold the shared confidence-gate
    outcome; the LLM engine fills `rationale` and may set `weight`.
    """
    labels: List[str] = field(default_factory=list)
    scores: List[float] = field(default_factory=list)

    sentiment_label: Optional[str] = None
    sentiment_score: Optional[float] = None

    weight: Optional[float] = None
    rationale: str = ""

    # Provenance of the scores (see SCORE_KIND_* constants above).
    score_kind: Optional[str] = None
    source_engine: Optional[str] = None   # "transformer" | "llm"
    model_id: Optional[str] = None        # exact model, e.g. facebook/bart-large-mnli

    # Strict-coding gate outputs (populated when a strict_coding config is given).
    strict_label: Optional[str] = None
    strict_confident: Optional[bool] = None
    strict_reason: Optional[str] = None
    strict_margin: Optional[float] = None

    def __post_init__(self) -> None:
        if len(self.labels) != len(self.scores):
            raise ValueError(
                f"ResponseCoding labels/scores length mismatch: "
                f"{len(self.labels)} labels vs {len(self.scores)} scores"
            )

    @property
    def top_label(self) -> str:
        return self.labels[0] if self.labels else ""

    @property
    def top_score(self) -> float:
        return self.scores[0] if self.scores else math.nan

    def all_labels_str(self, delimiter: str = "|") -> str:
        """Reproduce the v2.1 `*_all_labels` export field."""
        return delimiter.join(str(x) for x in self.labels)

    def all_scores_str(self, delimiter: str = "|") -> str:
        """Reproduce the v2.1 `*_all_scores` export field (4-dp formatting)."""
        return delimiter.join(f"{float(s):.4f}" for s in self.scores)


@runtime_checkable
class ThemeEngine(Protocol):
    """Contract for a coding backend.

    Given raw texts and a candidate label set, return one ResponseCoding per
    text. `config` carries engine-agnostic knobs (multi_label, batch size,
    strict_coding block, whether to run sentiment, etc.).
    """

    def code_responses(
        self,
        texts: Sequence[str],
        labels: Sequence[str],
        config: Dict[str, Any],
    ) -> List[ResponseCoding]:
        ...
