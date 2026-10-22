"""Surveys, step 3 (Code) on the web: three ways to code, one main button (item 4b.5c)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from core.ux import coding_choices, words
from tests import webkit

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "data" / "sample_survey_education.csv"


def _code_step(loaded: bool = True, page: str = "Run Analysis"):
    at = webkit.start("survey")
    if loaded:
        at.session_state["df"] = pd.read_csv(SAMPLE)
        at.session_state["input_source"] = "synthetic_sample"
        at.session_state["text_column"] = "response_text"
        at.session_state["theme_labels_text"] = "Cost\nBelonging"
    return webkit.go(at, page)


def test_the_step_offers_the_same_three_ways_in_the_same_words_as_the_desktop():
    at = _code_step()
    choice = next(r for r in at.radio if r.key == "code_choice")
    assert list(choice.options) == ["suggest", "codebook", "hand"] or \
        list(choice.options) == [coding_choices.title(k) for k in coding_choices.KEYS]
    shown = " ".join(str(c) for c in at.main.children.values())
    for _key, title, when in coding_choices.CHOICES:
        assert title in shown or title in " ".join(map(str, choice.options))
    assert at.session_state["code_choice"] == "suggest"


def test_suggesting_codes_shows_few_controls_and_one_main_button():
    at = _code_step()
    visible = webkit.visible_controls(at)
    assert len(visible) <= webkit.MAX_VISIBLE_CONTROLS, webkit.describe(visible)
    assert [b.key for b in webkit.primary_buttons(at)] == ["run_full"]
    keys = [getattr(c, "key", None) for c in visible]
    assert "run_preview" in keys and "run_engine" in keys


def test_the_language_model_settings_thresholds_and_inclusions_are_folded():
    at = _code_step()
    outside = " ".join(getattr(c, "label", "") for c in webkit.visible_controls(at))
    inside = " ".join(getattr(c, "label", "") for c in webkit.all_controls(at))
    for folded in ("The best theme must score at least", "Suggest a code for every answer",
                   "Also mark each answer positive or negative", "Also save a project file (.qnw)"):
        assert folded not in outside and folded in inside, folded


def test_the_keys_the_run_reads_are_set_and_keep_their_defaults():
    at = _code_step()
    state = at.session_state
    assert state["engine_type"] == "transformer"
    assert state["use_sentiment"] is True and state["use_zero_shot"] is True
    assert state["use_question_theme"] is True and state["use_question_zero_shot"] is False
    assert state["save_project_store"] is True


def test_choosing_the_language_model_shows_its_settings_in_the_fold():
    at = _code_step()
    next(r for r in at.radio if r.key == "run_engine").set_value("llm").run()
    assert not at.exception, at.exception
    assert at.session_state["engine_type"] == "llm"
    inside = " ".join(getattr(c, "label", "") for c in webkit.all_controls(at))
    assert "Model name" in inside and "How much it varies" in inside


def test_the_quick_preview_and_the_run_button_start_a_run(monkeypatch):
    calls = []
    from app import run_analysis

    monkeypatch.setattr(run_analysis, "_run_pipeline_ui", lambda df, preview: calls.append(preview))
    at = _code_step()
    next(b for b in at.button if b.key == "run_preview").click().run()
    next(b for b in at.button if b.key == "run_full").click().run()
    assert calls == [True, False]


def test_the_other_two_ways_open_their_own_screens_and_stay_chosen():
    at = _code_step()
    choice = next(r for r in at.radio if r.key == "code_choice")
    choice.set_value("codebook").run()
    assert not at.exception, at.exception
    assert at.session_state["code_choice"] == "codebook"
    assert any("written" in str(e.value).lower() or "codebook" in str(e.value).lower()
               for e in list(at.subheader) + list(at.header) + list(at.markdown))
    next(r for r in at.radio if r.key == "code_choice").set_value("hand").run()
    assert not at.exception, at.exception
    assert at.session_state["code_choice"] == "hand"


def test_a_page_name_from_a_button_picks_the_way_to_code():
    at = _code_step(page="Alt Survey Flow")
    assert at.session_state["code_choice"] == "codebook" and at.session_state["step_surveys"] == "code"
    webkit.go(at, "Iterative Labeling Lab")
    assert at.session_state["code_choice"] == "hand"
    webkit.go(at, "Run Analysis")
    assert at.session_state["code_choice"] == "suggest"


def test_without_answers_loaded_it_says_so_and_points_back():
    at = _code_step(loaded=False)
    assert any("Load your answers first" in w.value for w in at.warning)
    assert any(b.key == "run_goto_data" for b in at.button)
    assert webkit.primary_buttons(at) == []


def test_the_chosen_way_is_remembered_with_the_place():
    from app.shared import progress_state

    at = _code_step(page="Alt Survey Flow")
    saved = __import__("core.ux.progress", fromlist=["load"]).load("surveys")
    assert saved["step"] == "code" and saved["state"]["code_choice"] == "codebook"


def test_the_words_on_this_screen_are_plain():
    for name in ("app/run_analysis.py", "core/ux/coding_choices.py"):
        text = (ROOT / name).read_text(encoding="utf-8")
        for string in words.ui_strings(text):
            assert words.find_never(string) == [], (name, string)
            assert words.find_replace(string) == [], (name, string)


def test_without_the_analysis_engine_the_step_says_so_and_offers_models_instead_of_a_run(monkeypatch):
    from core import engine_install

    monkeypatch.setattr(engine_install, "installed", lambda: False)
    at = _code_step()
    assert not at.exception, at.exception
    assert any("analysis engine" in i.value and "Install the analysis engine" in i.value for i in at.info)
    keys = [b.key for b in at.button]
    assert "run_goto_models" in keys and "run_full" not in keys and "run_preview" not in keys
    next(b for b in at.button if b.key == "run_goto_models").click().run()
    assert at.session_state["view"] == "settings" and at.session_state["settings_tab"] == "Models"
