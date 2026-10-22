"""The progress store keeps the session shape per activity, and never any text."""

import json

import pytest

from core.ux import progress


@pytest.fixture(autouse=True)
def settings_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("QNW_SETTINGS_DIR", str(tmp_path))
    return tmp_path


def test_nothing_saved_loads_none():
    assert progress.load("surveys") is None


def test_round_trip_and_step_recorded():
    progress.save("surveys", "explore", {"text_column": "Answer", "explore_tab": "Frequency"},
                  now="2026-10-02T10:00:00+00:00")
    got = progress.load("surveys")
    assert got["step"] == "explore"
    assert got["updated"] == "2026-10-02T10:00:00+00:00"
    assert got["state"] == {"text_column": "Answer", "explore_tab": "Frequency"}


def test_unknown_step_is_refused():
    assert progress.save("charts", "explore", {}) is None
    assert progress.load("charts") is None


def test_activities_are_independent():
    progress.save("surveys", "code", {"text_column": "A"})
    progress.save("charts", "adjust", {"question": "Q7"})
    progress.clear("charts")
    assert progress.load("charts") is None
    assert progress.load("surveys")["step"] == "code"


def test_unknown_keys_are_dropped():
    progress.save("charts", "open", {"file_path": "C:/x.csv", "response_text": "hello", "cells": [1]})
    assert progress.load("charts")["state"] == {"file_path": "C:/x.csv"}


def test_the_privacy_confirmation_is_never_saved(settings_dir):
    progress.save("surveys", "load", {"pii_confirmed": True, "text_column": "A"})
    raw = (settings_dir / "progress.json").read_text(encoding="utf-8")
    assert "pii" not in raw
    for keys in progress.WHITELIST.values():
        assert not any("pii" in k or "privacy" in k for k in keys)


def test_long_values_are_dropped_not_cut():
    long_answer = "I felt lost in my first year. " * 20
    progress.save("surveys", "explore", {"explore_tab": long_answer, "text_column": "A"})
    assert progress.load("surveys")["state"] == {"text_column": "A"}


def test_long_text_inside_a_list_or_dict_is_dropped():
    long_answer = "x" * 300
    progress.save("surveys", "explore", {
        "explore_filters": ["Money", long_answer],
        "code_settings": {"a": {"b": {"c": {"d": 1}}}},
    })
    assert progress.load("surveys")["state"] == {}


def test_theme_list_and_paths_may_be_longer():
    themes = "\n".join(f"Theme {i}" for i in range(200))
    progress.save("surveys", "themes", {"theme_labels_text": themes, "resume_path": "C:/" + "d/" * 200})
    state = progress.load("surveys")["state"]
    assert state["theme_labels_text"] == themes and "resume_path" in state


def test_corrupt_file_is_treated_as_empty(settings_dir):
    (settings_dir / "progress.json").write_text("{not json", encoding="utf-8")
    assert progress.load("surveys") is None
    progress.save("surveys", "load", {})
    assert progress.load("surveys")["step"] == "load"


def test_a_hand_edited_file_cannot_smuggle_keys(settings_dir):
    (settings_dir / "progress.json").write_text(json.dumps({
        "version": 1,
        "surveys": {"step": "code", "updated": "x",
                    "state": {"text_column": "A", "answers": "secret", "pii_confirmed": True}},
        "charts": {"step": "no-such-step", "state": {}},
    }), encoding="utf-8")
    assert progress.load("surveys")["state"] == {"text_column": "A"}
    assert progress.load("charts") is None


def test_wrong_version_is_ignored(settings_dir):
    (settings_dir / "progress.json").write_text(
        json.dumps({"version": 99, "surveys": {"step": "load", "state": {}}}), encoding="utf-8")
    assert progress.load("surveys") is None


def test_migrates_workspace_json_once(settings_dir):
    ws = settings_dir / "workspace.json"
    ws.write_text(json.dumps({
        "resume_path": "C:/data/survey.csv", "text_column": "Answer",
        "theme_labels_text": "Money\nTime", "ingestion_mode": "wide",
        "secret_extra": "dropped",
    }), encoding="utf-8")
    assert progress.load("surveys") is None        # load never migrates by itself
    assert ws.exists()
    assert progress.migrate_workspace() is True
    got = progress.load("surveys")
    assert got["step"] == "load"
    assert got["state"]["text_column"] == "Answer"
    assert got["state"]["theme_labels_text"] == "Money\nTime"
    assert "secret_extra" not in got["state"]
    assert not ws.exists() and (settings_dir / "workspace.json.bak").exists()
    # A second call does not redo or undo anything.
    assert progress.migrate_workspace() is False
    assert progress.load("surveys")["state"]["text_column"] == "Answer"


def test_migration_does_not_overwrite_newer_progress(settings_dir):
    progress.save("surveys", "report", {"text_column": "New"})
    (settings_dir / "workspace.json").write_text(
        json.dumps({"resume_path": "C:/old.csv", "text_column": "Old"}), encoding="utf-8")
    assert progress.migrate_workspace() is True
    assert progress.load("surveys")["state"]["text_column"] == "New"
    assert (settings_dir / "workspace.json.bak").exists()


