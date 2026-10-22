#!/usr/bin/env python
"""
Charts of themes (Surveys and Interviews, Explore) — the chart builder (v4.6, Phase B1),
simplified in Update 3, phase 4b (item 4b.5d).

On the page: what to chart, one-click starting points, the chart, and Save or share. The chart type,
the fields on each shelf, the title and the saved charts are folded under "Change this chart" and
"Saved charts".

The Analysis page answers the questions the tool decided are interesting:
frequency, co-occurrence, code × descriptor. This page answers the ones the
analyst decided are interesting. Pick a mark, drop fields on X, Y, Colour and
Split-by, and read the result — the shape Tableau made ordinary and no
qualitative package offers without a licence.

All the grammar lives in `core/chart_spec.py`, which imports no front end. This
module is the Streamlit skin over it: widgets in, `ChartRequest` out, spec back,
Altair renders it. The desktop build can put its own skin on the same engine, and
`PORTED_BACK.md` §9 is the reason that boundary is drawn so hard.

Per `app/__init__`, this module imports only from `core/`, `analysis/`, and
Streamlit — never from `streamlit_app`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Dict, Optional, Tuple

import altair as alt
import pandas as pd
import streamlit as st
from app.shared.layout import stretch

from analysis.crosstab import join_descriptors
from core.chart_spec import (
    AGGREGATES, MARKS, SHELVES, ChartRequest, Shelf, aggregate, build_spec,
    can_build, describe, infer_field_types, problems, request_from_dict,
    request_to_dict, suggested_charts)
from core.model import SavedChart
from core.project import Project

#: An aggregated chart is small whatever the corpus size, so this only matters
#: for the marks that plot rows individually. Never truncate: a truncated chart
#: is a wrong chart, silently.
_UNAGGREGATED_ROW_WARNING = 20_000

_SHELF_LABELS = {
    "x": "Across",
    "y": "Up",
    "color": "Colour",
    "facet": "Split by",
}

_AGGREGATE_LABELS = {
    "": "(as it is)",
    "count": "Count of rows",
    "distinct": "Count of distinct values",
    "sum": "Sum",
    "mean": "Mean",
    "median": "Median",
    "min": "Minimum",
    "max": "Maximum",
}


def render_charts_page(
    store_path: Optional[Path],
    *,
    chart_export: Optional[Callable] = None,
) -> None:
    """Render the chart builder for the active project store."""
    if store_path is None or not Path(store_path).exists():
        st.info("Open or create a project to chart it.")
        return

    frame, source_label = _load_frame(store_path)
    if frame is None or frame.empty:
        st.info(
            "This project has no codings yet. Code some answers or passages, and there will be "
            "something to chart."
        )
        return

    field_types = infer_field_types(frame)
    st.caption(f"{len(frame):,} rows from {source_label}.")
    if len(frame) > _UNAGGREGATED_ROW_WARNING:
        st.caption(
            f"With {len(frame):,} rows, a chart that plots them individually (a "
            "scatter, or any shelf left on '(as it is)') will be slow to draw. An "
            "aggregate on Y groups them first."
        )

    _render_saved_charts(store_path, field_types)
    request = _build_request(field_types, frame)
    found = problems(request, field_types)

    if not can_build(request, field_types):
        for message in found:
            st.warning(message)
        st.caption("Pick a starting point above, or choose what to show under Change this chart.")
        return

    for message in found:  # advice only, by definition of can_build
        st.info(message)

    # Aggregated here, not by Vega. The desktop build paints pixels and so has
    # to know the numbers; computing them in one place is what stops the two
    # builds drawing different charts from the same request. It also means the
    # exported .csv is the data actually plotted, and a coding table no longer
    # travels to the browser row by row.
    plotted = aggregate(frame, request, field_types)
    spec = build_spec(request, field_types, pre_aggregated=True)
    spec["data"] = {"values": plotted.to_dict("records")}

    try:
        chart = alt.Chart.from_dict(spec)
    except Exception as exc:  # noqa: BLE001 - a bad spec must not blank the page
        st.error(f"That combination could not be drawn: {exc}")
        return

    st.altair_chart(chart, **stretch())

    with st.expander("Save or share this chart"):
        if chart_export is not None:
            chart_export(chart, request.title or "chart", plotted, key_prefix="chartbuilder", fold=False)
        _render_save(store_path, request)

    with st.expander("The numbers behind this chart"):
        st.dataframe(plotted, **stretch(), height=280)


# ── saved charts ──────────────────────────────────────────────────────────────

def _render_saved_charts(store_path: Path, field_types: Dict[str, str]) -> None:
    """Reopen a chart saved with this project.

    The PNG export answers "get this figure into the document". This answers the
    other question a study that keeps collecting data has: redraw it against the
    project as it stands *now*. A figure built after twenty interviews comes back
    after forty without anyone remembering how it was made.
    """
    with Project.open(store_path) as project:
        saved = project.list_charts()
    if not saved:
        return

    with st.expander(f"Charts you kept ({len(saved)})"):
        for chart in saved:
            columns = st.columns([5, 1, 1])
            columns[0].markdown(
                f"**{chart.name}**: {describe(request_from_dict(chart.spec))}")
            if columns[1].button("Open", key=f"chart_open_{chart.chart_id}"):
                _adopt(request_from_dict(chart.spec))
                st.session_state["chart_source"] = (
                    "Codings with respondent details"
                    if chart.source == "codings_with_descriptors" else "Codings")
                st.rerun()
            if columns[2].button("Delete", key=f"chart_del_{chart.chart_id}"):
                with Project.open(store_path) as project:
                    project.delete_chart(chart.name)
                st.rerun()


def _render_save(store_path: Path, request: ChartRequest) -> None:
    """Save this chart's definition, rather than its picture, with the project."""
    st.markdown("**Keep this chart with the project**")
    st.caption("Keeps how the chart is made, so opening it later draws it from the project as it "
               "stands then. The picture and the data are a moment; this keeps the method.")
    name = st.text_input("Name", value=request.title, key="chart_save_name",
                         placeholder="Themes by class year")
    if st.button("Keep it", key="chart_save_btn", disabled=not name.strip()):
        source = ("codings_with_descriptors"
                  if st.session_state.get("chart_source", "").endswith("descriptors")
                  else "codings")
        with Project.open(store_path) as project:
            project.save_chart(SavedChart(
                chart_id="", name=name.strip(), spec=request_to_dict(request), source=source))
        st.success(f"Kept as “{name.strip()}”. It is drawn again from the project whenever you open it.")


