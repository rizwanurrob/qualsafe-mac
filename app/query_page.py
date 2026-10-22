#!/usr/bin/env python
"""
Query & Synthesis page (v4, Phase 3).

Where coding turns into findings: retrieve passages by code logic, cross-tabulate
any two axes, and build a **framework matrix** — cases × themes, each cell
summarising what that case said about that theme.

Per `app/__init__`, this module imports only from `core/`, `analysis/`, and
Streamlit — never from `streamlit_app`.
"""

from __future__ import annotations

import html
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import pandas as pd
import streamlit as st
from app.shared.layout import stretch

from analysis.cooccurrence import cooccurrence_matrix
from analysis.crosstab import code_by_descriptor
from analysis.framework import (
    UNCASED, cell_excerpt_texts, draft_cell_summary, format_cell, framework_cells,
    framework_grid, get_cell_summary, set_cell_summary,
)
from analysis.query import QueryError, run_query
from core.model import Case, Memo
from core.project import Project

SAVED_QUERY_TYPE = "saved_query"
_MAX_SHOWN = 60


def render_query_page(store_path: Optional[Path]) -> None:
    st.header("Query & Synthesis")
    st.caption(
        "Retrieve passages by code logic, cross-tabulate any two axes, and build a "
        "framework matrix of cases against themes."
    )
    if store_path is None or not Path(store_path).exists():
        st.info("No active project. Pick one in Data Management, or run an analysis "
                "with the `.qnw` option enabled.")
        return

    with Project.open(store_path) as proj:
        coding = proj.coding_spans_table()
        if coding.empty:
            st.info("Nothing is coded in this project yet — code some passages first.")
            return
        t_query, t_matrix, t_framework, t_cases = st.tabs(
            ["Query", "Matrix", "Framework matrix", "Cases"])
        with t_query:
            _render_query_tab(proj, coding)
        with t_matrix:
            _render_matrix_tab(proj, coding)
        with t_framework:
            _render_framework_tab(proj, coding)
        with t_cases:
            _render_cases_tab(proj, coding)


# ── Query ───────────────────────────────────────────────────────────────────
def _render_query_tab(proj, coding: pd.DataFrame) -> None:
    st.caption(
        "Combine codes with **AND**, **OR**, **NOT**, brackets, and **NEAR/n** "
        "(within n characters). Put multi-word code names in \"quotes\"."
    )
    saved = proj.list_memos(target_type=SAVED_QUERY_TYPE)
    if saved:
        names = {m.text.split("\n", 1)[0]: m.text.split("\n", 1)[-1] for m in saved}
        pick = st.selectbox("Saved queries", ["(none)"] + list(names), key="q_saved")
        if pick != "(none)" and st.button("Load", key="q_load"):
            st.session_state["q_text"] = names[pick]
            st.rerun()

    text = st.text_input("Query", key="q_text",
                         placeholder='Cost AND NOT FirstGen     "Cost worry" NEAR/200 dropout')
    unit = st.radio(
        "Codes must co-occur within the same", ["excerpt", "source", "case"],
        horizontal=True, key="q_unit",
        help="Same passage = the same passage. Source = anywhere in the same document or "
             "response. Case = anywhere in the same person's material. The same "
             "query gives different answers at each — pick the one you mean.")

    if not text.strip():
        codes = sorted(set(coding["code_name"]))
        st.caption("Codes available: " + ", ".join(codes[:25])
                   + ("…" if len(codes) > 25 else ""))
        return

    try:
        result = run_query(coding, text, unit=unit)
    except QueryError as exc:
        st.error(str(exc))
        return

    if result["unknown_codes"]:
        st.warning("Not in this project's codebook: "
                   + ", ".join(f"`{c}`" for c in result["unknown_codes"])
                   + " — check the spelling, or quote a multi-word name.")
    st.success(f"**{len(result['unit_ids'])}** {unit}(s) match, "
               f"covering {len(result['excerpt_ids'])} passage(s).")

    s1, s2 = st.columns([3, 1])
    save_as = s1.text_input("Save this query as", key="q_save_name",
                            placeholder="e.g. Cost without first-gen")
    if s2.button("Save", key="q_save_btn", disabled=not save_as.strip()):
        proj.add_memo(Memo(memo_id="", target_type=SAVED_QUERY_TYPE, target_id="",
                           text=f"{save_as.strip()}\n{text}", author="human"))
        st.success("Saved.")
        st.rerun()

    _show_excerpt_list(proj, coding, result["excerpt_ids"])


