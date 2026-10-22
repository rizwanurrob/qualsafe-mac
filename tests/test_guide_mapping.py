"""core/guide_mapping: an interview guide matched to a transcript, kept as removable suggestions."""

from __future__ import annotations

import json
import zlib
from pathlib import Path

import numpy as np
import pytest

from core import guide_mapping as gm
from core import speakers
from core.documents import add_document
from core.model import CodeApplication, Rater
from core.project import Project

ROOT = Path(__file__).resolve().parents[1]
GUIDE = (ROOT / "config" / "interview_template.example.yaml").read_text(encoding="utf-8")
TRANSCRIPT = (ROOT / "data" / "sample_interview_transcript.txt").read_text(encoding="utf-8")


def embed(texts):
    """A fixed, tiny stand-in for the real embedder: words hashed into 64 slots."""
    out = []
    for text in texts:
        v = np.zeros(64)
        for word in text.lower().split():
            v[zlib.crc32(word.encode()) % 64] += 1
        out.append(v / (np.linalg.norm(v) or 1.0))
    return np.array(out)


@pytest.fixture
def project(tmp_path):
    with Project.create(tmp_path / "p.qnw") as proj:
        yield proj


@pytest.fixture
def source_id(project):
    sid = add_document(project, "Interview 01", TRANSCRIPT)
    review = speakers.analyse(TRANSCRIPT)
    project.update_source_metadata(sid, {"speakers": speakers.to_metadata(
        review, {row.label: row.role for row in review.rows})})
    return sid


# -- the guide file ---------------------------------------------------------------------

def test_the_example_guide_loads_and_is_described():
    template = gm.parse_guide(GUIDE)
    assert gm.describe(template) == "Student Belonging Interview Guide: 5 themes, 8 guide questions"


@pytest.mark.parametrize("text,fragment", [
    ("a: [unclosed", "not a readable guide"),
    ("just some words", "does not look like an interview guide"),
    ("interview_template:\n  title: T\n  themes: []\n", "themes"),
])
def test_a_bad_guide_is_refused_in_words_a_researcher_can_use(text, fragment):
    with pytest.raises(gm.GuideError, match=fragment):
        gm.parse_guide(text)


def test_a_missing_file_is_refused_too(tmp_path):
    with pytest.raises(gm.GuideError, match="Could not read"):
        gm.load_guide_file(tmp_path / "nope.yaml")


def test_the_guide_is_kept_in_the_project_and_survives_a_reopen(tmp_path):
    path = tmp_path / "p.qnw"
    with Project.create(path) as proj:
        assert gm.saved_guide(proj) is None
        gm.save_guide(proj, GUIDE)
    with Project.open(path) as proj:
        assert gm.describe(gm.saved_guide(proj)).startswith("Student Belonging")
        proj.set_meta(gm.GUIDE_KEY, "not a guide")
        assert gm.saved_guide(proj) is None


def test_guide_themes_become_codes_and_an_existing_code_is_reused(project):
    from core.model import Code

    project.add_code(Code(code_id="", name="TRANSITION TO COLLEGE"))
    template = gm.parse_guide(GUIDE)
    first = gm.ensure_codes(project, template)
    assert len(first) == 5 and len(project.get_codebook()) == 5
    assert gm.ensure_codes(project, template) == first          # again: nothing new
    assert len(project.get_codebook()) == 5


# -- suggesting -------------------------------------------------------------------------

def test_matching_needs_the_speakers_confirmed_first(project):
    sid = add_document(project, "Interview 01", TRANSCRIPT)
    with pytest.raises(gm.GuideError, match="who is speaking"):
        gm.suggest(project, sid, gm.parse_guide(GUIDE), embed)


def test_a_transcript_with_no_answered_question_says_so(project):
    text = "Interviewer: Hello there.\nRespondent: Hi.\n"
    sid = add_document(project, "x", text)
    review = speakers.analyse(text)
    project.update_source_metadata(sid, {"speakers": speakers.to_metadata(
        review, {r.label: r.role for r in review.rows})})
    with pytest.raises(gm.GuideError, match="any question followed by an answer"):
        gm.suggest(project, sid, gm.parse_guide(GUIDE), embed)


