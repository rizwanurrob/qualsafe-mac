"""
Tests for engines/ollama_setup.py — guided Ollama installation (v4).

Pure detection + guidance; no live server, no installer execution.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engines.ollama_setup import (
    install_instructions,
    installation_status,
    recommended_models,
)


class TestInstallInstructions:
    def test_windows_uses_installer_not_shell(self):
        info = install_instructions("Windows")
        assert info["os"] == "Windows"
        assert info["command"] is None  # GUI installer, never a piped shell script
        assert "ollama.com" in info["url"]

    def test_macos_offers_brew(self):
        info = install_instructions("Darwin")
        assert "brew" in info["command"]

    def test_linux_offers_official_script(self):
        info = install_instructions("Linux")
        assert "install.sh" in info["command"]

    def test_every_os_has_steps_and_url(self):
        for system in ("Windows", "Darwin", "Linux"):
            info = install_instructions(system)
            assert info["steps"] and info["url"].startswith("https://")


class TestInstallationStatus:
    def test_not_installed_when_no_binary_no_server(self):
        client = MagicMock()
        client.is_available.return_value = False
        with patch("engines.ollama_setup.ollama_binary_path", return_value=None):
            status = installation_status(client)
        assert status["state"] == "not_installed"

    def test_installed_not_running(self):
        client = MagicMock()
        client.is_available.return_value = False
        with patch("engines.ollama_setup.ollama_binary_path", return_value="/usr/bin/ollama"):
            status = installation_status(client)
        assert status["state"] == "installed_not_running"

    def test_ready_when_server_up(self):
        client = MagicMock()
        client.is_available.return_value = True
        client.version.return_value = "0.3.0"
        with patch("engines.ollama_setup.ollama_binary_path", return_value="/usr/bin/ollama"):
            status = installation_status(client)
        assert status["state"] == "ready" and status["version"] == "0.3.0"

    def test_detection_never_raises(self):
        client = MagicMock()
        client.is_available.side_effect = RuntimeError("boom")
        with patch("engines.ollama_setup.ollama_binary_path", return_value=None):
            status = installation_status(client)  # must not raise
        assert status["state"] == "not_installed"


def test_recommended_models_present():
    tags = [m["tag"] for m in recommended_models()]
    assert "llama3.2:3b" in tags
