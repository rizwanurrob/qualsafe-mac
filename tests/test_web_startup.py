"""Start-up: the web app must not load the analysis engine before it is needed.

scikit-learn and SciPy cost the app more than half of its start-up time (about 25 s to 12 s measured
on a warm machine, minutes on a cold one), and nothing on Home, Settings or the Load step uses them.
They load when a run is pressed or Explore is opened. This runs in a fresh process, because the
test process has long since imported them.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

HEAVY = ("sklearn", "scipy", "torch", "transformers", "sentence_transformers", "analyze_survey",
         "iterative_supervised_thematic")


def _run(code: str) -> str:
    prelude = f"import sys; sys.path.insert(0, {str(ROOT)!r})\n"
    done = subprocess.run([sys.executable, "-c", prelude + textwrap.dedent(code)], cwd=str(ROOT),
                          capture_output=True, text=True, timeout=300,
                          env={**__import__("os").environ, "QUALSAFE_NO_TOUR": "1"})
    assert done.returncode == 0, done.stderr[-800:]
    return done.stdout


def test_importing_the_app_loads_none_of_the_heavy_engine():
    out = _run(f"""
        import sys
        import streamlit_app
        print("LOADED", [m for m in {HEAVY!r} if m in sys.modules])
    """)
    assert "LOADED []" in out, out


def test_drawing_home_and_the_load_step_loads_none_of_it_either():
    out = _run(f"""
        import os, sys, tempfile
        os.environ["QNW_SETTINGS_DIR"] = tempfile.mkdtemp()
        from streamlit.testing.v1 import AppTest
        at = AppTest.from_file(r"{ROOT / 'streamlit_app.py'}", default_timeout=300)
        at.run()
        at.session_state["view"], at.session_state["activity"] = "activity", "surveys"
        at.run()
        assert not at.exception
        print("LOADED", [m for m in {HEAVY!r} if m in sys.modules])
    """)
    assert "LOADED []" in out, out


def test_the_image_renderer_warms_once_in_the_background_and_never_raises(monkeypatch):
    """The first chart used to take about 11 s (the renderer starting up); it warms while Home shows."""
    from core.chartbuilder import export

    monkeypatch.setitem(export._WARMING, "thread", None)
    calls = []
    monkeypatch.setattr(export, "image_export_available", lambda: True)

    class Fake:
        def vegalite_to_png(self, text, scale=1):
            calls.append(text)
            raise RuntimeError("a broken renderer must not matter")

    monkeypatch.setattr(export, "_vlc", lambda: Fake())
    thread = export.warm_renderer()
    assert thread is not None and thread.daemon
    thread.join(5)
    assert len(calls) == 1
    assert export.warm_renderer() is None                       # once per process
    assert len(calls) == 1


def test_warming_does_nothing_when_the_renderer_is_not_installed(monkeypatch):
    from core.chartbuilder import export

    monkeypatch.setitem(export._WARMING, "thread", None)
    monkeypatch.setattr(export, "image_export_available", lambda: False)
    assert export.warm_renderer() is None
