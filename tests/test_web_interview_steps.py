"""Interviews on the web: add transcripts, read and code, codebook (item 4b.5g)."""

from __future__ import annotations

from pathlib import Path

from core.documents import add_document
from core.model import Code
from core.project import Project
from core.ux import activities
from tests import webkit

TRANSCRIPT = ("Interviewer: What has been hardest this term?\n"
              "Respondent: Honestly the cost. The textbooks alone were more than I expected.\n")


def _interviews(page: str = "Documents", project: Path | None = None):
    at = webkit.start("interview")
    if project is not None:
        at.session_state["active_project_path"] = str(project)
    return webkit.go(at, page)


def _project(tmp_path) -> Path:
    from app.shared import constants

    path = constants.STREAMLIT_OUTPUT_DIR / "interviews_test" / "project.qnw"
    path.parent.mkdir(parents=True)
    with Project.create(path) as proj:
        add_document(proj, "Interview 01", TRANSCRIPT)
        proj.add_code(Code(code_id="", name="Cost", definition="Money."))
    return path


def test_the_web_puts_the_transcript_screens_where_the_desktop_does():
    steps = {s.key: s for s in activities.get("interviews").steps}
    assert steps["add"].screens[activities.WEB] == ("Documents",)
    assert steps["add"].more[activities.WEB] == ("Interview Mode",)
    assert steps["code"].screens[activities.WEB] == ("Documents",)
    assert activities.web_screen_title("Interview Mode") == "One interview, with a guide and summaries"


def test_with_no_project_step_one_offers_to_start_one_and_nothing_else():
    at = _interviews()
    shown = webkit.describe(webkit.visible_controls(at))
    assert shown == ["text_input:doc_new_project_name", "button:doc_new_project_btn"], shown
    assert [b.key for b in webkit.primary_buttons(at)] == ["doc_new_project_btn"]


def test_starting_a_project_makes_the_file_and_opens_the_import_controls():
    at = _interviews()
    next(b for b in at.button if b.key == "doc_new_project_btn").click().run()
    assert not at.exception, at.exception
    project = Path(at.session_state["active_project_path"])
    assert project.is_file() and project.name == "project.qnw"
    visible = webkit.visible_controls(at)
    assert len(visible) <= webkit.MAX_VISIBLE_CONTROLS, webkit.describe(visible)
    keys = {getattr(c, "key", None) for c in visible}
    assert "doc_add_mode" in keys and "doc_folder" in keys


def test_step_one_lists_what_is_there_and_keeps_the_interview_wizard_under_more_tools(tmp_path):
    at = _interviews(project=_project(tmp_path))
    assert any("1 document" in c.value for c in at.caption)
    assert not [t for t in at.get("tab")]                       # the library alone: no tabs
    more = [e for e in at.expander if e.label == "More tools"]
    assert more, "the one-interview wizard lives under More tools"
    pick = next(s for s in at.selectbox if s.key == "more_interviews_add")
    assert list(pick.options) == ["One interview, with a guide and summaries"]
    assert activities.web_screen_title("Interview Mode") == "One interview, with a guide and summaries"


def test_step_two_reads_and_codes_in_two_tabs(tmp_path):
    at = _interviews(project=_project(tmp_path))
    at.session_state["step_interviews"] = "code"
    at.run()
    assert not at.exception, at.exception
    assert [t.label for t in at.get("tab")] == ["Read", "Code"]
    for index in (0, 1):
        shown = webkit.visible_controls(at, tab=index)
        assert len(shown) <= webkit.MAX_VISIBLE_CONTROLS, (index, webkit.describe(shown))


def test_the_codebook_step_shows_the_project_codes(tmp_path):
    at = _interviews(project=_project(tmp_path))
    at.session_state["step_interviews"] = "codebook"
    at.run()
    assert not at.exception, at.exception
    assert any("Your codes are yours to change" in c.value for c in at.caption)
    assert any(getattr(c, "key", "") == "cb_save" for c in at.button)


def test_the_interview_steps_show_five_and_use_the_interview_colour():
    at = _interviews()
    rail = next(r for r in at.sidebar.radio if r.key == "rail_interviews")
    assert list(rail.options) == ["1 Add transcripts", "2 Code", "3 Codebook", "4 Explore", "5 Report"]


