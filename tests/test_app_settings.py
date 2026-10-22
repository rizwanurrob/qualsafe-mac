"""
Tests for core/app_settings.py — persisted preferences (v3.7 UX pass).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.app_settings import PERSISTED_KEYS, load_app_settings, save_app_settings


@pytest.fixture(autouse=True)
def _tmp_settings_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("QNW_SETTINGS_DIR", str(tmp_path))
    return tmp_path


class TestAppSettings:
    def test_roundtrip(self, _tmp_settings_dir):
        save_app_settings({"app_mode": "survey", "engine_type": "llm",
                           "llm_model": "qwen2.5:3b", "analyst_name": "Riz",
                           "active_project_path": "C:/x/project.qnw"})
        loaded = load_app_settings()
        assert loaded["app_mode"] == "survey"
        assert loaded["llm_model"] == "qwen2.5:3b"

    def test_only_whitelisted_keys_persist(self, _tmp_settings_dir):
        """The file is a preferences whitelist, never a session-state dump."""
        save_app_settings({"app_mode": "survey", "df": "SHOULD NOT PERSIST",
                           "theme_labels_text": "nor this"})
        raw = json.loads((_tmp_settings_dir / "app_settings.json").read_text(encoding="utf-8"))
        assert set(raw) == set(PERSISTED_KEYS)
        assert "df" not in raw

    def test_missing_file_is_empty(self):
        assert load_app_settings() == {}

    def test_corrupt_file_is_empty_not_fatal(self, _tmp_settings_dir):
        (_tmp_settings_dir / "app_settings.json").write_text("{not json", encoding="utf-8")
        assert load_app_settings() == {}

    def test_non_dict_json_is_empty(self, _tmp_settings_dir):
        (_tmp_settings_dir / "app_settings.json").write_text('["a list"]', encoding="utf-8")
        assert load_app_settings() == {}
