"""
The codebook: edit, merge, similarity suggestions, health, versions.

Extracted from the former monolithic `streamlit_app.py` (v4, Phase 0.1).
Per `app/__init__`, this module imports only from `core/`, `analysis/`,
`exports/`, `app.shared`, and Streamlit — never from `streamlit_app`.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st
from app.shared.layout import stretch
from core.project import Project
from core.ux.fields import origin_label

from app.shared.projects import list_project_runs
from app.shared.widgets import render_memo_section


def render_codebook() -> None:
    st.caption("Your codes are yours to change: rename them, define them, group them, or merge two. "
               "Changes are saved in the project file.")
    runs = list_project_runs()
    if not runs:
        st.info("There is no project yet. Add transcripts, or run the analysis with 'Also save a project "
                "file (.qnw)' ticked.")
        return
    sel = st.selectbox("Project", [p.name for p in runs], key="cb_run")
    run_dir = next(p for p in runs if p.name == sel)
    with Project.open(run_dir / "project.qnw") as proj:
        codes = proj.get_codebook()
        if not codes:
            st.info("This project has no codes.")
            return
        freq = proj.code_frequency()
        name_by_id = {c.code_id: c.name for c in codes}
        overview = pd.DataFrame([{
            "Code": c.name, "Definition": c.definition,
            "Part of": name_by_id.get(c.parent_id, ""), "Where it came from": origin_label(c.origin),
            "Times used": freq.get(c.code_id, 0),
        } for c in codes])
        st.dataframe(overview, **stretch(), hide_index=True)

        st.divider()
        st.subheader("Edit a code")
        by_id = {c.code_id: c for c in codes}
        pick = st.selectbox("Code", [c.code_id for c in codes],
                            format_func=lambda cid: name_by_id[cid], key="cb_pick")
        cur = by_id[pick]
        new_name = st.text_input("Name", value=cur.name, key="cb_name")
        new_def = st.text_area("Definition", value=cur.definition, key="cb_def", height=80)
        parent_opts = ["(none)"] + [c.code_id for c in codes if c.code_id != pick]
        p_idx = parent_opts.index(cur.parent_id) if cur.parent_id in parent_opts else 0
        new_parent = st.selectbox("Parent code", parent_opts, index=p_idx,
                                  format_func=lambda cid: "(none)" if cid == "(none)" else name_by_id[cid],
                                  key="cb_parent")
        if st.button("Save code changes", key="cb_save"):
            try:
                proj.rename_code(pick, new_name)
                proj.set_code_definition(pick, new_def)
                proj.set_code_parent(pick, None if new_parent == "(none)" else new_parent)
                st.success("Saved.")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

        # Per-code memos — the analyst's reasoning about this theme.
        render_memo_section(run_dir / "project.qnw", "code", pick,
                            title=f"Memos on '{name_by_id[pick]}'")

        with st.expander("More options"):
            st.divider()
            st.subheader("Merge codes")
            st.caption("Merge one code into another: its applications move over and it's removed. Useful when "
                       "co-occurrence shows two codes are really the same theme.")
            m1, m2 = st.columns(2)
            merge_from = m1.selectbox("Merge this code…", [c.code_id for c in codes],
                                      format_func=lambda cid: name_by_id[cid], key="cb_from")
            into_opts = [c.code_id for c in codes if c.code_id != merge_from]
            merge_into = m2.selectbox("…into this code", into_opts,
                                      format_func=lambda cid: name_by_id[cid], key="cb_into")
            if st.button("Merge", key="cb_merge"):
                try:
                    proj.merge_codes(merge_from, merge_into)
                    st.success(f"Merged '{name_by_id[merge_from]}' into '{name_by_id[merge_into]}'.")
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))

            # ── Possible duplicate codes (v3.9.6, F1) ──────────────────────────────
            st.divider()
            st.subheader("Possible duplicate codes")
            st.caption(
                "Suggestions from meaning, not spelling: codes whose name + definition "
                "are semantically similar (e.g. 'Cost worry' ≈ 'Financial stress'). "
                "Especially useful after merging a colleague's codes. Nothing is merged "
                "automatically — review each pair and merge if you agree."
            )
            if st.button("Find similar codes", key="cb_sim_find",
                         help="Uses the local similarity model (offline) to compare codes."):
                from analyze_survey import ModelNotDownloadedError      # heavy: loaded when first needed
                try:
                    from analysis.code_similarity import embed_with_model, similar_code_pairs
                    model_name = st.session_state.get(
                        "adv_embedding_model", "sentence-transformers/all-MiniLM-L6-v2")
                    st.session_state["cb_sim_pairs"] = similar_code_pairs(
                        codes, lambda t: embed_with_model(t, model_name), threshold=0.80)
                except ModelNotDownloadedError as exc:
                    st.warning(str(exc))
                except Exception as exc:  # noqa: BLE001
                    st.error(f"Similarity check failed: {exc}")
            sim_pairs = st.session_state.get("cb_sim_pairs")
            if sim_pairs is not None:
                if not sim_pairs:
                    st.info("No code pairs cleared the similarity threshold.")
                for k, pair in enumerate(sim_pairs):
                    pc1, pc2 = st.columns([3, 1])
                    pc1.markdown(
                        f"**{pair['name_a']}** ≈ **{pair['name_b']}**  "
                        f"(similarity {pair['similarity']:.2f})")
                    if pc2.button(f"Merge → '{pair['name_b']}'", key=f"cb_sim_merge_{k}"):
                        try:
                            proj.merge_codes(pair["code_id_a"], pair["code_id_b"])
                            st.session_state.pop("cb_sim_pairs", None)
                            st.success(f"Merged '{pair['name_a']}' into '{pair['name_b']}'.")
                            st.rerun()
                        except ValueError as exc:
                            st.error(str(exc))

            # ── Codebook health (v3.9.6, F3) ───────────────────────────────────────
            st.divider()
            st.subheader("Codebook health")
            st.caption(
                "Hygiene checks over the codebook — most useful after a merge adds "
                "emergent codes. Fix any of these with the controls above (define, "
                "merge, or delete)."
            )
            from analysis.codebook_health import codebook_health
            health = codebook_health(codes, freq)
            if health["is_clean"]:
                st.success("No issues found — every code is applied and defined.")
            else:
                hc = health["counts"]
                m1, m2, m3, m4, m5 = st.columns(5)
                m1.metric("Dead (0 uses)", hc["dead"])
                m2.metric("Used once", hc["singletons"])
                m3.metric("Undefined", hc["undefined"])
                m4.metric("Orphan parent", hc["orphans"])
                m5.metric("Too deep", hc["too_deep"])
                for label, key in [("Never applied", "dead"), ("Applied once", "singletons"),
                                   ("Missing a definition", "undefined"),
                                   ("Parent code missing", "orphans"),
                                   ("Nested very deep", "too_deep")]:
                    if health[key]:
                        names = ", ".join(d["name"] for d in health[key])
                        st.caption(f"**{label}:** {names}")

            # ── Version history (v3.8: surfaces the v3.5 snapshot backend) ─────────
            st.divider()
            st.subheader("Version history")
            st.caption("The codebook snapshots itself before every merge, delete, or reparent — "
                       "so those edits are undoable. Tag a version before a big reorganization.")
            tag_col1, tag_col2 = st.columns([3, 1])
            tag_note = tag_col1.text_input("Tag the current codebook", key="cb_tag_note",
                                           placeholder="e.g. before spring reorg",
                                           label_visibility="collapsed")
            if tag_col2.button("Tag version", key="cb_tag_btn",
                               help="Saves a named snapshot of the codebook as it is right now."):
                proj.tag_codebook_version(tag_note or "manual tag")
                st.success("Tagged.")
                st.rerun()

            versions = proj.list_codebook_versions()
            if versions:
                st.dataframe(pd.DataFrame(versions), **stretch(), hide_index=True)
                options = [v["version_id"] for v in versions]
                fmt = {v["version_id"]: f"{v['created_at']} · {v['trigger']}"
                                        + (f" · {v['note']}" if v["note"] else "")
                       for v in versions}
                pick_v = st.selectbox("Restore to version", options,
                                      format_func=lambda vid: fmt[vid], key="cb_restore_pick",
                                      help="Restores the codebook to this snapshot. Codes that "
                                           "exist in both keep their codings; codes added after "
                                           "the snapshot are removed (with their codings). The "
                                           "current state is snapshotted first, so a restore is "
                                           "itself undoable.")
                if st.button("Restore codebook to this version", key="cb_restore_btn"):
                    try:
                        from core.backups import backup_store
                        backup_store(run_dir / "project.qnw", reason="pre_codebook_restore")
                        proj.restore_codebook_version(pick_v)
                        st.success("Codebook restored.")
                        st.rerun()
                    except Exception as exc:  # noqa: BLE001
                        st.error(f"Restore failed: {exc}")
            else:
                st.caption("No snapshots yet — one is created automatically at your first "
                           "merge/delete/reparent.")

            # ── Share / reuse the codebook (v3.8.1) ────────────────────────────────
            st.divider()
            st.subheader("Share / reuse this codebook")
            st.caption("Names, definitions, and hierarchy — no data. Two formats: YAML "
                       "to read and diff yourself, and REFI-QDA to exchange with NVivo, "
                       "MAXQDA, ATLAS.ti, QDA Miner or Quirkos.")
            from core.codebook_io import codebook_label_list, export_codebook_yaml, import_codebook_yaml
            from core.refi_qda import export_codebook_qdc, import_codebook_qdc

            dl1, dl2 = st.columns(2)
            yaml_text = export_codebook_yaml(proj)
            dl1.download_button("Download codebook.yaml", data=yaml_text,
                                file_name="codebook.yaml", mime="text/yaml", key="cb_yaml_dl",
                                help="Human-readable and diffable. QualSafe's own format.")
            # The REFI-QDA format cannot express an empty codebook — `CodesType`
            # requires at least one code — so the exporter refuses rather than
            # writing a file NVivo would reject. Say that here instead of showing a
            # button that raises.
            try:
                qdc_text = export_codebook_qdc(proj)
            except ValueError as exc:
                qdc_text = ""
                dl2.caption(str(exc))
            if qdc_text:
                dl2.download_button(
                    "Download codebook.qdc", data=qdc_text,
                    file_name="codebook.qdc", mime="application/xml", key="cb_qdc_dl",
                    help="REFI-QDA, the open exchange standard. Import this into NVivo, "
                         "MAXQDA, ATLAS.ti and others — and it is what makes this codebook "
                         "archivable rather than trapped in one program.")

            uploaded_cb = st.file_uploader(
                "Import a codebook into this project",
                type=["yaml", "yml", "qdc"], key="cb_yaml_up",
                help="YAML or REFI-QDA (.qdc), including one exported from NVivo, MAXQDA "
                     "or ATLAS.ti. Additive either way: codes you already have (same "
                     "name) are left untouched and reported, never overwritten.")
            if uploaded_cb is not None:
                imported_text = uploaded_cb.getvalue().decode("utf-8", errors="replace")
                # Chosen by extension, not by sniffing the bytes: an analyst who
                # renames a file is telling us something, and a wrong guess here
                # silently imports nothing.
                is_qdc = Path(uploaded_cb.name).suffix.lower() == ".qdc"
                import_fn = import_codebook_qdc if is_qdc else import_codebook_yaml
                col_imp1, col_imp2 = st.columns(2)
                if col_imp1.button("Import into codebook", key="cb_yaml_import"):
                    try:
                        result = import_fn(proj, imported_text)
                        msg = (f"Created {len(result['created'])} code(s); "
                               f"skipped {len(result['skipped_existing'])} already present.")
                        if result["parents_unresolved"]:
                            msg += f" Unresolved parents: {', '.join(result['parents_unresolved'])}."
                        st.success(msg)
                        st.rerun()
                    except ValueError as exc:
                        st.error(str(exc))
                if col_imp2.button("Use as Theme Setup labels", key="cb_yaml_labels",
                                   help="Loads the file's code names into Theme Setup as your "
                                        "label set (does not change this codebook)."):
                    try:
                        st.session_state["theme_labels_text"] = "\n".join(
                            codebook_label_list(imported_text))
                        st.success("Labels loaded into Theme Setup.")
                    except ValueError as exc:
                        st.error(str(exc))
