"""Widget width in the web app: the new Streamlit argument, the old one on old Streamlit, no deprecation warning."""

from __future__ import annotations

import ast
import logging
from pathlib import Path

import pytest

from app.shared import layout
from tests import webkit

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ["app", "streamlit_app.py", "interview_ui.py"]


def test_new_streamlit_gets_the_new_argument_and_old_streamlit_the_old_one():
    assert layout.stretch("1.61.1") == {"width": "stretch"}
    assert layout.content("1.61.1") == {"width": "content"}
    assert layout.stretch("1.51.0") == {"width": "stretch"}
    assert layout.stretch("1.50.2") == {"use_container_width": True}
    assert layout.content("1.38.0") == {"use_container_width": False}
    assert layout.stretch("2.0.0") == {"width": "stretch"}


def test_odd_version_strings_do_not_break_the_choice():
    assert layout.takes_width("1.60.0.dev0") is True
    assert layout.takes_width("1.51.0rc1") is True
    assert layout.takes_width("1.49") is False


def test_no_web_source_still_uses_the_deprecated_argument():
    """Say it once, in app/shared/layout.py; everywhere else it is stretch() or content()."""
    offenders = []
    for name in SOURCES:
        target = ROOT / name
        for path in ([target] if target.is_file() else sorted(target.rglob("*.py"))):
            if path.name == "layout.py":
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.keyword) and node.arg == "use_container_width":
                    offenders.append(f"{path.relative_to(ROOT)}:{node.value.lineno}")
    assert not offenders, offenders


def test_the_pages_that_draw_tables_charts_and_wide_buttons_raise_no_width_warning(tmp_path, monkeypatch):
    """Streamlit logs 'Please replace use_container_width with width' once per call; none may appear."""
    records = []

    class Catch(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())

    handler = Catch(level=logging.WARNING)
    for name in ("streamlit", "streamlit.deprecation_util"):
        logging.getLogger(name).addHandler(handler)
    try:
        at = webkit.start("")                                          # Home: the wide buttons
        webkit.go(at, "Data Charts")                                    # Charts
        next(b for b in at.button if b.key == "dc_sample").click().run()   # the sample's table
        at.session_state["step_charts"] = "question"
        at.run()
        next(s for s in at.selectbox if str(s.key).endswith("_field")).set_value("Class year").run()   # the chart
        at.session_state["step_charts"] = "save"
        at.run()
        assert not at.exception, at.exception
    finally:
        for name in ("streamlit", "streamlit.deprecation_util"):
            logging.getLogger(name).removeHandler(handler)
    assert not [m for m in records if "use_container_width" in m], records[:3]
