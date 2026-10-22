#!/usr/bin/env python
"""
Ollama HTTP client (v3, Phase 1).

A thin, fully-mockable wrapper over the local Ollama server so the tool can run a
small instruction-tuned model on-device — no survey/interview text ever leaves
the machine (the local-first, FERPA-conscious posture). Everything goes through
`requests`; tests patch `engines.ollama_client.requests`, so no live server or
model download is ever required in CI.

API verified against the live Ollama docs at build time (2026-07):
- Host: http://localhost:11434 (overridable via OLLAMA_HOST).
- GET  /api/version           -> {"version": "..."}
- GET  /api/tags              -> {"models": [{"model": "...", ...}]}
- POST /api/pull   (stream)   -> lines of {"status","digest","total","completed"} … {"status":"success"}
- POST /api/generate          -> {"response": "...", "done": true, ...}
  `format` accepts the string "json" OR a JSON schema object (structured outputs,
  Ollama >= 0.3.0) for constrained decoding — more reliable + faster on small models.

Small models still occasionally wrap JSON in prose/markdown, so `generate_json`
adds tolerant extraction + bounded retry.
"""

from __future__ import annotations

import json
import os
from typing import Any, Callable, Dict, List, Optional, Union

import requests

DEFAULT_TIMEOUT = 120


def _default_host() -> str:
    host = os.environ.get("OLLAMA_HOST", "http://localhost:11434").strip()
    if not host.startswith(("http://", "https://")):
        host = "http://" + host
    return host.rstrip("/")


# ── Errors ───────────────────────────────────────────────────────────────────
class OllamaError(Exception):
    """Base error for Ollama interactions."""


class OllamaNotAvailable(OllamaError):
    """Server not installed/reachable, or model not pulled."""


class OllamaTimeout(OllamaError):
    """A request exceeded the configured timeout."""


class OllamaJSONError(OllamaError):
    """The model did not return recoverable JSON."""


# ── Tolerant JSON extraction (pure, unit-tested) ─────────────────────────────
def extract_json(text: str) -> Dict[str, Any]:
    """Return the first complete JSON object in `text`.

    Handles the common small-model failure modes: leading/trailing prose and
    ```json fenced blocks. Brace counting is string-aware so braces inside string
    values don't fool it. Raises OllamaJSONError if nothing parseable is found.
    """
    s = (text or "").strip()
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass

    start = s.find("{")
    if start == -1:
        raise OllamaJSONError("No JSON object found in model response.")

    depth = 0
    in_str = False
    escaped = False
    for i in range(start, len(s)):
        c = s[i]
        if in_str:
            if escaped:
                escaped = False
            elif c == "\\":
                escaped = True
            elif c == '"':
                in_str = False
        else:
            if c == '"':
                in_str = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(s[start:i + 1])
                    except json.JSONDecodeError as exc:
                        raise OllamaJSONError(f"Malformed JSON object: {exc}") from exc
    raise OllamaJSONError("No complete JSON object found in model response.")


# ── Client ───────────────────────────────────────────────────────────────────
class OllamaClient:
    """Minimal client for the local Ollama server."""

    def __init__(self, host: Optional[str] = None, timeout: int = DEFAULT_TIMEOUT):
        self.host = (host.rstrip("/") if host else _default_host())
        self.timeout = timeout

    def _url(self, path: str) -> str:
        return f"{self.host}{path}"

    # ── detection / listing ──────────────────────────────────────────────────
    def version(self) -> Optional[str]:
        """Return the server version, or None if the server is unreachable."""
        try:
            resp = requests.get(self._url("/api/version"), timeout=self.timeout)
            resp.raise_for_status()
            return resp.json().get("version")
        except requests.exceptions.RequestException:
            return None

    def is_available(self) -> bool:
        """True if the Ollama server responds."""
        return self.version() is not None

    def list_models(self) -> List[str]:
        """Names of locally pulled models (e.g. 'llama3.2:3b')."""
        try:
            resp = requests.get(self._url("/api/tags"), timeout=self.timeout)
            resp.raise_for_status()
        except requests.exceptions.Timeout as exc:
            raise OllamaTimeout("Timed out listing Ollama models.") from exc
        except requests.exceptions.RequestException as exc:
            raise OllamaNotAvailable(f"Could not reach Ollama at {self.host}: {exc}") from exc
        data = resp.json()
        return [m.get("model") or m.get("name") for m in data.get("models", []) if (m.get("model") or m.get("name"))]

    def has_model(self, model: str) -> bool:
        """True if `model` is available locally (exact, or matches ':latest')."""
        available = self.list_models()
        return model in available or f"{model}:latest" in available

    # ── pull (with streaming progress) ───────────────────────────────────────
    def pull(self, model: str, on_progress: Optional[Callable[[Dict[str, Any]], None]] = None) -> bool:
        """Download a model, streaming progress events to `on_progress`.

        Each event is a dict like {"status","digest","total","completed"}; a UI
        can compute a percentage from total/completed. Returns True on success.
        The CALLER is responsible for obtaining user consent before pulling — a
        model download is a large, explicit network side-effect.
        """
        try:
            resp = requests.post(
                self._url("/api/pull"),
                json={"model": model, "stream": True},
                stream=True, timeout=self.timeout,
            )
            resp.raise_for_status()
        except requests.exceptions.Timeout as exc:
            raise OllamaTimeout(f"Timed out pulling model '{model}'.") from exc
        except requests.exceptions.RequestException as exc:
            raise OllamaNotAvailable(f"Could not pull '{model}' from Ollama: {exc}") from exc

        success = False
        for line in resp.iter_lines():
            if not line:
                continue
            if isinstance(line, bytes):
                line = line.decode("utf-8", errors="replace")
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if on_progress:
                on_progress(event)
            if event.get("error"):
                raise OllamaError(f"Pull failed: {event['error']}")
            if event.get("status") == "success":
                success = True
        return success

    # ── generate JSON (structured output + retry/repair) ─────────────────────
    def generate_json(
        self,
        model: str,
        prompt: str,
        schema: Optional[Dict[str, Any]] = None,
        *,
        temperature: float = 0.1,
        seed: Optional[int] = None,
        retries: int = 2,
    ) -> Dict[str, Any]:
        """Generate a response and return it parsed as a JSON object.

        `schema` (a JSON Schema dict) enables Ollama structured outputs
        (constrained decoding); when omitted, `format: "json"` is requested. On
        malformed JSON the call is retried up to `retries` times before raising
        OllamaJSONError. Determinism knobs: low `temperature` and optional `seed`.
        """
        options: Dict[str, Any] = {"temperature": temperature}
        if seed is not None:
            options["seed"] = seed
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "format": schema if schema is not None else "json",
            "options": options,
        }

        last_error: Optional[Exception] = None
        for _ in range(retries + 1):
            try:
                resp = requests.post(self._url("/api/generate"), json=payload, timeout=self.timeout)
                resp.raise_for_status()
            except requests.exceptions.Timeout as exc:
                raise OllamaTimeout(f"Timed out generating with '{model}'.") from exc
            except requests.exceptions.RequestException as exc:
                raise OllamaNotAvailable(f"Ollama generate failed: {exc}") from exc

            text = resp.json().get("response", "")
            try:
                return extract_json(text)
            except OllamaJSONError as exc:
                last_error = exc  # small model returned unparseable text — retry
                continue

        raise OllamaJSONError(
            f"Model '{model}' did not return valid JSON after {retries + 1} attempts: {last_error}"
        )
