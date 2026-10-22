"""
The chart configuration model: everything a saved chart needs, as plain data.

A `ChartConfig` is a value. It holds *choices* (which field, which recode, which
theme), never data or computed numbers, so it round-trips through JSON and can
rebuild the same chart from the same data structure later. Loading is forgiving
(unknown keys ignored, missing keys defaulted, an older version still opens);
validation is where strictness lives, and it returns sentences.

`EditHistory` gives the undo/redo the workflow needs: each edit pushes a
snapshot, so grouping, filtering, renaming and sorting are all reversible with
one mechanism instead of one per feature.
"""

from __future__ import annotations

import copy
from dataclasses import asdict, dataclass, field, fields
from typing import Any, Dict, List, Optional, Sequence

CONFIG_VERSION = 1

# ── vocabularies ──────────────────────────────────────────────────────────────

AGGREGATIONS = ("count", "percent", "sum", "mean", "median", "min", "max",
                "distinct")
MEASURE_AGGREGATIONS = ("sum", "mean", "median", "min", "max", "distinct")

CHART_TYPES = ("bar", "bar_horizontal", "grouped_bar", "stacked_bar",
               "normalized_bar", "pie", "donut", "line", "area", "scatter",
               "histogram", "box", "heatmap")

#: "scale" orders a recognised ordered scale (Likert etc.) by its own order.
SORTS = ("desc", "asc", "alpha", "source", "custom", "scale")
KINDS = ("single", "matrix", "multi", "text")
FILTER_OPS = ("eq", "ne", "in", "not_in", "gt", "ge", "lt", "le", "between",
              "contains", "is_missing", "not_missing")
DENOMINATORS = ("valid", "all_rows", "custom")
PERCENT_BASES = ("group", "total")
LEGEND_POSITIONS = ("right", "bottom", "top", "left", "none")
SIZES = ("small", "medium", "large", "xlarge")
TIME_GRAINS = ("auto", "day", "week", "month", "quarter", "year")
#: Chart types drawn from the rows themselves (a distribution, a trend, a
#: relationship) rather than from counts of categories.
NUMERIC_CHARTS = ("line", "area", "scatter", "histogram", "box")

#: Figure presets: name -> (width px, height px). Pixels at 96 per inch, so
#: DPI export scales them (a 1600x900 figure at 300 DPI is 4.8 x 2.7 in wide).
FIGURE_PRESETS: Dict[str, tuple] = {
    "16:9 PowerPoint": (1280, 720),
    "4:3": (1024, 768),
    "Square": (800, 800),
    "Report / document": (900, 600),
}
CUSTOM_PRESET = "Custom"

#: What "small / medium / large / xlarge" mean for text. One control each for
#: text and bars keeps the panel short; the numbers live here, not in the UI.
FONT_SIZES = {"small": 11, "medium": 13, "large": 16, "xlarge": 20}
#: Fraction of each category band left empty between bars: a bigger gap is a
#: thinner bar. Expressed as a ratio, not pixels, so the figure size the analyst
#: chose stays exact whatever the number of categories.
BAR_GAP = {"small": 0.62, "medium": 0.42, "large": 0.24, "xlarge": 0.08}


# ── pieces ────────────────────────────────────────────────────────────────────

@dataclass
class FilterRule:
    column: str
    op: str = "in"
    values: List[Any] = field(default_factory=list)


@dataclass
class Merge:
    """Categories combined into a new one. Source values stay untouched."""
    label: str
    members: List[str] = field(default_factory=list)


@dataclass
class Recode:
    #: Categories to leave out of the chart (and out of denominators).
    exclude: List[str] = field(default_factory=list)
    #: source label -> display label. Display only; never edits the data.
    rename: Dict[str, str] = field(default_factory=dict)
    merges: List[Merge] = field(default_factory=list)
    #: Manual category order, used when sort == "custom" (unlisted go last).
    order: List[str] = field(default_factory=list)
    #: Hide blanks (default) or show them as their own category.
    show_missing: bool = False
    missing_label: str = "No response"
    collapse_whitespace: bool = False
    missing_tokens: Optional[List[str]] = None       # None = the default list
    #: matrix item column -> display name (never renames the column itself)
    item_rename: Dict[str, str] = field(default_factory=dict)


#: Named multi-select delimiters. "custom" uses `MultiSelect.custom_delimiter`.
DELIMITER_CHARS = {"comma": ",", "semicolon": ";", "pipe": "|", "newline": "\n"}
MULTI_MODES = ("simple", "known")


