"""
Projects, team distribution, backups, erasure, merges, archives.

Extracted from the former monolithic `streamlit_app.py` (v4, Phase 0.1).
Per `app/__init__`, this module imports only from `core/`, `analysis/`,
`exports/`, `app.shared`, and Streamlit — never from `streamlit_app`.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
import streamlit as st
from core.project import Project

from app.shared.constants import PROJECT_ROOT, STREAMLIT_OUTPUT_DIR, SYNTHETIC_FILE
from app.shared.data import load_coding_sample_df
from app.shared.projects import active_project_path, discover_project_stores
from app.shared.widgets import render_working_data_panel


def render_export_bundle_section() -> None:
    """Build a shareable analysis zip from the active project (redacted by default)."""
    st.subheader("Export a shareable bundle")
    st.caption(
        "Package the analysis (codebook, frequencies, co-occurrence, agreement) as a "
        "zip to share with a collaborator or reviewer. Verbatim quotes are **excluded "
        "by default** — everything is redacted at the source, so no response text "
        "leaves in the file unless you deliberately include it."
    )
    store = active_project_path()
    if store is None or not Path(store).exists():
        st.info("Select or create a project above first.")
        return

    include_raw = st.checkbox(
        "Include verbatim response text (quotes)", value=False, key="bundle_raw",
        help="Off = a safe-to-share bundle with all quotes redacted. Only turn on if "
             "the recipient is cleared to see raw responses.")
    include_memos = st.checkbox("Include memos", value=True, key="bundle_memos",
                                help="Analyst notes. Redacted too when quotes are excluded.")

    # Descriptor crosstabs default to NONE — subgroup labels are a re-identification
    # vector, so the analyst opts in per descriptor.
    with Project.open(store) as proj:
        desc_table = proj.descriptor_table()
    descriptor_keys = sorted(desc_table["key"].unique().tolist()) if not desc_table.empty else []
    chosen_desc = st.multiselect(
        "Respondent detail crosstabs to include (default none)", options=descriptor_keys,
        default=[], key="bundle_desc",
        help="Cells with fewer than the threshold below are flagged as small (suppression risk).")
    threshold = st.number_input("Small-cell flag threshold", min_value=1, value=5, key="bundle_thresh")

    if st.button("Build bundle", key="bundle_build"):
        try:
            from exports.bundle import build_bundle
            out_zip = Path(store).parent / (
                "analysis_bundle" + ("_with_quotes" if include_raw else "_redacted") + ".zip")
            build_bundle(store, out_zip, include_raw_text=include_raw,
                         descriptor_keys=chosen_desc, include_memos=include_memos,
                         small_cell_threshold=int(threshold))
            with out_zip.open("rb") as f:
                st.download_button(
                    f"Download {out_zip.name}", data=f.read(), file_name=out_zip.name,
                    mime="application/zip", key="bundle_dl")
            if not include_raw:
                st.success("Redacted bundle built — no verbatim response text is included.")
            else:
                st.warning("This bundle contains verbatim response text. Share only with cleared recipients.")
        except Exception as exc:  # noqa: BLE001
            st.error(f"Bundle build failed: {exc}")

    # ── Word + Excel deliverables (v3.8.2) ────────────────────────────────────
    dcol, xcol = st.columns(2)
    if dcol.button("Build Word report (.docx)", key="docx_build",
                   help="A formatted report — codebook, frequencies, top co-occurrences, "
                        "agreement, memos. Quotes follow the checkbox above: excluded and "
                        "redacted unless you included verbatim text."):
        try:
            from exports.docx_report import build_docx_report
            out_docx = Path(store).parent / (
                "analysis_report" + ("_with_quotes" if include_raw else "_redacted") + ".docx")
            build_docx_report(store, out_docx, include_raw_text=include_raw,
                              include_memos=include_memos)
            with out_docx.open("rb") as f:
                st.download_button(f"Download {out_docx.name}", data=f.read(),
                                   file_name=out_docx.name, key="docx_dl",
                                   mime="application/vnd.openxmlformats-officedocument"
                                        ".wordprocessingml.document")
            st.success("Word report built.")
        except Exception as exc:  # noqa: BLE001
            st.error(f"Word report failed: {exc}")
    if xcol.button("Build Excel workbook (.xlsx)", key="xlsx_build",
                   help="Analysis tables (codebook, frequency, co-occurrence, agreement) "
                        "on separate sheets. Never contains response text — always safe "
                        "to share."):
        try:
            from exports.excel_workbook import build_analysis_workbook
            out_xlsx = Path(store).parent / "analysis_tables.xlsx"
            build_analysis_workbook(store, out_xlsx)
            with out_xlsx.open("rb") as f:
                st.download_button(f"Download {out_xlsx.name}", data=f.read(),
                                   file_name=out_xlsx.name, key="xlsx_dl",
                                   mime="application/vnd.openxmlformats-officedocument"
                                        ".spreadsheetml.sheet")
            st.success("Excel workbook built.")
        except Exception as exc:  # noqa: BLE001
            st.error(f"Excel workbook failed: {exc}")


def render_team_distribution_section() -> None:
    """Split a coding sample across a team, then merge the coded files back."""
    st.subheader("Distribute coding to a team")
    st.caption(
        "Split the current coding sample among several coders. **Partition** = "
        "disjoint slices for speed (no agreement to compute). **Overlap** = a shared "
        "calibration set everyone codes, for between-coder reliability, plus a "
        "partitioned remainder. Each coder gets a CSV to fill and send back."
    )
    iterative_dir = Path(st.session_state["iterative_output_dir"])
    sample = load_coding_sample_df(iterative_dir)
    if sample.empty:
        st.info("No coding sample yet. Create one in the Iterative Labeling Lab first.")
        return

    coders_text = st.text_input("Coder names (comma-separated)", value="Coder A, Coder B",
                                key="team_coders")
    coders = [c.strip() for c in coders_text.split(",") if c.strip()]
    mode_label = st.radio("Mode", ["Partition (throughput)", "Overlap (reliability)"],
                          horizontal=True, key="team_mode")
    mode = "overlap" if mode_label.startswith("Overlap") else "partition"
    overlap_n = 0
    if mode == "overlap":
        overlap_n = st.slider("Calibration set size (coded by everyone)", 1,
                              max(1, len(sample)), min(5, len(sample)), key="team_overlap")

    if st.button("Build per-coder sheets", key="team_split") and coders:
        try:
            import io, zipfile
            from core.assignments import split_coding_sample
            parts = split_coding_sample(sample, coders, mode=mode, overlap_n=overlap_n)
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                for coder, frame in parts.items():
                    slug = re.sub(r"[^A-Za-z0-9]+", "_", coder).strip("_") or "coder"
                    zf.writestr(f"coding_sample_{slug}.csv", frame.to_csv(index=False))
            st.download_button("Download coder sheets (zip)", data=buf.getvalue(),
                               file_name="coder_sheets.zip", mime="application/zip",
                               key="team_dl")
            sizes = {c: len(f) for c, f in parts.items()}
            st.success("Built sheets: " + ", ".join(f"{c} ({n})" for c, n in sizes.items()))
            if mode == "partition":
                st.caption("Partition mode: no shared items, so there is no between-coder "
                           "agreement to compute — this is throughput only.")
        except Exception as exc:  # noqa: BLE001
            st.error(f"Split failed: {exc}")

    # ── Merge coded sheets back ───────────────────────────────────────────────
    st.markdown("**Merge coded sheets back**")
    store = active_project_path()
    if store is None or not Path(store).exists():
        st.caption("Select a project above to merge coded sheets into it.")
        return
    uploaded = st.file_uploader("Upload coders' filled coding_sample CSVs", type=["csv"],
                                accept_multiple_files=True, key="team_merge_files")
    merge_q = st.text_input("Question these sheets cover (must match the run)",
                            value=str(st.session_state.get("selected_question_value", "")),
                            key="team_merge_q")
    if uploaded and st.button("Merge coded sheets", key="team_merge_btn"):
        try:
            from core.assignments import coverage_report, merge_coder_samples
            coder_files = {}
            for uf in uploaded:
                tmp = Path(store).parent / f"_merge_{uf.name}"
                tmp.write_bytes(uf.getvalue())
                # Derive the coder name from the filename (…_Name.csv), else the file stem.
                name = Path(uf.name).stem.replace("coding_sample_", "").replace("_", " ").strip()
                coder_files[name or uf.name] = tmp
            merge_coder_samples(store, coder_files, question_text=merge_q or None)
            for tmp in coder_files.values():
                Path(tmp).unlink(missing_ok=True)
            cov = coverage_report(store)
            st.success(
                f"Merged {len(coder_files)} coder(s). "
                f"{cov['n_excerpts_coded']} item(s) coded, {cov['n_double_coded']} double-coded "
                f"(available for human-vs-human agreement in the Analysis → Agreement tab).")
        except Exception as exc:  # noqa: BLE001
            st.error(f"Merge failed: {exc}")


def render_backup_section() -> None:
    """Safety backups of the active store: list, restore, and clear (v3.8, 8.3)."""
    st.subheader("Project backups")
    st.caption(
        "The store is backed up automatically before destructive operations "
        "(erasure, team merges, codebook restores) — the newest 5 are kept in "
        "`project_backups/` next to the project."
    )
    store = active_project_path()
    if store is None or not Path(store).exists():
        st.info("Select an existing project above to see its backups.")
        return
    from core.backups import backup_store, list_backups, restore_backup

    if st.button("Back up now", key="backup_now",
                 help="Takes a manual snapshot of the current project store."):
        result = backup_store(store, reason="manual")
        st.success(f"Backed up: `{Path(result).name}`" if result else "Backup failed.")

    backups = list_backups(store)
    if not backups:
        st.caption("No backups yet.")
        return
    fmt = {str(p): p.name for p in backups}
    pick = st.selectbox("Available backups (newest first)", [str(p) for p in backups],
                        format_func=lambda p: fmt[p], key="backup_pick")
    c1, c2 = st.columns(2)
    if c1.button("Restore this backup", key="backup_restore",
                 help="Replaces the current project with the backup. The current state "
                      "is backed up first, so this is undoable."):
        try:
            restore_backup(store, pick)
            st.success("Project restored from backup.")
            st.rerun()
        except Exception as exc:  # noqa: BLE001
            st.error(f"Restore failed: {exc}")
    if c2.button("Delete ALL backups", key="backup_delete_all",
                 help="Backups contain the same sensitive data as the project. After a "
                      "respondent erasure, delete backups to complete the erasure — the "
                      "pre-erasure copy lives here until you do."):
        removed = 0
        for b in backups:
            try:
                b.unlink()
                removed += 1
            except Exception:  # noqa: BLE001
                pass
        st.success(f"Deleted {removed} backup(s).")
        st.rerun()


def render_project_json_section() -> None:
    """Portable project exchange: export/import the whole store as JSON (v3.8, 8.4)."""
    st.subheader("Project portability (JSON)")
    st.caption(
        "Export the whole project — sources, passages, codes, codings, respondent details, "
        "memos — as one portable, inspectable JSON file, or rebuild a project from "
        "one. **Contains raw response text**; treat the file like the data itself."
    )
    store = active_project_path()
    if store is not None and Path(store).exists():
        if st.button("Export project as JSON", key="pjson_export"):
            try:
                out = Path(store).with_suffix(".json")
                with Project.open(store) as proj:
                    proj.export_json(out)
                with out.open("rb") as f:
                    st.download_button(f"Download {out.name}", data=f.read(),
                                       file_name=out.name, mime="application/json",
                                       key="pjson_dl")
                st.success(f"Exported: `{out}`")
            except Exception as exc:  # noqa: BLE001
                st.error(f"Export failed: {exc}")
    uploaded_json = st.file_uploader("Import a project JSON (creates a new project)",
                                     type=["json"], key="pjson_upload")
    if uploaded_json is not None and st.button("Import as new project", key="pjson_import"):
        try:
            name = Path(uploaded_json.name).stem
            target_dir = STREAMLIT_OUTPUT_DIR / f"imported_{name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            target_dir.mkdir(parents=True, exist_ok=True)
            tmp_json = target_dir / uploaded_json.name
            tmp_json.write_bytes(uploaded_json.getvalue())
            proj = Project.import_json(tmp_json, target_dir / "project.qnw")
            proj.close()
            st.session_state["active_project_path"] = str(target_dir / "project.qnw")
            st.success(f"Imported as `{target_dir.name}` and set active.")
            st.rerun()
        except Exception as exc:  # noqa: BLE001
            st.error(f"Import failed: {exc}")

    # ── Whole-project archive (.zip) — v3.9.1 ─────────────────────────────────
    st.subheader("Project archive (.zip)")
    st.caption(
        "Export the whole project folder — the `.qnw` store plus its run outputs "
        "and report — as one zip to carry to another installation, then import it "
        "there. Safety backups and caches are left out. **Contains raw response "
        "text**; treat the zip like the data itself. (On the far side, use "
        "*Rebuild responses from a project* in Data Setup to code without the "
        "original spreadsheet.)"
    )
    archive_store = active_project_path()
    if archive_store is not None and Path(archive_store).exists():
        if st.button("Export project as .zip", key="parch_export"):
            try:
                from core.project_archive import export_project_archive
                data = export_project_archive(archive_store)
                fname = f"{Path(archive_store).parent.name or 'project'}.zip"
                st.download_button("Download project archive", data=data,
                                   file_name=fname, mime="application/zip",
                                   key="parch_dl")
                st.success(f"Built archive ({len(data) / 1024:.0f} KB).")
            except Exception as exc:  # noqa: BLE001
                st.error(f"Archive export failed: {exc}")
    else:
        st.info("Select an active project above to export it.")
    uploaded_zip = st.file_uploader("Import a project archive (.zip)", type=["zip"],
                                    key="parch_upload")
    if uploaded_zip is not None and st.button("Import archive as new project", key="parch_import"):
        try:
            from core.project_archive import import_project_archive
            store = import_project_archive(
                uploaded_zip.getvalue(), STREAMLIT_OUTPUT_DIR,
                name_hint=Path(uploaded_zip.name).stem)
            st.session_state["active_project_path"] = str(store)
            st.success(f"Imported and set active: `{store.parent.name}`.")
            st.rerun()
        except Exception as exc:  # noqa: BLE001
            st.error(f"Archive import failed: {exc}")


def open_project_bytes(name: str, data: bytes, output_dir: Path = None) -> Path:
    """Keep a project file in the program's own output folder, check it opens, and return where it is.

    Raises ValueError (in plain words) and leaves nothing behind if it is not a project this program can open."""
    if not data.startswith(b"SQLite format 3\x00"):
        raise ValueError("That file could not be opened as a project: it is not a QualSafe project file.")
    root = Path(output_dir) if output_dir else STREAMLIT_OUTPUT_DIR
    folder = root / ("opened_" + re.sub(r"[^A-Za-z0-9_-]+", "_", Path(name).stem)[:40]
                     + "_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / "project.qnw"
    target.write_bytes(data)
    try:
        with Project.open(target):
            pass
    except Exception as exc:  # noqa: BLE001 - say what happened, leave nothing half-opened
        import gc
        import shutil

        gc.collect()                                  # let go of the half-opened file (Windows keeps it locked)
        shutil.rmtree(folder, ignore_errors=True)
        raise ValueError(f"That file could not be opened as a project: {exc}") from exc
    return target


def _render_open_project_file() -> None:
    """Open a project file somebody gave you (or you saved earlier) by choosing it from your computer."""
    with st.expander("Open a project file"):
        upload = st.file_uploader("A project file (.qnw)", type=["qnw"], key="open_qnw_upload")
        if upload is not None and st.button("Open this project", key="open_qnw_btn"):
            try:
                target = open_project_bytes(upload.name, upload.getvalue())
            except ValueError as exc:
                st.error(str(exc))
                return
            st.session_state["active_project_path"] = str(target)
            st.success("Opened. You can read its results under Explore.")
            st.rerun()


def render_data_management() -> None:
    """Project selection, human-rater identity, and respondent erasure / purge."""
    st.header("Data Management")

    # ── Active project ────────────────────────────────────────────────────────
    st.subheader("Active project")
    st.caption(
        "Your project file (`.qnw`) holds your themes, your coding and the results of each run. "
        "Pick the one you want to work in, or open one you were given."
    )
    stores = discover_project_stores()
    if stores:
        labels = [p.parent.name for p in stores]
        current = st.session_state.get("active_project_path", "")
        default_idx = next((i for i, p in enumerate(stores) if str(p) == current), len(stores) - 1)
        picked = st.selectbox("Project", options=range(len(stores)),
                              format_func=lambda i: labels[i], index=default_idx)
        st.session_state["active_project_path"] = str(stores[picked])
        st.caption(f"Working in `{stores[picked].parent.name}`.")
    else:
        st.info("No project yet. Run the analysis with the project file switched on, or open one below.")
    _render_open_project_file()

    st.session_state["analyst_name"] = st.text_input(
        "Your name (optional) — recorded as the human coder in agreement analysis",
        value=st.session_state.get("analyst_name", ""),
    )

    # ── Guided sample project ─────────────────────────────────────────────────
    st.subheader("Guided sample project")
    st.caption(
        "New here? Build a small example project (made-up answers that are already coded, a few coded by "
        "hand, and a note) so the results, the codebook and agreement have something to explore right away. "
        "It is clearly marked SAMPLE and will not interfere with real work."
    )
    if st.button("Create guided sample project", key="build_sample"):
        try:
            from core.sample_project import build_sample_project, default_sample_path
            out = default_sample_path(STREAMLIT_OUTPUT_DIR)
            out.parent.mkdir(parents=True, exist_ok=True)
            build_sample_project(SYNTHETIC_FILE, out)
            st.session_state["active_project_path"] = str(out)
            st.success(f"Built sample project at `{out}`. Open the Analysis or Codebook page to explore it.")
            st.rerun()
        except Exception as exc:  # noqa: BLE001
            st.error(f"Could not build sample project: {exc}")

    # ── Export a shareable bundle ─────────────────────────────────────────────
    render_export_bundle_section()

    # ── Second coder (multi-coder IRR) ────────────────────────────────────────
    st.subheader("Import a second coder")
    st.caption(
        "For human-vs-human reliability: a colleague codes the same "
        "`coding_sample.csv`, and you import it here as a second coder. "
        "Human-vs-human kappa then appears in the Analysis → Agreement tab."
    )
    store_for_import = active_project_path()
    if store_for_import is None or not Path(store_for_import).exists():
        st.info("Select an existing project above first.")
    else:
        uploaded_sample = st.file_uploader(
            "Second coder's coding_sample.csv", type=["csv"], key="second_coder_csv"
        )
        second_rater = st.text_input("Coder id for this coder", value="human_secondary",
                                     key="second_rater_id")
        second_question = st.text_input(
            "Question this sample covers (must match the run's question text)",
            value=str(st.session_state.get("selected_question_value", "")), key="second_q")
        if uploaded_sample is not None and st.button("Import second coder", key="import_second"):
            try:
                import io
                from core.populate import import_second_coder_sample
                tmp = Path(store_for_import).parent / f"_second_{uploaded_sample.name}"
                tmp.write_bytes(uploaded_sample.getvalue())
                result = import_second_coder_sample(
                    store_for_import, tmp, rater_id=second_rater.strip() or "human_secondary",
                    question_text=second_question or None)
                tmp.unlink(missing_ok=True)
                msg = (f"Imported {result['applications']} code(s) as `{second_rater}`, "
                       f"over {result['excerpts']} reviewed response(s) — including the ones "
                       f"this coder left uncoded, which count in agreement.")
                if result["unmatched"]:
                    shown = ", ".join(result.get("unmatched_ids", [])[:10])
                    more = "…" if result["unmatched"] > 10 else ""
                    msg += (f" {result['unmatched']} response id(s) didn't match a source in the "
                            f"store ({shown}{more}): check they are this dataset's ids and "
                            f"this question, or run the analysis on this dataset first.")
                st.success(msg)
                if result.get("encoding_note"):
                    st.info(result["encoding_note"])
            except Exception as exc:  # noqa: BLE001
                st.error(f"Import failed: {exc}")

    # ── Team distribution ─────────────────────────────────────────────────────
    render_team_distribution_section()

    # ── Erasure ───────────────────────────────────────────────────────────────
    st.subheader("Erase a respondent")
    st.caption(
        "Right-to-erasure: removes one respondent from the project store **and** its "
        "derived files (scored CSVs, the run report, saved similarity data). Quotes are "
        "scrubbed from summaries. This cannot be undone."
    )
    store = active_project_path()
    if store is None or not Path(store).exists():
        st.info("Select an existing project above to enable erasure.")
    else:
        erase_id = st.text_input("Response ID to erase", key="erase_response_id")
        purge_backups = st.checkbox(
            "Also delete this project's backups",
            value=True,
            key="erase_purge_backups",
            help=(
                "Erasure takes a backup first, and that backup still contains the "
                "respondent. Leaving it in place means the data has not really gone. "
                "Untick only if you want a way back from erasing the wrong id — and "
                "then delete the backups yourself once you have checked."
            ),
        )
        st.caption(
            "The project file is rebuilt (VACUUM) after the delete, so the removed "
            "response leaves no readable remnant in the `.qnw`. Deletion still unlinks "
            "files rather than shredding disk sectors — for strong guarantees keep "
            "projects on an encrypted institutional volume."
        )
        if st.button("Erase this respondent", key="erase_btn", disabled=not erase_id):
            try:
                from core.erasure import erase_respondent
                report = erase_respondent(Path(store).parent, erase_id, store_path=store,
                                          purge_backups=purge_backups)
                counts = report.get("store", {})
                st.success(
                    f"Erased response `{erase_id}`: removed {counts.get('sources', 0)} source(s), "
                    f"{counts.get('applications', 0)} code application(s), and "
                    f"{len(report.get('caches_removed', []))} cache file(s). "
                    f"Audit event recorded (hashed, no identifier retained)."
                )
                if not report.get("vacuumed", False):
                    st.warning(
                        "The project file could not be rebuilt (it may be open elsewhere). "
                        "The response is gone from every query, but its text may still sit "
                        "in the file's free pages — close other copies and erase again, or "
                        "run `VACUUM` on the store."
                    )
                remaining = report.get("backups_retaining_data") or []
                if remaining:
                    st.warning(
                        f"{len(remaining)} backup(s) were kept and **still contain this "
                        "respondent** (including the pre-erasure safety copy). The erasure "
                        "is complete only once they are deleted — use 'Delete ALL backups' "
                        "below after verifying you erased the right id."
                    )
            except Exception as exc:  # noqa: BLE001
                st.error(f"Erasure failed: {exc}")

    # ── Merge a colleague's project (v3.8.1) ─────────────────────────────────
    # ── Bring a project in from another package (v4.6) ───────────────────────
    st.subheader("Import from NVivo, MAXQDA, ATLAS.ti (.qdpx)")
    st.caption(
        "REFI-QDA is the open exchange standard those packages all export. This "
        "reads a whole project — documents, coded passages with their exact "
        "character positions, the coders who made them, and respondent "
        "variables — so you can try QualSafe on work you have already done."
    )
    qdpx_store = active_project_path()
    if qdpx_store is None or not Path(qdpx_store).exists():
        st.info("Select an active project above to import into.")
    else:
        st.caption(
            "**Imported codings stay someone else's.** They arrive under their own "
            "coder, never merged into yours — agreement between two coders is only "
            "meaningful if they stay two coders."
        )
        uploaded_qdpx = st.file_uploader("REFI-QDA project (.qdpx)", type=["qdpx"],
                                         key="qdpx_upload")
        if uploaded_qdpx is not None and st.button("Import this project",
                                                   key="qdpx_import_btn"):
            from core.qdpx import import_qdpx

            tmp = Path(qdpx_store).parent / f"_incoming_{uploaded_qdpx.name}"
            try:
                tmp.write_bytes(uploaded_qdpx.getvalue())
                with Project.open(qdpx_store) as proj:
                    report = import_qdpx(proj, tmp)
                st.success(report.summary())
                if report.unresolved_selections or report.skipped:
                    st.warning(
                        "Some of that file did not come across — the detail is in "
                        "the message above. The standard's own documentation says "
                        "complex projects cannot transfer one-to-one between "
                        "packages, so check what matters to you before relying on it."
                    )
            except ValueError as exc:
                st.error(str(exc))
            except Exception as exc:  # noqa: BLE001
                st.error(f"Import failed: {exc}")
            finally:
                tmp.unlink(missing_ok=True)

    # ── Take a project out to another package (v4.6) ─────────────────────────
    st.subheader("Export to NVivo, MAXQDA, ATLAS.ti (.qdpx)")
    st.caption(
        "The same open standard, going the other way: your documents, coded "
        "passages, coders and respondent details as a file those packages can open — "
        "and that an archive can accept. This is what makes *no lock-in* a fact "
        "rather than a claim."
    )
    export_store = active_project_path()
    if export_store is None or not Path(export_store).exists():
        st.info("Select an active project above to export.")
    else:
        st.warning(
            "**A `.qdpx` always contains the full text of every source.** That is "
            "what the format is for, and unlike the bundle or the workbook it "
            "cannot be redacted into something still worth exchanging. Treat the "
            "file as you would the project itself."
        )
        if st.button("Build the .qdpx", key="qdpx_export_btn"):
            from core.qdpx_export import export_qdpx

            try:
                out = Path(export_store).parent / f"{Path(export_store).stem}.qdpx"
                with Project.open(export_store) as proj:
                    export_qdpx(proj, out, project_name=Path(export_store).stem)
                st.session_state["qdpx_export_bytes"] = out.read_bytes()
                st.session_state["qdpx_export_name"] = out.name
                st.success(f"Built {out.name} ({out.stat().st_size / 1024:.0f} KB).")
            except Exception as exc:  # noqa: BLE001
                st.error(f"Export failed: {exc}")

        if st.session_state.get("qdpx_export_bytes"):
            st.download_button(
                f"Download {st.session_state['qdpx_export_name']}",
                data=st.session_state["qdpx_export_bytes"],
                file_name=st.session_state["qdpx_export_name"],
                mime="application/zip", key="qdpx_export_dl")

    st.subheader("Merge another project (.qnw)")
    st.caption(
        "A colleague coded in their own copy of this project? Merge their **human** "
        "codings and emergent codes into the active project. Responses are matched by "
        "response id + question (never internal ids); their coders stay distinct; codes "
        "match by exact name, and near-name pairs are *suggested* for you to merge in "
        "the Codebook page — never merged automatically. Machine codings are not "
        "imported. Re-merging an updated file replaces (doesn't duplicate) their codes."
    )
    merge_store = active_project_path()
    if merge_store is None or not Path(merge_store).exists():
        st.info("Select an active project above first.")
    else:
        uploaded_qnw = st.file_uploader("Colleague's project file (.qnw)", type=["qnw"],
                                        key="merge_qnw_upload")
        if uploaded_qnw is not None and st.button("Merge into active project", key="merge_qnw_btn"):
            try:
                from core.store_merge import merge_project_stores
                tmp = Path(merge_store).parent / f"_incoming_{uploaded_qnw.name}"
                tmp.write_bytes(uploaded_qnw.getvalue())
                result = merge_project_stores(merge_store, tmp)
                tmp.unlink(missing_ok=True)
                msg = (f"Merged {result['matched']} coding(s) from "
                       f"{len(result['raters_merged'])} coder(s); "
                       f"created {len(result['codes_created'])} new code(s).")
                st.success(msg + " (The store was backed up first.)")
                if result["near_name_suggestions"]:
                    pairs = "; ".join(f"'{a}' ≈ '{b}'" for a, b in result["near_name_suggestions"])
                    st.warning(f"Possible duplicate codes to review and merge in the "
                               f"Codebook page: {pairs}")
                if result["unmatched_responses"]:
                    st.warning(f"{len(result['unmatched_responses'])} coding(s) had no matching "
                               f"response in this project (different dataset?): "
                               f"{', '.join(result['unmatched_responses'][:8])}…")
            except Exception as exc:  # noqa: BLE001
                st.error(f"Merge failed: {exc}")

    # ── Backups (v3.8) ────────────────────────────────────────────────────────
    render_backup_section()

    # ── Project portability (v3.8: surfaces export_json / import_json) ───────
    render_project_json_section()

    # ── Purge ─────────────────────────────────────────────────────────────────
    st.subheader("Purge a project")
    st.caption("Delete an entire project directory — store, run outputs, and caches.")
    if store is not None and Path(store).exists():
        project_dir = Path(store).parent
        st.write(f"Would delete: `{project_dir}`")
        typed = st.text_input(f"Type the folder name (`{project_dir.name}`) to confirm",
                              key="purge_confirm_text")
        if st.button("Purge project permanently", key="purge_btn",
                     disabled=(typed != project_dir.name)):
            try:
                from core.erasure import purge_project
                result = purge_project(project_dir)
                st.session_state["active_project_path"] = ""
                st.success(f"Purged `{result['path']}` ({result.get('files_removed', 0)} files).")
                st.rerun()
            except Exception as exc:  # noqa: BLE001
                st.error(f"Purge failed: {exc}")

    render_working_data_panel()
