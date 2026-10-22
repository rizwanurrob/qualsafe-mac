#!/usr/bin/env python
"""
Workspace resume (v3.8.0, item 8.2).

A multi-day project shouldn't start each morning with redoing Data Setup and
Theme Setup. This persists the *shape* of a session — where the data file lives,
how its columns are mapped, and the analyst's theme labels — so one click
restores it.

What is deliberately NOT stored: the data itself, and the PII confirmation. The
file stays wherever the analyst keeps it; we remember only its path (metadata,
consistent with the app-settings whitelist philosophy). The PII gate re-arms on
every resume because the attestation is about a load, not a session.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# The session-shape keys that persist. Labels are analyst-authored codebook
# vocabulary (their work product), not respondent data.
WORKSPACE_KEYS = (
    "resume_path",              # where the data can be re-read from
    "input_source",             # provenance label shown in the UI
    "ingestion_mode",           # "long" | "wide"
    "text_column",
    "text_columns",
    "question_column",
    "question_text_manual",
    "question_label_overrides_text",
    "descriptor_columns",
    "id_column",
    "analyze_one_question",
    "question_filter_value",
    "selected_question_value",
    "theme_labels_text",
)


def _workspace_path() -> Path:
    override = os.environ.get("QNW_SETTINGS_DIR", "").strip()
    base = Path(override) if override else PROJECT_ROOT
    return base / "workspace.json"


def derive_resume_path(input_source: str, input_file_path: str = "") -> str:
    """Best on-disk path to re-read the current dataset from, or "".

    Folder loads and the synthetic sample have stable paths. Browser uploads
    don't — but once a run has happened, the run's input snapshot is a faithful
    on-disk copy, so that becomes the resume point. No path → no resume offer
    (never guess at data).
    """
    source = str(input_source or "")
    if source.startswith("folder:"):
        return source[len("folder:"):]
    if source == "synthetic_sample":
        return str(PROJECT_ROOT / "data" / "sample_survey_education.csv")
    if source.startswith("resume:"):
        return source[len("resume:"):]
    # Uploads/public: only resumable via a run's input snapshot.
    if input_file_path and Path(input_file_path).exists():
        return input_file_path
    return ""


def save_workspace(state: Dict[str, Any]) -> Optional[Path]:
    """Persist the whitelisted session shape. Returns the path, or None if there
    is nothing worth resuming (no reachable data path)."""
    resume_path = derive_resume_path(
        str(state.get("input_source", "")), str(state.get("input_file_path", "")))
    if not resume_path:
        return None
    payload = {k: state.get(k, "") for k in WORKSPACE_KEYS}
    payload["resume_path"] = resume_path
    path = _workspace_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def load_workspace() -> Dict[str, Any]:
    """Read the saved workspace; {} when absent, corrupt, or its data file is gone.

    A workspace pointing at a deleted/moved file is useless and confusing to
    offer — treat it as no workspace.
    """
    path = _workspace_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    if not isinstance(data, dict):
        return {}
    resume_path = str(data.get("resume_path", ""))
    if not resume_path or not Path(resume_path).exists():
        return {}
    return {k: data.get(k) for k in WORKSPACE_KEYS if k in data}


def clear_workspace() -> None:
    _workspace_path().unlink(missing_ok=True)