# ── data ──────────────────────────────────────────────────────────────────────

def _load_frame(store_path: Path) -> Tuple[Optional[pd.DataFrame], str]:
    """The table to chart, chosen by the analyst.

    "Codings with descriptors" is the mixed-methods table — a theme against class
    year, program, first-generation status — and is the reason this page earns
    its place next to the fixed Analysis charts.
    """
    choice = st.radio(
        "What to chart",
        ["Codings", "Codings with respondent details"],
        format_func=lambda v: {"Codings": "The codes", "Codings with respondent details":
                               "The codes, with respondent details"}[v],
        horizontal=True,
        key="chart_source",
        help=(
            "The codes: one row for each time a code was applied. With respondent details: the same "
            "rows with each person's class year, program and so on beside them."
        ),
    )

    with Project.open(store_path) as project:
        coding = project.coding_table()
        descriptors = project.descriptor_table() if choice.endswith("descriptors") else None

    if choice == "Codings":
        return coding, "this project's codings"

    if descriptors is None or descriptors.empty:
        st.info(
            "This project has no respondent details yet. Choose them under Load, More options, "
            "to chart themes by group."
        )
        return coding, "this project's codings"

    return join_descriptors(coding, descriptors), "codings joined to respondent details"


# ── the shelves ───────────────────────────────────────────────────────────────

