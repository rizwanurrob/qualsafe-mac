"""The first-visit tour: a dimmed screen, the real control lit up, and a small card.

The cards are in `core/ux/help/tours.py`. This file only draws them and finds the control
each one points at. Always skippable (Skip, or Escape); Next and Back also answer to the
arrow keys.
"""

from __future__ import annotations

from typing import Callable, Dict, List, Optional

from PySide6.QtCore import QEvent, QPoint, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QToolButton, QVBoxLayout, QWidget,
)

from core.ux.help import tours

PADDING = 6


class TourOverlay(QWidget):
    #: True if the person reached the last card, False if they skipped.
    finished = Signal(str, bool)

    def __init__(self, window: QWidget, activity_key: str,
                 finders: Dict[str, Callable[[], Optional[QWidget]]]) -> None:
        super().__init__(window)
        self._window = window
        self.activity_key = activity_key
        self._finders = finders
        self.cards = list(tours.tour(activity_key))
        self.index = 0
        self.setObjectName("tourOverlay")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName("Tour")

        self.card = QFrame(self)
        self.card.setObjectName("tipBox")
        self.card.setFrameShape(QFrame.Shape.StyledPanel)
        self.card.setFixedWidth(340)
        layout = QVBoxLayout(self.card)
        layout.setContentsMargins(14, 12, 14, 12)
        self.counter = QLabel()
        self.title = QLabel()
        self.title.setStyleSheet("font-weight: bold; font-size: 12pt;")
        self.title.setWordWrap(True)
        self.text = QLabel()
        self.text.setWordWrap(True)
        layout.addWidget(self.counter)
        layout.addWidget(self.title)
        layout.addWidget(self.text)
        row = QHBoxLayout()
        self.skip_button = QPushButton("Skip tour")
        self.skip_button.setFlat(True)
        self.back_button = QPushButton("Back")
        self.next_button = QPushButton("Next")
        self.next_button.setProperty("main", True)
        row.addWidget(self.skip_button)
        row.addStretch(1)
        row.addWidget(self.back_button)
        row.addWidget(self.next_button)
        layout.addLayout(row)
        self.skip_button.clicked.connect(lambda: self._end(False))
        self.back_button.clicked.connect(self.back)
        self.next_button.clicked.connect(self.next)

        window.installEventFilter(self)
        self._fit()
        self._show_card()

    # -- the cards -----------------------------------------------------------
    def current(self) -> tours.Card:
        return self.cards[self.index]

    def next(self) -> None:
        if self.index >= len(self.cards) - 1:
            self._end(True)
        else:
            self.index += 1
            self._show_card()

    def back(self) -> None:
        if self.index > 0:
            self.index -= 1
            self._show_card()

    def _end(self, completed: bool) -> None:
        self._window.removeEventFilter(self)
        self.hide()
        self.finished.emit(self.activity_key, completed)
        self.deleteLater()

    def target_widget(self) -> Optional[QWidget]:
        finder = self._finders.get(self.current().target)
        widget = finder() if finder else None
        return widget if widget is not None and widget.isVisible() else None

    def _show_card(self) -> None:
        card = self.current()
        self.counter.setText(f"{self.index + 1} of {len(self.cards)}")
        self.title.setText(card.title)
        self.text.setText(card.text)
        last = self.index == len(self.cards) - 1
        self.next_button.setText("Done" if last else "Next")
        self.back_button.setVisible(self.index > 0)
        self.card.adjustSize()
        self._place()
        self.update()
        self.setFocus()

    def target_rect(self) -> Optional[QRect]:
        widget = self.target_widget()
        if widget is None:
            return None
        top_left = widget.mapTo(self._window, QPoint(0, 0))
        return QRect(top_left, widget.size()).adjusted(-PADDING, -PADDING, PADDING, PADDING)

    def _place(self) -> None:
        rect = self.target_rect()
        w, h = self.card.width(), self.card.height()
        if rect is None:
            x, y = (self.width() - w) // 2, (self.height() - h) // 2
        else:
            x = min(max(12, rect.left()), max(12, self.width() - w - 12))
            below = rect.bottom() + 12
            y = below if below + h <= self.height() - 12 else max(12, rect.top() - h - 12)
        self.card.move(x, y)

    # -- drawing and keys ----------------------------------------------------
    def _fit(self) -> None:
        self.setGeometry(self._window.rect())
        self.raise_()
        self.show()

    def eventFilter(self, obj, event) -> bool:                  # keep covering the window
        if obj is self._window and event.type() in (QEvent.Type.Resize, QEvent.Type.Move):
            self.setGeometry(self._window.rect())
            self._place()
        return False

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRect(QRectF(self.rect()))
        rect = self.target_rect()
        if rect is not None:
            hole = QPainterPath()
            hole.addRoundedRect(QRectF(rect), 6, 6)
            path = path.subtracted(hole)
        painter.fillPath(path, QColor(0, 0, 0, 150))
        if rect is not None:
            painter.setPen(QPen(QColor("#ffffff"), 3))
            painter.drawRoundedRect(QRectF(rect), 6, 6)

    def mousePressEvent(self, event) -> None:                    # a click outside does nothing
        event.accept()

    def keyPressEvent(self, event) -> None:
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self._end(False)
        elif key in (Qt.Key.Key_Right, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.next()
        elif key == Qt.Key.Key_Left:
            self.back()
        else:
            super().keyPressEvent(event)


def find_main_button(root: QWidget) -> Optional[QWidget]:
    """The step's one filled button: the first visible button marked `main`."""
    for button in root.findChildren(QPushButton):
        if button.property("main") and button.isVisibleTo(root) and button.isVisible():
            return button
    return None


def find_more_options(root: QWidget) -> Optional[QWidget]:
    """The first visible "More options" toggle."""
    for button in root.findChildren(QToolButton):
        if button.isCheckable() and button.text().startswith("More options") and button.isVisible():
            return button
    return None
