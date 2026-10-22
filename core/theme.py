#!/usr/bin/env python
"""
Theme palettes — single source of truth for the app's colors (dark + light).

v3.1.1 introduced a dark grey / red theme and made this the one place the
Streamlit chrome, the injected CSS, and the Altair charts read their colors from
(they were three drifting copies before). v3.9.8 adds a **light** skin alongside
the dark one and gives heatmaps a high-contrast, two-hue ramp so low/zero cells
are legible instead of fading to black.

Two palettes, same keys, selected by `mode` ("dark" | "light"):

    bg / bg_elevated / surface / border   layout tones
    text / text_muted                     body + secondary text
    red / red_bright / red_deep           brand accent (button, headings, hover)
    amber / green                         warning / success
    heat                                  sequential ramp for heatmaps
    category                              categorical series colors

Two deliberate choices carried over: **warnings are amber, not red** (red is the
brand accent, so a red warning stops reading as a warning), and heat ramps do
**not** start at the page background — a low count must be a visible color, or the
co-occurrence matrix reads as an empty black grid.
"""

from __future__ import annotations

from typing import Any, Dict

# ── Dark palette (default) ──────────────────────────────────────────────────
DARK: Dict[str, Any] = {
    "bg": "#141518",
    "bg_elevated": "#1C1E22",
    "surface": "#26282E",
    "border": "#35373E",
    "text": "#E8E9EC",
    "text_muted": "#9AA0A8",
    "red": "#E03846",
    "red_bright": "#FF6B72",
    "red_deep": "#A81D28",
    "amber": "#E0A040",
    "green": "#4FAF7C",
    # Blue → orange → cream. Low end is a visible slate-blue (not the page
    # background), so the smallest counts still read; intensity climbs through
    # orange to near-white. Blue↔orange is the most colorblind-safe two-hue pair
    # and stays distinct from the red brand chrome, so the heatmap reads as data.
    "heat": ["#2A3E56", "#356089", "#5A9BC4", "#E8944A", "#F2B85E", "#FBE7C6"],
    "category": ["#5A9BC4", "#E8944A", "#4FAF7C", "#B98AD6", "#F2C879", "#E06666"],
    # Activity colours (Update 3). Each activity has an accent and the text colour
    # to put on it. They mark where you are, never chart data or status.
    "activity.surveys": "#6AA7E8", "activity.surveys.on": "#141518",
    "activity.charts": "#3FB8AC", "activity.charts.on": "#141518",
    "activity.interviews": "#C08BE0", "activity.interviews.on": "#141518",
}

# ── Light palette ───────────────────────────────────────────────────────────
LIGHT: Dict[str, Any] = {
    "bg": "#FAFAFB",
    "bg_elevated": "#F0F1F4",
    "surface": "#FFFFFF",
    "border": "#D4D7DE",
    "text": "#1F2328",
    "text_muted": "#5A616B",
    # On a light background the accent must be darkened to stay legible — a bright
    # red glares and fails contrast. red_bright is therefore *deeper* than red
    # here (it styles headings, which sit on the page background).
    "red": "#C62234",
    "red_bright": "#A3121F",
    "red_deep": "#8A1721",
    # Amber and green are used as *text* (warnings, "done"), so they must reach
    # 4.5:1 on the page, cards and tinted panels (tests/test_ux_colours.py).
    "amber": "#A05E00",
    "green": "#287650",
    # Light → blue → orange → deep orange. Low end is a pale blue that recedes on
    # white; intensity deepens through orange. Same blue↔orange family as dark.
    "heat": ["#EAF2FB", "#9CC3E6", "#5A9BC4", "#E8944A", "#D2691E", "#A0430A"],
    "category": ["#2F6690", "#D2691E", "#2E7D53", "#7A4F9E", "#B8860B", "#C62234"],
    "activity.surveys": "#1F5FA8", "activity.surveys.on": "#FFFFFF",
    "activity.charts": "#0F766E", "activity.charts.on": "#FFFFFF",
    "activity.interviews": "#7B3FA0", "activity.interviews.on": "#FFFFFF",
}

