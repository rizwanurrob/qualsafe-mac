"""
The Qt skin, generated from QualSafe's existing palette.

`core/theme.py` is the single source of truth for the app's colours in the
Streamlit build -- it exists because the chrome, the injected CSS, and the Altair
charts had drifted into three copies of "roughly the brand red". This module
keeps that discipline: it reads the same `DARK` / `LIGHT` dictionaries and turns
them into a Qt palette plus a stylesheet, so the desktop app is a fourth *view*
of one palette rather than a fourth copy of it.

Two choices carried over from `core/theme.py` deliberately, because they are
load-bearing rather than decorative:

* **Warnings are amber, not red.** Red is the brand accent here, so a red
  warning stops reading as a warning.
* **On the light skin the accent darkens.** A bright red on white glares and
  fails contrast, so `red_bright` is *deeper* than `red` in the light palette.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QColor, QPalette

from core.theme import (  # noqa: F401 - CATEGORY_* re-exported for this package
    CATEGORY_PALETTES, DEFAULT_CATEGORY_PALETTE, category_colors, get_palette)


def qt_palette(mode: str = "dark") -> QPalette:
    """A `QPalette` built from the skin, so native widgets follow it too."""
    p = get_palette(mode)
    palette = QPalette()
    bg = QColor(p["bg"])
    elevated = QColor(p["bg_elevated"])
    surface = QColor(p["surface"])
    text = QColor(p["text"])
    muted = QColor(p["text_muted"])
    accent = QColor(p["red"])

    palette.setColor(QPalette.ColorRole.Window, bg)
    palette.setColor(QPalette.ColorRole.WindowText, text)
    palette.setColor(QPalette.ColorRole.Base, elevated)
    palette.setColor(QPalette.ColorRole.AlternateBase, surface)
    palette.setColor(QPalette.ColorRole.Text, text)
    palette.setColor(QPalette.ColorRole.Button, surface)
    palette.setColor(QPalette.ColorRole.ButtonText, text)
    palette.setColor(QPalette.ColorRole.Mid, muted)
    palette.setColor(QPalette.ColorRole.PlaceholderText, muted)
    palette.setColor(QPalette.ColorRole.ToolTipBase, surface)
    palette.setColor(QPalette.ColorRole.ToolTipText, text)
    palette.setColor(QPalette.ColorRole.Highlight, accent)
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#FFFFFF"))
    palette.setColor(QPalette.ColorRole.Link, QColor(p["red_bright"]))

    disabled = QPalette.ColorGroup.Disabled
    palette.setColor(disabled, QPalette.ColorRole.Text, muted)
    palette.setColor(disabled, QPalette.ColorRole.ButtonText, muted)
    palette.setColor(disabled, QPalette.ColorRole.WindowText, muted)
    return palette


def _indicator_images(mode: str) -> dict:
    """Tick-box pictures for this skin, drawn once into a cache folder.

    The built-in unticked box is a dark outline on a dark list in the dark skin, so a person
    cannot see where to tick. These have a clear border in the muted text colour and a filled
    box with a white tick when ticked. Returns {} when there is no application to draw with
    (the stylesheet is then built without them)."""
    import tempfile

    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPen, QPixmap

    if QGuiApplication.instance() is None:
        return {}
    p = get_palette(mode)
    folder = Path(tempfile.gettempdir()) / "qualsafe_indicators" / mode
    folder.mkdir(parents=True, exist_ok=True)
    border, fill, base = QColor(p["text_muted"]), QColor(p["red"]), QColor(p["bg_elevated"])
    out = {}
    for name in ("unchecked", "checked", "partial", "radio_off", "radio_on"):
        path = folder / f"{name}.png"
        if not path.exists() and name.startswith("radio"):
            pixmap = QPixmap(32, 32)
            pixmap.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(QPen(fill if name == "radio_on" else border, 3))
            painter.setBrush(base)
            painter.drawEllipse(3, 3, 26, 26)
            if name == "radio_on":
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(fill)
                painter.drawEllipse(10, 10, 12, 12)
            painter.end()
            pixmap.save(str(path))
        elif not path.exists():
            pixmap = QPixmap(32, 32)
            pixmap.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(QPen(fill if name != "unchecked" else border, 3))
            painter.setBrush(fill if name != "unchecked" else base)
            painter.drawRoundedRect(3, 3, 26, 26, 5, 5)
            if name != "unchecked":
                painter.setPen(QPen(QColor("#FFFFFF"), 4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                                    Qt.PenJoinStyle.RoundJoin))
                if name == "checked":
                    painter.drawPolyline([QPointF(8, 17), QPointF(14, 23), QPointF(24, 10)])
                else:
                    painter.drawLine(QPointF(9, 16), QPointF(23, 16))
            painter.end()
            pixmap.save(str(path))
        out[name] = path.as_posix()
    return out


def _indicator_rules(mode: str) -> str:
    images = _indicator_images(mode)
    if not images:
        return ""
    kinds = ("QCheckBox", "QListView", "QTreeView", "QTableView")
    parts = [", ".join(f"{k}::indicator" for k in kinds) + " { width: 16px; height: 16px; }"]
    for state, name in (("unchecked", "unchecked"), ("checked", "checked"), ("indeterminate", "partial")):
        parts.append(", ".join(f"{k}::indicator:{state}" for k in kinds)
                     + f" {{ image: url({images[name]}); }}")
    parts.append("QRadioButton::indicator { width: 16px; height: 16px; }")
    parts.append(f"QRadioButton::indicator:unchecked {{ image: url({images['radio_off']}); }}")
    parts.append(f"QRadioButton::indicator:checked {{ image: url({images['radio_on']}); }}")
    return " ".join(parts)


def stylesheet(mode: str = "dark", *, font_pt: float = 10.5) -> str:
    """Stylesheet for the parts a palette alone cannot reach.

    Kept small on purpose: the palette above does most of the work, and every
    rule here is one more thing that can disagree with `core/theme.py`.
    """
    p = get_palette(mode)
    return f"""
    QWidget {{
        color: {p['text']};
        font-size: {font_pt}pt;
    }}
    QMainWindow, QDialog {{ background: {p['bg']}; }}

    QGroupBox {{
        border: 1px solid {p['border']};
        border-radius: 4px;
        margin-top: 1.2em;
        padding-top: 0.5em;
        background: {p['bg_elevated']};
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 10px;
        padding: 0 4px;
        color: {p['red_bright']};
        font-weight: bold;
    }}

    QPlainTextEdit, QTextEdit {{
        background: {p['bg_elevated']};
        border: 1px solid {p['border']};
        border-radius: 3px;
        padding: 10px 14px;
        selection-background-color: {p['red']};
        selection-color: #FFFFFF;
    }}

    QTableWidget, QListWidget {{
        background: {p['bg_elevated']};
        border: 1px solid {p['border']};
        border-radius: 3px;
        outline: none;
    }}
    QListWidget::item {{ padding: 4px 6px; }}
    QListWidget::item:selected, QTableWidget::item:selected {{
        background: {p['red_deep']};
        color: #FFFFFF;
    }}
    QHeaderView::section {{
        background: {p['surface']};
        color: {p['text_muted']};
        border: none;
        border-bottom: 1px solid {p['border']};
        padding: 5px;
    }}

    QPushButton {{
        background: {p['surface']};
        border: 1px solid {p['border']};
        border-radius: 3px;
        padding: 6px 14px;
    }}
    QPushButton:hover {{ border-color: {p['red']}; }}
    QPushButton:default, QPushButton:focus {{
        border-color: {p['red']};
    }}
    QPushButton:disabled {{ color: {p['text_muted']}; border-color: {p['border']}; }}

    QLineEdit {{
        background: {p['bg_elevated']};
        border: 1px solid {p['border']};
        border-radius: 3px;
        padding: 5px 7px;
    }}
    QLineEdit:focus {{ border-color: {p['red']}; }}

    QMenuBar, QMenu {{ background: {p['bg_elevated']}; }}
    QMenuBar::item:selected, QMenu::item:selected {{ background: {p['red_deep']}; }}
    QStatusBar {{ background: {p['bg_elevated']}; color: {p['text_muted']}; }}
    QSplitter::handle {{ background: {p['border']}; }}
    {_indicator_rules(mode)}
    QToolTip {{
        background: {p['surface']};
        color: {p['text']};
        border: 1px solid {p['border']};
        padding: 4px;
    }}
    QToolButton#infoTip {{
        background: transparent; color: {p['text']}; border: 1px solid {p['text_muted']};
        border-radius: 10px; font-weight: bold; padding: 0;
    }}
    QToolButton#infoTip:hover, QToolButton#infoTip:focus {{
        background: {p['surface']}; border: 2px solid {p['text']};
    }}
    QFrame#tipBox {{
        background: {p['surface']}; color: {p['text']}; border: 1px solid {p['text_muted']};
    }}
    QFrame#tipBox QPushButton[main="true"] {{
        background: {p['red_deep']}; color: #ffffff; text-decoration: none; font-weight: bold;
        border: 2px solid {p['red_deep']}; padding: 4px 16px;
    }}
    QFrame#tipBox QPushButton {{
        background: transparent; color: {p['text']}; border: none; text-decoration: underline;
        padding: 2px 6px;
    }}
    """


def apply_theme(app, mode: str = "dark", *, font_pt: float = 10.5) -> None:
    """Apply the skin, and the base font size, to a whole `QApplication`."""
    from PySide6.QtWidgets import QStyleFactory

    # Fusion is the one built-in style that honours a custom palette on every
    # platform; the native Windows style ignores most of it.
    app.setStyle(QStyleFactory.create("Fusion"))
    app.setPalette(qt_palette(mode))
    app.setStyleSheet(stylesheet(mode, font_pt=font_pt))
    set_active_mode(mode)


# ── categorical palettes for codes ──────────────────────────────────────────
#
# These used to be defined here, because `core/theme.py` shipped only six
# categorical colours and six is wrong for a codebook: a twelve-code project got
# six colours and every code had an identical twin in the reader's margin
# stripes, which is actively misleading in the one place this app asks you to
# trust colour.
#
# That fix has since landed upstream (PORTED_BACK.md §8) with the same names and
# the same values, so the definitions are gone and these are re-exports. Two
# implementations of "what colour is this code" would drift, and the drift would
# be invisible until a project opened in the two builds and looked different.
#
# Callers keep importing them from here — that is the point of a re-export; the
# import itself is at the top of the module with the rest.


# ── semantic colours for view text ──────────────────────────────────────────
#
# The rest of this module exists so the app does not accumulate a second place
# that decides what a colour means. Rich-text labels in the views were quietly
# doing exactly that -- hardcoding the *dark* skin's amber and green, which on
# the light skin are the washed-out, low-contrast values `core/theme.py`
# deliberately darkens. These accessors close that hole: a view asks for
# "warning", never for "#E0A040".

#: The skin every module-level helper reads. Set by `apply_theme`, so a view
#: does not have to thread the mode through every label it builds.
_ACTIVE_MODE = "dark"


def active_mode() -> str:
    return _ACTIVE_MODE


def set_active_mode(mode: str) -> None:
    global _ACTIVE_MODE
    _ACTIVE_MODE = mode if mode in ("dark", "light") else "dark"


def color(role: str, mode: str = "") -> str:
    """A palette colour by name, for the active skin unless `mode` is given.

    Roles are `core/theme.py`'s keys: bg, bg_elevated, surface, border, text,
    text_muted, red, red_bright, red_deep, amber, green.
    """
    palette = get_palette(mode or _ACTIVE_MODE)
    value = palette.get(role)
    return value if isinstance(value, str) else palette["text"]


def warning_color(mode: str = "") -> str:
    """Amber, not red -- red is the brand accent, so a red warning stops
    reading as a warning. Darker on the light skin, where amber on white
    otherwise fails contrast."""
    return color("amber", mode)


def success_color(mode: str = "") -> str:
    return color("green", mode)


def muted_color(mode: str = "") -> str:
    return color("text_muted", mode)


def span(text: str, role: str, *, bold: bool = False, mode: str = "") -> str:
    """Rich text in a palette colour. The only way a view should colour text."""
    body = f"<b>{text}</b>" if bold else text
    return f"<span style='color:{color(role, mode)}'>{body}</span>"


#: Status is shown with an icon and a word, never by colour alone. The same in
#: every activity. (Update 3, design rule 6.)
STATUS_ICON = {"success": "✓", "warning": "⚠", "error": "✖", "note": "ⓘ"}
STATUS_WORD = {"success": "Done", "warning": "Warning", "error": "Problem", "note": "Note"}
#: The ordinary text font has none of these marks, so they are drawn from a symbol font.
SYMBOL_FONTS = ["Segoe UI Symbol", "Apple Symbols", "DejaVu Sans"]


def icon_html(kind: str) -> str:
    """The mark for a status as rich text, in a font that has it."""
    families = ", ".join(f"'{f}'" for f in SYMBOL_FONTS)
    return f"<span style=\"font-family:{families}\">{STATUS_ICON.get(kind, '')}</span>"


def warning_span(text: str, *, bold: bool = True, mode: str = "", icon: bool = True) -> str:
    return span((icon_html("warning") + " " if icon else "") + text, "amber", bold=bold, mode=mode)


def success_span(text: str, *, bold: bool = False, mode: str = "", icon: bool = True) -> str:
    return span((icon_html("success") + " " if icon else "") + text, "green", bold=bold, mode=mode)


def error_span(text: str, *, bold: bool = True, mode: str = "", icon: bool = True) -> str:
    return span((icon_html("error") + " " if icon else "") + text, "red_bright", bold=bold, mode=mode)


def muted_span(text: str, *, mode: str = "") -> str:
    return span(text, "text_muted", mode=mode)


#: Banner ground and text colour per kind. A warning is amber and an error is red:
#: neither is ever green (the Modelling screen once showed errors on green).
_BANNER = {"warning": ("amber", "bg"), "error": ("red_bright", "bg"), "success": ("green", "bg"),
           "note": ("surface", "text")}


def banner_style(kind: str = "warning", mode: str = "") -> str:
    """Inline style for a filled callout banner."""
    ground, ink = _BANNER.get(kind, _BANNER["warning"])
    return (f"background:{color(ground, mode)};color:{color(ink, mode)};"
            "padding:6px;border-radius:3px;")


def banner_text(kind: str, html: str) -> str:
    """Banner text that starts with the icon and the word for its kind."""
    return f"{icon_html(kind)} <b>{STATUS_WORD.get(kind, '')}:</b> {html}"


def activity_stylesheet(mode: str = "dark") -> str:
    """Activity colours: Home cards and the filled main button of each activity.

    Widgets opt in with the dynamic property `activity` ("surveys", "charts",
    "interviews"); anything without it keeps the app's red. The colour says where
    you are. It is never used for chart data or for status.
    """
    from core.ux import activities

    p = get_palette(mode)
    parts = []
    for act in activities.ACTIVITIES:
        accent, on = p[act.colour_token], p[act.colour_token + ".on"]
        parts.append(f"""
    QFrame#activityCard[activity="{act.key}"] {{
        background: {p['surface']}; border: 1px solid {p['border']};
        border-top: 6px solid {accent};
    }}
    QFrame#activityCard[activity="{act.key}"] QLabel#activityTitle {{ color: {accent}; }}
    QPushButton[activity="{act.key}"] {{
        background: {accent}; color: {on}; border: 2px solid {accent}; font-weight: bold;
    }}
    QPushButton[activity="{act.key}"]:hover {{ border-color: {on}; }}
    QPushButton[activity="{act.key}"]:focus {{ border: 2px solid {p['text']}; }}""")
    return "\n".join(parts)


def _mix(foreground: str, background: str, share: float) -> str:
    """`share` of `foreground` over `background`, as #RRGGBB."""
    f = [int(foreground.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)]
    b = [int(background.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)]
    return "#" + "".join(f"{round(x * share + y * (1 - share)):02X}" for x, y in zip(f, b))


