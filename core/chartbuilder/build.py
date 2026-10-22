"""
Orchestration: the one call a front end makes.

    data, spec = build(frame, config)

`aggregate` produces the numbers, `themes` assigns colours, and the renderer turns
the finished `ChartData` into a Vega-Lite spec. Front ends never call the pieces
in a different order, so a chart in the web build and the desktop build cannot
differ by a step somebody skipped.
"""

from __future__ import annotations

from typing import Dict, Optional, Tuple

import pandas as pd

from core.chartbuilder import themes
from core.chartbuilder.aggregate import ChartBuildError, ChartData, aggregate
from core.chartbuilder.config import NUMERIC_CHARTS, ChartConfig

_ARC_TYPES = ("pie", "donut")
_STACKED = ("stacked_bar", "normalized_bar")


def color_dimension(cfg: ChartConfig, categories, has_groups: bool) -> str:
    """What carries colour: "category", "group", or "none" (one primary colour)."""
    if cfg.chart_type in NUMERIC_CHARTS:
        return "group" if has_groups else "none"
    if cfg.chart_type in _ARC_TYPES + _STACKED or cfg.kind == "matrix":
        return "category"
    if has_groups:
        return "group"
    scale = themes.resolve_scale(categories, cfg.theme.semantic_scale)
    if scale or cfg.theme.color_overrides:
        return "category"
    return "none"


def colorize(data: ChartData, cfg: ChartConfig,
             custom_themes: Optional[Dict[str, themes.Theme]] = None
             ) -> Tuple[ChartData, themes.Theme]:
    """Fill the canonical table's `color` column and the colour metadata."""
    theme = themes.get_theme(cfg.theme.name, custom_themes)
    dimension = color_dimension(cfg, data.categories, bool(data.groups))
    table = data.table.copy()
    scale = themes.resolve_scale(data.categories, cfg.theme.semantic_scale)

    if dimension == "category":
        mapping = themes.category_colors(
            data.categories, theme, scale=cfg.theme.semantic_scale,
            overrides=cfg.theme.color_overrides)
        table["color"] = table["category"].map(mapping)
        data.stack_border = themes.adjacent_duplicates(data.categories, mapping)
    elif dimension == "group":
        mapping = themes.category_colors(
            data.groups, theme, scale="none",
            overrides=cfg.theme.color_overrides)
        table["color"] = table["group"].map(mapping)
    else:
        table["color"] = theme.primary
    data.table = table
    data.color_by = dimension
    data.scale = scale
    return data, theme


def build_data(frame: pd.DataFrame, cfg: ChartConfig,
               custom_themes: Optional[Dict[str, themes.Theme]] = None
               ) -> Tuple[ChartData, themes.Theme]:
    """Aggregate then colour. Raises `ChartBuildError` with a sentence."""
    data = aggregate(frame, cfg)
    return colorize(data, cfg, custom_themes)


__all__ = ["ChartBuildError", "build_data", "colorize", "color_dimension"]