@dataclass
class MultiSelect:
    """How a select-all-that-apply cell is turned into choices."""
    mode: str = "known"              # "simple" split, or "known" phrase matching
    delimiter: str = "comma"
    custom_delimiter: str = ""
    #: The canonical response choices, for `known` mode. Order = source order.
    choices: List[str] = field(default_factory=list)
    #: Pieces not on the known list are counted and reported, not charted,
    #: unless this is on (then each becomes its own category as found).
    include_unmatched: bool = False

    def delimiter_char(self) -> str:
        if self.delimiter == "custom":
            return self.custom_delimiter
        return DELIMITER_CHARS.get(self.delimiter, ",")


@dataclass
class BoxConfig:
    """Top/bottom-box summaries over an ordered scale (matrix questions)."""
    top: List[int] = field(default_factory=lambda: [1, 2])
    bottom: List[int] = field(default_factory=lambda: [1, 2])
    #: Custom combined boxes, e.g. Merge("Favourable", ["Agree", "Strongly agree"]).
    custom: List[Merge] = field(default_factory=list)
    #: Leave off-scale answers ("No opinion") out of the valid N of a box.
    exclude_off_scale: bool = False


@dataclass
class Labels:
    title: str = ""
    subtitle: str = ""
    footnote: str = ""
    x_title: str = ""
    y_title: str = ""
    legend_title: str = ""
    legend_position: str = "right"


@dataclass
class Display:
    data_labels: bool = True
    show_percent: bool = True
    show_count: bool = True
    show_valid_n: bool = True
    decimals: int = 0
    thousands_separator: bool = True
    gridlines: bool = True
    axis_min: Optional[float] = None
    axis_max: Optional[float] = None
    wrap_labels: bool = True
    max_label_chars: int = 28
    size: str = "medium"
    orientation: str = "horizontal"      # grouped / stacked charts
    #: Keep only the N largest categories (0 = all). Others are left out, not
    #: combined, and a warning says so.
    max_categories: int = 0
    #: Histogram: number of bins (0 = chosen from the data).
    bins: int = 0
    #: Line and area charts of dates: the period each point summarises.
    time_grain: str = "auto"
    #: Scatter: draw a straight line of best fit and report it.
    trend_line: bool = False


@dataclass
class Figure:
    preset: str = "16:9 PowerPoint"
    width: int = 1280
    height: int = 720
    dpi: int = 300
    transparent: bool = False
    format: str = "png"


@dataclass
class ThemeChoice:
    name: str = "QualSafe default"
    #: category label -> "#RRGGBB", beats every automatic rule.
    color_overrides: Dict[str, str] = field(default_factory=dict)
    #: "auto" detects a known ordered scale, "none" turns semantic colours off,
    #: or the name of a scale preset.
    semantic_scale: str = "auto"


@dataclass
class ChartConfig:
    version: int = CONFIG_VERSION
    dataset: Dict[str, Any] = field(default_factory=dict)   # name, sheet, columns
    kind: str = "single"
    column: str = ""
    columns: List[str] = field(default_factory=list)         # matrix items
    group_by: List[str] = field(default_factory=list)
    value_field: str = ""
    aggregation: str = "percent"
    chart_type: str = "bar_horizontal"
    filters: List[FilterRule] = field(default_factory=list)
    multi: MultiSelect = field(default_factory=MultiSelect)
    boxes: BoxConfig = field(default_factory=BoxConfig)
    recode: Recode = field(default_factory=Recode)
    sort: str = "desc"
    denominator: str = "valid"
    custom_denominator: Optional[float] = None
    percent_base: str = "group"
    labels: Labels = field(default_factory=Labels)
    display: Display = field(default_factory=Display)
    figure: Figure = field(default_factory=Figure)
    theme: ThemeChoice = field(default_factory=ThemeChoice)

    # ── (de)serialisation ────────────────────────────────────────────────────
    def to_dict(self) -> Dict[str, Any]:
        return copy.deepcopy(asdict(self))

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "ChartConfig":
        """Forgiving load: unknown keys ignored, missing keys defaulted."""
        return _build(cls, data or {})

    def copy(self) -> "ChartConfig":
        return ChartConfig.from_dict(self.to_dict())

    # ── validation ───────────────────────────────────────────────────────────
    def problems(self) -> List[str]:
        """Sentences describing what is wrong. Empty means buildable."""
        out: List[str] = []
        if self.kind == "matrix":
            if len(self.columns) < 2:
                out.append("A matrix question needs two or more columns.")
            if self.group_by:
                out.append("A matrix question already uses its items as groups; "
                           "remove the grouping field.")
        elif not self.column:
            out.append("Choose a field to analyse.")
        if self.kind == "multi":
            if self.multi.mode not in MULTI_MODES:
                out.append(f"Unknown parsing mode '{self.multi.mode}'.")
            if self.multi.delimiter == "custom" and not self.multi.custom_delimiter:
                out.append("Enter the custom delimiter.")
            if self.multi.mode == "known" and not self.multi.choices:
                out.append("Known-category matching needs the list of response "
                           "choices. Paste them, or pick them from the suggestions.")
            if self.aggregation in MEASURE_AGGREGATIONS:
                out.append("Select-all questions are counted, not summed: choose "
                           "count or percent.")
        if self.aggregation not in AGGREGATIONS:
            out.append(f"Unknown aggregation '{self.aggregation}'.")
        if self.aggregation in MEASURE_AGGREGATIONS and not self.value_field:
            out.append(f"'{self.aggregation}' needs a value field to summarise.")
        if self.chart_type not in CHART_TYPES:
            out.append(f"Unknown chart type '{self.chart_type}'.")
        if self.sort not in SORTS:
            out.append(f"Unknown sort '{self.sort}'.")
        if self.denominator == "custom" and not (self.custom_denominator or 0) > 0:
            out.append("A custom denominator must be greater than zero.")
        if self.chart_type in ("pie", "donut") and len(self.group_by) > 0 \
                and self.kind == "single":
            out.append("A pie or donut shows one variable; remove the grouping "
                       "field or choose a grouped or stacked bar.")
        return out


