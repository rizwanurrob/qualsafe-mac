"""Where each person left off, per activity (V8_PLAN.md section 5).

One small JSON file, `progress.json`, holds for each activity the current step
and a handful of choices: paths, column names, labels, settings. It follows the
same rule as `core/app_settings.py`: **settings and paths, never anything
derived from a response.** Three guards enforce that:

* a per-activity whitelist of keys; anything else is dropped on save;
* values must be short (a per-key length limit); a value over its limit is
  dropped, not cut, so a half-saved value never comes back;
* the privacy confirmation is not a whitelisted key and is never saved. It is
  asked again on every data load.

The old survey resume file, `workspace.json`, is moved into `surveys` by an
explicit call to `migrate_workspace()` (the web app makes it when it switches
to this store); the old file is renamed to `workspace.json.bak`. `load` and
`save` never do it on their own, so the desktop app cannot take away a file the
web app still reads.

File location: `QNW_SETTINGS_DIR` if set (tests, the desktop app), else the app
folder.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from core.ux import activities

PROJECT_ROOT = Path(__file__).resolve().parents[2]
VERSION = 1

# Keys the old workspace.json carried; they move into `surveys` unchanged.
_WORKSPACE_KEYS = (
    "resume_path", "input_source", "ingestion_mode", "text_column", "text_columns",
    "question_column", "question_text_manual", "question_label_overrides_text",
    "descriptor_columns", "id_column", "analyze_one_question",
    "question_filter_value", "selected_question_value", "theme_labels_text",
)

# Per-activity whitelist of state keys.
WHITELIST: Dict[str, tuple] = {
    "surveys": _WORKSPACE_KEYS + (
        "project_path", "code_choice", "code_settings", "hand_answer", "explore_tab",
        "explore_filters",
    ),
    "charts": (
        "file_path", "question", "chart_type", "chart_settings", "draft_chart",
    ),
    "interviews": (
        "project_path", "document", "scroll_position", "explore_tab", "explore_filters",
    ),
}

# Never saved, whatever a caller passes. The privacy gate is asked on every load.
NEVER_SAVED = ("pii_confirmed", "pii_gate", "pii_attested", "privacy_confirmed")

# Default longest string; longer keys are listed here. Paths and a theme list
# (the analyst's own vocabulary) are the only long ones.
DEFAULT_MAX_LEN = 200
MAX_LEN: Dict[str, int] = {
    "resume_path": 1024, "project_path": 1024, "file_path": 1024,
    "theme_labels_text": 4000,
    "question_text_manual": 500, "question_filter_value": 500,
    "selected_question_value": 500, "question": 500,
}
MAX_ITEMS = 100
MAX_DEPTH = 3
MAX_FILE_BYTES = 64_000


def progress_path() -> Path:
    override = os.environ.get("QNW_SETTINGS_DIR", "").strip()
    base = Path(override) if override else PROJECT_ROOT
    return base / "progress.json"


def _workspace_path() -> Path:
    return progress_path().with_name("workspace.json")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class _TooLong(Exception):
    pass


def _clean(value: Any, limit: int, depth: int = 0) -> Any:
    """Return `value` if it is short plain data; raise `_TooLong` otherwise."""
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        if len(value) > limit:
            raise _TooLong
        return value
    if depth >= MAX_DEPTH:
        raise _TooLong
    if isinstance(value, (list, tuple)):
        if len(value) > MAX_ITEMS:
            raise _TooLong
        return [_clean(v, limit, depth + 1) for v in value]
    if isinstance(value, dict):
        if len(value) > MAX_ITEMS:
            raise _TooLong
        out = {}
        for k, v in value.items():
            if not isinstance(k, str) or len(k) > limit:
                raise _TooLong
            out[k] = _clean(v, limit, depth + 1)
        return out
    raise _TooLong


def clean_state(activity: str, state: Dict[str, Any]) -> Dict[str, Any]:
    """Keep only whitelisted keys whose values are short plain data."""
    allowed = WHITELIST[activity]
    out: Dict[str, Any] = {}
    for key, value in (state or {}).items():
        if key not in allowed or key in NEVER_SAVED:
            continue
        try:
            out[key] = _clean(value, MAX_LEN.get(key, DEFAULT_MAX_LEN))
        except _TooLong:
            continue
    return out


def _read_file() -> Dict[str, Any]:
    path = progress_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - a corrupt file must never block launch
        return {}
    if not isinstance(data, dict) or data.get("version") != VERSION:
        return {}
    return data


def _write_file(data: Dict[str, Any]) -> Path:
    path = progress_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, indent=2, ensure_ascii=False)
    if len(text.encode("utf-8")) > MAX_FILE_BYTES:
        raise ValueError("progress file would be too large")
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, path)
    return path


def _valid_entry(activity: str, entry: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(entry, dict):
        return None
    step = entry.get("step")
    if step not in {s.key for s in activities.get(activity).steps}:
        return None
    state = entry.get("state")
    return {
        "step": step,
        "updated": str(entry.get("updated", "")),
        "state": clean_state(activity, state if isinstance(state, dict) else {}),
    }


def migrate_workspace() -> bool:
    """Move `workspace.json` into `surveys` once. True if something moved."""
    old = _workspace_path()
    if not old.exists():
        return False
    try:
        raw = json.loads(old.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        raw = None
    if isinstance(raw, dict) and raw.get("resume_path") and "surveys" not in _read_file():
        state = clean_state("surveys", {k: raw[k] for k in _WORKSPACE_KEYS if k in raw})
        data = _read_file() or {"version": VERSION}
        data["surveys"] = {"step": "load", "updated": _now(), "state": state}
        _write_file(data)
    os.replace(old, old.with_name(old.name + ".bak"))
    return True


def load(activity: str) -> Optional[Dict[str, Any]]:
    """{"step", "updated", "state"} for an activity, or None if nothing is saved."""
    return _valid_entry(activity, _read_file().get(activity))


def save(activity: str, step: str, state: Dict[str, Any], *, now: Optional[str] = None) -> Optional[Path]:
    """Save the step and whitelisted state for one activity.

    Other activities are left as they are. Returns the file path, or None if
    `step` is not a step of this activity.
    """
    if step not in {s.key for s in activities.get(activity).steps}:
        return None
    data = _read_file() or {"version": VERSION}
    data[activity] = {"step": step, "updated": now or _now(),
                      "state": clean_state(activity, state)}
    return _write_file(data)


def clear(activity: str) -> None:
    """Start over: forget one activity and leave the others."""
    data = _read_file()
    if activity in data:
        del data[activity]
        _write_file(data)


def missing_paths(activity: str) -> list:
    """Saved file paths that no longer exist, so Continue can say so."""
    entry = load(activity)
    if not entry:
        return []
    keys = ("resume_path", "project_path", "file_path")
    return [p for k in keys if (p := entry["state"].get(k)) and not Path(p).exists()]


# ── Continue: what Home says about a saved place ─────────────────────────────

#: A saved place is worth offering only if it points at something: a file, a
#: project, or a theme list. A step alone (someone clicked through and left) is not.
_SUBSTANCE_KEYS = ("resume_path", "project_path", "file_path", "theme_labels_text")
#: The path that names the work, most telling first.
_NAME_KEYS = ("resume_path", "file_path", "project_path")


@dataclass(frozen=True)
class Summary:
    """What the Continue line on a Home card shows."""

    activity: str
    step_key: str
    step_title: str
    step_number: int
    step_total: int
    name: str                      # a file or project name, or "" (never a path)
    updated: Optional[datetime]
    missing: Tuple[str, ...]       # saved paths that are gone

    @property
    def detail(self) -> str:
        """`Step 3 of 5 · Code · 2 hours ago`."""
        parts = [f"Step {self.step_number} of {self.step_total}", self.step_title]
        if self.updated is not None:
            parts.append(ago(self.updated))
        return " · ".join(parts)


def summary(activity: str) -> Optional[Summary]:
    """The Continue summary for an activity, or None if there is nothing to continue."""
    entry = load(activity)
    if entry is None:
        return None
    state = entry["state"]
    if not any(state.get(k) for k in _SUBSTANCE_KEYS):
        return None
    act = activities.get(activity)
    name = ""
    for key in _NAME_KEYS:
        if state.get(key):
            name = Path(str(state[key])).name
            break
    return Summary(
        activity=activity, step_key=entry["step"], step_title=act.step(entry["step"]).title,
        step_number=act.step_number(entry["step"]), step_total=len(act.steps),
        name=name, updated=_parse_time(entry["updated"]),
        missing=tuple(missing_paths(activity)))


def _parse_time(text: str) -> Optional[datetime]:
    try:
        when = datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


def ago(when: datetime, now: Optional[datetime] = None) -> str:
    """Plain words for how long ago: `just now`, `5 minutes ago`, `yesterday`."""
    now = now or datetime.now(timezone.utc)
    seconds = max(0, int((now - when).total_seconds()))
    if seconds < 60:
        return "just now"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    days = hours // 24
    if days == 1:
        return "yesterday"
    if days < 14:
        return f"{days} days ago"
    return when.astimezone().strftime("%d %b %Y").lstrip("0")


def replace_path(activity: str, old: str, new: str) -> bool:
    """Point a saved place at a moved file. True if anything was replaced."""
    entry = load(activity)
    if entry is None:
        return False
    state, changed = dict(entry["state"]), False
    for key in ("resume_path", "project_path", "file_path"):
        if state.get(key) == old:
            state[key], changed = new, True
    if changed:
        save(activity, entry["step"], state, now=entry["updated"])
    return changed