def test_suggestions_are_the_matchers_own_and_say_so_in_a_fixed_phrase(project, source_id):
    report = gm.suggest(project, source_id, gm.parse_guide(GUIDE), embed, min_similarity=0.0)
    assert report.questions == 9 and report.pairs == 8 and report.matched == 8
    assert report.unclassified == 0 and report.suggestions == 40
    assert gm.suggestion_count(project, source_id) == 40
    matcher = {r.rater_id for r in project.list_raters() if r.name == gm.MATCHER_NAME}
    apps = project.list_applications()
    assert apps and all(a.rater_id in matcher and a.rationale == gm.RATIONALE for a in apps)
    # every suggested passage is a verbatim slice of the transcript
    source = project.get_source(source_id)
    for excerpt in project.list_excerpts(source_id):
        assert excerpt.text == source.raw_text[excerpt.char_start:excerpt.char_end]


def test_a_strict_setting_suggests_nothing_and_counts_the_answers_it_left_alone(project, source_id):
    report = gm.suggest(project, source_id, gm.parse_guide(GUIDE), embed, min_similarity=1.01)
    assert report.matched == 0 and report.unclassified == 8 and report.suggestions == 0
    assert gm.suggestion_count(project) == 0 and project.list_excerpts(source_id) == []


def test_coverage_names_the_guide_questions_that_were_not_asked(project, source_id):
    report = gm.suggest(project, source_id, gm.parse_guide(GUIDE), embed, min_similarity=1.01)
    assert len(report.coverage) == 8
    assert report.guide_questions_missed == [row["guide_question"] for row in report.coverage
                                              if not row["addressed"]]


def test_running_it_again_replaces_the_suggestions_instead_of_piling_them_up(project, source_id):
    template = gm.parse_guide(GUIDE)
    gm.suggest(project, source_id, template, embed, min_similarity=0.0)
    gm.suggest(project, source_id, template, embed, min_similarity=0.0)
    assert gm.suggestion_count(project, source_id) == 40
    assert len(project.list_excerpts(source_id)) == 8


def test_removing_the_suggestions_never_touches_what_the_researcher_coded(project, source_id):
    template = gm.parse_guide(GUIDE)
    gm.suggest(project, source_id, template, embed, min_similarity=0.0)
    # the researcher codes one of the same passages and another one of their own
    mine = project.add_rater(Rater(rater_id="", kind="human", name="Me", model_id=""))
    first = project.list_excerpts(source_id)[0]
    code_id = project.get_codebook()[0].code_id
    project.apply_code(CodeApplication(application_id="", excerpt_id=first.excerpt_id, code_id=code_id,
                                       coder="human", rater_id=mine))
    removed = gm.remove_suggestions(project, source_id)
    assert removed == 40 and gm.suggestion_count(project) == 0
    left = project.list_applications()
    assert len(left) == 1 and left[0].rater_id == mine
    assert [e.excerpt_id for e in project.list_excerpts(source_id)] == [first.excerpt_id]


def test_nothing_from_the_answers_is_kept_beyond_the_passages_themselves(project, source_id):
    gm.suggest(project, source_id, gm.parse_guide(GUIDE), embed, min_similarity=0.0)
    runs = [r for r in project.list_runs() if r.model == "interview guide"]
    assert len(runs) == 1
    blob = json.dumps([runs[0].thresholds, runs[0].counts])
    for phrase in ("tuition", "roommate", "laptop", "financial aid"):
        assert phrase not in blob
    assert all(a.rationale == gm.RATIONALE for a in project.list_applications())


def test_a_passage_with_a_note_survives_removing_the_suggestion(project, source_id):
    from core.model import Annotation

    gm.suggest(project, source_id, gm.parse_guide(GUIDE), embed, min_similarity=0.0)
    first = project.list_excerpts(source_id)[0]
    project.add_annotation(Annotation(annotation_id="", excerpt_id=first.excerpt_id, text="check this"))
    gm.remove_suggestions(project, source_id)
    assert [e.excerpt_id for e in project.list_excerpts(source_id)] == [first.excerpt_id]
