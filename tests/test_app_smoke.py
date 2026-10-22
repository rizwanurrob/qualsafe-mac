"""
Headless render-smoke of the Streamlit app (v3.7: mode-aware navigation).

Renders the start wizard (no mode chosen), then every page of each mode, and
asserts no exception. Catches wiring/render-time breakage (bad imports, missing
session keys, renamed widgets) that plain module import cannot. It does NOT run
pipelines or load models — pages render their initial (empty-state) view.

QNW_SETTINGS_DIR points app-settings persistence at a temp dir so test runs never
write app_settings.json into the repo.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

APP_PATH = Path(__file__).resolve().parent.parent / "streamlit_app.py"

SURVEY_PAGES = [
    "Data Setup", "Theme Setup", "Run Analysis", "Iterative Labeling Lab",
    "Alt Survey Flow", "Analysis", "Chart Builder", "Data Charts", "Modelling",
    "Codebook", "Documents", "Search", "Query & Synthesis", "Results & Downloads",
    "Data Management", "Model Manager", "Help & Troubleshooting",
]
INTERVIEW_PAGES = [
    "Interview Mode", "Analysis", "Chart Builder", "Data Charts", "Modelling", "Codebook",
    "Documents", "Search", "Query & Synthesis", "Results & Downloads", "Data Management",
    "Model Manager", "Help & Troubleshooting",
]


@pytest.fixture(autouse=True)
def _isolate_settings():
    # Per-test isolation: each test gets a fresh settings dir, so a persisted
    # preference written by one test (e.g. the embedding model, which the Run
    # Analysis render sets) can't leak app_mode into the next and mismatch the nav.
    with tempfile.TemporaryDirectory() as tmp:
        old = os.environ.get("QNW_SETTINGS_DIR")
        os.environ["QNW_SETTINGS_DIR"] = tmp
        yield
        if old is None:
            os.environ.pop("QNW_SETTINGS_DIR", None)
        else:
            os.environ["QNW_SETTINGS_DIR"] = old


class _Nav:
    """Go to a page by its name, the way every Continue button in the app does.

    The page list is gone from the sidebar (Update 3, phase 4b): a step shows its screens, and a
    button anywhere sets `nav_target` to a page name. These tests keep saying `_nav(at).set_value(page)`
    and get exactly that.
    """

    def __init__(self, at):
        self.at = at

    @property
    def options(self):
        rail = [r for r in self.at.sidebar.radio if r.key.startswith("rail_")]
        return list(rail[0].options) if rail else []

    def set_value(self, page):
        self.at.session_state["nav_target"] = page
        return self.at


def _caveats(at) -> str:
    """Every caveat on the page, whole: the short boxes plus what is folded under each Why?."""
    shown = [str(w.value) for w in list(at.warning) + list(at.info)]
    folded = [str(m.value) for e in at.expander if e.label == "Why?" for m in e.markdown]
    return " ".join(shown + folded)


def _nav(at):
    return _Nav(at)


def _more(at, which: str):
    """Open one of the rarer analyses (Joint display, Saturation, Deviant cases): they sit behind a
    choice on the More tab, so only the one chosen is drawn."""
    next(x for x in at.selectbox if x.key == "an_more").set_value(which).run()
    assert not at.exception, at.exception


def _app(mode: str = ""):
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(APP_PATH), default_timeout=300)
    if mode:
        at.session_state["app_mode"] = mode
    at.run()
    assert not at.exception, f"initial render raised: {at.exception}"
    return at


def test_home_is_the_first_page_and_has_three_activities():
    at = _app("")
    headers = " ".join(h.value for h in at.header)
    assert "What would you like to do?" in headers
    assert at.session_state["view"] == "home"
    starts = [b.key for b in at.button if b.key.startswith("start_")]
    assert starts == ["start_surveys", "start_charts", "start_interviews"]
    assert not any(r.key.startswith("rail_") for r in at.sidebar.radio)


@pytest.mark.parametrize("page", SURVEY_PAGES)
def test_survey_page_renders(page):
    at = _app("survey")
    _nav(at).set_value(page).run()
    assert not at.exception, f"survey page '{page}' raised: {at.exception}"


@pytest.mark.parametrize("page", INTERVIEW_PAGES)
def test_interview_page_renders(page):
    at = _app("interview")
    _nav(at).set_value(page).run()
    assert not at.exception, f"interview page '{page}' raised: {at.exception}"


def test_the_page_lists_here_match_the_shell():
    """These lists drive every render test, so a page added to the shell and not
    to them is a page nothing renders. Assert every page has a renderer and a place."""
    import streamlit_app
    from core.ux import activities

    placed = {activities.top_level(sc) for _a, _s, sc, _m in activities.placements(activities.WEB)}
    placed |= set(activities.SETTINGS_SCREENS[activities.WEB]) | set(activities.HELP_SCREENS[activities.WEB])
    assert set(streamlit_app._PAGE_RENDERERS) >= set(SURVEY_PAGES) | set(INTERVIEW_PAGES)
    assert set(streamlit_app._PAGE_RENDERERS) == placed


def test_interview_steps_omit_survey_only_pages():
    at = _app("interview")
    assert _nav(at).options == ["1 Add transcripts", "2 Code", "3 Codebook", "4 Explore", "5 Report"]
    surveys = _app("survey")
    assert _nav(surveys).options == ["1 Load", "2 Themes", "3 Code", "4 Explore", "5 Report"]


def test_start_surveys_opens_the_first_step():
    """Clicking Start on the Surveys card opens Surveys on Load."""
    at = _app("")
    next(b for b in at.button if b.key == "start_surveys").click().run()
    assert not at.exception
    assert at.session_state["view"] == "activity" and at.session_state["activity"] == "surveys"
    assert at.session_state["app_mode"] == "survey" and at.session_state["step_surveys"] == "load"
    assert "Your answers" in " ".join(h.value for h in at.subheader)


def test_a_page_name_from_a_continue_button_lands_in_the_right_activity_and_step():
    at = _app("survey")
    _nav(at).set_value("Run Analysis").run()
    assert not at.exception
    assert (at.session_state["activity"], at.session_state["step_surveys"]) == ("surveys", "code")
    assert at.session_state["screen_surveys_code"] == "Run Analysis"
    _nav(at).set_value("Model Manager").run()
    assert at.session_state["view"] == "settings" and at.session_state["settings_tab"] == "Models"
    _nav(at).set_value("Help & Troubleshooting").run()
    assert at.session_state["view"] == "help"


def test_home_button_returns_to_home():
    at = _app("survey")
    next(b for b in at.button if b.key == "nav_home").click().run()
    assert not at.exception
    assert at.session_state["view"] == "home" and at.session_state["app_mode"] == ""
    headers = " ".join(h.value for h in at.header)
    assert "What would you like to do?" in headers


def test_pii_gate_confirm_reveals_column_mapping():
    """Regression: ticking the PII checkbox must let Column Mapping appear.

    The re-arm helper used to fire on every rerun of an unconfirmed file and
    pop the checkbox key, so the tick was destroyed before the confirmation was
    recorded — the gate could never be confirmed and mapping never showed
    (bug present v3.1.1–v3.9.0). This drives the real tick→rerun flow, which the
    unit test of reset_pii_gate_if_source_changed() alone did not cover.
    """
    import pandas as pd

    at = _app("survey")
    at.session_state["df"] = pd.DataFrame(
        {"response_id": ["1", "2"], "answer": ["good", "bad"], "program": ["A", "B"]}
    )
    at.session_state["input_source"] = "upload:regression.csv"
    _nav(at).set_value("Data Setup").run()

    # Gate is up; the answers column is not offered yet.
    assert "Where are the answers?" not in " ".join(s.value for s in at.subheader)

    pii = next(c for c in at.checkbox if "confirm this file" in c.label)
    pii.set_value(True).run()

    assert not at.exception
    assert at.session_state["pii_confirmed"] is True
    # The tick survived the rerun and mapping is now offered.
    assert next(c for c in at.checkbox if "confirm this file" in c.label).value is True
    assert "Where are the answers?" in " ".join(s.value for s in at.subheader)


def test_search_page_finds_and_autocodes(tmp_path):
    """v4 Phase 1: the Search page searches the active project and codes hits."""
    from core.model import Source
    from core.project import Project

    store = tmp_path / "run_search" / "project.qnw"
    store.parent.mkdir(parents=True)
    with Project.create(store) as proj:
        src = Source(source_id="s1", type="document",
                     raw_text="Tuition cost is a worry. The cost of books too.",
                     label="Doc 1", metadata={"title": "Doc 1"})
        proj.add_source(src)
        proj.add_whole_response_excerpt(src)

    at = _app("survey")
    at.session_state["active_project_path"] = str(store)
    _nav(at).set_value("Search").run()
    assert not at.exception

    query = next(t for t in at.text_input if t.key == "search_query")
    query.set_value("cost").run()
    assert not at.exception
    # Both occurrences found and reported.
    assert any("2" in m.value and "hit" in m.value.lower()
               for m in at.success), [m.value for m in at.success]

    # Auto-code them, and confirm they landed under the non-human rater.
    next(t for t in at.text_input if t.key == "autocode_name").set_value("Cost").run()
    next(b for b in at.button if b.key == "autocode_btn").click().run()
    assert not at.exception
    with Project.open(store) as proj:
        coding = proj.coding_table()
    assert len(coding) == 2
    assert set(coding["rater_id"]) == {"auto_textsearch"}


def test_results_page_builds_a_codebook_report(tmp_path):
    """v4 Phase 5: the Reports section generates a real .docx from the project."""
    from core.model import Code
    from core.project import Project

    store = tmp_path / "run_rep" / "project.qnw"
    store.parent.mkdir(parents=True)
    with Project.create(store) as proj:
        proj.add_code(Code(code_id="", name="Cost", definition="Money worries"))

    at = _app("survey")
    at.session_state["active_project_path"] = str(store)
    _nav(at).set_value("Results & Downloads").run()
    assert not at.exception

    next(r for r in at.radio if r.key == "report_kind").set_value("codebook").run()
    next(b for b in at.button if b.key == "rep_cb_btn").click().run()
    assert not at.exception
    data = at.session_state["rep_cb"]
    assert data[:2] == b"PK", "a .docx is a zip archive"
    assert len(data) > 1000


def test_query_page_retrieves_and_builds_a_framework_cell(tmp_path):
    """v4 Phase 3: boolean retrieval, and a saved framework-matrix cell."""
    from analysis.framework import get_cell_summary
    from core.documents import add_document
    from core.model import Case, Code, CodeApplication, Excerpt, Rater
    from core.project import Project

    store = tmp_path / "run_q" / "project.qnw"
    store.parent.mkdir(parents=True)
    with Project.create(store) as proj:
        sid = add_document(proj, "Interview 1", "The cost of housing is the hardest part.")
        case_id = proj.add_case(Case(case_id="", name="Alice"))
        proj.assign_source_to_case(case_id, sid)
        proj.add_rater(Rater(rater_id="human_primary", kind="human"))
        eid = proj.add_excerpt(Excerpt(excerpt_id="", source_id=sid, text="cost of housing",
                                       char_start=4, char_end=19))
        for name in ("Cost", "Housing"):
            code_id = proj.add_code(Code(code_id="", name=name))
            proj.apply_code(CodeApplication(application_id="", excerpt_id=eid,
                                            code_id=code_id, coder="human",
                                            rater_id="human_primary"))

    at = _app("survey")
    at.session_state["active_project_path"] = str(store)
    _nav(at).set_value("Query & Synthesis").run()
    assert not at.exception

    next(t for t in at.text_input if t.key == "q_text").set_value("Cost AND Housing").run()
    assert not at.exception
    assert any("excerpt(s) match" in m.value and "**1**" in m.value
               for m in at.success), [m.value for m in at.success]

    # Write a framework cell and confirm it persists against (case, code).
    next(t for t in at.text_area if t.key == "fw_text").set_value("Alice stresses cost.").run()
    next(b for b in at.button if b.key == "fw_save").click().run()
    assert not at.exception
    with Project.open(store) as proj:
        memo = get_cell_summary(proj, case_id, "Cost")
    assert memo is not None and memo.text == "Alice stresses cost."


def test_documents_page_imports_and_reads(tmp_path):
    """v4 Phase 2a: import documents behind the gate, then read one with stripes."""
    from core.documents import add_document
    from core.model import Code, CodeApplication, Excerpt, Rater
    from core.project import Project

    store = tmp_path / "run_docs" / "project.qnw"
    store.parent.mkdir(parents=True)
    with Project.create(store) as proj:
        sid = add_document(proj, "Interview 1", "The cost of housing is the hardest part.")
        proj.add_rater(Rater(rater_id="human_primary", kind="human"))
        code_id = proj.add_code(Code(code_id="", name="Cost"))
        eid = proj.add_excerpt(Excerpt(excerpt_id="", source_id=sid, text="cost",
                                       char_start=4, char_end=8))
        proj.apply_code(CodeApplication(application_id="", excerpt_id=eid, code_id=code_id,
                                        coder="human", rater_id="human_primary"))

    at = _app("survey")
    at.session_state["active_project_path"] = str(store)
    _nav(at).set_value("Documents").run()
    assert not at.exception
    # Step 1 lists the document; step 2's reader reports its coverage.
    assert any("1 document" in c.value for c in at.caption), [c.value for c in at.caption]
    at.session_state["step_interviews"] = "code"
    at.run()
    assert not at.exception
    assert any(m.label == "Coded passages" and m.value == "1" for m in at.metric)


def test_documents_page_codes_a_passage_by_hand(tmp_path):
    """v4 Phase 2b: tick a sentence, apply a code, and it lands as an exact span."""
    from core.documents import add_document
    from core.project import Project

    store = tmp_path / "run_code" / "project.qnw"
    store.parent.mkdir(parents=True)
    text = "The cost of housing is the hardest part. My advisor helped a lot."
    with Project.create(store) as proj:
        add_document(proj, "Interview 1", text)

    at = _app("survey")
    at.session_state["active_project_path"] = str(store)
    _nav(at).set_value("Documents").run()
    at.session_state["step_interviews"] = "code"           # reading and coding are step 2
    at.run()

    # Tick the first sentence, name a new code, apply.
    unit_box = next(c for c in at.checkbox if c.key and c.key.startswith("cu_"))
    unit_box.set_value(True).run()
    next(t for t in at.text_input if t.key == "code_new").set_value("Cost").run()
    next(b for b in at.button if b.key == "code_apply_units").click().run()
    assert not at.exception

    with Project.open(store) as proj:
        coding = proj.coding_table()
        assert len(coding) == 1
        assert coding.iloc[0]["code_name"] == "Cost"
        assert coding.iloc[0]["rater_id"] == "human_primary"
        excerpt = proj.get_excerpt(coding.iloc[0]["excerpt_id"])
        # The excerpt must quote the document exactly.
        assert text[excerpt.char_start:excerpt.char_end] == excerpt.text
        assert "cost of housing" in excerpt.text


def test_documents_import_is_blocked_until_confirmed(tmp_path):
    """Nothing is written to the project until the PII attestation is given."""
    from core.documents import DOCUMENT_TYPE
    from core.project import Project

    store = tmp_path / "run_gate" / "project.qnw"
    store.parent.mkdir(parents=True)
    with Project.create(store):
        pass
    folder = tmp_path / "docs"
    folder.mkdir()
    (folder / "a.txt").write_text("some interview text", encoding="utf-8")

    at = _app("survey")
    at.session_state["active_project_path"] = str(store)
    _nav(at).set_value("Documents").run()
    next(t for t in at.text_input if t.key == "doc_folder").set_value(str(folder)).run()
    next(b for b in at.button if b.key == "doc_scan_btn").click().run()
    assert not at.exception

    # The import button exists but is disabled before attestation.
    import_btn = next(b for b in at.button if b.key == "doc_import_btn")
    assert import_btn.disabled is True
    with Project.open(store) as proj:
        assert proj.count_sources(DOCUMENT_TYPE) == 0

    next(c for c in at.checkbox if c.key == "doc_pii_confirm").set_value(True).run()
    next(b for b in at.button if b.key == "doc_import_btn").click().run()
    assert not at.exception
    with Project.open(store) as proj:
        assert proj.count_sources(DOCUMENT_TYPE) == 1


def test_rebuild_working_data_from_project(tmp_path):
    """v3.9.1: Data Setup can rebuild the responses from the active .qnw alone."""
    from core.model import Source
    from core.project import Project

    store = tmp_path / "run_reb" / "project.qnw"
    store.parent.mkdir(parents=True)
    with Project.create(store) as proj:
        src = Source(source_id="s1", type="survey_response", raw_text="advising helped",
                     label="Q1", metadata={"response_id": "1", "question_text": "Q1"})
        proj.add_source(src)
        proj.add_whole_response_excerpt(src)

    at = _app("survey")
    at.session_state["active_project_path"] = str(store)
    _nav(at).set_value("Data Setup").run()

    btn = next(b for b in at.button if b.key == "rebuild_from_store")
    btn.click().run()
    assert not at.exception

    df = at.session_state["df"]
    assert list(df["response_text"]) == ["advising helped"]
    assert at.session_state["text_column"] == "response_text"
    assert at.session_state["id_column"] == "response_id"
    assert str(at.session_state["input_source"]).startswith("project:")


def test_alt_survey_flow_codes_reviews_and_applies(tmp_path):
    """Alt Survey Flow Phase 1: add a code, run with the demo engine (Laya is
    never installed in this suite), accept a suggestion in the Review Queue,
    and confirm it landed as a real CodeApplication."""
    import pandas as pd
    from core.project import Project

    store = tmp_path / "run_asf" / "project.qnw"
    store.parent.mkdir(parents=True)
    with Project.create(store):
        pass

    at = _app("survey")
    at.session_state["active_project_path"] = str(store)
    at.session_state["df"] = pd.DataFrame({
        "response_id": ["1", "2"],
        "response_text": ["I could not afford rent this semester.",
                          "The campus is lovely in autumn."],
    })
    at.session_state["text_column"] = "response_text"
    at.session_state["id_column"] = "response_id"
    _nav(at).set_value("Alt Survey Flow").run()
    assert not at.exception

    next(t for t in at.text_input if t.key == "asf_new_name").set_value("Financial stress").run()
    next(a for a in at.text_area if a.key == "asf_new_inc").set_value(
        "mentions difficulty affording costs").run()
    next(b for b in at.button if b.key == "asf_add_code").click().run()
    assert not at.exception

    # No Laya install anywhere in this suite -- the demo-engine notice must show
    # now that there's a code to run (the section is gated on codes existing).
    assert any("demo engine" in c.value.lower() for c in at.info), \
        [c.value for c in at.info]

    next(b for b in at.button if b.key == "asf_run_button").click().run()
    assert not at.exception

    with Project.open(store) as proj:
        decisions = proj.list_coding_decisions()
        assert len(decisions) == 2   # one candidate code x two responses
        assert all(d.review_status == "unreviewed" or d.model_assigned is not None
                   for d in decisions)

    # Accept whatever the Review Queue is showing (may be zero if both landed
    # outside the ambiguous band on this run -- deterministic but not
    # meaningful with the demo engine, so don't assume which).
    accept_all = next((b for b in at.button if b.key == "asf_accept_all"), None)
    if accept_all is not None:
        accept_all.click().run()
        assert not at.exception


def test_alt_survey_flow_names_demo_codings_and_removes_them(tmp_path):
    """A project holding demo-engine codings says so on the page, and one click
    removes them without touching anything else (review finding F2)."""
    import pandas as pd
    from core.model import Code, Excerpt, Source
    from core.project import Project
    from engines.laya_engine import (CodingRunSpec, MockLayaEngine, demo_rater_ids,
                                     run_coding_pass, run_id_for)

    store = tmp_path / "run_asf" / "project.qnw"
    store.parent.mkdir(parents=True)
    with Project.create(store) as proj:
        proj.add_code(Code(code_id="", name="Financial stress"))
        proj.add_source(Source(source_id="s1", type="survey_response", raw_text="Rent is a lot."))
        proj.add_excerpt(Excerpt(excerpt_id="e1", source_id="s1", text="Rent is a lot.",
                                 char_start=0, char_end=14))
        run_coding_pass(proj, [("e1", "Rent is a lot.")], proj.get_codebook(), {},
                        MockLayaEngine().predict, run_id_for("r", "project", demo=True),
                        CodingRunSpec.from_dict({"low_threshold": 0.0, "high_threshold": 0.0001}))
        assert demo_rater_ids(proj)

    at = _app("survey")
    at.session_state["active_project_path"] = str(store)
    at.session_state["df"] = pd.DataFrame({"response_id": ["1"], "response_text": ["Rent is a lot."]})
    at.session_state["text_column"] = "response_text"
    at.session_state["id_column"] = "response_id"
    _nav(at).set_value("Alt Survey Flow").run()
    assert not at.exception
    assert any("demo engine" in w.value for w in at.warning), [w.value for w in at.warning]

    next(b for b in at.button if b.key == "asf_remove_demo").click().run()
    assert not at.exception
    with Project.open(store) as proj:
        assert not demo_rater_ids(proj)
        assert proj.coding_table().empty
        assert len(proj.get_codebook()) == 1, "codes are the analyst's, not the demo's"


def _alt_survey_with_a_run(tmp_path, n=8):
    import pandas as pd
    from core.project import Project

    store = tmp_path / "run_asf" / "project.qnw"
    store.parent.mkdir(parents=True)
    with Project.create(store):
        pass
    at = _app("survey")
    at.session_state["active_project_path"] = str(store)
    at.session_state["df"] = pd.DataFrame({
        "response_id": [str(i) for i in range(n)],
        "response_text": [f"Response number {i} about rent and books." for i in range(n)]})
    at.session_state["text_column"] = "response_text"
    at.session_state["id_column"] = "response_id"
    _nav(at).set_value("Alt Survey Flow").run()
    next(t for t in at.text_input if t.key == "asf_new_name").set_value("Cost").run()
    next(b for b in at.button if b.key == "asf_add_code").click().run()
    next(b for b in at.button if b.key == "asf_run_button").click().run()
    assert not at.exception
    return at, store


def test_calibration_saves_only_the_responses_marked_judged(tmp_path):
    """U4: a response left unticked must not be recorded as "no code" -- that
    would be finding F1 in reverse."""
    from analysis.calibration import load_sample
    from core.project import Project

    at, store = _alt_survey_with_a_run(tmp_path)
    next(n for n in at.number_input if n.key == "asf_cal_size").set_value(5).run()
    next(b for b in at.button if b.key == "asf_cal_draw").click().run()
    assert not at.exception
    run_id = at.session_state["asf_active_run_id"]
    with Project.open(store) as proj:
        sample = load_sample(proj, run_id)
    assert len(sample) == 5
    first, second = sample[0], sample[1]
    next(m for m in at.multiselect if m.key == f"asf_cal_codes_{first}").set_value(["Cost"])
    next(c for c in at.checkbox if c.key == f"asf_cal_done_{first}").check()
    next(m for m in at.multiselect if m.key == f"asf_cal_codes_{second}").set_value(["Cost"])
    next(b for b in at.button if b.label == "Save judged responses").click().run()
    assert not at.exception
    with Project.open(store) as proj:
        labels = proj.rater_labels("human_primary")
    assert labels.get(first) == {"Cost"}
    assert second not in labels, "an unticked response was saved as judged"


def test_an_applied_band_reaches_the_slider(tmp_path):
    at, _store = _alt_survey_with_a_run(tmp_path, n=4)
    at.session_state["asf_thresholds_pending"] = (0.4, 0.8)
    at.run()
    assert not at.exception
    assert tuple(next(s for s in at.slider if s.key == "asf_thresholds").value) == (0.4, 0.8)


def test_alt_survey_flow_creates_a_project_when_none_is_active(tmp_path, monkeypatch):
    """Alt Survey Flow must work standalone, without the exploratory pipeline
    having run first -- it mints its own project the first time it needs one."""
    import pandas as pd

    import app.alt_survey_flow as asf_module

    monkeypatch.setattr(asf_module, "STREAMLIT_OUTPUT_DIR", tmp_path)

    at = _app("survey")
    at.session_state["active_project_path"] = ""
    at.session_state["df"] = pd.DataFrame({
        "response_id": ["1"], "response_text": ["some response text"],
    })
    at.session_state["text_column"] = "response_text"
    at.session_state["id_column"] = "response_id"
    _nav(at).set_value("Alt Survey Flow").run()
    assert not at.exception

    created = list(tmp_path.glob("altflow_*/project.qnw"))
    assert len(created) == 1
    assert at.session_state["active_project_path"] == str(created[0].resolve())


def test_chart_builder_draws_from_the_project_and_offers_the_spec(tmp_path):
    """v4.6 Phase B1: shelves in, a real Vega-Lite chart out.

    Asserts on the spec rather than on pixels — the spec is what exports, what a
    methods appendix cites, and what the desktop build will read.
    """
    from core.model import Code, CodeApplication, Source
    from core.project import Project

    store = tmp_path / "run_chart" / "project.qnw"
    store.parent.mkdir(parents=True)
    # Two codes, not one: a category with a single value is deliberately not
    # suggested, because a bar chart of it is one bar.
    with Project.create(store) as proj:
        code_ids = [proj.add_code(Code(code_id="", name=name, definition=name))
                    for name in ("Cost", "Advising")]
        for n in range(4):
            src = Source(source_id=f"s{n}", type="survey_response",
                         raw_text=f"response {n}", label="Q1",
                         metadata={"response_id": f"r{n}", "question_text": "Q1"})
            proj.add_source(src)
            excerpt_id = proj.add_whole_response_excerpt(src)
            proj.apply_code(CodeApplication(
                application_id="", excerpt_id=excerpt_id, code_id=code_ids[n % 2],
                rater_id="human_primary"))

    at = _app("survey")
    at.session_state["active_project_path"] = str(store)
    _nav(at).set_value("Chart Builder").run()
    assert not at.exception

    # The first suggestion is "how often each code_name occurs" — one click.
    suggestion = next(b for b in at.button if b.key.startswith("chart_suggest_"))
    suggestion.click().run()
    assert not at.exception

    assert at.session_state["chart_mark"] in ("bar", "bar_horizontal")
    assert at.session_state["chart_shelf_y_agg"] == "count"
    # And it is over a real category, not an internal identifier.
    assert at.session_state["chart_shelf_x_field"] == "code_name"


def test_chart_builder_says_what_is_missing_instead_of_drawing_something_else(tmp_path):
    """An unfilled shelf must produce a sentence, not a substituted chart."""
    from core.model import Code, CodeApplication, Source
    from core.project import Project

    store = tmp_path / "run_chart2" / "project.qnw"
    store.parent.mkdir(parents=True)
    with Project.create(store) as proj:
        code_id = proj.add_code(Code(code_id="", name="Cost", definition="Money"))
        src = Source(source_id="s0", type="survey_response", raw_text="text",
                     label="Q1", metadata={"response_id": "r0", "question_text": "Q1"})
        proj.add_source(src)
        excerpt_id = proj.add_whole_response_excerpt(src)
        proj.apply_code(CodeApplication(application_id="", excerpt_id=excerpt_id,
                                        code_id=code_id, rater_id="human_primary"))

    at = _app("survey")
    at.session_state["active_project_path"] = str(store)
    _nav(at).set_value("Chart Builder").run()
    assert not at.exception

    next(s for s in at.selectbox if s.key == "chart_mark").set_value("pie").run()
    # Nothing on the Slices shelf yet.
    assert any("Slices" in w.value for w in at.warning), [w.value for w in at.warning]


def test_chart_builder_is_calm_about_an_empty_project(tmp_path):
    from core.project import Project

    store = tmp_path / "run_chart3" / "project.qnw"
    store.parent.mkdir(parents=True)
    Project.create(store).close()

    at = _app("survey")
    at.session_state["active_project_path"] = str(store)
    _nav(at).set_value("Chart Builder").run()
    assert not at.exception
    assert any("no codings" in i.value.lower() for i in at.info), [i.value for i in at.info]


def test_chart_builder_survives_swapping_a_number_for_a_category(tmp_path):
    """Choosing Mean and then choosing a text field is ordinary, not a crash.

    Every aggregate stays on offer whatever the field is, so the stored selection
    can never stop being one of the options. The impossible combination is caught
    by `chart_spec.problems()` and explained in a sentence instead.
    """
    from core.model import Code, CodeApplication, Source
    from core.project import Project

    store = tmp_path / "run_chart4" / "project.qnw"
    store.parent.mkdir(parents=True)
    with Project.create(store) as proj:
        code_id = proj.add_code(Code(code_id="", name="Cost", definition="Money"))
        src = Source(source_id="s0", type="survey_response", raw_text="text",
                     label="Q1", metadata={"response_id": "r0", "question_text": "Q1"})
        proj.add_source(src)
        excerpt_id = proj.add_whole_response_excerpt(src)
        proj.apply_code(CodeApplication(application_id="", excerpt_id=excerpt_id,
                                        code_id=code_id, rater_id="human_primary"))

    at = _app("survey")
    at.session_state["active_project_path"] = str(store)
    _nav(at).set_value("Chart Builder").run()
    assert not at.exception

    next(s for s in at.selectbox if s.key == "chart_shelf_y_field").set_value("weight").run()
    next(s for s in at.selectbox if s.key == "chart_shelf_y_agg").set_value("mean").run()
    assert not at.exception

    next(s for s in at.selectbox if s.key == "chart_shelf_y_field").set_value("code_name").run()
    assert not at.exception, f"swapping the field raised: {at.exception}"
    assert any("has no mean" in w.value for w in at.warning), [w.value for w in at.warning]


# ── the co-occurrence coder filter (PORTED_BACK.md §5) ───────────────────────

def _analysis_run(tmp_path, monkeypatch, raters):
    """A run directory the Analysis page will find, with one passage per rater.

    The page reads from the output tree, not the active project, so the tree is
    pointed at tmp_path. One excerpt carrying a different code from each rater is
    the shape that made the pooled matrix wrong.
    """
    from app.shared import projects as shared_projects
    from core.model import Code, CodeApplication, Source
    from core.project import Project

    monkeypatch.setattr(shared_projects, "STREAMLIT_OUTPUT_DIR", tmp_path)
    run_dir = tmp_path / "run_test"
    run_dir.mkdir(parents=True)

    with Project.create(run_dir / "project.qnw") as proj:
        src = Source(source_id="s1", type="survey_response", raw_text="a response",
                     label="Q1", metadata={"response_id": "r1", "question_text": "Q1"})
        proj.add_source(src)
        excerpt_id = proj.add_whole_response_excerpt(src)
        for index, rater in enumerate(raters):
            code_id = proj.add_code(Code(code_id="", name=f"Code{index}", definition="d"))
            proj.apply_code(CodeApplication(application_id="", excerpt_id=excerpt_id,
                                            code_id=code_id, rater_id=rater))
    return run_dir


def test_two_coders_span_coding_is_compared_on_sentences(tmp_path, monkeypatch):
    """A colleague's .qdpx coding and yours, compared on sentences of the
    documents both have finished -- ticked on the page (review finding F4)."""
    from app.shared import projects as shared_projects
    from core.model import Code, Rater, Source
    from core.project import Project
    from core.span_coding import apply_codes_to_span

    monkeypatch.setattr(shared_projects, "STREAMLIT_OUTPUT_DIR", tmp_path)
    store = tmp_path / "run_docs" / "project.qnw"
    store.parent.mkdir(parents=True)
    text = "Money is tight. I work a lot. Friends help me."
    with Project.create(store) as proj:
        proj.add_code(Code(code_id="", name="Cost"))
        proj.add_source(Source(source_id="d1", type="document", raw_text=text, label="Interview 1",
                               metadata={"title": "Interview 1"}))
        proj.add_rater(Rater(rater_id="imported_alex", kind="human", name="Alex"))
        apply_codes_to_span(proj, "d1", 0, 15, ["Cost"], rater_id="human_primary")
        apply_codes_to_span(proj, "d1", 6, 20, ["Cost"], rater_id="imported_alex")

    at = _app("survey")
    at.session_state["active_project_path"] = str(store)
    _nav(at).set_value("Analysis").run()
    next(r for r in at.radio if r.key == "irr_mode").set_value("Two coders on documents").run()
    assert not at.exception
    assert any("Tick at least one document" in i.value for i in at.info)

    next(c for c in at.checkbox if c.key == "span_done_d1").check().run()
    assert not at.exception
    assert any("on sentences" in c.value for c in at.caption), [c.value for c in at.caption]
    with Project.open(store) as proj:
        assert "d1" in proj.documents_coded_by("human_primary")
        assert "d1" in proj.documents_coded_by("imported_alex")


def test_code_by_descriptor_shows_prevalence_with_intervals(tmp_path, monkeypatch):
    """The Code x Descriptor tab gives each group's prevalence a 95% interval
    and compares two groups in a sentence (V7 Update 2, U1)."""
    from app.shared import projects as shared_projects
    from core.model import Code, CodeApplication, Descriptor, Rater, Source
    from core.project import Project

    monkeypatch.setattr(shared_projects, "STREAMLIT_OUTPUT_DIR", tmp_path)
    run_dir = tmp_path / "run_prev"
    run_dir.mkdir()
    with Project.create(run_dir / "project.qnw") as proj:
        proj.add_rater(Rater(rater_id="human_primary", kind="human"))
        cost = proj.add_code(Code(code_id="", name="Cost"))
        for i in range(40):
            src = Source(source_id=f"s{i}", type="survey_response", raw_text=f"text {i}")
            proj.add_source(src)
            excerpt = proj.add_whole_response_excerpt(src)
            proj.set_descriptor(Descriptor(source_id=src.source_id, key="Aid",
                                           value="Pell" if i < 20 else "Other"))
            if i < 12 or 20 <= i < 24:
                proj.apply_code(CodeApplication(application_id="", excerpt_id=excerpt,
                                                code_id=cost, coder="human",
                                                rater_id="human_primary"))
    at = _app("survey")
    _nav(at).set_value("Analysis").run()
    assert not at.exception
    assert "Wilson" in _caveats(at) or any("Wilson" in c.value for c in at.caption)
    next(s for s in at.selectbox if s.key == "prev_a").set_value("Pell").run()
    next(s for s in at.selectbox if s.key == "prev_b").set_value("Other").run()
    assert any("difference of +40.0 points" in m.value for m in at.markdown),         [m.value for m in at.markdown][-3:]


def test_the_audit_trail_builds_from_the_reports_page(tmp_path):
    """Results & Downloads builds the audit trail in both formats (U3). AppTest
    cannot see download buttons, so the built bytes are checked instead."""
    from core.model import Code
    from core.project import Project

    store = tmp_path / "run_audit" / "project.qnw"
    store.parent.mkdir(parents=True)
    with Project.create(store) as proj:
        code = proj.add_code(Code(code_id="", name="Cost"))
        proj.set_code_definition(code, "Worry about paying for college")
    at = _app("survey")
    at.session_state["active_project_path"] = str(store)
    _nav(at).set_value("Results & Downloads").run()
    assert not at.exception
    next(b for b in at.button if b.key == "rep_audit_btn").click().run()
    assert not at.exception
    assert at.session_state["rep_audit_docx"][:2] == b"PK"
    assert at.session_state["rep_audit_xlsx"][:2] == b"PK"


def test_cooccurrence_states_that_it_is_pooling_two_coders(tmp_path, monkeypatch):
    """A pair neither coder asserted must not read as a finding.

    The passage carries Code0 from a human and Code1 from the model. The pooled
    matrix reports them as co-occurring, which neither claimed — and the number
    moves when the model is re-run, though no human changed their mind. The
    default still pools, so the two front ends agree, but it now says so.
    """
    _analysis_run(tmp_path, monkeypatch, ["human_primary", "transformer"])

    at = _app("survey")
    _nav(at).set_value("Analysis").run()
    assert not at.exception

    assert any("2 coders contributed" in w.value for w in at.warning),         [w.value for w in at.warning]


def test_cooccurrence_can_be_narrowed_to_one_coder(tmp_path, monkeypatch):
    """And the caveat goes away once the finding is attributable."""
    _analysis_run(tmp_path, monkeypatch, ["human_primary", "transformer"])

    at = _app("survey")
    _nav(at).set_value("Analysis").run()
    next(s for s in at.selectbox if s.key == "cooc_rater").set_value("human_primary").run()
    assert not at.exception

    assert not any("coders contributed" in w.value for w in at.warning),         [w.value for w in at.warning]


def test_a_single_coder_project_is_not_asked_to_choose(tmp_path, monkeypatch):
    """No widget and no banner — there is nothing to disambiguate."""
    _analysis_run(tmp_path, monkeypatch, ["human_primary"])

    at = _app("survey")
    _nav(at).set_value("Analysis").run()
    assert not at.exception
    assert not any(s.key == "cooc_rater" for s in at.selectbox)
    assert not any("coders contributed" in w.value for w in at.warning)


def test_saturation_tab_plots_discovery_and_states_its_caveats(tmp_path, monkeypatch):
    """v4.6 §B5: the curve is easy, the caveats are the feature.

    A saturation figure gets quoted in a Methods section and then travels without
    whatever sat below it, so the page must show the cautions, and must never
    print a verdict.
    """
    _analysis_run(tmp_path, monkeypatch, ["human_primary"])

    at = _app("survey")
    _nav(at).set_value("Analysis").run()
    _more(at, "Saturation")
    assert not at.exception

    warnings = _caveats(at)
    assert "not meaning saturation" in warnings, warnings
    assert "not necessarily the order the data was collected" in warnings

    body = " ".join(str(m.value) for m in at.markdown) + warnings
    assert "saturation was reached" not in body.lower()


def test_saturation_drops_the_order_caveat_when_the_order_is_real(tmp_path, monkeypatch):
    _analysis_run(tmp_path, monkeypatch, ["human_primary"])

    at = _app("survey")
    _nav(at).set_value("Analysis").run()
    _more(at, "Saturation")
    next(c for c in at.checkbox if c.key == "sat_order").set_value(True).run()
    assert not at.exception

    warnings = _caveats(at)
    assert "not necessarily the order the data was collected" not in warnings
    assert "not meaning saturation" in warnings, "this one never goes away"


def test_saturation_is_calm_when_only_a_machine_has_coded(tmp_path, monkeypatch):
    """Human-only is the default, so a machine-coded project has nothing to plot
    rather than a curve that flatters itself."""
    _analysis_run(tmp_path, monkeypatch, ["transformer"])

    at = _app("survey")
    _nav(at).set_value("Analysis").run()
    _more(at, "Saturation")
    assert not at.exception
    assert any("no discovery to plot" in i.value for i in at.info), \
        [i.value for i in at.info]


def test_a_chart_can_be_saved_and_reopened(tmp_path):
    """v4.6 §B1c: the definition travels with the project, so it can be re-run.

    The PNG and CSV export a moment; this exports the method.
    """
    from core.model import Code, CodeApplication, Source
    from core.project import Project

    store = tmp_path / "run_save" / "project.qnw"
    store.parent.mkdir(parents=True)
    with Project.create(store) as proj:
        code_ids = [proj.add_code(Code(code_id="", name=n, definition=n))
                    for n in ("Cost", "Advising")]
        for n in range(4):
            src = Source(source_id=f"s{n}", type="survey_response",
                         raw_text=f"response {n}", label="Q1",
                         metadata={"response_id": f"r{n}", "question_text": "Q1"})
            proj.add_source(src)
            excerpt_id = proj.add_whole_response_excerpt(src)
            proj.apply_code(CodeApplication(
                application_id="", excerpt_id=excerpt_id, code_id=code_ids[n % 2],
                rater_id="human_primary"))

    at = _app("survey")
    at.session_state["active_project_path"] = str(store)
    _nav(at).set_value("Chart Builder").run()
    assert not at.exception

    next(s for s in at.selectbox if s.key == "chart_shelf_x_field").set_value("code_name").run()
    next(s for s in at.selectbox if s.key == "chart_shelf_y_agg").set_value("count").run()
    next(t for t in at.text_input if t.key == "chart_save_name").set_value("Frequency").run()
    next(b for b in at.button if b.key == "chart_save_btn").click().run()
    assert not at.exception

    with Project.open(store) as proj:
        saved = proj.list_charts()
    assert [c.name for c in saved] == ["Frequency"]
    assert saved[0].spec["shelves"]["x"]["field"] == "code_name"

    # And it is offered back on the next render.
    at = _app("survey")
    at.session_state["active_project_path"] = str(store)
    _nav(at).set_value("Chart Builder").run()
    assert any(b.key.startswith("chart_open_") for b in at.button)


def test_the_codebook_page_offers_refi_qda_both_ways():
    """v4.6 §B7: the codebook can leave for, and arrive from, another package.

    Asserted on the wiring rather than on the widgets: `AppTest` does not expose
    `st.download_button`, so a render test cannot see the export at all. The
    format itself is covered in `test_refi_qda.py`; what can silently break here
    is the page forgetting to offer it.
    """
    import inspect

    from app import codebook as codebook_page

    source = inspect.getsource(codebook_page)
    assert "export_codebook_qdc" in source, "no REFI-QDA export offered"
    assert "import_codebook_qdc" in source, "no REFI-QDA import offered"
    assert '"qdc"' in source, "the uploader does not accept .qdc"
    # Chosen by extension, not by sniffing bytes -- a wrong guess silently
    # imports nothing.
    assert ".qdc" in source and "suffix" in source


def test_a_refi_qda_codebook_imports_additively(tmp_path):
    from core.model import Code
    from core.project import Project
    from core.refi_qda import import_codebook_qdc

    store = tmp_path / "p.qnw"
    with Project.create(store) as proj:
        proj.add_code(Code(code_id="", name="Mine", definition="My definition"))

    incoming = """<?xml version="1.0" encoding="utf-8"?>
    <CodeBook origin="NVivo">
      <Codes>
        <Code guid="1" name="Mine"><Description>Theirs</Description></Code>
        <Code guid="2" name="Theirs">
          <Code guid="3" name="Nested"/>
        </Code>
      </Codes>
    </CodeBook>"""

    with Project.open(store) as proj:
        report = import_codebook_qdc(proj, incoming)
        codes = {c.name: c for c in proj.get_codebook()}

    assert report["skipped_existing"] == ["Mine"]
    assert codes["Mine"].definition == "My definition", "never overwritten"
    assert codes["Nested"].parent_id == codes["Theirs"].code_id


def test_data_management_offers_qdpx_import(tmp_path):
    """v4.6 §B7: the adoption path is reachable, and it says whose codings these are.

    Asserted on the wiring and the wording — `AppTest` cannot drive a file
    uploader, and the import itself is covered end to end in `test_qdpx.py`.
    What can silently break here is the page forgetting to offer it, or
    forgetting to say that imported codings stay someone else's.
    """
    import inspect

    from app import data_management

    source = inspect.getsource(data_management)
    assert "import_qdpx" in source, "no REFI-QDA project import offered"
    assert '"qdpx"' in source, "the uploader does not accept .qdpx"
    assert "stay someone else" in source, (
        "the page must say imported codings are not the analyst's own — "
        "kappa between two coders is only meaningful if they stay two coders")


def test_data_management_offers_qdpx_export_and_says_what_is_in_it():
    """v4.6 §B7: the exit promise, and the one export that cannot be redacted.

    Wiring and wording, for the same reason as the import test — `AppTest` does
    not expose `st.download_button`. What can silently break is the page
    offering the file without saying it carries every word of every source.
    """
    import inspect

    from app import data_management

    source = inspect.getsource(data_management)
    assert "export_qdpx" in source, "no REFI-QDA project export offered"
    assert "full text of every source" in source, (
        "a .qdpx carries the whole corpus and cannot be redacted; the page has "
        "to say so, because every other export here states what it contains")


def test_the_deviant_cases_tab_refuses_a_thinly_coded_code(tmp_path, monkeypatch):
    """v4.6 §B6: below a handful of applications the centre of a code sits close
    to every response, so the page says so rather than ranking noise.

    The refusal path needs no model, which is why it is the one asserted here.
    """
    _analysis_run(tmp_path, monkeypatch, ["human_primary"])

    at = _app("survey")
    _nav(at).set_value("Analysis").run()
    _more(at, "Deviant cases")
    assert not at.exception

    messages = " ".join(i.value for i in at.info)
    assert "sits close to every" in messages, messages


def test_the_deviant_cases_page_never_calls_anything_deviant(tmp_path, monkeypatch):
    """It proposes cases to re-read. Distance from a centroid is a property of
    the embedding, not a verdict about a respondent."""
    _analysis_run(tmp_path, monkeypatch, ["human_primary"])

    at = _app("survey")
    _nav(at).set_value("Analysis").run()
    _more(at, "Deviant cases")

    shown = " ".join(
        [str(c.value) for c in at.caption] + [str(i.value) for i in at.info]
        + [str(w.value) for w in at.warning]).lower()
    assert "is deviant" not in shown
    assert "outlier respondent" not in shown
