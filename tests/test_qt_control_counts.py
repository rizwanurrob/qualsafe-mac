"""No screen shows more than seven controls before its More options (Update 3, design rule 2).

One pass over every step, every screen the step shows and every tab inside a screen, with the
sample project open so the screens have something in them. `OVER_FOR_NOW` is the list of
screens that are still over, with the count they are allowed; it can only shrink. A screen on
the list that gets down to seven has to be taken off it.
"""

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QTabWidget

from core.sample_project import build_sample_project
from core.ux import activities
from qualsafe_qt.widgets.more_options import MAX_VISIBLE_CONTROLS, visible_controls
from qualsafe_qt.windows.main_window import MainWindow

SAMPLE = Path(__file__).resolve().parents[1] / "data" / "sample_survey_education.csv"

#: (screen, tab) -> the most controls it may show for now. Empty: every screen is at seven or fewer.
OVER_FOR_NOW: dict = {}


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_no_screen_shows_more_than_seven_controls_before_more_options(app, tmp_path):
    win = MainWindow()
    win.resize(1440, 900)
    win.show()
    sample = tmp_path / "sample.qnw"
    build_sample_project(SAMPLE, sample)
    win._service.open(sample)
    app.processEvents()

    counts = {}
    for act in activities.ACTIVITIES:
        for step in act.steps:
            win.open_activity(act.key, step.key)
            app.processEvents()
            names = (list(step.screens.get(activities.DESKTOP, ()))
                     + list(step.more.get(activities.DESKTOP, ())))
            for name in names:
                if not win.activity.show_named_screen(name):
                    continue
                app.processEvents()
                view = win.activity.content.currentWidget()
                counts[(act.key, step.key, name, "")] = len(visible_controls(view))
                tabs = [t for t in view.findChildren(QTabWidget) if t.isVisibleTo(view)]
                for tab in tabs[:1]:
                    for i in range(tab.count()):
                        tab.setCurrentIndex(i)
                        app.processEvents()
                        counts[(act.key, step.key, name, tab.tabText(i))] = len(visible_controls(view))
    win.close()

    assert len(counts) > 40, "the pass should have reached every screen"
    too_many, stale = [], []
    for (act, step, screen, tab), n in counts.items():
        allowed = OVER_FOR_NOW.get((screen, tab))
        if n > (allowed or MAX_VISIBLE_CONTROLS):
            too_many.append(f"{act}/{step}: {screen} {tab!r} shows {n} (allowed {allowed or MAX_VISIBLE_CONTROLS})")
        if allowed and n <= MAX_VISIBLE_CONTROLS:
            stale.append(f"{screen} {tab!r} is down to {n}: take it off OVER_FOR_NOW")
    assert not too_many, "\n".join(too_many)
    assert not stale, "\n".join(stale)
    # the list itself must not name a screen that was never reached
    reached = {(screen, tab) for (_a, _s, screen, tab) in counts}
    assert set(OVER_FOR_NOW) <= reached
