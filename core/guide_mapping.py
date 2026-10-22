"""Suggest codes from an interview guide (Update 3, item 4.6; V8_PLAN UX-11).

The web app's interview mode matches each question the interviewer asked, and the
answer that followed, to the themes of an interview guide. This is the same matching
(`interview/`), applied to a transcript that is already in a desktop project, and kept
there as *suggestions*: coded passages made by the guide matcher, that the researcher
reads and corrects like any other computer suggestion.

Rules this module keeps
-----------------------
* Speakers first. The matching needs to know who asked and who answered, and that is only
  ever the researcher's confirmed answer (`core/speakers.py`), never a silent guess.
* Suggestions only. Every coded passage is made by its own rater ("interview guide
  matcher"), so it can be told apart from the researcher's own coding, counted apart and
  removed in one step without touching anything the researcher coded.
* Nothing from the answers is stored beyond what coding already stores: a passage is a
  span of the transcript, the reason is a short fixed phrase.
* The guide is the researcher's own file. It is kept in the project, in the same table that
  keeps the project format number, so it travels with the project.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Union

import yaml

from core import speakers
from interview.grouping import guide_question_coverage
from interview.matching import DEFAULT_MIN_SIMILARITY, MatchedPair, match_qa_pairs
from interview.questions import detect_questions, pair_questions_with_responses
from interview.template import InterviewTemplate, TemplateError

GUIDE_KEY = "interview_guide_yaml"
MATCHER_NAME = "interview guide matcher"
RATIONALE = "interview guide match"


class GuideError(ValueError):
    """Something the researcher can fix, in a sentence they can read."""


# -- the guide file ---------------------------------------------------------------------

def parse_guide(text: str) -> InterviewTemplate:
    """A guide from YAML text; raises `GuideError` in plain words if it cannot be used."""
    try:
        data = yaml.safe_load(text or "")
    except yaml.YAMLError:
        raise GuideError("That file is not a readable guide. It should be a YAML file with "
                         "a list of themes; see the example that came with QualSafe.") from None
    if not isinstance(data, dict):
        raise GuideError("That file does not look like an interview guide. It should start "
                         "with interview_template: and list its themes.")
    try:
        return InterviewTemplate.from_dict(data)
    except TemplateError as exc:
        raise GuideError(str(exc)) from None


def load_guide_file(path: Union[str, Path]) -> Tuple[InterviewTemplate, str]:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise GuideError(f"Could not read that file: {exc}") from None
    return parse_guide(text), text


def describe(template: InterviewTemplate) -> str:
    themes = len(template.themes)
    questions = sum(len(t.guide_questions) for t in template.themes)
    return (f"{template.title}: {themes} theme{'s' if themes != 1 else ''}, "
            f"{questions} guide question{'s' if questions != 1 else ''}")


def save_guide(project: Any, text: str) -> None:
    project.set_meta(GUIDE_KEY, text)


def saved_guide(project: Any) -> Optional[InterviewTemplate]:
    text = project.get_meta(GUIDE_KEY, "")
    if not text:
        return None
    try:
        return parse_guide(text)
    except GuideError:
        return None


def ensure_codes(project: Any, template: InterviewTemplate) -> Dict[str, str]:
    """The guide's themes as codes in the codebook: an existing code with the same name is
    reused, the rest are added as a-priori codes. Returns theme id -> code id."""
    existing = {c.name.strip().lower(): c.code_id for c in project.get_codebook()}
    out: Dict[str, str] = {}
    for code in template.to_codes():
        key = code.name.strip().lower()
        if key in existing:
            out[code.code_id] = existing[key]
        else:
            new_id_ = project.add_code(_fresh(code))
            existing[key] = new_id_
            out[code.code_id] = new_id_
    return out


def _fresh(code: Any) -> Any:
    from dataclasses import replace

    return replace(code, code_id="")


# -- suggesting -------------------------------------------------------------------------

@dataclass
class GuideReport:
    run_id: str = ""
    questions: int = 0           # questions the interviewer asked
    pairs: int = 0               # questions that were followed by an answer
    matched: int = 0             # answers that fit at least one guide theme
    unclassified: int = 0        # answers that fit none (read these: often the most interesting)
    suggestions: int = 0         # coded passages made
    coverage: List[Dict[str, Any]] = field(default_factory=list)   # per guide question

    @property
    def guide_questions_missed(self) -> List[str]:
        return [r["guide_question"] for r in self.coverage if not r["addressed"]]


EmbedFn = Callable[[Sequence[str]], Any]


@dataclass
class GuidePlan:
    """What one run will do, worked out from the transcript alone (no model needed)."""
    source_id: str
    template: InterviewTemplate
    answered: List[Any]           # question/answer pairs that have an answer
    questions: int
    min_similarity: float = DEFAULT_MIN_SIMILARITY
    allow_multi_theme: bool = True


def plan(project: Any, source_id: str, template: InterviewTemplate, *,
         min_similarity: float = DEFAULT_MIN_SIMILARITY, allow_multi_theme: bool = True) -> GuidePlan:
    """Find the questions and the answers that followed them. Reads the project, writes nothing."""
    source = project.get_source(source_id)
    if source is None:
        raise GuideError("That transcript is not in the project.")
    turns = speakers.turns_of(source.raw_text, source.metadata)
    if not turns:
        raise GuideError("Say who is speaking in this transcript first. QualSafe needs to know "
                         "who asked and who answered.")
    questions = detect_questions(turns)
    answered = [p for p in pair_questions_with_responses(turns, questions) if p.response_turns]
    if not answered:
        raise GuideError("QualSafe could not find any question followed by an answer in this "
                         "transcript.")
    return GuidePlan(source_id, template, answered, len(questions), min_similarity, allow_multi_theme)


def match(plan_: GuidePlan, embed_fn: EmbedFn) -> Tuple[List[MatchedPair], List[Dict[str, Any]]]:
    """Score every answer against every guide theme. Touches no project, so it can run in the
    background while the window stays usable."""
    matched = match_qa_pairs(
        plan_.answered, plan_.template, embed_fn,
        {"min_similarity": plan_.min_similarity, "allow_multi_theme": plan_.allow_multi_theme})
    coverage = guide_question_coverage(plan_.answered, plan_.template, embed_fn, plan_.min_similarity)
    return matched, coverage


def apply(project: Any, plan_: GuidePlan, matched: List[MatchedPair],
          coverage: List[Dict[str, Any]]) -> GuideReport:
    """Keep the matches as suggestions. Replaces this transcript's earlier guide suggestions,
    so changing the guide or the strictness never piles one run on another."""
    from core.manifest import PACKAGE_VERSION
    from core.model import CodeApplication, Excerpt, Rater, RunManifest
    from core.project import new_id

    source_id = plan_.source_id
    source = project.get_source(source_id)
    report = GuideReport(questions=plan_.questions, pairs=len(plan_.answered), coverage=coverage)

    remove_suggestions(project, source_id)
    code_ids = ensure_codes(project, plan_.template)
    rater_id = project.add_rater(Rater(rater_id="", kind="transformer", name=MATCHER_NAME,
                                       model_id=""))
    existing_spans = {(e.char_start, e.char_end): e.excerpt_id
                      for e in project.list_excerpts(source_id)}
    created: List[str] = []
    run_id = project.add_run(RunManifest(
        run_id="", package_version=PACKAGE_VERSION, mode="interview", engine="transformer",
        model="interview guide", template_version=plan_.template.title,
        thresholds={"min_similarity": plan_.min_similarity,
                    "allow_multi_theme": plan_.allow_multi_theme},
        counts={"source_id": source_id}, exported_raw_text=False))

    for item in matched:
        if not item.matches:
            report.unclassified += 1
            continue
        report.matched += 1
        start = item.pair.response_turns[0].char_start
        end = item.pair.response_turns[-1].char_end
        excerpt_id = existing_spans.get((start, end))
        if excerpt_id is None:
            excerpt_id = project.add_excerpt(Excerpt(
                excerpt_id=new_id("exc"), source_id=source_id,
                text=source.raw_text[start:end], char_start=start, char_end=end))
            existing_spans[(start, end)] = excerpt_id
            created.append(excerpt_id)
        for found in item.matches:
            project.apply_code(CodeApplication(
                application_id="", excerpt_id=excerpt_id, code_id=code_ids[found.theme_id],
                coder="transformer", rater_id=rater_id, run_id=run_id,
                confidence=found.similarity, rationale=RATIONALE))
            report.suggestions += 1

    project.update_run_counts(run_id, {"source_id": source_id, "created_excerpts": created,
                                       "suggestions": report.suggestions})
    report.run_id = run_id
    return report


def suggest(project: Any, source_id: str, template: InterviewTemplate, embed_fn: EmbedFn, *,
            min_similarity: float = DEFAULT_MIN_SIMILARITY, allow_multi_theme: bool = True
            ) -> GuideReport:
    """Plan, match and keep, in one go (the desktop splits the middle step into a background
    thread; this is the same three steps for everything else)."""
    plan_ = plan(project, source_id, template, min_similarity=min_similarity,
                 allow_multi_theme=allow_multi_theme)
    matched, coverage = match(plan_, embed_fn)
    return apply(project, plan_, matched, coverage)


def suggestion_count(project: Any, source_id: Optional[str] = None) -> int:
    """Coded passages the guide matcher has made (for one transcript, or all)."""
    return len(_suggestions(project, source_id))


def _suggestions(project: Any, source_id: Optional[str]) -> List[Any]:
    raters = {r.rater_id for r in project.list_raters() if r.name == MATCHER_NAME}
    if not raters:
        return []
    if source_id is None:
        wanted = None
    else:
        wanted = {e.excerpt_id for e in project.list_excerpts(source_id)}
    return [a for a in project.list_applications()
            if a.rater_id in raters and (wanted is None or a.excerpt_id in wanted)]


def remove_suggestions(project: Any, source_id: Optional[str] = None) -> int:
    """Take away the guide matcher's suggestions (one transcript, or all). Never touches
    anything the researcher coded. Passages the matcher created that no longer carry any code
    are removed too. Returns how many suggestions were removed."""
    found = _suggestions(project, source_id)
    for app in found:
        project.delete_application(app.application_id)
    created = set()
    for run in project.list_runs():
        if run.mode == "interview" and run.model == "interview guide":
            if source_id is None or run.counts.get("source_id") == source_id:
                created.update(run.counts.get("created_excerpts") or [])
    still_coded = {a.excerpt_id for a in project.list_applications()}
    for excerpt_id in created - still_coded:
        project.delete_excerpt_if_unused(excerpt_id)
    return len(found)
