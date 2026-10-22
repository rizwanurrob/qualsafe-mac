#!/usr/bin/env python
"""
QualSafe — Streamlit shell.

This file used to be the whole GUI (~3,700 lines). As of v4 Phase 0.1 it is only
the *shell*: terminal logging, navigation, and `main()`. Every page lives in its
own module under `app/`, and the helpers they share live under `app/shared/`.

Why the split: the v4 corpus features (a document library, a reader with coding
stripes, the search workbench) could not be added responsibly to a single
3,700-line module, and a UI layer that can never be broken up can never be
replaced either. The rule that keeps it that way is in `app/__init__`: **a page
module imports only from `core/`, `analysis/`, `exports/`, `app.shared`, and
Streamlit — never from this shell.** Anything a page needs from here is passed in
as an argument (see `_render_search_page`).

Run with:  streamlit run streamlit_app.py
"""

from __future__ import annotations


def _setup_terminal_logging() -> None:
    """Make the pipeline's stage banners visible in the launching terminal.

    Streamlit doesn't configure the root logger, so `LOGGER.info(...)` from the
    pipeline (including the `[i/n] stage` banners) would be swallowed, leaving the
    terminal with only raw tqdm bars. Attach a simple stream handler once, so a
    user watching the console can see which stage a slow run is on. Guarded so
    Streamlit's per-interaction reruns don't stack handlers.
    """
    import logging

    logger = logging.getLogger("survey_nlp")
    if not any(getattr(h, "_qnw_console", False) for h in logger.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s | %(message)s", "%H:%M:%S"))
        handler._qnw_console = True  # type: ignore[attr-defined]
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False


_setup_terminal_logging()

import streamlit as st  # noqa: E402

# Importing `app` arms offline mode before any page pulls in the ML stack.
from app.alt_survey_flow import render_alt_survey_flow  # noqa: E402
from app.analysis_page import render_analysis  # noqa: E402
from app.codebook import render_codebook  # noqa: E402
from app.data_management import render_data_management  # noqa: E402
from app.data_setup import render_data_setup  # noqa: E402
from app.documents_page import render_documents_page  # noqa: E402
from app.help_page import render_help_and_troubleshooting  # noqa: E402
from app.charts_page import render_charts_page  # noqa: E402
from app.data_charts_page import render_data_charts_page  # noqa: E402
from app.model_page import render_model_page  # noqa: E402
from app.labeling_lab import render_iterative_labeling_lab  # noqa: E402
from app.model_manager import render_model_manager  # noqa: E402
from app.query_page import render_query_page  # noqa: E402
from app.results import render_results_and_downloads  # noqa: E402
from app.run_analysis import render_run_analysis  # noqa: E402
from app.search_page import render_search_page  # noqa: E402
from app.shared.constants import APP_TITLE  # noqa: E402
from app.shared import help_ui  # noqa: E402
from app.shared.layout import stretch  # noqa: E402
from core.chartbuilder.export import warm_renderer  # noqa: E402
from app.shared.projects import active_project_path  # noqa: E402
from app.shared.state import (  # noqa: E402
    apply_brand_theme_css, init_state, maybe_persist_settings,
    render_appearance_control,
)
from app.shared.widgets import render_chart_export, render_sidebar_status  # noqa: E402
from app.theme_setup import render_theme_setup  # noqa: E402
from app.home_page import render_home  # noqa: E402
from app.settings_page import render_settings  # noqa: E402
from app.shared import nav, progress_state  # noqa: E402
from core.theme import activity_web_css, home_web_css  # noqa: E402
from core.ux import activities, coding_choices  # noqa: E402
from interview_ui import render_interview_mode  # noqa: E402

# ── Backwards-compatible re-exports ─────────────────────────────────────────
# These moved into `app/shared/` but are still imported as `streamlit_app.X` by
# the test suite (and possibly by a user's own script). Re-exported so the split
# is invisible from outside; new code should import from `app.shared.*` directly.
from app.shared.data import (  # noqa: E402,F401
    build_saved_sample, load_coding_sample_df, make_suggested_labels,
)
from app.shared.io import (  # noqa: E402,F401
    _read_sav, delete_paths, describe_working_files, legacy_session_input_files,
    save_df_for_pipeline,
)
from app.shared.widgets import reset_pii_gate_if_source_changed  # noqa: E402,F401

def _documents_part() -> str:
    """Interviews, step 1 adds transcripts; step 2 reads and codes them."""
    if nav.current_activity() == "interviews":
        return "add" if nav.step_of("interviews") == "add" else "code"
    return "all"


def _render_search_page() -> None:
    """Adapter to the Search page module (v4, Phase 0.1/1.1).

    Page modules never import this shell — the shell hands them what they need.
    Here that's the active project and the shared chart-export widget.
    """
    render_search_page(active_project_path(), chart_export=render_chart_export)


#: Every screen the web app has, by its page name. Which activity and step shows it is
#: `core/ux/activities.py`; Settings and Help show the rest.
_PAGE_RENDERERS = {
    "Data Setup": lambda: render_data_setup(),
    "Theme Setup": lambda: render_theme_setup(),
    "Run Analysis": lambda: render_run_analysis(),
    "Interview Mode": lambda: render_interview_mode(),
    "Analysis": lambda: render_analysis(),
    "Codebook": lambda: render_codebook(),
    "Iterative Labeling Lab": lambda: render_iterative_labeling_lab(),
    "Alt Survey Flow": lambda: render_alt_survey_flow(),
    "Results & Downloads": lambda: render_results_and_downloads(),
    "Documents": lambda: render_documents_page(active_project_path(), part=_documents_part()),
    "Chart Builder": lambda: render_charts_page(
        active_project_path(), chart_export=render_chart_export),
    "Data Charts": lambda: render_data_charts_page(),
    "Modelling": lambda: render_model_page(active_project_path()),
    "Search": lambda: _render_search_page(),
    "Query & Synthesis": lambda: render_query_page(active_project_path()),
    "Data Management": lambda: render_data_management(),
    "Model Manager": lambda: render_model_manager(),
    "Help & Troubleshooting": lambda: render_help_and_troubleshooting(),
}


# -- the shell: Home, an activity's steps, Settings, Help ---------------------------------------

def _step_label(activity: activities.Activity, step: activities.Step) -> str:
    return f"{activity.step_number(step.key)} {step.title}"


def _sync_widget(key: str, value: str) -> None:
    """Make a keyed widget show `value` before it is drawn (a button elsewhere may have moved us)."""
    st.session_state[key] = value


def _on_step_picked(activity_key: str) -> None:
    activity = activities.get(activity_key)
    label = st.session_state.get(f"rail_{activity_key}")
    for step in activity.steps:
        if _step_label(activity, step) == label:
            st.session_state[f"step_{activity_key}"] = step.key


def _render_sidebar(mode: str, activity: "activities.Activity | None") -> None:
    sidebar = st.sidebar
    if sidebar.button("⌂ Home", key="nav_home", **stretch()):
        nav.go_home()
        st.rerun()
    if activity is not None:
        sidebar.markdown(f"**{activity.title}**")
        labels = [_step_label(activity, s) for s in activity.steps]
        rail = f"rail_{activity.key}"
        _sync_widget(rail, _step_label(activity, activity.step(nav.step_of(activity.key))))
        sidebar.radio("Steps", labels, key=rail, on_change=_on_step_picked, args=(activity.key,))
    if activity is not None:
        step = activity.step(nav.step_of(activity.key))
        if sidebar.button("Help for this step", key="nav_step_help", **stretch()):
            nav.go_help(f"{activity.key}-{step.key}")
            st.rerun()
    left, right = sidebar.columns(2)
    if left.button("Settings", key="nav_settings", **stretch()):
        nav.go_settings()
        st.rerun()
    if right.button("Help", key="nav_help", **stretch()):
        nav.go_help()
        st.rerun()
    render_sidebar_status(activity.key if activity is not None else "")


def _on_screen_picked(activity_key: str, step_key: str, widget: str) -> None:
    nav.set_screen(activity_key, step_key, st.session_state[widget])


def _render_code_step(activity: "activities.Activity", step: "activities.Step") -> None:
    """Surveys, step 3: choose how to code the answers, then the screen for that way.

    Same three choices and words as the desktop (`core/ux/coding_choices.py`). Suggesting codes is
    Run Analysis; a written codebook is Alt Survey Flow; coding by hand is the Labeling Lab."""
    st.markdown(f'<p class="qs-intro">{step.intro}</p>', unsafe_allow_html=True)
    if st.session_state.get("code_choice") not in coding_choices.KEYS:
        st.session_state["code_choice"] = "suggest"
    st.radio("How do you want to code the answers?", coding_choices.KEYS, key="code_choice",
             format_func=coding_choices.title,
             captions=[when for _k, _t, when in coding_choices.CHOICES])
    page = coding_choices.WEB_PAGE[st.session_state["code_choice"]]
    nav.set_screen(activity.key, step.key, page)
    _PAGE_RENDERERS[page]()


def _render_step(activity: "activities.Activity", step: "activities.Step") -> None:
    """One step: its one-line intro, its screen (or a choice of a few), and More tools."""
    if (activity.key, step.key) == ("surveys", "code"):
        _render_code_step(activity, step)
        return
    st.markdown(f'<p class="qs-intro">{step.intro}</p>', unsafe_allow_html=True)
    main, more = nav.screens(activity.key, step.key)
    current = nav.current_screen(activity.key, step.key)
    if len(main) > 1:
        pick = f"pick_{activity.key}_{step.key}"
        _sync_widget(pick, current if current in main else main[0])
        st.radio("Screen", main, key=pick, horizontal=True, label_visibility="collapsed",
                 format_func=activities.web_screen_title,
                 on_change=_on_screen_picked, args=(activity.key, step.key, pick))
    if more:
        extra = f"more_{activity.key}_{step.key}"
        with st.expander("More tools", expanded=current in more):
            _sync_widget(extra, current if current in more else None)
            st.selectbox("Open a tool", more, key=extra, index=None, placeholder="Pick a tool",
                         format_func=activities.web_screen_title,
                         on_change=_on_screen_picked, args=(activity.key, step.key, extra))
    renderer = _PAGE_RENDERERS.get(current)
    if renderer is None:
        st.write("This screen is not available.")
    else:
        renderer()


def main() -> None:
    st.set_page_config(page_title=APP_TITLE, layout="wide")
    init_state()
    nav.init_nav()
    progress_state.migrate_once()
    nav.apply_nav_target()          # before any widget: a Continue button may have set a target
    apply_brand_theme_css()
    mode = st.session_state.get("theme_mode", "dark")

    view = nav.view()
    activity = activities.get(nav.current_activity()) if nav.current_activity() else None
    st.markdown(activity_web_css(activity.key if activity else "", mode), unsafe_allow_html=True)
    if view == nav.HOME:
        st.markdown(home_web_css(mode), unsafe_allow_html=True)
    st.markdown(f'<div class="qs-band">{nav.breadcrumb()}</div>', unsafe_allow_html=True)
    _render_sidebar(mode, activity)

    if view == nav.HOME:
        render_home()
    elif view == nav.SETTINGS:
        render_settings()
    elif view == nav.HELP:
        render_help_and_troubleshooting()
    elif activity is not None:
        help_ui.render_tour(activity.key, force=st.session_state.get("tour_replay") == activity.key)
        _render_step(activity, activity.step(nav.step_of(activity.key)))
    else:
        nav.go_home()
        st.rerun()

    maybe_persist_settings()
    progress_state.maybe_persist_progress()
    warm_renderer()                 # last, so the page is drawn first: the first chart is then not slow


if __name__ == "__main__":
    main()
