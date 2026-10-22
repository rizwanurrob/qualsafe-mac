"""
Rendering engine: a finished `ChartData` becomes a Vega-Lite spec (a dict).

It reads the canonical table and the config and *computes nothing about the
data*: percentages, orderings and colours were decided upstream. That is the
guarantee that a bar, a pie and a stacked bar of the same question agree.

Figure size is exact. The spec uses ``autosize: fit`` with ``contains: padding``,
so a 1280 x 720 figure is 1280 x 720 whatever the axes and legend need; the plot
area gives way, the figure does not. The footnote is a text layer placed a fixed
distance under the plot area (Vega-Lite has no bottom-left footnote), which is
also why it survives a change of figure size.

Stacked charts are drawn from explicit start/end positions computed here rather
than by Vega-Lite's stack transform, so segment labels can be centred in their
segment and a segment too narrow to hold its label simply omits it.
"""

from __future__ import annotations

import textwrap
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from core.chartbuilder import labels as labels_mod
from core.chartbuilder.aggregate import ChartBuildError, ChartData
from core.chartbuilder.config import (
    BAR_GAP, FONT_SIZES, ChartConfig)
from core.chartbuilder.themes import Theme

SCHEMA = "https://vega.github.io/schema/vega-lite/v5.json"
FONT = "Arial, Helvetica, sans-serif"
#: The two characters backslash and n, for a newline inside a Vega expression.
NEWLINE_ESCAPE = chr(92) + "n"

#: Chart types this renderer draws. The rest (line, area, scatter, histogram,
#: box) work from raw rows rather than the canonical table and arrive later.
AVAILABLE_TYPES = ("bar", "bar_horizontal", "grouped_bar", "stacked_bar",
                   "normalized_bar", "pie", "donut", "heatmap",
                   "line", "area", "scatter", "histogram", "box")

_STACKED = ("stacked_bar", "normalized_bar")
#: A stacked segment narrower than this share of the axis gets no label.
_MIN_LABEL_SHARE = 0.06
#: Below this share a segment shows only its percent, not "n/N".
_FULL_LABEL_SHARE = 0.15


def figure_size(cfg: ChartConfig) -> tuple:
    from core.chartbuilder.config import FIGURE_PRESETS
    if cfg.figure.preset in FIGURE_PRESETS:
        return FIGURE_PRESETS[cfg.figure.preset]
    return (max(int(cfg.figure.width), 200), max(int(cfg.figure.height), 150))


def wrap_label(text: str, width: int) -> str:
    """Break a long label onto several lines at spaces (Vega renders '\\n')."""
    if width <= 0 or len(text) <= width:
        return text
    return "\n".join(textwrap.wrap(text, width=width, break_long_words=False)) or text


def _records(frame: pd.DataFrame) -> List[Dict[str, Any]]:
    out = []
    for row in frame.to_dict("records"):
        out.append({k: (None if isinstance(v, float) and np.isnan(v) else
                        (v.item() if hasattr(v, "item") else v))
                    for k, v in row.items()})
    return out


def effective_type(data: ChartData, cfg: ChartConfig) -> str:
    """A grouped question drawn as a plain bar becomes a grouped bar.

    Plotting several groups as one series would stack them invisibly on top of
    each other, which is the kind of quiet wrongness this builder avoids.
    """
    if data.groups and cfg.chart_type in ("bar", "bar_horizontal"):
        return "grouped_bar"
    return cfg.chart_type


def _horizontal(kind: str, cfg: ChartConfig) -> bool:
    if kind == "bar":
        return False
    if kind == "bar_horizontal":
        return True
    return cfg.display.orientation != "vertical"


def _title_block(cfg: ChartConfig, theme: Theme, fs: int) -> Optional[dict]:
    lab = cfg.labels
    if not (lab.title or lab.subtitle):
        return None
    block = {"text": lab.title or " ", "anchor": "start", "color": theme.title,
             "fontSize": fs + 5, "fontWeight": "bold", "font": FONT,
             "subtitleColor": theme.text, "subtitleFontSize": fs,
             "subtitleFont": FONT, "offset": 10}
    if lab.subtitle:
        block["subtitle"] = lab.subtitle
    return block


def _footnote(cfg: ChartConfig, data: ChartData, theme: Theme, fs: int,
              offset: int) -> Optional[dict]:
    """Footnote/source text plus the automatic base note, under the plot."""
    lines: List[str] = []
    if cfg.labels.footnote.strip():
        lines.extend(cfg.labels.footnote.strip().splitlines())
    if data.base_note:
        lines.append(data.base_note)
    if not lines:
        return None
    return {"data": {"values": [{"t": 1}]},
            "mark": {"type": "text", "align": "left", "baseline": "top",
                     "fontSize": max(fs - 2, 9), "color": theme.text,
                     "font": FONT, "lineBreak": "\n", "opacity": 0.85},
            "encoding": {"text": {"value": "\n".join(lines)},
                         "x": {"value": 0},
                         "y": {"value": {"expr": f"height + {offset}"}}}}


