"""
Tests for the shelf-based chart builder (`core/chart_spec.py`).

Two things are being pinned. First, that every spec this builder can produce is
one Altair will actually accept — a chart builder that emits *nearly* valid
Vega-Lite is worse than none, because the failure surfaces as a blank panel with
no explanation. Second, that a bad request produces a **sentence**, not a
silently different chart: substituting a mark the analyst did not ask for is how
a figure ends up in a paper meaning something else.

`altair` is a hard dependency of the light install, so it is imported directly.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import altair as alt

from core.chart_spec import (
    AGGREGATES, MARKS, NOMINAL, QUANTITATIVE, TEMPORAL, ChartRequest, Shelf,
    build_spec, can_build, infer_field_types, problems, suggested_charts)


@pytest.fixture()
def coding_frame():
    """The shape `Project.coding_table()` returns, trimmed to what charts use."""
    return pd.DataFrame({
        "code_name": ["Advising", "Cost", "Advising", "Belonging", "Cost", "Cost"],
        "rater_id": ["human_primary"] * 3 + ["human_secondary"] * 3,
        "weight": [1.0, 2.0, 1.5, 1.0, 3.0, 2.0],
        "flagged": [True, False, True, False, False, True],
        "coded_at": pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03",
                                    "2026-02-01", "2026-02-02", "2026-02-03"]),
    })


@pytest.fixture()
def types(coding_frame):
    return infer_field_types(coding_frame)


def _render(spec, frame):
    """Hand the spec to Altair exactly as the front end does. Raises if invalid."""
    spec = dict(spec)
    spec["data"] = {"values": frame.to_dict("records")}
    return alt.Chart.from_dict(spec)


class TestFieldTypes:

    def test_numbers_are_quantitative_and_text_is_nominal(self, types):
        assert types["weight"] == QUANTITATIVE
        assert types["code_name"] == NOMINAL

    def test_dates_are_temporal(self, types):
        assert types["coded_at"] == TEMPORAL

    def test_booleans_are_categories_not_numbers(self, types):
        """Averaging a bool gives a proportion that looks like a mean and is not
        labelled as one, so True/False stays a category."""
        assert types["flagged"] == NOMINAL


class TestEveryMarkProducesValidVegaLite:

    @pytest.mark.parametrize("mark_key", sorted(MARKS))
    def test_a_filled_request_renders(self, mark_key, coding_frame, types):
        request = ChartRequest(
            mark=mark_key,
            x=Shelf("code_name"),
            y=Shelf(aggregate="count"),
            color=Shelf("rater_id"),
        )
        assert can_build(request, types), problems(request, types)
        _render(build_spec(request, types), coding_frame)

    @pytest.mark.parametrize("aggregate", sorted(AGGREGATES))
    def test_every_aggregate_renders(self, aggregate, coding_frame, types):
        request = ChartRequest(mark="bar", x=Shelf("code_name"),
                               y=Shelf("weight", aggregate=aggregate))
        assert can_build(request, types), problems(request, types)
        _render(build_spec(request, types), coding_frame)

    def test_a_facet_renders(self, coding_frame, types):
        request = ChartRequest(mark="bar", x=Shelf("code_name"), y=Shelf(aggregate="count"),
                               facet=Shelf("rater_id"))
        _render(build_spec(request, types), coding_frame)

    def test_binning_a_measure_renders(self, coding_frame, types):
        request = ChartRequest(mark="bar", x=Shelf("weight", bin=True),
                               y=Shelf(aggregate="count"))
        _render(build_spec(request, types), coding_frame)


class TestTheGrammarIsWhatItClaims:

    def test_a_horizontal_bar_puts_the_category_on_y(self, types):
        spec = build_spec(ChartRequest(mark="bar_horizontal", x=Shelf("code_name"),
                                       y=Shelf(aggregate="count")), types)
        assert spec["encoding"]["y"]["field"] == "code_name"
        assert spec["encoding"]["x"]["aggregate"] == "count"

    def test_a_stacked_bar_stacks_and_a_grouped_one_does_not(self, types):
        common = dict(x=Shelf("code_name"), y=Shelf(aggregate="count"),
                      color=Shelf("rater_id"))
        stacked = build_spec(ChartRequest(mark="stacked_bar", **common), types)
        grouped = build_spec(ChartRequest(mark="grouped_bar", **common), types)

        assert stacked["encoding"]["y"]["stack"] == "zero"
        assert grouped["encoding"]["y"]["stack"] is None
        assert grouped["encoding"]["xOffset"]["field"] == "rater_id"

    def test_a_hundred_percent_bar_normalizes(self, types):
        spec = build_spec(ChartRequest(mark="normalized_bar", x=Shelf("code_name"),
                                       y=Shelf(aggregate="count"),
                                       color=Shelf("rater_id")), types)
        assert spec["encoding"]["y"]["stack"] == "normalize"

    def test_a_grouped_horizontal_bar_offsets_on_the_category_axis(self, types):
        """The offset has to swap with the chart, or the bars group along the
        measure and overlap."""
        spec = build_spec(ChartRequest(mark="grouped_bar", x=Shelf("code_name"),
                                       y=Shelf(aggregate="count"),
                                       color=Shelf("rater_id")), types)
        assert "xOffset" in spec["encoding"]

        spec = build_spec(ChartRequest(mark="bar_horizontal", x=Shelf("code_name"),
                                       y=Shelf(aggregate="count")), types)
        assert "xOffset" not in spec["encoding"]

    def test_a_pie_uses_angle_and_colour_not_axes(self, types):
        spec = build_spec(ChartRequest(mark="pie", color=Shelf("code_name"),
                                       y=Shelf(aggregate="count")), types)
        assert "theta" in spec["encoding"]
        assert "x" not in spec["encoding"] and "y" not in spec["encoding"]

    def test_no_spec_names_a_colour(self, coding_frame, types):
        """`core/theme.py` is the only place that decides what blue means. A spec
        carrying its own palette would be a second one."""
        import json

        for request in suggested_charts(types):
            rendered = json.dumps(build_spec(request, types))
            assert "#" not in rendered

    def test_a_spec_carries_no_data(self, types):
        """Purity: the caller attaches rows, so a spec can be built and checked
        before anything is loaded."""
        spec = build_spec(ChartRequest(mark="bar", x=Shelf("code_name"),
                                       y=Shelf(aggregate="count")), types)
        assert "data" not in spec


class TestBadRequestsExplainThemselves:

    def test_a_missing_required_shelf_is_named(self, types):
        found = problems(ChartRequest(mark="pie", y=Shelf(aggregate="count")), types)
        assert any("Slices" in p for p in found)

    def test_averaging_text_is_refused_with_a_reason(self, types):
        found = problems(ChartRequest(mark="bar", x=Shelf("code_name"),
                                      y=Shelf("code_name", aggregate="mean")), types)
        assert any("has no mean" in p for p in found)

    def test_an_unknown_column_is_named(self, types):
        found = problems(ChartRequest(mark="bar", x=Shelf("nonexistent"),
                                      y=Shelf(aggregate="count")), types)
        assert any("nonexistent" in p for p in found)

    def test_an_impossible_request_raises_rather_than_substituting_a_chart(self, types):
        with pytest.raises(ValueError):
            build_spec(ChartRequest(mark="pie", y=Shelf(aggregate="count")), types)

    def test_advice_warns_without_blocking(self, types):
        """A pie of seven categories is a bad idea, not an error."""
        request = ChartRequest(mark="pie", color=Shelf("code_name"),
                               y=Shelf(aggregate="count"))
        assert problems(request, types), "the pie caveat should be stated"
        assert can_build(request, types), "and it should still build"


class TestSuggestions:

    def test_the_first_suggestion_is_how_often_each_category_occurs(self, types):
        first = suggested_charts(types)[0]
        assert first.y.aggregate == "count"
        assert first.x.field == "code_name"

    def test_every_suggestion_is_buildable(self, coding_frame, types):
        suggestions = suggested_charts(types)
        assert suggestions
        for request in suggestions:
            _render(build_spec(request, types), coding_frame)

    def test_suggestions_survive_a_frame_with_one_text_column(self):
        frame = pd.DataFrame({"code_name": ["a", "b", "a"]})
        field_types = infer_field_types(frame)
        for request in suggested_charts(field_types):
            _render(build_spec(request, field_types), frame)

    def test_an_empty_frame_suggests_nothing_rather_than_failing(self):
        assert suggested_charts(infer_field_types(pd.DataFrame())) == []


class TestAggregation:
    """The numbers, computed once.

    Vega-Lite can aggregate for itself, and did. That stopped being acceptable
    when a second front end had to draw the same chart: Qt paints pixels, so it
    has to know the values, and a Qt implementation of "count rows per code per
    coder" would be a second answer to a question this module already answers.
    """

    def test_count_groups_rows(self, coding_frame, types):
        from core.chart_spec import MEASURE, aggregate

        out = aggregate(coding_frame,
                        ChartRequest(mark="bar", x=Shelf("code_name"),
                                     y=Shelf(aggregate="count")), types)

        assert dict(zip(out["code_name"], out[MEASURE])) == {
            "Advising": 2.0, "Cost": 3.0, "Belonging": 1.0}

    def test_sum_and_mean_reduce_the_measure_column(self, coding_frame, types):
        from core.chart_spec import MEASURE, aggregate

        totals = aggregate(coding_frame,
                           ChartRequest(mark="bar", x=Shelf("code_name"),
                                        y=Shelf("weight", aggregate="sum")), types)
        means = aggregate(coding_frame,
                          ChartRequest(mark="bar", x=Shelf("code_name"),
                                       y=Shelf("weight", aggregate="mean")), types)

        # Cost carries weights 2.0, 3.0 and 2.0.
        assert dict(zip(totals["code_name"], totals[MEASURE]))["Cost"] == 7.0
        assert dict(zip(means["code_name"], means[MEASURE]))["Cost"] == pytest.approx(7 / 3)

    def test_distinct_counts_values_not_rows(self, coding_frame, types):
        from core.chart_spec import MEASURE, aggregate

        out = aggregate(coding_frame,
                        ChartRequest(mark="bar", x=Shelf("rater_id"),
                                     y=Shelf("code_name", aggregate="distinct")),
                        types)

        assert dict(zip(out["rater_id"], out[MEASURE])) == {
            "human_primary": 2.0, "human_secondary": 2.0}

    def test_a_colour_shelf_becomes_another_grouping_column(self, coding_frame, types):
        from core.chart_spec import MEASURE, aggregate

        out = aggregate(coding_frame,
                        ChartRequest(mark="stacked_bar", x=Shelf("code_name"),
                                     y=Shelf(aggregate="count"),
                                     color=Shelf("rater_id")), types)

        assert set(out.columns) == {"code_name", "rater_id", MEASURE}
        assert out[MEASURE].sum() == len(coding_frame)

    def test_a_scatter_is_not_aggregated_at_all(self, coding_frame, types):
        """Two measures against each other plots rows, not groups."""
        from core.chart_spec import MEASURE, aggregate

        out = aggregate(coding_frame,
                        ChartRequest(mark="point", x=Shelf("weight"),
                                     y=Shelf("weight")), types)

        assert MEASURE not in out.columns
        assert len(out) == len(coding_frame)

    def test_sorting_by_size_orders_by_the_measure(self, coding_frame, types):
        from core.chart_spec import aggregate

        out = aggregate(coding_frame,
                        ChartRequest(mark="bar_horizontal",
                                     x=Shelf("code_name", sort="-x"),
                                     y=Shelf(aggregate="count")), types)

        assert list(out["code_name"]) == ["Cost", "Advising", "Belonging"]

    def test_an_impossible_request_raises_the_same_way_build_spec_does(self, coding_frame, types):
        from core.chart_spec import aggregate

        with pytest.raises(ValueError):
            aggregate(coding_frame,
                      ChartRequest(mark="pie", y=Shelf(aggregate="count")), types)

    def test_the_measure_gets_a_title_in_the_analysts_words(self):
        from core.chart_spec import measure_title

        assert measure_title(Shelf(aggregate="count")) == "Count"
        assert measure_title(Shelf("weight", "sum")) == "Sum of weight"
        assert measure_title(Shelf("code_name", "distinct")) == "Distinct code_name"

    def test_the_measure_column_is_not_a_source_field(self):
        """"Sum of weight" and "weight" are different columns; conflating them is
        how a chart plots the wrong one."""
        from core.chart_spec import MEASURE

        assert MEASURE.startswith("__") and MEASURE.endswith("__")


class TestSuggestionsAreWorthOffering:
    """Both defects below were invisible to the suite and obvious in a rendered
    picture of the desktop screen. A suggestion that is technically valid and
    useless is worse than no suggestion: it is the first thing an analyst sees.
    """

    @pytest.fixture()
    def coding_table_shape(self):
        """What `Project.coding_table()` actually returns.

        Note the object dtypes: a sqlite column with any NULL in it arrives as
        object even when every value is a float, which is why `weight` here is
        not a float column.
        """
        return pd.DataFrame({
            "application_id": [f"app{i}" for i in range(6)],
            "excerpt_id": [f"exc{i}" for i in range(6)],
            "source_id": [f"s{i}" for i in range(6)],
            "code_name": ["Cost", "Cost", "Advising", "Advising", "Cost", "Belonging"],
            "weight": pd.Series([1.0, 2.0, None, 1.0, 3.0, 1.0], dtype=object),
            "rater_id": ["human_primary"] * 6,
        })

    def test_an_all_null_free_object_column_of_numbers_is_a_measure(
            self, coding_table_shape):
        """Otherwise "Sum of weight" is refused as an average of categories,
        which is both wrong and baffling — the column plainly holds numbers."""
        types = infer_field_types(coding_table_shape)
        assert types["weight"] == QUANTITATIVE

    def test_a_text_column_is_still_a_category(self, coding_table_shape):
        types = infer_field_types(coding_table_shape)
        assert types["code_name"] == NOMINAL

    def test_an_empty_column_is_not_guessed_into_a_measure(self):
        frame = pd.DataFrame({"nothing": pd.Series([None, None], dtype=object)})
        assert infer_field_types(frame)["nothing"] == NOMINAL

    def test_a_column_of_mixed_junk_stays_a_category(self):
        frame = pd.DataFrame({"mixed": pd.Series([1.0, "banana"], dtype=object)})
        assert infer_field_types(frame)["mixed"] == NOMINAL

    def test_identifiers_are_never_suggested(self, coding_table_shape):
        """One bar per row tells the analyst nothing."""
        types = infer_field_types(coding_table_shape)

        for request in suggested_charts(types, frame=coding_table_shape):
            for name in ("x", "y", "color", "facet"):
                assert not request.shelf(name).field.endswith("_id"), request.title

    def test_the_first_suggestion_is_over_a_real_category(self, coding_table_shape):
        types = infer_field_types(coding_table_shape)
        first = suggested_charts(types, frame=coding_table_shape)[0]
        assert first.x.field == "code_name"

    def test_a_category_with_one_value_is_not_offered_as_an_axis(
            self, coding_table_shape):
        """`rater_id` is constant here — a bar chart of it is one bar."""
        types = infer_field_types(coding_table_shape)
        from core.chart_spec import chartable_fields

        assert "rater_id" not in chartable_fields(types, coding_table_shape)

    def test_a_category_with_hundreds_of_values_is_not_offered(self):
        from core.chart_spec import chartable_fields

        frame = pd.DataFrame({"note": [f"free text {i}" for i in range(200)]})
        types = infer_field_types(frame)

        assert chartable_fields(types, frame) == []

    def test_without_a_frame_only_the_name_rule_applies(self, coding_table_shape):
        """Cardinality needs the data; the name rule does not, so a caller with
        only the types still gets the useful half."""
        from core.chart_spec import chartable_fields

        types = infer_field_types(coding_table_shape)
        names = chartable_fields(types)

        assert "code_name" in names
        assert "application_id" not in names

    def test_a_field_merely_containing_id_is_not_swept_up(self):
        """A descriptor called "identity" is a real thing to chart."""
        from core.chart_spec import chartable_fields

        frame = pd.DataFrame({"identity": ["a", "b", "a"], "candidate": ["x", "y", "x"]})
        names = chartable_fields(infer_field_types(frame), frame)

        assert set(names) == {"identity", "candidate"}
