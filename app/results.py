"""
Surveys and Interviews, the last step (Report): make the file you need.

Update 3 (phase 4b, item 4b.5e): the same shape as the desktop's Report step. On the page: which of
the three common reports you need (the methods and reliability appendix, the codebook report, or the
tables from your last run), what goes in it, one main button to make it, and the download. Under
More reports: the framework matrix, the audit trail, and the older iterative-labelling output.

Reports that can hold the words people wrote say so, and the choice to include quotes is off unless
you turn it on.

Per `app/__init__`, this module imports only from `core/`, `analysis/`, `exports/`, `app.shared`
and Streamlit, never from `streamlit_app`.
"""

from __future__ import annotations

import io
import tempfile
import zipfile
from pathlib import Path

import pandas as pd
import streamlit as st
from app.shared.layout import stretch

from app.shared import constants
from app.shared.projects import active_project_path

#: (key, title, what it is for). The same three, in the same order, as the desktop's common reports.
KINDS = (
    ("methods", "Methods and reliability appendix",
     "What a reviewer or ethics board asks for: how the answers were coded and by whom, how well the "
     "coders agree on each theme, and the limits. No response text."),
    ("codebook", "Codebook report",
     "Your codes with their definitions and counts, to attach to a write-up."),
    ("files", "Tables from your last run",
     "The files an analysis run wrote: scores for each answer, theme summaries and the settings used."),
)


def _title(key: str) -> str:
    return next(t for k, t, _w in KINDS if k == key)


def render_results_and_downloads() -> None:
    st.subheader("Which report do you need?")
    st.radio("Report", [k for k, _t, _w in KINDS], key="report_kind", label_visibility="collapsed",
             format_func=_title, captions=[w for _k, _t, w in KINDS])
    kind = st.session_state.get("report_kind", "methods")

    store = active_project_path()
    if kind == "files":
        _render_run_files()
    elif store is None or not Path(store).exists():
        st.info("A project is needed for this report. Run the analysis with 'Also save a project file "
                "(.qnw)' ticked, or choose a project under Settings, Project and backups.")
    else:
        st.caption(f"Made from the project in {Path(store).parent.name}.")
        {"methods": _render_methods, "codebook": _render_codebook}[kind](store)

    with st.expander("More reports"):
        _render_more(store)


# -- the three common reports --------------------------------------------------------------------------

def _scratch() -> Path:
    return Path(tempfile.mkdtemp(prefix="qualsafe_reports_"))


def _render_methods(store) -> None:
    st.session_state.setdefault("rep_ma_support", 5)
    st.number_input("Smallest number of answers a theme needs before agreement is worked out", 1, 30,
                    key="rep_ma_support",
                    help="With fewer answers than this, a figure would mean nothing, so none is shown.")
    if st.button("Make the appendix", key="rep_ma_btn", type="primary"):
        try:
            from exports.methods_appendix import build_methods_appendix

            note_path = Path(st.session_state.get("iterative_output_dir", "")) / "sampling_note.txt"
            note = note_path.read_text(encoding="utf-8") if note_path.exists() else ""
            out = build_methods_appendix(store, _scratch() / "methods_appendix.docx",
                                         min_support=int(st.session_state["rep_ma_support"]),
                                         sampling_note=note)
            st.session_state["rep_ma"] = out.read_bytes()
        except Exception as exc:  # noqa: BLE001
            st.error(f"Could not make it: {exc}")
    if st.session_state.get("rep_ma"):
        st.download_button("Download the appendix", data=st.session_state["rep_ma"],
                           file_name="methods_appendix.docx", key="rep_ma_dl")


def _render_codebook(store) -> None:
    with_examples = st.checkbox(
        "Include example quotes", key="rep_cb_examples",
        help="Adds up to two quotes for each code. The file then holds the words people wrote, so treat it "
             "like the data itself.")
    if st.button("Make the codebook report", key="rep_cb_btn", type="primary"):
        try:
            from exports.codebook_report import build_codebook_report

            out = build_codebook_report(store, _scratch() / "codebook.docx", include_examples=with_examples)
            st.session_state["rep_cb"] = out.read_bytes()
        except Exception as exc:  # noqa: BLE001
            st.error(f"Could not make it: {exc}")
    if st.session_state.get("rep_cb"):
        st.download_button("Download the codebook report", data=st.session_state["rep_cb"],
                           file_name="codebook.docx", key="rep_cb_dl")


def _run_folders() -> list:
    base = constants.STREAMLIT_OUTPUT_DIR
    return sorted((p for p in base.glob("run_*") if p.is_dir()), reverse=True) if base.exists() else []


def _render_run_files() -> None:
    runs = _run_folders()
    if not runs:
        st.info("No run yet. Run the analysis on the Code step first.")
        return
    names = [p.name for p in runs]
    last = Path(st.session_state.get("last_run_output_dir", "")).name
    chosen = st.selectbox("Which run", names, index=names.index(last) if last in names else 0,
                          key="report_run", help="The most recent run is first.")
    run_dir = next(p for p in runs if p.name == chosen)
    files = sorted(f for f in run_dir.glob("*") if f.is_file())
    st.caption(f"{len(files)} file(s) in {run_dir.name}.")
    if st.button("Put the files in one zip", key="report_zip_btn", type="primary", disabled=not files):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for f in files:
                archive.write(f, f.name)
        st.session_state["report_zip"] = (chosen, buffer.getvalue())
    ready = st.session_state.get("report_zip")
    if ready and ready[0] == chosen:
        st.download_button("Download the zip", data=ready[1], file_name=f"{chosen}.zip",
                           mime="application/zip", key="report_zip_dl")
    _preview_run(run_dir)