def _axis(title: Optional[str], cfg: ChartConfig, theme: Theme, fs: int, *,
          grid: bool, percent: bool = False, orient: Optional[str] = None,
          labels_on: bool = True, wrap: bool = False) -> dict:
    axis: Dict[str, Any] = {
        "title": title or None, "labelColor": theme.text, "titleColor": theme.text,
        "labelFontSize": fs, "titleFontSize": fs, "labelFont": FONT,
        "titleFont": FONT, "grid": bool(grid and cfg.display.gridlines),
        "gridColor": theme.gridline, "domainColor": theme.gridline,
        "tickColor": theme.gridline, "labels": labels_on}
    if percent:
        axis["labelExpr"] = "datum.label + '%'"
    if wrap:
        # Wrapped labels carry a newline; Vega only breaks lines given an array.
        axis["labelExpr"] = "split(datum.label, '" + NEWLINE_ESCAPE + "')"
        axis["labelLimit"] = 400
    if grid:
        axis["tickCount"] = 6
    if orient:
        axis["orient"] = orient
    return axis


def _value_scale(cfg: ChartConfig, max_value: float, percent: bool,
                 labelled: bool, force_max: Optional[float] = None) -> dict:
    scale: Dict[str, Any] = {"zero": True, "nice": True}
    lo, hi = cfg.display.axis_min, cfg.display.axis_max
    if lo is not None:
        scale["domainMin"] = lo
    if hi is not None:
        scale["domainMax"] = hi
    elif force_max is not None:
        scale["domainMax"] = force_max
    elif labelled and max_value > 0:
        # Room for the label past the longest bar.
        scale["domainMax"] = max_value * 1.32
        scale["nice"] = False
    return scale


def _legend(cfg: ChartConfig, data: ChartData, theme: Theme, fs: int,
            title: str) -> Any:
    pos = cfg.labels.legend_position
    if pos == "none":
        return None
    return {"title": cfg.labels.legend_title or title or None, "orient": pos,
            "labelColor": theme.text, "titleColor": theme.text,
            "labelFontSize": fs, "titleFontSize": fs, "labelFont": FONT,
            "titleFont": FONT, "symbolType": "square", "symbolSize": 140}


def _layout_stacks(data: ChartData, normalize: bool) -> pd.DataFrame:
    """Start/end/mid per segment, one stack per group (or one stack overall)."""
    table = data.table.copy()
    table["row"] = table["group"].where(table["group"] != "", "All responses")
    starts, ends = [], []
    for _, block in table.groupby("row", sort=False):
        block = block.sort_values("sort_order", kind="stable")
        total = float(block["value"].fillna(0).sum())
        scale = (100.0 / total) if (normalize and total) else 1.0
        cursor = 0.0
        for idx, val in block["value"].fillna(0).items():
            width = val * scale
            starts.append((idx, cursor))
            ends.append((idx, cursor + width))
            cursor += width
    table["start"] = pd.Series(dict(starts))
    table["end"] = pd.Series(dict(ends))
    table["mid"] = (table["start"] + table["end"]) / 2
    return table


def _swap_roles(data: ChartData) -> ChartData:
    """Matrix grouped bars: items on the axis, one bar per response category.

    The canonical table keeps the item as `group` and the response as
    `category` (that is what stacking and the box summaries want). A grouped bar
    reads the other way round, so the roles are exchanged for drawing only.
    """
    import copy
    swapped = copy.copy(data)
    table = data.table.copy()
    table["category"], table["group"] = data.table["group"], data.table["category"]
    order = {c: i for i, c in enumerate(data.groups)}
    table["sort_order"] = table["category"].map(order)
    swapped.table = table.sort_values(["sort_order"], kind="stable").reset_index(drop=True)
    swapped.categories, swapped.groups = list(data.groups), list(data.categories)
    swapped.color_by = "group"
    swapped.group_fields = ["Response"]
    return swapped


