#!/usr/bin/env python
"""
Documents page: import a corpus, browse it, and read it with coding stripes
(v4, Phase 2a).

The half of qualitative work QualSafe could not do: put a folder of transcripts,
field notes, and reports into a project, then actually *read* them in the tool
with the coding visible in the margin.

Per `app/__init__`, this module imports only from `core/`, `analysis/`, and
Streamlit — never from `streamlit_app`.
"""

from __future__ import annotations

import hashlib
import html
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
import streamlit as st
from app.shared.layout import stretch

from core.documents import (
    DOCUMENT_TYPE, coding_density, coding_spans, document_table, import_documents,
    list_documents_in_folder, read_document, read_document_bytes, segment_by_spans,
)
from core.project import Project
from core.theme import DEFAULT_CATEGORY_PALETTE, category_colors
from privacy.scan import scan_frame, summarize_findings

# Characters shown per page in the reader. A 40-page transcript rendered in one
# go makes every rerun sluggish; paging keeps reading responsive.
_READER_PAGE_CHARS = 6000


def render_documents_page(store_path: Optional[Path], part: str = "all") -> None:
    """Transcripts. `part` is "add" (Interviews, step 1: bring them in), "code" (step 2: read them
    with your coding in the margin, and code them) or "all" (the three tabs, as before)."""
    if store_path is None or not Path(store_path).exists():
        _render_no_project(part)
        return

    with Project.open(store_path) as proj:
        if part == "add":
            _render_library(proj)
        elif part == "code":
            tab_read, tab_code = st.tabs(["Read", "Code"])
            with tab_read:
                _render_reader(proj)
            with tab_code:
                _render_coding(proj)
        else:
            tab_library, tab_read, tab_code = st.tabs(["Library", "Read", "Code"])
            with tab_library:
                _render_library(proj)
            with tab_read:
                _render_reader(proj)
            with tab_code:
                _render_coding(proj)


