"""Every step of every activity on the web: at most seven controls in view, one filled button (item 4b.5h).

Opened with a finished sample project (so steps that need one show their real controls) and with
nothing loaded (so each shows its way in). The screens of a step are visited one at a time.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.shared import nav
from core.sample_project import build_sample_project
from core.ux import activities
from tests import webkit

ROOT = Path(__file__).resolve().parents[1]
SAMPLE_CSV = ROOT / "data" / "sample_survey_education.csv"


def _places():
    for activity in activities.ACTIVITIES:
        for step in activity.steps:
            main = list(step.screens.get(nav.SURFACE, ())) or [""]
            more = list(step.more.get(nav.SURFACE, ()))
            for screen in main + more:
                yield activity.key, step.key, screen


PLACES = list(_places())
IDS = [f"{a}-{s}-{c or 'step'}".replace(" ", "_") for a, s, c in PLACES]


@pytest.fixture
def project():
    from app.shared import constants

    out = constants.STREAMLIT_OUTPUT_DIR / "SAMPLE_all_steps" / "project.qnw"
    out.parent.mkdir(parents=True)
    build_sample_project(SAMPLE_CSV, out)
    return out


def _open(activity: str, step: str, screen: str, project=None):
    at = webkit.start("")
    if project is not None:
        at.session_state["active_project_path"] = str(project)
    at.session_state["view"], at.session_state["activity"] = nav.ACTIVITY, activity
    at.session_state[f"step_{activity}"] = step
    if screen:
        at.session_state[nav.screen_key(activity, step)] = screen
    at.run()
    assert not at.exception, (activity, step, screen, at.exception)
    return at


def _check(at, where):
    visible = webkit.visible_controls(at)
    assert len(visible) <= webkit.MAX_VISIBLE_CONTROLS, (where, webkit.describe(visible))
    assert len(webkit.primary_buttons(at)) <= 1, (where, webkit.describe(webkit.primary_buttons(at)))


@pytest.mark.parametrize("activity,step,screen", PLACES, ids=IDS)
def test_with_a_project(activity, step, screen, project):
    _check(_open(activity, step, screen, project), (activity, step, screen))


@pytest.mark.parametrize("activity,step,screen", PLACES, ids=IDS)
def test_with_nothing_loaded(activity, step, screen):
    _check(_open(activity, step, screen), (activity, step, screen))
