"""
Chart Builder numeric and time charts: histogram, box plot, scatter, line, area.

Every expected number is worked by hand in the comments. The renderer is checked
by handing its spec to Altair (schema validation) and to vl-convert.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.chartbuilder import clean, export, numeric, vocab
from core.chartbuilder.aggregate import ChartBuildError, aggregate
from core.chartbuilder.build import build_data
from core.chartbuilder.config import ChartConfig
from core.chartbuilder.render import build_spec


def _cfg(chart, **kw):
    return ChartConfig(chart_type=chart, **kw)


def _cell(data, **where):
    t = data.table
    for k, v in where.items():
        t = t[t[k] == v]
    assert len(t) == 1, t
    return t.iloc[0]


# ── reading numbers ───────────────────────────────────────────────────────────

def test_numbers_accept_thousands_and_currency_and_leave_text_alone():
    s = pd.Series(["1,234.5", "$2,000", "12", " 7 ", "3.5", "abc", "", "NA", "1,23", None])
    n = clean.to_numbers(s)
    assert n.tolist()[:5] == [1234.5, 2000.0, 12.0, 7.0, 3.5]
    assert n.iloc[5:].isna().all()                    # "abc", blanks, "1,23" (not a thousands form)
    assert clean.count_non_numeric(s, n) == 2         # "abc" and "1,23"; blanks and NA are not answers


def test_a_measure_summary_reads_thousands_separators():
    f = pd.DataFrame({"K": ["a", "a", "b"], "V": ["1,000", "2,500", "40"]})
    d, _ = build_data(f, ChartConfig(column="K", aggregation="sum", value_field="V"))
    assert _cell(d, category="a")["value"] == 3500 and _cell(d, category="b")["value"] == 40


# ── histogram ─────────────────────────────────────────────────────────────────

def _numbers(values, groups=None):
    f = pd.DataFrame({"X": [str(v) for v in values]})
    if groups is not None:
        f["G"] = groups
    return f


def test_histogram_counts_and_percents_hand_checked():
    # 0..9, 5 bins -> edges 0, 1.8, 3.6, 5.4, 7.2, 9. Two values per bin (9 lands in the last).
    cfg = _cfg("histogram", column="X", aggregation="count")
    cfg.display.bins = 5
    d = aggregate(_numbers(range(10)), cfg)
    assert d.table["count"].tolist() == [2, 2, 2, 2, 2]
    assert d.table["bin_start"].tolist() == pytest.approx([0, 1.8, 3.6, 5.4, 7.2])
    assert d.table["bin_end"].iloc[-1] == 9
    assert d.table["percent"].tolist() == [20.0] * 5
    assert d.table["display_label"].iloc[0] == "2/10 (20%)"       # count-led: n/N (percent)
    assert d.valid_n == 10 and d.value_title == "Number of responses"


def test_histogram_leaves_out_blanks_and_reports_text():
    f = _numbers([1, 2, 3, 4, 5, "", "NA", "oops"])
    cfg = _cfg("histogram", column="X", aggregation="percent")
    d = aggregate(f, cfg)
    assert d.valid_n == 5 and d.missing_n == 3
    assert d.table["denominator"].iloc[0] == 5
    assert any("1 value(s) in 'X' are not numbers" in w for w in d.warnings)
    assert any("fewer than 30" in w for w in d.warnings)
    assert d.value_title == "Percent of responses" and d.is_percent


def test_histogram_split_by_shares_bins_and_uses_per_group_bases():
    f = _numbers([1, 2, 3, 4, 10, 11, 12, 13, 14, 15], ["a"] * 4 + ["b"] * 6)
    cfg = _cfg("histogram", column="X", group_by=["G"], aggregation="count")
    cfg.display.bins = 3
    d = aggregate(f, cfg)
    a = d.table[d.table["group"] == "a"]
    b = d.table[d.table["group"] == "b"]
    assert a["bin_start"].tolist() == b["bin_start"].tolist()      # shared bins
    assert a["denominator"].iloc[0] == 4 and b["denominator"].iloc[0] == 6
    assert a["count"].sum() == 4 and b["count"].sum() == 6
    assert d.groups == ["a", "b"]


def test_histogram_refuses_a_measure_and_an_empty_field():
    with pytest.raises(ChartBuildError, match="counts rows"):
        aggregate(_numbers(range(5)), _cfg("histogram", column="X", aggregation="mean",
                                           value_field="X"))
    with pytest.raises(ChartBuildError, match="no numbers to plot"):
        aggregate(_numbers(["a", "b"]), _cfg("histogram", column="X"))


def test_automatic_bins_stay_within_the_limit():
    rng = np.random.default_rng(0)
    edges = numeric.bin_edges(rng.normal(size=20000))
    assert 2 <= len(edges) - 1 <= numeric.MAX_BINS
    assert len(numeric.bin_edges(np.arange(100.0), bins=999)) - 1 == numeric.MAX_BINS


# ── box plot ──────────────────────────────────────────────────────────────────

def test_box_statistics_hand_checked_with_an_outlier():
    # 1..9 and 100: q1 3.25, median 5.5, q3 7.75, IQR 4.5, fences -3.5 and 14.5.
    s = numeric.box_stats(np.array([1, 2, 3, 4, 5, 6, 7, 8, 9, 100], dtype=float))
    assert (s["q1"], s["median"], s["q3"]) == (3.25, 5.5, 7.75)
    assert (s["whisker_lo"], s["whisker_hi"], s["outliers"]) == (1.0, 9.0, [100.0])
    assert s["min"] == 1 and s["max"] == 100 and s["n"] == 10 and s["mean"] == pytest.approx(14.5)


def test_box_plot_by_group_is_sorted_by_median_and_counts_outliers():
    f = _numbers([1, 2, 3, 4, 5, 6, 7, 8, 9, 100, 20, 21, 22, 23, 24], ["lo"] * 10 + ["hi"] * 5)
    d = aggregate(f, _cfg("box", column="X", group_by=["G"], sort="desc"))
    assert list(d.table["category"]) == ["hi", "lo"]               # medians 22 and 5.5
    assert d.table.set_index("category").loc["lo", "n_outliers"] == 1
    assert d.notes["outliers"].to_dict("records") == [{"category": "lo", "group": "lo", "value": 100.0}]
    assert d.table.set_index("category").loc["hi", "count"] == 5
    d = aggregate(f, _cfg("box", column="X", group_by=["G"], sort="alpha"))
    assert list(d.table["category"]) == ["hi", "lo"]
    d = aggregate(f, _cfg("box", column="X", group_by=["G"], sort="asc"))
    assert list(d.table["category"]) == ["lo", "hi"]


def test_box_plot_without_groups_is_one_box_named_for_the_field():
    d = aggregate(_numbers(range(1, 21)), _cfg("box", column="X"))
    assert list(d.table["category"]) == ["X"] and d.groups == []
    assert d.table["median"].iloc[0] == 10.5


def test_box_plot_warns_when_a_group_has_too_few_values():
    f = _numbers([1, 2, 3, 10, 11, 12, 13, 14, 15], ["tiny"] * 3 + ["ok"] * 6)
    d = aggregate(f, _cfg("box", column="X", group_by=["G"]))
    assert any("Fewer than 5 values for tiny" in w for w in d.warnings)


# ── scatter ───────────────────────────────────────────────────────────────────

def _pairs():
    return pd.DataFrame({"X": ["1", "2", "3", "4", "5", "", "7"],
                         "Y": ["3", "5", "7", "9", "11", "13", "oops"],
                         "G": ["a", "a", "b", "b", "a", "b", "a"]})


def test_scatter_plots_only_rows_with_both_numbers_and_says_how_many_were_not():
    d = aggregate(_pairs(), _cfg("scatter", column="X", value_field="Y"))
    assert len(d.table) == 5 and d.valid_n == 5                    # rows 6 and 7 lack a number
    assert any("2 of 7 rows lack a number" in w for w in d.warnings)
    assert d.table[["x", "y"]].iloc[0].tolist() == [1.0, 3.0]


def test_scatter_fit_is_the_least_squares_line():
    # y = 2x + 1 exactly.
    d = aggregate(_pairs(), _cfg("scatter", column="X", value_field="Y"))
    fit = d.notes["fit"]
    assert fit["slope"] == pytest.approx(2.0) and fit["intercept"] == pytest.approx(1.0)
    assert fit["r"] == pytest.approx(1.0) and fit["n"] == 5
    assert d.base_note == ""                                       # not reported until asked for
    cfg = _cfg("scatter", column="X", value_field="Y")
    cfg.display.trend_line = True
    note = aggregate(_pairs(), cfg).base_note
    assert note.startswith("Line of best fit: Y = 1 + 2 x X") and "r = 1.00, n = 5" in note


def test_scatter_needs_a_second_field_and_two_numeric_ones():
    with pytest.raises(ChartBuildError, match="second numeric field"):
        aggregate(_pairs(), _cfg("scatter", column="X"))
    f = pd.DataFrame({"X": ["a", "b"], "Y": ["c", "d"]})
    with pytest.raises(ChartBuildError, match="No row has a number in both"):
        aggregate(f, _cfg("scatter", column="X", value_field="Y"))


def test_scatter_split_by_colours_groups_gold_then_blue():
    d, _ = build_data(_pairs(), _cfg("scatter", column="X", value_field="Y", group_by=["G"]))
    assert dict(zip(d.table["group"], d.table["color"])) == {"a": "#BC912C", "b": "#15284B"}
    d, _ = build_data(_pairs(), _cfg("scatter", column="X", value_field="Y"))
    assert set(d.table["color"]) == {"#BC912C"}


# ── line and area ─────────────────────────────────────────────────────────────

def _dates():
    return pd.DataFrame({
        "When": ["2026-01-05", "2026-01-20", "2026-03-02", "2026-03-15", "2026-03-30",
                 "2026-05-01", "", "not a date"],
        "V": ["10", "20", "30", "40", "50", "60", "70", "80"],
        "G": ["a", "b", "a", "a", "b", "a", "a", "a"]})


def test_grain_is_chosen_from_the_span():
    assert numeric.choose_grain(30) == "day" and numeric.choose_grain(90) == "day"
    assert numeric.choose_grain(91) == "month" and numeric.choose_grain(3 * 365) == "month"
    assert numeric.choose_grain(3 * 365 + 1) == "year"


def test_line_counts_rows_per_month_and_shows_empty_months_as_zero():
    # Jan 2, Feb 0 (empty), Mar 3, Apr 0, May 1.  The span is 116 days -> months.
    d = aggregate(_dates(), _cfg("line", column="When", aggregation="count"))
    assert d.categories == ["2026-01", "2026-02", "2026-03", "2026-04", "2026-05"]
    assert d.table["value"].tolist() == [2, 0, 3, 0, 1]
    assert d.table["x"].tolist()[0] == "2026-01-01"
    assert d.valid_n == 6 and d.value_title == "Number of responses"
    assert any("could not be read" in w for w in d.warnings)        # "not a date"


def test_line_means_leave_gaps_where_there_is_no_data():
    d = aggregate(_dates(), _cfg("line", column="When", aggregation="mean", value_field="V"))
    vals = d.table["value"].tolist()
    assert vals[0] == 15 and vals[2] == 40 and vals[4] == 60      # (10+20)/2, (30+40+50)/3, 60
    assert np.isnan(vals[1]) and np.isnan(vals[3])                 # empty months are gaps, not zeros
    assert d.value_title == "Mean of V"


def test_line_split_by_gives_one_series_per_group_with_a_shared_axis():
    d = aggregate(_dates(), _cfg("line", column="When", aggregation="count", group_by=["G"]))
    assert d.groups == ["a", "b"] and len(d.table) == 2 * len(d.categories)
    assert _cell(d, group="b", category="2026-03")["value"] == 1
    assert _cell(d, group="a", category="2026-03")["value"] == 2


def test_line_grain_can_be_forced_and_labels_say_what_they_are():
    cfg = _cfg("line", column="When", aggregation="count")
    cfg.display.time_grain = "quarter"
    assert aggregate(_dates(), cfg).categories == ["2026 Q1", "2026 Q2"]
    cfg.display.time_grain = "year"
    assert aggregate(_dates(), cfg).categories == ["2026"]
    cfg.display.time_grain = "week"
    assert aggregate(_dates(), cfg).categories[0] == "Week of 2026-01-05"


def test_line_percent_is_each_periods_share_of_its_group():
    d = aggregate(_dates(), _cfg("line", column="When", aggregation="percent"))
    assert d.table["percent"].sum() == pytest.approx(100.0) and d.is_percent
    assert _cell(d, category="2026-03")["percent"] == pytest.approx(50.0)      # 3 of 6


def test_line_over_a_non_date_field_orders_numbers_numerically():
    f = pd.DataFrame({"Year": ["10", "9", "2", "10", "9", "10"]})
    d = aggregate(f, _cfg("line", column="Year", aggregation="count"))
    assert d.categories == ["2", "9", "10"] and d.table["value"].tolist() == [1, 2, 3]
    assert d.notes["x_kind"] == "ordinal"
    f = pd.DataFrame({"Term": ["Spring", "Fall", "Spring"]})
    assert aggregate(f, _cfg("line", column="Term", aggregation="count")).categories == ["Spring", "Fall"]


def test_line_measure_needs_a_measure_field():
    with pytest.raises(ChartBuildError, match="value field"):
        aggregate(_dates(), _cfg("area", column="When", aggregation="sum"))


# ── rendering ─────────────────────────────────────────────────────────────────

def _big():
    rng = np.random.default_rng(1)
    n = 120
    x = rng.normal(15, 5, n).round(1)
    return pd.DataFrame({
        "Hours": x.astype(str), "GPA": (2 + 0.03 * x + rng.normal(0, 0.3, n)).round(2).astype(str),
        "Year": rng.choice(["First-year", "Senior"], n),
        "When": [f"2025-{m:02d}-{d:02d}" for m, d in zip(rng.integers(1, 13, n), rng.integers(1, 28, n))]})


CASES = [("histogram", dict(column="Hours")), ("histogram", dict(column="Hours", group_by=["Year"])),
         ("box", dict(column="Hours")), ("box", dict(column="Hours", group_by=["Year"])),
         ("scatter", dict(column="Hours", value_field="GPA")),
         ("scatter", dict(column="Hours", value_field="GPA", group_by=["Year"])),
         ("line", dict(column="When", aggregation="count")),
         ("line", dict(column="When", aggregation="count", group_by=["Year"])),
         ("area", dict(column="When", aggregation="count", group_by=["Year"])),
         ("area", dict(column="When", aggregation="mean", value_field="GPA"))]


@pytest.mark.parametrize("chart,kw", CASES)
def test_every_numeric_chart_is_valid_vega_lite_and_draws(chart, kw):
    alt = pytest.importorskip("altair")
    cfg = _cfg(chart, **kw)
    cfg.labels.title, cfg.labels.footnote = "T", "Source: X"
    if chart == "scatter":
        cfg.display.trend_line = True
    d, t = build_data(_big(), cfg)
    spec = build_spec(d, cfg, t)
    alt.Chart.from_dict(spec)
    if export.image_export_available():
        assert export.render_image(spec, "png", 96)[:4] == b"\x89PNG"


def test_histogram_bars_start_at_zero_and_ticks_sit_on_the_bin_edges():
    cfg = _cfg("histogram", column="Hours", aggregation="count")
    cfg.display.bins = 6
    d, t = build_data(_big(), cfg)
    enc = build_spec(d, cfg, t)["layer"][0]["encoding"]
    assert enc["y2"] == {"datum": 0}
    assert len(enc["x"]["axis"]["values"]) == 7
    assert not d.is_percent and "labelExpr" not in enc["y"]["axis"]     # a count axis has no % sign
    cfg.aggregation = "percent"
    d, t = build_data(_big(), cfg)
    assert build_spec(d, cfg, t)["layer"][0]["encoding"]["y"]["axis"]["labelExpr"] == "datum.label + '%'"


def test_box_plot_draws_whisker_box_median_and_outlier_layers():
    f = _numbers([1, 2, 3, 4, 5, 6, 7, 8, 9, 100])
    d, t = build_data(f, _cfg("box", column="X"))
    layers = build_spec(d, _cfg("box", column="X"), t)["layer"]
    kinds = [layer["mark"]["type"] for layer in layers]
    assert kinds[:3] == ["rule", "bar", "bar"] and "point" in kinds
    outliers = next(layer for layer in layers if layer["mark"]["type"] == "point")
    assert outliers["data"]["values"][0]["value"] == 100.0
    assert layers[1]["mark"]["color"] == "#BC912C"               # default gold for a single box


def test_scatter_trend_line_is_a_regression_layer_and_optional():
    cfg = _cfg("scatter", column="Hours", value_field="GPA", group_by=["Year"])
    d, t = build_data(_big(), cfg)
    assert len(build_spec(d, cfg, t)["layer"]) == 1
    cfg.display.trend_line = True
    d, t = build_data(_big(), cfg)
    fit = build_spec(d, cfg, t)["layer"][1]
    assert fit["transform"] == [{"regression": "y", "on": "x", "groupby": ["group"]}]


def test_area_stacks_counts_by_group_but_not_averages():
    cfg = _cfg("area", column="When", aggregation="count", group_by=["Year"])
    d, t = build_data(_big(), cfg)
    assert build_spec(d, cfg, t)["layer"][0]["encoding"]["y"]["stack"] == "zero"
    cfg = _cfg("area", column="When", aggregation="mean", value_field="GPA", group_by=["Year"])
    d, t = build_data(_big(), cfg)
    assert build_spec(d, cfg, t)["layer"][0]["encoding"]["y"]["stack"] is None


def test_line_marks_take_the_theme_colour_and_a_long_axis_is_thinned():
    cfg = _cfg("line", column="When", aggregation="count")
    cfg.display.time_grain = "day"
    d, t = build_data(_big(), cfg)
    spec = build_spec(d, cfg, t)
    mark = spec["layer"][0]["mark"]
    assert mark["color"] == "#BC912C" and mark["point"]["color"] == "#BC912C"
    assert len(spec["layer"][0]["encoding"]["x"]["axis"]["values"]) <= 13


# ── tables ────────────────────────────────────────────────────────────────────

def test_summary_tables_for_each_numeric_chart():
    cfg = _cfg("histogram", column="X", aggregation="count")
    cfg.display.bins = 5
    d = aggregate(_numbers(range(10)), cfg)
    t = export.summary_table(d, cfg)
    assert list(t.columns) == ["Range", "Count", "Percent", "Valid N"] and t["Count"].sum() == 10
    assert t["Range"].iloc[0] == "0 to 1.8"

    cfg = _cfg("box", column="X", group_by=["G"])
    f = _numbers([1, 2, 3, 4, 5, 6, 7, 8, 9, 100], ["g"] * 10)
    t = export.summary_table(aggregate(f, cfg), cfg)
    assert list(t.columns)[:2] == ["G", "N"] and t["Median"].iloc[0] == 5.5
    assert t["Values beyond the whiskers"].iloc[0] == 1

    cfg = _cfg("scatter", column="X", value_field="Y", group_by=["G"])
    t = export.summary_table(aggregate(_pairs(), cfg), cfg)
    assert list(t.columns) == ["X", "Y", "G"] and len(t) == 5

    cfg = _cfg("line", column="When", aggregation="count")
    t = export.summary_table(aggregate(_dates(), cfg), cfg)
    assert list(t.columns) == ["When", "Number of responses", "Rows"]
    assert t["Number of responses"].tolist() == [2, 0, 3, 0, 1]


# ── which charts are offered, and what they need ──────────────────────────────

def test_numbers_and_dates_offer_their_own_charts_first():
    assert vocab.available_charts("single", False, "numeric")[:3] == ["histogram", "box", "scatter"]
    assert vocab.available_charts("single", False, "datetime")[:2] == ["line", "area"]
    assert vocab.available_charts("single", False, "categorical")[0] == "bar_horizontal"
    assert "histogram" not in vocab.available_charts("matrix", False, "numeric")


def test_a_newly_chosen_chart_gets_the_summary_it_needs():
    assert vocab.settle_aggregation("line", "percent") == "count"
    assert vocab.settle_aggregation("line", "mean") == "mean"
    assert vocab.settle_aggregation("histogram", "mean") == "percent"
    assert vocab.settle_aggregation("histogram", "count") == "count"
    assert vocab.settle_aggregation("box", "sum") == "count"
    assert vocab.settle_aggregation("scatter", "median") == "count"
    assert vocab.settle_aggregation("bar", "percent") == "percent"
    assert vocab.is_numeric_chart("box") and not vocab.is_numeric_chart("bar")


def test_numeric_charts_do_not_change_the_source_data():
    f = _big()
    before = f.copy(deep=True)
    for chart, kw in CASES:
        build_data(f, _cfg(chart, **kw))
    pd.testing.assert_frame_equal(f, before)
