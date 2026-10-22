"""
Home: the three things a person comes to QualSafe to do.

Surveys, Charts and Interviews as three large cards in their activity colours,
one sentence each and a Start button. The wording comes from
`core.ux.activities`, so the desktop and web apps say the same thing. Below the
cards: the sample, the short guide, opening a project, and recent projects
tagged by activity. (The *Continue* line on each card arrives with saved
progress.)
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QStyle, QVBoxLayout, QWidget,
)

from core.ux import activities, recent
from core.ux.progress import Summary
from qualsafe_qt.theme import activity_stylesheet, muted_span, warning_span


class HomeView(QWidget):
    """Full-window start page."""

    activity_requested = Signal(str)          # activity key
    sample_requested = Signal()
    guide_requested = Signal()
    open_requested = Signal()
    recent_requested = Signal(str, str)       # path, activity key
    continue_requested = Signal(str)          # activity key: pick up where you left off
    find_requested = Signal(str)              # activity key: a saved file is gone
    start_over_requested = Signal(str)        # activity key: forget where you left off

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.start_buttons: Dict[str, QPushButton] = {}
        self.cards: Dict[str, QFrame] = {}
        self.recent_buttons: List[QPushButton] = []
        #: Per activity: the Continue block's parts, hidden until there is a place to return to.
        self.continue_boxes: Dict[str, QWidget] = {}
        self.continue_titles: Dict[str, QLabel] = {}
        self.continue_details: Dict[str, QLabel] = {}
        self.continue_warnings: Dict[str, QLabel] = {}
        self.continue_buttons: Dict[str, QPushButton] = {}
        self.start_over_buttons: Dict[str, QPushButton] = {}
        self._warning_rows: Dict[str, QWidget] = {}
        self._needs_file: set = set()           # activities whose saved file is gone

        outer = QVBoxLayout(self)
        outer.setContentsMargins(40, 32, 40, 32)
        outer.setSpacing(8)

        title = QLabel("What would you like to do?")
        font = title.font()
        font.setPointSize(font.pointSize() + 10)
        font.setBold(True)
        title.setFont(font)
        outer.addWidget(title)
        outer.addWidget(QLabel("Everything stays on this computer."))
        outer.addSpacing(18)

        row = QHBoxLayout()
        row.setSpacing(20)
        for activity in activities.ACTIVITIES:
            card = self._card(activity)
            self.cards[activity.key] = card
            row.addWidget(card, 1)
        outer.addLayout(row)
        outer.addSpacing(18)

        # New here?
        new_row = QHBoxLayout()
        new_row.addWidget(QLabel("<b>New here?</b>"))
        self.sample_button = self._link("Try the sample survey", self.sample_requested)
        self.guide_button = self._link("Read the 5-minute guide", self.guide_requested)
        self.open_button = self._link("Open a project…", self.open_requested)
        for button in (self.sample_button, self.guide_button, self.open_button):
            new_row.addWidget(button)
        new_row.addStretch(1)
        outer.addLayout(new_row)

        # Recent projects
        self._recent_box = QVBoxLayout()
        self._recent_box.setSpacing(2)
        self.recent_heading = QLabel("<b>Recent projects</b>")
        self._recent_box.addWidget(self.recent_heading)
        self._recent_rows = QVBoxLayout()
        self._recent_box.addLayout(self._recent_rows)
        outer.addSpacing(6)
        outer.addLayout(self._recent_box)
        outer.addStretch(1)
        self.set_recent([])

    # -- recent projects -----------------------------------------------------
    def set_recent(self, entries: List[recent.Entry]) -> None:
        """Show up to five recent projects, each tagged with its activity."""
        for button in self.recent_buttons:
            self._recent_rows.removeWidget(button)
            button.hide()
            button.setParent(None)
            button.deleteLater()
        self.recent_buttons = []
        shown = recent.existing(entries)
        self.recent_heading.setVisible(bool(shown))
        for entry in shown:
            activity = activities.get(entry["activity"])
            button = QPushButton(f"{Path(entry['path']).name}   ·   {activity.title}")
            button.setFlat(True)
            button.setToolTip(entry["path"])
            button.setStyleSheet("text-align: left;")
            button.clicked.connect(
                lambda _c=False, e=dict(entry): self.recent_requested.emit(e["path"], e["activity"]))
            self._recent_rows.addWidget(button)
            self.recent_buttons.append(button)

    # -- continue ------------------------------------------------------------
    def _continue_block(self, key: str) -> QWidget:
        box = QWidget()
        column = QVBoxLayout(box)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(4)

        title = QLabel()
        title.setWordWrap(True)
        title.setTextFormat(Qt.TextFormat.PlainText)
        font = title.font()
        font.setBold(True)
        title.setFont(font)
        column.addWidget(title)

        detail = QLabel()
        detail.setTextFormat(Qt.TextFormat.RichText)
        column.addWidget(detail)

        warning_row = QWidget()
        row = QHBoxLayout(warning_row)
        row.setContentsMargins(0, 0, 0, 0)
        icon = QLabel()      # a real icon: font glyphs vary by machine
        icon.setPixmap(self.style().standardIcon(
            QStyle.StandardPixmap.SP_MessageBoxWarning).pixmap(16, 16))
        icon.setFixedWidth(20)
        row.addWidget(icon)
        warning = QLabel()
        warning.setWordWrap(True)
        warning.setTextFormat(Qt.TextFormat.RichText)
        row.addWidget(warning, 1)
        column.addWidget(warning_row)

        button = QPushButton("Continue")
        button.clicked.connect(lambda _c=False: self._continue_clicked(key))
        column.addWidget(button)

        start_over = QPushButton("Start over")
        start_over.setFlat(True)
        start_over.setToolTip(
            "Forget where you left off in this activity. Your files and projects are "
            "not changed.")
        start_over.clicked.connect(lambda _c=False: self.start_over_requested.emit(key))
        column.addWidget(start_over, 0, Qt.AlignmentFlag.AlignLeft)
        self.start_over_buttons[key] = start_over

        box.hide()
        self.continue_boxes[key] = box
        self.continue_titles[key] = title
        self.continue_details[key] = detail
        self.continue_warnings[key] = warning
        self.continue_buttons[key] = button
        self._warning_rows[key] = warning_row
        return box

    def set_progress(self, summaries: Dict[str, Optional[Summary]]) -> None:
        """Show, on each card, where you left off (or nothing, when there is nothing).

        A saved file that has gone missing says so, with an icon and words, and
        the button becomes *Find it…* instead of failing on the step.
        """
        for key, box in self.continue_boxes.items():
            info = summaries.get(key)
            if info is None:
                box.hide()
                self._needs_file.discard(key)
                continue
            self.continue_titles[key].setText(
                f"Continue: {info.name}" if info.name else "Continue where you left off")
            self.continue_details[key].setText(muted_span(info.detail))
            gone = bool(info.missing)
            self._warning_rows[key].setVisible(gone)
            if gone:
                names = ", ".join(Path(p).name for p in info.missing)
                self.continue_warnings[key].setText(
                    warning_span("File not found:", bold=True) + f" {names}")
                self.continue_buttons[key].setText("Find it…")
                self._needs_file.add(key)
            else:
                self.continue_buttons[key].setText("Continue")
                self._needs_file.discard(key)
            box.show()

    def _continue_clicked(self, key: str) -> None:
        (self.find_requested if key in self._needs_file else self.continue_requested).emit(key)

    # -- theme ---------------------------------------------------------------
    def set_theme_mode(self, mode: str) -> None:
        self.setStyleSheet(activity_stylesheet(mode))

    # -- parts ---------------------------------------------------------------
    def _link(self, label: str, signal) -> QPushButton:
        button = QPushButton(label)
        button.setFlat(True)
        button.clicked.connect(signal.emit)
        return button

    def _card(self, activity: activities.Activity) -> QFrame:
        card = QFrame()
        card.setObjectName("activityCard")
        card.setProperty("activity", activity.key)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(10)

        heading = QLabel(activity.title)
        font = heading.font()
        font.setPointSize(font.pointSize() + 5)
        font.setBold(True)
        heading.setFont(font)
        heading.setObjectName("activityTitle")
        layout.addWidget(heading)

        blurb = QLabel(activity.tagline)
        blurb.setWordWrap(True)
        layout.addWidget(blurb)
        layout.addStretch(1)
        layout.addWidget(self._continue_block(activity.key))

        start = QPushButton("Start")
        start.setMinimumHeight(36)
        start.setProperty("activity", activity.key)
        start.clicked.connect(lambda _c=False, k=activity.key: self.activity_requested.emit(k))
        layout.addWidget(start)
        self.start_buttons[activity.key] = start
        card.setMinimumHeight(230)
        return card
