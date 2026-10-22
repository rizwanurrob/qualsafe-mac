"""
Tests for engines/factory.py — engine selection + graceful fallback.

OllamaClient is patched so no live server is needed.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engines.factory import resolve_theme_engine
from engines.transformer_engine import TransformerEngine
from engines.llm_engine import LlmEngine

MODELS = {"models": {"zero_shot_model": "facebook/bart-large-mnli"}}


def _fake_client(available=True, has_model=True):
    inst = MagicMock()
    inst.is_available.return_value = available
    inst.has_model.return_value = has_model
    cls = MagicMock(return_value=inst)
    return cls


class TestFactory:
    def test_default_is_transformer(self):
        engine, etype = resolve_theme_engine(MODELS)
        assert isinstance(engine, TransformerEngine) and etype == "transformer"

    def test_explicit_transformer(self):
        cfg = {**MODELS, "engine": {"type": "transformer"}}
        engine, etype = resolve_theme_engine(cfg)
        assert isinstance(engine, TransformerEngine) and etype == "transformer"

    def test_llm_selected_when_available(self):
        cfg = {**MODELS, "engine": {"type": "llm", "llm": {"model": "llama3.2:3b"}}}
        with patch("engines.ollama_client.OllamaClient", _fake_client(available=True, has_model=True)):
            engine, etype = resolve_theme_engine(cfg)
        assert isinstance(engine, LlmEngine) and etype == "llm"
        assert engine.model == "llama3.2:3b"

    def test_fallback_when_server_down(self):
        cfg = {**MODELS, "engine": {"type": "llm", "llm": {"model": "llama3.2:3b"}}}
        with patch("engines.ollama_client.OllamaClient", _fake_client(available=False)):
            engine, etype = resolve_theme_engine(cfg)
        assert isinstance(engine, TransformerEngine) and etype == "transformer"

    def test_fallback_when_model_not_pulled(self):
        cfg = {**MODELS, "engine": {"type": "llm", "llm": {"model": "llama3.2:3b"}}}
        with patch("engines.ollama_client.OllamaClient", _fake_client(available=True, has_model=False)):
            engine, etype = resolve_theme_engine(cfg)
        assert isinstance(engine, TransformerEngine) and etype == "transformer"

    def test_fallback_when_no_model_configured(self):
        cfg = {**MODELS, "engine": {"type": "llm", "llm": {}}}
        with patch("engines.ollama_client.OllamaClient", _fake_client(available=True)):
            engine, etype = resolve_theme_engine(cfg)
        assert etype == "transformer"