def _build_request(field_types: Dict[str, str], frame: pd.DataFrame) -> ChartRequest:
    """The widgets, and the `ChartRequest` they add up to."""
    _render_suggestions(field_types, frame)

    with st.expander("Change this chart"):
        mark_keys = list(MARKS)
        mark = st.selectbox(
            "Chart type", mark_keys,
            format_func=lambda key: MARKS[key].label,
            key="chart_mark",
        )
        st.caption(MARKS[mark].hint)

        kind = MARKS[mark]
        needed = set(kind.requires)
        shown = [name for name in SHELVES if name in needed or name in kind.optional]

        columns = st.columns(len(shown))
        shelves: Dict[str, Shelf] = {}
        for column, name in zip(columns, shown):
            with column:
                shelves[name] = _render_shelf(name, field_types, mark=mark,
                                              required=name in needed)

        title = st.text_input("Chart title (optional)", key="chart_title")

    return ChartRequest(
        mark=mark,
        x=shelves.get("x", Shelf()),
        y=shelves.get("y", Shelf()),
        color=shelves.get("color", Shelf()),
        facet=shelves.get("facet", Shelf()),
        title=title.strip(),
    )


def _render_shelf(name: str, field_types: Dict[str, str], *,
                  mark: str, required: bool) -> Shelf:
    """One shelf: a field, how to aggregate it, and how to sort it."""
    label = _SHELF_LABELS[name] + ("" if required else " (optional)")
    fields = [""] + sorted(field_types)

    field = st.selectbox(
        label, fields, key=f"chart_shelf_{name}_field",
        format_func=lambda f: "— none —" if f == "" else f,
    )

    # Colour and facet describe categories; aggregating them is meaningless.
    if name in ("color", "facet"):
        return Shelf(field=field)

    # Every aggregate is always offered, including the ones this field cannot
    # support. Two reasons, and the second is the real one:
    #
    #   1. A list that silently shrinks when the field changes is a list whose
    #      stored selection can stop being one of its own options, which is an
    #      error in Streamlit rather than a graceful reset.
    #   2. `core/chart_spec.problems()` already explains that a text column has
    #      no mean, in a sentence. Hiding the option instead would put the rule
    #      in two places and tell the analyst nothing about why.
    aggregate = st.selectbox(
        "how", [""] + list(AGGREGATES), key=f"chart_shelf_{name}_agg",
        format_func=lambda key: _AGGREGATE_LABELS.get(key, key.title()),
        label_visibility="collapsed",
    )

    sort = None
    if st.checkbox("sort by size", key=f"chart_shelf_{name}_sort"):
        # "Biggest first" means sorting a category by the *measure*, which sits
        # on the other axis — and the axes swap for a horizontal bar, so the
        # channel to sort by depends on the chart, not just on the shelf.
        horizontal = mark == "bar_horizontal"
        if name == "x":
            sort = "-x" if horizontal else "-y"
        else:
            sort = "-y" if horizontal else "-x"

    return Shelf(field=field, aggregate=aggregate or None, sort=sort)


def _render_suggestions(field_types: Dict[str, str], frame: pd.DataFrame) -> None:
    """One-click starting points, before the analyst has learned what a shelf is.

    The frame goes in so identifier and huge-cardinality columns are filtered by
    what they contain, not only by what they are called.
    """
    suggestions = suggested_charts(field_types, frame=frame)
    if not suggestions:
        return

    st.caption("**Start here.** One click, then change it if you like:")
    for index, (column, request) in enumerate(
            zip(st.columns(len(suggestions)), suggestions)):
        if column.button(request.title, key=f"chart_suggest_{index}",
                         **stretch()):
            _adopt(request)
            st.rerun()


def _adopt(request: ChartRequest) -> None:
    """Push a suggestion into the widgets' own keys.

    Written before the widgets are created on the next run, which is the only
    moment Streamlit allows a widget-backed key to be assigned.
    """
    st.session_state["chart_mark"] = request.mark
    st.session_state["chart_title"] = request.title
    for name in SHELVES:
        shelf = request.shelf(name)
        st.session_state[f"chart_shelf_{name}_field"] = shelf.field
        st.session_state[f"chart_shelf_{name}_agg"] = shelf.aggregate or ""
        st.session_state[f"chart_shelf_{name}_sort"] = bool(shelf.sort)
