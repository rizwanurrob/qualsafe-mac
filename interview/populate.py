#!/usr/bin/env python
"""
Populate a `.qnw` project store from an interview run (v3.1, I3).

Maps the interview pipeline's artifacts onto the SAME shared model the survey
mode uses — the whole point of the shared backbone:

- the transcript          -> one Source(type="interview")
- template themes         -> a-priori Codes (via InterviewTemplate.to_codes)
- each matched Q/A pair   -> an Excerpt spanning its response turns, plus one
                             CodeApplication per confident theme match
                             (coder="transformer", confidence=similarity)
- each VERIFIED quote     -> an Excerpt at the quote's exact source offsets, plus
                             a CodeApplication (coder="llm", rationale notes the
                             match kind)
- each theme summary      -> a Memo on the code (author="llm_draft")
- the run                 -> Rater rows + a RunManifest (mode="interview")

Every excerpt satisfies text == raw_text[start:end], so the Analysis page's
drill-back works identically for interviews and surveys. Unclassified pairs
produce no applications (they are off-template, surfaced in the report instead).

NOTE: a multi-turn response span may include an interleaved interviewer
backchannel line — the excerpt is still a verbatim slice of the source
(traceability holds); tightening to per-turn excerpts is a possible refinement.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Union

from core.manifest import PACKAGE_VERSION
from interview.analyze import ThemeAnalysis
from interview.matching import MatchedPair
from interview.template import InterviewTemplate


def populate_interview_store(
    store_path: Union[str, Path],
    *,
    raw_text: str,
    doc_label: str,
    matched: List[MatchedPair],
    template: InterviewTemplate,
    analyses: Optional[List[ThemeAnalysis]] = None,
    embedding_model: str = "",
    llm_model: str = "",
) -> str:
    """Build a fresh interview `.qnw` at store_path; returns the path as str."""
    from core.model import (
        Code, CodeApplication, Excerpt, Memo, Rater, RunManifest, Source,
    )
    from core.project import Project, new_id

    store_path = Path(store_path)
    if store_path.exists():
        store_path.unlink()

    n_matched = sum(1 for m in matched if m.matches)
    n_unclassified = sum(1 for m in matched if m.is_unclassified)

    with Project.create(store_path) as proj:
        source = Source(source_id=new_id("src"), type="interview",
                        raw_text=raw_text, label=doc_label)
        proj.add_source(source)

        for code in template.to_codes():
            proj.add_code(code)

        matcher_rater = proj.add_rater(Rater(
            rater_id="", kind="transformer", name="interview template matcher",
            model_id=embedding_model))
        llm_rater = ""
        if analyses is not None and llm_model:
            llm_rater = proj.add_rater(Rater(
                rater_id="", kind="llm", name="interview theme analyst",
                model_id=llm_model))

        run_id = proj.add_run(RunManifest(
            run_id="", package_version=PACKAGE_VERSION, mode="interview",
            engine="llm" if llm_model else "transformer",
            model=llm_model or embedding_model,
            template_version=template.title,
            counts={"qa_pairs": len(matched), "matched_pairs": n_matched,
                    "unclassified_pairs": n_unclassified,
                    "themes": len(template.themes)},
            exported_raw_text=True,
        ))

        # Matched Q/A pairs -> response-span excerpts + applications.
        for m in matched:
            if not m.matches or not m.pair.response_turns:
                continue
            start = m.pair.response_turns[0].char_start
            end = m.pair.response_turns[-1].char_end
            excerpt = Excerpt(excerpt_id=new_id("exc"), source_id=source.source_id,
                              text=raw_text[start:end], char_start=start, char_end=end)
            proj.add_excerpt(excerpt)
            for match in m.matches:
                proj.apply_code(CodeApplication(
                    application_id="", excerpt_id=excerpt.excerpt_id,
                    code_id=match.theme_id, coder="transformer",
                    rater_id=matcher_rater, run_id=run_id,
                    confidence=match.similarity,
                    rationale=f"template match ({match.source})",
                ))

        # Verified LLM quotes -> exact-offset excerpts + applications + memos.
        for analysis in (analyses or []):
            if analysis.summary:
                proj.add_memo(Memo(
                    memo_id="", target_type="code", target_id=analysis.theme_id,
                    text=analysis.summary, author="llm_draft"))
            for quote in analysis.quotes:
                excerpt = Excerpt(excerpt_id=new_id("exc"), source_id=source.source_id,
                                  text=quote.text, char_start=quote.char_start,
                                  char_end=quote.char_end)
                proj.add_excerpt(excerpt)
                proj.apply_code(CodeApplication(
                    application_id="", excerpt_id=excerpt.excerpt_id,
                    code_id=analysis.theme_id, coder="llm",
                    rater_id=llm_rater or None, run_id=run_id,
                    confidence=quote.similarity,
                    rationale=f"verified quote ({quote.match_kind})",
                ))

    return str(store_path)
