"""Activity colours exist for both themes and are readable (WCAG AA, 4.5:1)."""

import pytest

from core import theme
from qualsafe_qt.theme import activity_tints
from core.ux import activities

AA = 4.5


def _lum(hex_colour: str) -> float:
    h = hex_colour.lstrip("#")
    chans = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in chans]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(a: str, b: str) -> float:
    hi, lo = sorted((_lum(a), _lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def test_contrast_helper_known_values():
    assert contrast("#000000", "#FFFFFF") == pytest.approx(21.0)
    assert contrast("#777777", "#777777") == pytest.approx(1.0)


@pytest.mark.parametrize("mode", ["dark", "light"])
@pytest.mark.parametrize("act", activities.ACTIVITIES, ids=lambda a: a.key)
def test_every_activity_has_a_token_in_both_themes(mode, act):
    p = theme.get_palette(mode)
    assert act.colour_token in p
    assert act.colour_token + ".on" in p


@pytest.mark.parametrize("mode", ["dark", "light"])
@pytest.mark.parametrize("act", activities.ACTIVITIES, ids=lambda a: a.key)
def test_accent_is_readable_on_the_page_and_cards_and_under_its_button_text(mode, act):
    p = theme.get_palette(mode)
    accent, on = p[act.colour_token], p[act.colour_token + ".on"]
    assert contrast(accent, p["bg"]) >= AA            # links, rail text on the page
    assert contrast(accent, p["surface"]) >= AA       # the same on a card
    assert contrast(on, accent) >= AA                 # button label on the accent


@pytest.mark.parametrize("mode", ["dark", "light"])
def test_activity_colours_differ_from_each_other_and_from_status_and_brand(mode):
    p = theme.get_palette(mode)
    accents = [p[a.colour_token].lower() for a in activities.ACTIVITIES]
    assert len(set(accents)) == 3
    reserved = {p[k].lower() for k in ("red", "red_bright", "red_deep", "amber", "green")}
    assert not reserved & set(accents)


@pytest.mark.parametrize("mode", ["dark", "light"])
@pytest.mark.parametrize("role", ["amber", "green", "text_muted", "text"])
@pytest.mark.parametrize("ground", ["bg", "surface", "bg_elevated"])
def test_text_colours_for_status_and_notes_are_readable_on_every_ground(mode, role, ground):
    """Warnings, success words and muted notes are text: AA (4.5:1) on the page,
    on a card and on the tinted panels they sit in."""
    p = theme.get_palette(mode)
    assert contrast(p[role], p[ground]) >= AA, (mode, role, ground, p[role], p[ground])


@pytest.mark.parametrize("mode", ["dark", "light"])
@pytest.mark.parametrize("act", activities.ACTIVITIES, ids=lambda a: a.key)
def test_text_on_the_tinted_steps_and_tabs_is_readable(mode, act):
    """The rail and tab row are tinted in the activity colour; the words on them
    (the accent on a step, normal text on a tab) must stay at 4.5:1."""
    p = theme.get_palette(mode)
    tint = activity_tints(act.key, mode)
    accent = p[act.colour_token]
    assert contrast(p["text"], tint["step"]) >= AA     # an unselected step's label
    assert contrast(p["text"], tint["step_hover"]) >= AA  # the same under the pointer
    assert contrast(accent, p["surface"]) >= AA        # a selected tab's label
    assert contrast(p["text"], tint["tab"]) >= AA      # an unselected tab
    assert contrast(p["text"], tint["step"]) >= AA     # a tab under the pointer
    assert contrast(p["text"], tint["rail"]) >= AA     # anything sitting on the rail


@pytest.mark.parametrize("mode", ["dark", "light"])
def test_the_tints_are_different_for_each_activity(mode):
    seen = {tuple(sorted(activity_tints(a.key, mode).items())) for a in activities.ACTIVITIES}
    assert len(seen) == 3
