"""
The chart builder's canvas — a `ChartRequest` painted, and savable as an image.

`core/chart_spec.py` decides what a chart *is*, and `core.chart_spec.aggregate`
computes the numbers. This paints them. Nothing here decides anything the shared
module has already decided, which is why a figure built on this screen and the
same figure in the web build are the same figure rather than two similar ones.

Painted with `QPainter`, for the reason `widgets/charts.py` gives: QtCharts pulls
in PySide6-Addons (435 MB this app never otherwise touches) and matplotlib brings
its own colour opinions, and either would become a *second* place the program
decides what blue means — the drift `core/theme.py` exists to stop.

**A chart on this screen is a chart you can put in a report.** `to_image()`
renders at a chosen scale onto an opaque background, because a figure pasted into
Word over a transparent one comes out as light text on white.

Three marks are deliberately absent. Line, area and scatter want real numeric
axes with ticks and gridlines, which is a different widget rather than a
variation on this one; asking for them says so plainly instead of drawing
something that looks right and is not.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence, Tuple

import pandas as pd
from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QImage, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QToolTip, QWidget

from core.chart_spec import MEASURE, ChartRequest, measure_title
from core.theme import get_palette
from qualsafe_qt.theme import DEFAULT_CATEGORY_PALETTE, category_colors

#: Marks this canvas paints. Anything else is refused in words.
PAINTABLE = {"bar", "bar_horizontal", "stacked_bar", "normalized_bar",
             "grouped_bar", "pie", "donut", "heatmap"}

#: Why each unpaintable mark is unpaintable, in the analyst's terms.
NOT_PAINTABLE = {
    "line": ("A line chart needs a numeric axis with ticks, which this canvas "
             "does not draw. Use a bar chart here, or build it in the web app."),
    "area": ("An area chart needs a numeric axis with ticks, which this canvas "
             "does not draw. Use a bar chart here, or build it in the web app."),
    "point": ("A scatter needs two numeric axes with ticks, which this canvas "
              "does not draw. Build it in the web app."),
}

_MARGIN = 14
_BAR_GAP = 6
_LEGEND_HEIGHT = 26
_TITLE_HEIGHT = 26



def readable_on(fill: QColor) -> QColor:
    """White or near-black text, whichever reads better on `fill`.

    A bar's value is drawn on the bar, in a colour that can be anything the palette
    holds, so the page's text colour is sometimes unreadable on it."""
    def linear(channel: int) -> float:
        c = channel / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    luminance = (0.2126 * linear(fill.red()) + 0.7152 * linear(fill.green())
                 + 0.0722 * linear(fill.blue()))
    on_white = 1.05 / (luminance + 0.05)
    on_dark = (luminance + 0.05) / (0.007 + 0.05)          # near-black is #141518
    return QColor("#FFFFFF") if on_white >= on_dark else QColor("#141518")


