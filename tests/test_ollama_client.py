"""
Tests for engines/ollama_client.py — fully mocked HTTP (no live server).

Only requests.get / requests.post are patched, so requests.exceptions.* stay
real exception classes (the client's except-clauses depend on that).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engines.ollama_client import (
    OllamaClient, OllamaJSONError, OllamaNotAvailable, OllamaTimeout, extract_json,
)

GET = "engines.ollama_client.requests.get"
POST = "engines.ollama_client.requests.post"


def _resp(json_data=None, lines=None, raise_exc=None):
    r = MagicMock()
    r.raise_for_status.side_effect = raise_exc
    r.json.return_value = json_data or {}
    if lines is not None:
        r.iter_lines.return_value = iter(lines)
    return r


# ─────────────────────────────────────────────────────────────────────────────
# extract_json (pure)
# ─────────────────────────────────────────────────────────────────────────────

class TestExtractJson:
    def test_plain_object(self):
        assert extract_json('{"a": 1}') == {"a": 1}

    def test_fenced_block(self):
        assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}

    def test_prose_wrapped(self):
        text = 'Sure! Here is the coding:\n{"themes": ["A", "B"]}\nHope that helps.'
        assert extract_json(text) == {"themes": ["A", "B"]}

    def test_braces_inside_string_values(self):
        # A closing brace inside a string must not end the object early.
        assert extract_json('{"note": "use {curly} here", "n": 2}') == {"note": "use {curly} here", "n": 2}

    def test_no_json_raises(self):
        with pytest.raises(OllamaJSONError):
            extract_json("no json at all")

    def test_incomplete_raises(self):
        with pytest.raises(OllamaJSONError):
            extract_json('{"a": 1')


# ─────────────────────────────────────────────────────────────────────────────
# detection / listing
# ─────────────────────────────────────────────────────────────────────────────

class TestDetection:
    def test_version_returns_string(self):
        with patch(GET, return_value=_resp({"version": "0.5.1"})):
            assert OllamaClient().version() == "0.5.1"

    def test_version_none_when_unreachable(self):
        with patch(GET, side_effect=requests.exceptions.ConnectionError()):
            c = OllamaClient()
            assert c.version() is None
            assert c.is_available() is False

    def test_list_models_parses_tags(self):
        payload = {"models": [{"model": "llama3.2:3b"}, {"name": "qwen2.5:3b"}]}
        with patch(GET, return_value=_resp(payload)):
            assert OllamaClient().list_models() == ["llama3.2:3b", "qwen2.5:3b"]

    def test_list_models_unreachable_raises(self):
        with patch(GET, side_effect=requests.exceptions.ConnectionError()):
            with pytest.raises(OllamaNotAvailable):
                OllamaClient().list_models()

    def test_has_model_exact_and_latest(self):
        payload = {"models": [{"model": "llama3.2:3b"}, {"model": "gemma2:2b"}]}
        with patch(GET, return_value=_resp(payload)):
            c = OllamaClient()
            assert c.has_model("llama3.2:3b") is True
            assert c.has_model("phi3.5") is False
        with patch(GET, return_value=_resp({"models": [{"model": "phi3.5:latest"}]})):
            assert OllamaClient().has_model("phi3.5") is True


# ─────────────────────────────────────────────────────────────────────────────
# pull
# ─────────────────────────────────────────────────────────────────────────────

class TestPull:
    def test_streams_progress_and_succeeds(self):
        lines = [
            b'{"status": "pulling manifest"}',
            b'{"status": "pulling abc", "total": 100, "completed": 50}',
            b'{"status": "success"}',
        ]
        events = []
        with patch(POST, return_value=_resp(lines=lines)):
            ok = OllamaClient().pull("llama3.2:3b", on_progress=events.append)
        assert ok is True
        assert any(e.get("completed") == 50 for e in events)

    def test_error_event_raises(self):
        lines = [b'{"error": "model not found"}']
        with patch(POST, return_value=_resp(lines=lines)):
            with pytest.raises(Exception):
                OllamaClient().pull("nope")


# ─────────────────────────────────────────────────────────────────────────────
# generate_json
# ─────────────────────────────────────────────────────────────────────────────

class TestGenerateJson:
    def test_returns_parsed_json(self):
        with patch(POST, return_value=_resp({"response": '{"themes": ["A"], "sentiment": "positive"}'})):
            out = OllamaClient().generate_json("llama3.2:3b", "code this")
        assert out == {"themes": ["A"], "sentiment": "positive"}

    def test_passes_schema_as_format_and_options(self):
        schema = {"type": "object", "properties": {"themes": {"type": "array"}}}
        mock_post = MagicMock(return_value=_resp({"response": '{"themes": []}'}))
        with patch(POST, mock_post):
            OllamaClient().generate_json("m", "p", schema=schema, temperature=0.1, seed=42)
        sent = mock_post.call_args.kwargs["json"]
        assert sent["format"] == schema
        assert sent["stream"] is False
        assert sent["options"] == {"temperature": 0.1, "seed": 42}

    def test_defaults_to_json_format_without_schema(self):
        mock_post = MagicMock(return_value=_resp({"response": '{"a": 1}'}))
        with patch(POST, mock_post):
            OllamaClient().generate_json("m", "p")
        assert mock_post.call_args.kwargs["json"]["format"] == "json"

    def test_recovers_prose_wrapped_json(self):
        with patch(POST, return_value=_resp({"response": 'Here you go:\n{"themes": ["X"]}'})):
            assert OllamaClient().generate_json("m", "p") == {"themes": ["X"]}

    def test_retries_then_succeeds(self):
        bad = _resp({"response": "not json"})
        good = _resp({"response": '{"ok": true}'})
        with patch(POST, side_effect=[bad, good]):
            assert OllamaClient().generate_json("m", "p", retries=2) == {"ok": True}

    def test_all_attempts_fail_raises(self):
        bad = _resp({"response": "never json"})
        with patch(POST, side_effect=[bad, bad, bad]):
            with pytest.raises(OllamaJSONError):
                OllamaClient().generate_json("m", "p", retries=2)

    def test_timeout_raises_ollama_timeout(self):
        with patch(POST, side_effect=requests.exceptions.Timeout()):
            with pytest.raises(OllamaTimeout):
                OllamaClient().generate_json("m", "p")
