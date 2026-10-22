"""A caveat on the web: one sentence beside the figure, all of it behind Why? (design rule 5)."""

from __future__ import annotations

from streamlit.testing.v1 import AppTest

LONG = ("Pooled over three coders. A pair where one coder applied one code and another the other counts here, "
        "though neither claimed it, and the result will move if the analysis is re-run.")


def _run(text, kind="warning"):
    script = ("import streamlit as st\nfrom app.shared.caveat import caveat\n"
              f"caveat({text!r}, {kind!r})\n")
    at = AppTest.from_string(script, default_timeout=120)
    at.run()
    assert not at.exception, at.exception
    return at


def test_a_long_caveat_shows_its_first_sentence_with_an_icon_and_a_word_and_keeps_the_rest_under_why():
    at = _run(LONG)
    assert len(at.warning) == 1
    shown = at.warning[0].value
    assert shown.startswith("**Warning:**") and "Pooled over three coders." in shown
    assert "re-run" not in shown
    why = [e for e in at.expander if e.label == "Why?"]
    assert why and "re-run" in why[0].markdown[0].value


def test_a_short_caveat_has_no_why():
    at = _run("Only two groups were compared.", "note")
    assert len(at.info) == 1 and at.info[0].value.startswith("**Note:**")
    assert not at.expander


def test_markup_cut_by_the_short_form_never_leaves_a_mark_open():
    at = _run("**3 coders contributed** (`a`, `b`, `c`), and this view pools them. More.")
    assert "*" not in at.warning[0].value.replace("**Warning:**", "")
    assert "`" not in at.warning[0].value
