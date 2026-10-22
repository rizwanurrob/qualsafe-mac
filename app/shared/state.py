"""
Session state, persisted preferences, theming, and navigation.

Extracted from the former monolithic `streamlit_app.py` (v4, Phase 0.1).
Per `app/__init__`, this module imports only from `core/`, `analysis/`,
`exports/`, `app.shared`, and Streamlit — never from `streamlit_app`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict
import altair as alt
import streamlit as st
from core.app_settings import PERSISTED_KEYS, load_app_settings, save_app_settings
from core.theme import (
    CATEGORY_PALETTES, DEFAULT_CATEGORY_PALETTE, brand_css, register_altair_theme)

from app.shared.constants import PROJECT_ROOT
from app.shared.io import load_file_from_path, postprocess_loaded_df
from app.shared.data import dataframe_is_ready


def apply_brand_theme_css() -> None:
    """Apply the selected skin (dark or light), including the Altair charts.

    Palette and rationale live in `core/theme.py`. The mode is read from session
    state (set by the sidebar Appearance control) so a toggle re-themes the whole
    page — chrome, panels, banners, and charts — on the next rerun.
    """
    mode = st.session_state.get("theme_mode", "dark")
    if mode not in ("dark", "light"):
        mode = "dark"
    palette = st.session_state.get("category_palette", DEFAULT_CATEGORY_PALETTE)
    if palette not in CATEGORY_PALETTES:
        palette = DEFAULT_CATEGORY_PALETTE
    register_altair_theme(alt, mode, palette)
    st.markdown(brand_css(mode), unsafe_allow_html=True)


def render_appearance_control(container=None) -> None:
    """Sidebar Dark/Light skin toggle. The choice persists across restarts.

    Note: this re-themes everything QualSafe styles directly (chrome, panels,
    banners, and the Altair charts). The interactive `st.dataframe` grid renders
    on a canvas that follows Streamlit's *own* theme (the ⋮ → Settings → Theme
    menu), which the app can't set at runtime — so for a fully light data grid a
    user also flips that. The colored heatmap (the data visualization) is fully
    themed here.
    """
    container = container if container is not None else st.sidebar
    container.radio(
        "Appearance",
        options=["dark", "light"],
        format_func=lambda m: "🌙 Dark" if m == "dark" else "☀️ Light",
        key="theme_mode",
        horizontal=True,
    )
    container.selectbox(
        "Code colours",
        options=list(CATEGORY_PALETTES),
        key="category_palette",
        help=(
            "The colours codes get in the reader's margin, the legend, and any "
            "chart coloured by code. Okabe-Ito is the standard palette designed "
            "to stay distinguishable with colour-vision deficiency — worth "
            "choosing for a figure that will be published."
        ),
    )


def init_state() -> None:
    """Initialize Streamlit session state keys."""
    defaults: Dict[str, Any] = {
        "df": None,
        "input_source": "",
        "input_file_path": "",
        "selected_dataset_meta": None,
        "source_folder_path": str(Path.home()),
        "source_file_choice": "",
        "confirm_use_home_folder": False,
        "pii_confirmed": False,
        # Which mode the app is in: "survey" | "interview" | "" (start wizard).
        "app_mode": "",
        # UI skin: "dark" (default) | "light". Toggled in the sidebar, persisted.
        "theme_mode": "dark",
        # Named code-colour palette (see core/theme.CATEGORY_PALETTES), persisted.
        "category_palette": DEFAULT_CATEGORY_PALETTE,
        # Heatmap color scheme (Analysis co-occurrence chart), persisted.
        "heatmap_scheme": "Blue → Orange",
        # Which dataset the confirmation above was given for. The gate re-arms
        # when input_source moves away from this.
        "last_confirmed_source": "",
        # Which dataset the gate is currently armed (displayed) for. Set at
        # arm time regardless of confirmation, so the re-arm fires once per new
        # source instead of on every rerun (which would eat the checkbox tick).
        "pii_gate_armed_for": "",
        "pii_masking_applied": False,
        # The active project store (.qnw). Both the pipeline populate and the
        # Labeling Lab write human codes here, so they must agree on one path;
        # otherwise human codes land in a run-artifact store the next run wipes.
        "active_project_path": "",
        "analyst_name": "",
        "ingestion_mode": "long",          # "long" | "wide"
        "text_column": "",
        "text_columns": [],                # wide mode: question columns
        "question_column": "",
        "question_text_manual": "",        # long/single mode: typed question
        "question_label_overrides_text": "",  # wide mode: header -> full question
        "descriptor_columns": [],          # respondent attributes to carry through
        "id_column": "",
        "analyze_one_question": False,
        "question_filter_value": "",
        "selected_question_value": "",
        "theme_labels_text": "",
        "last_run_output_dir": "",
        "save_project_store": True,
        "engine_type": "transformer",       # "transformer" | "llm"
        "llm_model": "llama3.2:3b",
        "llm_temperature": 0.1,
        "llm_seed": 42,
        "last_error": "",
        "iterative_output_dir": str((PROJECT_ROOT / "output_iterative").resolve()),
        # Iterative labeling lab (card UI) working state.
        "iter_card_idx": 0,
        "iter_labels": {},                 # {response_id: [labels]}
        "iter_notes": {},                  # {response_id: notes}
        "iter_custom_labels": [],          # analyst-added labels not in theme set
        "iter_sample_signature": "",       # detects when to reload sample into state
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

    # Overlay persisted preferences once per session, AFTER defaults so a saved
    # value wins over its default but never over live session state. This is what
    # makes mode/engine/model/name/active-project survive an app restart.
    if not st.session_state.get("settings_loaded"):
        persisted = load_app_settings()
        for key, value in persisted.items():
            if key == "app_mode":
                continue                      # the app opens on Home, not inside the last activity
            if value:
                st.session_state[key] = value
        st.session_state["settings_loaded"] = True
        st.session_state["_persisted_settings"] = {
            k: st.session_state.get(k, "") for k in PERSISTED_KEYS
        }


def maybe_persist_settings() -> None:
    """Write settings when (and only when) a persisted preference changed."""
    current = {k: st.session_state.get(k, "") for k in PERSISTED_KEYS}
    if current != st.session_state.get("_persisted_settings"):
        try:
            save_app_settings(current)
            st.session_state["_persisted_settings"] = current
        except Exception:  # noqa: BLE001 - a broken prefs write must never break the app
            pass


def resume_workspace(workspace: Dict[str, Any]) -> None:
    """Reload the saved session shape: data from its path, mapping, labels.

    The PII gate re-arms because input_source changes to a fresh 'resume:' value —
    the attestation is per-load, never persisted.
    """
    resume_path = Path(str(workspace.get("resume_path", "")))
    st.session_state["df"] = postprocess_loaded_df(load_file_from_path(resume_path))
    st.session_state["input_source"] = f"resume:{resume_path}"
    for key, value in workspace.items():
        if key in ("resume_path", "input_source") or value is None:
            continue
        st.session_state[key] = value


def _nav_cb(page: str) -> None:
    """on_click callback: navigate on the next rerun.

    Used instead of `if st.button(...): st.rerun()` wherever the button lives
    inside a conditional block that won't re-render (e.g. post-run results):
    on_click fires before the rerun, so the navigation lands even though the
    button itself is gone from the next script run.
    """
    st.session_state["nav_target"] = page


def goto(page: str) -> None:
    """Navigate immediately (for buttons in always-rendered blocks)."""
    st.session_state["nav_target"] = page
    st.rerun()
