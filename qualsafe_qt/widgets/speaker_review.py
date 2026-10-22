"""Who is speaking? The checkpoint where the person confirms the roles (item 4.5).

QualSafe proposes who the interviewer is from the shape of the transcript; a wrong guess would
quietly change what counts as the participant's words, so nothing is kept until the person
presses *Use these roles*. *Skip* keeps the transcript exactly as it is, as one block of text.
"""

from __future__ import annotations

from typing import Dict, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QDialog, QHBoxLayout, QLabel, QPushButton, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget, QHeaderView,
)

from core import speakers
from qualsafe_qt.widgets.wrapping import WrappingLabel


class SpeakerReviewDialog(QDialog):
    def __init__(self, title: str, review: speakers.SpeakerReview,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.review = review
        self.setWindowTitle("Who is speaking?")
        self.setMinimumWidth(640)
        layout = QVBoxLayout(self)

        heading = QLabel(f"<b>{_escape(title)}</b>")
        heading.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(heading)
        speakers_found = len(review.rows)
        self.intro = WrappingLabel(
            f"QualSafe found {review.n_turns} turns by {speakers_found} speakers. "
            "Check who is who: it decides which words count as the participant's. "
            + (review.rationale or ""))
        layout.addWidget(self.intro)

        self.table = QTableWidget(len(review.rows), 5)
        self.table.setHorizontalHeaderLabels(
            ["Speaker", "Turns", "Share of the words", "Questions asked", "Who is this?"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.combos: Dict[str, QComboBox] = {}
        for row, item in enumerate(review.rows):
            cells = [item.label, str(item.turns), f"{item.share:.0%}", str(item.questions)]
            for column, text in enumerate(cells):
                self.table.setItem(row, column, QTableWidgetItem(text))
            combo = QComboBox()
            for role in speakers.ROLES:
                combo.addItem(speakers.ROLE_NAMES[role], role)
            combo.setCurrentIndex(speakers.ROLES.index(item.role) if item.role in speakers.ROLES else 2)
            combo.setAccessibleName(f"Who is {item.label}?")
            self.table.setCellWidget(row, 4, combo)
            self.combos[item.label] = combo
        self.table.setMinimumHeight(40 + 32 * min(len(review.rows), 6))
        layout.addWidget(self.table)

        layout.addWidget(QLabel("<b>How the transcript starts</b>"))
        self.preview = WrappingLabel("<br>".join(
            f"<b>{_escape(label)}:</b> {_escape(text)}" for label, text in review.preview))
        layout.addWidget(self.preview)

        self.warning = WrappingLabel("")
        layout.addWidget(self.warning)
        row = QHBoxLayout()
        self.skip_button = QPushButton("Skip")
        self.skip_button.setToolTip("Keep the transcript as it is, with no speakers marked.")
        self.use_button = QPushButton("Use these roles")
        self.use_button.setProperty("main", True)
        row.addWidget(self.skip_button)
        row.addStretch(1)
        row.addWidget(self.use_button)
        layout.addLayout(row)
        self.skip_button.clicked.connect(self.reject)
        self.use_button.clicked.connect(self._accept)
        for combo in self.combos.values():
            combo.currentIndexChanged.connect(self._check)
        self._check()

    def roles(self) -> Dict[str, str]:
        return {label: combo.currentData() for label, combo in self.combos.items()}

    def _check(self) -> None:
        """Warn, without blocking, when there is no interviewer or no participant."""
        chosen = set(self.roles().values())
        missing = [speakers.ROLE_NAMES[r] for r in ("interviewer", "interviewee") if r not in chosen]
        self.warning.setText(
            f"<i>No one is marked as {' or '.join(missing).lower()}. You can still go on.</i>"
            if missing else "")

    def _accept(self) -> None:
        self.accept()


def _escape(text: str) -> str:
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