PALETTES: Dict[str, Dict[str, Any]] = {"dark": DARK, "light": LIGHT}
DEFAULT_MODE = "dark"

# Named heatmap ramps the analyst can choose per chart (v3.9.9). Each low end is a
# visible color (never the page background), so low/zero cells stay legible on
# either skin. Ordered low→high. "Blue → Orange" is the default (matches the
# palette `heat`); the rest cover the common asks (red/orange/white, green/orange)
# plus two perceptual ramps.
HEATMAP_SCHEMES: Dict[str, list] = {
    "Blue → Orange": ["#2A3E56", "#356089", "#5A9BC4", "#E8944A", "#F2B85E", "#FBE7C6"],
    "Red → Orange → White": ["#5A1F26", "#A81D28", "#E03846", "#E8944A", "#F2C879", "#FFF3D6"],
    "Green → Orange": ["#1E4D3A", "#2E7D53", "#7FB069", "#E8C84A", "#E8944A", "#C25A1E"],
    "Purple → Yellow": ["#3B0F70", "#8C2981", "#DE4968", "#FE9F6D", "#FCFDBF"],
    "Teal → Yellow": ["#0D3B4F", "#1F7A8C", "#4FAF9C", "#BFD77A", "#F2E863"],
}
DEFAULT_HEATMAP_SCHEME = "Blue → Orange"

# ── Categorical colours for codes ───────────────────────────────────────────
#
# Six is right for a chart legend and wrong for a codebook. Real codebooks run to
# twenty or forty codes, and at six the seventh code wraps to the first — in the
# document reader's margin stripes and in a chart built by code, where colour is
# the only identifier, two different codes then become indistinguishable.
#
# The palettes above keep their six unchanged and these are **appended**, never
# reordered, so a project that already exists keeps every colour it had.
#
# Chosen to stay apart from each other and from the brand red at stripe width on
# both skins. Ported from the desktop build, where the wrap was most visible
# (PORTED_BACK.md §8).
_EXTRA_DARK = ["#7FD1C1", "#D98BA5", "#9CB86F", "#C9A26D", "#8FA5E0", "#E0A0C8",
               "#6FB8D9", "#C4A484", "#A8D18D", "#D4A5D8"]
_EXTRA_LIGHT = ["#1F7A6B", "#A63E5F", "#5C7A30", "#8A6A2F", "#3D52A0", "#9C3F78",
                "#2A6E8F", "#7A5C3A", "#4A7A2E", "#7A3F8A"]

#: Okabe-Ito, the standard qualitative palette designed for colour-vision
#: deficiency. Seven hues plus a per-skin neutral, then it repeats — and eight
#: hues everyone can tell apart beats sixteen that some readers cannot. Worth
#: having in a tool whose figures end up in published research: red and green sit
#: adjacent in the default list.
_OKABE_ITO = ["#E69F00", "#56B4E9", "#009E73", "#F0E442",
              "#0072B2", "#D55E00", "#CC79A7"]

CATEGORY_PALETTES: Dict[str, str] = {
    "QualSafe (default)": "default",
    "Colour-blind safe (Okabe-Ito)": "okabe_ito",
    "High contrast": "high_contrast",
}
DEFAULT_CATEGORY_PALETTE = "QualSafe (default)"


def category_colors(mode: str = DEFAULT_MODE,
                    palette: str = DEFAULT_CATEGORY_PALETTE) -> list:
    """The ordered code colours for a skin and palette choice.

    At least sixteen entries for the default palette, so an ordinary codebook
    does not wrap. The default's first six are the palette's own, unchanged.
    """
    kind = CATEGORY_PALETTES.get(palette, "default")
    if kind == "okabe_ito":
        return list(_OKABE_ITO) + ["#DDDDDD" if mode == "dark" else "#333333"]
    if kind == "high_contrast":
        # Maximum separation, accepting that it is louder than the brand.
        return (["#FFFFFF", "#FFD400", "#00E5FF", "#FF5A5A", "#7CFF6B", "#FF8AE2",
                 "#FFA23A", "#8AB6FF"] if mode == "dark" else
                ["#000000", "#8A6D00", "#005F73", "#9B0000", "#0B6B2E", "#7A0F6B",
                 "#8A4B00", "#123A8A"])
    extra = _EXTRA_DARK if mode == "dark" else _EXTRA_LIGHT
    return list(get_palette(mode)["category"]) + extra


