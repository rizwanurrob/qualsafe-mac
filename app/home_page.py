"""Home: three activities, and the ways back into your work (Update 3, phase 4b).

Replaces the "What are you analyzing?" wizard. Each activity is a card in its own colour with one
sentence on what it is for and one button. Beneath them: the sample, the guide, and picking up the
last session. Nothing here runs an analysis; it only moves you somewhere.

Per `app/__init__`, this module imports only from `core/`, `analysis/`, `exports/`, `app.shared`
and Streamlit, never from the shell.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st
from app.shared.layout import stretch

from app.shared import nav, progress_state
from app.shared.constants import STREAMLIT_OUTPUT_DIR, SYNTHETIC_FILE
from app.shared.data import make_suggested_labels
from core.ux import activities


def render_home() -> None:
    st.header("What would you like to do?")
    st.caption("Everything stays on this computer.")

    saved = progress_state.summaries()
    columns = st.columns(len(activities.ACTIVITIES))
    for column, activity in zip(columns, activities.ACTIVITIES):
        with column, st.container(border=True, key=f"card_{activity.key}"):
            st.subheader(activity.title)
            st.write(activity.tagline)
            if st.button(f"Start {activity.title}", key=f"start_{activity.key}", type="primary",
                         **stretch()):
                nav.go_activity(activity.key)
                st.rerun()
            if activity.key in saved:
                _render_continue(activity.key, saved[activity.key])

    st.divider()
    st.markdown("**New here?**")
    first, second, third = st.columns(3)
    # The same button, and the same result, as on the desktop: a finished example you can read at once.
    if first.button("Try the sample survey", key="home_sample", **stretch(),
                    help="Opens a finished example: 40 made-up student answers that are already coded, so "
                         "you can look at the results. Nothing to install and nothing to run."):
        _open_demo_project()
    if second.button("Walk through the steps", key="home_walkthrough", **stretch(),
                     help="Opens the same 40 answers, not yet coded, with a list of themes, so you can follow "
                          "Load, Themes, Code, Explore and Report. Suggesting codes needs the analysis engine."):
        _open_sample_survey()
    if third.button("Read the short guide", key="home_guide", **stretch()):
        nav.go_help()
        st.rerun()


def _render_continue(activity_key: str, saved) -> None:
    """Where you were in this activity, and a way back to it (or to start again)."""
    name = f": {saved.name}" if saved.name else ""
    st.caption(f"Continue{name}")
    st.caption(saved.detail)
    if saved.missing:
        st.caption("⚠ A file you were using has moved. Your place is kept; open the file again.")
    left, right = st.columns(2)
    if left.button("Continue", key=f"continue_{activity_key}", **stretch()):
        progress_state.continue_activity(activity_key)
        st.rerun()
    if right.button("Start over", key=f"startover_{activity_key}", **stretch(),
                    help="Forgets where you were in this activity. Your files and projects are not touched."):
        progress_state.start_over(activity_key)
        st.rerun()


def _open_sample_survey() -> None:
    try:
        st.session_state["df"] = pd.read_csv(SYNTHETIC_FILE)
        st.session_state["input_source"] = "synthetic_sample"
        if not st.session_state.get("theme_labels_text", "").strip():
            packs = make_suggested_labels()
            st.session_state["theme_labels_text"] = "\n".join(packs["Education / Student Experience"])
        nav.go_activity("surveys", "load")
        st.rerun()
    except Exception as exc:  # noqa: BLE001
        st.error(f"Could not open the sample: {exc}")


def _open_demo_project() -> None:
    try:
        from core.sample_project import build_sample_project, default_sample_path

        out = default_sample_path(STREAMLIT_OUTPUT_DIR)
        out.parent.mkdir(parents=True, exist_ok=True)
        build_sample_project(SYNTHETIC_FILE, out)
        st.session_state["active_project_path"] = str(out)
        nav.go_activity("surveys", "explore", screen="Analysis")
        st.rerun()
    except Exception as exc:  # noqa: BLE001
        st.error(f"Could not build the demo project: {exc}")
