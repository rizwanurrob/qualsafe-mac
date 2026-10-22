"""
Shell smoke: the app starts, and the offline guarantee is armed when it does.

The Qt counterpart of `tests/test_app_smoke.py`. Two things it is worth failing
a build over:

1. **The shell constructs and shows without raising** -- the wiring check that
   plain module import cannot give you (missing signals, renamed widgets, a view
   that needs a project before one is open).
2. **`enforce_local_mode()` really ran, first.** Invariant #1 is an ordering
   claim: the flags must be set before `transformers` is imported, because that
   library reads the environment at import time. A test that merely calls the
   function proves nothing about ordering, so this launches a **subprocess with
   the offline variables deliberately cleared** and checks the entry point sets
   them itself.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("PySide6", reason="Qt front end not installed")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent

#: The variables `core.offline.enforce_local_mode` is responsible for.
OFFLINE_VARS = ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE",
                "HF_HUB_DISABLE_TELEMETRY", "HF_HUB_DISABLE_IMPLICIT_TOKEN")


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_the_shell_builds_and_shows_with_no_project(qapp):
    """A cold start with nothing open must render, not raise."""

    import qualsafe_qt.windows.main_window as module

    module.open_settings().clear()

    window = module.MainWindow()
    try:
        window.show()
        qapp.processEvents()
        assert window.documents is not None
        # The empty state is a real state: no project, no crash, no document.
        assert not window._service.is_open
        assert window.documents.library.rowCount() == 0
        assert not window.documents.apply_button.isEnabled()
    finally:
        window.close()


def test_the_status_bar_reports_the_real_offline_state(qapp):
    """The indicator must read the environment, not assume the intention.

    A hard-coded "Offline: on" label would be worse than no label -- it would
    make an unverified claim to an auditor.
    """
    import qualsafe_qt.windows.main_window as module

    window = module.MainWindow()
    try:
        from core.offline import is_offline_enforced

        text = window._offline_label.text()
        assert ("on" in text) == is_offline_enforced()
    finally:
        window.close()


def test_entry_point_arms_offline_mode_from_a_clean_environment():
    """The ordering claim, tested by running the real entry point.

    The subprocess starts with every offline variable removed, so a pass means
    `qualsafe_qt.main` set them itself before anything could import the HF
    stack -- not that the developer's shell happened to have them.
    """
    script = (
        "import sys\n"
        # If this fails, something imported the HF stack before main.py ran.
        "assert 'transformers' not in sys.modules\n"
        "import qualsafe_qt.main\n"
        "from core.offline import is_offline_enforced, local_mode_status\n"
        "assert is_offline_enforced(), local_mode_status()\n"
        "assert all(v == '1' for v in local_mode_status().values()), local_mode_status()\n"
        "print('ok')\n"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT)
    env["QT_QPA_PLATFORM"] = "offscreen"
    for var in OFFLINE_VARS:
        env.pop(var, None)

    result = subprocess.run(
        [sys.executable, "-c", script], env=env, cwd=str(REPO_ROOT),
        capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, (
        f"entry point did not arm offline mode\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr[-1500:]}")
    assert "ok" in result.stdout


def test_preferences_written_to_disk_are_only_the_whitelist(qapp):
    """Invariant #9: persistence is a whitelist of preferences.

    Nothing derived from a response, a document, or a code may be written to
    `QSettings` -- the same rule `core/app_settings.py` enforces upstream.
    """

    import qualsafe_qt.windows.main_window as module

    settings = module.open_settings()
    settings.clear()

    window = module.MainWindow()
    try:
        window._service.set_analyst_name("Analyst")
        window._apply_theme("light")
        window.close()
    finally:
        pass

    written = set(module.open_settings().allKeys())
    assert written <= set(module._PERSISTED_KEYS), (
        f"unexpected keys persisted: {sorted(written - set(module._PERSISTED_KEYS))}")
