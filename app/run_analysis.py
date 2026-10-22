"""
Surveys, step 3, "Suggest codes for me to check": run the analysis.

Update 3 (phase 4b, item 4b.5c): the same screen as the desktop. On the page: the way to suggest
codes (default: fast and offline), how long it will take, a quick preview of 50 answers, and one
main button. Folded under More options: the local language model's settings, how sure QualSafe
must be, what to include, saving a project file, and which models are on this computer.

Per `app/__init__`, this module imports only from `core/`, `analysis/`, `exports/`, `app.shared`
and Streamlit, never from `streamlit_app`.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict

import pandas as pd
import streamlit as st
from app.shared.layout import stretch

from app.shared import help_ui
from app.shared.constants import PREVIEW_ROWS, STREAMLIT_OUTPUT_DIR
from app.shared.data import (
    build_general_config, dataframe_is_ready, estimate_runtime_minutes, mapping_is_ready,
    parse_labels_from_text, write_config_snapshot)
from app.shared.io import save_df_for_pipeline
from app.shared.models import render_model_status_panel, render_ollama_setup_panel
from app.shared.state import _nav_cb

ENGINES = {
    "transformer": "Fast, works offline (the usual choice)",
    "llm": "A local language model: slower, and it explains each choice",
}


def render_run_analysis() -> None:
    if not mapping_is_ready():
        # Say what is missing: with the sample open the answers ARE loaded, and "load your answers"
        # sent a person in circles. What is missing is the privacy check and the answers column.
        st.warning("Finish the Load step first: confirm the privacy check, then say which column "
                   "holds the answers." if dataframe_is_ready() else "Load your answers first.")
        st.button("Go to Load", key="run_goto_data", on_click=_nav_cb, args=("Data Setup",))
        return

    # A fresh install has no analysis engine (PyTorch and friends). Pressing Run would only end in a module
    # error, so say so here, in plain words, and point at the button that fixes it.
    from core import engine_install

    if not engine_install.installed():
        st.info("Suggesting codes needs the analysis engine, and it is not installed on this computer yet. "
                "Open Settings, then Models, and press **Install the analysis engine** (about 1 GB, once; "
                "it needs the internet that one time). Coding by hand, and the finished example on Home, "
                "work without it.")
        st.button("Open Models", key="run_goto_models", on_click=_nav_cb, args=("Model Manager",))
        return

    state = st.session_state
    df = state["df"]
    _render_last_run()
    _render_scope()

    st.subheader("Suggest codes")
    state["engine_type"] = st.radio(
        "How should QualSafe suggest codes?", list(ENGINES), index=1 if state.get("engine_type") == "llm" else 0,
        format_func=ENGINES.get, key="run_engine",
        help="The usual choice needs no extra setup. The local language model runs on this computer "
             "through Ollama, so nothing leaves it, and adds a short reason for each choice. If it is "
             "not available, the run uses the usual one.")

    _init_defaults()
    # Said here, next to the estimate, rather than found out mid-run: each model used to be checked
    # only when its own stage first reached it, so a partial download failed once per model.
    _warn_about_missing_models()
    eta = estimate_runtime_minutes(
        n_rows=len(df), use_sentiment=state["use_sentiment"], use_zero_shot=state["use_zero_shot"],
        use_question_theme=state["use_question_theme"], use_question_zero_shot=state["use_question_zero_shot"],
        n_labels=len(parse_labels_from_text(state.get("theme_labels_text", "") or "")) or 6)
    st.caption(f"Estimated time on an ordinary computer: {eta['cpu']}. The first run is slower while "
               "models load.")

    preview_n = min(PREVIEW_ROWS, len(df))
    if st.button(f"Quick preview ({preview_n} answers)", key="run_preview",
                 help="Tries the first answers to show what the output will look like. It is not saved "
                      "as a project."):
        _run_pipeline_ui(df, preview=True)
    if st.button("Run the analysis", key="run_full", type="primary"):
        _run_pipeline_ui(df, preview=False)

    with st.expander("More options"):
        _render_more(eta)


def _init_defaults() -> None:
    state = st.session_state
    for key, value in (("use_sentiment", True), ("use_zero_shot", True), ("use_question_theme", True),
                       ("use_question_zero_shot", False), ("save_project_store", True)):
        state.setdefault(key, value)


def _render_last_run() -> None:
    """Persistent shortcuts after a run (shown every time, unlike the just-ran summary)."""
    last_run = st.session_state.get("last_run_output_dir", "")
    if last_run and Path(last_run).exists():
        with st.container(border=True):
            st.caption(f"Your last run finished: {Path(last_run).name}")
            left, right = st.columns(2)
            left.button("See the results", key="post_run_results", on_click=_nav_cb,
                        args=("Results & Downloads",), **stretch())
            right.button("Explore the analysis", key="post_run_analysis", on_click=_nav_cb,
                         args=("Analysis",), **stretch())


def _render_scope() -> None:
    state = st.session_state
    if state.get("analyze_one_question", False):
        chosen = state.get("question_filter_value", "")
        if chosen:
            st.caption(f"Looking at one question only: {chosen}")
        else:
            st.warning("You asked to look at one question, but none is chosen yet. Choose it under Load, "
                       "More options.")
    else:
        st.caption("Looking at every answer in the file.")


def _render_more(eta: Dict[str, str]) -> None:
    state = st.session_state
    if state["engine_type"] == "llm":
        st.markdown("**The local language model**")
        state["llm_model"] = st.text_input(
            "Model name", value=state.get("llm_model", "llama3.2:3b"),
            help="It must be downloaded first, for example: ollama pull llama3.2:3b")
        state["llm_temperature"] = st.slider("How much it varies", 0.0, 1.0,
                                             float(state.get("llm_temperature", 0.1)), 0.05)
        state["llm_seed"] = st.number_input("Seed", value=int(state.get("llm_seed", 42)), step=1,
                                            help=help_ui.tip("model.seed"))
        render_ollama_setup_panel(state["llm_model"])

    st.markdown("**How sure QualSafe must be**")
    st.caption("Scores from the two ways are not comparable, so each keeps its own limits. You are "
               "changing the limits for the way chosen above.")
    if state["engine_type"] == "llm":
        state["strict_top1_llm"] = st.slider(
            "The best theme must score at least", 0.0, 1.0, float(state.get("strict_top1_llm", 0.70)), 0.05,
            key="w_top1_llm", help=help_ui.tip("code.review_limits"))
        state["strict_margin_llm"] = st.slider(
            "and must beat the next theme by", 0.0, 0.5, float(state.get("strict_margin_llm", 0.10)), 0.01,
            key="w_margin_llm")
        st.caption("The language model's scores run high, so its limits start higher. Provisional.")
    else:
        state["strict_top1_transformer"] = st.slider(
            "The best theme must score at least", 0.0, 1.0,
            float(state.get("strict_top1_transformer", 0.55)), 0.05, key="w_top1_tf",
            help=help_ui.tip("code.review_limits"))
        state["strict_margin_transformer"] = st.slider(
            "and must beat the next theme by", 0.0, 0.5,
            float(state.get("strict_margin_transformer", 0.10)), 0.01, key="w_margin_tf")

    st.markdown("**What to include**")
    state["use_zero_shot"] = st.checkbox(
        "Suggest a code for every answer", value=state["use_zero_shot"],
        help="Codes every answer against your themes: the main step. Turn it off only to look for "
             "groups of similar answers.")
    state["use_sentiment"] = st.checkbox(
        "Also mark each answer positive or negative", value=state["use_sentiment"],
        help="Uses a small model on this computer. Adds a little time.")
    state["use_question_theme"] = st.checkbox(
        "Also find groups of similar answers within each question", value=state["use_question_theme"],
        help="Finds groups separately for each question, so a survey with several questions gets "
             "groups for each.")
    state["use_question_zero_shot"] = st.checkbox(
        "Also suggest codes with each question's own themes", value=state["use_question_zero_shot"],
        help="Uses the themes you gave for particular questions (Themes, More options). One extra pass "
             "per question, so slower.")
    state["save_project_store"] = st.checkbox(
        "Also save a project file (.qnw)", value=state.get("save_project_store", True),
        help="One file with your answers, codes and details that you can reopen or share. Your other "
             "output files are the same either way.")

    st.markdown("**Time**")
    st.caption(f"On an ordinary computer: {eta['cpu']}. With a graphics card: {eta['gpu']} (a guess, "
               "not measured). Suggesting codes runs once for each answer and each theme, so more themes "
               "take more time.")
    st.markdown("**Models on this computer**")
    render_model_status_panel()


def _warn_about_missing_models() -> None:
    """Name any model this run needs and this machine has not got.

    Advisory, not a gate: the Run button stays live because a cache this cannot read must not become
    a new way for an analysis to be refused. The pipeline's own pre-flight is what actually stops the
    run, and it stops it before writing anything.
    """
    from core.model_readiness import describe_missing, remedy

    state = st.session_state
    try:
        missing = describe_missing({
            "models": {
                "embedding_model": state.get("embedding_model", ""),
                "sentiment_model": state.get("sentiment_model", ""),
                "zero_shot_model": state.get("zero_shot_model", ""),
            },
            "sentiment": {"enabled": state.get("use_sentiment", True)},
            "zero_shot": {"enabled": state.get("use_zero_shot", True)},
            "question_zero_shot": {"enabled": state.get("use_question_zero_shot", False)},
        })
    except Exception:  # noqa: BLE001 - an advisory check must not break the page
        return

    if missing:
        st.warning(f"Before this can run: {missing}.\n\n{remedy()}")


def _run_pipeline_ui(df: pd.DataFrame, preview: bool) -> None:
    """Execute a pipeline run from the GUI: full, or a capped quick preview."""
    # Imported here, not at the top: the analysis engine pulls in scikit-learn and SciPy, which cost
    # the app most of its start-up time, and nothing needs them until a run is pressed.
    from analyze_survey import ModelNotDownloadedError, run_pipeline

    try:
        prefix = "preview_" if preview else "run_"
        run_dir = STREAMLIT_OUTPUT_DIR / (prefix + datetime.now().strftime("%Y%m%d_%H%M%S"))
        run_dir.mkdir(parents=True, exist_ok=True)

        work = df.head(PREVIEW_ROWS) if preview else df
        saved_input = save_df_for_pipeline(work, "input_snapshot", run_dir)
        st.session_state["input_file_path"] = str(saved_input.resolve())

        config = build_general_config(run_dir)
        if preview:
            # Cap rows, and never keep a preview as the project of record.
            config.setdefault("preprocessing", {})["max_rows"] = PREVIEW_ROWS
            config.setdefault("output", {})["project_store_path"] = None
        write_config_snapshot(config, run_dir)

        _bar = st.progress(0.0, text="Starting…")

        def progress_cb(fraction, message, _bar=_bar):
            pct = int(min(max(fraction, 0.0), 1.0) * 100)
            _bar.progress(min(max(fraction, 0.0), 1.0), text=f"{message}  ·  {pct}%")

        with st.spinner("Trying the first answers…" if preview else "Suggesting codes…"):
            run_summary = run_pipeline(config, progress_callback=progress_cb)
        _bar.empty()

        if preview:
            st.info(f"This was a preview of the first {run_summary.get('total_responses', '—')} answers. "
                    "It was not saved as a project. Press Run the analysis to do the whole file.")
        else:
            st.session_state["last_run_output_dir"] = str(run_dir.resolve())
            if run_summary.get("project_store"):
                st.session_state["active_project_path"] = str(run_summary["project_store"])
            st.success(f"Finished. The output is in {run_dir}")

        _render_run_summary(run_summary, run_dir, preview)
    except ModelNotDownloadedError as exc:
        st.error(str(exc))
    except Exception as exc:  # noqa: BLE001
        st.session_state["last_error"] = str(exc)
        st.error(f"{'The preview' if preview else 'The analysis'} did not finish: {exc}")


def _render_run_summary(run_summary: Dict[str, Any], run_dir: Path, preview: bool) -> None:
    st.subheader("What the preview found" if preview else "What the analysis found")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Answers", run_summary.get("total_responses", "—"))
    c2.metric("Groups of similar answers", run_summary.get("clusters_found", "—"))
    c3.metric("Questions coded",
              f"{run_summary.get('questions_coded', '—')}/{run_summary.get('questions_total', '—')}")
    c4.metric("Answers unlike the rest", run_summary.get("possible_outliers", 0))
    scored = run_dir / "responses_scored.csv"
    if scored.exists():
        st.caption("A few of the answers, with their suggested codes:")
        st.dataframe(pd.read_csv(scored).head(10), **stretch())
    skipped = run_summary.get("questions_skipped", [])
    if skipped:
        st.warning(f"{len(skipped)} question(s) had no themes and were skipped.")
