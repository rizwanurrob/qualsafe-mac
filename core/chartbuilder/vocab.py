"""
The words both front ends use for the chart builder's choices.

One place, so the Streamlit page and the desktop view cannot drift into calling
the same option two different things. Keys are the config values; values are what
the analyst reads.
"""

from __future__ import annotations

CHART_LABELS = {
    "bar_horizontal": "Horizontal bar", "bar": "Vertical bar",
    "grouped_bar": "Grouped bar", "stacked_bar": "Stacked bar",
    "normalized_bar": "100% stacked bar", "donut": "Donut", "pie": "Pie",
    "heatmap": "Heatmap", "line": "Line", "area": "Area", "scatter": "Scatter",
    "histogram": "Histogram", "box": "Box plot"}
KIND_LABELS = {
    "single": "One question (single choice)",
    "matrix": "Matrix / Likert (several related columns)",
    "multi": "Select all that apply (several answers in one cell)",
    "text": "Free text"}
AGG_LABELS = {"count": "Count", "percent": "Percent", "sum": "Sum", "mean": "Mean",
              "median": "Median", "min": "Minimum", "max": "Maximum",
              "distinct": "Distinct count"}
SORT_LABELS = {"desc": "Highest to lowest", "asc": "Lowest to highest",
               "alpha": "Alphabetical", "source": "Original order in the file",
               "scale": "Scale order (Likert)", "custom": "My order (Position column)"}
DENOM_LABELS = {"valid": "Valid responses (blanks left out)",
                "all_rows": "All rows, blanks included", "custom": "A number I enter"}
OP_LABELS = {"in": "is one of", "not_in": "is not one of", "gt": "is greater than",
             "ge": "is at least", "lt": "is less than", "le": "is at most",
             "between": "is between", "contains": "contains",
             "is_missing": "is blank", "not_missing": "is not blank"}
DELIM_LABELS = {"comma": "Comma", "semicolon": "Semicolon", "pipe": "Pipe |",
                "newline": "New line", "custom": "Something else"}
LEGEND_LABELS = {"right": "Right", "bottom": "Bottom", "top": "Top", "left": "Left",
                 "none": "Hidden"}
SIZE_LABELS = {"small": "Small", "medium": "Medium", "large": "Large",
               "xlarge": "Extra large"}
DPIS = [96, 150, 300, 600]
PERCENT_OR_COUNT = ("percent", "count")
TIME_GRAIN_LABELS = {"auto": "Automatic", "day": "Day", "week": "Week", "month": "Month",
                     "quarter": "Quarter", "year": "Year"}


def is_numeric_chart(chart_type: str) -> bool:
    """Charts drawn from the rows themselves (distribution, trend, relationship)."""
    from core.chartbuilder.config import NUMERIC_CHARTS
    return chart_type in NUMERIC_CHARTS


def settle_aggregation(chart_type: str, aggregation: str) -> str:
    """The aggregation a newly chosen chart type needs, changing it only if it must.

    A trend defaults to counting rows (a share of one group over time is a
    different, less common question); a histogram takes count or percent; a box
    plot and a scatter ignore it, so it is set to something harmless rather than
    left as "mean" with nothing to average.
    """
    from core.chartbuilder.config import MEASURE_AGGREGATIONS
    if chart_type in ("line", "area"):
        return "count" if aggregation == "percent" else aggregation
    if chart_type == "histogram":
        return aggregation if aggregation in PERCENT_OR_COUNT else "percent"
    if chart_type in ("box", "scatter"):
        return "count" if aggregation in MEASURE_AGGREGATIONS else aggregation
    return aggregation

#: Sorts offered for a matrix question (scale order first) and for the rest.
MATRIX_SORTS = ["scale", "desc", "asc", "alpha", "source", "custom"]
OTHER_SORTS = ["desc", "asc", "alpha", "source", "custom"]


def available_charts(kind: str, has_groups: bool, column_kind: str = "") -> list:
    """Chart types worth offering for a question, in the order to show them.

    `column_kind` is the profile type of the analysed field ("numeric",
    "datetime", ...): a number offers the distribution charts and a date the
    trend charts, ahead of the category charts.
    """
    from core.chartbuilder.render import AVAILABLE_TYPES

    if kind == "matrix":
        order = ["normalized_bar", "stacked_bar", "grouped_bar", "donut", "pie", "heatmap"]
    elif kind in ("multi", "text"):
        order = ["bar_horizontal", "bar"]
    elif has_groups:
        order = ["grouped_bar", "normalized_bar", "stacked_bar", "heatmap"]
    else:
        order = ["bar_horizontal", "bar", "donut", "pie"]
    if kind == "single":
        if column_kind == "datetime":
            order = ["line", "area"] + order
        elif column_kind == "numeric":
            order = ["histogram", "box", "scatter", "line"] + order
    return [c for c in order if c in AVAILABLE_TYPES]
