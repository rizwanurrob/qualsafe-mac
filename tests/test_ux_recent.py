"""Recent projects hold a path and an activity, and which activity a project is."""

import json

import pytest

from core.ux import recent
from core.ux.kind import activity_for_source_types, landing


@pytest.mark.parametrize("types,expected", [
    (["survey_response"], "surveys"),
    (["document"], "interviews"),
    (["interview"], "interviews"),
    (["interview", "document"], "interviews"),
    (["survey_response", "document"], "interviews"),
    ([], "interviews"),
])
def test_activity_from_what_the_project_holds(types, expected):
    assert activity_for_source_types(types) == expected


def test_add_puts_the_newest_first_and_removes_the_older_copy():
    entries = recent.add([], "C:/a.qnw", "surveys")
    entries = recent.add(entries, "C:/b.qnw", "interviews")
    entries = recent.add(entries, "C:/A.qnw", "surveys")      # same file, other case
    assert [e["path"] for e in entries] == ["C:/A.qnw", "C:/b.qnw"]


def test_the_list_is_capped():
    entries = []
    for i in range(recent.MAX_RECENT + 3):
        entries = recent.add(entries, f"C:/p{i}.qnw", "surveys")
    assert len(entries) == recent.MAX_RECENT
    assert entries[0]["path"] == f"C:/p{recent.MAX_RECENT + 2}.qnw"


def test_charts_has_no_project_so_it_is_never_listed():
    assert recent.add([], "C:/a.csv", "charts") == []
    assert recent.add([], "C:/a.qnw", "nope") == []


def test_round_trip_stores_only_a_path_and_an_activity():
    entries = recent.add([], "C:/a.qnw", "surveys")
    raw = recent.dump(entries)
    assert set(json.loads(raw)[0]) == {"path", "activity"}
    assert recent.parse(raw) == entries


@pytest.mark.parametrize("raw", ["", "not json", "{}", "[1, 2]", None, 5,
                                 '[{"path": "", "activity": "surveys"}]',
                                 '[{"path": "C:/a", "activity": "charts"}]',
                                 '[{"path": 3, "activity": "surveys"}]'])
def test_malformed_stored_values_become_an_empty_list(raw):
    assert recent.parse(raw) == []


def test_existing_drops_files_that_are_gone(tmp_path):
    here = tmp_path / "here.qnw"
    here.write_text("x", encoding="utf-8")
    entries = [{"path": str(here), "activity": "surveys"},
               {"path": str(tmp_path / "gone.qnw"), "activity": "interviews"}]
    assert recent.existing(entries) == entries[:1]


@pytest.mark.parametrize("types,codes,codings,expected", [
    (["survey_response"], 5, 40, ("surveys", "explore")),     # coded: read the results
    (["survey_response"], 5, 0, ("surveys", "code")),         # themes, not coded yet
    (["survey_response"], 0, 0, ("surveys", "themes")),       # no themes yet
    (["document"], 0, 0, ("interviews", "code")),             # the reader
    (["interview", "document"], 3, 9, ("interviews", "code")),
    ([], 0, 0, ("interviews", "add")),                        # empty: add transcripts
])
def test_where_a_project_opens(types, codes, codings, expected):
    assert landing(types, codes, codings) == expected


def test_a_survey_project_never_lands_on_the_document_list():
    from core.ux import activities

    for codes, codings in ((0, 0), (3, 0), (3, 9)):
        activity, step = landing(["survey_response"], codes, codings)
        screens = activities.get(activity).step(step).screens["desktop"]
        assert "Documents" not in screens
