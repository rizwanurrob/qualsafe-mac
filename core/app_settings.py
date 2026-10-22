#!/usr/bin/env python
"""
Persistent app settings (v3.7, UX pass).

Streamlit session state dies with the process, so until now every restart lost
the analyst's mode, engine choice, model, name, and active project — a returning
user re-entered everything. This persists that handful of preferences to a small
local JSON file next to the app.

Deliberately a whitelist, not a session-state dump: only harmless preferences are
stored, never data, never anything derived from responses. The file is plain JSON
so a curious user can read exactly what the tool remembers about them.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# The only keys that persist. Anything else passed to save is dropped.
PERSISTED_KEYS = (
    "app_mode",             # "survey" | "interview" | "" (wizard)
    "theme_mode",           # "dark" | "light" (UI skin)
    "category_palette",     # named code-colour palette (see core/theme.py)
    "heatmap_scheme",       # chosen heatmap color ramp
    "engine_type",          # "transformer" | "llm"
    "llm_model",
    "analyst_name",
    "active_project_path",
    "tours_seen",           # JSON list of activity keys whose first-visit tour was shown
    # Model choices (names only — never data). Let a selected embedding /
    # sentiment / zero-shot model survive a restart (v3.9.7 Model Manager).
    "adv_embedding_model",
    "adv_sentiment_model",
    "adv_zero_shot_model",
)


def _settings_path() -> Path:
    """Settings file location; QNW_SETTINGS_DIR overrides (used by tests)."""
    override = os.environ.get("QNW_SETTINGS_DIR", "").strip()
    base = Path(override) if override else PROJECT_ROOT
    return base / "app_settings.json"


def load_app_settings() -> Dict[str, Any]:
    """Read persisted settings; missing/corrupt file is just empty settings."""
    path = _settings_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - a corrupt prefs file must never block launch
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: data[k] for k in PERSISTED_KEYS if k in data}


def save_app_settings(settings: Dict[str, Any]) -> Path:
    """Write the whitelisted subset of `settings`. Returns the file path."""
    path = _settings_path()
    payload = {k: settings.get(k, "") for k in PERSISTED_KEYS}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path
