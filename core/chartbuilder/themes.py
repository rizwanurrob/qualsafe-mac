"""
Theme engine: colours as data, and the rules that assign them to categories.

A `Theme` is a small value (primary, secondary, tertiary, neutral, background,
text, gridline, an ordered categorical palette, a sequential palette). Every
built-in and every user-made theme is one, so "choose a theme", "make a custom
theme" and "reset to the default" are the same operation on the same type.

Colour assignment, in priority order, for each category:
1. a **manual override** the analyst set (always wins),
2. a **semantic scale** colour, when the categories are a recognised ordered
   scale (importance, agreement, satisfaction, frequency) or the analyst named
   one, expressed as a *role* (neutral / secondary / primary / tertiary) so it
   follows whichever theme is active,
3. the theme's **ordered categorical palette**.

Semantic roles resolve through the theme, which is why the default theme's agreement
scale is silver -> purple -> blue -> gold -> gold there and something sensible in
the colour-blind theme too.

The default hexes are the ones the brief specifies. The four extra categorical
entries are tints/shades of them so a chart with more than four series still
reads as the default; they are not brand-book colours.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence

DEFAULT_BLUE = "#15284B"
DEFAULT_GOLD = "#BC912C"
DEFAULT_SILVER = "#A7A8AA"
DEFAULT_PURPLE = "#B7B4D8"

_HEX = re.compile(r"^#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


def normalize_hex(value: str) -> str:
    """'#RRGGBB' from '#bc912c', 'BC912C' or '#abc'. Raises ValueError otherwise."""
    match = _HEX.match((value or "").strip())
    if not match:
        raise ValueError(f"'{value}' is not a hex colour (expected #RRGGBB).")
    digits = match.group(1)
    if len(digits) == 3:
        digits = "".join(c * 2 for c in digits)
    return "#" + digits.upper()


@dataclass
class Theme:
    name: str
    primary: str
    secondary: str
    tertiary: List[str]
    neutral: str
    background: str = "#FFFFFF"
    text: str = "#222222"
    title: str = "#222222"
    gridline: str = "#E4E4E4"
    categorical: List[str] = field(default_factory=list)
    sequential: List[str] = field(default_factory=list)
    builtin: bool = False

    def __post_init__(self):
        for attr in ("primary", "secondary", "neutral", "background", "text",
                     "title", "gridline"):
            setattr(self, attr, normalize_hex(getattr(self, attr)))
        self.tertiary = [normalize_hex(c) for c in self.tertiary]
        self.categorical = [normalize_hex(c) for c in self.categorical] or \
            [self.primary, self.secondary, self.neutral, *self.tertiary]
        self.sequential = [normalize_hex(c) for c in self.sequential] or \
            [self.background, self.primary, self.secondary]

    def role(self, name: str) -> str:
        """Colour for a semantic role."""
        return {"primary": self.primary, "secondary": self.secondary,
                "neutral": self.neutral,
                "tertiary": self.tertiary[0] if self.tertiary else self.neutral,
                }[name]

    def series_color(self, index: int) -> str:
        return self.categorical[index % len(self.categorical)]

    def to_dict(self) -> dict:
        data = asdict(self)
        data.pop("builtin")
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "Theme":
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__
                 and k != "builtin"}
        return cls(**known)


BUILT_IN_DEFAULT = Theme(
    name="QualSafe default",
    primary=DEFAULT_GOLD, secondary=DEFAULT_BLUE, tertiary=[DEFAULT_PURPLE],
    neutral=DEFAULT_SILVER, background="#FFFFFF", text="#222222",
    title=DEFAULT_BLUE, gridline="#E6E6E6",
    categorical=[DEFAULT_GOLD, DEFAULT_BLUE, DEFAULT_SILVER, DEFAULT_PURPLE,
                 "#E3C878", "#4A6491", "#6D6E71", "#8A6A1F"],
    sequential=["#F3EEDC", "#E3C878", DEFAULT_GOLD, DEFAULT_BLUE],
    builtin=True)

OKABE_ITO = Theme(
    name="Colour-blind safe (Okabe-Ito)",
    primary="#E69F00", secondary="#0072B2", tertiary=["#56B4E9", "#009E73"],
    neutral="#999999", title="#222222",
    categorical=["#E69F00", "#0072B2", "#009E73", "#CC79A7", "#56B4E9",
                 "#D55E00", "#F0E442", "#999999"],
    sequential=["#EAF3FA", "#56B4E9", "#0072B2", "#08306B"], builtin=True)

GRAYSCALE = Theme(
    name="Grayscale", primary="#404040", secondary="#808080",
    tertiary=["#B0B0B0"], neutral="#D0D0D0", title="#111111",
    categorical=["#404040", "#808080", "#B0B0B0", "#D0D0D0", "#606060",
                 "#909090"],
    sequential=["#F2F2F2", "#BDBDBD", "#737373", "#252525"], builtin=True)

OCEAN = Theme(
    name="Ocean", primary="#1F77B4", secondary="#0B3C5D",
    tertiary=["#5FB3B3"], neutral="#A9B4BE", title="#0B3C5D",
    categorical=["#1F77B4", "#0B3C5D", "#5FB3B3", "#A9B4BE", "#F2A65A",
                 "#7A9CC6"],
    sequential=["#E8F1F8", "#7A9CC6", "#1F77B4", "#0B3C5D"], builtin=True)

BUILTIN_THEMES: Dict[str, Theme] = {t.name: t for t in
                                    (BUILT_IN_DEFAULT, OKABE_ITO, GRAYSCALE, OCEAN)}
DEFAULT_THEME_NAME = BUILT_IN_DEFAULT.name


def get_theme(name: Optional[str], custom: Optional[Dict[str, Theme]] = None) -> Theme:
    """A theme by name (custom first), else the default. Never raises: a saved chart
    that names a theme since deleted still opens."""
    if custom and name in custom:
        return custom[name]
    return BUILTIN_THEMES.get(name or "", BUILT_IN_DEFAULT)


def _hex_list(text: str) -> List[str]:
    return [t.strip() for t in re.split(r"[,\s]+", text or "") if t.strip()]


def build_theme(name: str, *, primary: str, secondary: str, neutral: str,
                background: str = "#FFFFFF", text: str = "#222222", title: str = "",
                gridline: str = "#E4E4E4", tertiary: str = "", palette: str = "") -> Theme:
    """A theme from what a form holds: hex strings and two comma-separated lists.

    Both front ends call this, so a hex that is refused is refused in the same
    words everywhere. The title colour defaults to the text colour; a blank
    palette is derived from the primary, secondary, neutral and tertiary colours.
    Raises `ValueError` naming the first colour that is not a hex code.
    """
    if not (name or "").strip():
        raise ValueError("Give the theme a name.")
    return Theme(name=name.strip(), primary=primary, secondary=secondary,
                 tertiary=_hex_list(tertiary), neutral=neutral, background=background,
                 text=text, title=title or text, gridline=gridline,
                 categorical=_hex_list(palette))


# ── semantic scales ───────────────────────────────────────────────────────────

#: Answers that sit outside an ordered scale; always the tertiary colour.
_OFF_SCALE = ("no opinion", "don't know", "dont know", "do not know",
              "not applicable", "n/a", "unsure", "prefer not to answer",
              "prefer not to say")

SCALE_PRESETS: Dict[str, Dict[str, str]] = {
    "importance": {
        "not at all": "neutral", "slightly": "secondary",
        "moderately": "secondary", "very": "primary", "extremely": "primary"},
    "agreement": {
        "strongly disagree": "neutral", "somewhat disagree": "tertiary",
        "disagree": "tertiary", "neutral": "secondary",
        "neither agree nor disagree": "secondary", "somewhat agree": "primary",
        "agree": "primary", "strongly agree": "primary"},
    "satisfaction": {
        "very dissatisfied": "neutral", "somewhat dissatisfied": "tertiary",
        "dissatisfied": "tertiary", "neutral": "secondary",
        "neither satisfied nor dissatisfied": "secondary",
        "somewhat satisfied": "primary", "satisfied": "primary",
        "very satisfied": "primary"},
    "frequency": {
        "never": "neutral", "rarely": "secondary", "sometimes": "secondary",
        "often": "primary", "always": "primary"},
}


def _role_for(label: str, table: Dict[str, str]) -> Optional[str]:
    low = re.sub(r"\s+", " ", label.strip().lower())
    if low in _OFF_SCALE:
        return "tertiary"
    for key in sorted(table, key=len, reverse=True):
        if low == key or re.match(rf"^{re.escape(key)}\b", low):
            return table[key]
    return None


def detect_scale(categories: Sequence[str]) -> Optional[str]:
    """Name of the preset most of these categories belong to, or None.

    At least three categories and more than half must be recognised by the
    *same* preset, so a nominal question whose answers happen to include "Never"
    is not painted as a scale.
    """
    real = [c for c in categories if c]
    if len(real) < 3:
        return None
    best, best_hits = None, 0
    for name, table in SCALE_PRESETS.items():
        hits = sum(1 for c in real
                   if _role_for(c, table) is not None
                   and re.sub(r"\s+", " ", c.strip().lower()) not in _OFF_SCALE)
        if hits > best_hits:
            best, best_hits = name, hits
    return best if best and best_hits * 2 > len(real) else None


def resolve_scale(categories: Sequence[str], choice: str) -> Optional[str]:
    if choice == "none":
        return None
    if choice in SCALE_PRESETS:
        return choice
    return detect_scale(categories)


def category_colors(categories: Sequence[str], theme: Theme, *,
                    scale: str = "auto",
                    overrides: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """category -> hex, by override, then semantic scale, then palette order."""
    overrides = {k: normalize_hex(v) for k, v in (overrides or {}).items()}
    preset = resolve_scale(categories, scale)
    table = SCALE_PRESETS.get(preset) if preset else None
    colors: Dict[str, str] = {}
    palette_index = 0
    for cat in categories:
        if cat in overrides:
            colors[cat] = overrides[cat]
            continue
        role = _role_for(cat, table) if table else None
        if role:
            colors[cat] = theme.role(role)
        else:
            colors[cat] = theme.series_color(palette_index)
        palette_index += 1
    return colors


def adjacent_duplicates(categories: Sequence[str],
                        colors: Dict[str, str]) -> bool:
    """True when neighbouring categories share a colour (they need a white
    border in a stacked chart, or the segments blur into one)."""
    return any(colors.get(a) == colors.get(b)
               for a, b in zip(categories, categories[1:]))