def heatmap_range(scheme: str = DEFAULT_HEATMAP_SCHEME) -> list:
    """The color stops for a named heatmap scheme (falls back to the default)."""
    return HEATMAP_SCHEMES.get(scheme, HEATMAP_SCHEMES[DEFAULT_HEATMAP_SCHEME])

# Backwards-compatible module constants (the dark palette), for any importer that
# referenced the old flat names.
BG = DARK["bg"]
BG_ELEVATED = DARK["bg_elevated"]
SURFACE = DARK["surface"]
BORDER = DARK["border"]
TEXT = DARK["text"]
TEXT_MUTED = DARK["text_muted"]
RED = DARK["red"]
RED_BRIGHT = DARK["red_bright"]
RED_DEEP = DARK["red_deep"]
AMBER = DARK["amber"]
GREEN = DARK["green"]
HEAT_RANGE = DARK["heat"]


def get_palette(mode: str = DEFAULT_MODE) -> Dict[str, Any]:
    """Return the palette for a mode, falling back to dark for anything unknown."""
    return PALETTES.get(mode, DARK)


def altair_theme(mode: str = DEFAULT_MODE,
                 category_palette: str = DEFAULT_CATEGORY_PALETTE) -> Dict[str, Any]:
    """Altair theme config matching the app chrome for `mode`.

    Altair defaults to white panels with black text; dropped onto either skin
    without this they read as holes punched in the layout.

    The categorical range is the **extended** list, so a chart coloured by code
    does not wrap at the seventh one.
    """
    p = get_palette(mode)
    return {
        "config": {
            "background": p["bg"],
            "title": {"color": p["text"], "subtitleColor": p["text_muted"], "fontSize": 14},
            "style": {
                "guide-label": {"fill": p["text_muted"]},
                "guide-title": {"fill": p["text"]},
            },
            "axis": {
                "domainColor": p["border"],
                "gridColor": p["border"],
                "gridOpacity": 0.4,
                "tickColor": p["border"],
                "labelColor": p["text_muted"],
                "titleColor": p["text"],
            },
            "legend": {
                "labelColor": p["text_muted"],
                "titleColor": p["text"],
                "gradientStrokeColor": p["border"],
            },
            "view": {"stroke": p["border"], "continuousWidth": 400, "continuousHeight": 300},
            "range": {
                "heatmap": p["heat"],
                "ramp": p["heat"],
                "category": category_colors(mode, category_palette),
            },
        }
    }


# Kept as an alias so older call sites / tests referencing the dark-only name work.
def altair_dark_theme() -> Dict[str, Any]:
    return altair_theme("dark")


def register_altair_theme(alt: Any, mode: str = DEFAULT_MODE,
                          category_palette: str = DEFAULT_CATEGORY_PALETTE) -> None:
    """Register and enable the Altair theme for `mode`.

    Registered under a per-mode, per-palette name and enabled, so switching skins
    *or* categorical palettes re-points the charts. Altair 5.5 moved theme
    registration to a new API; charts are cosmetic, so a registration failure must
    never take down the Analysis page — worst case the chart uses Altair's
    default colors.
    """
    # The palette is part of the name because Altair caches a registered theme by
    # it: reusing one name across palettes would enable the first one forever.
    slug = CATEGORY_PALETTES.get(category_palette, "default")
    name = f"qnw_{mode}_{slug}"

    try:  # Altair >= 5.5
        from altair.theme import register as _register

        @_register(name, enable=True)
        def _theme() -> Dict[str, Any]:
            return altair_theme(mode, category_palette)

        return
    except Exception:  # noqa: BLE001 - fall through to the legacy API
        pass

    try:  # Altair < 5.5
        alt.themes.register(name, lambda: altair_theme(mode, category_palette))
        alt.themes.enable(name)
    except Exception:  # noqa: BLE001 - cosmetic only
        pass


