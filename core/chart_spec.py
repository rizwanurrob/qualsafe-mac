#!/usr/bin/env python
"""
Shelf-based chart building — the engine behind a Tableau-style chart builder.

The analyst assigns fields to **shelves** (X, Y, Colour, Facet), picks a mark and
an aggregate, and gets a chart. This module is the part that turns those choices
into a figure definition. It draws nothing and imports no front end.

Design decisions
----------------
- **The output is a Vega-Lite spec, not a chart object.** Every piece of the
  pipeline already speaks Vega-Lite: Altair emits it, `core/viz_export.py`
  renders it to PNG/SVG through offline `vl-convert`, and Streamlit displays it.
  So a chart builder adds *no new dependency* — it assembles a dict.

  It also makes a figure a **reproducible artifact**. The exported `.vl.json`
  plus the exported `.csv` reconstruct the chart exactly, on any machine, with no
  QualSafe installed. That is what a methods appendix wants and what no
  commercial rival ships: NVivo, MAXQDA and Dedoose all give you a picture.

- **Pure, and deliberately so.** No Streamlit, no Qt, no Altair at module scope.
  `PORTED_BACK.md` §9 records that this project keeps stranding pure helpers
  behind Streamlit imports and then reimplementing them in the desktop fork. A
  chart builder is the most tempting candidate yet — it is all UI-adjacent
  arithmetic — so it starts on the right side of the line. The desktop app can
  consume the same specs.

- **No colours are baked in.** `core.theme.register_altair_theme` already decides
  what blue means, in both skins. A spec that hardcoded colours would become a
  second source of that decision, which is the drift `core/theme.py` exists to
  stop.

- **Validation speaks English and never guesses.** An impossible combination
  (a pie chart with no category, a mean of a text column) returns a sentence
  saying what is wrong, and no spec. Silently substituting a different chart is
  how a figure ends up in a paper meaning something other than the analyst
  thought.

- **Pie charts are offered with their caveat attached.** They are genuinely the
  right mark for parts of one whole and genuinely bad above a handful of slices,
  so `problems()` says so rather than refusing. Same pattern the project already
  uses for kappa: the caveat travels with the number.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field
from typing import Any, Dict, List, Optional, Sequence

# ── field types ───────────────────────────────────────────────────────────────

#: Vega-Lite's type vocabulary, minus `geojson` which nothing here produces.
QUANTITATIVE = "quantitative"
NOMINAL = "nominal"
ORDINAL = "ordinal"
TEMPORAL = "temporal"


def infer_field_types(df) -> Dict[str, str]:
    """Map each column of a DataFrame to a Vega-Lite type.

    Booleans are nominal, not quantitative: "True" is a category, and averaging
    it produces a proportion that looks like a mean and is not labelled as one.
    """
    import pandas as pd

    types: Dict[str, str] = {}
    for column in df.columns:
        series = df[column]
        if pd.api.types.is_bool_dtype(series):
            types[str(column)] = NOMINAL
        elif pd.api.types.is_numeric_dtype(series):
            types[str(column)] = QUANTITATIVE
        elif pd.api.types.is_datetime64_any_dtype(series):
            types[str(column)] = TEMPORAL
        elif _is_numeric_in_disguise(series):
            types[str(column)] = QUANTITATIVE
        else:
            types[str(column)] = NOMINAL
    return types


def _is_numeric_in_disguise(series) -> bool:
    """Is this object column really numbers?

    `Project.coding_table()` builds a frame from sqlite rows, and a column with
    any NULL in it arrives as dtype ``object`` even when every actual value is a
    float. `weight` and `confidence` are exactly that, so without this the chart
    builder refuses "Sum of weight" as an average of categories — which is both
    wrong and baffling, because the column plainly holds numbers.

    Deliberately strict: **every** non-null value must convert, and a column with
    no values at all stays nominal rather than being guessed into a measure.
    """
    import pandas as pd

    if series.dtype != object:
        return False
    present = series.dropna()
    if present.empty:
        return False
    if present.map(lambda v: isinstance(v, (str, bytes))).any():
        return False
    return not pd.to_numeric(present, errors="coerce").isna().any()


# ── aggregates ────────────────────────────────────────────────────────────────

#: Aggregate name -> whether it needs a quantitative field.
AGGREGATES: Dict[str, bool] = {
    "count": False,      # counts rows; the field is ignored
    "distinct": False,   # counts distinct values of the field
    "sum": True,
    "mean": True,
    "median": True,
    "min": True,
    "max": True,
}

#: What Vega-Lite calls each of them.
_VL_AGGREGATE = {
    "count": "count",
    "distinct": "distinct",
    "sum": "sum",
    "mean": "mean",
    "median": "median",
    "min": "min",
    "max": "max",
}


# ── marks ─────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class MarkKind:
    """One entry in the chart picker."""

    key: str
    label: str
    #: Shelves that must be filled for the chart to mean anything.
    requires: Sequence[str]
    #: Shelves this mark can use but does not need.
    optional: Sequence[str] = ()
    #: One line for the UI, in the analyst's language rather than Vega-Lite's.
    hint: str = ""


MARKS: Dict[str, MarkKind] = {
    "bar": MarkKind(
        "bar", "Bar", ("x", "y"), ("color", "facet"),
        "Compare a measure across categories."),
    "bar_horizontal": MarkKind(
        "bar_horizontal", "Bar (horizontal)", ("x", "y"), ("color", "facet"),
        "Same as Bar, but category names read left-to-right — use it when they are words."),
    "stacked_bar": MarkKind(
        "stacked_bar", "Stacked bar", ("x", "y", "color"), ("facet",),
        "Break each bar into parts. The total stays readable; the parts do not."),
    "normalized_bar": MarkKind(
        "normalized_bar", "100% stacked bar", ("x", "y", "color"), ("facet",),
        "Compare composition when the totals differ. Every bar becomes 100%."),
    "grouped_bar": MarkKind(
        "grouped_bar", "Grouped bar", ("x", "y", "color"), ("facet",),
        "Bars side by side instead of stacked — easier to compare the parts."),
    "line": MarkKind(
        "line", "Line", ("x", "y"), ("color", "facet"),
        "A measure over an ordered sequence."),
    "area": MarkKind(
        "area", "Area", ("x", "y"), ("color", "facet"),
        "A line with the space beneath filled; stacks when a colour is set."),
    "point": MarkKind(
        "point", "Scatter", ("x", "y"), ("color", "facet"),
        "Two measures against each other, one dot per row."),
    "pie": MarkKind(
        "pie", "Pie", ("color", "y"), (),
        "Parts of one whole. Hard to read past about six slices."),
    "donut": MarkKind(
        "donut", "Donut", ("color", "y"), (),
        "A pie with the middle removed. Same strengths and same limits."),
    "heatmap": MarkKind(
        "heatmap", "Heatmap", ("x", "y", "color"), (),
        "A grid coloured by a measure — good for two categories at once."),
}

#: Shelf order, for a UI that wants to lay them out consistently.
SHELVES = ("x", "y", "color", "facet")

_STACKED = {"stacked_bar", "normalized_bar"}
_BARS = {"bar", "bar_horizontal", "stacked_bar", "normalized_bar", "grouped_bar"}
_ARCS = {"pie", "donut"}


# ── the request ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Shelf:
    """One field assignment.

    `aggregate=None` plots the field as it is. `"count"` ignores the field
    entirely — it counts rows — which is why `field` may be empty for it.
    """

    field: str = ""
    aggregate: Optional[str] = None
    sort: Optional[str] = None       # "ascending" | "descending" | None
    bin: bool = False

    @property
    def is_empty(self) -> bool:
        return not self.field and self.aggregate != "count"


@dataclass(frozen=True)
class ChartRequest:
    """Everything the analyst chose. A plain value, comparable and hashable."""

    mark: str = "bar"
    x: Shelf = dataclass_field(default_factory=Shelf)
    y: Shelf = dataclass_field(default_factory=Shelf)
    color: Shelf = dataclass_field(default_factory=Shelf)
    facet: Shelf = dataclass_field(default_factory=Shelf)
    title: str = ""
    #: Chart size in points. None lets the container decide.
    width: Optional[int] = None
    height: Optional[int] = None

    def shelf(self, name: str) -> Shelf:
        return getattr(self, name)


# ── validation ────────────────────────────────────────────────────────────────

def problems(request: ChartRequest, field_types: Dict[str, str]) -> List[str]:
    """Everything wrong with this request, in plain sentences. Empty means fine.

    Warnings and errors are not separated: a caller that wants to block on the
    hard ones can check `can_build`, and the honest thing to show an analyst is
    the whole list either way.
    """
    found: List[str] = []
    mark = MARKS.get(request.mark)
    if mark is None:
        return [f"'{request.mark}' is not a chart type this builder knows."]

    for shelf_name in mark.requires:
        if request.shelf(shelf_name).is_empty:
            found.append(f"{mark.label} needs a field on {_shelf_label(shelf_name, request.mark)}.")

    for shelf_name in SHELVES:
        shelf = request.shelf(shelf_name)
        if shelf.is_empty:
            continue
        if shelf.field and shelf.field not in field_types:
            found.append(f"There is no column called '{shelf.field}'.")
            continue
        if shelf.aggregate and shelf.aggregate not in AGGREGATES:
            found.append(f"'{shelf.aggregate}' is not an aggregate this builder knows.")
            continue
        if (shelf.aggregate and AGGREGATES[shelf.aggregate]
                and field_types.get(shelf.field) != QUANTITATIVE):
            found.append(
                f"'{shelf.field}' holds categories, so it has no {shelf.aggregate}. "
                f"Use Count, or put a number on that shelf.")

    found.extend(_advice(request, field_types))
    return found


def _advice(request: ChartRequest, field_types: Dict[str, str]) -> List[str]:
    """Caveats that do not make the chart impossible, only misleading."""
    notes: List[str] = []
    if request.mark in _ARCS and not request.color.is_empty:
        notes.append(
            "A pie shows parts of one whole. If these categories are not parts of "
            "the same total, or there are more than about six, a bar chart is read "
            "more accurately.")
    if request.mark == "normalized_bar":
        notes.append(
            "Every bar becomes 100%, so the underlying totals disappear. State the "
            "counts alongside if some categories are much rarer than others.")
    if request.mark == "point" and field_types.get(request.x.field) == NOMINAL \
            and field_types.get(request.y.field) == NOMINAL:
        notes.append(
            "Both axes hold categories, so the dots can only overlap. A heatmap "
            "shows the same pairing with a readable count.")
    return notes


def can_build(request: ChartRequest, field_types: Dict[str, str]) -> bool:
    """True when a spec can be produced — advice alone does not block."""
    blocking = set(problems(request, field_types)) - set(_advice(request, field_types))
    return not blocking


# ── the spec ──────────────────────────────────────────────────────────────────

def build_spec(request: ChartRequest, field_types: Dict[str, str], *,
               pre_aggregated: bool = False) -> Dict[str, Any]:
    """Assemble a Vega-Lite v5 spec. **No data** — the caller attaches it.

    `pre_aggregated=True` describes a frame that `aggregate()` has already
    reduced: the encodings point at `MEASURE` and carry no `aggregate`, so Vega
    plots the numbers rather than recomputing them. Both front ends use it, which
    is what guarantees the painted chart and the specified chart are the same
    chart.

    Leaving data out keeps this function pure and cheap, lets a caller decide
    between inline values and a URL, and means a spec can be built and validated
    before any rows are loaded.

    Raises ValueError when the request cannot be built; check `can_build` first
    if you want the reason rather than the exception.
    """
    if not can_build(request, field_types):
        raise ValueError("; ".join(problems(request, field_types)))

    horizontal = request.mark == "bar_horizontal"
    encode = (lambda shelf, **kw: _encode_measured(shelf, field_types, **kw))         if pre_aggregated else (lambda shelf, **kw: _encode(shelf, field_types, **kw))

    spec: Dict[str, Any] = {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "mark": _mark_definition(request.mark),
        "encoding": {},
    }
    if request.title:
        spec["title"] = request.title
    if request.width:
        spec["width"] = request.width
    if request.height:
        spec["height"] = request.height

    encoding = spec["encoding"]

    if request.mark in _ARCS:
        # An arc has no axes: the measure is the angle and the category the colour.
        encoding["theta"] = encode(request.y, stack="normalize")
        encoding["color"] = encode(request.color)
    elif request.mark == "heatmap":
        encoding["x"] = encode(request.x)
        encoding["y"] = encode(request.y)
        encoding["color"] = encode(request.color)
    else:
        x_shelf, y_shelf = (request.y, request.x) if horizontal else (request.x, request.y)
        encoding["x"] = encode(x_shelf)
        encoding["y"] = encode(y_shelf)
        if not request.color.is_empty:
            encoding["color"] = encode(request.color)
            measure_channel = "x" if horizontal else "y"
            if request.mark in _STACKED:
                encoding[measure_channel]["stack"] = (
                    "normalize" if request.mark == "normalized_bar" else "zero")
            elif request.mark == "grouped_bar":
                # Side-by-side bars. xOffset is Vega-Lite 5.7+; the offset goes on
                # the category axis, which swaps with the chart.
                offset_channel = "yOffset" if horizontal else "xOffset"
                encoding[offset_channel] = {
                    "field": request.color.field,
                    "type": field_types.get(request.color.field, NOMINAL)}
                encoding[measure_channel]["stack"] = None

    if not request.facet.is_empty:
        spec["encoding"]["facet"] = {
            "field": request.facet.field,
            "type": field_types.get(request.facet.field, NOMINAL),
            "columns": 3,
        }

    return spec


def _mark_definition(mark_key: str) -> Dict[str, Any]:
    if mark_key in _BARS:
        return {"type": "bar", "tooltip": True}
    if mark_key == "pie":
        return {"type": "arc", "tooltip": True}
    if mark_key == "donut":
        return {"type": "arc", "innerRadius": 60, "tooltip": True}
    if mark_key == "heatmap":
        return {"type": "rect", "tooltip": True}
    if mark_key == "point":
        return {"type": "point", "filled": True, "tooltip": True}
    if mark_key == "line":
        return {"type": "line", "point": True, "tooltip": True}
    if mark_key == "area":
        return {"type": "area", "tooltip": True}
    return {"type": mark_key, "tooltip": True}


def _encode(shelf: Shelf, field_types: Dict[str, str], *,
            stack: Optional[str] = None) -> Dict[str, Any]:
    """One channel definition."""
    channel: Dict[str, Any] = {}

    if shelf.aggregate == "count":
        # Vega-Lite's count aggregate takes no field, and is always quantitative.
        channel["aggregate"] = "count"
        channel["type"] = QUANTITATIVE
        channel["title"] = "Count"
    else:
        channel["field"] = shelf.field
        if shelf.aggregate:
            channel["aggregate"] = _VL_AGGREGATE[shelf.aggregate]
            channel["type"] = QUANTITATIVE
            channel["title"] = f"{shelf.aggregate.title()} of {shelf.field}"
        else:
            channel["type"] = field_types.get(shelf.field, NOMINAL)

    if shelf.bin and channel.get("type") == QUANTITATIVE and not shelf.aggregate:
        channel["bin"] = True
    if shelf.sort:
        channel["sort"] = shelf.sort
    if stack:
        channel["stack"] = stack
    return channel


def _encode_measured(shelf: Shelf, field_types: Dict[str, str], *,
                     stack: Optional[str] = None) -> Dict[str, Any]:
    """A channel over an already-aggregated frame.

    An aggregated shelf points at `MEASURE` and carries no `aggregate`, because
    the number is already computed; everything else is an ordinary field.
    """
    if shelf.aggregate:
        channel: Dict[str, Any] = {
            "field": MEASURE, "type": QUANTITATIVE, "title": measure_title(shelf)}
    else:
        channel = {"field": shelf.field,
                   "type": field_types.get(shelf.field, NOMINAL)}
        if shelf.bin and channel["type"] == QUANTITATIVE:
            channel["bin"] = True
    if shelf.sort:
        channel["sort"] = shelf.sort
    if stack:
        channel["stack"] = stack
    return channel


def _shelf_label(shelf_name: str, mark_key: str) -> str:
    """What to call a shelf in an error message, per chart type."""
    if mark_key in _ARCS:
        return {"y": "Size", "color": "Slices"}.get(shelf_name, shelf_name.title())
    if mark_key == "heatmap" and shelf_name == "color":
        return "Colour (the measure)"
    return {"x": "X", "y": "Y", "color": "Colour", "facet": "Split by"}[shelf_name]


# ── aggregation ───────────────────────────────────────────────────────────────
#
# Vega-Lite can aggregate for itself, and for a long time it did. That stopped
# being acceptable the moment a second front end had to draw the same chart:
# Qt paints pixels, so it has to know the numbers, and a Qt implementation of
# "count distinct sources per code per subgroup" would be a second answer to a
# question this module already answers.
#
# So aggregation happens here, once, and both builds render an already-reduced
# frame. Two useful side effects: the exported `.csv` becomes the data actually
# plotted rather than the raw rows behind it, and the Streamlit page stops
# inlining a whole coding table into the browser.

#: The column `aggregate()` writes its measure into. Named rather than reusing
#: the source field, because "sum of weight" and "weight" are different columns
#: and conflating them is how a chart ends up plotting the wrong one.
MEASURE = "__measure__"


def measure_title(shelf: "Shelf") -> str:
    """What to call the aggregated axis, in the analyst's words."""
    if shelf.aggregate == "count":
        return "Count"
    if shelf.aggregate == "distinct":
        return f"Distinct {shelf.field}"
    if shelf.aggregate:
        return f"{shelf.aggregate.title()} of {shelf.field}"
    return shelf.field