def _build(cls, data: Dict[str, Any]):
    """Recursive dict -> dataclass that ignores what it does not know."""
    if not isinstance(data, dict):
        return cls()
    kwargs: Dict[str, Any] = {}
    for f in fields(cls):
        if f.name not in data:
            continue
        value = data[f.name]
        kwargs[f.name] = _coerce(f.type, value)
    return cls(**kwargs)


def _coerce(type_hint, value):
    name = type_hint if isinstance(type_hint, str) else getattr(type_hint, "__name__", "")
    if name in ("Recode", "Labels", "Display", "Figure", "ThemeChoice",
                "MultiSelect", "BoxConfig"):
        return _build(globals()[name], value)
    if name == "List[FilterRule]":
        return [_build(FilterRule, v) for v in (value or [])]
    if name == "List[Merge]":
        return [_build(Merge, v) for v in (value or [])]
    return value


#: The choices about *what the numbers are*: the ones "undo" covers. Titles,
#: colours and figure size are presentation, and undoing a filter should not
#: also un-type the title.
SHAPING_FIELDS = ("kind", "column", "columns", "group_by", "value_field",
                  "aggregation", "filters", "multi", "boxes", "recode", "sort",
                  "denominator", "custom_denominator", "percent_base")


class EditHistory:
    """Undo/redo over configs: one mechanism for every reversible edit.

    With `fields`, only those parts of the config are recorded and restored, so
    undo can step back through filtering, recoding and sorting without touching
    the title or the colours. Without it the whole config is versioned.
    """

    def __init__(self, start: Optional[ChartConfig] = None, limit: int = 100,
                 fields: Optional[Sequence[str]] = None):
        self._limit = limit
        self._fields = tuple(fields) if fields else None
        self._stack: List[Dict[str, Any]] = [self._snap(start or ChartConfig())]
        self._at = 0

    def _snap(self, config: ChartConfig) -> Dict[str, Any]:
        data = config.to_dict()
        if self._fields is None:
            return data
        return {name: data[name] for name in self._fields}

    @property
    def current(self) -> ChartConfig:
        return ChartConfig.from_dict(self._stack[self._at])

    def restore_into(self, config: ChartConfig) -> ChartConfig:
        """`config` with the recorded parts replaced by the current state."""
        data = config.to_dict()
        data.update(copy.deepcopy(self._stack[self._at]))
        return ChartConfig.from_dict(data)

    def push(self, config: ChartConfig) -> None:
        """Record a new state. A no-op edit is not recorded."""
        snapshot = self._snap(config)
        if snapshot == self._stack[self._at]:
            return
        del self._stack[self._at + 1:]
        self._stack.append(snapshot)
        if len(self._stack) > self._limit:
            self._stack.pop(0)
        self._at = len(self._stack) - 1

    @property
    def can_undo(self) -> bool:
        return self._at > 0

    @property
    def can_redo(self) -> bool:
        return self._at < len(self._stack) - 1

    def undo(self) -> ChartConfig:
        if self.can_undo:
            self._at -= 1
        return self.current

    def redo(self) -> ChartConfig:
        if self.can_redo:
            self._at += 1
        return self.current

    def reset(self, config: Optional[ChartConfig] = None) -> ChartConfig:
        """"Reset chart": back to a blank config, itself undoable."""
        self.push(config or ChartConfig())
        return self.current
