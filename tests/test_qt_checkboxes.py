"""Tick boxes you can see, in both skins (the built-in unticked box vanished in the dark one)."""

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from core import theme as core_theme
from qualsafe_qt import theme
from tests.test_ux_colours import contrast


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.mark.parametrize("mode", ["light", "dark"])
def test_the_pictures_exist_and_the_stylesheet_uses_them_for_every_kind_of_tick_box(app, mode):
    images = theme._indicator_images(mode)
    assert set(images) == {"unchecked", "checked", "partial", "radio_off", "radio_on"} and all(Path(p).is_file() for p in images.values())
    css = theme.stylesheet(mode)
    for kind in ("QCheckBox", "QListView", "QTreeView", "QTableView"):
        for state in ("unchecked", "checked", "indeterminate"):
            assert f"{kind}::indicator:{state}" in css
    assert "QRadioButton::indicator:checked" in css and "QRadioButton::indicator:unchecked" in css
    assert all(p in css for p in images.values())


@pytest.mark.parametrize("mode", ["light", "dark"])
def test_an_unticked_box_has_a_border_that_can_be_seen_on_the_page(mode):
    p = core_theme.get_palette(mode)
    assert contrast(p["text_muted"], p["bg_elevated"]) >= 3.0           # non-text contrast (WCAG 1.4.11)
    assert contrast(p["red"], p["bg_elevated"]) >= 3.0                  # the filled box, ticked


@pytest.mark.parametrize("mode", ["light", "dark"])
def test_the_ticked_box_is_not_the_same_picture_as_the_empty_one(app, mode):
    images = theme._indicator_images(mode)
    empty, ticked = QImage(images["unchecked"]), QImage(images["checked"])
    assert not empty.isNull() and empty != ticked


def test_without_an_application_the_stylesheet_is_built_without_the_pictures(monkeypatch):
    from PySide6.QtGui import QGuiApplication
    monkeypatch.setattr(QGuiApplication, "instance", staticmethod(lambda: None))
    assert theme._indicator_images("dark") == {} and "::indicator" not in theme.stylesheet("dark")
