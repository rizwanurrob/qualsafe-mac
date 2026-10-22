"""The last step (Report) on the web: three common reports, the rest under More reports (item 4b.5e)."""

from __future__ import annotations

from pathlib import Path

from core.model import Code
from core.project import Project
from core.ux import words
from tests import webkit

ROOT = Path(__file__).resolve().parents[1]


def _report(tmp_path, with_project: bool = True):
    at = webkit.start("survey")
    if with_project:
        store = tmp_path / "run_rep" / "project.qnw"
        store.parent.mkdir(parents=True)
        with Project.create(store) as proj:
            proj.add_code(Code(code_id="", name="Cost", definition="Money worries"))
        at.session_state["active_project_path"] = str(store)
    return webkit.go(at, "Results & Downloads")


def test_the_step_asks_which_report_and_offers_the_three_common_ones(tmp_path):
    at = _report(tmp_path)
    kind = next(r for r in at.radio if r.key == "report_kind")
    assert len(kind.options) == 3
    assert at.session_state["report_kind"] == "methods"


def test_each_report_shows_few_controls_and_one_main_button(tmp_path):
    at = _report(tmp_path)
    for choice, button in (("methods", "rep_ma_btn"), ("codebook", "rep_cb_btn")):
        next(r for r in at.radio if r.key == "report_kind").set_value(choice).run()
        assert not at.exception, at.exception
        visible = webkit.visible_controls(at)
        assert len(visible) <= webkit.MAX_VISIBLE_CONTROLS, (choice, webkit.describe(visible))
        assert [b.key for b in webkit.primary_buttons(at)] == [button]


def test_the_methods_appendix_builds_and_offers_the_download(tmp_path):
    at = _report(tmp_path)
    next(b for b in at.button if b.key == "rep_ma_btn").click().run()
    assert not at.exception, at.exception
    assert at.session_state["rep_ma"][:2] == b"PK"
    assert any(getattr(d, "key", "") == "rep_ma_dl" for d in at.get("download_button"))


def test_quotes_are_off_unless_asked_for(tmp_path):
    at = _report(tmp_path)
    next(r for r in at.radio if r.key == "report_kind").set_value("codebook").run()
    assert next(c for c in at.checkbox if c.key == "rep_cb_examples").value is False


def test_the_other_reports_are_folded_away(tmp_path):
    at = _report(tmp_path)
    outside = {getattr(c, "key", None) for c in webkit.visible_controls(at)}
    inside = {getattr(c, "key", None) for c in webkit.all_controls(at)}
    for folded in ("rep_fw_codes", "rep_fw_btn", "rep_audit_btn", "rep_audit_memos"):
        assert folded in inside and folded not in outside, folded
    assert any(e.label == "More reports" for e in at.expander)


def test_without_a_project_it_says_what_is_needed(tmp_path):
    at = _report(tmp_path, with_project=False)
    assert any("A project is needed" in i.value for i in at.info)
    assert webkit.primary_buttons(at) == []


def test_the_run_files_are_one_zip_not_a_wall_of_buttons(tmp_path):
    from app.shared import constants

    run = constants.STREAMLIT_OUTPUT_DIR / "run_20261010_101010"
    run.mkdir(parents=True)
    for name in ("responses_scored.csv", "cluster_summary.csv", "run_config.json"):
        (run / name).write_text("a,b\n1,2\n", encoding="utf-8")
    at = _report(tmp_path, with_project=False)
    next(r for r in at.radio if r.key == "report_kind").set_value("files").run()
    assert not at.exception, at.exception
    visible = webkit.visible_controls(at)
    assert len(visible) <= webkit.MAX_VISIBLE_CONTROLS, webkit.describe(visible)
    next(b for b in at.button if b.key == "report_zip_btn").click().run()
    assert at.session_state["report_zip"][0] == "run_20261010_101010"
    assert at.session_state["report_zip"][1][:2] == b"PK"


def test_the_words_on_this_screen_are_plain():
    text = (ROOT / "app" / "results.py").read_text(encoding="utf-8")
    for string in words.ui_strings(text):
        assert words.find_never(string) == [], string
        assert words.find_replace(string) == [], string