def aggregate(frame, request: ChartRequest, field_types: Dict[str, str]):
    """Reduce a frame to exactly the rows a chart draws.

    Returns a tidy frame with one column per filled categorical shelf plus
    `MEASURE` for the aggregated value. When no shelf carries an aggregate the
    frame comes back with just the used columns — a scatter plots rows, not
    groups.

    Raises ValueError for a request that cannot be built, same as `build_spec`.
    """
    import pandas as pd

    if not can_build(request, field_types):
        raise ValueError("; ".join(problems(request, field_types)))

    measure_shelf, group_names = _measure_and_groups(request)
    if measure_shelf is None:
        keep = [request.shelf(n).field for n in SHELVES if request.shelf(n).field]
        keep = [c for c in dict.fromkeys(keep) if c in frame.columns]
        return frame[keep].copy() if keep else frame.copy()

    groups = [request.shelf(n).field for n in group_names
              if request.shelf(n).field and request.shelf(n).field in frame.columns]
    groups = list(dict.fromkeys(groups))

    if not groups:
        value = _reduce(frame, measure_shelf)
        return pd.DataFrame([{MEASURE: value}])

    rows = []
    for key, chunk in frame.groupby(groups, dropna=False, sort=False):
        key = key if isinstance(key, tuple) else (key,)
        row = dict(zip(groups, key))
        row[MEASURE] = _reduce(chunk, measure_shelf)
        rows.append(row)

    out = pd.DataFrame(rows, columns=groups + [MEASURE])
    return _sorted(out, request, groups)


