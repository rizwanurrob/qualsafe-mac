"""The web app saves and restores your place per activity (phase 4b, item 4b.4)."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pandas as pd
import pytest

from app.shared import nav, progress_state
from core.ux import progress

ROOT = Path(__file__).resolve().parents[1]
APP_PATH = ROOT / "streamlit_app.py"
SAMPLE = ROOT / "data" / "sample_survey_education.csv"


class State(dict):
    pass


@pytest.fixture(autouse=True)
def _own_settings_folder(monkeypatch, tmp_path):
    monkeypatch.setenv("QNW_SETTINGS_DIR", str(tmp_path / "settings"))


@pytest.fixture
def state(monkeypatch):
    fake = State()
    monkeypatch.setattr(nav.st, "session_state", fake)
    nav.init_nav()
    return fake


def _load_sample(state):
    state["df"] = pd.read_csv(SAMPLE)
    state["input_source"] = "synthetic_sample"
    state["text_column"] = "response_text"
    state["theme_labels_text"] = "Cost\nBelonging"
    state["pii_confirmed"] = True


# -- what is saved ------------------------------------------------------------------------------

def test_surveys_saves_the_file_the_columns_and_the_themes_but_not_the_privacy_confirmation(state):
    _load_sample(state)
    nav.go_activity("surveys", "code")
    progress_state.maybe_persist_progress()
    entry = progress.load("surveys")
    assert entry["step"] == "code"
    saved = entry["state"]
    assert saved["resume_path"].endswith("sample_survey_education.csv")
    assert saved["text_column"] == "response_text" and saved["theme_labels_text"] == "Cost\nBelonging"
    blob = json.dumps(saved)
    assert "pii_confirmed" not in blob and "confirmed" not in blob


def test_no_response_text_is_ever_saved(state):
    _load_sample(state)
    nav.go_activity("surveys", "explore")
    progress_state.maybe_persist_progress()
    raw = progress.progress_path().read_text(encoding="utf-8")
    sample = pd.read_csv(SAMPLE)["response_text"].dropna().astype(str)
    for answer in sample.head(10):
        assert answer[:40] not in raw


def test_nothing_is_saved_while_you_are_on_home_or_in_settings(state):
    progress_state.maybe_persist_progress()
    nav.go_settings()
    progress_state.maybe_persist_progress()
    assert not progress.progress_path().exists()


def test_it_saves_again_only_when_something_changed(state, monkeypatch):
    _load_sample(state)
    nav.go_activity("surveys", "load")
    calls = []
    real = progress.save
    monkeypatch.setattr(progress, "save", lambda *a, **k: calls.append(a) or real(*a, **k))
    progress_state.maybe_persist_progress()
    progress_state.maybe_persist_progress()
    assert len(calls) == 1
    nav.go_activity("surveys", "themes")
    progress_state.maybe_persist_progress()
    assert len(calls) == 2


def test_each_activity_keeps_its_own_place(state):
    _load_sample(state)
    nav.go_activity("surveys", "code")
    progress_state.maybe_persist_progress()
    nav.go_activity("interviews", "codebook")
    progress_state.maybe_persist_progress()
    assert progress.load("surveys")["step"] == "code" and progress.load("interviews")["step"] == "codebook"


def test_the_explore_screen_is_remembered(state):
    _load_sample(state)
    nav.go_activity("surveys", "explore", screen="Search")
    progress_state.maybe_persist_progress()
    assert progress.load("surveys")["state"]["explore_tab"] == "Search"


def test_a_project_is_remembered_only_while_its_file_exists(state, tmp_path):
    project = tmp_path / "p.qnw"
    state["active_project_path"] = str(project)
    nav.go_activity("interviews", "add")
    assert "project_path" not in progress_state.collect("interviews")
    project.write_bytes(b"x")
    assert progress_state.collect("interviews")["project_path"] == str(project)


def test_a_broken_progress_file_never_stops_the_page(state, monkeypatch):
    nav.go_activity("surveys", "load")
    monkeypatch.setattr(progress, "save", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    progress_state.maybe_persist_progress()                     # must not raise


# -- Continue ---------------------------------------------------------------------------------

def test_continue_puts_back_the_file_the_step_and_the_screen(state):
    _load_sample(state)
    nav.go_activity("surveys", "explore", screen="Search")
    progress_state.maybe_persist_progress()
    state.clear()                                        # a new session
    nav.init_nav()
    progress_state.continue_activity("surveys")
    assert nav.current_activity() == "surveys" and nav.step_of("surveys") == "explore"
    assert nav.current_screen("surveys", "explore") == "Search"
    assert isinstance(state["df"], pd.DataFrame) and len(state["df"]) == 40
    assert state["text_column"] == "response_text" and state["theme_labels_text"] == "Cost\nBelonging"
    assert not state.get("pii_confirmed"), "the privacy check is asked again on every load"
    assert state["input_source"].startswith("resume:")


def test_continue_with_a_moved_file_still_opens_the_saved_step(state, tmp_path):
    copy = tmp_path / "mine.csv"
    copy.write_text(SAMPLE.read_text(encoding="utf-8"), encoding="utf-8")
    state["df"] = pd.read_csv(copy)
    state["input_source"] = f"folder:{copy}"
    nav.go_activity("surveys", "themes")
    progress_state.maybe_persist_progress()
    copy.unlink()
    state.clear()
    nav.init_nav()
    summary = progress.summary("surveys")
    assert summary.missing and summary.name == "mine.csv"
    progress_state.continue_activity("surveys")
    assert nav.step_of("surveys") == "themes" and state.get("df") is None


def test_continue_with_nothing_saved_just_opens_the_activity(state):
    progress_state.continue_activity("charts")
    assert nav.current_activity() == "charts" and nav.step_of("charts") == "open"


def test_start_over_forgets_one_activity_and_leaves_the_others(state):
    _load_sample(state)
    nav.go_activity("surveys", "code")
    progress_state.maybe_persist_progress()
    nav.go_activity("interviews", "codebook")
    progress_state.maybe_persist_progress()
    progress_state.start_over("surveys")
    assert progress.load("surveys") is None and progress.load("interviews") is not None
    assert nav.step_of("surveys") == "load"


def test_home_offers_continue_only_where_there_is_something_to_continue(state):
    assert progress_state.summaries() == {}
    _load_sample(state)
    nav.go_activity("surveys", "code")
    progress_state.maybe_persist_progress()
    found = progress_state.summaries()
    assert list(found) == ["surveys"]
    assert found["surveys"].detail.startswith("Step 3 of 5 · Code") and found["surveys"].name == "sample_survey_education.csv"


def test_the_old_resume_file_moves_into_the_new_store_once(state, tmp_path):
    settings = Path(os.environ["QNW_SETTINGS_DIR"])
    settings.mkdir(parents=True)
    old = settings / "workspace.json"
    old.write_text(json.dumps({"resume_path": str(SAMPLE), "text_column": "response_text",
                               "theme_labels_text": "Cost"}), encoding="utf-8")
    progress_state.migrate_once()
    assert not old.exists() and (settings / "workspace.json.bak").exists()
    entry = progress.load("surveys")
    assert entry["state"]["resume_path"] == str(SAMPLE) and entry["step"] == "load"
    progress_state.migrate_once()                         # once per session: nothing more happens


# -- in the real app --------------------------------------------------------------------------

def _app():
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(APP_PATH), default_timeout=180)
    at.run()
    assert not at.exception, at.exception
    return at


def test_home_then_the_sample_then_back_to_home_says_where_you_were_and_continues():
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["QNW_SETTINGS_DIR"] = tmp
        at = _app()
        next(b for b in at.button if b.key == "home_walkthrough").click().run()
        assert not at.exception and nav_state(at) == ("activity", "surveys")
        at.session_state["nav_target"] = "Run Analysis"
        at.run()
        assert at.session_state["step_surveys"] == "code"
        next(b for b in at.button if b.key == "nav_home").click().run()
        assert not at.exception and at.session_state["view"] == "home"
        captions = " ".join(c.value for c in at.caption)
        assert "Continue: sample_survey_education.csv" in captions and "Step 3 of 5 · Code" in captions
        next(b for b in at.button if b.key == "continue_surveys").click().run()
        assert not at.exception
        assert at.session_state["view"] == "activity" and at.session_state["step_surveys"] == "code"
        assert not at.session_state["pii_confirmed"]
        next(b for b in at.button if b.key == "nav_home").click().run()
        next(b for b in at.button if b.key == "startover_surveys").click().run()
        assert not at.exception and not any(b.key == "continue_surveys" for b in at.button)


def nav_state(at):
    return at.session_state["view"], at.session_state["activity"]
