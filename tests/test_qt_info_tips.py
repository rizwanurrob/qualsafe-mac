"""The small (i) beside non-obvious controls: shown, accessible, not counted as a control."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QComboBox, QWidget

from core.ux.help import tips
from qualsafe_qt.widgets import info_tip
from qualsafe_qt.widgets.info_tip import InfoTip
from qualsafe_qt.widgets.more_options import MoreOptions, count_controls, visible_controls


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_a_row_with_a_tip_gets_an_i_beside_its_label(app):
    panel = MoreOptions("More options")
    panel.add_row("Layout", QComboBox())
    panel.add_row("Name of something with no tip", QComboBox())
    found = panel.findChildren(InfoTip)
    assert len(found) == 1
    assert found[0].toolTip() == tips.TIPS["survey.layout"].text
    assert found[0].accessibleName() == "About Layout"


def test_a_tip_id_can_be_given_when_the_label_is_ambiguous(app):
    panel = MoreOptions("More options")
    panel.add_row("Method", QComboBox(), tip="model.method")
    assert panel.findChildren(InfoTip)[0].tip_id == "model.method"


def test_the_i_is_help_and_does_not_count_against_the_seven_controls(app):
    panel = MoreOptions("More options")
    panel.add_row("Layout", QComboBox())
    panel.set_expanded(True)
    holder = QWidget()
    from PySide6.QtWidgets import QVBoxLayout
    QVBoxLayout(holder).addWidget(panel)
    holder.show()
    app.processEvents()
    assert len(holder.findChildren(InfoTip)) == 1
    # the "More options" button and the combo; not the (i)
    assert count_controls(holder) == 2
    assert len(visible_controls(holder)) == 2
    assert not any(isinstance(w, InfoTip) for w in visible_controls(holder))


def test_clicking_the_i_opens_the_box_and_more_opens_the_article(app):
    opened = []
    info_tip.set_article_opener(opened.append)
    try:
        host = QWidget()
        tip = InfoTip("code.method", about="Method", parent=host)
        host.show()
        tip.click()
        assert tip.box is not None and tip.box.label.text() == tips.TIPS["code.method"].text
        tip.box.more.click()
        assert opened == ["surveys-code"]
    finally:
        info_tip.set_article_opener(None)


def test_an_unknown_tip_is_an_error_not_a_blank_button(app):
    with pytest.raises(KeyError):
        InfoTip("nope")


def test_the_main_window_sends_more_to_the_right_step_article(app):
    from qualsafe_qt.windows.main_window import MainWindow

    win = MainWindow()
    win.resize(1200, 800)
    win.show()
    app.processEvents()
    try:
        win.open_activity("surveys", "load")
        tip = next(t for t in win.findChildren(InfoTip) if t.tip_id == "survey.layout")
        win.activity.show_step("surveys", "load")
        tip.show_tip()
        tip.box.more.click()
        assert win.pages.currentWidget() is win.help
        assert win.help.body.toPlainText().startswith("Surveys, step 1: Load your answers")
    finally:
        win.close()