def _pie_grid_spec(data: ChartData, cfg: ChartConfig, theme: Theme, kind: str) -> Dict[str, Any]:
    """One pie or donut per matrix item, side by side, sharing one legend.

    A concat cannot use `autosize: fit`, so each panel is sized from the figure
    (minus room for the title, legend and footnote) to land close to the
    requested size rather than exactly on it.
    """
    import math
    fs = FONT_SIZES[cfg.display.size]
    W, H = figure_size(cfg)
    items = data.groups
    n = len(items)
    cols = n if n <= 3 else (2 if n == 4 else 3 if n <= 9 else 4)
    rows_n = math.ceil(n / cols)
    title_room = 70 if (cfg.labels.title or cfg.labels.subtitle) else 20
    foot_room = 46 if (cfg.labels.footnote.strip() or data.base_note) else 16
    legend_room = 0 if cfg.labels.legend_position in ("none", "top", "bottom") else 190
    cell_w = (W - legend_room - 40) / cols
    cell_h = (H - title_room - foot_room) / rows_n
    size = int(max(min(cell_w, cell_h) - 46, 80))
    radius, inner = size / 2 - 2, (size / 2 - 2) * 0.55 if kind == "donut" else 0
    cats = data.categories
    colors = [dict(zip(data.table["category"], data.table["color"]))[k] for k in cats]
    panels = []
    for item in items:
        block = _arc_label_column(data.table[data.table["group"] == item], cfg)
        theta = {"field": "value", "type": "quantitative", "stack": True}
        order = {"field": "sort_order", "type": "quantitative"}
        arcs = {"mark": {"type": "arc", "outerRadius": radius, "innerRadius": inner,
                         "stroke": "#FFFFFF", "strokeWidth": 1.5},
                "encoding": {"theta": theta, "order": order,
                             "color": {"field": "category", "type": "nominal",
                                       "scale": {"domain": cats, "range": colors},
                                       "legend": _legend(cfg, data, theme, fs,
                                                         cfg.labels.legend_title)},
                             "tooltip": [{"field": "category"},
                                         {"field": "display_label", "title": "Value"}]}}
        layers = [arcs]
        if cfg.display.data_labels:
            layers.append({"mark": {"type": "text", "fontSize": max(fs - 2, 9),
                                    "radius": (radius + inner) / 2 if inner else radius * 0.68,
                                    "color": "#FFFFFF", "font": FONT},
                           "encoding": {"theta": theta, "order": order,
                                        "text": {"field": "arc_label"}}})
        panels.append({"title": {"text": wrap_label(item, 30).split("\n"), "fontSize": fs,
                                 "color": theme.title, "font": FONT, "anchor": "middle"},
                       "width": size, "height": size,
                       "data": {"values": _records(block)}, "layer": layers})
    grid: Dict[str, Any] = {"columns": cols, "concat": panels,
                            "resolve": {"scale": {"color": "shared"}}}
    lines = [l for l in cfg.labels.footnote.strip().splitlines()] if cfg.labels.footnote.strip() else []
    if data.base_note:
        lines.append(data.base_note)
    blocks: List[Dict[str, Any]] = [grid]
    if lines:
        blocks.append({"width": 10, "height": 10 + 14 * len(lines), "data": {"values": [{"t": 1}]},
                       "mark": {"type": "text", "align": "left", "baseline": "top",
                                "fontSize": max(fs - 2, 9), "color": theme.text, "font": FONT,
                                "lineBreak": "\n"},
                       "encoding": {"text": {"value": "\n".join(lines)},
                                    "x": {"value": 0}, "y": {"value": 0}}})
    spec: Dict[str, Any] = {
        "$schema": SCHEMA,
        "background": "transparent" if cfg.figure.transparent else theme.background,
        "padding": {"left": 16, "right": 20, "top": 14, "bottom": 12},
        "config": {"view": {"stroke": None}, "font": FONT},
        "vconcat": blocks}
    title = _title_block(cfg, theme, fs)
    if title:
        spec["title"] = title
    return spec


