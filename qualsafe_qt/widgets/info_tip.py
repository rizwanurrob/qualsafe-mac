"""The small (i) beside a control that is not obvious (Update 3, item 4.2).

Hover shows the tip; a click (or Enter) opens it in a small box with a *More* link to the
help article for the step. The text is in `core/ux/help/tips.py`, shared with the web app.

It is a button, but it is help, not a control of the step, so `visible_controls` and
`count_controls` skip it (the dynamic property `infoTip`).
"""

from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import Qt, QPoint
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QToolButton, QVBoxLayout, QWidget

from core.ux.help import tips as shared_tips

#: Set once by the main window: opens the help article with this id (`surveys-code`).
_open_article: Optional[Callable[[str], None]] = None


def set_article_opener(opener: Optional[Callable[[str], None]]) -> None:
    global _open_article
    _open_article = opener


class _TipBox(QFrame):
    """The popup: the tip, and More."""

    def __init__(self, text: str, article: str, parent: QWidget) -> None:
        super().__init__(parent, Qt.WindowType.Popup)
        self.setObjectName("tipBox")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setMaximumWidth(340)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        self.label = QLabel(text)
        self.label.setWordWrap(True)
        layout.addWidget(self.label)
        row = QHBoxLayout()
        row.addStretch(1)
        self.more = QPushButton("More")
        self.more.setFlat(True)
        self.more.setCursor(Qt.CursorShape.PointingHandCursor)
        self.more.clicked.connect(lambda: (self.close(), _open(article)))
        row.addWidget(self.more)
        layout.addLayout(row)


def _open(article: str) -> None:
    if _open_article is not None:
        _open_article(article)


class InfoTip(QToolButton):
    def __init__(self, tip_id: str, about: str = "", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        tip = shared_tips.get(tip_id)
        if tip is None:
            raise KeyError(f"no tip called {tip_id!r}")
        self.tip_id = tip_id
        self.tip = tip
        self.setObjectName("infoTip")
        self.setProperty("infoTip", True)
        self.setText("i")
        self.setFixedSize(20, 20)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setToolTip(tip.text)
        self.setAccessibleName(f"About {about}" if about else "About this option")
        self.setAccessibleDescription(tip.text)
        self.clicked.connect(self.show_tip)
        self.box: Optional[_TipBox] = None

    def show_tip(self) -> None:
        self.box = _TipBox(self.tip.text, self.tip.article, self.window())
        self.box.move(self.mapToGlobal(QPoint(0, self.height() + 4)))
        self.box.show()
