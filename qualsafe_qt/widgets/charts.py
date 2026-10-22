"""
The two charts the Analysis screen needs, painted directly.

The Streamlit build draws these with Altair. Qt has no Altair, and the obvious
alternatives each cost something: QtCharts pulls in PySide6-Addons and styles
itself, matplotlib is a new dependency with its own colour opinions. Both would
end up as a *second* place the app decides what blue means — which is exactly the
drift `core/theme.py` was created to stop.

So these are painted with `QPainter` from the same palette. Two small widgets,
no dependency, and a co-occurrence cell is the same colour it would be in the
Streamlit heatmap because both read `core.theme.heatmap_range`.

Both widgets emit a signal when something is clicked, so drill-back works the way
it does everywhere else in this app: see the number, click it, read the evidence.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

from PySide6.QtCore import QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QToolTip, QWidget

from core.theme import get_palette, heatmap_range
from qualsafe_qt.theme import DEFAULT_CATEGORY_PALETTE, category_colors

_LABEL_GAP = 10
_BAR_GAP = 4
_MIN_BAR_HEIGHT = 18
#: Vertical room reserved under the heatmap grid for its colour scale.
_SCALE_HEIGHT = 40
_MAX_BAR_HEIGHT = 34


class BarChart(QWidget):
    """Horizontal bars, longest first — code frequency.

    Horizontal rather than vertical because code names are words, and vertical
    bars force them into rotated or truncated labels.
    """

    #: A bar was clicked. Argument is its label.
    bar_clicked = Signal(str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._items: List[Tuple[str, float]] = []
        self._mode = "dark"
        self._value_suffix = ""
        self._palette = DEFAULT_CATEGORY_PALETTE
        self._rects: List[Tuple[QRect, str, float]] = []
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

    def set_data(self, items: Sequence[Tuple[str, float]], *, value_suffix: str = "") -> None:
        """`items` as (label, value), drawn in the order given."""
        self._items = [(str(a), float(b)) for a, b in items]
        self._value_suffix = value_suffix
        self.updateGeometry()
        self.update()

    def set_theme_mode(self, mode: str, palette: str = "") -> None:
        self._mode = mode if mode in ("dark", "light") else "dark"
        self._palette = palette or self._palette
        self.update()

    def sizeHint(self) -> QSize:  # noqa: D102 - Qt override
        rows = max(1, len(self._items))
        return QSize(400, rows * (_MAX_BAR_HEIGHT + _BAR_GAP) + 16)

    def minimumSizeHint(self) -> QSize:  # noqa: D102 - Qt override
        rows = max(1, len(self._items))
        return QSize(240, rows * (_MIN_BAR_HEIGHT + _BAR_GAP) + 16)

    def mouseMoveEvent(self, event) -> None:  # noqa: D102 - Qt override
        point = event.position().toPoint()
        for rect, label, value in self._rects:
            if rect.contains(point):
                QToolTip.showText(event.globalPosition().toPoint(),
                                  f"{label}: {_pretty(value)}{self._value_suffix}", self)
                return
        QToolTip.hideText()

    def mousePressEvent(self, event) -> None:  # noqa: D102 - Qt override
        point = event.position().toPoint()
        for rect, label, _value in self._rects:
            if rect.contains(point):
                self.bar_clicked.emit(label)
                return

    def paintEvent(self, _event) -> None:  # noqa: D102 - Qt override
        palette = get_palette(self._mode)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), QColor(palette["bg_elevated"]))
        self._rects = []
        if not self._items:
            painter.setPen(QColor(palette["text_muted"]))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No data yet.")
            return

        metrics = QFontMetrics(self.font())
        label_width = min(
            max(240, self.width() // 3),
            max(metrics.horizontalAdvance(label) for label, _v in self._items) + 12,
        )
        value_width = max(
            metrics.horizontalAdvance(_pretty(v) + self._value_suffix)
            for _l, v in self._items) + 10

        available = max(1, len(self._items))
        height = max(_MIN_BAR_HEIGHT,
                     min(_MAX_BAR_HEIGHT, (self.height() - 16) // available - _BAR_GAP))
        plot_left = label_width + _LABEL_GAP
        plot_width = max(10, self.width() - plot_left - value_width - 12)
        largest = max((v for _l, v in self._items), default=1.0) or 1.0

        bar_color = QColor(category_colors(self._mode, self._palette)[0])
        y = 8
        for label, value in self._items:
            bar_length = int(plot_width * (value / largest))
            rect = QRect(plot_left, y, max(2, bar_length), height)
            painter.fillRect(rect, bar_color)

            painter.setPen(QColor(palette["text"]))
            painter.drawText(
                QRect(0, y, label_width, height),
                int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                metrics.elidedText(label, Qt.TextElideMode.ElideRight, label_width))
            painter.setPen(QColor(palette["text_muted"]))
            painter.drawText(
                QRect(plot_left + bar_length + 6, y, value_width, height),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                _pretty(value) + self._value_suffix)

            # The whole row is the click target, not just the drawn bar: a code
            # with one application would otherwise be a 2px sliver to hit.
            self._rects.append(
                (QRect(0, y, self.width(), height), label, value))
            y += height + _BAR_GAP


class Heatmap(QWidget):
    """Square code x code matrix — co-occurrence.

    Colours come from `core.theme.heatmap_range`, so a cell here is the colour
    the same cell would be in the Streamlit chart. Every ramp in that module
    deliberately starts at a *visible* colour rather than the page background, so
    a low count reads as a low count instead of an empty grid.
    """

    #: A cell was clicked. Arguments are (row label, column label).
    cell_clicked = Signal(str, str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._labels: List[str] = []
        self._values: Dict[Tuple[int, int], float] = {}
        self._largest = 1.0
        self._mode = "dark"
        self._scheme = "Blue → Orange"
        self._cells: List[Tuple[QRect, int, int]] = []
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_matrix(self, matrix) -> None:
        """`matrix` is a square DataFrame indexed and columned by code name."""
        self._labels = [str(c) for c in matrix.columns]
        self._values = {}
        largest = 0.0
        for r, _row_name in enumerate(matrix.index):
            for c in range(len(matrix.columns)):
                value = float(matrix.iat[r, c])
                self._values[(r, c)] = value
                if r != c:                      # the diagonal dwarfs the rest
                    largest = max(largest, value)
        self._largest = largest or 1.0
        self.update()

    def set_theme_mode(self, mode: str) -> None:
        self._mode = mode if mode in ("dark", "light") else "dark"
        self.update()

    def set_scheme(self, scheme: str) -> None:
        self._scheme = scheme
        self.update()

    def mouseMoveEvent(self, event) -> None:  # noqa: D102 - Qt override
        point = event.position().toPoint()
        for rect, row, col in self._cells:
            if rect.contains(point):
                QToolTip.showText(
                    event.globalPosition().toPoint(),
                    f"{self._labels[row]}  +  {self._labels[col]}\n"
                    f"{_pretty(self._values.get((row, col), 0))}"
                    + ("  (total for this code)" if row == col else ""),
                    self)
                return
        QToolTip.hideText()

    def mousePressEvent(self, event) -> None:  # noqa: D102 - Qt override
        point = event.position().toPoint()
        for rect, row, col in self._cells:
            if rect.contains(point) and row != col:
                self.cell_clicked.emit(self._labels[row], self._labels[col])
                return

    def paintEvent(self, _event) -> None:  # noqa: D102 - Qt override
        palette = get_palette(self._mode)
        ramp = [QColor(c) for c in heatmap_range(self._scheme)]
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(palette["bg_elevated"]))
        self._cells = []
        if not self._labels:
            painter.setPen(QColor(palette["text_muted"]))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                             "No co-occurrence to show.")
            return

        metrics = QFontMetrics(self.font())
        n = len(self._labels)
        margin = min(190, max(90, max(
            metrics.horizontalAdvance(label) for label in self._labels) + 12))
        # Leave room under the grid for the colour scale.
        grid = max(10, min(self.width() - margin - 12,
                           self.height() - margin - 12 - _SCALE_HEIGHT))
        cell = max(8, grid // n)
        grid = cell * n
        left, top = margin, margin

        for row in range(n):
            for col in range(n):
                value = self._values.get((row, col), 0.0)
                rect = QRect(left + col * cell, top + row * cell, cell - 1, cell - 1)
                painter.fillRect(rect, _ramp_color(ramp, value, self._largest,
                                                   diagonal=(row == col)))
                self._cells.append((rect, row, col))

        painter.setPen(QColor(palette["text"]))
        for i, label in enumerate(self._labels):
            shown = metrics.elidedText(label, Qt.TextElideMode.ElideRight, margin - 10)
            painter.drawText(
                QRect(0, top + i * cell, margin - 8, cell),
                int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter), shown)
            # Column labels rotated: horizontal ones would overlap at any real
            # codebook size.
            painter.save()
            painter.translate(left + i * cell + cell // 2, top - 8)
            painter.rotate(-60)
            painter.drawText(0, 0, shown)
            painter.restore()

        painter.setPen(QPen(QColor(palette["border"]), 1))
        painter.drawRect(QRect(left, top, grid, grid))
        self._paint_scale(painter, palette, ramp, left, top + grid + 14, grid)

    def _paint_scale(self, painter: QPainter, palette, ramp: List[QColor],
                     left: int, top: int, width: int) -> None:
        """A low->high colour key.

        Tooltips give the exact count on hover, but without a scale a reader
        glancing at the matrix cannot tell whether orange means 3 or 30 — and a
        heatmap whose colours carry no magnitude is decoration.
        """
        if top + 30 > self.height():
            return
        bar_width = min(220, max(120, width // 3))
        bar_height = 10
        for i in range(bar_width):
            colour = _ramp_color(ramp, i / max(1, bar_width - 1), 1.0, diagonal=False)
            painter.fillRect(QRect(left + i, top, 1, bar_height), colour)
        painter.setPen(QColor(palette["text_muted"]))
        painter.drawText(left, top + bar_height + 14, "0")
        painter.drawText(left + bar_width - 24, top + bar_height + 14,
                         _pretty(self._largest))
        painter.drawText(left + bar_width + 14, top + bar_height,
                         "co-occurrences (the diagonal is each code's own total)")


def _ramp_color(ramp: List[QColor], value: float, largest: float,
                *, diagonal: bool) -> QColor:
    """Interpolate `value` along the ramp.

    The diagonal is a code's own total, which is always the largest number in
    its row and would flatten every real co-occurrence to the bottom of the
    scale. It is drawn muted and excluded from the scale entirely.
    """
    if diagonal:
        base = QColor(ramp[0])
        base.setAlpha(90)
        return base
    if largest <= 0:
        return ramp[0]
    position = max(0.0, min(1.0, value / largest)) * (len(ramp) - 1)
    low = int(position)
    high = min(low + 1, len(ramp) - 1)
    fraction = position - low
    a, b = ramp[low], ramp[high]
    return QColor(
        int(a.red() + (b.red() - a.red()) * fraction),
        int(a.green() + (b.green() - a.green()) * fraction),
        int(a.blue() + (b.blue() - a.blue()) * fraction),
    )


def _pretty(value: float) -> str:
    """Whole numbers without a trailing .0; fractions to one decimal."""
    return str(int(value)) if float(value).is_integer() else f"{value:.1f}"
