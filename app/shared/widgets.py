"""
Widgets reused across pages: PII gate, memos, chart export, drill-back.

Extracted from the former monolithic `streamlit_app.py` (v4, Phase 0.1).
Per `app/__init__`, this module imports only from `core/`, `analysis/`,
`exports/`, `app.shared`, and Streamlit — never from `streamlit_app`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional
import pandas as pd
import streamlit as st
from app.shared.layout import stretch
from core.project import Project
from privacy.scan import mask_frame, scan_frame, summarize_findings

from app.shared.constants import PROJECT_ROOT
from app.shared.io import delete_paths, describe_working_files, legacy_session_input_files
from app.shared.data import parse_labels_from_text


def render_sidebar_status(activity: str = "") -> None:
    """At-a-glance status of the activity you are in: what is loaded, confirmed, chosen, and open.

    Each activity shows only its own lines (Update 3: a Charts spreadsheet is not Surveys data, and
    survey themes mean nothing in Interviews). Home, Settings and Help show the project only."""
    st.sidebar.divider()
    st.sidebar.caption("**Status**")
    for line in status_lines(activity, st.session_state):
        st.sidebar.caption(line)
    render_version_footer()


def status_lines(activity: str, state: Any) -> List[str]:
    """The status lines for an activity key ("surveys", "charts", "interviews", or "" for none)."""
    lines: List[str] = []
    if activity == "surveys":
        df = state.get("df")
        if isinstance(df, pd.DataFrame) and not df.empty:
            confirmed = bool(state.get("pii_confirmed"))
            lines.append(f"✓ Data: {len(df):,} rows")
            lines.append(("✓" if confirmed else "○") + " PII check " + ("confirmed" if confirmed else "pending"))
        else:
            lines.append("○ No data loaded")
        labels = parse_labels_from_text(state.get("theme_labels_text", ""))
        lines.append(f"{'✓' if labels else '○'} Theme labels: {len(labels) or 'none'}")
        engine = state.get("engine_type", "transformer")
        lines.append(f"• Engine: {engine}" + (f" ({state.get('llm_model')})" if engine == "llm" else ""))
    elif activity == "charts":
        table = state.get("dc_table")
        frame = getattr(table, "frame", None)
        if isinstance(frame, pd.DataFrame):
            lines.append(f"✓ Spreadsheet: {len(frame):,} rows, {len(frame.columns)} columns")
        else:
            lines.append("○ No spreadsheet open")
        return lines                                    # a chart needs no project
    store = state.get("active_project_path", "")
    if store and Path(store).exists():
        lines.append(f"• Project: {Path(store).parent.name}")
    else:
        lines.append("○ No active project yet")
    return lines


def render_version_footer() -> None:
    """The two numbers that say what produced a result and what can open it.

    The interface showed neither. Every export carries them, so an analyst could
    always recover the version by opening a methods appendix — which is no use
    at the moment it matters, sitting in front of a project and wondering
    whether this install can open it. A store written by a newer schema raises
    rather than degrading, so the format number is the one that answers that,
    and it was the number nothing on screen reported.
    """
    from core.manifest import PACKAGE_VERSION
    from core.project import SCHEMA_VERSION

    st.sidebar.divider()
    st.sidebar.caption(
        f"QualSafe {PACKAGE_VERSION} · project format v{SCHEMA_VERSION}")


def reset_pii_gate_if_source_changed() -> None:
    """Re-arm the PII confirmation whenever a different dataset is loaded.

    The checkbox attests to one specific file having been reviewed. Leaving it
    ticked across a second load would carry the first file's attestation onto
    data it was never about — the analyst would have confirmed a file they never
    saw the gate for.

    Re-arm exactly ONCE per new source. The signal for "this is a new file" is
    `pii_gate_armed_for` (set here, at arm time), NOT `last_confirmed_source`
    (which is only set once the box is ticked). Using the latter created a
    circular deadlock: this function fired on every rerun of an unconfirmed
    file and popped the checkbox key, so the tick was destroyed before the code
    that records the confirmation could ever see it — the gate could never be
    confirmed and Column Mapping never appeared. (Bug present v3.1.1–v3.9.0.)
    """
    current = st.session_state.get("input_source", "")
    if not current:
        return
    # Already confirmed for, or already armed for, this exact source → leave the
    # checkbox state (and any tick in flight) alone.
    if current in (
        st.session_state.get("last_confirmed_source", ""),
        st.session_state.get("pii_gate_armed_for", ""),
    ):
        st.session_state["pii_gate_armed_for"] = current
        return
    # A genuinely different dataset: re-arm the gate.
    st.session_state["pii_confirmed"] = False
    st.session_state["last_confirmed_source"] = ""
    # The widget key holds its own state and would re-render ticked, ignoring
    # the value= we pass in. It has to be dropped, not just set False.
    st.session_state.pop("pii_confirm_checkbox", None)
    st.session_state.pop("pii_masking_applied", None)
    st.session_state.pop("pii_pseudonymised", None)
    st.session_state.pop("pii_pseudonym_map_csv", None)
    st.session_state["pii_gate_armed_for"] = current


def render_pii_gate(df: pd.DataFrame) -> bool:
    """Show the scan + confirmation for the loaded frame. True when confirmed.

    Ordering matters: the scan needs the loaded frame, so the gate can't sit in
    front of the loaders. Loading into memory isn't the risk — processing and
    persisting are, and both stay behind this confirmation.
    """
    st.subheader("PII / FERPA check")
    st.warning(
        "**FERPA / PII Reminder** — Survey open-text responses may contain "
        "personally identifiable information (student names, contact details, ID numbers, etc.). "
        "Confirm that this file has been reviewed for PII and is appropriate to process "
        "locally on this machine.",
        icon="⚠️",
    )

    findings = scan_frame(df)
    st.caption(summarize_findings(findings))
    if findings:
        st.dataframe(pd.DataFrame(findings), **stretch())
        st.caption(
            "These are rough checks, not a verdict: the scan above says what it cannot "
            "see, and it flags some harmless numbers too. Your review is what this "
            "gate records."
        )

        # Every content signal can be masked in text; column-name signals can't
        # (a column of names is removed by not mapping it, not by masking).
        maskable = sorted({f["column"] for f in findings
                           if not f["signal"].startswith("column name")})
        if maskable:
            with st.expander("Mask identifiers in text (optional)"):
                st.caption(
                    "Replaces what the scan finds with [EMAIL], [PHONE], [SSN], [ID], "
                    "[ADDRESS], [ROOM] and [NAME] (or a pseudonym) in the working copy. "
                    "Your source file is not modified, and the run manifest records that "
                    "masking was applied."
                )
                chosen = st.multiselect("Columns to mask", options=maskable, default=maskable,
                                        key="pii_mask_cols")
                naming = st.radio(
                    "Names become", ["[NAME] everywhere", "A consistent pseudonym per person"],
                    key="pii_naming",
                    help="Pseudonyms ([PERSON_1], [PERSON_2]...) keep the same person "
                         "recognisable across answers, so analysis of who is mentioned "
                         "still works. The key that maps them back is offered once, below, "
                         "and is never stored by QualSafe.")
                if st.button("Apply masking to working data", key="pii_apply_mask") and chosen:
                    if naming.startswith("A consistent"):
                        from privacy.scan import pseudonymise_frame

                        masked, mapping = pseudonymise_frame(df, chosen)
                        st.session_state["pii_pseudonymised"] = True
                        st.session_state["pii_pseudonym_map_csv"] = pd.DataFrame(
                            {"pseudonym": list(mapping), "name": list(mapping.values())}
                        ).to_csv(index=False).encode("utf-8")
                    else:
                        masked = mask_frame(df, chosen)
                    st.session_state["df"] = masked
                    st.session_state["pii_masking_applied"] = True
                    st.success(f"Masked {len(chosen)} column(s) in the working copy.")
                    st.rerun()

    if st.session_state.get("pii_pseudonym_map_csv"):
        st.warning(
            "**The pseudonym key re-identifies people.** Download it only if you need to "
            "trace a pseudonym back later, and keep it somewhere separate from the project "
            "and its exports, under the same protection as the original file. QualSafe "
            "does not store it: it disappears when you load another file.")
        st.download_button("Download the pseudonym key (.csv)",
                           data=st.session_state["pii_pseudonym_map_csv"],
                           file_name="pseudonym_key_KEEP_SEPARATE.csv", key="pii_map_dl")

    if st.session_state.get("pii_masking_applied"):
        st.info("Masking has been applied to the working copy for this dataset.")

    confirmed = st.checkbox(
        "I confirm this file does not contain unreviewed PII / FERPA-protected information",
        value=st.session_state.get("pii_confirmed", False),
        key="pii_confirm_checkbox",
    )
    st.session_state["pii_confirmed"] = confirmed
    if confirmed:
        st.session_state["last_confirmed_source"] = st.session_state.get("input_source", "")
    return confirmed


def _show_excerpts(excerpt_ids: List[str], excerpt_lookup: Dict[str, Any], limit: int = 40) -> None:
    st.caption(f"{len(excerpt_ids)} response(s) — showing up to {limit}:")
    for eid in list(excerpt_ids)[:limit]:
        exc = excerpt_lookup.get(eid)
        if exc is not None:
            with st.container(border=True):
                st.write(exc.text)


def render_chart_export(chart, name: str, data_df=None, key_prefix: str = "", *,
                        fold: bool = True) -> None:
    """Download controls for an Altair chart: image (PNG/SVG), spec, and data.

    Spec + data are instant and dependency-free; the image is rendered on demand
    (via offline `vl-convert`) so it isn't recomputed on every rerun. The chart's
    own "⋯" menu and browser right-click also export/copy the image.
    """
    from core.viz_export import (
        available_image_formats, chart_spec, chart_to_png, chart_to_svg)

    kp = key_prefix or name
    # `fold=False` when the caller already sits inside a fold: folds cannot be nested.
    with (st.expander("Export / copy this chart") if fold else st.container()):
        st.caption(
            "Save the figure for a report. You can also use the chart's ⋯ menu (top-right "
            "of the chart) to save an image, or right-click the chart to copy it."
        )
        c = st.columns(2)
        c[0].download_button("Spec (.json)", data=chart_spec(chart),
                             file_name=f"{name}.vl.json", mime="application/json",
                             key=f"exp_spec_{kp}")
        if data_df is not None:
            c[1].download_button("Data (.csv)", data=data_df.to_csv(index=False),
                                 file_name=f"{name}.csv", mime="text/csv", key=f"exp_csv_{kp}")

        if not available_image_formats():
            st.caption("Image (PNG/SVG) export needs `vl-convert-python`; the chart's ⋯ menu "
                       "still saves images. The spec and data downloads work now.")
            return
        if st.button("Prepare image (PNG / SVG)", key=f"exp_prep_{kp}"):
            try:
                st.session_state[f"_img_{kp}"] = {
                    "png": chart_to_png(chart), "svg": chart_to_svg(chart)}
            except Exception as exc:  # noqa: BLE001
                st.error(f"Could not render image: {exc}")
        imgs = st.session_state.get(f"_img_{kp}")
        if imgs:
            d = st.columns(2)
            d[0].download_button("Download PNG", data=imgs["png"], file_name=f"{name}.png",
                                 mime="image/png", key=f"exp_png_{kp}")
            d[1].download_button("Download SVG", data=imgs["svg"], file_name=f"{name}.svg",
                                 mime="image/svg+xml", key=f"exp_svg_{kp}")


def render_memo_section(store_path: Path, target_type: str, target_id: Optional[str],
                        title: str = "Memos") -> None:
    """Reusable memo panel for a target (project, a code, or an analysis view).

    Analytic memos are where the interpretation lives — why a code means what it
    means, what a frequency pattern suggests. Opens the project per operation
    (the codebase's pattern) so it works wherever it's dropped, regardless of the
    caller's connection lifetime.
    """
    from core.model import Memo

    with Project.open(store_path) as proj:
        memos = proj.list_memos(target_type=target_type, target_id=target_id)

    header = f"📝 {title}" + (f" ({len(memos)})" if memos else "")
    with st.expander(header, expanded=bool(memos)):
        for m in memos:
            edit_key = f"memo_edit_{m.memo_id}"
            cols = st.columns([8, 1])
            cols[0].text_area("memo", value=m.text, key=edit_key,
                              label_visibility="collapsed", height=70)
            if cols[1].button("🗑", key=f"memo_del_{m.memo_id}", help="Delete memo"):
                with Project.open(store_path) as proj:
                    proj.delete_memo(m.memo_id)
                st.rerun()
        if memos and st.button("Save memo edits", key=f"memo_save_{target_type}_{target_id}"):
            with Project.open(store_path) as proj:
                for m in memos:
                    edited = st.session_state.get(f"memo_edit_{m.memo_id}", m.text)
                    if edited != m.text:
                        proj.update_memo(m.memo_id, edited)
            st.success("Memos updated.")
            st.rerun()

        new_key = f"memo_new_{target_type}_{target_id}"
        draft = st.text_area("Add a memo", key=new_key, height=70,
                             placeholder="Your analytic note…")
        if st.button("Add memo", key=f"memo_add_{target_type}_{target_id}"):
            if draft.strip():
                with Project.open(store_path) as proj:
                    proj.add_memo(Memo(memo_id="", target_type=target_type,
                                       target_id=target_id, text=draft.strip(), author="human"))
                st.session_state.pop(new_key, None)
                st.rerun()


def render_working_data_panel() -> None:
    """Show every copy of the analyst's data this app has written to disk.

    You cannot be responsible for data you don't know exists. Runs necessarily
    write copies of response text to disk; this panel makes that visible and
    deletable in the app, rather than something you'd have to know to go looking
    for in the filesystem.
    """
    st.subheader("Working data on disk")
    st.caption(
        "Copies of your data written by this app. Deleting a run's files does not "
        "affect your original source file."
    )

    working = describe_working_files()
    if working.empty:
        st.info("No working data files on disk.")
        return

    st.dataframe(working, **stretch())

    # In-app cache cleanup (a light version of the uninstaller's "caches" scope).
    with st.expander("Clear saved similarity data"):
        st.caption("Removes cached similarity scores (regenerated automatically on the next run). "
                   "Frees disk without touching your projects or outputs. For a full "
                   "uninstall/clean reinstall, use the uninstall script for your OS.")
        caches = list(PROJECT_ROOT.rglob(".embedding_cache"))
        st.caption(f"{len(caches)} cache folder(s) found.")
        if caches and st.button("Clear saved similarity data", key="clear_emb_caches"):
            import shutil as _shutil
            removed = 0
            for c in caches:
                try:
                    _shutil.rmtree(c)
                    removed += 1
                except Exception:  # noqa: BLE001
                    pass
            st.success(f"Cleared {removed} cache folder(s).")
            st.rerun()

    legacy = legacy_session_input_files()
    if legacy:
        # Versions <= 3.1 wrote a timestamped copy of every analyzed dataset here
        # and never removed them. Report, don't silently delete: these are the
        # user's data, and a tool that quietly erases files it once quietly
        # created has only changed which surprise you get.
        total_kb = round(sum(p.stat().st_size for p in legacy) / 1024, 1)
        st.warning(
            f"**{len(legacy)} leftover input snapshot(s)** ({total_kb} KB) found in "
            f"`data/session_inputs/`. Versions up to 3.1 saved a copy of every analyzed "
            f"dataset there and never cleaned them up. Since 3.1.1 snapshots are written "
            f"inside each run folder instead. These leftovers are no longer used by "
            f"anything and can be deleted."
        )
        if st.button("Delete leftover session inputs", key="purge_legacy_inputs"):
            result = delete_paths(legacy)
            if result["deleted"]:
                st.success(f"Deleted {len(result['deleted'])} file(s).")
            if result["failed"]:
                st.error(
                    "Could not delete some files (they may be open in another "
                    "program):\n\n" + "\n".join(f"- {f}" for f in result["failed"])
                )
            st.rerun()
