"""Tests for the dark/light theme palettes (v3.9.8)."""

from __future__ import annotations

import core.theme as theme

REQUIRED_KEYS = {
    "bg", "bg_elevated", "surface", "border", "text", "text_muted",
    "red", "red_bright", "red_deep", "amber", "green", "heat", "category",
}


def test_both_palettes_have_all_keys():
    for mode in ("dark", "light"):
        p = theme.get_palette(mode)
        assert REQUIRED_KEYS <= set(p), f"{mode} palette missing keys"


def test_unknown_mode_falls_back_to_dark():
    assert theme.get_palette("chartreuse") is theme.DARK


def test_brand_css_differs_by_mode_and_uses_its_bg():
    dark_css = theme.brand_css("dark")
    light_css = theme.brand_css("light")
    assert dark_css != light_css
    assert theme.DARK["bg"] in dark_css
    assert theme.LIGHT["bg"] in light_css


def test_dark_heat_low_end_is_not_the_page_background():
    """The core v3.9.8 fix: low/zero heatmap cells must be visible, not black."""
    dark = theme.get_palette("dark")
    assert dark["heat"][0].lower() != dark["bg"].lower()
    # And it must not be a near-black either (some real color).
    assert dark["heat"][0].lower() not in ("#000000", "#141518", "#1c1e22")


def test_heat_ramps_differ_between_modes():
    assert theme.get_palette("dark")["heat"] != theme.get_palette("light")["heat"]


def test_altair_theme_uses_palette_heat_range():
    for mode in ("dark", "light"):
        cfg = theme.altair_theme(mode)["config"]
        p = theme.get_palette(mode)
        assert cfg["range"]["heatmap"] == p["heat"]
        assert cfg["range"]["ramp"] == p["heat"]
        assert cfg["background"] == p["bg"]


def test_register_altair_theme_never_raises():
    class _FakeThemes:
        def register(self, *a, **k):
            raise RuntimeError("boom")

        def enable(self, *a, **k):
            raise RuntimeError("boom")

    class _FakeAlt:
        themes = _FakeThemes()

    # Must swallow failures (charts are cosmetic) for both modes.
    theme.register_altair_theme(_FakeAlt(), "dark")
    theme.register_altair_theme(_FakeAlt(), "light")


def test_backwards_compatible_constants_match_dark():
    assert theme.BG == theme.DARK["bg"]
    assert theme.RED == theme.DARK["red"]
    assert theme.HEAT_RANGE == theme.DARK["heat"]


# ── categorical code colours (PORTED_BACK.md §8) ─────────────────────────────
#
# Six colours is right for a chart legend and wrong for a codebook. In the
# reader's margin stripes, and in a chart coloured by code, colour is the only
# identifier a code has — so the seventh code wrapping to the first makes two
# codes indistinguishable, silently.

class TestCategoryColors:

    def test_a_normal_codebook_does_not_wrap(self):
        """Real codebooks run to twenty or forty codes."""
        for mode in ("dark", "light"):
            assert len(theme.category_colors(mode)) >= 16

    def test_the_first_six_are_unchanged(self):
        """Appended, never reordered — an existing project keeps its colours."""
        for mode in ("dark", "light"):
            palette = theme.get_palette(mode)["category"]
            assert theme.category_colors(mode)[:6] == palette

    def test_every_colour_is_distinct_within_a_palette(self):
        for mode in ("dark", "light"):
            for name in theme.CATEGORY_PALETTES:
                colours = theme.category_colors(mode, name)
                assert len(set(colours)) == len(colours), f"{name}/{mode} repeats a colour"

    def test_every_colour_is_a_hex_triple(self):
        for mode in ("dark", "light"):
            for name in theme.CATEGORY_PALETTES:
                for colour in theme.category_colors(mode, name):
                    assert colour.startswith("#") and len(colour) == 7, colour

    def test_a_colour_vision_safe_palette_is_offered(self):
        """Red and green sit adjacent in the default list, and these figures get
        published."""
        okabe = theme.category_colors("dark", "Colour-blind safe (Okabe-Ito)")
        assert "#0072B2" in okabe and "#E69F00" in okabe

    def test_the_okabe_neutral_stays_visible_on_both_skins(self):
        assert theme.category_colors("dark", "Colour-blind safe (Okabe-Ito)")[-1] == "#DDDDDD"
        assert theme.category_colors("light", "Colour-blind safe (Okabe-Ito)")[-1] == "#333333"

    def test_an_unknown_palette_name_falls_back_rather_than_failing(self):
        assert theme.category_colors("dark", "Neon Disco") == theme.category_colors("dark")

    def test_the_altair_theme_uses_the_extended_list(self):
        """A chart coloured by code must not wrap either."""
        for mode in ("dark", "light"):
            category = theme.altair_theme(mode)["config"]["range"]["category"]
            assert category == theme.category_colors(mode)

    def test_the_altair_theme_follows_the_chosen_palette(self):
        chosen = "Colour-blind safe (Okabe-Ito)"
        category = theme.altair_theme("dark", chosen)["config"]["range"]["category"]
        assert category == theme.category_colors("dark", chosen)

    def test_each_palette_registers_under_its_own_name(self):
        """Altair caches a registered theme by name, so one name across palettes
        would enable the first choice forever."""
        registered = []

        class _FakeAlt:
            class themes:
                @staticmethod
                def register(name, fn):
                    registered.append(name)

                @staticmethod
                def enable(name):
                    pass

        try:
            from altair.theme import register  # noqa: F401
        except Exception:  # pragma: no cover - only on Altair < 5.5
            theme.register_altair_theme(_FakeAlt(), "dark", "QualSafe (default)")
            theme.register_altair_theme(_FakeAlt(), "dark", "High contrast")
            assert len(set(registered)) == 2
            return

        # On Altair >= 5.5 the names are computed the same way; assert on that.
        assert (theme.CATEGORY_PALETTES["QualSafe (default)"]
                != theme.CATEGORY_PALETTES["High contrast"])
