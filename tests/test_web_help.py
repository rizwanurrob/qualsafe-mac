"""Help on the web: the shared articles, tips, tour and clips (item 4b.6)."""

from __future__ import annotations

import os

from app.shared import help_ui
from core.ux import activities
from core.ux import help as shared_help
from core.ux.help import media, tours
from tests import webkit


def _help(article: str = ""):
    at = webkit.start("")
    at.session_state["view"] = "help"
    if article:
        at.session_state["help_article"] = article
    at.run()
    assert not at.exception, at.exception
    return at


def test_help_lists_every_step_task_the_glossary_and_troubleshooting():
    at = _help()
    pick = next(s for s in at.selectbox if s.key == "help_pick")
    options = list(pick.options)
    assert len(options) == len(shared_help.steps()) + len(shared_help.task_ids()) + 2
    assert "When something goes wrong" in options and "Glossary" in options


def test_help_opens_at_the_article_it_was_asked_for_and_shows_its_text():
    at = _help("surveys-code")
    text = " ".join(m.value for m in at.markdown)
    assert shared_help.title_of(shared_help.article("surveys", "code")) in text
    assert next(s for s in at.selectbox if s.key == "help_pick").value == "surveys-code"


def test_search_narrows_the_list_and_says_so_when_nothing_matches():
    at = _help()
    next(t for t in at.text_input if t.key == "help_query").set_value("kappa").run()
    assert not at.exception, at.exception
    shown = list(next(s for s in at.selectbox if s.key == "help_pick").options)
    assert 0 < len(shown) < 20
    next(t for t in at.text_input if t.key == "help_query").set_value("zzqxzzqx").run()
    assert any("Nothing in Help mentions" in i.value for i in at.info)


def test_the_step_help_button_opens_that_steps_article_and_back_returns():
    at = webkit.start("")
    webkit.go(at, "Data Setup")
    assert at.session_state["activity"] == "surveys"
    next(b for b in at.sidebar.button if b.key == "nav_step_help").click().run()
    assert not at.exception, at.exception
    assert at.session_state["view"] == "help"
    assert at.session_state["help_article"] == f"surveys-{at.session_state['step_surveys']}"
    next(b for b in at.button if b.key == "help_back_btn").click().run()
    assert at.session_state["view"] == "activity" and at.session_state["activity"] == "surveys"


def test_a_clip_is_shown_under_its_article():
    clip = media.for_article("surveys-code")[0]
    assert "data:image/svg+xml;base64," in help_ui.clip_html(clip.clip_id)
    at = _help("surveys-code")
    assert any(clip.title in m.value for m in at.markdown)


def test_tips_are_the_shared_words_with_a_pointer_to_help():
    text = help_ui.tip("model.seed")
    assert text and "More: Help" in text
    assert help_ui.tip("no such tip") is None
    assert help_ui.tip("Seed") == text                                    # found by its label too


def test_the_tour_shows_once_walks_four_cards_and_is_remembered(monkeypatch):
    monkeypatch.delenv("QUALSAFE_NO_TOUR", raising=False)
    at = webkit.start("")
    webkit.go(at, "Data Setup")
    assert any(b.key == "tour_next_surveys" for b in at.button)
    for _ in range(len(tours.tour("surveys"))):
        next(b for b in at.button if b.key == "tour_next_surveys").click().run()
        assert not at.exception, at.exception
    assert not any(b.key == "tour_next_surveys" for b in at.button)
    assert tours.parse(at.session_state["tours_seen"]) == {"surveys"}
    webkit.go(at, "Data Setup")
    assert not any(b.key == "tour_skip_surveys" for b in at.button)


def test_skip_ends_the_tour_and_help_can_show_it_again(monkeypatch):
    monkeypatch.delenv("QUALSAFE_NO_TOUR", raising=False)
    at = webkit.start("")
    webkit.go(at, "Data Setup")
    next(b for b in at.button if b.key == "tour_skip_surveys").click().run()
    assert "surveys" in tours.parse(at.session_state["tours_seen"])
    at.session_state["view"] = "help"
    at.run()
    next(b for b in at.button if b.key == "tour_again_surveys").click().run()
    assert any(b.key == "tour_next_surveys" for b in at.button)


def test_no_tour_while_testing():
    assert os.environ.get("QUALSAFE_NO_TOUR")
    at = webkit.start("")
    webkit.go(at, "Data Setup")
    assert not any(str(b.key).startswith("tour_") for b in at.button)


def test_every_activity_has_its_tour_cards_in_plain_words():
    from core.ux import words
    for activity in activities.ACTIVITIES:
        for card in tours.tour(activity.key):
            assert words.find_never(card.title + " " + card.text) == []


def test_the_shared_tips_sit_on_the_web_controls_that_have_them():
    """Each tip id used on a web control exists; the controls the desktop tips are covered on the web too."""
    import re
    from pathlib import Path

    from core.ux.help.tips import TIPS

    used = set()
    for path in (Path(__file__).resolve().parents[1] / "app").glob("*.py"):
        used |= set(re.findall(r'help_ui\.tip\("([a-z_.]+)"\)', path.read_text(encoding="utf-8")))
    assert used <= set(TIPS), used - set(TIPS)
    assert {"survey.question_column", "survey.question_label", "survey.respondent_id", "survey.details",
            "themes.per_question", "code.review_limits", "chart.split", "chart.sharpness", "model.method",
            "model.seed", "model.folds"} <= used