def build_spec(data: ChartData, cfg: ChartConfig, theme: Theme) -> Dict[str, Any]:
    """The Vega-Lite spec for `data` under `cfg`. Raises `ChartBuildError`."""
    kind = effective_type(data, cfg)
    if data.kind == "matrix" and kind == "grouped_bar":
        data = _swap_roles(data)
    if data.kind == "matrix" and kind in ("pie", "donut"):
        return _pie_grid_spec(data, cfg, theme, kind)
    if kind not in AVAILABLE_TYPES:
        raise ChartBuildError(
            f"The '{kind}' chart is not available yet. Available now: "
            f"{', '.join(AVAILABLE_TYPES)}.")
    if kind == "heatmap" and not data.groups:
        raise ChartBuildError("A heatmap needs a grouping field for its second axis.")

    fs = FONT_SIZES[cfg.display.size]
    W, H = figure_size(cfg)
    horizontal = _horizontal(kind, cfg)
    gap = BAR_GAP[cfg.display.size]
    table = data.table
    color_mapping = dict(zip(table["category"], table["color"]))
    group_mapping = dict(zip(table["group"], table["color"]))
    percent = data.is_percent
    quant_title = (cfg.labels.x_title if horizontal else cfg.labels.y_title) \
        or data.value_title
    cat_title = (cfg.labels.y_title if horizontal else cfg.labels.x_title) or None

    wrapped = {c: (wrap_label(c, cfg.display.max_label_chars)
                   if cfg.display.wrap_labels else c) for c in data.categories}
    n_lines = max((w.count("\n") + 1 for w in wrapped.values()), default=1)

    if kind == "histogram":
        layers, foot_offset, used = _hist_layers(data, cfg, theme, fs)
    elif kind == "box":
        layers, foot_offset, used = _box_layers(data, cfg, theme, fs, gap)
    elif kind in ("line", "area"):
        layers, foot_offset, used = _line_layers(data, cfg, theme, fs, kind == "area")
    elif kind == "scatter":
        layers, foot_offset, used = _scatter_layers(data, cfg, theme, fs)
    elif kind in ("pie", "donut"):
        layers, foot_offset, used = _arc_layers(data, cfg, theme, fs, W, H, kind, wrapped)
    elif kind == "heatmap":
        layers, foot_offset, used = _heatmap_layers(data, cfg, theme, fs, wrapped)
    elif kind in _STACKED:
        layers, foot_offset, used = _stacked_layers(
            data, cfg, theme, fs, horizontal, gap, kind == "normalized_bar",
            quant_title, cat_title)
    else:
        layers, foot_offset, used = _bar_layers(
            data, cfg, theme, fs, horizontal, gap, kind == "grouped_bar",
            quant_title, cat_title, wrapped, n_lines)

    note = _footnote(cfg, data, theme, fs, foot_offset)
    if note:
        layers.append(note)

    bottom_pad = 16 + (max(fs, 11) * 1.5 * (
        (cfg.labels.footnote.strip().count("\n") + 1 if cfg.labels.footnote.strip() else 0)
        + (1 if data.base_note else 0)) if note else 0)

    spec: Dict[str, Any] = {
        "$schema": SCHEMA,
        "background": None if cfg.figure.transparent else theme.background,
        "width": W, "height": H,
        "autosize": {"type": "fit", "contains": "padding"},
        "padding": {"left": 16, "right": 20, "top": 14, "bottom": int(bottom_pad)},
        "config": {"view": {"stroke": None}, "font": FONT,
                   "text": {"font": FONT, "color": theme.text}},
        "data": {"values": _records(used)},
        "layer": layers,
    }
    title = _title_block(cfg, theme, fs)
    if title:
        spec["title"] = title
    if cfg.figure.transparent:
        spec["background"] = "transparent"
    return spec


# ── bars ──────────────────────────────────────────────────────────────────────

def _bar_layers(data, cfg, theme, fs, horizontal, gap, grouped, quant_title,
                cat_title, wrapped, n_lines):
    table = data.table.copy()
    table["axis_label"] = table["category"].map(wrapped)
    order = [wrapped[c] for c in data.categories]
    values = table["value"].dropna()
    vmax = float(values.max()) if len(values) else 0.0
    labelled = cfg.display.data_labels
    domain = _value_scale(cfg, vmax, data.is_percent, labelled)
    q, c = ("x", "y") if horizontal else ("y", "x")
    off = ("yOffset" if horizontal else "xOffset")

    cat_enc = {"field": "axis_label", "type": "nominal", "sort": order,
               "title": cat_title,
               "axis": _axis(cat_title, cfg, theme, fs, grid=False,
                             orient=None, wrap=cfg.display.wrap_labels),
               "scale": {"paddingInner": gap, "paddingOuter": 0.08}}
    if not horizontal:
        cat_enc["axis"]["labelAngle"] = 0
        cat_enc["axis"]["labelLimit"] = 0 if not cfg.display.wrap_labels else 400
    quant_enc = {"field": "value", "type": "quantitative", "title": quant_title,
                 "scale": domain,
                 "axis": _axis(quant_title, cfg, theme, fs, grid=True,
                               percent=data.is_percent)}
    encoding: Dict[str, Any] = {c: cat_enc, q: quant_enc,
                                "tooltip": [{"field": "category", "title": "Category"},
                                            {"field": "group", "title": "Group"},
                                            {"field": "display_label", "title": "Value"}]}
    mark: Dict[str, Any] = {"type": "bar"}
    if grouped:
        groups = data.groups
        encoding[off] = {"field": "group", "type": "nominal", "sort": groups}
        encoding["color"] = {
            "field": "group", "type": "nominal",
            "scale": {"domain": groups,
                      "range": [dict(zip(table["group"], table["color"]))[g] for g in groups]},
            "legend": _legend(cfg, data, theme, fs, " / ".join(data.group_fields))}
    elif data.color_by == "category":
        cats = data.categories
        encoding["color"] = {
            "field": "category", "type": "nominal",
            "scale": {"domain": cats, "range": [dict(zip(table["category"], table["color"]))[k] for k in cats]},
            "legend": None}
    else:
        mark["color"] = theme.primary

    bars = {"mark": mark, "encoding": encoding}
    layers = [bars]
    if labelled:
        text_enc = {c: {k: v for k, v in cat_enc.items() if k != "axis"}, q: {"field": "value", "type": "quantitative",
                                                   "scale": domain},
                    "text": {"field": "display_label"}}
        if grouped:
            text_enc[off] = encoding[off]
        text_mark = {"type": "text", "fontSize": fs, "color": theme.text,
                     "font": FONT}
        if horizontal:
            text_mark.update(align="left", baseline="middle", dx=5)
        else:
            text_mark.update(align="center", baseline="bottom", dy=-4)
        layers.append({"mark": text_mark, "encoding": text_enc})
    axis_room = 30 + (n_lines * fs * 1.25 if not horizontal else 0) + fs * 1.6
    return layers, int(axis_room), table