def _measure_and_groups(request: ChartRequest):
    """Which shelf is the measure, and which shelves group it.

    Only X and Y can carry an aggregate — colour and facet describe categories,
    which is why `Shelf.aggregate` is never read from them.
    """
    for name in ("y", "x"):
        shelf = request.shelf(name)
        if shelf.aggregate:
            others = [n for n in SHELVES if n != name]
            return shelf, others
    return None, []


def _reduce(chunk, shelf: "Shelf") -> float:
    """One group, one number."""
    if shelf.aggregate == "count":
        return float(len(chunk))
    series = chunk[shelf.field] if shelf.field in chunk.columns else None
    if series is None:
        return 0.0
    if shelf.aggregate == "distinct":
        return float(series.nunique(dropna=True))
    reduced = getattr(series, shelf.aggregate)()
    try:
        return float(reduced)
    except (TypeError, ValueError):  # an empty group, or a non-numeric column
        return 0.0


def _sorted(out, request: ChartRequest, groups):
    """Apply a shelf's sort, in the terms the analyst asked for.

    A sort of `-x`/`-y` means "by the measure, descending" — which is what the
    checkbox in both front ends offers, and what Vega-Lite understands. Sorting
    here as well keeps the painted chart in the same order as the specified one.
    """
    for name in SHELVES:
        shelf = request.shelf(name)
        if not shelf.sort or shelf.field not in groups:
            continue
        descending = str(shelf.sort).startswith("-")
        if str(shelf.sort).lstrip("-") in ("x", "y"):
            return out.sort_values(MEASURE, ascending=not descending,
                                   kind="stable").reset_index(drop=True)
        return out.sort_values(shelf.field, ascending=not descending,
                               kind="stable").reset_index(drop=True)
    return out