def brand_css(mode: str = DEFAULT_MODE) -> str:
    """The app's injected stylesheet for `mode`, built from the palette above."""
    p = get_palette(mode)
    bg, bg_elevated, surface, border = p["bg"], p["bg_elevated"], p["surface"], p["border"]
    text, text_muted = p["text"], p["text_muted"]
    red, red_bright, red_deep = p["red"], p["red_bright"], p["red_deep"]
    amber, green = p["amber"], p["green"]
    return f"""
<style>
/* ── Base layout ───────────────────────────────────────────────────── */
html, body, [data-testid="stAppViewContainer"] {{
    background-color: {bg};
    color: {text};
}}
[data-testid="stHeader"] {{
    background-color: {bg};
    border-bottom: 1px solid {border};
}}
[data-testid="stAppViewContainer"] p,
[data-testid="stAppViewContainer"] li,
[data-testid="stAppViewContainer"] label {{
    color: {text};
}}

/* ── Sidebar ───────────────────────────────────────────────────────── */
[data-testid="stSidebar"] {{
    background-color: {bg_elevated};
    border-right: 2px solid {red};
}}
[data-testid="stSidebar"] .stRadio label {{
    font-weight: 500;
    color: {text};
}}

/* ── Typography ────────────────────────────────────────────────────── */
h1 {{
    color: {red_bright} !important;
    border-left: 5px solid {red};
    padding-left: 0.6rem;
    font-weight: 700 !important;
}}
h2 {{
    color: {text} !important;
    border-bottom: 1px solid {red}55;
    padding-bottom: 0.2rem;
}}
h3 {{
    color: {red_bright} !important;
}}

/* ── Buttons ───────────────────────────────────────────────────────── */
.stButton > button, .stDownloadButton > button {{
    background-color: {red} !important;
    color: #FFFFFF !important;
    border: 1.5px solid {red} !important;
    border-radius: 6px !important;
    font-weight: 600 !important;
    letter-spacing: 0.01em;
    transition: background-color 0.15s ease;
}}
.stButton > button:hover, .stDownloadButton > button:hover {{
    background-color: {red_deep} !important;
    color: #FFFFFF !important;
    border-color: {red_bright} !important;
}}

/* ── Inputs ────────────────────────────────────────────────────────── */
[data-testid="stTextInput"] input,
[data-testid="stNumberInput"] input,
[data-testid="stTextArea"] textarea,
[data-baseweb="select"] > div {{
    background-color: {surface} !important;
    color: {text} !important;
    border-color: {border} !important;
}}

/* ── Metrics ───────────────────────────────────────────────────────── */
[data-testid="stMetricValue"] {{
    color: {red_bright} !important;
    font-weight: 700;
}}
[data-testid="stMetricLabel"] {{
    color: {text_muted} !important;
}}
[data-testid="metric-container"], [data-testid="stMetric"] {{
    background-color: {surface};
    border: 1px solid {border};
    border-radius: 8px;
    padding: 0.5rem 0.75rem;
}}

/* ── Data tables ───────────────────────────────────────────────────── */
[data-testid="stDataFrame"], [data-testid="stTable"] {{
    border: 1px solid {border};
    border-radius: 6px;
}}
/* Static (HTML) tables are CSS-styleable, so give them full contrast in both
   skins. The interactive stDataFrame grid renders on a canvas that follows
   Streamlit's own theme setting; see the note in render_appearance_control. */
[data-testid="stTable"] table {{ color: {text}; }}
[data-testid="stTable"] th {{
    background-color: {bg_elevated} !important;
    color: {text} !important;
}}
[data-testid="stTable"] td {{
    background-color: {surface} !important;
    color: {text} !important;
    border-color: {border} !important;
}}

/* ── Banners ───────────────────────────────────────────────────────── */
/* Amber (not red) for warnings: red is brand chrome here, so a red warning
   would blend into the UI instead of interrupting it. */
[data-testid="stWarning"] {{
    border-left: 4px solid {amber};
    background-color: {amber}1A;
    color: {text};
}}
[data-testid="stSuccess"] {{
    border-left: 4px solid {green};
    background-color: {green}1A;
    color: {text};
}}
[data-testid="stInfo"] {{
    border-left: 4px solid {text_muted};
    background-color: {surface};
    color: {text};
}}
[data-testid="stError"] {{
    border-left: 4px solid {red};
    background-color: {red}1A;
    color: {text};
}}

/* ── Expanders ─────────────────────────────────────────────────────── */
[data-testid="stExpander"] {{
    border: 1px solid {border} !important;
    border-radius: 6px !important;
    background-color: {bg_elevated};
}}

/* ── Tabs ──────────────────────────────────────────────────────────── */
[data-baseweb="tab-list"] {{
    border-bottom: 1px solid {border};
}}
[data-baseweb="tab"][aria-selected="true"] {{
    color: {red_bright} !important;
    border-bottom-color: {red} !important;
}}

/* ── Code blocks ───────────────────────────────────────────────────── */
code, pre, [data-testid="stCodeBlock"] {{
    background-color: {surface} !important;
    color: {text} !important;
}}

/* ── Caption / footer text ─────────────────────────────────────────── */
.stCaption, [data-testid="stCaption"] {{
    color: {text_muted} !important;
}}
</style>
"""


