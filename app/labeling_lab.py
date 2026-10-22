"""
Human-in-the-loop card coding, with autosave.

Extracted from the former monolithic `streamlit_app.py` (v4, Phase 0.1).
Per `app/__init__`, this module imports only from `core/`, `analysis/`,
`exports/`, `app.shared`, and Streamlit — never from `streamlit_app`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List
import pandas as pd
import streamlit as st
from app.shared.layout import stretch

from app.shared.constants import MIN_ITERATIVE_LABELED_ROWS
from app.shared.io import save_df_for_pipeline
from app.shared.data import build_iterative_config, build_saved_sample, current_question_values, load_coding_sample_df, mapping_is_ready, parse_labels_from_text, parse_multilabel_value, resolve_long_dataframe
from app.shared.projects import _record_codings_to_active_project


def _load_sample_into_state(coding_df: pd.DataFrame) -> None:
    """Populate card state (iter_labels/iter_notes) from a coding sample, and
    clear any lingering per-response widget keys from a previous sample."""
    for key in [k for k in list(st.session_state.keys())
                if k.startswith(("iter_ms_", "iter_notes_", "iter_new_"))]:
        del st.session_state[key]
    labels: Dict[str, List[str]] = {}
    notes: Dict[str, str] = {}
    for _, row in coding_df.iterrows():
        rid = str(row.get("response_id", ""))
        labels[rid] = parse_multilabel_value(row.get("human_labels", ""))
        notes[rid] = str(row.get("coder_notes", "") or "")
    st.session_state["iter_labels"] = labels
    st.session_state["iter_notes"] = notes
    st.session_state["iter_card_idx"] = 0
    # Seed the autosave signature with the just-loaded state so the first rerun
    # doesn't do a pointless rewrite of the file we just read.
    st.session_state["iter_autosave_sig"] = json.dumps([labels, notes], sort_keys=True, default=str)


def _autosave_coding_sample(coding_df: pd.DataFrame, iterative_dir: Path) -> bool:
    """Write coding progress to disk whenever it changed (v3.8: item 8.1).

    Until now codes lived only in session state between clicks of the save
    button — a Streamlit restart or a closed tab silently discarded every card
    since the last save. Now every card action lands on disk; the CSV is the
    source of truth the Lab reloads from, so a crash costs nothing.

    Returns True when a write happened. Signature-guarded so untouched reruns
    don't rewrite the file, and failures never interrupt coding (the manual save
    still exists and will surface a real disk problem).
    """
    signature = json.dumps(
        [st.session_state.get("iter_labels", {}), st.session_state.get("iter_notes", {})],
        sort_keys=True, default=str)
    if signature == st.session_state.get("iter_autosave_sig"):
        return False
    try:
        out = build_saved_sample(coding_df, st.session_state.get("iter_labels", {}),
                                 st.session_state.get("iter_notes", {}))
        out.to_csv(iterative_dir / "coding_sample.csv", index=False)
        st.session_state["iter_autosave_sig"] = signature
        return True
    except Exception:  # noqa: BLE001 - autosave must never break the coding flow
        return False


def render_iterative_labeling_lab() -> None:
    """
    In-app human-in-the-loop coding, one response at a time (card view).

    Why this exists:
    - Full response text is readable (not truncated in a grid cell).
    - Labels are picked from the current theme set (multi-select) or added.
    - Removes CSV-editing friction for non-technical coders.
    """
    st.header("Iterative Labeling Lab")
    st.caption(
        "Human-in-the-loop coding: sample rows → code each response → validate coverage → train → discover themes."
    )

    if not mapping_is_ready():
        st.warning("Load data and map columns first in Data Setup.")
        return

    # Resolve to long shape so wide-format data works here too.
    try:
        long_df, text_col, question_col, id_col, _descriptors = resolve_long_dataframe()
    except ValueError as exc:
        st.warning(str(exc))
        return

    question_values = current_question_values() or ["All Responses"]

    cfg_col1, cfg_col2, cfg_col3 = st.columns(3)
    with cfg_col1:
        sel = st.session_state.get("selected_question_value", "")
        st.session_state["selected_question_value"] = st.selectbox(
            "Question value",
            options=question_values,
            index=question_values.index(sel) if sel in question_values else 0,
            key="iter_question_select",
            help="Type inside this dropdown to search.",
        )
    with cfg_col2:
        iterative_sample_size = st.selectbox(
            "Sample size", options=[30, 20, 10], index=0, key="iter_sample_size",
            help="How many responses you'll hand-code. 30 gives a usable first "
                 "agreement estimate; 10 is enough for a quick trial round.")
    with cfg_col3:
        st.session_state["iterative_output_dir"] = st.text_input(
            "Iterative output folder",
            value=st.session_state["iterative_output_dir"],
            key="iter_output_dir_input",
            help="Where the coding sample and training outputs live. This folder is "
                 "durable — your hand-coded sample is read back across sessions.",
        )

    st.markdown("### Step 1 · Create / refresh coding sample")
    st.caption("Creates a random `coding_sample.csv` for the selected question.")
    if st.button("Create coding sample", key="iter_create_sample"):
        try:
            # Snapshot lives with output_iterative/'s durable artifacts:
            # coding_sample.csv is read back across sessions and its config points
            # at this input path, so it must not be treated as run scrap.
            saved_input = save_df_for_pipeline(
                long_df, "iterative_input", Path(st.session_state["iterative_output_dir"])
            )
            iterative_cfg = build_iterative_config(
                input_csv_path=saved_input,
                question_value=st.session_state["selected_question_value"],
                sample_size=int(iterative_sample_size),
                text_column=text_col,
                question_column=question_col,
                id_column=id_col,
            )
            from iterative_supervised_thematic import create_coding_sample   # heavy: loaded when used
            create_coding_sample(iterative_cfg)
            st.session_state["iter_sample_signature"] = ""  # force reload into card state
            st.success("Coding sample created.")
        except Exception as exc:  # noqa: BLE001
            st.error(f"Could not create sample: {exc}")

    iterative_dir = Path(st.session_state["iterative_output_dir"])
    coding_df = load_coding_sample_df(iterative_dir)
    if coding_df.empty:
        st.info("No coding sample yet. Create one above.")
        return
    coding_df = coding_df.assign(response_id=coding_df["response_id"].astype(str))

    # Load the sample into card state whenever it changes (new sample / question).
    signature = f"{iterative_dir}|{len(coding_df)}|{st.session_state.get('selected_question_value', '')}"
    if st.session_state.get("iter_sample_signature", "") != signature:
        _load_sample_into_state(coding_df)
        st.session_state["iter_sample_signature"] = signature

    # ── Step 2: card-based coding ────────────────────────────────────────────
    st.markdown("### Step 2 · Code each response")
    theme_labels = parse_labels_from_text(st.session_state.get("theme_labels_text", ""))
    applied: set = set()
    for vals in st.session_state["iter_labels"].values():
        applied.update(vals)
    label_universe = sorted(set(theme_labels) | applied | set(st.session_state.get("iter_custom_labels", [])))
    if not theme_labels:
        st.caption("Tip: define theme labels in **Theme Setup** to pick from them here (you can still add labels below).")

    rids = coding_df["response_id"].tolist()
    n = len(rids)
    idx = max(0, min(int(st.session_state.get("iter_card_idx", 0)), n - 1))
    st.session_state["iter_card_idx"] = idx
    rid = rids[idx]
    row = coding_df.iloc[idx]

    labeled_count = sum(1 for v in st.session_state["iter_labels"].values() if v)
    st.progress((idx + 1) / n)
    st.caption(f"Response **{idx + 1} of {n}**  ·  {labeled_count}/{n} coded")

    with st.container(border=True):
        st.markdown(f"**Response ID:** `{rid}`")
        q_text = str(row.get("question_text", "") or "")
        if q_text:
            st.markdown(f"**Question:** {q_text}")
        st.markdown("**Response**")
        st.write(str(row.get("response_text", "") or ""))

        st.divider()

        # Labels multiselect — initialize the widget key before creating it so
        # navigation/reruns preserve selections; mirror into iter_labels (the
        # source of truth for progress across all cards).
        ms_key = f"iter_ms_{rid}"
        if ms_key not in st.session_state:
            st.session_state[ms_key] = st.session_state["iter_labels"].get(rid, [])
        options = sorted(set(label_universe) | set(st.session_state[ms_key]))
        selected = st.multiselect(
            "Themes / codes for this response",
            options=options,
            key=ms_key,
            help="Pick from your theme labels, or add a new one below.",
        )
        st.session_state["iter_labels"][rid] = selected

        add_col1, add_col2 = st.columns([4, 1])
        with add_col1:
            new_label = st.text_input(
                "Add a new label", value="", key=f"iter_new_{rid}",
                placeholder="Type a new code, click Add, then select it above",
                label_visibility="collapsed",
            )
        with add_col2:
            if st.button("Add label", key=f"iter_add_{rid}"):
                nl = (new_label or "").strip()
                if nl and nl not in st.session_state["iter_custom_labels"]:
                    st.session_state["iter_custom_labels"].append(nl)
                    st.rerun()

        notes_key = f"iter_notes_{rid}"
        if notes_key not in st.session_state:
            st.session_state[notes_key] = st.session_state["iter_notes"].get(rid, "")
        st.session_state["iter_notes"][rid] = st.text_area(
            "Coder notes (optional)", key=notes_key, height=70,
        )

    # Write-through autosave: every card action lands in coding_sample.csv, so a
    # crash or restart costs nothing (v3.8, item 8.1).
    if _autosave_coding_sample(coding_df, iterative_dir):
        st.caption("💾 Autosaved to coding_sample.csv")

    nav_prev, nav_mid, nav_next = st.columns([1, 2, 1])
    with nav_prev:
        if st.button("← Previous", key="iter_prev", disabled=(idx == 0), **stretch()):
            st.session_state["iter_card_idx"] = idx - 1
            st.rerun()
    with nav_mid:
        uncoded = [i for i, r in enumerate(rids) if not st.session_state["iter_labels"].get(r)]
        if uncoded and st.button(f"Skip to next uncoded ({len(uncoded)} left)", key="iter_next_uncoded", **stretch()):
            nxt = next((i for i in uncoded if i > idx), uncoded[0])
            st.session_state["iter_card_idx"] = nxt
            st.rerun()
    with nav_next:
        if st.button("Next →", key="iter_next", disabled=(idx == n - 1), **stretch()):
            st.session_state["iter_card_idx"] = idx + 1
            st.rerun()

    # ── Step 3: save + validate ──────────────────────────────────────────────
    st.markdown("### Step 3 · Save & validate")
    st.caption("Cards autosave to coding_sample.csv as you code. This button additionally "
               "records your codes into the project store (for the Agreement tab).")
    if st.button("💾 Save codes to the project store", key="iter_save_all"):
        try:
            out = build_saved_sample(coding_df, st.session_state["iter_labels"],
                                     st.session_state["iter_notes"])
            out.to_csv(iterative_dir / "coding_sample.csv", index=False)

            # Also record the codes into the active project store, so human
            # coding becomes first-class data the Agreement tab can compare
            # against the model — not just a CSV. Non-fatal: the CSV is the
            # durable artifact, the store is the enrichment.
            store_msg = _record_codings_to_active_project(
                {r: st.session_state["iter_labels"].get(r, []) for r in coding_df["response_id"]},
                question_text=str(st.session_state.get("selected_question_value", "")) or None,
            )
            st.success(f"Saved {labeled_count}/{n} coded responses." + (f" {store_msg}" if store_msg else ""))
        except Exception as exc:  # noqa: BLE001
            st.error(f"Save failed: {exc}")

    m1, m2, m3 = st.columns(3)
    m1.metric("Total", n)
    m2.metric("Coded", labeled_count)
    m3.metric("Remaining", n - labeled_count)
    if labeled_count < MIN_ITERATIVE_LABELED_ROWS:
        st.warning(
            f"{labeled_count} coded — at least {MIN_ITERATIVE_LABELED_ROWS} recommended before training. "
            "Remember to **Save** before training."
        )
    else:
        st.success("Enough coded rows for a first training pass. Save, then train below.")

    dist: Dict[str, int] = {}
    for vals in st.session_state["iter_labels"].values():
        for lab in vals:
            dist[lab] = dist.get(lab, 0) + 1
    if dist:
        dist_df = pd.DataFrame([{"label": k, "count": v} for k, v in dist.items()]).sort_values("count", ascending=False)
        st.caption("Label distribution across the sample")
        st.bar_chart(dist_df.set_index("label")["count"])

    # ── Step 4: train ────────────────────────────────────────────────────────
    st.markdown("### Step 4 · Train + apply + discover")
    st.caption("Trains the multi-label model on your **saved** codes and runs unsupervised discovery.")
    if st.button("Run iterative train", key="iter_train"):
        try:
            saved_input = save_df_for_pipeline(
                long_df, "iterative_input", Path(st.session_state["iterative_output_dir"])
            )
            iterative_cfg = build_iterative_config(
                input_csv_path=saved_input,
                question_value=st.session_state["selected_question_value"],
                sample_size=int(iterative_sample_size),
                text_column=text_col,
                question_column=question_col,
                id_column=id_col,
            )
            with st.spinner("Training and running unsupervised discovery..."):
                from iterative_supervised_thematic import train_and_apply     # heavy: loaded when used
                train_and_apply(iterative_cfg)
            st.success("Iterative training completed. See Results & Downloads.")
        except Exception as exc:  # noqa: BLE001
            st.error(f"Iterative training failed: {exc}")

    # ── Step 5: output preview ───────────────────────────────────────────────
    st.markdown("### Step 5 · Output preview")
    pred_path = iterative_dir / "iterative_predictions.csv"
    label_summary_path = iterative_dir / "iterative_label_summary.csv"
    if pred_path.exists():
        st.write("Predictions preview")
        st.dataframe(pd.read_csv(pred_path).head(20), **stretch())
    if label_summary_path.exists():
        label_df = pd.read_csv(label_summary_path)
        if {"supervised_label_single", "response_count"}.issubset(label_df.columns):
            st.bar_chart(label_df.set_index("supervised_label_single")["response_count"])