# ── saving a chart with the project ───────────────────────────────────────────
#
# A `ChartRequest` is the *definition* of a figure, not the figure. Storing it
# means a chart built after twenty interviews redraws itself after forty, against
# the project as it stands then — which is what a longitudinal study needs and
# what an exported PNG cannot give. It is also what lets a methods appendix cite
# a figure by name instead of describing how it was made.
#
# Round-tripping is the whole contract, so `from_dict(to_dict(x)) == x` is the
# test that matters. `ChartRequest` is frozen, so equality is structural and that
# assertion means what it says.


def request_to_dict(request: ChartRequest) -> Dict[str, Any]:
    """A `ChartRequest` as plain JSON-able data."""
    return {
        "version": 1,
        "mark": request.mark,
        "title": request.title,
        "width": request.width,
        "height": request.height,
        "shelves": {
            name: {
                "field": request.shelf(name).field,
                "aggregate": request.shelf(name).aggregate,
                "sort": request.shelf(name).sort,
                "bin": request.shelf(name).bin,
            }
            for name in SHELVES
        },
    }


def request_from_dict(data: Dict[str, Any]) -> ChartRequest:
    """Rebuild a `ChartRequest`. Unknown keys are ignored, missing ones default.

    Forgiving on purpose: a saved chart is stored inside someone's project file
    and outlives the version that wrote it. A spec from an older build that
    lacks a field should open with that field's default, not refuse — the chart
    is recoverable either way, and refusing loses it.
    """
    shelves = data.get("shelves") or {}

    def _shelf(name: str) -> Shelf:
        entry = shelves.get(name) or {}
        return Shelf(
            field=str(entry.get("field", "") or ""),
            aggregate=entry.get("aggregate") or None,
            sort=entry.get("sort") or None,
            bin=bool(entry.get("bin", False)),
        )

    return ChartRequest(
        mark=str(data.get("mark", "bar") or "bar"),
        x=_shelf("x"), y=_shelf("y"), color=_shelf("color"), facet=_shelf("facet"),
        title=str(data.get("title", "") or ""),
        width=data.get("width"),
        height=data.get("height"),
    )


