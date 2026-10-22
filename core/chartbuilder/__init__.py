"""
Chart Builder: a general chart builder for uploaded tabular data, strongest on
survey and institutional-research files.

Layers, each importable and testable alone (no Streamlit, no Qt):

    loader      CSV/XLSX/XLS bytes -> `LoadedTable` (source never modified)
    clean       missing tokens, whitespace, similar-label detection
    profile     column types, missing counts, warnings
    config      `ChartConfig` (the whole saved chart) and `EditHistory` (undo)
    transform   filters and recode (rename / combine / exclude), non-destructive
    aggregate   frame + config -> the canonical chart-ready table
    themes      colour themes, default, semantic scale colours
    labels      "93% (519/558)" and number formatting
    build       aggregate + colour, the call front ends make
    render      canonical table -> Vega-Lite spec
    export      PNG/SVG/PDF, CSV/XLSX tables, safe filenames

This sits beside `core/chart_spec.py` (the shelf builder over coded data) rather
than inside it: that one is a Tableau-style pivot over a project's codings, this
one starts from an arbitrary uploaded file and adds survey structures, recoding,
themes and saved chart definitions. Both emit Vega-Lite and export through
`vl-convert`, so a figure looks the same in the web and desktop builds.
"""

from core.chartbuilder.aggregate import CANONICAL_COLUMNS, ChartBuildError, ChartData
from core.chartbuilder.config import ChartConfig, EditHistory

__all__ = ["CANONICAL_COLUMNS", "ChartBuildError", "ChartData", "ChartConfig",
           "EditHistory"]
