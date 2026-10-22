"""Interviews on the web: who is speaking, and suggestions from an interview guide (the desktop's 4.5 and 4.6)."""

from __future__ import annotations

from pathlib import Path

from core import guide_mapping as gm
from core import speakers
from core.documents import add_document
from core.project import Project
from tests import test_guide_mapping as helpers
from tests import webkit


def _project(guide: bool = False, reviewed: bool = False) -> Path:
    from app.shared import constants

    path = constants.STREAMLIT_OUTPUT_DIR / "interviews_parity" / "project.qnw"
    path.parent.mkdir(parents=True)
    with Project.create(path) as proj:
        sid = add_document(proj, "Interview 01", helpers.TRANSCRIPT)
        if reviewed:
            review = speakers.analyse(helpers.TRANSCRIPT)
            proj.update_source_metadata(sid, {"speakers": speakers.to_metadata(
                review, {row.label: row.role for row in review.rows})})
        if guide:
            gm.save_guide(proj, helpers.GUIDE)
            gm.ensure_codes(proj, gm.parse_guide(helpers.GUIDE))
    return path


def _open(path: Path, step: str):
    at = webkit.start("interview")
    at.session_state["active_project_path"] = str(path)
    at = webkit.go(at, "Documents")
    if step != "add":
        at.session_state["step_interviews"] = step
        at.run()
    return at


def _button(at, key):
    return next(b for b in at.button if b.key == key)


def test_a_transcript_with_two_speakers_asks_who_is_speaking_and_keeps_nothing_until_confirmed():
    path = _project()
    at = _open(path, "add")
    assert not at.exception, at.exception
    assert any("Who is speaking in Interview 01" in m.value for m in at.markdown)
    with Project.open(path) as proj:
        assert not speakers.stored(proj.get_source(proj.list_sources()[0].source_id).metadata)
    _button(at, next(b.key for b in at.button if b.key.startswith("spk_use_"))).click().run()
    assert not at.exception, at.exception
    with Project.open(path) as proj:
        record = speakers.stored(proj.get_source(proj.list_sources()[0].source_id).metadata)
    assert record and set(record["roles"].values()) >= {"interviewer", "interviewee"}
    assert not any("Who is speaking in" in m.value for m in at.markdown)


def test_skip_leaves_the_transcript_alone_and_can_be_asked_again():
    path = _project()
    at = _open(path, "add")
    _button(at, next(b.key for b in at.button if b.key.startswith("spk_skip_"))).click().run()
    assert not any("Who is speaking in" in m.value for m in at.markdown)
    with Project.open(path) as proj:
        assert not speakers.stored(proj.get_source(proj.list_sources()[0].source_id).metadata)
    _button(at, "doc_speakers_again").click().run()
    assert any("Who is speaking in" in m.value for m in at.markdown)


def test_the_guide_needs_the_speakers_confirmed_first(monkeypatch):
    import app.documents_page as page

    monkeypatch.setattr(page, "_guide_unavailable", lambda: "")
    at = _open(_project(guide=True), "code")
    _button(at, "guide_suggest").click().run()
    assert any("Say who is speaking first" in i.value for i in at.info)


def test_the_guide_says_when_the_engine_is_missing(monkeypatch):
    import app.documents_page as page

    monkeypatch.setattr(page, "_guide_unavailable", lambda: "Matching needs the analysis engine, which is not installed.")
    at = _open(_project(guide=True, reviewed=True), "code")
    _button(at, "guide_suggest").click().run()
    assert any("analysis engine" in i.value for i in at.info)


def test_suggesting_from_the_guide_then_removing_the_suggestions(monkeypatch):
    import app.documents_page as page

    monkeypatch.setattr(page, "_guide_unavailable", lambda: "")
    monkeypatch.setattr(page, "guide_embedder", lambda: helpers.embed)
    path = _project(guide=True, reviewed=True)
    at = _open(path, "code")
    assert any("No guide" not in c.value and "themes" in c.value for c in at.caption)
    _button(at, "guide_suggest").click().run()
    assert not at.exception, at.exception
    with Project.open(path) as proj:
        sid = proj.list_sources()[0].source_id
        assert gm.suggestion_count(proj, sid) > 0
    remove = next(b for b in at.button if b.key == "guide_remove")
    remove.click().run()
    with Project.open(path) as proj:
        assert gm.suggestion_count(proj, sid) == 0
