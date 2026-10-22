"""
Interview Mode page (v3.1, I4) — the Streamlit front-end for semi-structured
interview analysis.

A sequential wizard: Upload (FERPA gate) → Template → Parsing review (the
MANDATORY human checkpoint: detected pattern + confidence, proposed speaker roles
with rationale, detected questions — the analyst confirms or corrects before
anything runs) → Run (embedding match + optional local-LLM summaries with
progress) → Results (per-theme summaries with verified quotes + hallucination
rate, guide coverage, off-template material).

Interview runs save a `.qnw` into the same output_streamlit/run_* convention as
survey runs, so the existing Analysis and Results & Downloads pages pick them up
with no extra wiring.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd
import streamlit as st
from app.shared.layout import stretch
import yaml

from core.manifest import PACKAGE_VERSION, PRIVACY_NOTE
from interview.analyze import analyze_interview
from interview.grouping import group_by_theme, guide_question_coverage
from interview.matching import default_embed_fn, match_qa_pairs, response_text
from interview.parse import PATTERNS, load_document, segment_turns
from interview.populate import populate_interview_store
from interview.questions import detect_questions, pair_questions_with_responses
from interview.speakers import apply_roles, infer_speaker_roles
from interview.template import InterviewTemplate, TemplateError

PROJECT_ROOT = Path(__file__).resolve().parent
IV_INPUT_DIR = PROJECT_ROOT / "data" / "session_inputs" / "interviews"
IV_OUTPUT_DIR = PROJECT_ROOT / "output_streamlit"
EXAMPLE_TEMPLATE_PATH = PROJECT_ROOT / "config" / "interview_template.example.yaml"
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

ROLE_OPTIONS = ["interviewer", "interviewee", "other"]


def init_interview_state() -> None:
    defaults: Dict[str, Any] = {
        "iv_pii_confirmed": False,
        # Signature (name:size) of the transcript the confirmation was given for.
        "iv_confirmed_doc": "",
        "iv_doc_name": "",
        "iv_raw_text": "",
        "iv_turns": [],
        "iv_pattern": "",
        "iv_confidence": 0.0,
        "iv_role_inference": None,
        "iv_roles_confirmed": False,
        "iv_roled_turns": [],
        "iv_questions": [],
        "iv_pairs": [],
        "iv_template_yaml": "",
        "iv_template": None,
        "iv_min_similarity": 0.45,
        "iv_allow_multi": True,
        "iv_use_llm": False,
        "iv_llm_model": "llama3.2:3b",
        "iv_results": None,          # dict: matched/groups/off/coverage/analyses/run_dir
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def _reset_after_upload() -> None:
    """New document (or re-segmentation) invalidates everything downstream."""
    st.session_state["iv_roles_confirmed"] = False
    st.session_state["iv_roled_turns"] = []
    st.session_state["iv_questions"] = []
    st.session_state["iv_pairs"] = []
    st.session_state["iv_results"] = None


def _segment(pattern_name: str = "auto") -> None:
    turns, used, confidence = segment_turns(st.session_state["iv_raw_text"], pattern_name=pattern_name)
    st.session_state["iv_turns"] = turns
    st.session_state["iv_pattern"] = used
    st.session_state["iv_confidence"] = confidence
    st.session_state["iv_role_inference"] = infer_speaker_roles(turns)
    _reset_after_upload()


# ── 1. Upload ────────────────────────────────────────────────────────────────

def upload_signature(name: str, size: int) -> str:
    """Identity of an uploaded transcript, for keying the confirmation to it.

    Name alone is not enough: re-exporting a transcript under the same filename
    is routine, and the analyst should re-attest to the new contents.
    """
    return f"{name}:{size}"


def _section_upload() -> bool:
    st.subheader("1 · Upload interview transcript")
    st.warning(
        "**FERPA / IRB Reminder** — an interview transcript is highly sensitive: a single "
        "identifiable person, often discussing personal experience. Confirm this file has been "
        "reviewed and is appropriate to process locally on this machine. Nothing leaves this device.",
        icon="⚠️",
    )

    uploaded = st.file_uploader(
        "One interview per file (.txt, .docx, .pdf)",
        type=["txt", "docx", "pdf"], key="iv_uploader",
        help="Digital-text transcripts. Scanned/OCR PDFs are not supported in this version.",
    )

    # Synthetic sample: a ~15-minute first-year-student interview shipped with the
    # tool. No PII attestation needed — the gate exists for the analyst's own
    # data; this file is ours and contains no real person.
    sample_path = PROJECT_ROOT / "data" / "sample_interview_transcript.txt"
    if sample_path.exists() and st.button(
        "Use the sample transcript (synthetic)", key="iv_use_sample",
        help="Loads a built-in synthetic student interview so you can walk the whole "
             "wizard — parsing, roles, template matching, summaries — without real data. "
             "Pairs with the example template in step 2.",
    ):
        try:
            st.session_state["iv_raw_text"] = load_document(sample_path)
            st.session_state["iv_doc_name"] = sample_path.name
            st.session_state["iv_confirmed_doc"] = f"{sample_path.name}:synthetic"
            st.session_state["iv_pii_confirmed"] = True
            _segment("auto")
            st.success("Sample transcript loaded. Next: load the example template in step 2.")
        except Exception as exc:  # noqa: BLE001
            st.error(f"Could not load the sample transcript: {exc}")

    # The confirmation is per transcript, not per session. Previously the
    # checkbox gated the uploader, so a second transcript dropped into a
    # confirmed session was written to disk and parsed under the *first* file's
    # attestation. The gate now sits between the upload and the first write.
    if uploaded is not None:
        signature = upload_signature(uploaded.name, uploaded.size)
        if signature != st.session_state.get("iv_confirmed_doc", ""):
            st.session_state["iv_pii_confirmed"] = False
            st.caption(f"Selected: `{uploaded.name}` ({uploaded.size:,} bytes) — not yet processed.")
            confirmed = st.checkbox(
                "I confirm this transcript has been reviewed for PII / FERPA / IRB concerns",
                value=False,
                key=f"iv_pii_checkbox_{signature}",
            )
            if not confirmed:
                st.info("Confirm the review above to load this transcript.")
                return False
            try:
                # First write of the file happens here — after confirmation.
                IV_INPUT_DIR.mkdir(parents=True, exist_ok=True)
                saved = IV_INPUT_DIR / uploaded.name
                saved.write_bytes(uploaded.getvalue())
                st.session_state["iv_raw_text"] = load_document(saved)
                st.session_state["iv_doc_name"] = uploaded.name
                st.session_state["iv_confirmed_doc"] = signature
                st.session_state["iv_pii_confirmed"] = True
                _segment("auto")
                st.success(f"Loaded: {uploaded.name}")
            except Exception as exc:  # noqa: BLE001
                st.error(f"Could not load transcript: {exc}")
                return False

    if not st.session_state["iv_raw_text"]:
        return False
    n_chars = len(st.session_state["iv_raw_text"])
    st.caption(f"Document: `{st.session_state['iv_doc_name']}` — {n_chars:,} characters, "
               f"{len(st.session_state['iv_turns'])} detected turns.")
    return True


# ── 2. Template ──────────────────────────────────────────────────────────────

def _section_template() -> bool:
    st.subheader("2 · Interview template (your guide = your codebook)")
    st.caption("Themes with guide questions and keywords, as YAML. Each theme becomes an "
               "a-priori code in the project.")
    if st.button("Load example template", key="iv_load_example"):
        st.session_state["iv_template_yaml"] = EXAMPLE_TEMPLATE_PATH.read_text(encoding="utf-8")

    st.session_state["iv_template_yaml"] = st.text_area(
        "Template YAML", value=st.session_state.get("iv_template_yaml", ""),
        height=240, key="iv_template_editor",
    )
    if not st.session_state["iv_template_yaml"].strip():
        st.info("Load the example template or paste your own to continue.")
        return False
    try:
        data = yaml.safe_load(st.session_state["iv_template_yaml"])
        template = InterviewTemplate.from_dict(data)
    except (TemplateError, yaml.YAMLError) as exc:
        st.error(f"Template problem: {exc}")
        return False
    st.session_state["iv_template"] = template
    st.dataframe(pd.DataFrame([{
        "id": t.id, "label": t.label,
        "guide questions": len(t.guide_questions), "keywords": ", ".join(t.keywords),
    } for t in template.themes]), **stretch(), hide_index=True)
    return True


# ── 3. Parsing review — the mandatory human checkpoint ──────────────────────

def _section_review() -> bool:
    st.subheader("3 · Review parsing (required)")
    pattern = st.session_state["iv_pattern"]
    confidence = st.session_state["iv_confidence"]

    pat_col, red_col = st.columns([3, 1])
    options = ["auto"] + [p.name for p in PATTERNS]
    forced = pat_col.selectbox("Speaker pattern", options, index=0, key="iv_pattern_choice",
                               help="'auto' scores all detectors and picks the best.")
    if red_col.button("Re-detect turns", key="iv_resegment"):
        _segment(forced)
        st.rerun()

    if pattern == "none":
        st.error(
            "No speaker structure could be detected — the whole document parsed as one block. "
            "Interview mode needs speaker-labeled turns (e.g. `Interviewer:` / `Respondent:`, "
            "`Q:`/`A:`, timestamps, or `Name:`). Add labels to the transcript, or force a "
            "pattern above if you believe one applies."
        )
        return False

    conf_msg = f"Detected pattern **{pattern}** (segmentation confidence {confidence:.0%})."
    if confidence < 0.4:
        st.warning(conf_msg + " Low confidence — check the turns below carefully.")
    else:
        st.info(conf_msg)

    inference = st.session_state["iv_role_inference"]
    st.markdown("**Speaker roles** — proposed automatically; you decide.")
    st.caption(inference.rationale)
    role_map: Dict[str, str] = {}
    cols = st.columns(min(4, max(2, len(inference.role_by_label))))
    for i, (label, proposed) in enumerate(sorted(inference.role_by_label.items())):
        with cols[i % len(cols)]:
            role_map[label] = st.selectbox(
                f"'{label}' is the…", ROLE_OPTIONS,
                index=ROLE_OPTIONS.index(proposed) if proposed in ROLE_OPTIONS else 2,
                key=f"iv_role_{label}",
            )

    with st.expander("Spot-check the detected turns", expanded=False):
        for t in st.session_state["iv_turns"][:30]:
            st.markdown(f"**{t.speaker_raw}** ({role_map.get(t.speaker_raw, '?')}): {t.text}")

    if st.button("Confirm roles & detect questions", key="iv_confirm_roles", type="primary"):
        if "interviewer" not in role_map.values() or "interviewee" not in role_map.values():
            st.error("Assign at least one interviewer and one interviewee.")
            return False
        roled = apply_roles(st.session_state["iv_turns"], role_map)
        questions = detect_questions(roled)
        pairs = pair_questions_with_responses(roled, questions)
        st.session_state["iv_roled_turns"] = roled
        st.session_state["iv_questions"] = questions
        st.session_state["iv_pairs"] = pairs
        st.session_state["iv_roles_confirmed"] = True
        st.session_state["iv_results"] = None

    if not st.session_state["iv_roles_confirmed"]:
        st.info("Confirm the speaker roles to continue — this checkpoint is required.")
        return False

    questions = st.session_state["iv_questions"]
    st.success(f"{len(questions)} question(s) detected, "
               f"{len(st.session_state['iv_pairs'])} question→response pair(s) built.")
    with st.expander("Spot-check the detected questions", expanded=False):
        st.dataframe(pd.DataFrame([{
            "id": q.question_id, "turn": q.turn_index, "question": q.text,
        } for q in questions]), **stretch(), hide_index=True)
    return len(questions) > 0


# ── 4. Run ───────────────────────────────────────────────────────────────────

def _section_run() -> None:
    st.subheader("4 · Run analysis")
    c1, c2 = st.columns(2)
    st.session_state["iv_min_similarity"] = c1.slider(
        "Matching threshold (below → off-template bucket)", 0.30, 0.70,
        float(st.session_state.get("iv_min_similarity", 0.45)), 0.01, key="iv_minsim")
    st.session_state["iv_allow_multi"] = c2.checkbox(
        "Allow a response to match multiple themes", value=st.session_state.get("iv_allow_multi", True),
        key="iv_multi")

    st.session_state["iv_use_llm"] = st.checkbox(
        "Also generate per-theme summaries with a local language model (Ollama)",
        value=st.session_state.get("iv_use_llm", False), key="iv_llm_toggle",
        help="Summaries, sub-themes, tone, and verbatim quotes — every quote is verified "
             "against the transcript before it is shown. Requires Ollama.")
    if st.session_state["iv_use_llm"]:
        st.session_state["iv_llm_model"] = st.text_input(
            "Ollama model", value=st.session_state.get("iv_llm_model", "llama3.2:3b"),
            key="iv_llm_model_input")

    if not st.button("Run interview analysis", key="iv_run", type="primary"):
        return

    template: InterviewTemplate = st.session_state["iv_template"]
    pairs = st.session_state["iv_pairs"]
    raw_text = st.session_state["iv_raw_text"]

    with st.spinner("Measuring similarity and matching against the template (first run downloads the similarity model)…"):
        embed_fn = default_embed_fn(EMBEDDING_MODEL)
        matched = match_qa_pairs(pairs, template, embed_fn, {
            "min_similarity": float(st.session_state["iv_min_similarity"]),
            "allow_multi_theme": bool(st.session_state["iv_allow_multi"]),
        })
        groups, off_template = group_by_theme(matched, template)
        coverage = guide_question_coverage(
            pairs, template, embed_fn,
            min_similarity=float(st.session_state["iv_min_similarity"]))

    analyses = None
    llm_model = ""
    if st.session_state["iv_use_llm"]:
        from engines.ollama_client import OllamaClient
        client = OllamaClient()
        model = st.session_state["iv_llm_model"]
        if not client.is_available() or not client.has_model(model):
            st.warning(f"Ollama or model '{model}' unavailable — matching results are shown "
                       "without language model summaries. Pull the model and re-run to add them.")
        else:
            bar = st.progress(0.0, text="Summarizing themes with the local language model…")
            analyses = analyze_interview(
                groups, template, raw_text, client, model,
                progress_callback=lambda done, total: bar.progress(
                    done / total if total else 1.0,
                    text=f"Summarizing themes with the local language model… {done}/{total}"))
            llm_model = model

    run_dir = IV_OUTPUT_DIR / datetime.now().strftime("run_iv_%Y%m%d_%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)
    store_path = populate_interview_store(
        run_dir / "project.qnw", raw_text=raw_text,
        doc_label=st.session_state["iv_doc_name"], matched=matched, template=template,
        analyses=analyses, embedding_model=EMBEDDING_MODEL, llm_model=llm_model)

    manifest = {
        "package_version": PACKAGE_VERSION,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "mode": "interview",
        "engine": "llm" if analyses else "transformer",
        "model": llm_model or EMBEDDING_MODEL,
        "document": st.session_state["iv_doc_name"],
        "speaker_pattern": st.session_state["iv_pattern"],
        "segmentation_confidence": st.session_state["iv_confidence"],
        "template_title": template.title,
        "thresholds": {"min_similarity": float(st.session_state["iv_min_similarity"])},
        "counts": {"turns": len(st.session_state["iv_turns"]),
                   "questions": len(st.session_state["iv_questions"]),
                   "qa_pairs": len(pairs),
                   "matched_pairs": sum(1 for m in matched if m.matches),
                   "off_template_pairs": len(off_template)},
        "exports": {"project_store": store_path},
        "privacy_note": PRIVACY_NOTE,
    }
    (run_dir / "run_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    st.session_state["iv_results"] = {
        "matched": matched, "groups": groups, "off_template": off_template,
        "coverage": coverage, "analyses": analyses, "run_dir": str(run_dir),
    }
    st.success(f"Analysis complete. Project saved to `{run_dir}` — also browsable in the "
               "**Analysis** page.")


# ── 5. Results ───────────────────────────────────────────────────────────────

def _section_results() -> None:
    results = st.session_state.get("iv_results")
    if not results:
        return
    st.subheader("5 · Results")
    matched, groups = results["matched"], results["groups"]
    analyses = {a.theme_id: a for a in (results["analyses"] or [])}

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Q→A pairs", len(matched))
    m2.metric("Matched", sum(1 for m in matched if m.matches))
    m3.metric("Off-template", len(results["off_template"]))
    m4.metric("Themes with content", sum(1 for g in groups if g.items))

    for group in groups:
        with st.expander(f"**{group.label}** — {len(group.items)} matched exchange(s)",
                         expanded=bool(group.items)):
            analysis = analyses.get(group.theme_id)
            if analysis and analysis.summary:
                st.markdown(f"**Summary (language model first pass — review before use):** {analysis.summary}")
                if analysis.tone:
                    st.caption(f"Tone: {analysis.tone}"
                               + (f" · Sub-themes: {', '.join(analysis.sub_themes)}"
                                  if analysis.sub_themes else ""))
                if analysis.quotes:
                    st.markdown("**Verified quotes (verbatim from transcript):**")
                    for q in analysis.quotes:
                        st.markdown(f"> {q.text}")
                        st.caption(f"match: {q.match_kind} · similarity {q.similarity}")
                if analysis.dropped_quotes:
                    st.warning(f"{len(analysis.dropped_quotes)} language-model-proposed quote(s) could not "
                               f"be verified against the transcript and were dropped "
                               f"(share of quotes not found in the transcript {analysis.hallucination_rate:.0%}).")
            elif analysis and analysis.note == "llm_json_error":
                st.warning("The language model did not return a usable summary for this theme.")
            for item in group.items:
                st.markdown(f"— **Q:** {item.pair.question.text}")
                answer = response_text(item.pair) or "*(no direct response recorded)*"
                st.markdown(f"  **A:** {answer}")
                st.caption(f"similarity {group.similarity_for(item):.2f}")

    st.markdown("#### Guide coverage")
    st.caption("Was each guide question actually asked? A theme can still receive content "
               "through answers to other questions — that shows in the theme groups above.")
    st.dataframe(pd.DataFrame(results["coverage"]), **stretch(), hide_index=True)

    if results["off_template"]:
        st.markdown("#### Off-template material")
        st.caption("Exchanges that matched no theme — often the most interesting findings.")
        for m in results["off_template"]:
            with st.container(border=True):
                st.markdown(f"**Q:** {m.pair.question.text}")
                st.markdown(f"**A:** {response_text(m.pair) or '*(no direct response)*'}")


def render_interview_mode() -> None:
    init_interview_state()
    st.header("Interview Mode (semi-structured)")
    st.caption("One transcript → speaker turns → questions → template themes → regrouped, "
               "evidence-linked analysis. Every automated step is reviewable; nothing leaves "
               "this machine.")
    if not _section_upload():
        return
    st.divider()
    if not _section_template():
        return
    st.divider()
    if not _section_review():
        return
    st.divider()
    _section_run()
    _section_results()
