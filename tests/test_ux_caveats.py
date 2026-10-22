"""Caveats beside the number (core/ux/caveats.py): short first sentence, nothing lost."""

import pytest

from core.ux import caveats


def test_a_short_single_sentence_has_nothing_more():
    assert caveats.short_form("Percentages can add to more than 100%.") == (
        "Percentages can add to more than 100%.", False)


def test_a_long_text_shows_its_first_sentence_and_says_there_is_more():
    text = "These are importances, not coefficients. They have no direction. Read them with care."
    short, more = caveats.short_form(text)
    assert short == "These are importances, not coefficients." and more


def test_line_breaks_separate_caveats_and_only_the_first_shows():
    short, more = caveats.short_form("One caveat.<br>Another caveat.<br>A third.")
    assert short == "One caveat." and more


def test_markup_is_removed_from_the_short_form():
    short, _ = caveats.short_form("<b>This matrix mixes 2 coders.</b> A passage one coder marked A counts.")
    assert short == "This matrix mixes 2 coders."


def test_a_very_long_sentence_is_cut_at_a_word_and_marked():
    short, more = caveats.short_form("word " * 100)
    assert short.endswith("…") and len(short) <= caveats.SHORT_LIMIT + 1 and more


def test_empty_text_is_empty():
    assert caveats.short_form("") == ("", False)
    assert caveats.short_form(None) == ("", False)


def test_decimals_and_abbreviations_do_not_end_a_sentence():
    short, more = caveats.short_form("The interval is 0.42 to 0.61 (95% Wilson), so it is wide.")
    assert "0.61" in short and not more


@pytest.mark.parametrize("text", ["A. B.", "<i>Hello there.</i> More.<br>Last.", "x"])
def test_nothing_is_ever_lost_the_full_text_is_kept_by_the_caller(text):
    short, _ = caveats.short_form(text)
    assert short and short in caveats.plain(text)


def test_a_leading_bullet_is_dropped_from_the_short_form():
    short, more = caveats.short_form(chr(0x00B7) + " Codes sit close. More follows here.")
    assert short == "Codes sit close." and more