def _stacked_layers(data, cfg, theme, fs, horizontal, gap, normalize,
                    quant_title, cat_title):
    table = _layout_stacks(data, normalize)
    rows = list(dict.fromkeys(table["row"]))
    cats = data.categories
    span = 100.0 if normalize else float(table.groupby("row")["end"].max().max() or 1)
    colors = [dict(zip(table["category"], table["color"]))[k] for k in cats]
    border = "#FFFFFF"
    q, q2, c = ("x", "x2", "y") if horizontal else ("y", "y2", "x")
    domain: Dict[str, Any] = {"domain": [cfg.display.axis_min or 0,
                                         cfg.display.axis_max or span], "nice": False}
    label_share = (table["end"] - table["start"]) / span
    table["show_label"] = label_share >= _MIN_LABEL_SHARE
    table["seg_label"] = [
        full if share >= _FULL_LABEL_SHARE else labels_mod.format_percent(
            pct, cfg.display.decimals) if pct == pct else ""
        for full, share, pct in zip(table["display_label"], label_share, table["percent"])]
    percent_axis = normalize or data.is_percent
    title = quant_title if not normalize else (cfg.labels.x_title if horizontal
                                              else cfg.labels.y_title) or "Percent of respondents"
    row_enc = {"field": "row", "type": "nominal", "sort": rows, "title": cat_title,
               "axis": _axis(cat_title, cfg, theme, fs, grid=False),
               "scale": {"paddingInner": gap, "paddingOuter": 0.08}}
    legend_title = cfg.labels.legend_title or " "
    color_enc = {"field": "category", "type": "nominal",
                 "scale": {"domain": cats, "range": colors},
                 "legend": _legend(cfg, data, theme, fs, legend_title if cfg.labels.legend_title else "")}
    bars = {"mark": {"type": "bar", "stroke": border if data.stack_border else None,
                     "strokeWidth": 1.6 if data.stack_border else 0},
            "encoding": {c: row_enc,
                         q: {"field": "start", "type": "quantitative", "title": title,
                             "scale": domain,
                             "axis": dict(_axis(title, cfg, theme, fs, grid=True,
                                                percent=percent_axis),
                                          **({"values": [0, 20, 40, 60, 80, 100]}
                                             if normalize else {}))},
                         q2: {"field": "end"}, "color": color_enc,
                         "tooltip": [{"field": "row", "title": "Group"},
                                     {"field": "category", "title": "Category"},
                                     {"field": "display_label", "title": "Value"}]}}
    layers = [bars]
    if cfg.display.data_labels:
        text_mark = {"type": "text", "fontSize": max(fs - 1, 9), "font": FONT,
                     "align": "center", "baseline": "middle"}
        layers.append({
            "transform": [{"filter": "datum.show_label"}],
            "mark": text_mark,
            "encoding": {c: {"field": "row", "type": "nominal", "sort": rows},
                         q: {"field": "mid", "type": "quantitative", "scale": domain},
                         "text": {"field": "seg_label"},
                         "color": {"value": "#FFFFFF"}}})
    return layers, 30 + int(fs * 1.6), table


# ── pie / donut ───────────────────────────────────────────────────────────────

def _arc_label_column(table: pd.DataFrame, cfg: ChartConfig) -> pd.DataFrame:
    """Full label on wide slices, percent only on narrow ones, none on slivers."""
    table = table.copy()
    table["arc_label"] = [
        full if pct >= 12 else (labels_mod.format_percent(pct, cfg.display.decimals)
                                if pct >= 5 else "")
        for full, pct in zip(table["display_label"], table["percent"].fillna(0))]
    return table


def _arc_layers(data, cfg, theme, fs, W, H, kind, wrapped):
    table = _arc_label_column(data.table, cfg)
    cats = data.categories
    # Radius follows the plot area, which Vega-Lite shrinks to fit the title
    # and legend, so the ring is never clipped whatever the figure size.
    radius = {"expr": "min(width, height) / 2 - 6"}
    inner = {"expr": "(min(width, height) / 2 - 6) * 0.55"} if kind == "donut" else 0
    colors = [dict(zip(table["category"], table["color"]))[k] for k in cats]
    theta = {"field": "value", "type": "quantitative", "stack": True}
    order = {"field": "sort_order", "type": "quantitative"}
    arcs = {"mark": {"type": "arc", "outerRadius": radius, "innerRadius": inner,
                     "stroke": "#FFFFFF", "strokeWidth": 1.5},
            "encoding": {"theta": theta, "order": order,
                         "color": {"field": "category", "type": "nominal",
                                   "scale": {"domain": cats, "range": colors},
                                   "legend": _legend(cfg, data, theme, fs,
                                                     cfg.labels.legend_title)},
                         "tooltip": [{"field": "category", "title": "Category"},
                                     {"field": "display_label", "title": "Value"}]}}
    layers = [arcs]
    if cfg.display.data_labels:
        layers.append({"mark": {"type": "text",
                                "radius": {"expr": "min(width, height) / 2 * 0.78"}
                                if inner else {"expr": "min(width, height) / 2 * 0.7"},
                                "fontSize": fs, "font": FONT,
                                "color": "#FFFFFF"},
                       "encoding": {"theta": theta, "order": order,
                                    "text": {"field": "arc_label"}}})
    return layers, 24, table


