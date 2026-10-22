"""Surveys, step 1 (Load) on the web: few controls, one main button, plain words (item 4b.5a)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from core.ux import words
from tests import webkit

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "data" / "sample_survey_education.csv"


def _loaded(confirmed: bool = False, mode: str = "survey"):
    at = webkit.start(mode)
    at.session_state["df"] = pd.read_csv(SAMPLE)
    at.session_state["input_source"] = "synthetic_sample"
    webkit.go(at, "Data Setup")
    if confirmed:
        next(c for c in at.checkbox if "confirm this file" in c.label).set_value(True).run()
        assert not at.exception, at.exception
    return at


def test_an_empty_load_step_offers_a_file_and_the_sample_and_folds_the_rest():
    at = webkit.start("survey")
    webkit.go(at, "Data Setup")
    shown = webkit.describe(webkit.visible_controls(at))
    assert shown == ["file_uploader:Open a spreadsheet", "button:ds_sample"], shown
    assert len(webkit.all_controls(at)) > len(webkit.visible_controls(at))
    assert any("Other ways to open data" in e.label for e in at.expander)
    assert webkit.primary_buttons(at) == []


def test_the_sample_button_loads_the_sample_and_its_themes():
    """Found in phase 4b: this button could not work for several releases (a wrong folder constant)."""
    at = webkit.start("survey")
    webkit.go(at, "Data Setup")
    next(b for b in at.button if b.key == "ds_sample").click().run()
    assert not at.exception, at.exception
    assert len(at.session_state["df"]) == 40 and at.session_state["input_source"] == "synthetic_sample"
    assert "Cost" in at.session_state["theme_labels_text"] or at.session_state["theme_labels_text"].strip()


def test_after_loading_the_privacy_check_comes_before_anything_else():
    at = _loaded(confirmed=False)
    shown = webkit.describe(webkit.visible_controls(at))
    assert len(shown) <= webkit.MAX_VISIBLE_CONTROLS, shown
    assert "Where are the answers?" not in " ".join(s.value for s in at.subheader)
    assert webkit.primary_buttons(at) == []


def test_once_confirmed_the_step_has_at_most_seven_controls_and_one_main_button():
    at = _loaded(confirmed=True)
    visible = webkit.visible_controls(at)
    assert len(visible) <= webkit.MAX_VISIBLE_CONTROLS, webkit.describe(visible)
    main = webkit.primary_buttons(at)
    assert len(main) <= 1
    assert "Where are the answers?" in " ".join(s.value for s in at.subheader)
    labels = " ".join(getattr(c, "label", "") for c in visible)
    assert "Answers are in column" in labels


def test_the_layout_question_column_and_details_are_under_more_options():
    at = _loaded(confirmed=True)
    outside = " ".join(getattr(c, "label", "") for c in webkit.visible_controls(at))
    for folded in ("How is the file organised?", "Question column", "Respondent ID column",
                   "Respondent details to keep"):
        assert folded not in outside
    inside = " ".join(getattr(c, "label", "") for c in webkit.all_controls(at))
    for folded in ("How is the file organised?", "Question column", "Respondent ID column",
                   "Respondent details to keep"):
        assert folded in inside


def test_a_suggestion_is_shown_and_not_applied_until_the_person_presses_the_button():
    at = webkit.start("survey")
    frame = pd.DataFrame({
        "respondent_id": [f"r{i}" for i in range(12)],
        "question": ["What was hardest about this term for you?"] * 12,
        "answer": [f"I found number {i} hard because of the cost and the long hours at work" for i in range(12)],
        "year": ["1", "2"] * 6,
    })
    at.session_state["df"] = frame
    at.session_state["input_source"] = "upload:s.csv"
    webkit.go(at, "Data Setup")
    next(c for c in at.checkbox if "confirm this file" in c.label).set_value(True).run()
    assert any("QualSafe thinks" in i.value and "answer" in i.value for i in at.info)
    assert at.session_state["text_column"] == ""                       # not chosen for them
    next(b for b in at.button if b.key == "ds_use_suggestion").click().run()
    assert not at.exception, at.exception
    assert at.session_state["text_column"] == "answer" and at.session_state["question_column"] == "question"
    assert at.session_state["id_column"] == "respondent_id"
    assert not any(b.key == "ds_use_suggestion" for b in at.button)    # used: not offered again


def test_choosing_the_answers_column_enables_the_main_button_and_goes_to_themes():
    at = _loaded(confirmed=True)
    column = next(s for s in at.selectbox if s.key == "map_text_col")
    column.set_value("response_text").run()
    assert not at.exception, at.exception
    main = next(b for b in at.button if b.key == "next_theme_setup")
    assert main.proto.type == "primary"
    main.click().run()
    assert at.session_state["step_surveys"] == "themes"


def test_the_words_on_this_screen_are_plain():
    text = (ROOT / "app" / "data_setup.py").read_text(encoding="utf-8")
    for string in words.ui_strings(text):
        assert words.find_never(string) == [], string
        assert words.find_replace(string) == [], string
