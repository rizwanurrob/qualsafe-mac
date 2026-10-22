#!/usr/bin/env python
"""
Guided sample project (v3.4, Phase 3.3).

A first-time user opening the Analysis, Codebook, or Agreement pages sees empty
states until they've run a real pipeline — which needs data, model downloads, and
a few minutes. This builds a small, self-contained `.qnw` from the synthetic
feedback dataset so every panel has something real to show immediately: a starter
codebook, machine codings from a mocked run, a few human codings (so the Agreement
tab computes a kappa), and one memo.

It is built entirely offline — no models, no Ollama — by writing plausible
codings directly into the store, so it works on a fresh install before anything is
downloaded.

The project is named with a ``SAMPLE_`` prefix and the UI banners it, so it is
never mistaken for, or accidentally used as, real analysis.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Union

SAMPLE_PREFIX = "SAMPLE_"

# A small a-priori codebook matching the built-in education sample dataset
# (data/sample_survey_education.csv) and the default label pack (v3.7.1).
_STARTER_CODES = [
    ("Financial concerns", "Cost, tuition, books, work hours, and money pressure."),
    ("Sense of belonging", "Feeling connected, making friends, fitting in on campus."),
    ("Academic difficulty", "Coursework, studying, grades, and academic skills."),
    ("Advising & support services", "Advisors, tutoring, counseling, and other services."),
    ("Time management & workload", "Balancing classes, work, commuting, and life."),
]

# Keyword → code, used to assign plausible machine codings without a model.
_KEYWORDS = {
    "Financial concerns": ["cost", "tuition", "money", "afford", "financial aid", "scholarship",
                           "books", "bill", "grant", "textbook", "meal plan"],
    "Sense of belonging": ["friends", "belong", "lonely", "loneliness", "homesick", "fit in",
                           "community", "club", "roommate", "first in my family", "weekend"],
    "Academic difficulty": ["math", "exam", "grades", "study", "studying", "writing", "failing",
                            "statistics", "chemistry", "workload", "papers", "lab report"],
    "Advising & support services": ["advisor", "advising", "tutoring", "counseling", "career services",
                                    "writing center", "registration", "resources", "mentoring"],
    "Time management & workload": ["time management", "balancing", "commut", "hours a week",
                                   "shift", "schedule", "behind", "planning"],
}


def _assign_codes(text: str) -> List[str]:
    """Keyword-match a response to zero or more codes (a stand-in for the model)."""
    low = text.lower()
    return [code for code, words in _KEYWORDS.items() if any(w in low for w in words)]


def build_sample_project(
    csv_path: Union[str, Path],
    out_path: Union[str, Path],
    *,
    max_rows: int = 40,
) -> Path:
    """Build a guided sample `.qnw` at `out_path` from a feedback CSV. Returns it.

    Offline and deterministic. Overwrites any existing file at the path.
    """
    import pandas as pd

    from core.model import Code, CodeApplication, Memo, Rater, RunManifest, Source
    from core.project import Project, new_id

    csv_path = Path(csv_path)
    out_path = Path(out_path)
    if out_path.exists():
        out_path.unlink()

    df = pd.read_csv(csv_path)
    text_col = next((c for c in df.columns
                     if c.lower() in ("response_text", "feedback", "text", "comment", "response")),
                    df.columns[0])
    df = df.head(max_rows)

    with Project.create(out_path) as proj:
        with proj.bulk():
            model_rater = proj.add_rater(Rater(
                rater_id="transformer", kind="transformer", name="sample model",
                model_id="synthetic"))
            human_rater = proj.add_rater(Rater(
                rater_id="human_primary", kind="human", name="sample analyst"))
            run_id = proj.add_run(RunManifest(
                run_id="", package_version="sample", mode="survey", engine="transformer",
                model="synthetic", counts={"responses": int(len(df))}, exported_raw_text=True))

            code_id_by_name = {}
            for name, definition in _STARTER_CODES:
                code_id_by_name[name] = proj.add_code(Code(
                    code_id="", name=name, definition=definition,
                    origin="a_priori", created_by="human"))

            for i, (_, row) in enumerate(df.iterrows()):
                text = str(row.get(text_col, "") or "")
                if not text.strip():
                    continue
                rid = str(i)
                question = str(row.get("question_text", "") or "Open feedback")
                source = Source(
                    source_id=new_id("src"), type="survey_response", raw_text=text,
                    label=question,
                    metadata={"response_id": rid, "question_text": question})
                proj.add_source(source)
                excerpt_id = proj.add_whole_response_excerpt(source)

                codes = _assign_codes(text)
                for name in codes:
                    proj.apply_code(CodeApplication(
                        application_id="", excerpt_id=excerpt_id,
                        code_id=code_id_by_name[name], coder="transformer",
                        rater_id=model_rater, run_id=run_id, confidence=0.8))

                # Human codes the first ~12 rows (so the Agreement tab has overlap),
                # agreeing with the model but occasionally differing — a realistic κ.
                if i < 12:
                    human_codes = list(codes)
                    if i % 4 == 0 and human_codes:
                        human_codes = human_codes[:-1]  # human is a bit more conservative
                    if i % 5 == 0:
                        human_codes = list(set(human_codes) | {"Sense of belonging"})
                    for name in human_codes:
                        proj.apply_code(CodeApplication(
                            application_id="", excerpt_id=excerpt_id,
                            code_id=code_id_by_name[name], coder="human",
                            rater_id=human_rater, run_id=run_id))

            proj.add_memo(Memo(
                memo_id="", target_type="project", target_id=None,
                text="Sample project — synthetic data, keyword-assigned codes. Use it to "
                     "explore the Analysis, Codebook, and Agreement pages; it is not real "
                     "analysis.",
                author="human"))

    return out_path


def default_sample_path(output_root: Union[str, Path]) -> Path:
    """Where the guided sample project lives under the app's output tree."""
    return Path(output_root) / f"{SAMPLE_PREFIX}guided_project" / "project.qnw"
