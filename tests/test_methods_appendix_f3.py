"""Methods appendix, book-audit F3: the research question, an optional position section, and limitations."""

from __future__ import annotations

from docx import Document

from core import research_question
from core.model import Memo
from core.project import Project
from exports import methods_appendix as ma


def _text(path) -> str:
    return "\n".join(p.text for p in Document(str(path)).paragraphs)


def _memo(project, text, author="human"):
    project.add_memo(Memo(memo_id="", target_type="project", target_id=None, text=text, author=author))


def _project(tmp_path):
    return Project.create(tmp_path / "m.qnw")


def test_the_research_question_opens_the_appendix_when_set(tmp_path):
    project = _project(tmp_path)
    out = tmp_path / "a.docx"
    ma.build_methods_appendix(project, out)
    assert "Research question" not in _text(out)
    research_question.set(project, "What helps first-year students stay?")
    ma.build_methods_appendix(project, out)
    text = _text(out)
    assert "Research question" in text and "What helps first-year students stay?" in text
    project.close()


def test_the_position_section_is_off_unless_asked_and_uses_only_the_analysts_own_notes(tmp_path):
    project = _project(tmp_path)
    _memo(project, "My position\nI was an advisor at this college for six years.")
    _memo(project, "An ethical worry\nSomething else entirely.")
    out = tmp_path / "a.docx"
    _memo(project, "My position\nA drafted line from a model.", author="llm_draft")
    ma.build_methods_appendix(project, out)
    assert "Researcher position" not in _text(out) and "advisor" not in _text(out)
    ma.build_methods_appendix(project, out, include_position=True)
    text = _text(out)
    assert "Researcher position" in text and "advisor at this college" in text
    assert "Something else entirely" not in text and "drafted line" not in text
    project.close()


def test_the_position_section_says_so_when_there_is_no_note(tmp_path):
    project = _project(tmp_path)
    out = tmp_path / "a.docx"
    ma.build_methods_appendix(project, out, include_position=True)
    assert "No diary note under" in _text(out)
    project.close()


def test_limitations_follow_from_what_the_record_shows():
    facts = {"n_sources": 4, "machine_raters": ["x (m)"], "human_raters": [], "demo_codings": 0}
    lines = ma.limitations(facts, {}, sampling_note="uncertainty sample")
    joined = " ".join(lines)
    assert "4 source(s)" in joined and "suggested by a model" in joined
    assert "No second coder" in joined and "not chosen at random" in joined
    quiet = {"n_sources": 40, "machine_raters": [], "human_raters": ["a", "b"], "demo_codings": 0}
    assert ma.limitations(quiet, {"k": object()}) == []


def test_the_appendix_always_has_a_limitations_heading(tmp_path):
    project = _project(tmp_path)
    out = tmp_path / "a.docx"
    ma.build_methods_appendix(project, out)
    assert "Limitations" in _text(out)
    project.close()
