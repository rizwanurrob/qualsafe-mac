"""Interface wording: the word lists work. The desktop uses none of them; the web only gets plainer.

Desktop (Update 3, phase 3): no hype word and no technical term in any interface string outside
`words.ALLOWED_PATHS` (Settings > Models, the model manager and the Help pages, which phase 4
rewrites). A new violation fails this test.

Web (phase 4b, item 4b.5h): the same, zero.
"""

from pathlib import Path

import pytest

from core.ux import words

@pytest.mark.parametrize("text,expected", [
    ("An AI-powered, seamless way to unlock insights", ["AI-powered", "insights", "seamless", "unlock"]),
    ("Leverage a smart, intelligent, magic tool", ["smart", "intelligent", "magic", "leverage"]),
    ("Effortless and revolutionary", ["effortless", "revolutionary"]),
    ("Find the themes in your answers", []),
])
def test_never_words_found(text, expected):
    assert sorted(words.find_never(text)) == sorted(expected)


@pytest.mark.parametrize("text,expected", [
    ("Zero-shot labels per excerpt", ["zero-shot", "excerpt"]),
    ("Flagged UNCERTAIN_REVIEW by the rater", ["UNCERTAIN_REVIEW", "rater"]),
    ("Charts of application_id and code::Money", ["id field", "code:: prefix"]),
    ("Needs your review", []),
    ("The NLI model from Hugging Face", ["NLI/MNLI/SST-2", "Hugging Face"]),
])
def test_replace_terms_found(text, expected):
    assert sorted(words.find_replace(text)) == sorted(expected)


def test_ui_strings_skip_docstrings():
    src = 'def f():\n    """An excerpt in a docstring."""\n    return "Pick an excerpt to read"\n'
    assert words.ui_strings(src) == ["Pick an excerpt to read"]


def test_every_replacement_has_a_plain_word():
    for term, (_pattern, plain) in words.REPLACE.items():
        assert plain.strip(), term


def test_the_desktop_uses_no_banned_or_technical_words():
    """Zero, not a baseline: the desktop interface has been through the plain-words pass."""
    now = words.scan()["desktop"]
    found = {kind: dict(now[kind]) for kind in ("never", "replace") if now[kind]}
    assert not found, (
        f"desktop interface text uses words it should not: {found}. Use the plain word "
        "(core/ux/words.py), or, for a Settings-only term, put the file in words.ALLOWED_PATHS.")


def test_a_technical_term_is_only_allowed_in_the_allowed_files():
    for path in words.ALLOWED_PATHS:
        assert (words.ROOT / path).is_file(), path
    assert len(words.ALLOWED_PATHS) <= 4, "the list is meant to shrink, not grow"


def test_hype_words_are_banned_even_in_the_allowed_files(tmp_path, monkeypatch):
    allowed = tmp_path / "qualsafe_qt" / "views"
    allowed.mkdir(parents=True)
    (allowed / "help_view.py").write_text('TEXT = "An effortless way to look at your embedding model"', encoding="utf-8")
    monkeypatch.setattr(words, "ALLOWED_PATHS", ("qualsafe_qt/views/help_view.py",))
    monkeypatch.setattr(words, "FRONT_END_GLOBS", {"desktop": ("qualsafe_qt/views/*.py",)})
    result = words.scan(tmp_path)["desktop"]
    assert result["never"]["effortless"] == 1 and not result["replace"]      # the technical term is allowed here


def test_the_web_uses_no_banned_or_technical_words():
    """Zero, as on the desktop: the web interface has been through the plain-words pass."""
    now = words.scan()["web"]
    found = {kind: dict(now[kind]) for kind in ("never", "replace") if now[kind]}
    assert not found, (
        f"web interface text uses words it should not: {found}. Use the plain word "
        "(core/ux/words.py), or, for a Settings-only term, put the file in words.ALLOWED_PATHS.")


def test_the_deviant_case_and_saturation_screen_uses_plain_words():
    """The desktop screen added for audit finding G4 adds nothing to the lists."""
    src = Path(__file__).parents[1] / "qualsafe_qt" / "views" / "analysis_view.py"
    strings = words.ui_strings(src.read_text(encoding="utf-8"))
    mine = [s for s in strings if any(k in s for k in (
        "re-read", "Find them", "language model", "aturation", "reading order"))]
    assert len(mine) >= 8, "expected the new screen's strings"
    for text in mine:
        assert not words.find_never(text), text
        assert not words.find_replace(text), text


def test_a_one_word_label_is_read_but_a_lower_case_key_is_not():
    """'Descriptor' slipped through for weeks as a one-word selectbox label."""
    assert "Descriptor" in words.ui_strings('st.selectbox("Descriptor", keys)')
    assert "descriptor" not in words.ui_strings('state["descriptor"] = 1')
    assert words.find_replace("Descriptor") == ["descriptor"]