def _render_no_project(part: str) -> None:
    """No project yet: for the add step, start one here, so a person can begin with their files."""
    if part != "add":
        st.info("Add transcripts first, on the Add transcripts step.")
        return
    from datetime import datetime

    from app.shared import constants

    st.info("Transcripts are kept in a project file. Start one to add them.")
    name = st.text_input("Name for the project", value="My interviews", key="doc_new_project_name")
    if st.button("Start a project", key="doc_new_project_btn", type="primary", disabled=not name.strip()):
        folder = constants.STREAMLIT_OUTPUT_DIR / ("interviews_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
        folder.mkdir(parents=True, exist_ok=True)
        Project.create(folder / "project.qnw").close()
        st.session_state["active_project_path"] = str((folder / "project.qnw").resolve())
        st.rerun()


# ── Library + import ────────────────────────────────────────────────────────
def _selection_signature(names: List[str]) -> str:
    return hashlib.sha256("|".join(sorted(names)).encode("utf-8")).hexdigest()[:16]


def _render_library(proj) -> None:
    st.subheader("Add your transcripts")
    st.caption("Plain text, Markdown, Word or PDF files. A scanned PDF has no text to read, so it is "
               "reported rather than added silently.")

    mode = st.radio("Add from", ["A folder on this computer", "Upload files"],
                    horizontal=True, key="doc_add_mode")

    pending: List[Any] = []      # paths or (name, bytes)
    names: List[str] = []
    if mode.startswith("A folder"):
        folder = st.text_input("Folder path", key="doc_folder",
                               placeholder=r"C:\Users\you\Documents\Interviews")
        if folder.strip():
            found = list_documents_in_folder(folder)
            if not found:
                st.info("No supported documents found in that folder.")
            else:
                picked = st.multiselect(
                    "Files to import", [p.name for p in found],
                    default=[p.name for p in found], key="doc_folder_pick")
                by_name = {p.name: p for p in found}
                pending = [by_name[n] for n in picked]
                names = picked
    else:
        uploads = st.file_uploader(
            "Documents", type=["txt", "md", "docx", "pdf"],
            accept_multiple_files=True, key="doc_uploads")
        if uploads:
            pending = [(u.name, u.getvalue()) for u in uploads]
            names = [u.name for u in uploads]

    if pending:
        _render_import_gate(proj, pending, names)

    for kind, message in st.session_state.pop("doc_import_notes", []):
        getattr(st, kind)(message)
    st.divider()
    st.subheader("In this project")
    table = document_table(proj)
    if table.empty:
        st.info("No transcripts yet.")
        return
    st.caption(f"{len(table)} document(s), {int(table['words'].sum()):,} words.")
    st.dataframe(table.drop(columns=["source_id"]), **stretch(), hide_index=True)
    _render_speaker_check(proj, table)
    _render_case_assignment(proj, table)


def _render_import_gate(proj, pending: List[Any], names: List[str]) -> None:
    """Read the selection, scan it for PII, and import only after attestation."""
    sig = _selection_signature(names)
    st.markdown(f"**{len(pending)} file(s) selected.**")

    if st.button("Check for PII and preview", key="doc_scan_btn"):
        texts, failed = [], []
        for item in pending:
            try:
                if isinstance(item, Path):
                    texts.append((item.name, read_document(item)))
                else:
                    texts.append((item[0], read_document_bytes(item[0], item[1])))
            except Exception as exc:  # noqa: BLE001
                failed.append((item if isinstance(item, str) else getattr(item, "name", str(item)), str(exc)))
        st.session_state["doc_scan"] = {
            "sig": sig,
            "preview": [(n, len(t.split()), t[:200]) for n, t in texts],
            "findings": scan_frame(pd.DataFrame({"text": [t for _n, t in texts]})),
            "failed": failed,
        }

    scan = st.session_state.get("doc_scan")
    if not scan or scan.get("sig") != sig:
        st.caption("Run the check to see a preview and the PII scan before importing.")
        return

    for name, err in scan["failed"]:
        st.error(f"{name}: {err}")
    st.caption(summarize_findings(scan["findings"]))
    if scan["findings"]:
        st.dataframe(pd.DataFrame(scan["findings"]), **stretch(), hide_index=True)
        st.caption("Rough checks, not a verdict — they miss a name written mid-sentence "
                   "and flag harmless numbers. Your review is what this gate records.")
    with st.expander("Preview the first lines of each file"):
        for name, words, head in scan["preview"]:
            st.markdown(f"**{name}** — {words:,} words")
            st.caption(head.replace("\n", " ")[:200] + "…")

    cases = proj.list_cases()
    case_pick = "(none)"
    if cases:
        case_pick = st.selectbox("Assign all to case (optional)",
                                 ["(none)"] + [c.name for c in cases], key="doc_import_case")
    confirmed = st.checkbox(
        "I confirm these documents have been reviewed and are appropriate to process "
        "locally on this machine", key="doc_pii_confirm")
    if confirmed:
        st.session_state["doc_confirmed_sig"] = sig

    ready = st.session_state.get("doc_confirmed_sig") == sig
    if confirmed and not ready:
        st.warning("The selection changed — please re-confirm.")
    if st.button(f"Import {len(pending)} document(s)", key="doc_import_btn", type="primary", disabled=not ready):
        case_id = None
        if cases and case_pick != "(none)":
            case_id = next(c.case_id for c in cases if c.name == case_pick)
        result = import_documents(proj, pending, case_id=case_id)
        # The page reruns to show the new list, which would wipe a message written here: keep it
        # in the session and show it after the rerun.
        notes = []
        if result["imported"]:
            notes.append(("success", f"Imported {len(result['imported'])} document(s)."))
        if result["skipped"]:
            notes.append(("info", f"Skipped {len(result['skipped'])} already in the project: "
                          + ", ".join(result["skipped"])))
        notes.extend(("error", f"{name}: {err}") for name, err in result["failed"])
        st.session_state["doc_import_notes"] = notes
        st.session_state.pop("doc_scan", None)
        st.session_state.pop("doc_confirmed_sig", None)
        st.rerun()


def _render_speaker_check(proj, table: pd.DataFrame) -> None:
    """'Who is speaking?' for the next transcript with two or more speakers (as the desktop asks after an import).

    QualSafe proposes who the interviewer is from the shape of the transcript, but a wrong guess would quietly
    change what counts as the participant's words, so nothing is kept until the person presses *Use these roles*.
    *Skip* leaves the transcript exactly as it was."""
    from core import speakers

    skipped = st.session_state.setdefault("doc_speakers_skipped", set())
    single = st.session_state.setdefault("doc_speakers_single", set())
    review = None
    for title, source_id in zip(table["title"], table["source_id"]):
        if source_id in skipped or source_id in single:
            continue
        source = proj.get_source(source_id)
        if source is None or speakers.stored(source.metadata):
            continue
        found = speakers.analyse(source.raw_text or "")
        if found.needs_roles:
            review, name, target = found, title, source_id
            break
        single.add(source_id)
    if review is None:
        if skipped:
            with st.expander("Transcripts you skipped"):
                st.caption(f"{len(skipped)} transcript(s) were left as one block of text, with no speakers marked.")
                if st.button("Ask me again", key="doc_speakers_again"):
                    skipped.clear()
                    st.rerun()
        return
    with st.container(border=True):
        st.markdown(f"**Who is speaking in {name}?**")
        st.write(f"QualSafe found {review.n_turns} turns by {len(review.rows)} speakers. Check who is who: it "
                 "decides which words count as the participant's. " + (review.rationale or ""))
        st.dataframe(pd.DataFrame([{
            "Speaker": row.label, "Turns": row.turns, "Share of the words": f"{row.share:.0%}",
            "Questions asked": row.questions} for row in review.rows]), **stretch(), hide_index=True)
        roles = {}
        for row in review.rows:
            roles[row.label] = st.selectbox(
                f"Who is {row.label}?", list(speakers.ROLES), key=f"spk_{target}_{row.label}",
                index=speakers.ROLES.index(row.role) if row.role in speakers.ROLES else 2,
                format_func=lambda role: speakers.ROLE_NAMES[role])
        if review.preview:
            with st.expander("The first turns"):
                for label, start in review.preview:
                    st.markdown(f"**{label}:** {start}")
        use, skip = st.columns(2)
        if use.button("Use these roles", key=f"spk_use_{target}", type="primary"):
            proj.update_source_metadata(target, {"speakers": speakers.to_metadata(review, roles)})
            st.session_state["doc_import_notes"] = [("success", f"Saved who is speaking in {name}.")]
            st.rerun()
        if skip.button("Skip", key=f"spk_skip_{target}"):
            skipped.add(target)
            st.rerun()


def _render_case_assignment(proj, table: pd.DataFrame) -> None:
    with st.expander("Assign a document to a case"):
        st.caption("A case is the person, site, or group a document belongs to — "
                   "so analyses can be reported per case rather than per file.")
        c1, c2 = st.columns(2)
        new_case = c1.text_input("New case name", key="doc_new_case")
        if c2.button("Create case", key="doc_new_case_btn", disabled=not new_case.strip()):
            from core.model import Case
            proj.add_case(Case(case_id="", name=new_case.strip()))
            st.rerun()
        cases = proj.list_cases()
        if not cases:
            st.caption("No cases yet — create one above.")
            return
        titles = dict(zip(table["title"], table["source_id"]))
        d1, d2, d3 = st.columns([2, 2, 1])
        doc_pick = d1.selectbox("Document", list(titles), key="doc_assign_doc")
        case_pick = d2.selectbox("Case", [c.name for c in cases], key="doc_assign_case")
        if d3.button("Assign", key="doc_assign_btn"):
            cid = next(c.case_id for c in cases if c.name == case_pick)
            proj.assign_source_to_case(cid, titles[doc_pick])
            st.success(f"`{doc_pick}` assigned to **{case_pick}**.")
            st.rerun()


# ── Reader ──────────────────────────────────────────────────────────────────
def _code_colors(code_names: List[str]) -> Dict[str, str]:
    """Stable colour per code, from the active skin and chosen categorical palette.

    The **extended** list, not the palette's own six: in the reader's margin
    colour is the only identifier a code has, so a seventh code wrapping to the
    first makes two codes literally indistinguishable.
    """
    palette = category_colors(
        st.session_state.get("theme_mode", "dark"),
        st.session_state.get("category_palette", DEFAULT_CATEGORY_PALETTE))
    return {name: palette[i % len(palette)] for i, name in enumerate(sorted(code_names))}


def _render_reader(proj) -> None:
    table = document_table(proj)
    if table.empty:
        st.info("No documents to read yet — add some in the Library tab.")
        return

    titles = dict(zip(table["title"], table["source_id"]))
    pick = st.selectbox("Document", list(titles), key="reader_doc")
    source_id = titles[pick]
    source = proj.get_source(source_id)
    if source is None:
        st.warning("That document is no longer in the project.")
        return
    text = source.raw_text or ""

    all_spans = coding_spans(proj, source_id)
    all_codes = sorted({c for s in all_spans for c in s["codes"]})
    raters = sorted({r for s in all_spans for r in s["raters"]})

    f1, f2 = st.columns(2)
    code_filter = f1.multiselect("Show codes", all_codes, default=all_codes,
                                 key="reader_codes") if all_codes else []
    rater_filter = f2.selectbox("Coder", ["(all)"] + raters, key="reader_rater") if raters else "(all)"

    spans = coding_spans(
        proj, source_id,
        rater_id=None if rater_filter == "(all)" else rater_filter,
        code_names=code_filter if all_codes else None,
    )

    m1, m2, m3 = st.columns(3)
    m1.metric("Words", f"{len(text.split()):,}")
    m2.metric("Coded passages", len(spans))
    m3.metric("Coverage", f"{coding_density(len(text), spans):.0%}")

    if all_codes:
        colors = _code_colors(all_codes)
        legend = "  ".join(
            f"<span style='background:{colors[c]};color:#fff;padding:1px 6px;"
            f"border-radius:3px;font-size:0.8em'>{html.escape(c)}</span>"
            for c in (code_filter or all_codes))
        st.markdown("**Codes:** " + legend, unsafe_allow_html=True)
    else:
        st.caption("Nothing coded in this document yet.")

    # Paged rendering: a long transcript re-rendered whole on every interaction
    # makes the page crawl.
    pages = max(1, (len(text) + _READER_PAGE_CHARS - 1) // _READER_PAGE_CHARS)
    page = 1
    if pages > 1:
        page = st.slider("Page", 1, pages, 1, key="reader_page",
                         help=f"{_READER_PAGE_CHARS:,} characters per page.")
    start = (page - 1) * _READER_PAGE_CHARS
    end = min(len(text), start + _READER_PAGE_CHARS)

    window = [s for s in spans if s["char_end"] > start and s["char_start"] < end]
    shifted = [{**s, "char_start": max(0, s["char_start"] - start),
                "char_end": min(end - start, s["char_end"] - start)} for s in window]
    st.markdown(_render_segments(text[start:end], shifted, all_codes),
                unsafe_allow_html=True)

    if spans:
        with st.expander("Coded passages in this document"):
            st.dataframe(
                pd.DataFrame([{
                    "chars": f"{s['char_start']}–{s['char_end']}",
                    "codes": ", ".join(s["codes"]),
                    "coder": ", ".join(s["raters"]),
                    "text": (text[s["char_start"]:s["char_end"]][:160]),
                } for s in spans]),
                **stretch(), hide_index=True)


# ── Coding ──────────────────────────────────────────────────────────────────
_UNITS_PER_PAGE = 10           # a screen: the sentences and the Apply button are in view together


def _render_coding(proj) -> None:
    """Apply codes to passages by hand — the defining act of qualitative analysis."""
    from core.span_coding import (
        HUMAN_RATER, apply_codes_to_span, apply_codes_to_units, codeable_units,
        locate_passage, remove_coding,
    )

    table = document_table(proj)
    if table.empty:
        st.info("No documents to code yet — add some in the Library tab.")
        return

    titles = dict(zip(table["title"], table["source_id"]))
    pick = st.selectbox("Document", list(titles), key="code_doc")
    source_id = titles[pick]
    source = proj.get_source(source_id)
    if source is None:
        st.warning("That document is no longer in the project.")
        return
    text = source.raw_text or ""
    analyst = str(st.session_state.get("analyst_name", "")).strip()
    st.caption(f"Coding as {analyst or 'you'}. Set your name under Settings so agreement can say who "
               "did the coding.")

    existing_codes = [c.name for c in proj.get_codebook()]
    with st.expander("More options"):
        method = st.radio("Choose the passage by", ["Picking sentences", "Pasting a passage"],
                          horizontal=True, key="code_method",
                          help="Picking uses the exact edges of each sentence. Pasting lets you code any "
                               "wording you copy out of the Read tab.")
        unit = st.radio("Pick whole", ["sentence", "paragraph"], horizontal=True, key="code_unit")
        use_selection = st.checkbox("Name a new code after the passage itself (in-vivo)", key="code_invivo",
                                    help="The words you select become the name of the new code.")
        _render_guide(proj, source_id)

    # ── the codes to apply (shared by both methods) ──
    for kind, message in st.session_state.pop("code_notes", []):
        getattr(st, kind)(message)
    chosen = st.multiselect("Codes to apply", existing_codes, key="code_codes")
    new_code = st.text_input("…or a new code", key="code_new", placeholder="Cost worry")

    if method.startswith("Picking"):
        _render_pick_and_code(proj, source_id, text, chosen, new_code, use_selection,
                              analyst, codeable_units, apply_codes_to_units, unit)
    else:
        _render_paste_and_code(proj, source_id, chosen, new_code, use_selection,
                               analyst, locate_passage, apply_codes_to_span)

    _render_my_codings(proj, source_id, text, analyst, remove_coding, HUMAN_RATER)

    # Agreement on span coding compares only finished documents: in one you are
    # still working through, the sentences you have not reached would count as
    # "no code applies" (review finding F4).
    finished = source_id in proj.documents_coded_by(HUMAN_RATER)
    ticked = st.checkbox(
        "I've finished coding this document", value=finished, key=f"code_done_{source_id}",
        help="Two coders' agreement is computed only on documents both have finished.")
    if ticked != finished:
        proj.mark_document_coded(HUMAN_RATER, source_id, coded=ticked)


def guide_embedder():
    """The embedder the guide matching uses (replaced in tests)."""
    from interview.matching import default_embed_fn

    return default_embed_fn()


def _guide_unavailable() -> str:
    """Why the matching cannot run on this computer yet, or an empty string."""
    from core.model_readiness import missing_models
    from tools.setup_laya_env import has_engine

    if not has_engine():
        return ("Matching needs the analysis engine, which is not installed. "
                "Open Settings, then Models, to install it. Hand coding does not need it.")
    embedding = "sentence-transformers/all-MiniLM-L6-v2"
    if missing_models({"models": {"embedding_model": embedding}, "sentiment": {"enabled": False}}):
        return ("Matching needs a small language model that is not on this computer yet. "
                "Open Settings, then Models, to download it once.")
    return ""


def _render_guide(proj, source_id: str) -> None:
    """Suggest codes from an interview guide (the desktop's Code step, More options)."""
    from core import guide_mapping as gm
    from core import speakers

    st.markdown("**Interview guide**")
    template = gm.saved_guide(proj)
    upload = st.file_uploader("Add an interview guide (a .yaml file)", type=["yaml", "yml"], key="guide_upload")
    if upload is not None:
        signature = f"{upload.name}:{upload.size}"
        if st.session_state.get("guide_sig") != signature:
            st.session_state["guide_sig"] = signature
            try:
                text = upload.getvalue().decode("utf-8")
                template = gm.parse_guide(text)
                gm.save_guide(proj, text)
                gm.ensure_codes(proj, template)
                st.session_state["code_notes"] = [(
                    "success", f"Added. Its themes are now in your codebook. {gm.describe(template)}.")]
                st.rerun()
            except (gm.GuideError, UnicodeDecodeError) as exc:
                st.error(f"That guide cannot be used: {exc}")
    st.caption(gm.describe(template) + "." if template else "No guide added yet.")
    if template is None:
        return
    count = gm.suggestion_count(proj, source_id)
    if st.button("Suggest codes from the guide", key="guide_suggest"):
        problem = _guide_unavailable()
        source = proj.get_source(source_id)
        if problem:
            st.info(problem)
        elif source is None or not speakers.stored(source.metadata):
            st.info("Say who is speaking first: the guide needs to know who asked and who answered. "
                    "Do that on the Add transcripts step.")
        else:
            try:
                plan = gm.plan(proj, source_id, template)
                with st.spinner("Matching… the first time can take a few minutes while the model loads."):
                    matched, coverage = gm.match(plan, guide_embedder())
                    report = gm.apply(proj, plan, matched, coverage)
            except gm.GuideError as exc:
                st.info(f"Cannot match this transcript: {exc}")
            except Exception as exc:  # noqa: BLE001 - say what happened instead of a stack trace
                st.error(f"Matching did not finish: {exc or exc.__class__.__name__}")
            else:
                st.session_state["code_notes"] = [(
                    "success",
                    f"Suggested {report.suggestions} code(s) on {report.matched} of {report.pairs} answers. "
                    f"{report.unclassified} answer(s) fit no theme: read those too. "
                    f"{len(report.guide_questions_missed)} guide question(s) were not asked. "
                    "The suggestions are in the reader; correct them like any other.")]
                st.rerun()
    if count and st.button(f"Remove the guide's suggestions ({count})", key="guide_remove"):
        removed = gm.remove_suggestions(proj, source_id)
        st.session_state["code_notes"] = [("info", f"Removed {removed} suggestion(s).")]
        st.rerun()


def _codes_to_apply(chosen: List[str], new_code: str, in_vivo: bool, selected_text: str) -> List[str]:
    """The final code list: picked codes, a typed new one, or the passage itself."""
    codes = list(chosen)
    if in_vivo and selected_text.strip():
        label = " ".join(selected_text.split())[:80]
        if label:
            codes.append(label)
    if new_code.strip():
        codes.append(new_code.strip())
    return codes


def _render_pick_and_code(proj, source_id, text, chosen, new_code, in_vivo, analyst,
                          codeable_units, apply_codes_to_units, unit: str = "sentence") -> None:
    units = codeable_units(text, unit)
    if not units:
        st.info("Nothing to code in this document.")
        return

    pages = max(1, (len(units) + _UNITS_PER_PAGE - 1) // _UNITS_PER_PAGE)
    page = st.slider("Page", 1, pages, 1, key="code_unit_page") if pages > 1 else 1
    window = units[(page - 1) * _UNITS_PER_PAGE: page * _UNITS_PER_PAGE]

    # The main button sits above the sentences, next to the codes you chose, and is filled in once the
    # ticks below are known (a container keeps its place on the page).
    action = st.container()
    first, last = (page - 1) * _UNITS_PER_PAGE + 1, min(page * _UNITS_PER_PAGE, len(units))
    st.caption(f"{unit.capitalize()}s {first} to {last} of {len(units)}. Tick the ones to code: a run "
               "of consecutive ticks is stored as one passage.")
    picked: List[tuple] = []
    for utext, start, end in window:
        label = " ".join(utext.split())
        if st.checkbox(label[:160] + ("…" if len(label) > 160 else ""),
                       key=f"cu_{source_id}_{start}_{end}"):
            picked.append((start, end, utext))

    selected_text = " ".join(u[2] for u in picked)
    codes = _codes_to_apply(chosen, new_code, in_vivo, selected_text)
    with action:
        clicked = st.button(f"Apply to {len(picked)} passage(s)", key="code_apply_units", type="primary",
                            disabled=not picked or not codes,
                            help=None if codes else "Choose a code, or type a new one, first.")
    if clicked:
        try:
            result = apply_codes_to_units(
                proj, source_id, [(s, e) for s, e, _t in picked], codes,
                rater_name=analyst)
            # the page reruns to show the new coding, which would wipe a message written here
            st.session_state["code_notes"] = [(
                "success", f"Coded {len(result['excerpts'])} passage(s): "
                           f"{result['applied']} coding(s) applied"
                           + (f", {result['skipped']} already there" if result["skipped"] else "")
                           + (f". New code(s): {', '.join(result['new_codes'])}"
                              if result["new_codes"] else "."))]
            for _s, _e, _t in picked:                    # clear the ticks
                st.session_state.pop(f"cu_{source_id}_{_s}_{_e}", None)
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))


def _render_paste_and_code(proj, source_id, chosen, new_code, in_vivo, analyst,
                           locate_passage, apply_codes_to_span) -> None:
    st.caption("Paste a passage copied from the Read tab. It is located in the "
               "document, so the stored quote is the document's exact characters — "
               "differences in quote marks or spacing are tolerated.")
    passage = st.text_area("Passage", key="code_passage", height=100)
    if not passage.strip():
        return
    found = locate_passage(proj, source_id, passage)
    if found is None:
        st.error("That passage isn't in this document. Check you copied it from the "
                 "document you're coding.")
        return
    kind = found["match_kind"]
    note = {"exact": "exact match", "normalized": "matched ignoring spacing/punctuation",
            "fuzzy": f"closest match ({found['similarity']:.0%} similar)"}.get(kind, kind)
    st.info(f"Found at characters {found['char_start']}–{found['char_end']} — {note}.")
    st.markdown(f"> {html.escape(found['text'][:400])}")

    codes = _codes_to_apply(chosen, new_code, in_vivo, found["text"])
    if st.button("Apply to this passage", key="code_apply_paste", type="primary", disabled=not codes):
        try:
            result = apply_codes_to_span(
                proj, source_id, found["char_start"], found["char_end"], codes,
                rater_name=analyst)
            st.session_state["code_notes"] = [(
                "success", f"{result['applied']} coding(s) applied"
                           + (f", {result['skipped']} already there." if result["skipped"] else "."))]
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))


