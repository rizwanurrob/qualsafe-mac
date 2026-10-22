"""
The code network, painted.

`analysis/code_network.py` decides what the network *is* and where every node
goes. This paints it. Nothing here computes a position, which is the whole point:
the layout is deterministic in core, so the figure on this screen and the figure
in the web build are the same figure rather than two similar ones — and a
researcher can put either in a paper and have a reviewer reproduce it.

That property is worth more than it sounds. Every rival's network view
(ATLAS.ti, MAXQDA's MAXMaps, NVivo's concept maps) is force-directed from a
random seed and rearranges itself on every open, so it can be looked at but not
cited.

`QPainter`, for the reason `widgets/chart_canvas.py` gives: QtCharts pulls in
PySide6-Addons (435 MB this app never otherwise touches), and either that or
matplotlib would become a second place the program decides what a colour means.

**A network on this screen is a network you can put in a report.** `to_image()`
renders at a chosen scale onto an opaque background, because a transparent PNG
pasted into Word keeps the document's white under light text and the figure
disappears.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QImage, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QToolTip, QWidget

from analysis.code_network import CodeNetwork
from core.theme import get_palette
from qualsafe_qt.theme import DEFAULT_CATEGORY_PALETTE, category_colors

_MARGIN = 18
#: Room for the longest label to sit above its node without leaving the canvas.
_LABEL_HEADROOM = 16

_MIN_RADIUS = 7.0
_MAX_RADIUS = 26.0
_MIN_EDGE_WIDTH = 1.0
_MAX_EDGE_WIDTH = 6.0


class NetworkCanvas(QWidget):
    """Paints one `CodeNetwork`, and reports what was clicked."""

    node_clicked = Signal(str)
    edge_clicked = Signal(str, str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._network: Optional[CodeNetwork] = None
        self._message = ""
        self._mode = "dark"
        self._node_hits: List[Tuple[QRect, str, int]] = []
        self._edge_hits: List[Tuple[QRect, str, str, float, int]] = []
        self.setMinimumHeight(340)
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    # -- input ---------------------------------------------------------------

    def set_network(self, network: Optional[CodeNetwork]) -> None:
        """Show a network, or its refusal.

        A refusal is a sentence the module wrote, not an empty canvas: "no two
        codes co-occur above this threshold" is an answer, and an empty box is
        not.
        """
        self._network = network
        self._message = network.refusal if network is not None else ""
        if network is not None and not network.usable and not self._message:
            self._message = "Nothing to draw."
        self.update()

    def set_message(self, message: str) -> None:
        self._network = None
        self._message = message
        self.update()

    def set_theme_mode(self, mode: str) -> None:
        self._mode = mode if mode in ("dark", "light") else "dark"
        self.update()

    def has_network(self) -> bool:
        return (self._network is not None and self._network.usable
                and not self._message)

    # -- output --------------------------------------------------------------

    def to_image(self, scale: int = 2) -> QImage:
        """Render at `scale`x for a report. Opaque, always."""
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
        painter.fillRect(self.rect(),
                         QColor(get_palette(self._mode)["bg_elevated"]))
        self._paint(painter, self.rect())

    def mouseMoveEvent(self, event) -> None:  # noqa: D102 - Qt override
        point = event.position().toPoint()
        for rect, name, count in self._node_hits:
            if rect.contains(point):
                QToolTip.showText(
                    event.globalPosition().toPoint(),
                    f"{name}: {count} unit(s) coded", self)
                return
        for rect, a, b, strength, count in self._edge_hits:
            if rect.contains(point):
                QToolTip.showText(
                    event.globalPosition().toPoint(),
                    f"{a} + {b}: {count} unit(s), strength {strength:.2f}", self)
                return
        QToolTip.hideText()

    def mousePressEvent(self, event) -> None:  # noqa: D102 - Qt override
        point = event.position().toPoint()
        for rect, name, _count in self._node_hits:
            if rect.contains(point):
                self.node_clicked.emit(name)
                return
        for rect, a, b, _strength, _count in self._edge_hits:
            if rect.contains(point):
                self.edge_clicked.emit(a, b)
                return

    # -- painting ------------------------------------------------------------

    def _paint(self, painter: QPainter, area: QRect) -> None:
        palette = get_palette(self._mode)
        self._node_hits = []
        self._edge_hits = []

        if self._message or self._network is None or not self._network.usable:
            self._paint_message(painter, area, palette)
            return

        network = self._network
        metrics = QFontMetrics(painter.font())
        # The same first colour the chart canvas gives a single series, so a
        # network and a bar chart in one report do not disagree about the
        # program's blue.
        accent = QColor(category_colors(self._mode, DEFAULT_CATEGORY_PALETTE)[0])

        # Inset by the largest radius, not just the margin: a node at x = 1.0 is
        # a *centre* at the boundary, so without this the biggest circles and
        # their labels are drawn half outside the widget.
        edge_room = _MARGIN + int(_MAX_RADIUS)
        inset = area.adjusted(edge_room, edge_room + _LABEL_HEADROOM,
                              -edge_room, -edge_room)
        if inset.width() <= 0 or inset.height() <= 0:
            return

        largest = max((node.count for node in network.nodes), default=1) or 1
        centres = {
            node.name: QPoint(
                int(inset.left() + node.x * inset.width()),
                # Screen y grows downwards; the layout's does not. Flipping here
                # rather than in core keeps the geometry one thing both front
                # ends agree on.
                int(inset.top() + (1.0 - node.y) * inset.height()))
            for node in network.nodes
        }

        # Edges first, so nodes sit on top of them.
        for edge in network.edges:
            start, end = centres[edge.source], centres[edge.target]
            width = _MIN_EDGE_WIDTH + (_MAX_EDGE_WIDTH - _MIN_EDGE_WIDTH) * min(
                1.0, max(0.0, edge.strength))
            colour = QColor(accent)
            colour.setAlpha(90 + int(120 * min(1.0, max(0.0, edge.strength))))
            painter.setPen(QPen(colour, width, Qt.PenStyle.SolidLine,
                                Qt.PenCapStyle.RoundCap))
            painter.drawLine(start, end)

            midpoint = QPoint((start.x() + end.x()) // 2,
                              (start.y() + end.y()) // 2)
            self._edge_hits.append((
                QRect(midpoint.x() - 8, midpoint.y() - 8, 16, 16),
                edge.source, edge.target, edge.strength, edge.count))

        isolated = set(network.isolated)
        for node in network.nodes:
            centre = centres[node.name]
            radius = _MIN_RADIUS + (_MAX_RADIUS - _MIN_RADIUS) * (
                (node.count / largest) ** 0.5)

            if node.name in isolated:
                # Unconnected codes are drawn, never dropped: "this code relates
                # to nothing" is a finding about the codebook. Hollow, so the
                # difference is visible rather than only in the caveats.
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(QPen(QColor(palette["text_muted"]), 1.6,
                                    Qt.PenStyle.DashLine))
            else:
                fill = QColor(accent)
                fill.setAlpha(210)
                painter.setBrush(fill)
                painter.setPen(QPen(QColor(palette["bg_elevated"]), 1.5))
            painter.drawEllipse(centre, int(radius), int(radius))

            self._node_hits.append((
                QRect(centre.x() - int(radius), centre.y() - int(radius),
                      int(radius) * 2, int(radius) * 2),
                node.name, node.count))

            painter.setPen(QPen(QColor(palette["text"])))
            label_width = metrics.horizontalAdvance(node.name)
            painter.drawText(
                QPoint(centre.x() - label_width // 2,
                       centre.y() - int(radius) - 5),
                node.name)

    def _paint_message(self, painter: QPainter, area: QRect, palette) -> None:
        painter.setPen(QPen(QColor(palette["text_muted"])))
        painter.drawText(area.adjusted(_MARGIN, _MARGIN, -_MARGIN, -_MARGIN),
                         int(Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap),
                         self._message or "No network to show.")