def _show_excerpt_list(proj, coding: pd.DataFrame, excerpt_ids: List[str]) -> None:
    if not excerpt_ids:
        return
    st.subheader("Passages")
    if len(excerpt_ids) > _MAX_SHOWN:
        st.caption(f"Showing the first {_MAX_SHOWN} of {len(excerpt_ids)}.")
    codes_by_excerpt = (coding.groupby("excerpt_id")["code_name"]
                        .apply(lambda s: sorted(set(s))).to_dict())
    rows = []
    for excerpt_id in excerpt_ids[:_MAX_SHOWN]:
        excerpt = proj.get_excerpt(excerpt_id)
        if excerpt is None:
            continue
        rows.append({"text": excerpt.text,
                     "codes": ", ".join(codes_by_excerpt.get(excerpt_id, []))})
    if rows:
        st.dataframe(pd.DataFrame(rows), **stretch(), hide_index=True)
        st.download_button("Download these passages (.csv)",
                           data=pd.DataFrame(rows).to_csv(index=False),
                           file_name="query_results.csv", mime="text/csv", key="q_dl")


# ── Matrix ──────────────────────────────────────────────────────────────────
def _render_matrix_tab(proj, coding: pd.DataFrame) -> None:
    st.caption("Cross-tabulate codes against another axis. Every cell is a count "
               "of distinct items, so a code applied twice to one item counts once.")
    descriptors = proj.descriptor_table()
    keys = sorted(set(descriptors["key"])) if not descriptors.empty else []
    axes = ["Code × Code"] + (["Code × respondent detail"] if keys else []) + ["Code × Case"]
    axis = st.selectbox("Axes", axes, key="mx_axis")

    if axis == "Code × Code":
        matrix, _drill = cooccurrence_matrix(proj.coding_table())
        st.caption("How often two codes are applied to the same passage.")
        table = matrix
    elif axis == "Code × respondent detail":
        key = st.selectbox("Group by", keys, key="mx_desc")
        normalize = st.checkbox(
            "Show as prevalence within each group", value=False, key="mx_norm",
            help="Normalises by group size, so a large subgroup doesn't look more "
                 "themed simply for being large.")
        table, _drill = code_by_descriptor(
            proj.coding_table(), descriptors, key,
            normalize="group_size" if normalize else None)
    else:
        cased = coding[coding["case_id"] != ""]
        if cased.empty:
            st.info("No documents are assigned to a case yet — see the Cases tab.")
            return
        table = (cased.drop_duplicates(["excerpt_id", "code_name", "case_name"])
                 .pivot_table(index="code_name", columns="case_name",
                              values="excerpt_id", aggfunc="count", fill_value=0))
    if table is None or getattr(table, "empty", True):
        st.info("Nothing to show for these axes yet.")
        return
    st.dataframe(table, **stretch())
    st.download_button("Download matrix (.csv)", data=table.to_csv(),
                       file_name="matrix.csv", mime="text/csv", key="mx_dl")


# ── Framework matrix ────────────────────────────────────────────────────────
def _ollama_generate(model: str) -> Callable[[str, Dict[str, Any]], Dict[str, Any]]:
    """A `generate_json(prompt, schema)` backed by the local Ollama server."""
    from engines.ollama_client import OllamaClient

    client = OllamaClient()

    def _generate(prompt: str, schema: Dict[str, Any]) -> Dict[str, Any]:
        return client.generate_json(model, prompt, schema)

    return _generate