def activity_tints(activity_key: str, mode: str = "dark") -> dict:
    """Soft versions of an activity's colour, for the surfaces of its steps and tabs.

    The accent itself is for the current step and the marks; these tints keep the
    rest of the rail and the tab row visibly in the same colour without shouting.
    Text on them (the accent, or normal text) is checked at 4.5:1 in
    `tests/test_ux_colours.py`.
    """
    from core.ux import activities

    p = get_palette(mode)
    accent = p[activities.get(activity_key).colour_token]
    light = mode == "light"
    return {
        "step": _mix(accent, p["surface"], 0.12 if light else 0.20),
        "step_hover": _mix(accent, p["surface"], 0.22 if light else 0.32),
        "tab": _mix(accent, p["bg"], 0.10 if light else 0.16),
        "rail": _mix(accent, p["bg"], 0.07 if light else 0.11),
        "edge": _mix(accent, p["border"], 0.55),
    }


def activity_shell_stylesheet(activity_key: str, mode: str = "dark") -> str:
    """Colour for everything inside one activity: the step rail, the main button,
    the selected tab's underline and the focus rings.

    Set on the activity container, so it reaches its descendants and nothing
    else. A button is the screen's one main action when it has the dynamic
    property `main` set to True; it is the only filled button.
    """
    from core.ux import activities

    p = get_palette(mode)
    act = activities.get(activity_key)
    accent, on = p[act.colour_token], p[act.colour_token + ".on"]
    tint = activity_tints(activity_key, mode)
    return f"""
    QWidget#stepRail {{ background: {tint['rail']}; }}
    QPushButton[main="true"] {{
        background: {accent}; color: {on}; border: 2px solid {accent}; font-weight: bold;
    }}
    QPushButton[main="true"]:hover {{ border-color: {p['text']}; }}
    QPushButton[main="true"]:focus {{ border: 2px solid {p['text']}; }}
    QPushButton[main="true"]:disabled {{
        background: {p['surface']}; color: {p['text_muted']}; border: 2px solid {p['border']};
    }}
    QPushButton:hover, QPushButton:default, QPushButton:focus {{ border-color: {accent}; }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
        border-color: {accent};
    }}

    QPushButton#stepButton {{
        padding: 6px 16px; background: {tint['step']}; color: {p['text']};
        border: 1px solid {accent};
    }}
    QPushButton#stepButton:hover {{ background: {tint['step_hover']}; }}
    QPushButton#stepButton:checked {{
        background: {accent}; color: {on}; border: 2px solid {accent};
    }}

    QPushButton#stepHelp {{
        background: transparent; color: {p['text']}; border: none;
        padding: 4px 8px; text-decoration: underline;
    }}
    QPushButton#stepHelp:hover, QPushButton#stepHelp:focus {{
        border: none; background: {tint['step_hover']};
    }}

    QGroupBox::title {{ color: {p['text']}; }}

    QTabBar::tab {{
        background: {tint['tab']}; color: {p['text']};
        border: 1px solid {tint['edge']}; border-bottom: none;
        padding: 6px 14px; margin-right: 2px;
    }}
    QTabBar::tab:selected {{
        background: {p['surface']}; color: {accent};
        border-bottom: 4px solid {accent}; font-weight: bold;
    }}
    QTabBar::tab:hover:!selected {{ background: {tint['step']}; }}
    """


def activity_topbar_stylesheet(activity_key: str, mode: str = "dark") -> str:
    """The top bar as a band in the activity colour, with its text and buttons
    in the colour made for it (checked at 4.5:1 in `tests/test_ux_colours.py`)."""
    from core.ux import activities

    p = get_palette(mode)
    act = activities.get(activity_key)
    accent, on = p[act.colour_token], p[act.colour_token + ".on"]
    return f"""
    QFrame#topBar {{ background: {accent}; }}
    QFrame#topBar QLabel#breadcrumb {{ color: {on}; }}
    QFrame#topBar QPushButton {{
        background: transparent; color: {on}; border: 1px solid {on};
    }}
    QFrame#topBar QPushButton:hover, QFrame#topBar QPushButton:focus {{
        border: 2px solid {on};
    }}
    """
