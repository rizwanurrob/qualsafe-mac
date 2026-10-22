#!/usr/bin/env python
"""
Local-LLM coding engine (v3, Phase 2).

`LlmEngine` implements the same `ThemeEngine` contract as `TransformerEngine`, but
codes each response by prompting a small instruction-tuned model via Ollama and
parsing a structured JSON result. It reuses the shared strict-coding gate so the
two engines are methodologically consistent, and tags its scores
`score_kind="llm_selfreport"` so downstream never naively compares them with the
transformer's NLI scores.

Design:
- Prompt lives in prompts/survey_coding.txt (versioned, auditable), not inline.
- The model returns a per-label relevance map (`theme_scores`); we build a
  score-descending (labels, scores) list from the analyst's candidate labels only
  (labels the model invents are ignored — the codebook is human-owned), then run
  `assign_strict_labels_from_results` exactly as the transformer path does.
- A per-response JSON failure yields an UNCERTAIN coding for that row (empty
  scores → the strict gate routes it to review) rather than killing the batch;
  server/timeout errors propagate (the batch can't proceed).
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from tqdm import tqdm

from analyze_survey import assign_strict_labels_from_results
from engines.base import ResponseCoding, SCORE_KIND_LLM_SELFREPORT
from engines.ollama_client import OllamaClient, OllamaJSONError

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


def _report(progress, done: int, total: int) -> None:
    """Call the GUI progress callback, swallowing UI errors so coding never dies."""
    if progress is not None:
        try:
            progress(done, total)
        except Exception:  # noqa: BLE001
            pass

# JSON schema for Ollama structured outputs (constrained decoding). theme_scores
# is left as a generic object because its keys are the (dynamic) candidate labels.
CODING_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "theme_scores": {"type": "object"},
        "sentiment": {"type": "string", "enum": ["positive", "neutral", "negative"]},
        "sentiment_confidence": {"type": "number"},
        "rationale": {"type": "string"},
    },
    "required": ["theme_scores", "sentiment", "rationale"],
}


class LlmEngine:
    """Ollama-backed theme/sentiment/rationale coding engine."""

    def __init__(
        self,
        model: str,
        client: Optional[OllamaClient] = None,
        *,
        temperature: float = 0.1,
        seed: Optional[int] = None,
        prompt_path: Optional[Path] = None,
    ):
        self.model = model
        self.client = client or OllamaClient()
        self.temperature = temperature
        self.seed = seed
        self.prompt_template = (prompt_path or (PROMPTS_DIR / "survey_coding.txt")).read_text(encoding="utf-8")

    def _build_prompt(self, text: str, labels: Sequence[str]) -> str:
        labels_block = "\n".join(f"- {label}" for label in labels)
        return (self.prompt_template
                .replace("<<LABELS>>", labels_block)
                .replace("<<RESPONSE>>", text))

    def code_responses(
        self,
        texts: Sequence[str],
        labels: Sequence[str],
        config: Dict[str, Any],
    ) -> List[ResponseCoding]:
        labels = list(labels)
        texts = list(texts)
        strict_cfg = config.get("strict_coding") or {}
        progress = config.get("progress_callback")  # progress(done, total) for the GUI
        total = len(texts)

        # Concurrency: the bottleneck is Ollama round-trips, which are I/O-bound, so
        # a few threads overlap them. Default is deliberately low — Ollama serves
        # requests up to its own OLLAMA_NUM_PARALLEL (often 1–4) and queues the
        # rest, so more workers past that buys nothing and just floods the server.
        # max_workers <= 1 keeps the plain sequential path (no thread overhead).
        max_workers = max(1, int(config.get("max_workers", 3)))

        if max_workers == 1:
            return self._code_sequential(texts, labels, strict_cfg, progress, total)
        return self._code_concurrent(texts, labels, strict_cfg, progress, total, max_workers)

    def _fetch(self, text: str, labels: List[str]) -> Dict[str, Any]:
        """One Ollama round-trip. Returns {} on unrecoverable JSON (→ uncertain)."""
        prompt = self._build_prompt(str(text), labels)
        try:
            return self.client.generate_json(
                self.model, prompt, schema=CODING_SCHEMA,
                temperature=self.temperature, seed=self.seed,
            )
        except OllamaJSONError:
            return {}

    def _code_sequential(self, texts, labels, strict_cfg, progress, total):
        codings: List[ResponseCoding] = []
        for i, text in enumerate(tqdm(texts, desc="LLM coding", unit="resp")):
            data = self._fetch(text, labels)
            codings.append(self._to_coding(data, labels, strict_cfg))
            _report(progress, i + 1, total)
        return codings

    def _code_concurrent(self, texts, labels, strict_cfg, progress, total, max_workers):
        # Results are collected by index so the output order matches the input
        # order regardless of which future finishes first — coding[i] must line up
        # with texts[i] for the downstream column joins.
        data_by_index: Dict[int, Dict[str, Any]] = {}
        done = 0
        lock = threading.Lock()  # guards the completion counter + progress call
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {pool.submit(self._fetch, text, labels): i
                       for i, text in enumerate(texts)}
            for future in tqdm(as_completed(futures), total=total, desc="LLM coding", unit="resp"):
                idx = futures[future]
                try:
                    data_by_index[idx] = future.result()
                except Exception:  # noqa: BLE001 - a single row failure → uncertain, not a dead batch
                    data_by_index[idx] = {}
                with lock:
                    done += 1
                    _report(progress, done, total)
        return [self._to_coding(data_by_index.get(i, {}), labels, strict_cfg)
                for i in range(total)]


    def _to_coding(
        self, data: Dict[str, Any], labels: List[str], strict_cfg: Dict[str, Any],
    ) -> ResponseCoding:
        theme_scores = data.get("theme_scores") or {}
        # Score every candidate label (missing -> 0.0); ignore invented labels.
        pairs = []
        for label in labels:
            try:
                score = float(theme_scores.get(label, 0.0))
            except (TypeError, ValueError):
                score = 0.0
            pairs.append((label, score))
        pairs.sort(key=lambda p: p[1], reverse=True)

        coding = ResponseCoding(
            labels=[p[0] for p in pairs],
            scores=[p[1] for p in pairs],
            score_kind=SCORE_KIND_LLM_SELFREPORT,
            source_engine="llm",
            model_id=self.model,
        )

        sentiment = data.get("sentiment")
        if sentiment:
            coding.sentiment_label = str(sentiment).upper()
            try:
                coding.sentiment_score = float(data.get("sentiment_confidence"))
            except (TypeError, ValueError):
                coding.sentiment_score = None
        coding.rationale = str(data.get("rationale", "") or "")

        if strict_cfg.get("enabled", False):
            result = [{"labels": coding.labels, "scores": coding.scores}]
            s_labels, s_conf, s_reason, s_margin = assign_strict_labels_from_results(result, strict_cfg)
            coding.strict_label = s_labels[0]
            coding.strict_confident = s_conf[0]
            coding.strict_reason = s_reason[0]
            coding.strict_margin = s_margin[0]

        return coding
