"""
What a new user sees before there is a project to see.

`RELEASE_READINESS.md` §2.3 recorded this as a gap and understated it. On a
fresh install the app opened on Documents with no project loaded, which rendered
as five empty panels: an empty corpus list, an empty reader, an empty code list,
an empty codebook, an empty margin. No heading said what to do, and nothing on
screen was clickable to any effect.

That is the first thing every new user sees, and for a research tool asking
people to trust it with interview data, a blank grid is an unpromising start.

Three actions, no more
----------------------
Open, create, or try the sample. Those are the only three things a person can
usefully do with no project, so those are the only three offered. A welcome
screen that lists ten links is a menu, and a menu is what the person is already
looking at.

The sample is deliberately first among equals. Reading a guide teaches the
vocabulary; opening a project that already has documents, codes and codings in
it teaches the shape, and the guided walkthroughs in Help are written against
exactly that project.

Why a panel and not a dialog
----------------------------
A modal has to be dismissed before the program can be looked at, which teaches a
new user that the first thing this software does is get in the way. This sits
inside the Documents screen and is replaced by the corpus the moment a project
opens, so it occupies the space it is explaining rather than covering it.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from qualsafe_qt.theme import muted_span
from qualsafe_qt.version import APP_NAME, version_line


class WelcomePanel(QWidget):
    """The empty state for Documents: three ways to have a project."""

    open_requested = Signal()
    create_requested = Signal()
    sample_requested = Signal()
    guide_requested = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addStretch(1)

        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self._card(), 0)
        row.addStretch(1)
        outer.addLayout(row)

        outer.addStretch(2)   # sits slightly above centre, where the eye goes

    def _card(self) -> QWidget:
        card = QFrame()
        card.setFrameShape(QFrame.Shape.StyledPanel)
        card.setMaximumWidth(560)
        card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(10)

        title = QLabel(APP_NAME)
        font = title.font()
        font.setPointSize(font.pointSize() + 6)
        font.setBold(True)
        title.setFont(font)
        layout.addWidget(title)

        blurb = QLabel(
            "Qualitative analysis that stays on this computer. Nothing you open "
            "here is uploaded, and no part of it needs an internet connection.")
        blurb.setWordWrap(True)
        layout.addWidget(blurb)

        layout.addSpacing(8)
        layout.addWidget(QLabel("<b>To begin</b>"))

        # Ordered by what a first-time user should do, not by what is easiest to
        # implement. The sample is the fastest route to understanding the shape
        # of the program, and the Help walkthroughs are written against it.
        self.sample_button = self._action(
            layout, "Try the sample project",
            "A small survey with documents, a codebook and some coding already "
            "in it. The walkthroughs in Help follow this project.",
            self.sample_requested)
        self.open_button = self._action(
            layout, "Open a project…",
            "A .qnw file you or a colleague made earlier.",
            self.open_requested)
        self.create_button = self._action(
            layout, "Create a new project…",
            "An empty project to import your own documents into.",
            self.create_requested)

        layout.addSpacing(6)
        guide = QPushButton("Read the guide")
        guide.setFlat(True)
        guide.clicked.connect(self.guide_requested.emit)
        layout.addWidget(guide, 0, Qt.AlignmentFlag.AlignLeft)

        footer = QLabel(muted_span(version_line()))
        footer.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(footer)

        return card

    def _action(self, layout: QVBoxLayout, label: str, explanation: str,
                signal) -> QPushButton:
        button = QPushButton(label)
        button.setMinimumHeight(34)
        button.clicked.connect(signal.emit)
        layout.addWidget(button)

        caption = QLabel(muted_span(explanation))
        caption.setTextFormat(Qt.TextFormat.RichText)
        caption.setWordWrap(True)
        caption.setContentsMargins(2, 0, 2, 6)
        layout.addWidget(caption)
        return button
