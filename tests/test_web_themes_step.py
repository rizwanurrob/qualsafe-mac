"""Surveys, step 2 (Themes) on the web: a list, a ready-made set, one main button (item 4b.5b)."""

from __future__ import annotations

from pathlib import Path

from core.ux import words
from tests import webkit

ROOT = Path(__file__).resolve().parents[1]


def _themes(text: str = ""):
    at = webkit.start("survey")
    if text:
        at.session_state["theme_labels_text"] = text
    return webkit.go(at, "Theme Setup")


def test_with_no_themes_the_step_shows_the_set_the_list_and_a_quiet_next():
    at = _themes()
    shown = webkit.describe(webkit.visible_controls(at))
    assert len(shown) <= webkit.MAX_VISIBLE_CONTROLS
    assert any("Start from a ready-made set" in s or "theme_pack_choice" in s for s in shown)
    assert webkit.primary_buttons(at) == []
    assert any("No themes yet" in c.value for c in at.caption)


def test_with_themes_there_is_one_main_button_and_it_goes_to_the_next_step():
    at = _themes("Money worries\nBelonging\nSupport")
    assert len(webkit.visible_controls(at)) <= webkit.MAX_VISIBLE_CONTROLS
    main = webkit.primary_buttons(at)
    assert [b.key for b in main] == ["next_run_analysis"]
    assert any("3 themes" in c.value for c in at.caption)
    main[0].click().run()
    assert not at.exception, at.exception
    assert at.session_state["step_surveys"] == "code"


def test_a_ready_made_set_fills_the_list_and_the_list_stays_editable():
    at = _themes()
    next(b for b in at.button if b.key == "theme_use_pack").click().run()
    assert not at.exception, at.exception
    filled = at.session_state["theme_labels_text"]
    assert len(filled.splitlines()) >= 3
    area = next(t for t in at.text_area if t.label.startswith("Your themes"))
    area.set_value(filled + "\nA theme of my own").run()
    assert at.session_state["theme_labels_text"].endswith("A theme of my own")


def test_saving_a_set_how_sure_and_the_rest_are_folded_away():
    at = _themes("Money worries")
    outside = " ".join(getattr(c, "label", "") for c in webkit.visible_controls(at))
    inside = " ".join(getattr(c, "label", "") for c in webkit.all_controls(at))
    for folded in ("Name for this set", "Mark unsure answers for review", "The best theme must score at least",
                   "Fewest groups to try", "Themes for particular questions (optional)"):
        assert folded not in outside and folded in inside, folded


def test_the_settings_the_run_reads_keep_their_values_and_names():
    at = _themes("Money worries")
    state = at.session_state
    assert state["use_strict_global"] is False and abs(state["strict_top1_global"] - 0.55) < 1e-9
    assert state["use_strict_question"] is True and state["adv_min_k"] == 3 and state["adv_max_k"] == 8
    assert state["adv_embedding_model"].endswith("all-MiniLM-L6-v2")
    next(s for s in at.slider if s.label == "Most groups to try").set_value(10).run()
    assert at.session_state["adv_max_k"] == 10                      # kept, not reset on the next render


def test_the_words_on_this_screen_are_plain():
    text = (ROOT / "app" / "theme_setup.py").read_text(encoding="utf-8")
    for string in words.ui_strings(text):
        assert words.find_never(string) == [], string
        assert words.find_replace(string) == [], string
