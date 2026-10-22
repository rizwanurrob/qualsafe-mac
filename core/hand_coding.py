"""
Coding survey answers by hand, without a front end.

A person reads each answer and says which codes apply to it, as a whole. That
choice is saved on the answer's whole-answer excerpt as the human coder's, and the
answer is recorded as *reviewed* by them, including "no code applies". That record
is what lets agreement count a hand-coded answer with no codes as a real judgement
instead of a missing one (`Project.replace_applications_for_rater`).

The desktop screen (`qualsafe_qt/views/answers_view.py`) is the only front end.
Nothing here imports Qt.

Why whole answers and not highlighted passages: survey answers are a few sentences,
and the computer's coding (the suggested codes, the written codebook) is also whole
answer, so a hand code on the whole answer can be compared with it directly by
per-code Cohen's kappa. A highlighted span inside an answer has no counterpart to
compare with.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterator, List, Optional, Sequence, Tuple

import pandas as pd

from core import written_codebook
from core.model import Code, CodeApplication, Rater, Source
from core.project import Project
from core.span_coding import HUMAN_RATER

SURVEY = "survey_response"
_BATCH = 500


@dataclass
class Answer:
    source_id: str
    excerpt_id: str
    label: str                       # the response id from the spreadsheet
    text: str
    judged: bool = False             # this coder has said what applies, even if nothing does
    codes: List[str] = field(default_factory=list)


def prepare(project_path, frame: pd.DataFrame, text_column: str, id_column: str = "") -> int:
    """Make sure every answer is in the project, once. Opens its own `Project`, so run it on a
    worker thread from a window. Returns how many answers there are to code."""
    with Project.open(project_path) as project:
        return len(written_codebook.ensure_excerpts(project, frame, text_column, id_column))


def total_answers(project: Project) -> int:
    return project.count_sources(SURVEY)


def _sources(project: Project) -> Iterator[Source]:
    offset = 0
    while True:
        batch = project.iter_sources(source_type=SURVEY, limit=_BATCH, offset=offset, order="entered")
        if not batch:
            return
        yield from batch
        offset += len(batch)


def _whole_answer_excerpt(project: Project, source_id: str) -> Optional[str]:
    """The excerpt that is the whole answer (not a highlighted passage)."""
    for excerpt in project.list_excerpts(source_id):
        if excerpt.char_start == 0:
            return excerpt.excerpt_id
    return None


def source_ids_for_excerpts(project: Project, excerpt_ids: Sequence[str]) -> set:
    """The answers (sources) that a set of excerpts belong to."""
    found = set()
    for excerpt_id in excerpt_ids:
        excerpt = project.get_excerpt(excerpt_id)
        if excerpt is not None:
            found.add(excerpt.source_id)
    return found


def page(project: Project, *, offset: int = 0, limit: int = 50, search: str = "",
         only_unjudged: bool = False, rater_id: str = HUMAN_RATER,
         only_ids: Optional[set] = None) -> Tuple[List[Answer], int]:
    """A page of answers, and how many match. Reads the answers in batches, never all at once
    into the list a window shows."""
    judged = project.rater_item_set(rater_id)
    reviewed = project.coverage_excerpt_ids(rater_id)
    needle = (search or "").strip().lower()
    shown: List[Answer] = []
    matches = 0
    for source in _sources(project):
        if only_ids is not None and source.source_id not in only_ids:
            continue
        text = source.raw_text or ""
        if needle and needle not in text.lower() and needle not in (source.label or "").lower():
            continue
        excerpt_id = _whole_answer_excerpt(project, source.source_id)
        if excerpt_id is None:
            continue
        is_judged = excerpt_id in reviewed
        if only_unjudged and is_judged:
            continue
        if offset <= matches < offset + limit:
            shown.append(Answer(source.source_id, excerpt_id, source.label or "", text, is_judged,
                                sorted(judged.labels.get(excerpt_id, set())) if is_judged else []))
        matches += 1
    return shown, matches


def get(project: Project, source_id: str, rater_id: str = HUMAN_RATER) -> Optional[Answer]:
    source = project.get_source(source_id)
    if source is None or source.type != SURVEY:
        return None
    excerpt_id = _whole_answer_excerpt(project, source_id)
    if excerpt_id is None:
        return None
    reviewed = project.coverage_excerpt_ids(rater_id)
    labels = project.rater_item_set(rater_id).labels
    is_judged = excerpt_id in reviewed
    return Answer(source_id, excerpt_id, source.label or "", source.raw_text or "", is_judged,
                  sorted(labels.get(excerpt_id, set())) if is_judged else [])


def progress(project: Project, rater_id: str = HUMAN_RATER,
             only_ids: Optional[set] = None) -> Tuple[int, int]:
    """(answers this coder has judged, answers there are), of all answers or of `only_ids`."""
    reviewed = project.coverage_excerpt_ids(rater_id)
    done = total = 0
    for source in _sources(project):
        if only_ids is not None and source.source_id not in only_ids:
            continue
        total += 1
        excerpt_id = _whole_answer_excerpt(project, source.source_id)
        done += excerpt_id in reviewed
    return done, total


def save(project: Project, source_id: str, code_names: Sequence[str], *, rater_name: str = "",
         rater_id: str = HUMAN_RATER) -> Dict[str, object]:
    """Record which codes apply to one answer (possibly none). A new name makes a new code.

    Replaces this coder's earlier choice for the answer, so changing your mind is safe.
    Returns `{"excerpt_id", "codes", "new_codes"}`.
    """
    excerpt_id = _whole_answer_excerpt(project, source_id)
    if excerpt_id is None:
        raise ValueError(f"No such answer: {source_id}")
    names: List[str] = []
    for name in code_names:
        clean = str(name).strip()
        if clean and clean not in names:
            names.append(clean)
    project.add_rater(Rater(rater_id=rater_id, kind="human", name=rater_name))
    new_codes: List[str] = []
    applications: List[CodeApplication] = []
    for name in names:
        code = project.find_code_by_name(name)
        if code is None:
            code_id = project.add_code(Code(code_id="", name=name, origin="emergent", created_by="human"))
            new_codes.append(name)
        else:
            code_id = code.code_id
        applications.append(CodeApplication(application_id="", excerpt_id=excerpt_id, code_id=code_id,
                                            coder="human", rater_id=rater_id))
    project.replace_applications_for_rater(rater_id, [excerpt_id], applications)
    return {"excerpt_id": excerpt_id, "codes": names, "new_codes": new_codes}


def next_unjudged(project: Project, after_source_id: str = "", rater_id: str = HUMAN_RATER,
                  only_ids: Optional[set] = None) -> Optional[str]:
    """The next answer this coder has not judged, after `after_source_id` (wrapping round)."""
    reviewed = project.coverage_excerpt_ids(rater_id)
    passed = not after_source_id
    first: Optional[str] = None
    for source in _sources(project):
        if only_ids is not None and source.source_id not in only_ids:
            continue
        excerpt_id = _whole_answer_excerpt(project, source.source_id)
        unjudged = excerpt_id is not None and excerpt_id not in reviewed
        if passed and unjudged:
            return source.source_id
        if unjudged and first is None:
            first = source.source_id
        if source.source_id == after_source_id:
            passed = True
    return first