def _render_framework_tab(proj, coding: pd.DataFrame) -> None:
    st.caption(
        "Cases down the side, themes across the top; each cell says what that case "
        "said about that theme. Cells can be drafted by the local language model — every quote "
        "it offers is checked verbatim against the source, and anything it altered "
        "is dropped. Drafts are yours to edit."
    )
    all_codes = sorted(set(coding["code_name"]))
    cases = proj.list_cases()
    include_uncased = st.checkbox(
        "Include material with no case", value=not cases, key="fw_uncased",
        help="Gathers everything not assigned to a case under one row, so it isn't "
             "invisible.")
    if not cases and not include_uncased:
        st.info("No cases yet — create some in the Cases tab, or tick the box above.")
        return

    codes = st.multiselect("Themes (columns)", all_codes,
                           default=all_codes[:6], key="fw_codes")
    if not codes:
        st.info("Pick at least one theme.")
        return

    cells = framework_cells(coding, code_names=codes, include_uncased=include_uncased)
    labels = {c.case_id: c.name for c in cases}
    if include_uncased:
        labels[UNCASED] = UNCASED
    grid = framework_grid(cells, labels, codes)
    st.dataframe(grid, **stretch(), hide_index=True)
    st.download_button("Download grid (.csv)", data=grid.to_csv(index=False),
                       file_name="framework_matrix.csv", mime="text/csv", key="fw_dl")

    st.divider()
    st.subheader("Cell")
    c1, c2 = st.columns(2)
    case_label = c1.selectbox("Case", [labels[k] for k in labels], key="fw_case")
    code_name = c2.selectbox("Theme", codes, key="fw_code")
    case_id = next(k for k, v in labels.items() if v == case_label)

    excerpt_ids = cells.get((case_id, code_name), [])
    st.caption(f"{len(excerpt_ids)} passage(s) coded **{code_name}** for **{case_label}**.")
    passages = cell_excerpt_texts(proj, excerpt_ids)
    if passages:
        with st.expander("The passages behind this cell", expanded=False):
            for text in passages[:20]:
                st.markdown(f"> {html.escape(text[:400])}")

    stored = get_cell_summary(proj, case_id, code_name)
    draft_key = f"fw_draft_{case_id}_{code_name}"
    if st.button("Draft this cell with the local language model", key="fw_draft_btn",
                 disabled=not passages,
                 help="Requires Ollama running. The draft is not saved until you save it."):
        model = str(st.session_state.get("llm_model", "llama3.2:3b"))
        with st.spinner(f"Drafting with {model}…"):
            out = draft_cell_summary(
                passages, code_name=code_name, case_label=case_label,
                generate_json=_ollama_generate(model))
        if out["note"] != "ok":
            st.error(f"Could not draft: {out['note']}")
        else:
            if out["dropped"]:
                st.warning(f"{out['dropped']} proposed quote(s) were not verbatim in the "
                           f"passages and were dropped.")
            st.session_state[draft_key] = format_cell(out["summary"], out["quotes"])
            st.rerun()

    initial = st.session_state.pop(draft_key, None)
    if initial is None:
        initial = stored.text if stored is not None else ""
    else:
        st.info("Draft below — review and edit before saving. Nothing is saved yet.")
    edited = st.text_area("Cell summary", value=initial, height=180, key="fw_text")
    if st.button("Save cell", key="fw_save"):
        set_cell_summary(proj, case_id, code_name, edited,
                         author=str(st.session_state.get("analyst_name", "")) or "human")
        st.success("Saved.")
        st.rerun()


# ── Cases ───────────────────────────────────────────────────────────────────
def _render_cases_tab(proj, coding: pd.DataFrame) -> None:
    st.caption("A case is the person, site, or group a document or response belongs "
               "to — the row of a framework matrix.")
    cases = proj.list_cases()
    if cases:
        counts = {c.case_id: len(proj.case_sources(c.case_id)) for c in cases}
        st.dataframe(pd.DataFrame([{"case": c.name, "kind": c.kind,
                                    "sources": counts[c.case_id]} for c in cases]),
                     **stretch(), hide_index=True)
    else:
        st.info("No cases yet.")

    c1, c2, c3 = st.columns([2, 1, 1])
    name = c1.text_input("New case", key="cs_name")
    kind = c2.selectbox("Kind", ["person", "site", "group"], key="cs_kind")
    if c3.button("Create", key="cs_create", disabled=not name.strip()):
        proj.add_case(Case(case_id="", name=name.strip(), kind=kind))
        st.rerun()

    st.divider()
    st.subheader("Create cases in bulk")
    st.caption("Turn a respondent detail (or the wide-form respondent id) into one case per "
               "value, assigning every source automatically — the quick way to make "
               "survey data case-based.")
    descriptors = proj.descriptor_table()
    options = sorted(set(descriptors["key"])) if not descriptors.empty else []
    has_respondents = (coding["respondent_id"] != "").any()
    if has_respondents:
        options = ["respondent_id"] + options
    if not options:
        st.caption("No respondent details or respondent ids in this project.")
        return
    b1, b2 = st.columns([3, 1])
    field = b1.selectbox("Field", options, key="cs_bulk_field")
    if b2.button("Create cases", key="cs_bulk_btn"):
        made = _bulk_create_cases(proj, coding, descriptors, field)
        st.success(f"Created or updated {made} case(s) from `{field}`.")
        st.rerun()


def _bulk_create_cases(proj, coding: pd.DataFrame, descriptors: pd.DataFrame,
                       field: str) -> int:
    """One case per distinct value of `field`, with its sources assigned."""
    if field == "respondent_id":
        pairs = (coding[coding["respondent_id"] != ""][["respondent_id", "source_id"]]
                 .drop_duplicates().values.tolist())
    else:
        subset = descriptors[descriptors["key"] == field]
        pairs = subset[["value", "source_id"]].drop_duplicates().values.tolist()

    by_value: Dict[str, List[str]] = {}
    for value, source_id in pairs:
        if str(value).strip():
            by_value.setdefault(str(value), []).append(source_id)

    existing = {c.name: c.case_id for c in proj.list_cases()}
    for value, source_ids in by_value.items():
        label = f"{field}: {value}" if field != "respondent_id" else str(value)
        case_id = existing.get(label) or proj.add_case(Case(case_id="", name=label))
        existing[label] = case_id
        for source_id in source_ids:
            proj.assign_source_to_case(case_id, source_id)
    return len(by_value)
