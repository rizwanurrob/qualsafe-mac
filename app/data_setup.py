"""
Surveys, step 1 (Load): open a spreadsheet, confirm the privacy check, say which column holds the
answers.

Update 3 (phase 4b, item 4b.5a): the same screen as the desktop's Load step. What a person needs
sits on the page: open a file or the sample, read the privacy check, say which column holds the
answers, go on. Everything else is folded under More options: the other ways to open data, the
layout of the file, the question column, respondent details, and one-question-at-a-time.

Per `app/__init__`, this module imports only from `core/`, `analysis/`, `exports/`, `app.shared`
and Streamlit, never from `streamlit_app`.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st
from app.shared.layout import stretch

from app.shared import help_ui
from app.shared.constants import PROJECT_ROOT, PUBLIC_DATA_DIR, SYNTHETIC_FILE
from app.shared.data import (
    current_question_values, dataframe_is_ready, make_suggested_labels, mapping_is_ready)
from app.shared.io import (
    list_supported_files_in_folder, load_uploaded_file_with_note, postprocess_loaded_df,
    read_with_encoding_note)
from app.shared.projects import active_project_path
from app.shared.state import _nav_cb
from app.shared.widgets import render_pii_gate, reset_pii_gate_if_source_changed
from core.ux import columns as column_hints
from tools.public_dataset_utils import PUBLIC_DATASET_OPTIONS, download_public_dataset

LONG, WIDE = "long", "wide"
LAYOUTS = {
    LONG: "One row per answer (long)",
    WIDE: "One column per question (wide)",
}


def render_data_setup() -> None:
    _render_open()
    if not dataframe_is_ready():
        st.info("No answers loaded yet. Open a spreadsheet, or use the sample answers.")
        return

    # A newly loaded file invalidates any confirmation given for the previous one.
    reset_pii_gate_if_source_changed()
    df = st.session_state["df"]
    st.write(f"**{st.session_state.get('input_source', '')}**: {len(df):,} rows, {len(df.columns)} columns")
    st.dataframe(df.head(10), **stretch())

    if not render_pii_gate(df):
        st.info("Confirm the privacy check above to choose the answers column.")
        st.stop()

    # Masking may have replaced the frame; read it again before mapping.
    _render_mapping(st.session_state["df"])


# -- opening data --------------------------------------------------------------------------------

def _render_open() -> None:
    st.subheader("Your answers")
    uploaded = st.file_uploader(
        "Open a spreadsheet", type=["csv", "xlsx", "xls", "json", "sav"],
        help="A CSV, Excel, JSON or SPSS file. It is read, never changed.")
    if uploaded is not None:
        signature = f"{uploaded.name}:{uploaded.size}"
        if st.session_state.get("_loaded_upload") != signature:       # once for each new file
            try:
                frame, encoding_note = load_uploaded_file_with_note(uploaded)
                st.session_state["df"] = postprocess_loaded_df(frame)
                st.session_state["input_source"] = f"upload:{uploaded.name}"
                st.session_state["_loaded_upload"] = signature
                st.session_state["_upload_encoding_note"] = encoding_note
            except Exception as exc:  # noqa: BLE001
                st.error(f"Could not open that file: {exc}")
        # Not UTF-8: say so, every time the page is drawn, not only on the run that read it. A wrong
        # guess does not fail, it turns every apostrophe into nonsense nobody notices until it is quoted.
        if st.session_state.get("_upload_encoding_note"):
            st.warning(st.session_state["_upload_encoding_note"])
    if st.button("Use the sample answers", key="ds_sample",
                 help="A made-up survey of 40 student answers, with a matching list of themes, to follow "
                      "the steps with. For a finished example, use Try the sample survey on Home."):
        _open_sample()
    _render_other_ways()


def _open_sample() -> None:
    if not SYNTHETIC_FILE.exists():
        st.error(f"The sample file is missing: {SYNTHETIC_FILE}")
        return
    st.session_state["df"] = pd.read_csv(SYNTHETIC_FILE)
    st.session_state["input_source"] = "synthetic_sample"
    if not st.session_state.get("theme_labels_text", "").strip():
        st.session_state["theme_labels_text"] = "\n".join(
            make_suggested_labels()["Education / Student Experience"])


def _render_other_ways() -> None:
    with st.expander("Other ways to open data"):
        st.markdown("**From a folder on this computer**")
        folder_mode = st.radio(
            "Folder", ["Use my Home folder", "Use another folder"], horizontal=True,
            key="ds_folder_mode", help="Browse files already here, instead of uploading a copy.")
        if folder_mode == "Use my Home folder":
            st.session_state["confirm_use_home_folder"] = st.checkbox(
                "I want to browse my Home folder",
                value=st.session_state.get("confirm_use_home_folder", False))
            if st.session_state["confirm_use_home_folder"]:
                st.session_state["source_folder_path"] = str(Path.home())
        else:
            st.session_state["source_folder_path"] = st.text_input(
                "Folder path", value=st.session_state.get("source_folder_path", str(PROJECT_ROOT)),
                help="For example C:\\Users\\yourname\\Documents\\SurveyFiles")
        _render_folder_files()

        st.markdown("**A public sample**")
        options = {opt.title: opt.key for opt in PUBLIC_DATASET_OPTIONS}
        title = st.selectbox("Public sample", list(options), key="ds_public_choice")
        if st.button("Download and open it", key="ds_public"):
            _open_public(options[title])

        st.markdown("**From a project file**")
        st.caption("Have a project file but not the spreadsheet? The answers can be rebuilt from the "
                   "project chosen under Settings, Project and backups.")
        store = active_project_path()
        if store is None or not Path(store).exists():
            st.caption("No project chosen yet.")
        elif st.button("Rebuild the answers from the project", key="rebuild_from_store"):
            _rebuild_from_project(store)


def _render_folder_files() -> None:
    folder = Path(st.session_state.get("source_folder_path", "")).expanduser()
    files = list_supported_files_in_folder(folder)
    if not files:
        st.caption("No CSV, Excel or JSON files in that folder yet." if folder.is_dir()
                   else "That folder is not available.")
        return
    names = [f.name for f in files]
    current = st.session_state.get("source_file_choice", "")
    st.session_state["source_file_choice"] = st.selectbox(
        "File in that folder", names, index=names.index(current) if current in names else 0,
        key="source_file_choice_box")
    if st.button("Open that file", key="ds_folder_open"):
        try:
            path = folder / st.session_state["source_file_choice"]
            frame, encoding_note = read_with_encoding_note(path)
            st.session_state["df"] = postprocess_loaded_df(frame)
            st.session_state["input_source"] = f"folder:{path}"
            # Not UTF-8: say so. A wrong guess does not fail, it turns every apostrophe into
            # nonsense that nobody notices until it is quoted in a paper.
            if encoding_note:
                st.warning(encoding_note)
        except Exception as exc:  # noqa: BLE001
            st.error(f"Could not open that file: {exc}")


def _open_public(option_key: str) -> None:
    try:
        PUBLIC_DATA_DIR.mkdir(parents=True, exist_ok=True)
        meta = download_public_dataset(option_key=option_key, target_dir=PUBLIC_DATA_DIR)
        frame, encoding_note = read_with_encoding_note(Path(meta["downloaded_file"]))
        st.session_state["df"] = frame
        st.session_state["input_source"] = f"public:{meta['dataset_title']}"
        st.session_state["selected_dataset_meta"] = meta
        if encoding_note:
            st.warning(encoding_note)
        st.caption(f"Source: {meta['record_url']}")
    except Exception as exc:  # noqa: BLE001
        st.error(f"Could not download it: {exc}")


def _rebuild_from_project(store) -> None:
    try:
        from core.reconstruct import (
            QUESTION_COL, RESPONSE_ID_COL, TEXT_COL, dataframe_from_store, descriptor_columns)

        rebuilt = dataframe_from_store(store)
        if rebuilt.empty:
            st.warning("That project has no survey answers to rebuild.")
            return
        state = st.session_state
        state["df"] = rebuilt
        state["ingestion_mode"] = LONG
        state["text_column"] = TEXT_COL
        questions = [q for q in rebuilt[QUESTION_COL].unique() if q]
        state["question_column"] = QUESTION_COL if len(set(questions)) > 1 else ""
        if not state["question_column"] and questions:
            state["question_text_manual"] = str(questions[0])
        state["id_column"] = RESPONSE_ID_COL
        state["descriptor_columns"] = descriptor_columns(rebuilt)
        # A fresh source, so the privacy check is asked again: this is real response text.
        state["input_source"] = f"project:{Path(store).parent.name}"
    except Exception as exc:  # noqa: BLE001
        st.error(f"Could not rebuild the answers: {exc}")


# -- which column holds the answers --------------------------------------------------------------

def _render_mapping(df: pd.DataFrame) -> None:
    state = st.session_state
    columns = list(df.columns)
    _render_suggestion(df)

    st.subheader("Where are the answers?")
    if state.get("ingestion_mode", LONG) == WIDE:
        state["text_columns"] = st.multiselect(
            "Answers are in these columns (each column is one question)", columns,
            default=[c for c in state.get("text_columns", []) if c in columns], key="ds_text_columns")
    else:
        current = state.get("text_column", "")
        # No column is chosen for the person: the first one is often the question or an id, and
        # analysing that "succeeds". They choose, or press Use these columns above.
        picked = st.selectbox(
            "Answers are in column", columns, index=columns.index(current) if current in columns else None,
            placeholder="Choose the column with the written answers", key="map_text_col")
        state["text_column"] = picked or ""
        if picked:
            st.caption(f"The first one reads: {column_hints.sample_of(df, picked) or '(empty)'}")

    with st.expander("More options"):
        _render_more_mapping(df, columns)

    if mapping_is_ready():
        st.button("Next: choose your themes", key="next_theme_setup", type="primary",
                  on_click=_nav_cb, args=("Theme Setup",))
    else:
        st.caption("Choose the column that holds the written answers to go on.")


def _render_suggestion(df: pd.DataFrame) -> None:
    """Offer a guess at the columns. Never applied until the person says so."""
    suggestion = column_hints.suggest_columns(df)
    state = st.session_state
    if suggestion is None or state.get("_suggestion_used") == state.get("input_source"):
        return
    st.info("QualSafe thinks:\n\n" + "\n".join(f"- {line}" for line in suggestion.describe()))
    if st.button("Use these columns", key="ds_use_suggestion",
                 help="Fills in the columns below. Nothing is chosen until you press this."):
        state["ingestion_mode"] = suggestion.shape
        if suggestion.shape == WIDE:
            state["text_columns"] = list(suggestion.answers)
        else:
            state["text_column"] = suggestion.answers[0]
            state["question_column"] = suggestion.question
        if suggestion.respondent:
            state["id_column"] = suggestion.respondent
        state["_suggestion_used"] = state.get("input_source")
        # The widgets below hold their own value: put the suggestion into them as well.
        for key in ("map_text_col", "ds_text_columns", "map_question_col", "map_id_col", "ds_layout"):
            state.pop(key, None)
        st.rerun()


def _render_more_mapping(df: pd.DataFrame, columns: list) -> None:
    state = st.session_state
    layout = st.radio("How is the file organised?", list(LAYOUTS.values()), horizontal=True, key="ds_layout",
                      index=1 if state.get("ingestion_mode", LONG) == WIDE else 0,
                      help="One row per answer, with an optional column naming the question; or one "
                           "column for each question.")
    state["ingestion_mode"] = WIDE if layout == LAYOUTS[WIDE] else LONG

    if state["ingestion_mode"] == WIDE:
        state["question_label_overrides_text"] = st.text_area(
            "Full wording for question headers (optional)",
            value=state.get("question_label_overrides_text", ""), height=90,
            placeholder="Q1_success :: What would make this a successful year for you?",
            help="One per line, as ColumnName :: Full question text?")
    else:
        options = ["(none: I will type the question)"] + columns
        current = state.get("question_column", "")
        picked = st.selectbox("Question column", options, key="map_question_col",
                              index=options.index(current) if current in options else 0,
                              help=help_ui.tip("survey.question_column"))
        state["question_column"] = "" if picked == options[0] else picked
        if not state["question_column"]:
            state["question_text_manual"] = st.text_input(
                "Question", value=state.get("question_text_manual", ""),
                placeholder="What would make this year successful for you?",
                help=help_ui.tip("survey.question_label"))

    ids = [""] + columns
    current_id = state.get("id_column", "")
    state["id_column"] = st.selectbox("Respondent ID column (optional)", ids, key="map_id_col",
                                      index=ids.index(current_id) if current_id in ids else 0,
                                      help=help_ui.tip("survey.respondent_id"))

    used = set(filter(None, (list(state.get("text_columns", [])) if state["ingestion_mode"] == WIDE
                             else [state.get("text_column", "")])
                      + [state.get("question_column", ""), state.get("id_column", "")]))
    detail_options = [c for c in columns if c not in used]
    state["descriptor_columns"] = st.multiselect(
        "Respondent details to keep", detail_options,
        default=[c for c in state.get("descriptor_columns", []) if c in detail_options],
        help=help_ui.tip("survey.details"))

    values = current_question_values()
    if len(values) > 1:
        state["analyze_one_question"] = st.checkbox(
            "Look at one question at a time", value=state.get("analyze_one_question", False),
            help="Recommended when the file has several questions.")
        if state["analyze_one_question"]:
            current_q = state.get("question_filter_value", "")
            state["question_filter_value"] = st.selectbox(
                "Which question", values, index=values.index(current_q) if current_q in values else 0)
    else:
        state["analyze_one_question"] = False