def describe(request: ChartRequest) -> str:
    """One line naming what this chart shows, for a list or a report caption.

    Built from the shelves rather than the title, because the title is the
    analyst's words and this has to be true even when they left it blank.
    """
    mark = MARKS.get(request.mark)
    label = mark.label if mark else request.mark
    parts = []
    for name in SHELVES:
        shelf = request.shelf(name)
        if shelf.is_empty:
            continue
        parts.append(f"{_shelf_label(name, request.mark)}: {measure_title(shelf)}")
    return f"{label} — " + ", ".join(parts) if parts else label


# ── one-click starting points ─────────────────────────────────────────────────

#: Column names that are identifiers, not things anyone charts. Matched on the
#: whole name or a trailing `_id`, never a substring: a descriptor legitimately
#: called "identity" or "candidate" must not be swept up.
def _looks_like_an_identifier(name: str) -> bool:
    lowered = name.lower()
    return lowered in {"id", "uuid"} or lowered.endswith("_id")


#: A category with more distinct values than this is a list, not an axis.
_MAX_SUGGESTED_CATEGORIES = 25


def chartable_fields(field_types: Dict[str, str], frame=None) -> List[str]:
    """Categorical fields worth suggesting a chart over, best first.

    Charting `application_id` produces one bar per row and tells the analyst
    nothing, and the first thing they see should not be that. Identifiers are
    dropped by name, and — when the frame is available to count them — so are
    categories with too many distinct values to read as an axis.

    Ordered by distinct count ascending, because a five-value descriptor makes a
    better first chart than a forty-value one.
    """
    names = [name for name, kind in field_types.items()
             if kind in (NOMINAL, ORDINAL) and not _looks_like_an_identifier(name)]
    if frame is None:
        return names

    counted = []
    for name in names:
        if name not in frame.columns:
            continue
        distinct = int(frame[name].nunique(dropna=True))
        if distinct < 2 or distinct > _MAX_SUGGESTED_CATEGORIES:
            # One value is not a comparison; hundreds is not an axis.
            continue
        counted.append((distinct, name))
    return [name for _distinct, name in sorted(counted)]