# ── heatmap ───────────────────────────────────────────────────────────────────

def _heatmap_layers(data, cfg, theme, fs, wrapped):
    table = data.table.copy()
    table["axis_label"] = table["category"].map(wrapped)
    order = [wrapped[c] for c in data.categories]
    vmax = float(table["value"].max() or 1)
    rects = {"mark": {"type": "rect", "stroke": "#FFFFFF", "strokeWidth": 1},
             "encoding": {
                 "x": {"field": "axis_label", "type": "nominal", "sort": order,
                       "axis": _axis(cfg.labels.x_title, cfg, theme, fs, grid=False),
                       "title": cfg.labels.x_title or None},
                 "y": {"field": "group", "type": "nominal", "sort": data.groups,
                       "axis": _axis(cfg.labels.y_title or " / ".join(data.group_fields),
                                     cfg, theme, fs, grid=False),
                       "title": cfg.labels.y_title or " / ".join(data.group_fields)},
                 "color": {"field": "value", "type": "quantitative",
                           "scale": {"range": theme.sequential, "domain": [0, vmax]},
                           "legend": _legend(cfg, data, theme, fs,
                                             cfg.labels.legend_title or data.value_title)},
                 "tooltip": [{"field": "category"}, {"field": "group"},
                             {"field": "display_label", "title": "Value"}]}}
    layers = [rects]
    if cfg.display.data_labels:
        layers.append({"mark": {"type": "text", "fontSize": fs, "font": FONT},
                       "encoding": {
                           "x": {"field": "axis_label", "type": "nominal", "sort": order},
                           "y": {"field": "group", "type": "nominal", "sort": data.groups},
                           "text": {"field": "display_label"},
                           "color": {"condition": {"test": f"datum.value > {vmax * 0.55}",
                                                   "value": "#FFFFFF"},
                                     "value": theme.text}}})
    return layers, 60, table


# ── numeric and time charts ───────────────────────────────────────────────────

def _group_scale(data: ChartData) -> Dict[str, Any]:
    colors = dict(zip(data.table["group"], data.table["color"]))
    return {"domain": data.groups, "range": [colors[g] for g in data.groups]}


def _numeric_titles(data: ChartData, cfg: ChartConfig):
    x = cfg.labels.x_title or str(data.notes.get("x_title", ""))
    y = cfg.labels.y_title or data.value_title
    return x, y


def _hist_layers(data: ChartData, cfg: ChartConfig, theme: Theme, fs: int):
    table = data.table.copy()
    table["mid"] = (table["bin_start"] + table["bin_end"]) / 2
    grouped = bool(data.groups)
    x_title, y_title = _numeric_titles(data, cfg)
    vmax = float(table["value"].max() or 0)
    domain = _value_scale(cfg, vmax, data.is_percent, cfg.display.data_labels and not grouped)
    edges = data.notes.get("edges") or []
    x_axis = _axis(x_title, cfg, theme, fs, grid=False)
    if 2 <= len(edges) <= 21:
        # Ticks on the bin edges themselves, so each bar spans two labelled ticks.
        x_axis.update(values=[float(f"{e:.6g}") for e in edges], format=".3~g")
    x_enc = {"field": "bin_start", "type": "quantitative", "title": x_title,
             "scale": {"nice": False, "zero": False}, "axis": x_axis}
    y_enc = {"field": "value", "type": "quantitative", "title": y_title, "stack": None,
             "scale": domain,
             "axis": _axis(y_title, cfg, theme, fs, grid=True, percent=data.is_percent)}
    mark: Dict[str, Any] = {"type": "bar", "stroke": "#FFFFFF", "strokeWidth": 1,
                            "opacity": 0.65 if grouped else 1}
    encoding: Dict[str, Any] = {
        "x": x_enc, "x2": {"field": "bin_end"}, "y": y_enc, "y2": {"datum": 0},
        "tooltip": [{"field": "category", "title": "Range"}, {"field": "group", "title": "Group"},
                    {"field": "display_label", "title": "Value"}]}
    if grouped:
        encoding["color"] = {"field": "group", "type": "nominal", "scale": _group_scale(data),
                             "legend": _legend(cfg, data, theme, fs, " / ".join(data.group_fields))}
    else:
        mark["color"] = theme.primary
    layers: List[Dict[str, Any]] = [{"mark": mark, "encoding": encoding}]
    if cfg.display.data_labels and not grouped and len(table) <= 15:
        layers.append({"mark": {"type": "text", "align": "center", "baseline": "bottom", "dy": -4,
                                "fontSize": max(fs - 1, 9), "color": theme.text, "font": FONT},
                       "encoding": {"x": {"field": "mid", "type": "quantitative"},
                                    "y": {"field": "value", "type": "quantitative"},
                                    "text": {"field": "display_label"}}})
    return layers, 60, table


