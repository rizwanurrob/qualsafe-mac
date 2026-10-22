"""CaveatNote and the status colours: icon and word on every status, never green for a warning."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from core import theme as core_theme  # noqa: E402
from qualsafe_qt import theme  # noqa: E402
from qualsafe_qt.widgets.caveat import CaveatNote  # noqa: E402

from tests.test_ux_colours import contrast  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


LONG = "This is the first sentence. This is the second sentence, which explains why."


def test_a_long_caveat_shows_one_sentence_and_why(app):
    n = CaveatNote("warning")
    n.resize(600, 100)
    n.show()
    n.setText(LONG)
    app.processEvents()
    assert "first sentence" in n.short.text() and "second" not in n.short.text()
    assert n.why.isVisibleTo(n) and not n.full.isVisibleTo(n)


def test_why_opens_the_full_text_and_hide_closes_it(app):
    n = CaveatNote("note")
    n.show()
    n.setText(LONG)
    n.why.click()
    assert n.full.isVisibleTo(n) and "second sentence" in n.full.text() and n.why.text() == "Hide"
    assert not n.short.isVisibleTo(n)
    n.why.click()
    assert not n.full.isVisibleTo(n) and n.short.isVisibleTo(n) and n.why.text() == "Why?"


def test_the_whole_text_is_always_kept(app):
    n = CaveatNote()
    n.setText(LONG)
    assert n.text() == LONG


def test_a_one_sentence_caveat_has_no_why(app):
    n = CaveatNote()
    n.show()
    n.setText("Short and complete.")
    assert not n.why.isVisibleTo(n)


@pytest.mark.parametrize("kind", ["warning", "error", "success", "note"])
def test_every_kind_has_an_icon_and_a_word(app, kind):
    n = CaveatNote(kind)
    n.setText("Something.")
    assert theme.STATUS_ICON[kind] in n.icon.text()
    assert theme.STATUS_WORD[kind] in n.icon.text()
    text = theme.banner_text(kind, "x")
    assert theme.STATUS_ICON[kind] in text and theme.STATUS_WORD[kind] in text


def test_spans_start_with_the_icon_unless_asked_not_to():
    assert theme.warning_span("x").count(theme.STATUS_ICON["warning"]) == 1
    assert theme.success_span("x").count(theme.STATUS_ICON["success"]) == 1
    assert theme.error_span("x").count(theme.STATUS_ICON["error"]) == 1
    assert theme.STATUS_ICON["warning"] not in theme.warning_span("x", icon=False)


@pytest.mark.parametrize("mode", ["light", "dark"])
def test_a_warning_or_error_banner_is_never_green(mode):
    green = core_theme.get_palette(mode)["green"].lower()
    for kind in ("warning", "error"):
        assert green not in theme.banner_style(kind, mode).lower(), kind


@pytest.mark.parametrize("mode", ["light", "dark"])
@pytest.mark.parametrize("kind", ["warning", "error", "success", "note"])
def test_banner_text_is_readable_on_its_ground(mode, kind):
    p = core_theme.get_palette(mode)
    ground, ink = theme._BANNER[kind]
    assert contrast(p[ground], p[ink]) >= 4.5, (kind, mode)


def test_warning_error_and_success_look_different():
    assert len({theme.banner_style(k, "light") for k in ("warning", "error", "success")}) == 3