def test_corrupt_workspace_is_set_aside(settings_dir):
    (settings_dir / "workspace.json").write_text("nope", encoding="utf-8")
    assert progress.migrate_workspace() is True
    assert progress.load("surveys") is None
    assert (settings_dir / "workspace.json.bak").exists()


def test_saving_and_loading_leave_the_web_apps_workspace_file_alone(settings_dir):
    """The web app still reads workspace.json; the desktop store must not take it."""
    ws = settings_dir / "workspace.json"
    ws.write_text(json.dumps({"resume_path": "C:/x.csv"}), encoding="utf-8")
    progress.save("charts", "open", {"file_path": "C:/y.csv"})
    progress.load("surveys")
    progress.clear("charts")
    assert ws.exists() and not (settings_dir / "workspace.json.bak").exists()


def test_missing_paths_are_reported(tmp_path):
    here = tmp_path / "here.csv"
    here.write_text("a", encoding="utf-8")
    progress.save("charts", "open", {"file_path": str(here)})
    assert progress.missing_paths("charts") == []
    here.unlink()
    assert progress.missing_paths("charts") == [str(here)]
    assert progress.missing_paths("interviews") == []


def test_no_state_value_in_a_saved_file_is_long_prose(settings_dir):
    progress.save("surveys", "code", {
        "text_column": "Answer", "theme_labels_text": "Money\nTime",
        "explore_filters": ["Money"], "code_choice": "suggest"})
    data = json.loads((settings_dir / "progress.json").read_text(encoding="utf-8"))

    def walk(v, key):
        if isinstance(v, str):
            assert len(v) <= progress.MAX_LEN.get(key, progress.DEFAULT_MAX_LEN)
        elif isinstance(v, list):
            [walk(i, key) for i in v]
        elif isinstance(v, dict):
            [walk(i, k) for k, i in v.items()]

    walk(data["surveys"]["state"], "")


# ── Continue: the summary Home shows ─────────────────────────────────────────

from datetime import datetime, timedelta, timezone


NOW = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize("delta,expected", [
    (timedelta(seconds=10), "just now"),
    (timedelta(minutes=1), "1 minute ago"),
    (timedelta(minutes=5), "5 minutes ago"),
    (timedelta(hours=1, minutes=10), "1 hour ago"),
    (timedelta(hours=2), "2 hours ago"),
    (timedelta(hours=30), "yesterday"),
    (timedelta(days=3), "3 days ago"),
])
def test_ago_is_plain_words(delta, expected):
    assert progress.ago(NOW - delta, now=NOW) == expected


def test_a_long_gap_is_a_date():
    assert "2026" in progress.ago(NOW - timedelta(days=40), now=NOW)


def test_nothing_saved_means_nothing_to_continue():
    assert progress.summary("surveys") is None


def test_a_step_with_nothing_behind_it_is_not_offered():
    progress.save("surveys", "code", {"ingestion_mode": "long", "text_column": ""})
    assert progress.summary("surveys") is None        # someone clicked through and left


def test_a_summary_names_the_work_and_the_step(tmp_path):
    data = tmp_path / "answers.csv"
    data.write_text("a", encoding="utf-8")
    progress.save("surveys", "code", {"resume_path": str(data)},
                  now=(datetime.now(timezone.utc) - timedelta(hours=2)).isoformat())
    s = progress.summary("surveys")
    assert (s.name, s.step_number, s.step_total, s.step_title) == ("answers.csv", 3, 5, "Code")
    assert s.detail == "Step 3 of 5 · Code · 2 hours ago"
    assert s.missing == ()
    assert str(tmp_path) not in s.name + s.detail          # a name, never a path


def test_a_theme_list_alone_is_worth_continuing():
    progress.save("surveys", "themes", {"theme_labels_text": "Money"})
    s = progress.summary("surveys")
    assert s is not None and s.name == ""


def test_a_missing_file_is_flagged(tmp_path):
    gone = tmp_path / "Q7.xlsx"
    progress.save("charts", "adjust", {"file_path": str(gone)})
    s = progress.summary("charts")
    assert s.missing == (str(gone),) and s.name == "Q7.xlsx"
    assert (s.step_number, s.step_total) == (3, 4)


def test_replace_path_points_a_saved_place_at_a_moved_file(tmp_path):
    old, new = tmp_path / "old.csv", tmp_path / "new.csv"
    new.write_text("x", encoding="utf-8")
    progress.save("charts", "adjust", {"file_path": str(old), "question": "Q7"},
                  now="2026-10-01T09:00:00+00:00")
    assert progress.replace_path("charts", str(old), str(new)) is True
    entry = progress.load("charts")
    assert entry["state"]["file_path"] == str(new) and entry["state"]["question"] == "Q7"
    assert entry["step"] == "adjust" and entry["updated"] == "2026-10-01T09:00:00+00:00"
    assert progress.summary("charts").missing == ()
    assert progress.replace_path("charts", str(old), str(new)) is False
    assert progress.replace_path("interviews", "a", "b") is False
