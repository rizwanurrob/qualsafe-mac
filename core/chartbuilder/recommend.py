"""
Chart recommendations: what to suggest, and why, never what to force.

The result is a ranked list. One entry is `primary` (what the UI pre-selects or
badges); the rest are reasonable alternatives with the reason attached. Nothing
here changes the config: the analyst stays in control, and a pie is never the
primary choice just because a field is categorical.

Chart types the renderer cannot draw yet are still listed, with
``available=False``, so the UI can show "line chart (coming)" beside a date field
instead of silently offering a bar chart of dates.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from core.chartbuilder import profile
from core.chartbuilder.config import ChartConfig
from core.chartbuilder.render import AVAILABLE_TYPES
from core.chartbuilder.themes import detect_scale

#: Up to this many slices a pie is honest; above it, a bar reads better.
PIE_MAX_CATEGORIES = 6


@dataclass(frozen=True)
class Recommendation:
    chart_type: str
    reason: str
    primary: bool = False

    @property
    def available(self) -> bool:
        return self.chart_type in AVAILABLE_TYPES


def _rec(kind: str, reason: str, primary: bool = False) -> Recommendation:
    return Recommendation(kind, reason, primary)


def recommend(cfg: ChartConfig, table: Optional[profile.TableProfile] = None,
              n_categories: Optional[int] = None,
              categories: Optional[List[str]] = None) -> List[Recommendation]:
    """Ranked suggestions for the current selection.

    `n_categories` / `categories` describe the analysed field once recoding has
    been applied (`ChartData.categories`); without them the profile's unique
    count is used.
    """
    def col(name: str) -> Optional[profile.ColumnProfile]:
        try:
            return table.column(name) if table else None
        except KeyError:
            return None

    if cfg.kind == "matrix":
        return [
            _rec("normalized_bar", "A matrix of ratings reads best as 100% stacked "
                 "horizontal bars, one per item.", True),
            _rec("stacked_bar", "Stacked counts show how many answered each item."),
            _rec("grouped_bar", "Grouped bars compare one response across items."),
            _rec("donut", "One donut per item, if there are few items."),
            _rec("heatmap", "Items by response, shaded by percent."),
        ]
    if cfg.kind == "multi":
        return [
            _rec("bar_horizontal", "Select-all answers are separate options, not "
                 "parts of one whole, so bars rather than a pie.", True),
            _rec("bar", "Vertical bars work when the option labels are short."),
        ]
    if cfg.kind == "text":
        return [_rec("bar_horizontal", "Keyword frequencies read as ranked bars.", True)]

    field = col(cfg.column)
    if field is not None and field.kind == profile.DATETIME:
        return [_rec("line", "A date field is a time series: a line shows the trend.", True),
                _rec("area", "An area chart emphasises volume over time."),
                _rec("bar", "Bars per period, if there are few periods.")]
    if field is not None and field.kind == profile.NUMERIC and not field.numeric_like_scale:
        other = col(cfg.value_field) if cfg.value_field else None
        if other is not None and other.kind == profile.NUMERIC:
            return [_rec("scatter", "Two numeric fields: a scatter shows the relationship.", True)]
        return [_rec("histogram", "A continuous number is best seen as a distribution.", True),
                _rec("box", "A box plot summarises the spread and outliers.")]

    n = n_categories if n_categories is not None else (field.n_unique if field else 0)
    ordered = detect_scale(categories or []) if categories else None
    if cfg.group_by:
        return [_rec("grouped_bar", "Grouped bars compare the categories across groups.", True),
                _rec("normalized_bar", "100% stacked bars compare the shape of each group."),
                _rec("heatmap", "A heatmap suits many categories by many groups.")]
    if n > PIE_MAX_CATEGORIES:
        return [_rec("bar_horizontal", f"{n} categories: horizontal bars keep the "
                     "labels readable and the ranking clear.", True),
                _rec("bar", "Vertical bars, if the labels are short.")]
    recs = [_rec("bar_horizontal", "Horizontal bars are the clearest default for "
                 "survey answers.", True),
            _rec("bar", "Vertical bars suit a few short labels.")]
    if 2 <= n <= PIE_MAX_CATEGORIES and not ordered:
        recs.append(_rec("donut", "Parts of one whole, with few enough slices to compare."))
        recs.append(_rec("pie", "A pie is acceptable for parts of a whole at this size."))
    return recs