def _box_layers(data: ChartData, cfg: ChartConfig, theme: Theme, fs: int, gap: float):
    table = data.table.copy()
    horizontal = cfg.display.orientation != "vertical"
    span = float(table["max"].max() - table["min"].min()) or 1.0
    # A zero-width bar is not drawn, so the median line is a hair-thin bar with a
    # white outline: it spans exactly the height of the box.
    table["median_hi"] = table["median"] + span * 1e-4
    table["lbl"] = "median " + table["display_label"]
    order = list(table["category"])
    q_title = cfg.labels.x_title if horizontal else cfg.labels.y_title
    q_title = q_title or str(data.notes.get("x_title", ""))
    c_title = (cfg.labels.y_title if horizontal else cfg.labels.x_title) or None
    q, q2, c = ("x", "x2", "y") if horizontal else ("y", "y2", "x")
    lo, hi = float(table["min"].min()), float(table["max"].max())
    pad = (hi - lo) * 0.06 or 1.0
    scale = {"zero": False, "nice": True,
             "domainMin": cfg.display.axis_min if cfg.display.axis_min is not None else lo - pad,
             "domainMax": cfg.display.axis_max if cfg.display.axis_max is not None else hi + pad}
    cat = {"field": "category", "type": "nominal", "sort": order, "title": c_title,
           "axis": _axis(c_title, cfg, theme, fs, grid=False),
           "scale": {"paddingInner": gap, "paddingOuter": 0.08}}
    cat_plain = {"field": "category", "type": "nominal", "sort": order}
    grouped = bool(data.groups)
    colour = ({"color": {"field": "group", "type": "nominal", "scale": _group_scale(data),
                         "legend": None}} if grouped else {})
    fill = {} if grouped else {"color": theme.primary}
    val = {"type": "quantitative", "scale": scale}
    whisker = {"mark": {"type": "rule", "color": theme.text, "strokeWidth": 1.5},
               "encoding": {c: cat,
                            q: dict(val, field="whisker_lo", title=q_title,
                                    axis=_axis(q_title, cfg, theme, fs, grid=True)),
                            q2: {"field": "whisker_hi"}}}
    box = {"mark": dict({"type": "bar", "stroke": theme.text, "strokeWidth": 1}, **fill),
           "encoding": dict({c: cat_plain, q: dict(val, field="q1"), q2: {"field": "q3"},
                             "tooltip": [{"field": "category", "title": "Group"},
                                         {"field": "count", "title": "N"},
                                         {"field": "q1", "title": "25th percentile"},
                                         {"field": "median", "title": "Median"},
                                         {"field": "q3", "title": "75th percentile"}]},
                            **colour)}
    median = {"mark": {"type": "bar", "color": "#FFFFFF", "stroke": "#FFFFFF", "strokeWidth": 3},
              "encoding": {c: cat_plain, q: dict(val, field="median"), q2: {"field": "median_hi"}}}
    layers: List[Dict[str, Any]] = [whisker, box, median]
    outliers = data.notes.get("outliers")
    if outliers is not None and len(outliers):
        layers.append({
            "data": {"values": _records(outliers)},
            "mark": dict({"type": "point", "filled": True, "size": 40, "opacity": 0.7}, **fill),
            "encoding": dict({c: cat_plain, q: {"field": "value", "type": "quantitative",
                                                "scale": scale}}, **colour)})
    if cfg.display.data_labels:
        text_mark = {"type": "text", "fontSize": max(fs - 1, 9), "color": theme.text, "font": FONT}
        if horizontal:
            text_mark.update(align="left", baseline="middle", dx=6)
        else:
            text_mark.update(align="center", baseline="bottom", dy=-6)
        layers.append({"mark": text_mark,
                       "encoding": {c: cat_plain, q: dict(val, field="whisker_hi"),
                                    "text": {"field": "lbl"}}})
    return layers, 60, table


