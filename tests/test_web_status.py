"""The sidebar Status block shows only the lines of the activity you are in (web)."""

from __future__ import annotations

import pandas as pd
import pytest

from app.shared.widgets import status_lines
from core.chartbuilder import loader
from core.ux import words
from tests import webkit


def _state(**kw):
    return dict(kw)


def test_surveys_shows_data_privacy_themes_and_engine():
    lines = status_lines("surveys", _state(df=pd.DataFrame({"a": [1, 2]}), pii_confirmed=True,
                                           theme_labels_text="A\nB", engine_type="transformer"))
    assert lines[0] == "✓ Data: 2 rows" and "confirmed" in lines[1]
    assert any("Theme labels: 2" in x for x in lines) and any("Engine" in x for x in lines)


def test_surveys_without_data_says_so():
    assert "○ No data loaded" in status_lines("surveys", _state())


def test_charts_shows_the_spreadsheet_and_nothing_from_surveys():
    table = loader.LoadedTable(name="x.csv", frame=pd.DataFrame({"a": [1], "b": [2]}), kind="csv")
    lines = status_lines("charts", _state(dc_table=table, df=pd.DataFrame({"a": [1]}), theme_labels_text="A"))
    assert lines == ["✓ Spreadsheet: 1 rows, 2 columns"]
    assert status_lines("charts", _state()) == ["○ No spreadsheet open"]


def test_interviews_and_the_pages_outside_an_activity_show_the_project_only(tmp_path):
    here = tmp_path / "proj" / "project.qnw"
    here.parent.mkdir()
    here.write_text("x")
    for activity in ("interviews", ""):
        lines = status_lines(activity, _state(df=pd.DataFrame({"a": [1]}), active_project_path=str(here)))
        assert lines == ["• Project: proj"], (activity, lines)
        assert status_lines(activity, _state()) == ["○ No active project yet"]


@pytest.mark.parametrize("activity,expect,absent", [
    ("surveys", "Theme labels", "Spreadsheet"),
    ("charts", "Spreadsheet", "Theme labels"),
    ("interviews", "project", "Theme labels"),
])
def test_the_sidebar_in_the_app_follows_the_activity(activity, expect, absent):
    at = webkit.start("")
    at.session_state["view"], at.session_state["activity"] = "activity", activity
    at.run()
    assert not at.exception, at.exception
    text = " ".join(c.value for c in at.sidebar.caption)
    assert expect.lower() in text.lower() and absent.lower() not in text.lower(), text
    assert "QualSafe" in text                                       # the version footer stays


def test_status_words_are_plain():
    for line in status_lines("surveys", _state()) + status_lines("charts", _state()):
        assert words.find_never(line) == []
