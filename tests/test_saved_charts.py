"""
Saved charts — a figure's definition, stored with the project (v4.6, §B1c).

The exported PNG answers "get this figure into the document". This answers the
other question, the one a study that keeps collecting data actually has:
**redraw this figure against the project as it stands now.** A chart built after
twenty interviews should come back after forty without anyone remembering how it
was made, and a methods appendix should be able to cite it by name.

So the contract under test is round-tripping and re-running, not pixels. And
because a saved chart lives inside someone's project file and outlives the
version that wrote it, loading is deliberately forgiving in a way that saving is
not — a spec missing a field that a later build added must still open.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.chart_spec import (
    MEASURE, ChartRequest, Shelf, aggregate, describe, infer_field_types,
    request_from_dict, request_to_dict)
from core.model import SavedChart
from core.project import SCHEMA_VERSION, Project


@pytest.fixture()
def request_():
    return ChartRequest(
        mark="stacked_bar",
        x=Shelf("code_name", sort="-y"),
        y=Shelf("weight", aggregate="sum", bin=False),
        color=Shelf("rater_id"),
        title="Themes by coder",
        width=640, height=360,
    )


@pytest.fixture()
def store(tmp_path):
    path = tmp_path / "p.qnw"
    Project.create(path).close()
    return path


class TestRoundTrip:
    """`from_dict(to_dict(x)) == x` is the contract. `ChartRequest` is frozen, so
    that equality is structural and the assertion means what it says."""

    def test_a_request_survives_the_trip(self, request_):
        assert request_from_dict(request_to_dict(request_)) == request_

    def test_every_shelf_property_survives(self, request_):
        back = request_from_dict(request_to_dict(request_))

        assert back.x.sort == "-y"
        assert back.y.aggregate == "sum"
        assert back.color.field == "rater_id"
        assert (back.width, back.height) == (640, 360)

    def test_an_empty_request_survives(self):
        empty = ChartRequest()
        assert request_from_dict(request_to_dict(empty)) == empty

    def test_the_payload_is_json_able(self, request_):
        import json

        assert json.loads(json.dumps(request_to_dict(request_)))

    def test_it_carries_a_version(self, request_):
        """So a later format change can tell what it is reading."""
        assert request_to_dict(request_)["version"] == 1


class TestLoadingIsForgiving:
    """A saved chart outlives the build that wrote it. Refusing to open one loses
    it; opening it with a default does not."""

    def test_a_spec_from_an_older_build_still_opens(self):
        older = {"version": 1, "mark": "bar", "shelves": {"x": {"field": "code_name"}}}

        request = request_from_dict(older)

        assert request.mark == "bar"
        assert request.x.field == "code_name"
        assert request.y.is_empty

    def test_an_unknown_key_is_ignored_rather_than_fatal(self):
        request = request_from_dict(
            {"mark": "pie", "shelves": {}, "someFutureOption": {"nested": True}})
        assert request.mark == "pie"

    def test_an_empty_dict_gives_a_usable_default(self):
        assert request_from_dict({}) == ChartRequest()

    def test_a_null_aggregate_stays_none_not_the_string(self):
        request = request_from_dict(
            {"shelves": {"y": {"field": "w", "aggregate": None}}})
        assert request.y.aggregate is None


class TestTheStore:

    def test_a_chart_is_saved_and_read_back(self, store, request_):
        with Project.open(store) as project:
            project.save_chart(SavedChart(chart_id="", name="Themes",
                                          spec=request_to_dict(request_)))

        with Project.open(store) as project:
            saved = project.get_chart("Themes")

        assert saved is not None
        assert request_from_dict(saved.spec) == request_

    def test_saving_the_same_name_replaces_rather_than_duplicates(self, store, request_):
        """An analyst who tweaks a chart and saves it again means *that* chart.
        A list of near-duplicates is how a saved-view feature stops being used."""
        with Project.open(store) as project:
            first = project.save_chart(SavedChart(chart_id="", name="Themes",
                                                  spec=request_to_dict(request_)))
            changed = request_to_dict(ChartRequest(mark="pie", color=Shelf("code_name"),
                                                   y=Shelf(aggregate="count")))
            second = project.save_chart(SavedChart(chart_id="", name="Themes",
                                                   spec=changed))

            assert len(project.list_charts()) == 1
            assert first == second, "the id should be kept, not minted again"
            assert project.get_chart("Themes").spec["mark"] == "pie"

    def test_the_data_source_is_recorded(self, store, request_):
        """The same shelves mean different things over different frames."""
        with Project.open(store) as project:
            project.save_chart(SavedChart(
                chart_id="", name="By year", spec=request_to_dict(request_),
                source="codings_with_descriptors"))

            assert project.get_chart("By year").source == "codings_with_descriptors"

    def test_charts_come_back_in_name_order(self, store, request_):
        with Project.open(store) as project:
            for name in ("Zeta", "Alpha", "Mu"):
                project.save_chart(SavedChart(chart_id="", name=name,
                                              spec=request_to_dict(request_)))

            assert [c.name for c in project.list_charts()] == ["Alpha", "Mu", "Zeta"]

    def test_a_timestamp_is_stamped_when_not_given(self, store, request_):
        with Project.open(store) as project:
            project.save_chart(SavedChart(chart_id="", name="T",
                                          spec=request_to_dict(request_)))
            assert project.get_chart("T").created_at

    def test_deleting_reports_whether_there_was_one(self, store, request_):
        with Project.open(store) as project:
            project.save_chart(SavedChart(chart_id="", name="T",
                                          spec=request_to_dict(request_)))

            assert project.delete_chart("T") is True
            assert project.delete_chart("T") is False
            assert project.list_charts() == []

    def test_an_absent_chart_is_none_not_an_error(self, store):
        with Project.open(store) as project:
            assert project.get_chart("never saved") is None


class TestTheMigration:

    def test_a_v4_store_gains_the_table_on_open(self, tmp_path):
        """The point of saving a chart is that it outlives the session. That only
        works if an existing project can gain the feature."""
        path = tmp_path / "old.qnw"
        Project.create(path).close()

        connection = sqlite3.connect(path)
        connection.execute("DROP TABLE saved_charts")
        connection.execute("UPDATE meta SET value='4' WHERE key='schema_version'")
        connection.commit()
        connection.close()

        with Project.open(path) as project:
            assert project.list_charts() == []
            project.save_chart(SavedChart(chart_id="", name="T", spec={"mark": "bar"}))
            assert len(project.list_charts()) == 1

        connection = sqlite3.connect(path)
        version = connection.execute(
            "SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]
        connection.close()
        assert int(version) == SCHEMA_VERSION

    def test_a_v4_store_keeps_everything_it_had(self, tmp_path):
        """Additive means additive."""
        from core.model import Code, Source

        path = tmp_path / "old.qnw"
        with Project.create(path) as project:
            project.add_code(Code(code_id="", name="Cost", definition="Money"))
            project.add_source(Source(source_id="s1", type="survey_response",
                                      raw_text="text", label="Q1",
                                      metadata={"response_id": "r1"}))

        connection = sqlite3.connect(path)
        connection.execute("DROP TABLE saved_charts")
        connection.execute("UPDATE meta SET value='4' WHERE key='schema_version'")
        connection.commit()
        connection.close()

        with Project.open(path) as project:
            assert project.find_code_by_name("Cost") is not None
            assert len(project.list_sources()) == 1


class TestReRunning:
    """The reason the feature exists: the same definition, more data, a new
    answer."""

    def test_a_saved_chart_redraws_against_a_grown_project(self, store):
        frame_now = pd.DataFrame({
            "code_name": ["Cost", "Advising"],
            "rater_id": ["human_primary"] * 2,
        })
        request = ChartRequest(mark="bar", x=Shelf("code_name"),
                               y=Shelf(aggregate="count"))

        with Project.open(store) as project:
            project.save_chart(SavedChart(chart_id="", name="Frequency",
                                          spec=request_to_dict(request)))
            reloaded = request_from_dict(project.get_chart("Frequency").spec)

        before = aggregate(frame_now, reloaded, infer_field_types(frame_now))
        assert before[MEASURE].sum() == 2

        frame_later = pd.concat([frame_now, pd.DataFrame({
            "code_name": ["Cost", "Cost", "Belonging"],
            "rater_id": ["human_primary"] * 3,
        })], ignore_index=True)

        after = aggregate(frame_later, reloaded, infer_field_types(frame_later))
        assert after[MEASURE].sum() == 5
        assert set(after["code_name"]) == {"Cost", "Advising", "Belonging"}


class TestDescribe:
    """A caption that is true even when the analyst left the title blank."""

    def test_it_names_the_mark_and_the_shelves(self, request_):
        line = describe(request_)
        assert "Stacked bar" in line
        assert "code_name" in line and "rater_id" in line
        assert "Sum of weight" in line

    def test_it_survives_an_empty_request(self):
        assert describe(ChartRequest())

    def test_it_uses_the_arc_shelf_names_for_a_pie(self):
        """A pie has no axes, so calling its shelves X and Y would be a lie."""
        line = describe(ChartRequest(mark="pie", color=Shelf("code_name"),
                                     y=Shelf(aggregate="count")))
        assert "Slices" in line and "Size" in line