def _preview_run(run_dir: Path) -> None:
    summary, scored = run_dir / "cluster_summary.csv", run_dir / "responses_scored.csv"
    if summary.exists():
        st.markdown("**Groups of similar answers**")
        table = pd.read_csv(summary)
        st.dataframe(table.head(20), **stretch())
        if {"cluster_id", "response_count"}.issubset(table.columns):
            st.bar_chart(table.set_index("cluster_id")["response_count"])
    if scored.exists():
        st.markdown("**The first answers, with their codes**")
        st.dataframe(pd.read_csv(scored).head(20), **stretch())


# -- more reports --------------------------------------------------------------------------------------

def _render_more(store) -> None:
    if store is None or not Path(store).exists():
        st.caption("The framework matrix and the audit trail need a project.")
    else:
        _render_framework(store)
        st.divider()
        _render_audit(store)
    st.divider()
    _render_iterative_files()


def _render_framework(store) -> None:
    from core.project import Project

    st.markdown("**Framework matrix**")
    st.caption("Each person or group against each theme, as a narrative or a grid.")
    with Project.open(store) as proj:
        codes = [c.name for c in proj.get_codebook()]
    picked = st.multiselect("Themes", codes, default=codes[:6], key="rep_fw_codes")
    include_passages = st.checkbox("Include supporting quotes", key="rep_fw_quotes",
                                   help="Word only. Adds the words people wrote.")
    if st.button("Make the matrix", key="rep_fw_btn", disabled=not picked):
        try:
            from exports.framework_export import build_framework_docx, build_framework_workbook

            scratch = _scratch()
            docx_path = build_framework_docx(store, scratch / "framework_matrix.docx", code_names=picked,
                                             include_uncased=True, include_passages=include_passages)
            xlsx_path = build_framework_workbook(store, scratch / "framework_matrix.xlsx", code_names=picked,
                                                 include_uncased=True)
            st.session_state["rep_fw_docx"] = docx_path.read_bytes()
            st.session_state["rep_fw_xlsx"] = xlsx_path.read_bytes()
        except Exception as exc:  # noqa: BLE001
            st.error(f"Could not make it: {exc}")
    if st.session_state.get("rep_fw_docx"):
        st.download_button("Download (.docx)", data=st.session_state["rep_fw_docx"],
                           file_name="framework_matrix.docx", key="rep_fw_dl_docx")
        st.download_button("Download (.xlsx)", data=st.session_state["rep_fw_xlsx"],
                           file_name="framework_matrix.xlsx", key="rep_fw_dl_xlsx")


def _render_audit(store) -> None:
    st.markdown("**Audit trail**")
    st.caption("Every dated decision in the project, oldest first: changes to the codebook, coding "
               "sessions, imports, backups and erasures. No response text and no response ids.")
    memo_text = st.checkbox("Include the text of memos", key="rep_audit_memos",
                            help="Off by default: a memo can quote a response.")
    if st.button("Make the audit trail", key="rep_audit_btn"):
        try:
            from exports.audit_trail import build_audit_trail_docx, build_audit_trail_xlsx

            scratch = _scratch()
            docx_path = build_audit_trail_docx(store, scratch / "audit_trail.docx", include_memo_text=memo_text)
            xlsx_path = build_audit_trail_xlsx(store, scratch / "audit_trail.xlsx", include_memo_text=memo_text)
            st.session_state["rep_audit_docx"] = docx_path.read_bytes()
            st.session_state["rep_audit_xlsx"] = xlsx_path.read_bytes()
        except Exception as exc:  # noqa: BLE001
            st.error(f"Could not make it: {exc}")
    if st.session_state.get("rep_audit_docx"):
        st.download_button("Download (.docx)", data=st.session_state["rep_audit_docx"],
                           file_name="audit_trail.docx", key="rep_audit_dl_docx")
        st.download_button("Download (.xlsx)", data=st.session_state["rep_audit_xlsx"],
                           file_name="audit_trail.xlsx", key="rep_audit_dl_xlsx")


def _render_iterative_files() -> None:
    """The output of the older iterative-labelling workflow, if there is any."""
    folder = Path(st.session_state.get("iterative_output_dir", ""))
    st.markdown("**Iterative labelling output**")
    files = sorted(f for f in folder.glob("*") if f.is_file()) if folder.is_dir() else []
    if not files:
        st.caption("Nothing here yet.")
        return
    st.caption(f"{len(files)} file(s) in {folder}.")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for f in files:
            archive.write(f, f.name)
    st.download_button("Download them in one zip", data=buffer.getvalue(), file_name="iterative_output.zip",
                       mime="application/zip", key="iter_zip_dl")
