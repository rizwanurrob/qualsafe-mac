"""Helpers for testing the web app's steps (phase 4b): open a page, count what a person sees.

`visible_controls` is the web counterpart of the desktop's `visible_controls()`: the controls on
a screen outside a closed "More options" fold. The fold is a Streamlit expander, so the count
skips expanders. Update 3's rule is at most seven.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any, List

APP_PATH = Path(__file__).resolve().parents[1] / "streamlit_app.py"

#: AppTest element types that are controls a person can act on.
CONTROL_TYPES = {
    "button", "checkbox", "selectbox", "radio", "multiselect", "text_input", "text_area",
    "number_input", "slider", "file_uploader", "date_input", "toggle", "select_slider",
    "segmented_control", "pills", "download_button", "link_button",
}
MAX_VISIBLE_CONTROLS = 7
#: Keys of tick boxes that are the rows of one list (a sentence to code), not separate controls:
#: the desktop counts a list as one control too.
LIST_ITEM_PREFIXES = ("cu_",)


def start(mode: str = "survey"):
    """The app, in its own settings folder, opened in an activity (older tests call this a mode)."""
    from streamlit.testing.v1 import AppTest

    os.environ["QNW_SETTINGS_DIR"] = tempfile.mkdtemp()
    at = AppTest.from_file(str(APP_PATH), default_timeout=180)
    if mode:
        at.session_state["app_mode"] = mode
    at.run()
    assert not at.exception, at.exception
    return at


def go(at, page: str):
    """Open a page by name, the way every Continue button in the app does."""
    at.session_state["nav_target"] = page
    at.run()
    assert not at.exception, at.exception
    return at


def _walk(block, skip_expanders: bool, tab: int = 0) -> List[Any]:
    """Controls under `block`. A person sees one tab at a time, so only tab number `tab` of each set
    of tabs is counted (the first by default); `all_controls` counts every tab."""
    found: List[Any] = []
    for child in block.children.values():
        kind = getattr(child, "type", None)
        if hasattr(child, "children"):
            if kind == "expander" and skip_expanders:
                continue
            if kind == "tab_container" and skip_expanders:
                tabs = list(child.children.values())
                if tab < len(tabs):
                    found.extend(_walk(tabs[tab], skip_expanders, tab))
                continue
            found.extend(_walk(child, skip_expanders, tab))
        elif kind in CONTROL_TYPES and not str(getattr(child, "key", "") or "").startswith(LIST_ITEM_PREFIXES):
            found.append(child)
    return found


def visible_controls(at, tab: int = 0) -> List[Any]:
    """The controls in the main area outside any "More options" fold, for tab number `tab`."""
    return _walk(at.main, skip_expanders=True, tab=tab)


def all_controls(at) -> List[Any]:
    """Every control in the main area, folds included."""
    return _walk(at.main, skip_expanders=False)


def primary_buttons(at) -> List[Any]:
    """The filled buttons on the screen: the one main action (Streamlit calls it primary)."""
    return [b for b in visible_controls(at)
            if getattr(b, "type", None) == "button" and getattr(b.proto, "type", "") == "primary"]


def describe(controls) -> List[str]:
    return [f"{getattr(c, 'type', '?')}:{getattr(c, 'key', None) or getattr(c, 'label', '')}" for c in controls]