def suggested_charts(field_types: Dict[str, str],
                     max_suggestions: int = 6,
                     *, frame=None, label=None, prefer=()) -> List[ChartRequest]:
    """Chart requests that are valid for these columns, best first.

    The point of a "show me" list is a chart in one click, before the analyst has
    learned what a shelf is — so a suggestion that is technically valid and
    useless is worse than no suggestion. Pass `frame` and the candidates are
    filtered by cardinality as well as by name.

    Ordered so the first is the one that is almost always wanted: how often each
    category occurs.

    `label` turns a field name into what a person reads in a title (the desktop
    passes `core.ux.fields.friendly`); with none, titles use the raw names.

    `prefer` names fields to put first among the categories (the desktop prefers
    the theme, because for coded results "how often each theme" is the question).
    """
    name = label or (lambda field: field)
    categories = chartable_fields(field_types, frame)
    categories = [f for f in prefer if f in categories] + [f for f in categories if f not in prefer]
    measures = [f for f, t in field_types.items()
                if t == QUANTITATIVE and not _looks_like_an_identifier(f)]
    times = [f for f, t in field_types.items() if t == TEMPORAL]

    out: List[ChartRequest] = []

    if categories:
        first = categories[0]
        out.append(ChartRequest(
            mark="bar_horizontal", x=Shelf(first, sort="-x"), y=Shelf(aggregate="count"),
            title=f"How often each {name(first)} occurs"))
    if categories and measures:
        out.append(ChartRequest(
            mark="bar_horizontal",
            x=Shelf(categories[0], sort="-x"), y=Shelf(measures[0], aggregate="sum"),
            title=f"Total {name(measures[0])} by {name(categories[0])}"))
    if len(categories) >= 2:
        out.append(ChartRequest(
            mark="stacked_bar", x=Shelf(categories[0]), y=Shelf(aggregate="count"),
            color=Shelf(categories[1]),
            title=f"{name(categories[0])} broken down by {name(categories[1])}"))
        out.append(ChartRequest(
            mark="heatmap", x=Shelf(categories[0]), y=Shelf(categories[1]),
            color=Shelf(aggregate="count"),
            title=f"{name(categories[0])} against {name(categories[1])}"))
    if categories:
        out.append(ChartRequest(
            mark="pie", color=Shelf(categories[0]), y=Shelf(aggregate="count"),
            title=f"Share of each {name(categories[0])}"))
    if times and measures:
        out.append(ChartRequest(
            mark="line", x=Shelf(times[0]), y=Shelf(measures[0], aggregate="sum"),
            title=f"{name(measures[0])} over time"))
    if len(measures) >= 2:
        out.append(ChartRequest(
            mark="point", x=Shelf(measures[0]), y=Shelf(measures[1]),
            title=f"{name(measures[1])} against {name(measures[0])}"))

    return [r for r in out if can_build(r, field_types)][:max_suggestions]