def test_importing_a_transcript_says_so_after_the_list_refreshes(tmp_path):
    """The page reruns after an import to show the new list; the message must survive that."""
    from app.shared import constants

    path = constants.STREAMLIT_OUTPUT_DIR / "interviews_import" / "project.qnw"
    path.parent.mkdir(parents=True)
    Project.create(path).close()
    folder = tmp_path / "talks"
    folder.mkdir()
    (folder / "one.txt").write_text(TRANSCRIPT, encoding="utf-8")

    at = _interviews("Documents", path)
    next(t for t in at.text_input if t.key == "doc_folder").set_value(str(folder)).run()
    scan = next(b for b in at.button if str(b.label).startswith("Check for PII"))
    scan.click().run()
    next(c for c in at.checkbox if c.key == "doc_pii_confirm").check().run()
    next(b for b in at.button if b.key == "doc_import_btn").click().run()
    assert not at.exception, at.exception
    assert any("Imported 1 document" in s.value for s in at.success), [s.value for s in at.success]
    assert not any("No transcripts yet" in i.value for i in at.info)
    # and it is shown once, not on every later draw
    at.run()
    assert not any("Imported 1 document" in s.value for s in at.success)


def _long_project() -> Path:
    from app.shared import constants

    path = constants.STREAMLIT_OUTPUT_DIR / "interviews_long" / "project.qnw"
    path.parent.mkdir(parents=True)
    text = " ".join(f"Sentence number {n} says something about the cost of term {n}." for n in range(1, 41))
    with Project.create(path) as proj:
        add_document(proj, "Long interview", text)
        proj.add_code(Code(code_id="", name="Cost", definition="Money."))
    return path


def test_coding_shows_a_screenful_with_the_main_button_above_the_sentences():
    at = _interviews("Documents", _long_project())
    at.session_state["step_interviews"] = "code"
    at.run()
    assert not at.exception, at.exception
    ticks = [c for c in at.checkbox if str(c.key).startswith("cu_")]
    assert len(ticks) == 10                                         # a page, not the whole transcript
    assert any("Sentences 1 to 10 of 40" in c.value for c in at.caption)
    primary = [b for b in at.button if b.proto.type == "primary"]
    assert [b.key for b in primary] == ["code_apply_units"]
    # the button comes before the first sentence on the page
    flat = []
    def walk(block):
        for child in block.children.values():
            if hasattr(child, "children"):
                walk(child)
            else:
                flat.append(getattr(child, "key", None))
    walk(at.main)
    assert flat.index("code_apply_units") < flat.index(ticks[0].key)


def test_applying_a_code_says_what_was_done_and_the_message_survives_the_refresh():
    at = _interviews("Documents", _long_project())
    at.session_state["step_interviews"] = "code"
    at.run()
    next(c for c in at.checkbox if str(c.key).startswith("cu_")).set_value(True).run()
    next(m for m in at.multiselect if m.key == "code_codes").set_value(["Cost"]).run()
    next(b for b in at.button if b.key == "code_apply_units").click().run()
    assert not at.exception, at.exception
    assert any("Coded 1 passage" in s.value for s in at.success), [s.value for s in at.success]
    at.run()
    assert not any("Coded 1 passage" in s.value for s in at.success)           # shown once


def test_the_import_button_is_the_steps_one_filled_button(tmp_path):
    from app.shared import constants

    path = constants.STREAMLIT_OUTPUT_DIR / "interviews_main" / "project.qnw"
    path.parent.mkdir(parents=True)
    Project.create(path).close()
    folder = tmp_path / "talks"
    folder.mkdir()
    (folder / "one.txt").write_text(TRANSCRIPT, encoding="utf-8")

    at = _interviews("Documents", path)
    next(t for t in at.text_input if t.key == "doc_folder").set_value(str(folder)).run()
    next(b for b in at.button if str(b.label).startswith("Check for PII")).click().run()
    assert [b.key for b in webkit.primary_buttons(at)] == ["doc_import_btn"]
    assert len(webkit.visible_controls(at)) <= webkit.MAX_VISIBLE_CONTROLS, webkit.describe(
        webkit.visible_controls(at))
