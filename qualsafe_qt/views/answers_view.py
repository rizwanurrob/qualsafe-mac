"""
Code survey answers by hand (Surveys, step 3, third choice).

Read an answer, tick the codes that apply to it as a whole, and go on to the next:
one answer at a time, with the keyboard as quick as the mouse. Saving an answer with
no ticks is a real choice ("no code applies") and counts as one when agreement is
worked out. The logic is `core/hand_coding.py`; this is only the screen.

The answers live in the project file. This screen shows them but never writes them
anywhere else, and what it saves for "where you were" is an answer's id, not its text.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional

import pandas as pd
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QFont, QKeySequence
from PySide6.QtWidgets import (
    QCheckBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from core import hand_coding as hc
from qualsafe_qt.services.project_service import ProjectService
from qualsafe_qt.services.tasks import run_task
from qualsafe_qt.theme import SYMBOL_FONTS, success_span, warning_span
from qualsafe_qt.widgets.more_options import MoreOptions, count_controls
from qualsafe_qt.widgets.wrapping import WrappingLabel

PAGE = 50
_QUICK_KEYS = 9
_PREVIEW = 64


def _preview(text: str) -> str:
    one_line = " ".join(text.split())
    return one_line if len(one_line) <= _PREVIEW else one_line[:_PREVIEW - 1].rstrip() + "…"


class HandCodingView(QWidget):
    """A list of answers, the answer in front of you, and the codes to tick."""

    status = Signal(str)
    project_created = Signal(str)
    #: Back was pressed: return to the choice of how to code.
    back_requested = Signal()

    def __init__(self, service: ProjectService, output_root: Optional[Callable[[], Path]] = None,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._service = service
        self._output_root = output_root
        self._frame: Optional[pd.DataFrame] = None
        self._text_column = ""
        self._id_column = ""
        self._source_id = ""
        self._offset = 0
        self._total = 0
        self._preparing = False
        self._answers: List[hc.Answer] = []
        self._pending_answer = ""          # an answer to return to once the answers are shown
        self._only_ids: Optional[set] = None    # code only these answers (a calibration sample)
        self._mark_font = QFont()          # the ✓ is not in the ordinary font
        self._mark_font.setFamilies(SYMBOL_FONTS)

        self.message = WrappingLabel("")
        self.progress_label = QLabel("")

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search the answers")
        self.search_edit.textChanged.connect(self._filters_changed)
        self.answers_tree = QTreeWidget()
        self.answers_tree.setColumnCount(2)
        self.answers_tree.setHeaderLabels(["Answer", "You"])
        self.answers_tree.setRootIsDecorated(False)
        self.answers_tree.setColumnWidth(0, 360)
        self.answers_tree.itemSelectionChanged.connect(self._on_answer_selected)
        self.earlier_button = QPushButton("Earlier answers")
        self.later_button = QPushButton("Later answers")
        self.earlier_button.clicked.connect(lambda: self._move_page(-1))
        self.later_button.clicked.connect(lambda: self._move_page(+1))
        self.page_label = QLabel("")

        self.answer_label = WrappingLabel("")
        self.codes_list = QListWidget()
        self.codes_list.setToolTip("Tick every code that applies to this answer. Keys 1 to 9 tick the first nine.")
        self.new_code_edit = QLineEdit()
        self.new_code_edit.setPlaceholderText("…or type a new code and press Enter")
        self.new_code_edit.returnPressed.connect(self._add_code)
        self.save_button = QPushButton("Save and go to the next answer")
        self.save_button.setProperty("main", True)
        self.save_button.clicked.connect(self._save_and_next)
        self.save_button.setToolTip("Shortcut: Ctrl+Enter. Saving with nothing ticked means no code applies.")
        self.back_button = QPushButton("Back to the choices")
        self.back_button.clicked.connect(self.back_requested)

        self.unjudged_check = QCheckBox("Show only the answers I have not coded yet")
        self.unjudged_check.toggled.connect(self._filters_changed)
        self.skip_button = QPushButton("Next answer without saving")
        self.skip_button.clicked.connect(self._skip)
        more = MoreOptions("More options")
        more.body_layout.addWidget(self.unjudged_check)
        more.body_layout.addWidget(self.skip_button)
        more._count = count_controls(more.body)
        more._refresh_title()
        self.more = more

        left = QWidget()
        left_col = QVBoxLayout(left)
        left_col.setContentsMargins(0, 0, 0, 0)
        left_col.addWidget(self.search_edit)
        left_col.addWidget(self.answers_tree, 1)
        paging = QHBoxLayout()
        paging.addWidget(self.earlier_button)
        paging.addWidget(self.page_label, 1, Qt.AlignmentFlag.AlignCenter)
        paging.addWidget(self.later_button)
        left_col.addLayout(paging)

        right = QWidget()
        right_col = QVBoxLayout(right)
        right_col.setContentsMargins(0, 0, 0, 0)
        right_col.addWidget(self.answer_label)
        right_col.addWidget(self.codes_list, 1)
        right_col.addWidget(self.new_code_edit)
        right_col.addWidget(self.save_button)
        right_col.addWidget(more)

        body = QHBoxLayout()
        body.addWidget(left, 2)
        body.addWidget(right, 3)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.progress_label)
        layout.addWidget(self.message)
        layout.addLayout(body, 1)
        layout.addWidget(self.back_button, 0, Qt.AlignmentFlag.AlignLeft)

        self._install_shortcuts()
        service.project_changed.connect(lambda _p: self._on_project_changed())
        self._show_empty("Load your answers and confirm the privacy check in step 1 first.")

    # ── keyboard ──────────────────────────────────────────────────────────────

    def _install_shortcuts(self) -> None:
        for number in range(1, _QUICK_KEYS + 1):
            action = QAction(f"Tick code {number}", self)
            action.setShortcut(QKeySequence(str(number)))
            action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            action.triggered.connect(lambda _c=False, n=number: self._toggle_code(n))
            self.addAction(action)
        save = QAction("Save and go to the next answer", self)
        save.setShortcut(QKeySequence("Ctrl+Return"))
        save.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        save.triggered.connect(self._save_and_next)
        self.addAction(save)

    def _toggle_code(self, number: int) -> None:
        item = self.codes_list.item(number - 1)
        if item is not None and self._source_id:
            item.setCheckState(Qt.CheckState.Unchecked if item.checkState() == Qt.CheckState.Checked
                               else Qt.CheckState.Checked)

    # ── getting the answers ready ─────────────────────────────────────────────

    def set_source(self, frame: Optional[pd.DataFrame], text_column: str, id_column: str = "") -> None:
        """The table from the Load step. Without it (or before the privacy check is confirmed) there
        is nothing to code."""
        self._frame = frame
        self._text_column = text_column or ""
        self._id_column = id_column or ""

    def begin(self) -> None:
        """Called when this way of coding is chosen: put the answers in the project, then show them."""
        if self._frame is None or not self._text_column:
            self._show_empty("Load your answers and confirm the privacy check in step 1 first.")
            return
        if not self._service.is_open:
            root = self._output_root() if self._output_root else Path.home() / "QualSafe"
            path = Path(root) / ("hand_coding_" + datetime.now().strftime("%Y%m%d_%H%M%S")) / "project.qnw"
            path.parent.mkdir(parents=True, exist_ok=True)
            self._service.create(path)
            self.project_created.emit(str(path))
        wanted = int(self._frame[self._text_column].astype(str).str.strip().ne("").sum()) \
            if self._text_column in self._frame.columns else 0
        have = self._service.project.count_sources(hc.SURVEY)
        if have >= wanted > 0 and have:
            self._reload()
            return
        if self._preparing:
            return
        self._preparing = True
        self.message.setText("<i>Getting the answers ready…</i>")
        self.status.emit("Getting the answers ready…")
        run_task(hc.prepare, str(self._service.path), self._frame, self._text_column, self._id_column,
                 reads_store=True, on_finished=lambda _n: None,
                 on_failed=lambda msg, _tb: self._show_empty(f"The answers could not be prepared: {msg}"),
                 on_done=self._prepared)

    def _prepared(self) -> None:
        self._preparing = False
        self._service.reopen()
        self._reload()

    def _on_project_changed(self) -> None:
        self._source_id = ""
        self._offset = 0
        if self._service.is_open and self._service.project.count_sources(hc.SURVEY):
            self._reload()
        else:
            self._show_empty("Load your answers and confirm the privacy check in step 1 first.")

    def _show_empty(self, text: str) -> None:
        self._total = 0                      # nothing is showing, so it is not "ready"
        self._source_id = ""
        self.answers_tree.clear()
        self.codes_list.clear()
        self.answer_label.setText("")
        self.progress_label.setText("")
        self.page_label.setText("")
        self.message.setText(warning_span(text, bold=False))
        self._enable(False)

    def _enable(self, on: bool) -> None:
        for widget in (self.search_edit, self.codes_list, self.new_code_edit, self.save_button,
                       self.skip_button, self.unjudged_check):
            widget.setEnabled(on)
        self.earlier_button.setVisible(False)
        self.later_button.setVisible(False)

    # ── the list ──────────────────────────────────────────────────────────────

    def _filters_changed(self, *_args) -> None:
        self._offset = 0
        self._reload()

    def _reload(self, keep: str = "") -> None:
        """Fill the list for the current page, search and filter, and the codes."""
        if not self._service.is_open:
            return
        keep = keep or self._pending_answer or self._source_id
        self._pending_answer = ""
        if keep and not self._offset and hc.get(self._service.project, keep) is None:
            keep = ""
        project = self._service.project
        self._answers, self._total = hc.page(
            project, offset=self._offset, limit=PAGE, search=self.search_edit.text(),
            only_unjudged=self.unjudged_check.isChecked(), only_ids=self._only_ids)
        self._enable(True)
        self.message.setText("")
        self.answers_tree.blockSignals(True)
        self.answers_tree.clear()
        select = None
        for answer in self._answers:
            item = QTreeWidgetItem([_preview(answer.text), "✓ coded" if answer.judged else ""])
            item.setFont(1, self._mark_font)
            item.setData(0, Qt.ItemDataRole.UserRole, answer.source_id)
            self.answers_tree.addTopLevelItem(item)
            if answer.source_id == keep:
                select = item
        self.answers_tree.blockSignals(False)
        self._fill_codes()
        done, total = hc.progress(project, only_ids=self._only_ids)
        what = "answers in your sample" if self._only_ids is not None else "answers"
        self.progress_label.setText(f"<b>You have coded {done} of {total} {what}.</b>")
        last = min(self._offset + PAGE, self._total)
        self.page_label.setText(f"{self._offset + 1 if self._total else 0}–{last} of {self._total}")
        self.earlier_button.setVisible(self._offset > 0)
        self.later_button.setVisible(self._offset + PAGE < self._total)
        if select is None and self.answers_tree.topLevelItemCount():
            select = self.answers_tree.topLevelItem(0)
        if select is not None:
            self.answers_tree.setCurrentItem(select)
            self._on_answer_selected()
        else:
            self._source_id = ""
            self.answer_label.setText("<i>No answers match.</i>")

    def _move_page(self, direction: int) -> None:
        self._offset = max(0, self._offset + direction * PAGE)
        self._reload()

    def _fill_codes(self) -> None:
        names = sorted(self._service.code_names()) if self._service.is_open else []
        ticked = self._ticked()
        self.codes_list.clear()
        for number, name in enumerate(names, start=1):
            item = QListWidgetItem(f"{number}. {name}" if number <= _QUICK_KEYS else name)
            item.setData(Qt.ItemDataRole.UserRole, name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if name in ticked else Qt.CheckState.Unchecked)
            self.codes_list.addItem(item)

    def _ticked(self) -> List[str]:
        return [self.codes_list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.codes_list.count())
                if self.codes_list.item(i).checkState() == Qt.CheckState.Checked]

    # ── one answer ────────────────────────────────────────────────────────────

    def current_answer_id(self) -> str:
        return self._source_id

    def restrict_to(self, source_ids: Optional[set]) -> None:
        """Show only these answers (a random sample to check the engine against), or all with None."""
        self._only_ids = set(source_ids) if source_ids is not None else None
        self._source_id = ""
        self._offset = 0

    def set_embedded(self, embedded: bool) -> None:
        """Part of another screen: no way back to the choices from here."""
        self.back_button.setVisible(not embedded)

    def show_project_answers(self) -> None:
        """Show the answers already in the project (no spreadsheet needed)."""
        if self._service.is_open and self._service.project.count_sources(hc.SURVEY):
            self._reload()
        else:
            self._show_empty("There are no answers in this project yet.")

    def is_ready(self) -> bool:
        """The answers are in the project and showing."""
        return self._total > 0

    def restore_answer(self, source_id: str) -> None:
        """Remember which answer to come back to (an id, never any text)."""
        self._pending_answer = str(source_id or "")

    def _on_answer_selected(self) -> None:
        items = self.answers_tree.selectedItems()
        if not items:
            return
        self._show_answer(items[0].data(0, Qt.ItemDataRole.UserRole))

    def _show_answer(self, source_id: str) -> None:
        if not self._service.is_open:
            return
        answer = hc.get(self._service.project, source_id)
        if answer is None:
            return
        self._source_id = source_id
        self.answer_label.setText(_plain(answer.text))
        self._fill_codes()
        for i in range(self.codes_list.count()):
            item = self.codes_list.item(i)
            item.setCheckState(Qt.CheckState.Checked if item.data(Qt.ItemDataRole.UserRole) in answer.codes
                               else Qt.CheckState.Unchecked)

    def show_answer(self, source_id: str) -> bool:
        """Go to one answer, on whichever page it is. False if it is not there."""
        if not self._service.is_open or hc.get(self._service.project, source_id) is None:
            return False
        self._reload(keep=source_id)
        for i in range(self.answers_tree.topLevelItemCount()):
            if self.answers_tree.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole) == source_id:
                self.answers_tree.setCurrentItem(self.answers_tree.topLevelItem(i))
                return True
        self._show_answer(source_id)
        return True

    def _add_code(self) -> None:
        name = self.new_code_edit.text().strip()
        if not name or not self._source_id:
            return
        existing = [self.codes_list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.codes_list.count())]
        if name not in existing:
            item = QListWidgetItem(name)
            item.setData(Qt.ItemDataRole.UserRole, name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            self.codes_list.addItem(item)
        for i in range(self.codes_list.count()):
            if self.codes_list.item(i).data(Qt.ItemDataRole.UserRole) == name:
                self.codes_list.item(i).setCheckState(Qt.CheckState.Checked)
        self.new_code_edit.clear()

    def _save_and_next(self) -> None:
        if not self._source_id or not self._service.is_open:
            return
        result = hc.save(self._service.project, self._source_id, self._ticked(),
                         rater_name=self._service.analyst_name)
        self._service.notify_changed()
        count = len(result["codes"])
        following = hc.next_unjudged(self._service.project, self._source_id, only_ids=self._only_ids)
        self._reload(keep=following or self._source_id)
        if following is None:
            self.message.setText(success_span(
                "You have coded every answer in the sample." if self._only_ids is not None
                else "You have coded every answer."))
        else:
            self.message.setText(success_span(
                f"Saved: {count} code{'s' if count != 1 else ''}." if count else "Saved: no code applies."))

    def _skip(self) -> None:
        if not self._service.is_open:
            return
        following = hc.next_unjudged(self._service.project, self._source_id, only_ids=self._only_ids)
        if following:
            self.show_answer(following)


def _plain(text: str) -> str:
    """The answer for a rich-text label: shown as written, never read as markup."""
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>"))
