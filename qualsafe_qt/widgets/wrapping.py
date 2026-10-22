"""
A word-wrapped label that is never cut off.

A plain wrapped `QLabel` inside a splitter can be given a height worked out for a
different width, which clips its last lines (the privacy-scan result was cut
mid-sentence). This one sets its own minimum height from the width it actually has.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QSizePolicy, QWidget


class WrappingLabel(QLabel):
    """Rich text, word-wrapped, tall enough for every line."""

    def __init__(self, text: str = "", parent: Optional[QWidget] = None) -> None:
        super().__init__(text, parent)
        self.setWordWrap(True)
        self.setTextFormat(Qt.TextFormat.RichText)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        self.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

    def resizeEvent(self, event) -> None:  # noqa: D102 - Qt override
        super().resizeEvent(event)
        self._fit()

    def setText(self, text: str) -> None:  # noqa: D102 - Qt override
        super().setText(text)
        self._fit()

    def _fit(self) -> None:
        width = self.width()
        if width <= 0:
            return
        self.setMinimumHeight(0)            # forget the height of the previous text
        needed = self.heightForWidth(width)
        if needed > 0:
            self.setMinimumHeight(needed)
        self.updateGeometry()
