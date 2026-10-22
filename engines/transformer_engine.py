#!/usr/bin/env python
"""
Transformer coding engine (v3, Phase 0a).

This is a *faithful wrapper* around the v2.1 coding path: it delegates to the
exact functions in analyze_survey (run_zero_shot, run_sentiment,
assign_strict_labels_from_results) so its results are identical to the
pre-abstraction pipeline. No model behavior changes here — this only re-homes
the existing calls behind the ThemeEngine contract so the survey pipeline can
be routed through an engine (and, later, swapped for the LLM engine).

Because it delegates to analyze_survey, tests mock `analyze_survey.pipeline`
exactly as the existing smoke test does — no model download, fully offline.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence

import analyze_survey  # for analyze_survey.pipeline (single mock point in tests)
from analyze_survey import (
    assign_strict_labels_from_results,
    run_sentiment,
    run_zero_shot_with_pipeline,
)
from engines.base import (
    ResponseCoding,
    SCORE_KIND_NLI_INDEPENDENT,
    SCORE_KIND_NLI_SOFTMAX,
)


class TransformerEngine:
    """Wraps zero-shot NLI + sentiment + the strict-coding gate.

    Parameters
    ----------
    zero_shot_model : str
        HF model id for zero-shot classification (e.g. facebook/bart-large-mnli).
    sentiment_model : str, optional
        HF model id for sentiment. Only used when config requests sentiment.
    """

    def __init__(self, zero_shot_model: str, sentiment_model: Optional[str] = None):
        self.zero_shot_model = zero_shot_model
        self.sentiment_model = sentiment_model
        self._zsc = None  # lazily built HF zero-shot pipeline, reused across calls

    def _get_zsc(self):
        """Build the zero-shot pipeline once and reuse it.

        v2.1's per-question path loaded the model once and looped; rebuilding it
        per call (as `run_zero_shot` does) would reload the model N times when the
        engine is used per-question. Caching here avoids that regression.

        Resolved through `analyze_survey._get_pipeline()` rather than reading
        `analyze_survey.pipeline` directly: the module-level name is a lazy-import
        sentinel that starts as None. The resolver returns whatever that attribute
        currently holds, so patching `analyze_survey.pipeline` remains the single
        mock point for tests.
        """
        if self._zsc is None:
            self._zsc = analyze_survey._load_model(
                self.zero_shot_model,
                lambda: analyze_survey._get_pipeline()(
                    "zero-shot-classification",
                    model=self.zero_shot_model,
                    truncation=True,
                ),
            )
        return self._zsc

    def code_responses(
        self,
        texts: Sequence[str],
        labels: Sequence[str],
        config: Dict[str, Any],
    ) -> List[ResponseCoding]:
        """Code `texts` against `labels`, returning one ResponseCoding each.

        Recognized config keys:
        - multi_label (bool, default True)
        - inference_batch_size (int, default 16)
        - strict_coding (dict): if present and enabled, applies the shared gate.
        - run_sentiment (bool, default False): if True and a sentiment_model was
          provided, also populates sentiment_label / sentiment_score.
        - inference_cache: a core.inference_cache.InferenceCache, or None. When
          present, responses already scored by this model are served from it and
          only the outstanding (response, label) pairs reach the model.
        """
        texts = list(texts)
        labels = list(labels)
        multi_label = bool(config.get("multi_label", True))
        batch_size = int(config.get("inference_batch_size", 16))
        strict_cfg = config.get("strict_coding") or {}
        run_sentiment_flag = bool(config.get("run_sentiment", False))

        # Themes — same computation as v2.1's run_zero_shot, but on a reused
        # pipeline (run_zero_shot == build pipeline + run_zero_shot_with_pipeline).
        if not labels:
            raise ValueError("candidate label list is empty")
        z_results = run_zero_shot_with_pipeline(
            # The builder, not the built thing. A run whose responses are all
            # cached has no work for the NLI model and should not spend 25
            # seconds loading 1.6 GB to discover that.
            zsc=None,
            zsc_builder=self._get_zsc,
            model_id=self.zero_shot_model,
            texts=texts,
            labels=labels,
            multi_label=multi_label,
            batch_size=batch_size,
            # Per-response progress for the GUI. None in CLI/tests, which keeps the
            # single-call path the byte-identity harness pins.
            progress=config.get("progress_callback"),
            # None in tests and whenever the run disables it, which keeps that
            # same byte-identity path intact.
            cache=config.get("inference_cache"),
            # Announced, not silent: an analyst who left a long run unattended
            # should be told what was reused rather than inferring it from a
            # suspiciously short wait.
            resume_callback=config.get("resume_callback"),
        )

        # Strict-coding gate (shared with the LLM engine in Phase 2).
        strict_rows = None
        if strict_cfg.get("enabled", False):
            s_labels, s_conf, s_reason, s_margin = assign_strict_labels_from_results(
                results=z_results,
                strict_cfg=strict_cfg,
            )
            strict_rows = list(zip(s_labels, s_conf, s_reason, s_margin))

        # Optional sentiment — same call/values as run_pipeline's sentiment block.
        sentiments = None
        if run_sentiment_flag and self.sentiment_model:
            sentiments = run_sentiment(
                texts=texts,
                model_name=self.sentiment_model,
                batch_size=batch_size,
                cache=config.get("inference_cache"),
            )

        # Score semantics depend on multi_label: independent per-label entailment
        # probabilities vs. a softmax over labels. Recorded so downstream never
        # compares these against LLM self-reported scores naively.
        score_kind = SCORE_KIND_NLI_INDEPENDENT if multi_label else SCORE_KIND_NLI_SOFTMAX

        codings: List[ResponseCoding] = []
        for i, item in enumerate(z_results):
            item_labels = [str(x) for x in item.get("labels", [])]
            item_scores = [float(x) for x in item.get("scores", [])]
            coding = ResponseCoding(
                labels=item_labels,
                scores=item_scores,
                score_kind=score_kind,
                source_engine="transformer",
                model_id=self.zero_shot_model,
            )

            if strict_rows is not None:
                sl, sc, sr, sm = strict_rows[i]
                coding.strict_label = sl
                coding.strict_confident = sc
                coding.strict_reason = sr
                coding.strict_margin = sm

            if sentiments is not None:
                coding.sentiment_label = sentiments[i].get("label")
                coding.sentiment_score = float(sentiments[i].get("score", math.nan))

            codings.append(coding)

        return codings
