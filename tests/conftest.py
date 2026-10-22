"""
Shared pytest fixtures: no test may touch the person running it.

Found in the 2026-09-25 review (F8): with no conftest, the desktop tests built
`MainWindow`, which reads and writes `QSettings("QualSafe", "QualSafe Desktop")`
-- the *installed* app's own settings. A developer's desktop app was left set
to reopen a pytest sample project, and because each test inherited whatever the
previous one left there, the full suite hung in an order-dependent way while
every file passed on its own.

So every test gets, fresh and empty:

* Qt settings -- INI format under a temp folder, never the registry;
* the app's settings folder (`QNW_SETTINGS_DIR`), which also covers label
  packs, workspaces and saved Data Charts;
* a home folder, which covers `~/.qualsafe` (samples, the Laya environment).

The Hugging Face cache is pinned to where it really is before home moves, so a
test that asks "is this model downloaded?" gets the same answer it always did.
Tests that need something else set it themselves; theirs wins, because their
monkeypatch runs after this one.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

_REAL_HF_HOME = os.environ.get("HF_HOME") or str(Path.home() / ".cache" / "huggingface")


@pytest.fixture(autouse=True)
def _isolate_user_state(tmp_path_factory, monkeypatch):
    base = tmp_path_factory.mktemp("user_state")
    home = base / "home"
    home.mkdir()

    monkeypatch.setenv("HF_HOME", _REAL_HF_HOME)
    monkeypatch.setenv("QNW_SETTINGS_DIR", str(base / "settings"))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("APPDATA", str(base / "appdata"))
    # The first-visit tour covers the window; tests that want it clear this themselves.
    monkeypatch.setenv("QUALSAFE_NO_TOUR", "1")
    _isolate_web_folders(monkeypatch, base)

    try:
        from PySide6.QtCore import QSettings
    except ImportError:
        yield
        return

    qsettings_dir = str(base / "qsettings")
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    for scope in (QSettings.Scope.UserScope, QSettings.Scope.SystemScope):
        QSettings.setPath(QSettings.Format.IniFormat, scope, qsettings_dir)
    yield
    _destroy_leftover_widgets()


def _isolate_web_folders(monkeypatch, base) -> None:
    """The web app's output, input and download folders live under the program folder.

    Until phase 4b they pointed inside `app/shared` by mistake, so a run a test made, or one a
    developer made by hand, could never be found by another test. Now that they are where the docs
    say, a project left in the real `output_streamlit` would be picked up as "the active project" by
    an unrelated test. So each test gets empty ones, in every module that already holds the value and
    in the constants module itself for any module imported later.
    """
    import sys

    try:
        from app.shared import constants
    except Exception:  # noqa: BLE001 - the web app is not importable in every environment
        return
    for name in ("STREAMLIT_OUTPUT_DIR", "SESSION_INPUT_DIR", "PUBLIC_DATA_DIR"):
        real = getattr(constants, name, None)
        if real is None:
            continue
        fresh = base / "web" / name.lower()
        # Every web module that holds the name, whatever it holds now: one first imported during an
        # earlier test captured that test's folder, not the real one.
        for module_name, module in list(sys.modules.items()):
            if (module_name.startswith("app") or module_name == "interview_ui") and hasattr(module, name):
                monkeypatch.setattr(module, name, fresh)
        monkeypatch.setattr(constants, name, fresh)


def _destroy_leftover_widgets() -> None:
    """Delete every top-level widget a test left behind.

    This is what the "order-dependent hang" was. Nothing deleted the windows
    tests built, and `QApplication.setStyleSheet` (which every `MainWindow`
    calls while restoring its appearance) re-polishes *every* widget still
    alive. Measured offscreen: re-theming took 3.7 s with one window alive,
    9 s with two, 28 s with four and 129 s with eight, each window bringing 74
    top-level widgets. Two thousand tests in, a new window took minutes and the
    suite looked hung, at whichever test happened to be next.
    """
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        return
    for widget in app.topLevelWidgets():
        widget.close()
        widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
