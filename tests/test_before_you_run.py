"""The "Before you run" card (book-audit F4): said where the button is, shown until dismissed, remembered."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from core.app_settings import PERSISTED_KEYS, load_app_settings
from core.ux import before_you_run
from tests import webkit

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "data" / "sample_survey_education.csv"


@pytest.fixture(autouse=True)
def _own_settings_folder(monkeypatch, tmp_path):
    monkeypatch.setenv("QNW_SETTINGS_DIR", str(tmp_path / "settings"))
    from core import engine_install

    monkeypatch.setattr(engine_install, "installed", lambda: True)


def test_the_text_tells_the_reader_to_read_first_and_not_to_count_unreviewed_suggestions():
    text = " ".join(before_you_run.LINES).lower()
    assert "read some of the answers first" in text and "not report a count" in text
    assert "—" not in text and "–" not in text


def test_the_flag_is_a_persisted_preference_and_only_a_flag():
    assert before_you_run.KEY in PERSISTED_KEYS
    assert before_you_run.is_hidden("1") and before_you_run.is_hidden("true")
    assert not before_you_run.is_hidden("") and not before_you_run.is_hidden(None)


def _web_run_step():
    at = webkit.start("survey")
    at.session_state["df"] = pd.read_csv(SAMPLE)
    at.session_state["input_source"] = "synthetic_sample"
    at.session_state["text_column"] = "response_text"
    at.session_state["theme_labels_text"] = "Cost\nBelonging"
    return webkit.go(at, "Run Analysis")


def _card_shown(at) -> bool:
    return any(before_you_run.TITLE in str(m.value) for m in at.markdown)


def test_the_web_run_step_shows_the_card_with_no_button_of_its_own():
    at = _web_run_step()
    assert _card_shown(at)
    assert not any("do not show" in (b.label or "").lower() for b in at.button)


def test_pressing_the_run_buttons_dismisses_it_and_that_is_remembered(monkeypatch):
    from app import run_analysis

    monkeypatch.setattr(run_analysis, "_run_pipeline_ui", lambda df, preview: None)
    at = _web_run_step()
    next(b for b in at.button if b.key == "run_preview").click().run()
    assert at.session_state[before_you_run.KEY] == "1"
    at.run()                                   # the card was drawn before the button was read; the next draw has none
    assert not _card_shown(at)
    assert load_app_settings().get(before_you_run.KEY) == "1"


def test_the_web_card_stays_away_once_dismissed():
    at = webkit.start("survey")
    at.session_state[before_you_run.KEY] = "1"
    at.session_state["df"] = pd.read_csv(SAMPLE)
    at.session_state["input_source"] = "synthetic_sample"
    at.session_state["text_column"] = "response_text"
    at.session_state["theme_labels_text"] = "Cost\nBelonging"
    at = webkit.go(at, "Run Analysis")
    assert not _card_shown(at)
