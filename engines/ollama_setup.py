#!/usr/bin/env python
"""
Ollama detection and guided installation (v4).

The local-LLM engine needs Ollama running, but "install Ollama" is a wall a
non-technical analyst hits with no guidance. This module reports exactly what's
missing (binary? server? model?) and gives the precise, OS-correct next step.

It does **not** silently run an installer. Installing system software and piping a
remote script to a shell are the user's decision to make in their own terminal —
the app surfaces the official command and link, detects when it's done, and lets
the user re-check. (Downloading a *model* through an installed Ollama is a
different, in-app, consent-gated action handled by OllamaClient.pull.)
"""

from __future__ import annotations

import platform
import shutil
from typing import Any, Dict, Optional

OLLAMA_DOWNLOAD_URL = "https://ollama.com/download"
OLLAMA_LIBRARY_URL = "https://ollama.com/library"


def ollama_binary_path() -> Optional[str]:
    """Path to the `ollama` executable, or None if not on PATH."""
    return shutil.which("ollama")


def installation_status(client=None) -> Dict[str, Any]:
    """Report what's present: the binary, a reachable server, and its version.

    `client` is an optional OllamaClient (injectable for tests). The three states
    that matter: not installed → install; installed but server down → start it;
    server up → ready to pull a model.
    """
    binary = ollama_binary_path()
    if client is None:
        from engines.ollama_client import OllamaClient
        client = OllamaClient()

    server_up = False
    version = None
    try:
        server_up = client.is_available()
        if server_up:
            version = client.version()
    except Exception:  # noqa: BLE001 - detection must never raise into the UI
        server_up = False

    if not binary and not server_up:
        state = "not_installed"
    elif binary and not server_up:
        state = "installed_not_running"
    else:
        state = "ready"

    return {
        "state": state,
        "binary_path": binary,
        "server_running": server_up,
        "version": version,
        "host": getattr(client, "host", "http://localhost:11434"),
    }


def install_instructions(system: Optional[str] = None) -> Dict[str, Any]:
    """OS-specific install guidance: a headline, ordered steps, and the command.

    `system` defaults to the current platform; passing it makes this testable
    across OSes.
    """
    system = (system or platform.system()).lower()

    if system == "windows":
        return {
            "os": "Windows",
            "method": "installer",
            "headline": "Download and run the Ollama installer",
            "steps": [
                f"Open {OLLAMA_DOWNLOAD_URL} and download 'OllamaSetup.exe'.",
                "Run the installer (it sets up Ollama and starts it automatically).",
                "Come back here and click 'Re-check Ollama'.",
            ],
            "command": None,  # Windows uses the GUI installer, not a shell command
            "url": OLLAMA_DOWNLOAD_URL,
        }
    if system == "darwin":
        return {
            "os": "macOS",
            "method": "installer_or_brew",
            "headline": "Install Ollama for macOS",
            "steps": [
                f"Download the macOS app from {OLLAMA_DOWNLOAD_URL} and open it, OR",
                "install via Homebrew in Terminal (command below), then",
                "click 'Re-check Ollama'.",
            ],
            "command": "brew install ollama && ollama serve",
            "url": OLLAMA_DOWNLOAD_URL,
        }
    # Linux and everything else.
    return {
        "os": "Linux",
        "method": "script",
        "headline": "Install Ollama with the official script",
        "steps": [
            "Run the command below in a terminal (it installs Ollama):",
            "start the server with 'ollama serve' if it isn't already running, then",
            "click 'Re-check Ollama'.",
        ],
        "command": "curl -fsSL https://ollama.com/install.sh | sh",
        "url": OLLAMA_DOWNLOAD_URL,
    }


def start_server_command(system: Optional[str] = None) -> str:
    """The command to start an already-installed Ollama server."""
    return "ollama serve"


def recommended_models() -> list:
    """Small instruction-tuned models that work well as the coding engine."""
    return [
        {"tag": "llama3.2:3b", "note": "good default balance (~2 GB)"},
        {"tag": "qwen2.5:3b", "note": "strong at structured output"},
        {"tag": "gemma2:2b", "note": "smallest / fastest"},
        {"tag": "phi3.5", "note": "strong reasoning for its size"},
    ]
