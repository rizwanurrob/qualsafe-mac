"""The desktop Help: an article per step, and a button on each step that opens it."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from core.ux import help as shared_help
from qualsafe_qt.views import help_view
from qualsafe_qt.windows.main_window import MainWindow


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_the_guide_lists_every_step_article_after_the_walkthroughs():
    titles = [t for t, _b in help_view.HELP_SECTIONS]
    for activity_key, step_key in shared_help.steps():
        assert help_view.step_section_title(activity_key, step_key) in titles
    assert titles[0].startswith("Start here")
    assert titles[1] == help_view.STEP_SECTIONS[0][0]


def test_the_exported_guide_includes_the_step_articles():
    guide = help_view.full_guide()
    for activity_key, step_key in shared_help.steps():
        assert shared_help.title_of(shared_help.article(activity_key, step_key)) in guide


def test_the_step_button_opens_the_article_for_that_step(app):
    win = MainWindow()
    win.resize(1200, 800)
    win.show()
    app.processEvents()
    try:
        win.home.start_buttons["surveys"].click()
        win.activity.show_step("surveys", "code")
        assert win.activity.step_help.text() == "Help for this step"
        win.activity.step_help.click()
        assert win.pages.currentWidget() is win.help
        shown = win.help.body.toPlainText()
        assert shown.startswith("Surveys, step 3: Code the answers")

        # A filter typed earlier must not hide the article.
        win.help.filter_edit.setText("kappa")
        win.open_help_for_step("charts", "save")
        assert win.help.filter_edit.text() == ""
        assert win.help.body.toPlainText().startswith("Charts, step 4: Save")

        # No article: the general guide still opens, nothing breaks.
        assert win.help.show_step("surveys", "no-such-step") is False
    finally:
        win.close()


def test_the_guide_has_the_task_articles_the_glossary_and_one_troubleshooting():
    titles = [t for t, _b in help_view.HELP_SECTIONS]
    for task_id in shared_help.task_ids():
        assert shared_help.title_of(shared_help.task(task_id)) in titles
    assert "Glossary" in titles
    assert titles.count("Troubleshooting") == 1
    body = dict(help_view.HELP_SECTIONS)["Troubleshooting"]
    assert body == shared_help.troubleshooting()


def test_filtering_the_guide_finds_a_task_by_a_word_in_it(app):
    view = help_view.HelpView()
    view.filter_edit.setText("two groups")
    shown = [view.contents.item(i).text() for i in range(view.contents.count())]
    assert any(t.startswith("How do I compare two groups") for t in shown)
