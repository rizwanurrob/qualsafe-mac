"""
A caveat beside the number it qualifies: one sentence, with *Why?* for the rest.

Update 3, design rule 5. The text is kept whole (`text()` returns all of it, so a
test or a screen reader can still reach it); only the first sentence shows until
*Why?* is pressed. It always carries an icon and a word, so it never relies on
colour, and a warning is never green.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QToolButton, QVBoxLayout, QWidget

from core.ux import caveats
from qualsafe_qt.theme import STATUS_ICON, STATUS_WORD, icon_html
from qualsafe_qt.widgets.wrapping import WrappingLabel


class CaveatNote(QWidget):
    """Icon, word, one sentence, and a *Why?* button when there is more."""

    def __init__(self, kind: str = "note", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._kind = kind if kind in STATUS_ICON else "note"
        self._full = ""
        self.setObjectName("caveatNote")

        self.icon = QLabel()                   # the mark and the word: never colour alone
        self.icon.setTextFormat(Qt.TextFormat.RichText)
        self.icon.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.short = WrappingLabel()
        self.why = QToolButton()
        self.why.setText("Why?")
        self.why.setCheckable(True)
        self.why.setAutoRaise(True)
        self.why.setAccessibleName("Why this matters")
        self.why.toggled.connect(self._on_toggled)
        self.full = WrappingLabel()
        self.full.setVisible(False)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignTop)
        row.addWidget(self.short, 1)
        row.addWidget(self.why, 0, Qt.AlignmentFlag.AlignTop)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 4, 6, 4)
        outer.addLayout(row)
        outer.addWidget(self.full)
        self._mark()
        self.setText("")

    def _mark(self) -> None:
        self.icon.setText(f"{icon_html(self._kind)} <b>{STATUS_WORD[self._kind]}:</b>")

    # -- the part of QLabel that screens use ---------------------------------
    def setText(self, html: str) -> None:
        """Set the whole caveat. Only its first sentence is shown at first."""
        self._full = html or ""
        short, more = caveats.short_form(self._full)
        self.short.setText(short)
        self.full.setText(self._full)
        self.why.setVisible(more)
        if not more:
            self.why.setChecked(False)

    def text(self) -> str:
        return self._full

    def is_expanded(self) -> bool:
        return self.why.isChecked()

    def kind(self) -> str:
        return self._kind

    def set_kind(self, kind: str) -> None:
        self._kind = kind if kind in STATUS_ICON else "note"
        self._mark()
        self.setText(self._full)

    def _on_toggled(self, on: bool) -> None:
        self.full.setVisible(on)
        self.short.setVisible(not on)        # the full text starts with the same sentence
        self.why.setText("Hide" if on else "Why?")