def _sparse_values(order: List[str], target: int = 12) -> List[str]:
    """Every k-th x label so a long axis stays readable."""
    step = max(1, -(-len(order) // target))
    return order[::step]


def _line_layers(data: ChartData, cfg: ChartConfig, theme: Theme, fs: int, area: bool):
    table = data.table.copy()
    grouped = bool(data.groups)
    order = data.categories
    x_title, y_title = _numeric_titles(data, cfg)
    vmax = float(table["value"].max() or 0)
    y_scale = _value_scale(cfg, vmax, data.is_percent, False)
    y_scale["zero"] = cfg.aggregation not in ("mean", "median", "min", "max")
    x_axis = _axis(x_title, cfg, theme, fs, grid=False)
    x_axis.update(labelAngle=-40 if len(order) > 6 else 0, labelOverlap=True,
                  values=_sparse_values(order))
    x_enc = {"field": "category", "type": "ordinal", "sort": order, "title": x_title,
             "axis": x_axis, "scale": {"type": "point", "padding": 0.4}}
    stack = "zero" if (area and grouped and cfg.aggregation in ("count", "sum", "distinct")) else None
    y_enc = {"field": "value", "type": "quantitative", "title": y_title, "stack": stack,
             "scale": y_scale,
             "axis": _axis(y_title, cfg, theme, fs, grid=True, percent=data.is_percent)}
    encoding: Dict[str, Any] = {
        "x": x_enc, "y": y_enc,
        "tooltip": [{"field": "category", "title": data.notes.get("x_title") or "Period"},
                    {"field": "group", "title": "Group"},
                    {"field": "display_label", "title": "Value"}]}
    if grouped:
        encoding["color"] = {"field": "group", "type": "nominal", "scale": _group_scale(data),
                             "legend": _legend(cfg, data, theme, fs, " / ".join(data.group_fields))}
    base: Dict[str, Any] = {} if grouped else {"color": theme.primary}
    if area:
        mark = dict({"type": "area", "opacity": 0.85 if (stack or not grouped) else 0.55,
                     "line": {"strokeWidth": 2}}, **base)
    else:
        point = dict({"filled": True, "size": 55}, **base)
        mark = dict({"type": "line", "strokeWidth": 2.5, "point": point}, **base)
    layers: List[Dict[str, Any]] = [{"mark": mark, "encoding": encoding}]
    small = len(order) <= 15 and len(data.groups) <= 3
    if cfg.display.data_labels and small and not (area and stack):
        layers.append({"mark": {"type": "text", "align": "center", "baseline": "bottom", "dy": -8,
                                "fontSize": max(fs - 1, 9), "color": theme.text, "font": FONT},
                       "encoding": {"x": {"field": "category", "type": "ordinal", "sort": order},
                                    "y": {"field": "value", "type": "quantitative", "stack": None},
                                    "text": {"field": "display_label"}}})
    return layers, 90, table


def _scatter_layers(data: ChartData, cfg: ChartConfig, theme: Theme, fs: int):
    table = data.table.copy()
    grouped = bool(data.groups)
    x_title = cfg.labels.x_title or str(data.notes.get("x_title", ""))
    y_title = cfg.labels.y_title or str(data.notes.get("y_title", ""))
    y_scale: Dict[str, Any] = {"zero": False, "nice": True}
    if cfg.display.axis_min is not None:
        y_scale["domainMin"] = cfg.display.axis_min
    if cfg.display.axis_max is not None:
        y_scale["domainMax"] = cfg.display.axis_max
    encoding: Dict[str, Any] = {
        "x": {"field": "x", "type": "quantitative", "title": x_title,
              "scale": {"zero": False, "nice": True},
              "axis": _axis(x_title, cfg, theme, fs, grid=True)},
        "y": {"field": "y", "type": "quantitative", "title": y_title, "scale": y_scale,
              "axis": _axis(y_title, cfg, theme, fs, grid=True)},
        "tooltip": [{"field": "x", "title": x_title}, {"field": "y", "title": y_title},
                    {"field": "group", "title": "Group"}]}
    mark: Dict[str, Any] = {"type": "point", "filled": True, "size": 60, "opacity": 0.7}
    if grouped:
        encoding["color"] = {"field": "group", "type": "nominal", "scale": _group_scale(data),
                             "legend": _legend(cfg, data, theme, fs, " / ".join(data.group_fields))}
    else:
        mark["color"] = theme.primary
    layers: List[Dict[str, Any]] = [{"mark": mark, "encoding": encoding}]
    if cfg.display.trend_line and "fit" in data.notes:
        fit_enc: Dict[str, Any] = {"x": {"field": "x", "type": "quantitative"},
                                   "y": {"field": "y", "type": "quantitative"}}
        regression: Dict[str, Any] = {"regression": "y", "on": "x"}
        line: Dict[str, Any] = {"type": "line", "strokeWidth": 2.5}
        if grouped:
            regression["groupby"] = ["group"]
            fit_enc["color"] = {"field": "group", "type": "nominal", "scale": _group_scale(data),
                                "legend": None}
        else:
            line["color"] = theme.secondary
        layers.append({"transform": [regression], "mark": line, "encoding": fit_enc})
    return layers, 60, table
