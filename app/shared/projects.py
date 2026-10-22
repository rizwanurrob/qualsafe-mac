"""
Finding and selecting `.qnw` project stores.

Extracted from the former monolithic `streamlit_app.py` (v4, Phase 0.1).
Per `app/__init__`, this module imports only from `core/`, `analysis/`,
`exports/`, `app.shared`, and Streamlit — never from `streamlit_app`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional
import streamlit as st

from app.shared.constants import STREAMLIT_OUTPUT_DIR


def discover_project_stores() -> List[Path]:
    """Find .qnw stores under the streamlit output tree (runs + interview runs)."""
    stores: List[Path] = []
    if STREAMLIT_OUTPUT_DIR.exists():
        stores.extend(sorted(STREAMLIT_OUTPUT_DIR.glob("**/*.qnw")))
    return stores


def active_project_path() -> Optional[Path]:
    """The store both the pipeline and the Lab write to, if one is chosen/known.

    Falls back to the most recent run's store so the Lab still works before the
    user explicitly picks a project — but the explicit choice always wins.
    """
    chosen = st.session_state.get("active_project_path", "")
    if chosen:
        return Path(chosen)
    stores = discover_project_stores()
    return stores[-1] if stores else None


def list_project_runs() -> List[Path]:
    """Every directory under the output tree holding a project store.

    Any subdirectory with a project.qnw counts — pipeline runs (`run_*`),
    interview runs (`run_iv_*`), and the guided sample (`SAMPLE_*`). The previous
    `run_*` glob silently hid the sample project from the Analysis and Codebook
    pages, stranding the onboarding path it exists for.
    """
    if not STREAMLIT_OUTPUT_DIR.exists():
        return []
    return sorted(
        [p for p in STREAMLIT_OUTPUT_DIR.iterdir()
         if p.is_dir() and (p / "project.qnw").exists()],
        reverse=True,
    )


def _record_codings_to_active_project(codings: Dict[str, List[str]], question_text=None) -> str:
    """Write Lab codes to the active project store. Returns a short status string."""
    store = active_project_path()
    if store is None:
        return ("No project store yet — run the analysis with '.qnw' enabled, or pick a "
                "project in Data Management, to save human codes into the store.")
    try:
        from core.populate import record_human_codings
        result = record_human_codings(
            store, codings, question_text=question_text,
            rater_name=str(st.session_state.get("analyst_name", "")),
        )
        msg = f"Recorded {result['applications']} human code(s) into {Path(store).name}."
        if result["unmatched"]:
            msg += (f" {result['unmatched']} response(s) had no matching source in the "
                    f"store (run the analysis on this dataset first).")
        return msg
    except Exception as exc:  # noqa: BLE001
        return f"(Could not update project store: {exc})"
