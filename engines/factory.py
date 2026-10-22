#!/usr/bin/env python
"""
Theme-engine factory + graceful fallback (v3, Phase 2).

`resolve_theme_engine(config)` returns the `ThemeEngine` selected by the
`engine.type` config block ("transformer" | "llm"), plus the resolved type. If
the LLM engine is requested but Ollama isn't reachable or the model isn't pulled,
it logs a warning and falls back to the transformer engine — the survey pipeline
must always be able to complete (the transformer stack is the dependable default).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Tuple

LOGGER = logging.getLogger("survey_nlp")


def resolve_theme_engine(config: Dict[str, Any]) -> Tuple[Any, str]:
    """Return (engine, engine_type). engine_type is the *effective* type after
    any fallback, so callers know which path actually ran."""
    # Local imports avoid import cycles (engines import analyze_survey).
    from engines.transformer_engine import TransformerEngine

    model_cfg = config.get("models", {})
    zero_shot_model = model_cfg.get("zero_shot_model", "facebook/bart-large-mnli")

    engine_cfg = config.get("engine", {}) or {}
    engine_type = engine_cfg.get("type", "transformer")

    if engine_type != "llm":
        return TransformerEngine(zero_shot_model=zero_shot_model), "transformer"

    # LLM engine requested — verify availability, else fall back.
    from engines.llm_engine import LlmEngine
    from engines.ollama_client import OllamaClient

    llm_cfg = engine_cfg.get("llm", {}) or {}
    model = llm_cfg.get("model")
    client = OllamaClient(timeout=int(llm_cfg.get("timeout_seconds", 120)))

    if not model or not client.is_available() or not client.has_model(model):
        LOGGER.warning(
            "LLM engine requested but Ollama server or model '%s' is unavailable — "
            "falling back to the transformer engine.", model,
        )
        return TransformerEngine(zero_shot_model=zero_shot_model), "transformer"

    return (
        LlmEngine(
            model=model, client=client,
            temperature=float(llm_cfg.get("temperature", 0.1)),
            seed=llm_cfg.get("seed"),
        ),
        "llm",
    )
