"""Review answers by theme (Surveys, step 4, Explore).

Always there once an answer has a theme, whichever way the coding was done. Pick a theme on the left and
read the answers that carry it, with the score when there is one. One button goes to the written-codebook
step that checks what the engine was unsure about. The scores are model scores, not probabilities.
"""

from __future__ import annotations

from typing import Optional

import pandas as pd
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QFileDialog, QHBoxLayout, QListWidget, QListWidgetItem, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from core import review_browse as rb
from qualsafe_qt.services.project_service import ProjectService
from qualsafe_qt.widgets.wrapping import WrappingLabel

_HEADERS = ["Answer", "Score", "Applied by", "You decided"]
_ALL = "All themes"


class ReviewView(QWidget):
    """Browse the coded answers by theme."""

    #: Take me to the step that checks what the engine was unsure about.
    review_unsure_requested = Signal()

    def __init__(self, service: ProjectService, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._service = service
        self._table = pd.DataFrame(columns=rb.COLUMNS)

        outer = QVBoxLayout(self)
        self.headline = WrappingLabel("")
        outer.addWidget(self.headline)

        row = QHBoxLayout()
        self.themes = QListWidget()
        self.themes.setMaximumWidth(260)
        self.themes.currentRowChanged.connect(self._show_theme)
        row.addWidget(self.themes)
        self.answers = QTableWidget(0, len(_HEADERS))
        self.answers.setHorizontalHeaderLabels(_HEADERS)
        self.answers.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.answers.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.answers.verticalHeader().setVisible(False)
        self.answers.setWordWrap(True)
        self.answers.setColumnWidth(0, 520)
        row.addWidget(self.answers, 1)
        outer.addLayout(row, 1)

        buttons = QHBoxLayout()
        self.review_button = QPushButton("Review what it was unsure about")
        self.review_button.setToolTip(
            "Go to the step where you accept or reject the codes the engine was unsure about. "
            "It works with a written codebook.")
        self.review_button.clicked.connect(self.review_unsure_requested.emit)
        self.save_button = QPushButton("Save this list…")
        self.save_button.clicked.connect(self.save_list)
        self.save_button.setEnabled(False)
        buttons.addWidget(self.review_button)
        buttons.addWidget(self.save_button)
        buttons.addStretch(1)
        outer.addLayout(buttons)

        service.project_changed.connect(lambda _p: self.refresh())
        service.store_changed.connect(self.refresh)
        self.refresh()

    # -- state ---------------------------------------------------------------
    def refresh(self) -> None:
        self.themes.blockSignals(True)
        self.themes.clear()
        if not self._service.is_open:
            self._table = pd.DataFrame(columns=rb.COLUMNS)
            self.headline.setText("Open a project and code some answers. They show here, by theme.")
        else:
            self._table = rb.browse_table(self._service.project)
            if self._table.empty:
                self.headline.setText(
                    "No answer has a theme yet. Code the answers at step 3, then come back to read them by theme.")
            else:
                self.headline.setText(
                    f"{self._table['answer_id'].nunique()} answers have a theme. Pick a theme to read its answers. "
                    "A score is a model score, not a probability.")
        total = self._table["answer_id"].nunique() if not self._table.empty else 0
        self.themes.addItem(QListWidgetItem(f"{_ALL} ({total})"))
        for _, r in rb.theme_counts(self._table).iterrows():
            item = QListWidgetItem(f"{r['theme']} ({int(r['answers'])})")
            item.setData(Qt.ItemDataRole.UserRole, r["theme"])
            self.themes.addItem(item)
        self.themes.blockSignals(False)
        self.themes.setCurrentRow(0)
        self._show_theme(0)
        self.save_button.setEnabled(not self._table.empty)

    def current_theme(self) -> Optional[str]:
        item = self.themes.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item is not None else None

    def _show_theme(self, _row: int) -> None:
        theme = self.current_theme()
        shown = rb.for_theme(self._table, theme)
        self.answers.setRowCount(len(shown))
        for i, (_, r) in enumerate(shown.iterrows()):
            score = "" if pd.isna(r["score"]) else f"{float(r['score']):.2f}"
            answer = r["answer"] if theme else f"{r['theme']}: {r['answer']}"
            for c, value in enumerate([answer, score, r["applied_by"], r["you_decided"]]):
                item = QTableWidgetItem(str(value))
                if c == 0:
                    item.setToolTip(str(r["answer"]))
                self.answers.setItem(i, c, item)
        self.answers.resizeRowsToContents()

    # -- saving --------------------------------------------------------------
    def _ask_save_path(self, default: str) -> str:
        path, _ = QFileDialog.getSaveFileName(self, "Save", default, "Spreadsheet (*.csv)")
        return path

    def save_list(self) -> Optional[str]:
        """The list on screen as a spreadsheet. It holds the answers, so you choose to write it."""
        shown = rb.for_theme(self._table, self.current_theme())
        if shown.empty:
            return None
        path = self._ask_save_path("answers_by_theme.csv")
        if not path:
            return None
        from analyze_survey import sanitize_frame_for_csv
        sanitize_frame_for_csv(shown).to_csv(path, index=False)
        return path
