"""The first-visit tour on the desktop: once, skippable, and available again from Help."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from qualsafe_qt.widgets.tour import TourOverlay
from qualsafe_qt.windows.main_window import MainWindow


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def window(app, monkeypatch):
    monkeypatch.delenv("QUALSAFE_NO_TOUR", raising=False)
    win = MainWindow()
    win.resize(1300, 850)
    win.show()
    app.processEvents()
    yield win
    win.close()


def _go(win, app, key):
    win.open_activity(key)
    app.processEvents()
    app.processEvents()                       # the tour starts on the next turn of the event loop


def test_the_first_visit_shows_the_tour_with_the_first_card_lit_on_the_step_row(window, app):
    _go(window, app, "surveys")
    tour = window._tour
    assert isinstance(tour, TourOverlay) and tour.isVisible()
    assert tour.title.text() == "Surveys has 5 steps"
    assert tour.counter.text() == "1 of 4"
    assert tour.target_widget() is window.activity.rail
    assert tour.next_button.text() == "Next" and tour.back_button.isHidden()


def test_next_walks_the_cards_and_each_points_at_a_real_control_where_there_is_one(window, app):
    _go(window, app, "surveys")
    tour = window._tour
    window.activity.show_step("surveys", "load")
    seen = []
    for _ in range(4):
        seen.append((tour.current().target, tour.target_widget()))
        if tour.next_button.text() == "Done":
            break
        tour.next_button.click()
    assert [t for t, _w in seen] == ["rail", "main", "more", "help"]
    assert all(w is not None for _t, w in seen)
    assert seen[3][1] is window.activity.step_help
    assert seen[1][1].property("main") is True


def test_finishing_remembers_it_and_it_does_not_come_back(window, app):
    _go(window, app, "charts")
    while window._tour is not None and window._tour.next_button.text() != "Done":
        window._tour.next_button.click()
    window._tour.next_button.click()                    # Done
    app.processEvents()
    assert window._tour is None
    assert window._tours_seen == {"charts"}
    assert window._settings.value("tours_seen") == '["charts"]'
    _go(window, app, "charts")                          # back again: nothing shows
    assert window._tour is None
    _go(window, app, "interviews")                      # a different activity still gets its own
    assert window._tour is not None and window._tour.activity_key == "interviews"


def test_skipping_counts_as_seen_and_escape_skips(window, app):
    _go(window, app, "surveys")
    window._tour.skip_button.click()
    app.processEvents()
    assert window._tour is None and "surveys" in window._tours_seen

    _go(window, app, "interviews")
    QTest.keyClick(window._tour, Qt.Key.Key_Escape)
    app.processEvents()
    assert window._tour is None and "interviews" in window._tours_seen


def test_a_second_visit_does_not_show_it_again(window, app):
    _go(window, app, "surveys")
    window._tour.skip_button.click()
    app.processEvents()
    _go(window, app, "surveys")
    assert window._tour is None


def test_help_can_take_the_tour_again(window, app):
    _go(window, app, "surveys")
    window._tour.skip_button.click()
    app.processEvents()
    window.open_help()
    assert set(window.help.tour_buttons) == {"surveys", "charts", "interviews"}
    window.help.tour_buttons["surveys"].click()
    app.processEvents()
    app.processEvents()
    assert window.pages.currentWidget() is window.activity
    assert window._tour is not None and window._tour.activity_key == "surveys"


def test_a_tour_never_opens_over_a_different_page(window, app):
    window.open_activity("surveys")
    window.open_help()                                   # went elsewhere before the tour started
    app.processEvents()
    app.processEvents()
    assert window._tour is None


def test_the_saved_setting_holds_activity_names_only(window, app):
    from qualsafe_qt.windows import main_window

    assert "tours_seen" in main_window._PERSISTED_KEYS
    _go(window, app, "surveys")
    window._tour.skip_button.click()
    app.processEvents()
    assert window._settings.value("tours_seen") == '["surveys"]'
