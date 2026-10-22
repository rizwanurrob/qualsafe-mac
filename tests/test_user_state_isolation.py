"""The test suite must never touch the state of the person running it (F8).

`tests/conftest.py` redirects settings, the app's settings folder and the home
folder for every test. These tests prove the redirect holds -- including for
the one constructor that silently ignored it (`QSettings(org, app)` is always
the native store) -- by reading the real locations, never writing them.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest


def test_home_and_settings_folder_are_temporary(tmp_path_factory):
    temp_root = Path(tmp_path_factory.getbasetemp()).resolve()
    assert temp_root in Path.home().resolve().parents
    assert temp_root in Path(os.environ["QNW_SETTINGS_DIR"]).resolve().parents


def test_core_settings_write_lands_in_the_temp_folder(tmp_path_factory):
    from core import app_settings

    written = Path(app_settings.save_app_settings({"theme_mode": "light"})).resolve()
    assert Path(tmp_path_factory.getbasetemp()).resolve() in written.parents


def test_a_desktop_window_leaves_the_installed_apps_settings_alone(tmp_path):
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication

    import qualsafe_qt.windows.main_window as module

    QApplication.instance() or QApplication([])
    # The installed app's store, opened the way it always resolved: natively.
    real = QSettings(QSettings.Format.NativeFormat, QSettings.Scope.UserScope,
                     "QualSafe", "QualSafe Desktop")
    before = {k: real.value(k) for k in real.allKeys()}

    window = module.MainWindow()
    try:
        window._settings.setValue("last_project_path", str(tmp_path / "fixture.qnw"))
        window._settings.sync()
        assert window._settings.format() == QSettings.Format.IniFormat
    finally:
        window.close()

    real.sync()
    assert {k: real.value(k) for k in real.allKeys()} == before, (
        "a test wrote into the installed desktop app's settings")


def test_the_shipped_app_still_uses_the_native_store():
    """Outside the test redirect, `open_settings` must be exactly what the app
    always used, or every user would lose their preferences on upgrade."""
    pytest.importorskip("PySide6")
    from PySide6.QtCore import QSettings

    import qualsafe_qt.windows.main_window as module

    saved = QSettings.defaultFormat()
    QSettings.setDefaultFormat(QSettings.Format.NativeFormat)
    try:
        settings = module.open_settings()
        legacy = QSettings(module.ORGANIZATION, module.APPLICATION)
        assert settings.format() == QSettings.Format.NativeFormat
        assert settings.fileName() == legacy.fileName()
    finally:
        QSettings.setDefaultFormat(saved)
