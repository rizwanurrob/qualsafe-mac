"""Where the web app saves and restores your place, per activity (Update 3, phase 4b).

The store is `core/ux/progress.py`, the same file the desktop app uses and with the same rules:
settings and paths, never anything derived from a response, and never the privacy confirmation (the
page asks for it again every time a file is loaded). This module is only the translation between
that store and the web app's `st.session_state`.

* `collect(activity)`  what to save for an activity, from session state
* `apply(activity, state)`  put a saved state back (reloads the data file; the privacy check re-arms
  because `input_source` becomes a fresh `resume:` value)
* `maybe_persist_progress()`  save when, and only when, something changed (called every run)
* `continue_activity(activity)`  Home's Continue: restore, then go to the saved step and screen

It replaces `core/workspace.py`'s resume file for the web app; `migrate_once()` moves an old
`workspace.json` into the surveys entry the first time it runs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import streamlit as st

from app.shared import nav
from app.shared.data import dataframe_is_ready
from core import workspace as old_workspace
from core.ux import activities, progress


def migrate_once() -> None:
    """Move the old resume file into the new store, once per session."""
    if st.session_state.get("_progress_migrated"):
        return
    st.session_state["_progress_migrated"] = True
    try:
        progress.migrate_workspace()
    except Exception:  # noqa: BLE001 - an unreadable old file must never stop the app opening
        pass


def collect(activity_key: str) -> Dict[str, Any]:
    """The whitelisted state worth saving for an activity (the store drops the rest)."""
    state = st.session_state
    out: Dict[str, Any] = {}
    if activity_key == "surveys":
        for key in old_workspace.WORKSPACE_KEYS:
            if key != "resume_path":
                out[key] = state.get(key, "")
        if dataframe_is_ready():
            resume = old_workspace.derive_resume_path(
                str(state.get("input_source", "")), str(state.get("input_file_path", "")))
            if resume:
                out["resume_path"] = resume
        out["explore_tab"] = nav.current_screen("surveys", "explore")
        out["code_choice"] = state.get("code_choice", "")
    if activity_key in ("surveys", "interviews"):
        project = state.get("active_project_path", "")
        if project and Path(project).exists():
            out["project_path"] = project
    if activity_key == "interviews":
        out["explore_tab"] = nav.current_screen("interviews", "explore")
    return out


def maybe_persist_progress() -> None:
    """Save the current activity's step and state when either changed since the last save."""
    activity_key = nav.current_activity()
    if not activity_key:
        return
    step = nav.step_of(activity_key)
    current = {"activity": activity_key, "step": step, "state": collect(activity_key)}
    if current == st.session_state.get("_persisted_progress"):
        return
    try:
        progress.save(activity_key, step, current["state"])
        st.session_state["_persisted_progress"] = current
    except Exception:  # noqa: BLE001 - saving your place must never break the page
        pass


def apply(activity_key: str, state: Dict[str, Any]) -> None:
    """Put a saved state back. A file that has moved is skipped; the rest still comes back."""
    resume = state.get("resume_path")
    if activity_key == "surveys" and resume and Path(str(resume)).exists():
        from app.shared.state import resume_workspace

        keys = (*old_workspace.WORKSPACE_KEYS,)
        resume_workspace({k: state[k] for k in keys if k in state})
    project = state.get("project_path")
    if project and Path(str(project)).exists():
        st.session_state["active_project_path"] = str(project)
    if activity_key == "surveys" and state.get("code_choice"):
        st.session_state["code_choice"] = state["code_choice"]


def continue_activity(activity_key: str) -> None:
    """Home's Continue: restore the saved state, then open the saved step and screen."""
    entry = progress.load(activity_key)
    if entry is None:
        nav.go_activity(activity_key)
        return
    apply(activity_key, entry["state"])
    screen = entry["state"].get("explore_tab", "") if entry["step"] == "explore" else ""
    nav.go_activity(activity_key, entry["step"], screen=screen)


def start_over(activity_key: str) -> None:
    """Forget one activity's saved place. Files and projects are left alone."""
    progress.clear(activity_key)
    if st.session_state.get("_persisted_progress", {}).get("activity") == activity_key:
        st.session_state.pop("_persisted_progress", None)
    st.session_state.pop(f"step_{activity_key}", None)


def summaries() -> Dict[str, Any]:
    """The Continue line for each activity that has one."""
    return {a.key: s for a in activities.ACTIVITIES if (s := progress.summary(a.key)) is not None}