def _hue_shift(accent: str, base: str = "#E03846") -> int:
    """Degrees to turn Streamlit's red so it lands on `accent` (for the parts CSS cannot recolour)."""
    import colorsys

    def hue(hex_colour: str) -> float:
        h = hex_colour.lstrip("#")
        r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
        return colorsys.rgb_to_hls(r, g, b)[0] * 360

    return int(round((hue(accent) - hue(base)) % 360))


def activity_web_css(activity_key: str = "", mode: str = DEFAULT_MODE) -> str:
    """The web app's colour for one activity (Update 3, phase 4b), on top of `brand_css`.

    Inside an activity its colour is used for the header bar, the band with the breadcrumb,
    the main (primary) button, tab underlines, the sidebar edge, links and focus rings (V8_PLAN
    section 4). It is not used for chart data or for status. With no activity (Home, Settings,
    Help) the same parts take the neutral colour, so the page does not look like any activity.

    The style arrives in the same script run as the band it colours, so a switch from one
    activity to another changes every part in one step (measured in 4b.1: no frame in between).
    """
    palette = get_palette(mode)
    if activity_key:
        accent, on = palette[f"activity.{activity_key}"], palette[f"activity.{activity_key}.on"]
    else:
        accent, on = palette["text_muted"], palette["bg"]
    text, bg, border = palette["text"], palette["bg"], palette["border"]
    # Tables are drawn on a canvas in Streamlit's own theme, which is dark and cannot be changed
    # while the app runs. Under the light skin the canvas is inverted (the text turns dark on light).
    # No table here carries colours of its own, so the invert does not change a meaning.
    grid_css = ('[data-testid="stDataFrameResizable"] { filter: invert(1) hue-rotate(180deg); }\n'
                if mode == "light" else "")
    return f"""
<style>
/* ── Activity colour: {activity_key or 'neutral'} ───────────────────────────── */
[data-testid="stHeader"] {{ background-color: {accent} !important; }}
[data-testid="stHeader"] * {{ color: {on} !important; }}
[data-testid="stSidebar"] {{ border-right: 4px solid {accent}; }}
.qs-band {{
    background: {accent}; color: {on}; padding: .55rem 1rem; border-radius: 6px;
    font-weight: 700; margin-bottom: .75rem;
}}
.qs-band a, .qs-band span {{ color: {on}; }}
.qs-intro {{ margin: 0 0 .75rem 0; }}
button[kind="primary"], [data-testid="stBaseButton-primary"] {{
    background-color: {accent} !important; color: {on} !important;
    border: 2px solid {accent} !important; font-weight: 700;
}}
/* the label is a <p> inside the button, and the page's own `p` colour wins over the button's unless
   it is set here: measured in the browser pane, dark text on the activity colour (about 2.4 to 1). */
button[kind="primary"]:not(:disabled) p, [data-testid="stBaseButton-primary"]:not(:disabled) p,
button[kind="primary"]:not(:disabled) *, [data-testid="stBaseButton-primary"]:not(:disabled) * {{
    color: {on} !important;
}}
button[kind="primary"]:hover, [data-testid="stBaseButton-primary"]:hover,
button[kind="primary"]:focus, [data-testid="stBaseButton-primary"]:focus,
button[kind="primary"]:active, [data-testid="stBaseButton-primary"]:active {{
    background-color: {accent} !important; color: {on} !important;
    border-color: {text} !important; filter: brightness(1.08);
}}
/* one filled button per screen: the main one. Every other button is an outline. */
button[kind="secondary"], [data-testid="stBaseButton-secondary"] {{
    background-color: transparent !important; color: {text} !important;
    border: 1px solid {accent} !important; font-weight: 400;
}}
button[kind="secondary"]:hover, [data-testid="stBaseButton-secondary"]:hover {{
    background-color: {bg} !important; border-color: {text} !important;
}}
button[kind="primary"]:disabled, [data-testid="stBaseButton-primary"]:disabled {{
    background-color: transparent !important; color: {palette['text_muted']} !important;
    border-color: {palette['text_muted']} !important; filter: none;
}}
button[kind="primary"]:disabled *, [data-testid="stBaseButton-primary"]:disabled * {{
    color: {palette['text_muted']} !important;
}}
[data-baseweb="tab"][aria-selected="true"] {{
    color: {text} !important; border-bottom-color: {accent} !important;
}}
div[role="radiogroup"] label[data-baseweb="radio"] > div:first-child {{ border-color: {accent} !important; }}
div[role="radiogroup"] label[data-baseweb="radio"]:has(input:checked) > div:first-child {{
    background-color: {accent} !important; border-color: {accent} !important;
}}
h1, h2, h3, h4 {{ color: {text} !important; }}
a {{ color: {accent}; }}
*:focus-visible {{ outline: 3px solid {accent} !important; outline-offset: 2px; }}
/* Streamlit 1.5x and later drop `data-baseweb` from radios and selects, so the rules above and the
   skin's input rule no longer reach them. These name the parts as they are now: a radio's ring is
   the one div that holds a single div (the inner dot) and no text; a select is a react-aria combo box. */
div[role="radiogroup"] label div:has(> div:only-child):not(:has(p)) {{
    background-color: {palette['surface']} !important; border: 2px solid {palette['text_muted']} !important;
}}
div[role="radiogroup"] label:has(input:checked) div:has(> div:only-child):not(:has(p)) {{
    background-color: {accent} !important; border-color: {accent} !important;
}}
div[role="radiogroup"] label div:has(> div:only-child):not(:has(p)) > div {{
    background-color: {palette['surface']} !important;
}}
div[role="radiogroup"] label:has(input:checked) div:has(> div:only-child):not(:has(p)) > div {{
    background-color: {on} !important;
}}
[data-testid="stCheckbox"] label > span + div {{
    background-color: {palette['surface']} !important; border: 2px solid {palette['text_muted']} !important;
}}
[data-testid="stCheckbox"] label:has(input:checked) > span + div {{
    background-color: {accent} !important; border-color: {accent} !important;
}}
[data-testid="stCheckbox"] label:has(input:checked) > span + div * {{ color: {on} !important; fill: {on} !important; }}
[data-testid="stFileUploaderDropzone"] {{
    background-color: {palette['surface']} !important; color: {text} !important;
    border: 1px dashed {palette['text_muted']} !important;
}}
[data-testid="stFileUploaderDropzone"] * {{ color: {text} !important; }}
[data-testid="stFileUploaderDropzone"] small {{ color: {palette['text_muted']} !important; }}
[data-testid="stTextInputRootElement"], [data-testid="stTextAreaRootElement"],
[data-testid="stNumberInputContainer"] {{
    background-color: {palette['surface']} !important; border-color: {border} !important;
}}
input::placeholder, textarea::placeholder {{ color: {palette['text_muted']} !important; opacity: 1; }}
{grid_css}/* tabs, and the slider (its filled track is a gradient set by Streamlit, so it is turned to the colour) */
[data-testid="stTab"] {{ color: {palette['text_muted']} !important; }}
[data-testid="stTab"][aria-selected="true"] {{ color: {text} !important; border-bottom-color: {accent} !important; }}
[role="tablist"] [class*="SelectionIndicator"] {{ background-color: {accent} !important; }}
[data-testid="stSlider"] {{ filter: hue-rotate({_hue_shift(accent)}deg); }}
/* the open list of a select (and of a multi-select) is drawn outside the page, in the base theme */
[data-testid="stSelectboxVirtualDropdown"], [role="listbox"] {{
    background-color: {palette['surface']} !important; border: 1px solid {border} !important;
}}
[data-testid="stSelectboxVirtualDropdown"] [role="option"], [role="listbox"] [role="option"] {{
    color: {text} !important; background-color: transparent !important;
}}
[role="listbox"] [role="option"][data-focused="true"], [role="listbox"] [role="option"][data-selected="true"],
[role="listbox"] [role="option"]:hover {{ background-color: {palette['bg_elevated']} !important; }}
[data-testid="stExpander"] summary {{
    background-color: {palette['surface']} !important; color: {text} !important;
}}
[data-testid="stExpander"] summary * {{ color: {text} !important; }}
[data-testid="stNumberInput"] button {{
    background-color: {palette['surface']} !important; color: {text} !important;
    border-color: {border} !important;
}}
[data-testid="stNumberInput"] button * {{ color: {text} !important; }}
.react-aria-ComboBox, [data-testid="stSelectbox"] div[role="group"], [data-testid="stMultiSelect"] div[role="group"] {{
    background-color: {palette['surface']} !important; color: {text} !important;
    border: 1px solid {border} !important;
}}
.react-aria-ComboBox *, [data-testid="stSelectbox"] div[role="group"] *,
[data-testid="stMultiSelect"] div[role="group"] * {{ color: {text} !important; }}
/* a chosen item in a multi-select: the activity colour, not Streamlit's red */
[data-testid="stMultiSelect"] span[data-tag] {{ background-color: {accent} !important; border-radius: 4px; }}
[data-testid="stMultiSelect"] span[data-tag] *, [data-testid="stMultiSelect"] span[data-tag] button * {{
    color: {on} !important; fill: {on} !important;
}}
</style>
"""