class ChartCanvas(QWidget):
    """Paints one `ChartRequest` over an already-aggregated frame."""

    #: A bar, slice or cell was clicked. Argument is its category label.
    item_clicked = Signal(str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._request: Optional[ChartRequest] = None
        self._frame = pd.DataFrame()
        self._message = "Put a field on each shelf and the chart appears here."
        self._mode = "dark"
        self._palette_name = DEFAULT_CATEGORY_PALETTE
        self._hits: List[Tuple[QRect, str, float]] = []
        self.setMouseTracking(True)
        self.setMinimumHeight(300)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    # -- inputs --------------------------------------------------------------

    def set_chart(self, request: Optional[ChartRequest], frame: pd.DataFrame) -> None:
        self._request = request
        self._frame = frame if frame is not None else pd.DataFrame()
        self._message = ""
        if request is not None and request.mark in NOT_PAINTABLE:
            self._message = NOT_PAINTABLE[request.mark]
        elif self._frame.empty:
            self._message = "Nothing to plot for that combination."
        self.update()

    def set_message(self, message: str) -> None:
        """Show words instead of a chart — a validation problem, or no project."""
        self._request = None
        self._frame = pd.DataFrame()
        self._message = message
        self.update()

    def set_theme_mode(self, mode: str, palette: str = "") -> None:
        self._mode = mode if mode in ("dark", "light") else "dark"
        self._palette_name = palette or self._palette_name
        self.update()

    def has_chart(self) -> bool:
        return self._request is not None and not self._frame.empty and not self._message

    # -- output --------------------------------------------------------------

    def to_image(self, scale: int = 2) -> QImage:
        """Render at `scale`x for a report.

        Opaque, always. A transparent PNG pasted into Word keeps the document's
        white background under light text and the figure disappears.
        """
        width = max(1, self.width())
        height = max(1, self.height())
        image = QImage(QSize(width * scale, height * scale),
                       QImage.Format.Format_RGB32)
        image.fill(QColor(get_palette(self._mode)["bg_elevated"]))
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.scale(scale, scale)
        self._paint(painter, QRect(0, 0, width, height))
        painter.end()
        return image

    # -- Qt overrides --------------------------------------------------------

    def paintEvent(self, _event) -> None:  # noqa: D102 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), QColor(get_palette(self._mode)["bg_elevated"]))
        self._paint(painter, self.rect())

    def mouseMoveEvent(self, event) -> None:  # noqa: D102 - Qt override
        point = event.position().toPoint()
        for rect, label, value in self._hits:
            if rect.contains(point):
                QToolTip.showText(event.globalPosition().toPoint(),
                                  f"{label}: {_pretty(value)}", self)
                return
        QToolTip.hideText()

    def mousePressEvent(self, event) -> None:  # noqa: D102 - Qt override
        point = event.position().toPoint()
        for rect, label, _value in self._hits:
            if rect.contains(point):
                self.item_clicked.emit(label)
                return

    # -- painting ------------------------------------------------------------

    def _paint(self, painter: QPainter, area: QRect) -> None:
        palette = get_palette(self._mode)
        self._hits = []

        if self._message or self._request is None:
            painter.setPen(QColor(palette["text_muted"]))
            painter.drawText(
                area.adjusted(24, 0, -24, 0),
                int(Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap),
                self._message or "No chart yet.")
            return

        plot = QRect(area)
        if self._request.title:
            painter.setPen(QColor(palette["text"]))
            font = painter.font()
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(
                QRect(area.left() + _MARGIN, area.top() + 4,
                      area.width() - 2 * _MARGIN, _TITLE_HEIGHT),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                self._request.title)
            font.setBold(False)
            painter.setFont(font)
            plot = plot.adjusted(0, _TITLE_HEIGHT, 0, 0)

        mark = self._request.mark
        if mark == "heatmap":
            self._paint_heatmap(painter, plot)
            return

        series = self._series()
        if not series:
            painter.setPen(QColor(palette["text_muted"]))
            painter.drawText(plot, Qt.AlignmentFlag.AlignCenter, "Nothing to plot.")
            return

        if mark in ("pie", "donut"):
            self._paint_arc(painter, plot, series, donut=mark == "donut")
        else:
            self._paint_bars(painter, plot, series)

    def _paint_bars(self, painter: QPainter, area: QRect,
                    series: Dict[str, Dict[str, float]]) -> None:
        """Bars, stacked, 100% stacked and grouped — one routine, four modes.

        They differ only in how a category's parts are laid out, so four painters
        would be four places to fix the same alignment bug.
        """
        palette = get_palette(self._mode)
        colours = category_colors(self._mode, self._palette_name)
        mark = self._request.mark if self._request else "bar"
        horizontal = mark == "bar_horizontal"
        stacked = mark in ("stacked_bar", "normalized_bar")
        normalized = mark == "normalized_bar"
        parts = self._part_names(series)

        metrics = QFontMetrics(painter.font())
        legend = _LEGEND_HEIGHT if len(parts) > 1 else 0
        body = area.adjusted(_MARGIN, _MARGIN, -_MARGIN, -_MARGIN - legend)

        categories = list(series)
        totals = {c: sum(series[c].values()) for c in categories}
        largest = 1.0 if normalized else max(list(totals.values()) + [0.0001])

        label_space = min(
            max(110, body.width() // 4),
            max((metrics.horizontalAdvance(c) for c in categories), default=60) + 12)
        span = body.height() if horizontal else body.width() - label_space // 4
        slot = max(16, span // max(1, len(categories)))

        for index, category in enumerate(categories):
            total = totals[category] or 0.0001
            offset = 0.0
            for part_index, part in enumerate(parts):
                value = series[category].get(part, 0.0)
                if not value:
                    continue
                fraction = (value / total) if normalized else (value / largest)
                colour = QColor(colours[part_index % len(colours)])

                if horizontal:
                    plot_width = body.width() - label_space
                    top = body.top() + index * slot + _BAR_GAP // 2
                    height = slot - _BAR_GAP
                    left = body.left() + label_space
                    if stacked or len(parts) == 1:
                        left += int(plot_width * offset)
                        width = int(plot_width * fraction)
                    else:
                        sub = max(2, height // max(1, len(parts)))
                        top += sub * part_index
                        height = sub - 1
                        width = int(plot_width * fraction)
                    rect = QRect(left, top, max(2, width), max(2, height))
                else:
                    plot_height = body.height() - metrics.height() - 4
                    left = body.left() + label_space // 4 + index * slot + _BAR_GAP // 2
                    width = slot - _BAR_GAP
                    height = int(plot_height * fraction)
                    if stacked or len(parts) == 1:
                        top = body.top() + plot_height - height - int(plot_height * offset)
                    else:
                        sub = max(2, width // max(1, len(parts)))
                        left += sub * part_index
                        width = sub - 1
                        top = body.top() + plot_height - height
                    rect = QRect(left, top, max(2, width), max(2, height))

                painter.fillRect(rect, colour)
                label = f"{category} · {part}" if len(parts) > 1 else category
                self._hits.append((rect, label, value))
                if stacked or len(parts) == 1:
                    offset += fraction

                # The number, on the bar. A figure in a report is read on paper,
                # where there is no tooltip to hover — a bar with no value on it
                # is a shape. Only drawn where it fits: a squeezed label
                # overlapping the next bar is worse than none.
                if not stacked or len(parts) == 1:
                    text = _pretty(value)
                    if horizontal and rect.width() > metrics.horizontalAdvance(text) + 10:
                        painter.setPen(readable_on(QColor(colour)))
                        painter.drawText(
                            rect.adjusted(6, 0, -4, 0),
                            int(Qt.AlignmentFlag.AlignLeft
                                | Qt.AlignmentFlag.AlignVCenter), text)
                    elif not horizontal and rect.height() > metrics.height() + 6:
                        painter.setPen(readable_on(QColor(colour)))
                        painter.drawText(
                            rect.adjusted(0, 2, 0, 0),
                            int(Qt.AlignmentFlag.AlignHCenter
                                | Qt.AlignmentFlag.AlignTop), text)

            painter.setPen(QColor(palette["text"]))
            if horizontal:
                painter.drawText(
                    QRect(body.left(), body.top() + index * slot, label_space - 6, slot),
                    int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                    metrics.elidedText(category, Qt.TextElideMode.ElideRight,
                                       label_space - 10))
            else:
                painter.drawText(
                    QRect(body.left() + label_space // 4 + index * slot,
                          body.bottom() - metrics.height(), slot, metrics.height()),
                    int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter),
                    metrics.elidedText(category, Qt.TextElideMode.ElideRight, slot - 4))

        if len(parts) > 1:
            self._paint_legend(
                painter,
                QRect(area.left() + _MARGIN, area.bottom() - _LEGEND_HEIGHT,
                      area.width() - 2 * _MARGIN, _LEGEND_HEIGHT),
                parts, colours)

    def _paint_arc(self, painter: QPainter, area: QRect,
                   series: Dict[str, Dict[str, float]], *, donut: bool) -> None:
        palette = get_palette(self._mode)
        colours = category_colors(self._mode, self._palette_name)

        slices = [(name, sum(parts.values())) for name, parts in series.items()]
        slices = [(name, value) for name, value in slices if value > 0]
        total = sum(value for _name, value in slices)
        if total <= 0:
            painter.setPen(QColor(palette["text_muted"]))
            painter.drawText(area, Qt.AlignmentFlag.AlignCenter, "Nothing to plot.")
            return

        legend_rect = QRect(area.left() + _MARGIN, area.bottom() - _LEGEND_HEIGHT,
                            area.width() - 2 * _MARGIN, _LEGEND_HEIGHT)
        body = area.adjusted(_MARGIN, _MARGIN, -_MARGIN, -_MARGIN - _LEGEND_HEIGHT)
        side = max(40, min(body.width(), body.height()))
        square = QRect(body.center().x() - side // 2, body.center().y() - side // 2,
                       side, side)

        start = 90 * 16  # twelve o'clock, running clockwise — how a pie is read
        for index, (name, value) in enumerate(slices):
            sweep = int(-360 * 16 * (value / total))
            painter.setBrush(QColor(colours[index % len(colours)]))
            painter.setPen(QPen(QColor(palette["bg_elevated"]), 2))
            painter.drawPie(square, start, sweep)
            middle = math.radians((start + sweep / 2) / 16)
            point = QPoint(int(square.center().x() + math.cos(middle) * side * 0.3),
                           int(square.center().y() - math.sin(middle) * side * 0.3))
            self._hits.append((QRect(point.x() - 18, point.y() - 18, 36, 36),
                               name, value))
            start += sweep

        if donut:
            hole = square.adjusted(side // 4, side // 4, -side // 4, -side // 4)
            painter.setBrush(QColor(palette["bg_elevated"]))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(hole)

        painter.setBrush(Qt.BrushStyle.NoBrush)
        self._paint_legend(painter, legend_rect,
                           [name for name, _v in slices], colours)

    def _paint_heatmap(self, painter: QPainter, area: QRect) -> None:
        palette = get_palette(self._mode)
        request = self._request
        if request is None:
            return
        x_field, y_field = request.x.field, request.y.field
        if (not x_field or not y_field or MEASURE not in self._frame.columns
                or x_field not in self._frame.columns
                or y_field not in self._frame.columns):
            painter.setPen(QColor(palette["text_muted"]))
            painter.drawText(area, Qt.AlignmentFlag.AlignCenter,
                             "A heatmap needs a field on X and on Y.")
            return

        xs = list(dict.fromkeys(self._frame[x_field].astype(str)))
        ys = list(dict.fromkeys(self._frame[y_field].astype(str)))
        lookup = {(str(row[x_field]), str(row[y_field])): float(row[MEASURE])
                  for _i, row in self._frame.iterrows()}
        largest = max(lookup.values()) if lookup else 1.0

        metrics = QFontMetrics(painter.font())
        label_space = min(
            max(90, area.width() // 5),
            max((metrics.horizontalAdvance(y) for y in ys), default=60) + 10)
        body = area.adjusted(_MARGIN + label_space, _MARGIN, -_MARGIN,
                             -_MARGIN - metrics.height())
        cell_w = max(8, body.width() // max(1, len(xs)))
        cell_h = max(8, body.height() // max(1, len(ys)))
        # The skin's ramp, not the named default. `heatmap_range()` returns the
        # dark ramp whatever the mode, so on the light skin the low end came out
        # navy and the eye read the emptiest cells as the fullest. The palette's
        # own `heat` is built per skin for exactly this reason, which is also
        # what `core.theme.altair_theme` gives the web build.
        ramp = [QColor(c) for c in palette["heat"]]

        for row_index, y_value in enumerate(ys):
            for column, x_value in enumerate(xs):
                value = lookup.get((x_value, y_value), 0.0)
                rect = QRect(body.left() + column * cell_w,
                             body.top() + row_index * cell_h,
                             cell_w - 1, cell_h - 1)
                painter.fillRect(rect, _ramp_colour(ramp, value, largest))
                self._hits.append((rect, f"{x_value} · {y_value}", value))
            painter.setPen(QColor(palette["text"]))
            painter.drawText(
                QRect(area.left() + _MARGIN, body.top() + row_index * cell_h,
                      label_space - 6, cell_h),
                int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                metrics.elidedText(y_value, Qt.TextElideMode.ElideRight,
                                   label_space - 10))

        painter.setPen(QColor(palette["text_muted"]))
        for column, x_value in enumerate(xs):
            painter.drawText(
                QRect(body.left() + column * cell_w, body.bottom() + 2, cell_w,
                      metrics.height()),
                int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter),
                metrics.elidedText(x_value, Qt.TextElideMode.ElideRight, cell_w - 2))

        self._paint_scale(painter, ramp, largest,
                          QRect(area.left() + _MARGIN, area.bottom() - 16,
                                min(200, area.width() // 3), 12))

    def _paint_scale(self, painter: QPainter, ramp: List[QColor], largest: float,
                     area: QRect) -> None:
        """The colour ramp with its ends labelled.

        A heatmap without one says "these cells differ" and nothing about by how
        much — which is exactly the defect a rendered picture caught in the
        co-occurrence chart (HANDOFF_QT §8).
        """
        palette = get_palette(self._mode)
        metrics = QFontMetrics(painter.font())
        steps = max(1, len(ramp) - 1)
        width = max(1, area.width() // (steps + 1))
        for index, colour in enumerate(ramp):
            painter.fillRect(QRect(area.left() + index * width, area.top(),
                                   width, area.height()), colour)
        painter.setPen(QColor(palette["text_muted"]))
        painter.drawText(QRect(area.left(), area.top() - metrics.height(),
                               area.width(), metrics.height()),
                         int(Qt.AlignmentFlag.AlignLeft), "0")
        painter.drawText(QRect(area.left(), area.top() - metrics.height(),
                               area.width(), metrics.height()),
                         int(Qt.AlignmentFlag.AlignRight), _pretty(largest))

    def _paint_legend(self, painter: QPainter, area: QRect,
                      names: Sequence[str], colours: Sequence[str]) -> None:
        palette = get_palette(self._mode)
        metrics = QFontMetrics(painter.font())
        x = area.left()
        for index, name in enumerate(names):
            painter.fillRect(QRect(x, area.top() + 6, 10, 10),
                             QColor(colours[index % len(colours)]))
            painter.setPen(QColor(palette["text_muted"]))
            width = metrics.horizontalAdvance(name) + 6
            painter.drawText(
                QRect(x + 14, area.top(), width, area.height()),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), name)
            x += 14 + width + 10
            if x > area.right() - 40:
                break

    # -- data shaping --------------------------------------------------------

    def _series(self) -> Dict[str, Dict[str, float]]:
        """`{category: {part: value}}` — the one shape every mark here paints.

        Reads the frame `core.chart_spec.aggregate` produced and never aggregates
        anything itself, because a second implementation of "count rows per code"
        would be a second answer to a question already answered.
        """
        request = self._request
        if request is None or self._frame.empty or MEASURE not in self._frame.columns:
            return {}

        arc = request.mark in ("pie", "donut")
        category_field = request.color.field if arc else request.x.field
        if not category_field or category_field not in self._frame.columns:
            return {}
        part_field = "" if arc else request.color.field

        measure_shelf = request.y if request.y.aggregate else request.x
        default_part = measure_title(measure_shelf)

        out: Dict[str, Dict[str, float]] = {}
        for _index, row in self._frame.iterrows():
            category = str(row[category_field])
            part = (str(row[part_field])
                    if part_field and part_field in self._frame.columns
                    else default_part)
            bucket = out.setdefault(category, {})
            bucket[part] = bucket.get(part, 0.0) + float(row[MEASURE])
        return out

    def _part_names(self, series: Dict[str, Dict[str, float]]) -> List[str]:
        names: List[str] = []
        for parts in series.values():
            for part in parts:
                if part not in names:
                    names.append(part)
        return names


def _ramp_colour(ramp: List[QColor], value: float, largest: float) -> QColor:
    if largest <= 0:
        return ramp[0]
    position = max(0.0, min(1.0, value / largest)) * (len(ramp) - 1)
    low = int(math.floor(position))
    high = min(len(ramp) - 1, low + 1)
    blend = position - low
    a, b = ramp[low], ramp[high]
    return QColor(int(a.red() + (b.red() - a.red()) * blend),
                  int(a.green() + (b.green() - a.green()) * blend),
                  int(a.blue() + (b.blue() - a.blue()) * blend))


def _pretty(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return f"{value:.2f}"