def _render_my_codings(proj, source_id, text, analyst, remove_coding, rater_id) -> None:
    st.divider()
    st.subheader("Your codings in this document")
    mine = coding_spans(proj, source_id, rater_id=rater_id)
    if not mine:
        st.caption("None yet.")
        return
    st.caption(f"{len(mine)} passage(s). Removing only affects your own coding.")
    for span in mine:
        with st.container(border=True):
            quote = text[span["char_start"]:span["char_end"]]
            st.markdown(f"> {html.escape(quote[:300])}" + ("…" if len(quote) > 300 else ""))
            r1, r2, r3 = st.columns([3, 2, 1])
            r1.caption("**" + ", ".join(span["codes"]) + "**")
            which = r2.selectbox("Remove", ["(all)"] + span["codes"],
                                 key=f"rm_pick_{span['excerpt_id']}",
                                 label_visibility="collapsed")
            if r3.button("Remove", key=f"rm_{span['excerpt_id']}"):
                removed = remove_coding(
                    proj, span["excerpt_id"],
                    code_name=None if which == "(all)" else which, rater_id=rater_id)
                st.success(f"Removed {removed} coding(s).")
                st.rerun()


def _render_segments(text: str, spans: List[Dict[str, Any]], all_codes: List[str]) -> str:
    """Document text as HTML, with coded passages highlighted.

    Text is HTML-escaped before any markup is added — a document containing
    `<script>` or a stray `&` must render as characters, not as markup.
    """
    colors = _code_colors(all_codes)
    parts = ["<div style='line-height:1.7;white-space:pre-wrap;font-size:0.95rem'>"]
    for seg in segment_by_spans(text, spans):
        body = html.escape(seg["text"])
        if not seg["codes"]:
            parts.append(body)
            continue
        color = colors.get(seg["codes"][0], "#888")
        tip = html.escape(", ".join(seg["codes"]))
        parts.append(
            f"<mark title='{tip}' style='background:{color}33;"
            f"border-bottom:2px solid {color};padding:1px 0'>{body}</mark>")
    parts.append("</div>")
    return "".join(parts)