def home_web_css(mode: str = DEFAULT_MODE) -> str:
    """The three activity cards on Home: a coloured top edge each, in the activity's colour."""
    palette = get_palette(mode)
    rules = []
    for key in ("surveys", "charts", "interviews"):
        rules.append(f'.st-key-card_{key} {{ border-top: 6px solid {palette["activity." + key]}; '
                     f'border-radius: 6px; min-height: 17rem; }}')
        rules.append(f'.st-key-card_{key} h3 {{ color: {palette["activity." + key]} !important; }}')
        # also on hover, focus and press, and for the label inside: the neutral rule for the page names
        # these states too and would otherwise turn a card's button grey under the pointer
        rules.append(f'.st-key-card_{key} [data-testid="stBaseButton-primary"], '
                     f'.st-key-card_{key} [data-testid="stBaseButton-primary"]:hover, '
                     f'.st-key-card_{key} [data-testid="stBaseButton-primary"]:focus, '
                     f'.st-key-card_{key} [data-testid="stBaseButton-primary"]:active {{ '
                     f'background-color: {palette["activity." + key]} !important; '
                     f'color: {palette["activity." + key + ".on"]} !important; '
                     f'border-color: {palette["activity." + key]} !important; }}')
        rules.append(f'.st-key-card_{key} [data-testid="stBaseButton-primary"] * {{ '
                     f'color: {palette["activity." + key + ".on"]} !important; }}')
    return "<style>\n" + "\n".join(rules) + "\n</style>\n"
