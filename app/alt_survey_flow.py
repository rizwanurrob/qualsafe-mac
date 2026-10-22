"""
Alt Survey Flow: structured, codebook-based coding as an alternative to the
exploratory zero-shot/LLM pipeline.

An analyst defines codes with inclusion/exclusion criteria and examples, a
local structured-decision engine ("Laya", optional and isolated — see
`engines/laya_engine.py`) scores every response against every code, and a
human reviews the ambiguous cases in the Review Queue. See
`docs/ALT_SURVEY_FLOW_PLAN.md` for the full design and what is and isn't built.

Per `app/__init__`, this module imports only from `core/`, `analysis/`,
`exports/`, `app.shared`, and Streamlit — never from `streamlit_app`. Laya's own
heavy dependencies are never imported here either: `engines.laya_client` and the
`laya` package only ever load inside the isolated worker process.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd
import streamlit as st
from app.shared.caveat import caveat
from app.shared.layout import stretch

from core.model import Code, CodingRunConfig
from core.project import Project
from core.run_config import parse_labels

from app.shared.constants import STREAMLIT_OUTPUT_DIR
from app.shared.data import mapping_is_ready
from app.shared.projects import active_project_path
from app.shared.state import _nav_cb


# ── project + source population ──────────────────────────────────────────────
def _project_path_for_this_flow() -> Path:
    """The `.qnw` Alt Survey Flow codes into.

    Reuses the app's one active project if there is one (so codes land next to
    whatever the exploratory pipeline already produced, feeding the same
    Analysis/Codebook/Agreement tabs), and otherwise mints a new store here —
    Alt Survey Flow is meant to work standalone, without requiring the
    exploratory pipeline to have run first.
    """
    existing = active_project_path()
    if existing is not None:
        return existing
    run_dir = STREAMLIT_OUTPUT_DIR / ("altflow_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "project.qnw"
    with Project.create(path):
        pass
    st.session_state["active_project_path"] = str(path.resolve())
    return path


def _working_text_column() -> str:
    """The column Data Setup mapped, with Alt Survey Flow's own override —
    "select the survey text column" (the user's spec) reuses the existing
    mapping by default rather than asking the analyst to redo it, but a
    dataset can have more than one free-text column and structured coding may
    reasonably target a different one than the exploratory pipeline does."""
    df = st.session_state["df"]
    default = st.session_state.get("text_column", "") or (
        st.session_state.get("text_columns", []) or [""])[0]
    candidates = [c for c in df.columns if df[c].dtype == object] or list(df.columns)
    if default and default not in candidates:
        candidates = [default] + candidates
    chosen = st.session_state.get("asf_text_column", default)
    if chosen not in candidates and candidates:
        chosen = candidates[0]
    st.session_state["asf_text_column"] = st.selectbox(
        "Text column to code", candidates,
        index=candidates.index(chosen) if chosen in candidates else 0,
        key="asf_text_column_select",
        help="Which column holds the open-ended text each code is scored against. "
             "Defaults to the column mapped in Data Setup.",
    )
    return st.session_state["asf_text_column"]


def _ensure_sources_and_excerpts(
    proj: Project, df: pd.DataFrame, text_col: str,
) -> List[Tuple[str, str]]:
    """Make sure every row of `df` has a Source + whole-response Excerpt in
    `proj`, reusing an existing one by `id_column` where possible (the same
    additive-populate convention `core/populate.py` already uses, so a row
    coded once here and once by the exploratory pipeline is one Source, not
    two). Returns `[(excerpt_id, text), ...]` in row order, skipping rows with
    empty text (nothing for a structured engine to score)."""
    id_col = st.session_state.get("id_column", "") or ""
    excerpts: List[Tuple[str, str]] = []
    for i, row in df.iterrows():
        text = str(row.get(text_col, "") or "").strip()
        if not text:
            continue
        response_id = str(row[id_col]) if id_col and id_col in df.columns else f"row_{i}"
        source = proj.find_source_by_response_id(response_id)
        if source is None:
            from core.model import Source

            source = Source(
                source_id="", type="survey_response", raw_text=text,
                label=response_id, metadata={"response_id": response_id},
            )
            sid = proj.add_source(source)
            source.source_id = sid
            eid = proj.add_whole_response_excerpt(source)
        else:
            existing_excerpts = proj.list_excerpts(source.source_id)
            eid = existing_excerpts[0].excerpt_id if existing_excerpts else \
                proj.add_whole_response_excerpt(source)
        excerpts.append((eid, source.raw_text))
    return excerpts


# ── codebook editor ───────────────────────────────────────────────────────────
def _render_codebook_editor(proj: Project) -> None:
    st.subheader("Codebook")
    st.caption(
        "Each code needs a clear inclusion/exclusion boundary — that boundary is "
        "what gets asked of the coding engine, not just the name."
    )
    codes = proj.get_codebook()
    name_by_id = {c.code_id: c.name for c in codes}

    if codes:
        overview = pd.DataFrame([{
            "code": c.name, "type": c.decision_type,
            "parent": name_by_id.get(c.parent_id, ""),
            "has criteria": bool(c.inclusion_criteria or c.exclusion_criteria),
            "examples": len(c.examples),
        } for c in codes])
        st.dataframe(overview, **stretch(), hide_index=True)

    with st.expander("Add a code", expanded=not codes):
        name = st.text_input("Name", key="asf_new_name")
        definition = st.text_area("Definition (human-readable summary)", key="asf_new_def", height=60)
        inclusion = st.text_area(
            "Assign when… (inclusion criteria)", key="asf_new_inc", height=70,
            help="The operational boundary the coding engine is actually asked. "
                 "Be concrete: 'mentions difficulty affording tuition, housing, or "
                 "books' works better than 'financial stress'.")
        exclusion = st.text_area(
            "Do NOT assign when… (exclusion criteria)", key="asf_new_exc", height=70,
            help="Optional, but this is usually what fixes a code that over-applies.")
        examples_text = st.text_area(
            "Example responses that fit (one per line, optional)", key="asf_new_ex", height=70)
        decision_type = st.radio(
            "How is this code decided?", ["Yes/No theme (noul)", "Ordinal rating (score)"],
            key="asf_new_type", horizontal=True,
            help="Most codes are themes: does the response touch this or not, "
                 "independent of every other code. Choose 'Ordinal rating' only "
                 "for a genuine rubric (e.g. severity none/mild/moderate/severe) — "
                 "it produces a rating, not a code assignment.")
        rubric_levels: List[str] = []
        if decision_type.startswith("Ordinal"):
            rubric_text = st.text_area(
                "Rubric levels, low to high (one per line)", key="asf_new_rubric", height=70,
                placeholder="none\nmild\nmoderate\nsevere")
            rubric_levels = parse_labels(rubric_text)
        parent_opts = ["(top level)"] + [c.code_id for c in codes]
        parent = st.selectbox(
            "Parent code", parent_opts, key="asf_new_parent",
            format_func=lambda cid: "(top level)" if cid == "(top level)" else name_by_id[cid],
            help="Codebooks larger than ~20 codes are far more accurate coded in "
                 "levels (parent theme, then its children) than all at once — "
                 "group related codes under a parent.")
        if st.button("Add code", key="asf_add_code"):
            if not name.strip():
                st.warning("Name a code first.")
            else:
                proj.add_code(Code(
                    code_id="", name=name.strip(), definition=definition,
                    parent_id=None if parent == "(top level)" else parent,
                    inclusion_criteria=inclusion, exclusion_criteria=exclusion,
                    examples=parse_labels(examples_text),
                    decision_type="score" if decision_type.startswith("Ordinal") else "noul",
                    rubric_levels=rubric_levels or None,
                ))
                st.success(f"Added '{name.strip()}'.")
                st.rerun()

    if not codes:
        return

    with st.expander("Edit a code", expanded=False):
        pick = st.selectbox("Code", [c.code_id for c in codes],
                            format_func=lambda cid: name_by_id[cid], key="asf_edit_pick")
        cur = next(c for c in codes if c.code_id == pick)
        e_inc = st.text_area("Assign when…", value=cur.inclusion_criteria,
                             key="asf_edit_inc", height=70)
        e_exc = st.text_area("Do NOT assign when…", value=cur.exclusion_criteria,
                             key="asf_edit_exc", height=70)
        e_examples = st.text_area("Examples (one per line)",
                                  value="\n".join(cur.examples), key="asf_edit_ex", height=70)
        if st.button("Save criteria", key="asf_edit_save"):
            proj.set_code_structured_fields(
                pick, inclusion_criteria=e_inc, exclusion_criteria=e_exc,
                examples=parse_labels(e_examples))
            st.success("Saved.")
            st.rerun()
        st.caption("To rename, reparent, merge, or delete a code, use the **Codebook** page — "
                   "the structured-coding fields here are additive to it.")


# ── engine status ─────────────────────────────────────────────────────────────
def _render_engine_status() -> bool:
    """Laya install/detect panel, mirroring `render_ollama_setup_panel`.
    Returns True if a real engine is ready to use."""
    from engines import laya_setup

    with st.expander("Coding engine (Laya)", expanded=False):
        status = laya_setup.installation_status()
        state = status["state"]
        if state == "ready":
            st.success(f"Laya {status['laya_version']} is installed and ready.")
        else:
            info = laya_setup.install_instructions()
            st.warning(
                "Laya isn't installed yet. Without it, **Run coding** uses a "
                "clearly-labelled demo engine so you can try the workflow — "
                "install Laya for real coding.")
            for line in info["what_it_does"]:
                st.markdown(f"- {line}")
            st.caption(info["why_isolated"])
            st.caption(f"About {info['disk_estimate_mb']:,} MB download.")
            if st.button("Install Laya", key="asf_install_laya"):
                with st.spinner("Creating an isolated environment and installing Laya "
                                "(this can take several minutes)…"):
                    result = laya_setup.install()
                if result.get("ok"):
                    st.success(f"Installed Laya {result.get('laya_version', '')}.")
                    st.rerun()
                else:
                    st.error(result.get("error", "Install failed."))
        if st.button("Re-check", key="asf_recheck_laya"):
            st.rerun()
        return state == "ready"


# ── run configuration ─────────────────────────────────────────────────────────
def _render_run_config() -> dict:
    st.subheader("Run configuration")
    # A band applied from the Calibration section arrives here: a widget's value
    # can only be set before the widget is drawn, so it waits for this rerun.
    pending = st.session_state.pop("asf_thresholds_pending", None)
    if pending is not None:
        st.session_state["asf_thresholds"] = pending
    c1, c2 = st.columns(2)
    mode_label = c1.radio(
        "Coding mode", ["Multi-label (each code independent)", "Single label (mutually exclusive)"],
        key="asf_mode", help="Multi-label is the right default: a response can "
             "legitimately touch several themes. Use single-label only when the "
             "codes at a level genuinely cannot co-occur (e.g. a primary category).")
    mode = "single_label_choice" if mode_label.startswith("Single") else "multi_label_noul"

    low, high = c2.slider(
        "Confidence band routed to the Review Queue", 0.0, 1.0, (0.35, 0.65), 0.05,
        key="asf_thresholds",
        help="Scores below the low end are treated as confident no; above the "
             "high end, confident yes and auto-assigned. Everything between "
             "needs a human look. These are model scores, not probabilities, "
             "unless you've run a calibration check.")

    with st.expander("Advanced", expanded=False):
        budget = st.number_input(
            "Segmentation token budget", min_value=50, max_value=1000, value=350, step=25,
            key="asf_seg_budget",
            help="Longer responses are split into overlapping chunks so none of "
                 "them exceed the coding engine's context window.")

    return {
        "text_column": st.session_state.get("asf_text_column", ""),
        "mode": mode, "low_threshold": float(low), "high_threshold": float(high),
        "segmentation_token_budget": int(budget),
        "model": "convaiinnovations/laya",
    }


# ── run ───────────────────────────────────────────────────────────────────────
def _resolve_predict_fn(engine_ready: bool):
    """A real LayaClient's predict, if installed and startable; otherwise the
    mock, with the caller responsible for showing that it's a demo. Mirrors
    `engines.factory.resolve_theme_engine`'s graceful-fallback shape."""
    from engines.laya_engine import MockLayaEngine

    if not engine_ready:
        return MockLayaEngine().predict, False
    try:
        from engines import laya_setup
        from engines.laya_client import LayaClient

        python = laya_setup.isolated_python_path()
        if not python:
            return MockLayaEngine().predict, False
        client_key = "asf_laya_client"
        client = st.session_state.get(client_key)
        if client is None or not client.is_running():
            client = LayaClient(python)
            client.start()
            st.session_state[client_key] = client
        return client.predict, True
    except Exception as exc:  # noqa: BLE001 - a start failure must fall back, not crash the page
        st.warning(f"Could not start the Laya worker ({exc}); using the demo engine instead.")
        return MockLayaEngine().predict, False


def _render_demo_codings_warning(proj: Project) -> None:
    """Say, above everything else, when the project holds demo-engine codings.

    They are hash scores, meaningless by design, and they reach frequency,
    co-occurrence and every export like real coding until removed (review F2).
    """
    from engines.laya_engine import demo_rater_ids, remove_demo_codings

    demo = demo_rater_ids(proj)
    if not demo:
        return
    coding = proj.coding_table()
    n = int(coding["rater_id"].isin(demo).sum()) if not coding.empty else 0
    st.warning(
        f"This project contains **{n} coding(s) from the demo engine** "
        f"({len(demo)} run(s)). Their scores are a hash of the text and mean nothing. "
        "They appear in Analysis and in exports until you remove them; the methods "
        "appendix flags them.")
    if st.button("Remove all demo codings", key="asf_remove_demo"):
        report = remove_demo_codings(proj)
        st.success(f"Removed {report['applications']} demo coding(s) and "
                   f"{report['decisions']} demo decision(s). Real and human coding is untouched.")
        st.rerun()


def _render_run_section(proj: Project, engine_ready: bool, run_spec: dict) -> None:
    from engines.laya_engine import CodingRunSpec, run_coding_pass, run_id_for

    st.subheader("Run coding")
    _render_demo_codings_warning(proj)
    df = st.session_state["df"]
    text_col = run_spec["text_column"]
    if not text_col:
        st.warning("Pick a text column above first.")
        return

    codes = proj.get_codebook()
    if not codes:
        st.info("Add at least one code above before running.")
        return

    run_id_key = "asf_active_run_id"
    run_name = st.text_input(
        "Run name", value=st.session_state.get("asf_run_name", "coding_run_1"), key="asf_run_name",
        help="Re-running with the same name resumes it — already-coded responses "
             "are skipped, not re-asked.")
    force_redo = st.checkbox(
        "Force re-code everything (ignore what's already coded)", key="asf_force_redo",
        help="Turn this on after changing thresholds or a code's criteria and "
             "wanting every response re-scored.")

    b1, b2 = st.columns([1, 1])
    run_clicked = b1.button("▶ Run coding", key="asf_run_button", type="primary")
    # Clicking Cancel while a run is going interrupts the running script (every
    # progress update is a Streamlit call, and Streamlit stops a script at its
    # next call when a widget changes). Writes are per response, so the run
    # stops with everything coded so far kept. The flag below is what a run
    # started in the same script execution reads; it does not reach a run that
    # is already going, and a move to a worker thread must replace it.
    if b2.button("■ Cancel", key="asf_cancel_button"):
        st.session_state["asf_cancel_requested"] = True

    if not engine_ready:
        st.info("Running with the **demo engine** (no real Laya installed) — scores are "
                "deterministic but meaningless. Install Laya above for real coding.")

    if run_clicked:
        st.session_state["asf_cancel_requested"] = False
        excerpts = _ensure_sources_and_excerpts(proj, df, text_col)
        if not excerpts:
            st.warning("No non-empty text found in that column.")
            return

        root_codes = [c for c in codes if c.parent_id is None]
        children_by_parent: Dict[Optional[str], List[Code]] = {}
        for c in codes:
            children_by_parent.setdefault(c.parent_id, []).append(c)

        predict_fn, used_real_engine = _resolve_predict_fn(engine_ready)
        # Demo and real runs never share an id: a real run started later under
        # the same name must code every response, not resume -- skip -- the
        # ones the demo "coded" (review F2).
        run_id = run_id_for(run_name, proj.path.stem, demo=not used_real_engine)
        spec = CodingRunSpec.from_dict(run_spec)
        bar = st.progress(0.0, text="Starting…")

        def progress_cb(fraction, message):
            bar.progress(min(max(fraction, 0.0), 1.0), text=message)

        def should_cancel():
            return bool(st.session_state.get("asf_cancel_requested"))

        with st.spinner("Coding…"):
            result = run_coding_pass(
                proj, excerpts, root_codes, children_by_parent, predict_fn, run_id, spec,
                progress_callback=progress_cb, should_cancel=should_cancel,
                skip_existing=not force_redo,
            )
        bar.empty()
        st.session_state[run_id_key] = run_id
        proj.save_coding_run_config(CodingRunConfig(config_id="", name=run_name, spec=run_spec))

        if result["cancelled"]:
            st.warning(f"Cancelled — {result['coded']} response(s) coded before stopping. "
                      f"Run again with the same name to resume the rest.")
        else:
            st.success(
                f"Coded {result['coded']} response(s) "
                f"({result['skipped']} already done, {result['assigned']} auto-assigned). "
                f"{'Demo engine.' if not used_real_engine else ''}")


# ── review queue ──────────────────────────────────────────────────────────────
def _render_review_queue(proj: Project, run_spec: dict) -> None:
    st.subheader("Review Queue")
    run_id = st.session_state.get("asf_active_run_id", "")
    if not run_id:
        st.caption("Run coding above first.")
        return

    queue = proj.review_queue(run_id, low=run_spec["low_threshold"], high=run_spec["high_threshold"])
    if queue.empty:
        st.success("Nothing ambiguous waiting for review in this run.")
        return

    st.caption(
        f"{len(queue)} candidate code(s) scored in the ambiguous band and not yet reviewed. "
        "Scores below are model scores, not probabilities."
    )

    reviewer = st.text_input(
        "Reviewing as", value=st.session_state.get("analyst_name", ""), key="asf_reviewer_name")

    if st.button(f"Accept all {len(queue)} suggested codes", key="asf_accept_all"):
        for _, row in queue.iterrows():
            proj.review_coding_decision(
                row["decision_id"], human_assigned=True, reviewer=reviewer or "analyst")
        st.success("Accepted all.")
        st.rerun()

    for _, row in queue.head(50).iterrows():
        with st.container(border=True):
            st.markdown(f"**{row['code_name']}**  ·  model score {row['model_score']:.2f}")
            st.write(row["excerpt_text"])
            a, b, c = st.columns(3)
            key_base = row["decision_id"]
            if a.button("✓ Accept", key=f"asf_accept_{key_base}"):
                proj.review_coding_decision(key_base, human_assigned=True,
                                            reviewer=reviewer or "analyst")
                st.rerun()
            if b.button("✗ Reject", key=f"asf_reject_{key_base}"):
                proj.review_coding_decision(key_base, human_assigned=False,
                                            reviewer=reviewer or "analyst")
                st.rerun()
            if c.button("⚑ Flag", key=f"asf_flag_{key_base}"):
                proj.review_coding_decision(
                    key_base, human_assigned=bool(row["model_assigned"]),
                    reviewer=reviewer or "analyst", review_status="flagged")
                st.rerun()
    if len(queue) > 50:
        st.caption(f"Showing the first 50 of {len(queue)}. Review these, then reload.")


# ── calibration (V7 Update 2, U4) ────────────────────────────────────────────
def _render_calibration(proj: Project, run_spec: dict) -> None:
    """Measure the engine against a person on a random sample, and turn the
    measurement into a confidence band (analysis.calibration)."""
    from analysis.calibration import (CAVEATS, HUMAN_RATER, calibration_pairs, decisions_export,
                                      draw_sample, load_sample, per_code_calibration,
                                      recommend_band, reliability_table, save_sample)
    from core.model import CodeApplication

    st.subheader("Calibration")
    run_id = st.session_state.get("asf_active_run_id", "")
    if not run_id:
        st.caption("Run coding above first.")
        return
    st.caption(
        "The confidence band above is a guess until it is measured. Draw a random sample, "
        "code each response yourself on every code, and this section shows how often the "
        "engine is right and which band your sample supports. Random, not the Review "
        "Queue: the queue holds only the hard cases.")
    if "__demo_" in run_id:
        st.warning("This run used the demo engine: a calibration of it measures a hash, "
                   "not coding. Fine for trying the workflow; meaningless as a result.")

    decisions = proj.coding_decisions_table(run_id)
    excerpt_ids = decisions["excerpt_id"].unique().tolist()
    c1, c2 = st.columns([1, 2])
    size = c1.number_input("Sample size", min_value=5, max_value=max(5, len(excerpt_ids)),
                           value=min(50, max(5, len(excerpt_ids))), key="asf_cal_size")
    if c2.button("Draw a new random sample", key="asf_cal_draw"):
        save_sample(proj, run_id, draw_sample(excerpt_ids, int(size)))
        st.rerun()
    sample = load_sample(proj, run_id)
    if not sample:
        st.info("No calibration sample for this run yet.")
        return

    codes = [c for c in proj.get_codebook() if c.decision_type != "score"]
    id_by_name = {c.name: c.code_id for c in codes}
    item_set = proj.rater_item_set(HUMAN_RATER)
    judged = set(item_set.labels) & set(sample) if item_set.recorded else set()
    st.write(f"**{len(judged)} of {len(sample)}** sampled response(s) judged.")

    waiting = [e for e in sample if e not in judged][:10]
    if waiting:
        with st.form("asf_cal_form"):
            st.caption("Tick **I've judged this** for each response you have read and "
                       "coded on every code. Only ticked responses are saved: an unticked "
                       "one is not counted as \"no code\".")
            for eid in waiting:
                excerpt = proj.get_excerpt(eid)
                with st.container(border=True):
                    st.write(excerpt.text if excerpt else "(response unavailable)")
                    st.multiselect("Codes that apply", list(id_by_name),
                                   default=sorted(item_set.labels.get(eid, set()) & set(id_by_name)),
                                   key=f"asf_cal_codes_{eid}")
                    st.checkbox("I've judged this", key=f"asf_cal_done_{eid}")
            saved = st.form_submit_button("Save judged responses")
        if saved:
            done = [e for e in waiting if st.session_state.get(f"asf_cal_done_{e}")]
            apps = [CodeApplication(application_id="", excerpt_id=e, code_id=id_by_name[name],
                                    coder="human", rater_id=HUMAN_RATER)
                    for e in done for name in st.session_state.get(f"asf_cal_codes_{e}", [])]
            if done:
                proj.replace_applications_for_rater(HUMAN_RATER, done, apps)
                st.rerun()
            st.warning("Nothing ticked as judged, so nothing was saved.")

    pairs = calibration_pairs(proj, run_id)
    if pairs.empty:
        return
    target = st.slider("Target precision for auto-assigned codes", 0.70, 0.99, 0.90, 0.01,
                       key="asf_cal_target",
                       help="Of the codes the engine assigns on its own, how many must a "
                            "person agree with? The same target applies to what the band "
                            "treats as confidently absent.")
    table = per_code_calibration(pairs, target=target)
    st.dataframe(table, **stretch(), hide_index=True)
    band = recommend_band(pairs, target=target)
    if band["high"] is not None and band["low"] is not None:
        st.success(f"This sample supports auto-assigning at **{band['high']:.2f}** and above, "
                   f"and treating scores below **{band['low']:.2f}** as no code. Current band: "
                   f"{run_spec['low_threshold']:.2f}–{run_spec['high_threshold']:.2f}.")
        if st.button("Apply this band", key="asf_cal_apply"):
            st.session_state["asf_thresholds_pending"] = (band["low"], band["high"])
            st.rerun()
    if band["note"]:
        st.warning(band["note"])
    with st.expander("Reliability table (is a score a probability?)"):
        st.dataframe(reliability_table(pairs), **stretch(), hide_index=True)
    for caveat_text in CAVEATS:
        caveat(caveat_text, "note")

    st.markdown("**Export this run's decisions**")
    include_text = st.checkbox("Include response text", key="asf_export_text",
                               help="Off by default: with it on, the file holds the data itself.")
    frame = decisions_export(decisions, include_text=include_text)
    from analyze_survey import sanitize_frame_for_csv
    import io
    safe = sanitize_frame_for_csv(frame)
    buffer = io.BytesIO()
    safe.to_excel(buffer, index=False)
    d1, d2 = st.columns(2)
    d1.download_button("Decisions (.csv)", safe.to_csv(index=False).encode("utf-8"),
                       file_name=f"decisions_{run_id}.csv", key="asf_dl_csv")
    d2.download_button("Decisions (.xlsx)", buffer.getvalue(),
                       file_name=f"decisions_{run_id}.xlsx", key="asf_dl_xlsx")


# ── entry point ────────────────────────────────────────────────────────────────
def render_alt_survey_flow() -> None:
    st.header("Alt Survey Flow")
    st.caption("**Preview.** The structured-coding engine (Laya) has not yet been run on a real install; without it this page uses a demo engine whose scores mean nothing, and says so.")
    st.caption(
        "Structured, codebook-based coding: define codes with a clear inclusion/"
        "exclusion boundary, run a local coding engine, and review what it's "
        "unsure about. An alternative to the exploratory analysis, not a "
        "replacement — they can be used on the same data."
    )

    if not mapping_is_ready():
        st.warning("Load data and map columns first in Data Setup.")
        st.button("Go to Data Setup", key="asf_goto_data", on_click=_nav_cb, args=("Data Setup",))
        return

    path = _project_path_for_this_flow()
    _working_text_column()

    with Project.open(path) as proj:
        _render_codebook_editor(proj)
        st.divider()
        engine_ready = _render_engine_status()
        st.divider()
        run_spec = _render_run_config()
        st.divider()
        _render_run_section(proj, engine_ready, run_spec)
        st.divider()
        _render_review_queue(proj, run_spec)
        st.divider()
        _render_calibration(proj, run_spec)
