"""
Code with a written codebook (Surveys, step 3, second choice).

Four short stages, one at a time: write the codebook, check the coding engine,
run it, review what it was unsure about. It is the desktop version of the web
page `app/alt_survey_flow.py`; both use `core/written_codebook.py`, so a run made
in one is the same run made in the other.

Every stage shows a few controls and one filled button; the rest are under More
options. It is labelled a preview, and a score is called a model score, never a
probability, until it has been compared with a person's coding.

The answers are in the project file. This screen shows them for review but never
writes them anywhere else, and the engine runs in its own process on this
computer (`engines/laya_client.py`).
"""

from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import pandas as pd
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QSpinBox, QStackedWidget,
    QTableWidget, QTableWidgetItem, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from analysis import calibration as cal

from core import written_codebook as wc
from core.model import Code
from core.run_config import parse_labels
from qualsafe_qt.services.project_service import ProjectService
from qualsafe_qt.services.tasks import run_task
from qualsafe_qt.theme import success_span, warning_span
from qualsafe_qt.views.answers_view import HandCodingView
from qualsafe_qt.widgets.caveat import CaveatNote
from qualsafe_qt.widgets.more_options import MoreOptions, count_controls
from qualsafe_qt.widgets.wrapping import WrappingLabel

STAGES = ("codebook", "engine", "run", "review", "sample", "compare")
_TITLES = {
    "codebook": "Write your codebook",
    "engine": "Check the coding engine",
    "run": "Run the coding",
    "review": "Review what it was unsure about",
    "sample": "Code a sample yourself",
    "compare": "See how it compares with you",
}
#: What the agreement table says when there are too few answers to trust a figure.
_TOO_FEW = "Applied to too few answers for κ to mean anything"
_TOP = "(top level)"
_ANSWER_LIMIT = 50          # answers listed for review at once


def _label(text: str) -> WrappingLabel:
    return WrappingLabel(text)


def hc_sources(project, excerpt_ids) -> set:
    from core import hand_coding

    return hand_coding.source_ids_for_excerpts(project, excerpt_ids)


def _flat_list() -> QTreeWidget:
    """A plain one-column list of rows to pick from (a tree with no branches, like the codebook's)."""
    tree = QTreeWidget()
    tree.setHeaderHidden(True)
    tree.setRootIsDecorated(False)
    return tree


class WrittenCodebookView(QWidget):
    """The four stages of coding with a written codebook."""

    status = Signal(str)
    #: A project was made here because none was open; the shell should show it.
    project_created = Signal(str)
    #: Back was pressed on the first stage: return to the choice of how to code.
    back_requested = Signal()

    def __init__(self, service: ProjectService, output_root: Optional[Callable[[], Path]] = None,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._service = service
        self._output_root = output_root
        self._frame: Optional[pd.DataFrame] = None
        self._text_column = ""
        self._id_column = ""
        self._stage = STAGES[0]
        self._editing_id = ""
        self._run_id = ""
        self._engine_state: Dict[str, Any] = {}
        self._running = False
        self._cancel = threading.Event()
        self._queue = pd.DataFrame()
        self._compare = pd.DataFrame()

        self.stage_label = QLabel("")
        self.preview_note = _label(
            "<i>Preview. Check its codes against your own coding before you rely on them. "
            "A score here is a model score, not a probability.</i>")
        self.message = _label("")

        self._stack = QStackedWidget()
        for page in (self._page_codebook(), self._page_engine(), self._page_run(),
                     self._page_review(), self._page_sample(), self._page_compare()):
            self._stack.addWidget(page)

        self.back_button = QPushButton("Back")
        self.next_button = QPushButton("Next")
        self.back_button.clicked.connect(self._back)
        self.next_button.clicked.connect(lambda: self._step(+1))
        nav = QHBoxLayout()
        nav.addWidget(self.back_button)
        nav.addStretch(1)
        nav.addWidget(self.next_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.stage_label)
        layout.addWidget(self.preview_note)
        layout.addWidget(self.message)
        layout.addWidget(self._stack, 1)
        layout.addLayout(nav)

        service.project_changed.connect(lambda _p: self._on_project_changed())
        self.go_stage(STAGES[0])

    # ── the four pages ────────────────────────────────────────────────────────

    def _page_codebook(self) -> QWidget:
        self.codes_list = _flat_list()
        self.codes_list.setToolTip("Your codes. Pick one to change its rules.")
        self.codes_list.itemSelectionChanged.connect(self._on_code_selected)
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("What the code is called")
        self.include_edit = QPlainTextEdit()
        self.include_edit.setPlaceholderText(
            "Count an answer when… (be concrete: 'mentions trouble paying tuition, housing or "
            "books' works better than 'money')")
        self.include_edit.setMaximumHeight(80)
        self.exclude_edit = QPlainTextEdit()
        self.exclude_edit.setPlaceholderText(
            "Leave an answer out when… (shown to you when you review. The engine is not asked this "
            "unless you turn it on in step 3: in our test it made the engine worse.)")
        self.exclude_edit.setMaximumHeight(80)
        self.save_code_button = QPushButton("Add code")
        self.save_code_button.clicked.connect(self._save_code)

        self.definition_edit = QPlainTextEdit()
        self.definition_edit.setMaximumHeight(60)
        self.definition_edit.setPlaceholderText("A short description in your own words")
        self.examples_edit = QPlainTextEdit()
        self.examples_edit.setMaximumHeight(70)
        self.examples_edit.setPlaceholderText("Answers that fit, one per line (optional)")
        self.parent_combo = QComboBox()
        self.type_combo = QComboBox()
        self.type_combo.addItem("Yes or no: does the answer touch this theme?", "noul")
        self.type_combo.addItem("A rating scale (for example none, mild, severe)", "score")
        self.rubric_edit = QPlainTextEdit()
        self.rubric_edit.setMaximumHeight(60)
        self.rubric_edit.setPlaceholderText("Rating levels, low to high, one per line")
        self.rubric_edit.setVisible(False)
        self.type_combo.currentIndexChanged.connect(
            lambda: self.rubric_edit.setVisible(self.type_combo.currentData() == "score"))
        self.new_code_button = QPushButton("Start a new code")
        self.new_code_button.clicked.connect(self._new_code)

        more = MoreOptions("More options")
        for text, widget in (("Description", self.definition_edit), ("Examples", self.examples_edit),
                             ("Group under", self.parent_combo), ("Kind of code", self.type_combo)):
            more.add_row(text, widget)
        more.body_layout.addWidget(self.rubric_edit)
        more.body_layout.addWidget(self.new_code_button)
        more.add_note("<i>To rename, regroup, merge or delete a code, use the Codebook screen.</i>")
        more._count = count_controls(more.body)
        more._refresh_title()
        self.codebook_more = more

        page = QWidget()
        col = QVBoxLayout(page)
        col.addWidget(_label(
            "Each code needs a clear rule for what counts and what does not. The rule, not "
            "just the name, is what the engine is asked."))
        col.addWidget(self.codes_list, 1)
        col.addWidget(self.name_edit)
        col.addWidget(self.include_edit)
        col.addWidget(self.exclude_edit)
        col.addWidget(self.save_code_button)
        col.addWidget(more)
        return page

    def _page_engine(self) -> QWidget:
        self.engine_label = _label("")
        self.engine_detail = _label("")
        self.install_button = QPushButton("Install the coding engine…")
        self.install_button.clicked.connect(self._install_clicked)
        self.recheck_button = QPushButton("Check again")
        self.recheck_button.clicked.connect(self.refresh_engine)
        more = MoreOptions("More options")
        more.add_row("Engine status", self.recheck_button)
        more._count = count_controls(more.body)
        more._refresh_title()
        self.engine_more = more
        self.install_progress = QProgressBar()
        self.install_progress.setRange(0, 0)
        self.install_progress.setVisible(False)

        page = QWidget()
        col = QVBoxLayout(page)
        col.addWidget(self.engine_label)
        col.addWidget(self.engine_detail)
        col.addWidget(self.install_progress)
        col.addWidget(self.install_button)
        col.addWidget(more)
        col.addStretch(1)
        return page

    def _page_run(self) -> QWidget:
        self.source_label = _label("")
        self.run_button = QPushButton("Run coding")
        self.run_button.clicked.connect(self._run_clicked)
        self.cancel_button = QPushButton("Stop")
        self.cancel_button.clicked.connect(self._cancel.set)
        self.cancel_button.setEnabled(False)
        self.run_progress = QProgressBar()
        self.run_progress.setRange(0, 100)
        self.run_progress.setVisible(False)
        self.run_progress_label = _label("")
        self.run_progress_label.setVisible(False)
        self.run_summary = _label("")
        self.demo_note = _label("")
        self.estimate_label = _label("")
        self.remove_demo_button = QPushButton("Remove the demo codings")
        self.remove_demo_button.clicked.connect(self._remove_demo)
        self.remove_demo_button.setVisible(False)

        self.run_name_edit = QLineEdit("coding_run_1")
        self.run_name_edit.setToolTip(
            "Running again under the same name carries on where it stopped: answers already "
            "coded are skipped.")
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Each code on its own (an answer can fit several)", "multi_label_noul")
        self.mode_combo.addItem("One code per answer (the codes cannot overlap)", "single_label_choice")
        self.low_spin = QDoubleSpinBox()
        self.high_spin = QDoubleSpinBox()
        for spin, value in ((self.low_spin, 0.35), (self.high_spin, 0.65)):
            spin.setRange(0.0, 1.0)
            spin.setSingleStep(0.05)
            spin.setDecimals(2)
            spin.setValue(value)
        self.budget_spin = QSpinBox()
        self.budget_spin.setRange(50, 1000)
        self.budget_spin.setSingleStep(25)
        self.budget_spin.setValue(350)
        self.force_check = QCheckBox("Code every answer again, even those already coded")
        self.exclusions_check = QCheckBox("Also ask the engine each code's leave-out rule")
        self.exclusions_check.setToolTip(
            "Off by default. In a small test on 12 answers, adding the leave-out rule made the "
            "engine pick the right code less often (5 of 12, against 9 of 12 without it).")
        more = MoreOptions("More options")
        more.add_row("Name of this run", self.run_name_edit)
        more.add_row("How to code", self.mode_combo)
        more.add_row("Ask me to check scores from", self.low_spin)
        more.add_row("up to", self.high_spin)
        more.add_row("Longest piece of an answer", self.budget_spin)
        more.body_layout.addWidget(self.force_check)
        more.body_layout.addWidget(self.exclusions_check)
        more._count = count_controls(more.body)
        more._refresh_title()
        self.run_more = more

        row = QHBoxLayout()
        row.addWidget(self.run_button)
        row.addWidget(self.cancel_button)
        row.addStretch(1)
        page = QWidget()
        col = QVBoxLayout(page)
        col.addWidget(self.source_label)
        col.addWidget(self.demo_note)
        col.addWidget(self.estimate_label)
        col.addWidget(self.remove_demo_button)
        col.addLayout(row)
        col.addWidget(self.run_progress_label)
        col.addWidget(self.run_progress)
        col.addWidget(self.run_summary)
        col.addWidget(more)
        col.addStretch(1)
        return page

    def _page_review(self) -> QWidget:
        self.review_note = _label("")
        self.queue_list = _flat_list()
        self.queue_list.itemSelectionChanged.connect(self._on_queue_selected)
        self.answer_label = _label("")
        self.accept_button = QPushButton("Accept this code")
        self.reject_button = QPushButton("Reject")
        self.flag_button = QPushButton("Flag it")
        self.accept_button.clicked.connect(lambda: self._review("accept"))
        self.reject_button.clicked.connect(lambda: self._review("reject"))
        self.flag_button.clicked.connect(lambda: self._review("flag"))
        self.accept_all_button = QPushButton("Accept all the codes waiting")
        self.accept_all_button.clicked.connect(self._accept_all)
        self.reviewer_edit = QLineEdit()
        self.reviewer_edit.setPlaceholderText("Your name")
        more = MoreOptions("More options")
        more.add_row("Reviewing as", self.reviewer_edit)
        more.body_layout.addWidget(self.accept_all_button)
        more._count = count_controls(more.body)
        more._refresh_title()
        self.review_more = more

        row = QHBoxLayout()
        for button in (self.accept_button, self.reject_button, self.flag_button):
            row.addWidget(button)
        row.addStretch(1)
        page = QWidget()
        col = QVBoxLayout(page)
        col.addWidget(self.review_note)
        col.addWidget(self.queue_list, 1)
        col.addWidget(self.answer_label)
        col.addLayout(row)
        col.addWidget(more)
        return page

    # ── pages 5 and 6: check it against yourself ──────────────────────────────

    def _page_sample(self) -> QWidget:
        self.sample_note = _label("")
        self.sample_size_spin = QSpinBox()
        self.sample_size_spin.setRange(5, 500)
        self.sample_size_spin.setValue(30)
        self.sample_size_spin.setToolTip("A random sample, not the answers it was unsure about: those "
                                         "are the hard ones, and would make it look worse than it is.")
        self.draw_button = QPushButton("Pick a random sample")
        self.draw_button.clicked.connect(self._draw_sample)
        pick = QWidget()
        pick_col = QVBoxLayout(pick)
        pick_col.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        row.addWidget(QLabel("How many answers"))
        row.addWidget(self.sample_size_spin)
        row.addStretch(1)
        pick_col.addLayout(row)
        pick_col.addWidget(self.draw_button)
        pick_col.addStretch(1)

        self.sample_hand = HandCodingView(self._service, output_root=self._output_root)
        self.sample_hand.set_embedded(True)
        self.sample_hand.status.connect(self.status)
        self.redraw_button = QPushButton("Pick a different random sample")
        self.redraw_button.clicked.connect(self._redraw_sample)
        self.sample_hand.more.body_layout.addWidget(self.redraw_button)
        self.sample_hand.more._count = count_controls(self.sample_hand.more.body)
        self.sample_hand.more._refresh_title()

        self.sample_stack = QStackedWidget()
        self.sample_stack.addWidget(pick)
        self.sample_stack.addWidget(self.sample_hand)
        page = QWidget()
        col = QVBoxLayout(page)
        col.addWidget(self.sample_note)
        col.addWidget(self.sample_stack, 1)
        return page

    def _page_compare(self) -> QWidget:
        self.compare_headline = _label("")
        self.compare_note = CaveatNote("note")
        self.compare_table = QTableWidget(0, 7)
        self.compare_table.setHorizontalHeaderLabels(
            ["Code", "Agreement (κ)", "Same answer", "You applied it", "Engine applied it",
             "Answers", "Note"])
        self.compare_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.compare_table.verticalHeader().setVisible(False)
        self.save_table_button = QPushButton("Save the table…")
        self.save_table_button.clicked.connect(self.save_table)

        self.detail_table = QTableWidget(0, 4)
        self.detail_table.setHorizontalHeaderLabels(["Code", "Right when it applied", "Found of yours",
                                                     "Combined"])
        self.detail_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.detail_table.verticalHeader().setVisible(False)
        self.band_label = _label("")
        self.apply_band_button = QPushButton("Use this range for the next run")
        self.apply_band_button.clicked.connect(self._apply_band)
        self.apply_band_button.setVisible(False)
        more = MoreOptions("More options")
        more.add_note("<i>Which kind of mistake: how often a code it applied was right, and how many "
                      "of the ones you applied it found. These describe the mistakes. Agreement "
                      "itself is the κ column.</i>")
        more.body_layout.addWidget(self.detail_table)
        more.body_layout.addWidget(self.band_label)
        more.body_layout.addWidget(self.apply_band_button)
        more._count = count_controls(more.body)
        more._refresh_title()
        self.compare_more = more

        page = QWidget()
        col = QVBoxLayout(page)
        col.addWidget(self.compare_headline)
        col.addWidget(self.compare_note)
        col.addWidget(self.compare_table, 1)
        col.addWidget(self.save_table_button, 0, Qt.AlignmentFlag.AlignLeft)
        col.addWidget(more)
        return page

    def _current_run(self) -> str:
        if self._run_id:
            return self._run_id
        if not self._service.is_open:
            return ""
        runs = cal.decision_run_ids(self._service.project)
        return runs[0] if runs else ""

    def _has_sample(self) -> bool:
        run = self._current_run()
        return bool(run) and self._service.is_open and bool(cal.load_sample(self._service.project, run))

    def _refresh_sample_page(self) -> None:
        run = self._current_run()
        if not run:
            self.sample_note.setText("Run the coding first. The sample is drawn from the answers it coded.")
            self.draw_button.setEnabled(False)
            self.sample_stack.setCurrentIndex(0)
            self._refresh_main()
            return
        project = self._service.project
        demo = "__demo_" in run
        n_all = len(cal.run_excerpt_ids(project, run))
        self.sample_size_spin.setMaximum(max(5, n_all))
        self.sample_size_spin.setValue(min(30, max(5, n_all)))
        self.draw_button.setEnabled(n_all >= 5)
        warning = warning_span("This run used the demo engine, so checking it measures nothing real.",
                               bold=False) + "<br>" if demo else ""
        if cal.load_sample(project, run):
            self.sample_note.setText(
                warning + "Code every answer below yourself, ticking every code that applies. You do not "
                "see what the engine chose, so that cannot sway you.")
            ids = cal.load_sample(project, run)
            self.sample_hand.restrict_to(hc_sources(project, ids))
            self.sample_hand.show_project_answers()
            self.sample_stack.setCurrentIndex(1)
        else:
            self.sample_note.setText(
                warning + "To see how often the engine agrees with you, code a random sample of the answers "
                "yourself, then compare. Pick how many: 30 is a small but usable check, and more is better.")
            self.sample_stack.setCurrentIndex(0)
        self._refresh_main()

    def _draw_sample(self) -> None:
        run = self._current_run()
        if not run:
            return
        project = self._service.project
        ids = cal.draw_sample(cal.run_excerpt_ids(project, run), self.sample_size_spin.value())
        cal.save_sample(project, run, ids)
        self._service.notify_changed()
        self._refresh_sample_page()

    def _redraw_sample(self) -> None:
        """A new sample replaces the old; what you coded stays, but only the new sample is compared."""
        self._draw_sample()

    def _refresh_compare_page(self) -> None:
        self._compare = pd.DataFrame()
        self.compare_table.setRowCount(0)
        self.detail_table.setRowCount(0)
        self.apply_band_button.setVisible(False)
        self.band_label.setText("")
        self.compare_note.setVisible(False)
        run = self._current_run()
        if not run or not self._service.is_open or not cal.load_sample(self._service.project, run):
            self.compare_headline.setText("Code a sample first (the step before this one). Then this "
                                          "shows how often the engine agrees with you, code by code.")
            return
        project = self._service.project
        size, judged = cal.sample_status(project, run)
        pairs = cal.calibration_pairs(project, run)
        if pairs.empty:
            self.compare_headline.setText(
                f"You have coded {judged} of the {size} sample answers. Code some of them first.")
            return
        table = cal.agreement_by_code(pairs)
        self._compare = table
        n = int(pairs["excerpt_id"].nunique())
        demo = "__demo_" in run
        self.compare_headline.setText(
            (warning_span("Demo engine: these figures measure nothing real. ", bold=False) if demo else "")
            + f"<b>You against the coding engine, on the {n} answers you coded.</b> The engine is shown "
              "beside you here; it is not counted as a coder. Agreement is Cohen's κ for each code.")
        self.compare_note.setText("<br>".join(cal.CAVEATS + [
            "κ describes agreement on these answers only. With few answers it moves a lot, so a "
            "figure with a note beside it should not be relied on."]))
        self.compare_note.setVisible(True)
        self.compare_table.setRowCount(len(table))
        for r, row in enumerate(table.itertuples(index=False)):
            reliable = bool(row.reliable)
            cells = [row.code,
                     f"{row.kappa:.2f}" if reliable and pd.notna(row.kappa) else "—",
                     f"{row.percent_agreement:.0%}", f"{row.prevalence_human:.0%}",
                     f"{row.prevalence_model:.0%}", str(int(row.n_items)),
                     "" if reliable else _TOO_FEW]
            for c, text in enumerate(cells):
                self.compare_table.setItem(r, c, QTableWidgetItem(text))
        self.compare_table.resizeColumnsToContents()
        self.detail_table.setRowCount(len(table))
        self.detail_table.resizeColumnsToContents()
        for r, row in enumerate(table.itertuples(index=False)):
            cells = [row.code, "—" if pd.isna(row.precision) else f"{row.precision:.0%}",
                     "—" if pd.isna(row.recall) else f"{row.recall:.0%}",
                     "—" if pd.isna(row.f1) else f"{row.f1:.2f}"]
            for c, text in enumerate(cells):
                self.detail_table.setItem(r, c, QTableWidgetItem(text))
        self.detail_table.resizeColumnsToContents()
        band = cal.recommend_band(pairs)
        if band["low"] is not None and band["high"] is not None:
            low, high = self._band()
            self.band_label.setText(
                f"This sample supports applying a code without a check at {band['high']:.2f} and above, "
                f"and treating scores below {band['low']:.2f} as no code. The current range is "
                f"{low:.2f} to {high:.2f}. {band['note']}")
            self._pending_band = (band["low"], band["high"])
            self.apply_band_button.setVisible(True)
        else:
            self.band_label.setText(band["note"] or "No range can be recommended from this sample.")

    def _apply_band(self) -> None:
        low, high = getattr(self, "_pending_band", (None, None))
        if low is None:
            return
        self.low_spin.setValue(low)
        self.high_spin.setValue(high)
        self._say(f"The next run will ask you to check scores from {low:.2f} to {high:.2f}.", "success")

    def _ask_save_path(self, default: str) -> str:
        path, _ = QFileDialog.getSaveFileName(self, "Save", default, "Spreadsheet (*.csv)")
        return path

    def save_table(self) -> Optional[str]:
        """The agreement table as a spreadsheet. It holds counts and figures, never an answer."""
        if self._compare.empty:
            self._say("Code some of your sample first: there is nothing to save yet.")
            return None
        path = self._ask_save_path("agreement_with_the_engine.csv")
        if not path:
            return None
        self._compare.to_csv(path, index=False)
        self._say(f"Saved {Path(path).name}.", "success")
        return path

    # ── stages ────────────────────────────────────────────────────────────────

    def current_stage(self) -> str:
        return self._stage

    def go_stage(self, key: str) -> None:
        if key not in STAGES:
            return
        self._stage = key
        number = STAGES.index(key) + 1
        self.stage_label.setText(f"<b>Step {number} of {len(STAGES)}: {_TITLES[key]}</b>")
        self._stack.setCurrentIndex(number - 1)
        self.message.setText("")
        if key == "codebook":
            self._refresh_codes()
        elif key == "engine":
            self.refresh_engine()
        elif key == "run":
            self._refresh_run_page()
        elif key == "review":
            self._refresh_queue()
        elif key == "sample":
            self._refresh_sample_page()
        else:
            self._refresh_compare_page()
        self.back_button.setVisible(True)
        self.back_button.setText("Back to the choices" if number == 1 else "Back")
        self.next_button.setVisible(number < len(STAGES))
        self._refresh_main()

    def _back(self) -> None:
        if self._stage == STAGES[0]:
            self.back_requested.emit()
        else:
            self._step(-1)

    def _step(self, delta: int) -> None:
        self.go_stage(STAGES[max(0, min(len(STAGES) - 1, STAGES.index(self._stage) + delta))])

    def _set_main(self, button: QPushButton, on: bool) -> None:
        if bool(button.property("main")) == on:
            return
        button.setProperty("main", on)
        button.style().unpolish(button)
        button.style().polish(button)

    def _refresh_main(self) -> None:
        """One filled button on each stage: the thing to do there."""
        engine_ready = self._engine_state.get("state") == "ready"
        mains = {
            self.save_code_button: self._stage == "codebook",
            self.install_button: self._stage == "engine" and not engine_ready,
            self.run_button: self._stage == "run",
            self.accept_button: self._stage == "review",
            self.draw_button: self._stage == "sample" and not self._has_sample(),
            self.save_table_button: self._stage == "compare",
        }
        for button, on in mains.items():
            self._set_main(button, on)
        # On the engine stage Next is the main action once the engine is ready.
        self._set_main(self.next_button, self._stage == "engine" and engine_ready)

    def _say(self, text: str, kind: str = "warning") -> None:
        self.message.setText(warning_span(text, bold=False) if kind == "warning"
                             else success_span(text))

    # ── source and project ────────────────────────────────────────────────────

    def set_source(self, frame: Optional[pd.DataFrame], text_column: str, id_column: str = "") -> None:
        """The answers to code: the table from the Load step and its answers column."""
        self._frame = frame
        self._text_column = text_column or ""
        self._id_column = id_column or ""
        if self._stage == "run":
            self._refresh_run_page()

    def _on_project_changed(self) -> None:
        self._editing_id = ""
        self._run_id = ""
        self._refresh_codes()
        if self._stage == "review":
            self._refresh_queue()

    def _ensure_project(self) -> bool:
        """A project to write into. Made here, once, if none is open."""
        if self._service.is_open:
            return True
        root = self._output_root() if self._output_root else Path.home() / "QualSafe"
        path = Path(root) / ("written_codebook_" + datetime.now().strftime("%Y%m%d_%H%M%S")) / "project.qnw"
        path.parent.mkdir(parents=True, exist_ok=True)
        self._service.create(path)
        self.project_created.emit(str(path))
        return True

    # ── 1 · the codebook ──────────────────────────────────────────────────────

    def _codes(self) -> List[Code]:
        return self._service.project.get_codebook() if self._service.is_open else []

    def _refresh_codes(self) -> None:
        selected = self._editing_id
        codes = self._codes()
        names = {c.code_id: c.name for c in codes}
        self.codes_list.blockSignals(True)
        self.codes_list.clear()
        for code in codes:
            suffix = "rules written" if wc.has_rules(code) else "no rules yet"
            item = QTreeWidgetItem([f"{code.name}   ({suffix})"])
            item.setData(0, Qt.ItemDataRole.UserRole, code.code_id)
            self.codes_list.addTopLevelItem(item)
            if code.code_id == selected:
                item.setSelected(True)
        self.codes_list.blockSignals(False)
        self.parent_combo.clear()
        self.parent_combo.addItem(_TOP, "")
        for code_id, name in names.items():
            self.parent_combo.addItem(name, code_id)
        self.save_code_button.setText("Save this code" if self._editing_id else "Add code")

    def _on_code_selected(self) -> None:
        items = self.codes_list.selectedItems()
        if not items:
            return
        code_id = items[0].data(0, Qt.ItemDataRole.UserRole)
        code = next((c for c in self._codes() if c.code_id == code_id), None)
        if code is None:
            return
        self._editing_id = code_id
        self.name_edit.setText(code.name)
        self.include_edit.setPlainText(code.inclusion_criteria or "")
        self.exclude_edit.setPlainText(code.exclusion_criteria or "")
        self.definition_edit.setPlainText(code.definition or "")
        self.examples_edit.setPlainText("\n".join(code.examples or []))
        self.type_combo.setCurrentIndex(max(0, self.type_combo.findData(code.decision_type or "noul")))
        self.rubric_edit.setPlainText("\n".join(code.rubric_levels or []))
        self.parent_combo.setCurrentIndex(max(0, self.parent_combo.findData(code.parent_id or "")))
        self.save_code_button.setText("Save this code")

    def _new_code(self) -> None:
        self._editing_id = ""
        self.codes_list.clearSelection()
        for edit in (self.name_edit,):
            edit.clear()
        for box in (self.include_edit, self.exclude_edit, self.definition_edit,
                    self.examples_edit, self.rubric_edit):
            box.clear()
        self.parent_combo.setCurrentIndex(0)
        self.type_combo.setCurrentIndex(0)
        self.save_code_button.setText("Add code")

    def _save_code(self) -> None:
        name = self.name_edit.text().strip()
        if not name:
            self._say("Name the code first.")
            return
        self._ensure_project()
        project = self._service.project
        fields = dict(inclusion_criteria=self.include_edit.toPlainText().strip(),
                      exclusion_criteria=self.exclude_edit.toPlainText().strip(),
                      examples=parse_labels(self.examples_edit.toPlainText()))
        kind = self.type_combo.currentData() or "noul"
        rubric = parse_labels(self.rubric_edit.toPlainText()) if kind == "score" else None
        if self._editing_id:
            self._service.update_code(self._editing_id, name=name,
                                      definition=self.definition_edit.toPlainText().strip())
            project.set_code_structured_fields(self._editing_id, **fields)
            self._say(f"Saved “{name}”.", "success")
        else:
            project.add_code(Code(
                code_id="", name=name, definition=self.definition_edit.toPlainText().strip(),
                parent_id=self.parent_combo.currentData() or None, decision_type=kind,
                rubric_levels=rubric or None, **fields))
            self._say(f"Added “{name}”.", "success")
            self._editing_id = ""
        self._service.notify_changed()
        self._refresh_codes()
        if not self._editing_id:
            self._new_code()

    # ── 2 · the engine ────────────────────────────────────────────────────────

    def refresh_engine(self) -> None:
        from engines import laya_setup

        self._engine_state = laya_setup.installation_status()
        ready = self._engine_state.get("state") == "ready"
        info = laya_setup.install_instructions()
        if ready:
            self.engine_label.setText(success_span(
                f"The coding engine (Laya {self._engine_state.get('laya_version', '')}) is "
                "installed and ready. It runs on this computer."))
            self.engine_detail.setText("")
        elif self._engine_state.get("state") == "needs_engine":
            self.engine_label.setText(warning_span(
                "The coding engine (Laya) needs the analysis engine (the language-model software) "
                "installed first. Install it in Settings, then Models, and come back. Until then "
                "“Run coding” uses a demo engine whose scores mean nothing.", bold=False))
        elif self._engine_state.get("state") == "needs_model":
            self.engine_label.setText(warning_span(
                "The coding engine (Laya) is installed, but its model file has not been downloaded "
                "yet. Until it is, “Run coding” uses a demo engine whose scores mean nothing.",
                bold=False))
        else:
            self.engine_label.setText(warning_span(
                "The coding engine (Laya) is not installed yet. Without it, “Run coding” uses a "
                "demo engine whose scores mean nothing. It says so wherever it is used.",
                bold=False))
            self.engine_detail.setText(
                "<i>Installing adds a small package and downloads the model, about "
                f"{info['disk_estimate_mb']:,} MB in all, once. After that it runs without the "
                "internet. None of your data is uploaded. " + info["why_isolated"] + "</i>")
        self.install_button.setVisible(not ready and self._engine_state.get("state") != "needs_engine")
        self._refresh_main()

    def _confirm_install(self) -> bool:
        from engines import laya_setup

        info = laya_setup.install_instructions()
        text = ("This adds a small package and downloads the model, about %s MB in all, onto this "
                "computer. Your data is not uploaded. It can take several minutes.\n\nInstall now?"
                % f"{info['disk_estimate_mb']:,}")
        return QMessageBox.question(self, "Install the coding engine", text) == QMessageBox.StandardButton.Yes

    def _install_clicked(self) -> None:
        from engines import laya_setup

        if self._running or not self._confirm_install():
            return
        self._running = True
        self.install_button.setEnabled(False)
        self.install_progress.setVisible(True)
        self.status.emit("Installing the coding engine…")
        run_task(laya_setup.install, on_finished=self._install_finished,
                 on_failed=lambda msg, _tb: self._install_finished({"ok": False, "error": msg}),
                 on_done=self._install_done)

    def _install_finished(self, result: Dict[str, Any]) -> None:
        if result.get("ok"):
            self._say("The coding engine is installed.", "success")
        else:
            self._say(f"The install did not finish: {result.get('error', 'unknown error')}")

    def _install_done(self) -> None:
        self._running = False
        self.install_button.setEnabled(True)
        self.install_progress.setVisible(False)
        self.refresh_engine()

    # ── 3 · run ───────────────────────────────────────────────────────────────

    def _refresh_run_page(self) -> None:
        if self._frame is None or not self._text_column:
            self.source_label.setText(warning_span(
                "No answers to code yet. Load a spreadsheet, choose the answers column and confirm the privacy check in step 1.",
                bold=False))
        else:
            n = int(self._frame[self._text_column].astype(str).str.strip().ne("").sum()) \
                if self._text_column in self._frame.columns else 0
            self.source_label.setText(f"Coding the answers in <b>{self._text_column}</b> "
                                      f"({n:,} answers).")
        ready = self._engine_state.get("state") == "ready"
        if ready and self._frame is not None and self._text_column in self._frame.columns:
            n = int(self._frame[self._text_column].astype(str).str.strip().ne("").sum())
            codes = len(wc.usable_codes(self._codes()))
            self.estimate_label.setText(
                f"<i>Expect {wc.estimate_text(n, codes)} for {n:,} answers and {codes} codes on a "
                "typical laptop. It keeps going if you work elsewhere, and you can stop it and carry on "
                "later.</i>")
        else:
            self.estimate_label.setText("")
        self.demo_note.setText("" if ready else warning_span(
            "The coding engine is not installed, so this will use the <b>demo engine</b>: "
            "its scores mean nothing.", bold=False))
        self._refresh_demo_button()

    def _refresh_demo_button(self) -> None:
        from engines.laya_engine import demo_rater_ids

        has_demo = self._service.is_open and bool(demo_rater_ids(self._service.project))
        self.remove_demo_button.setVisible(has_demo)

    def run_spec(self) -> Dict[str, Any]:
        return {"text_column": self._text_column, "mode": self.mode_combo.currentData(),
                "low_threshold": float(self.low_spin.value()),
                "high_threshold": float(self.high_spin.value()),
                "segmentation_token_budget": int(self.budget_spin.value()),
                "send_exclusions": self.exclusions_check.isChecked(),
                "model": "convaiinnovations/laya"}

    def _run_clicked(self) -> None:
        if self._running:
            return
        if self._frame is None or not self._text_column:
            self._say("Load your answers and confirm the privacy check in step 1 first.")
            return
        if not [c for c in self._codes() if c.decision_type != "score"]:
            self._say("Add at least one code before running.")
            return
        if self.low_spin.value() >= self.high_spin.value():
            self._say("The low score must be below the high score.")
            return
        self._ensure_project()
        self._service.notify_changed()
        ready = self._engine_state.get("state") == "ready"
        python = self._engine_state.get("python") if ready else None
        env = None
        if ready:
            from engines import laya_setup
            env = laya_setup.worker_env()
        self._cancel.clear()
        self._running = True
        self.run_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.run_progress.setValue(0)
        self.run_progress.setVisible(True)
        self.run_progress_label.setVisible(True)
        self.run_progress_label.setText("<i>Starting…</i>")
        self.run_summary.setText("")
        self.status.emit("Coding started…")
        run_task(
            wc.run, str(self._service.path), self._frame, self._text_column, self._id_column,
            self.run_name_edit.text().strip() or "coding_run", self.run_spec(),
            python_exe=python, worker_env=env, force=self.force_check.isChecked(),
            should_cancel=self._cancel.is_set, wants_progress=True, reads_store=True,
            on_progress=self._on_progress, on_finished=self._run_finished,
            on_failed=self._run_failed, on_done=self._run_done)

    def _on_progress(self, fraction: float, message: str) -> None:
        percent = int(max(0.0, min(1.0, fraction)) * 100)
        self.run_progress.setValue(percent)
        self.run_progress_label.setText(f"<i>{message}  ·  {percent}%</i>")

    def _run_finished(self, result: Dict[str, Any]) -> None:
        self._run_id = result.get("run_id", "")
        demo = result.get("engine") != "laya"
        parts = []
        if result.get("cancelled"):
            parts.append(warning_span(
                f"Stopped. {result.get('coded', 0)} answers were coded first. Run again under the "
                "same name to carry on.", bold=False))
        else:
            parts.append(success_span(
                f"Coded {result.get('coded', 0)} answers ({result.get('skipped', 0)} were already "
                f"done, {result.get('assigned', 0)} codes were applied without needing a check)."))
        if demo:
            parts.append(warning_span(
                (result.get("engine_note") or "The demo engine was used.")
                + " Its scores mean nothing.", bold=False))
        self.run_summary.setText("<br>".join(parts))
        self.status.emit("Coding finished.")

    def _run_failed(self, message: str, _traceback: str) -> None:
        self.run_summary.setText(warning_span(f"The run could not finish: {message}", bold=False))
        self.status.emit("The coding run failed.")

    def _run_done(self) -> None:
        self._running = False
        self.run_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.run_progress.setVisible(False)
        self.run_progress_label.setVisible(False)
        self._service.reopen()          # the worker wrote to the file on its own connection
        self._refresh_demo_button()
        self._refresh_codes()

    def _remove_demo(self) -> None:
        from engines.laya_engine import remove_demo_codings

        report = remove_demo_codings(self._service.project)
        self._service.notify_changed()
        self._say(f"Removed {report['applications']} demo codings. Real and hand coding is untouched.",
                  "success")
        self._refresh_demo_button()

    # ── 4 · review ────────────────────────────────────────────────────────────

    def _band(self) -> tuple:
        return float(self.low_spin.value()), float(self.high_spin.value())

    def _refresh_queue(self) -> None:
        self.queue_list.clear()
        self.answer_label.setText("")
        self._queue = pd.DataFrame()
        if not self._run_id or not self._service.is_open:
            self.review_note.setText("Run the coding first. Anything it is unsure about comes here.")
            self._enable_review(False)
            return
        low, high = self._band()
        self._queue = wc.queue(self._service.project, self._run_id, low, high)
        if self._queue.empty:
            self.review_note.setText(success_span("Nothing is waiting for your review in this run."))
            self._enable_review(False)
            return
        self.review_note.setText(
            f"{len(self._queue)} codes are waiting for you to check. The scores are model scores, "
            "not probabilities.")
        for position, (_i, row) in enumerate(self._queue.head(_ANSWER_LIMIT).iterrows()):
            item = QTreeWidgetItem([f"{row['code_name']}   ·   model score {float(row['model_score']):.2f}"])
            item.setData(0, Qt.ItemDataRole.UserRole, position)
            self.queue_list.addTopLevelItem(item)
        if len(self._queue) > _ANSWER_LIMIT:
            self.review_note.setText(self.review_note.text()
                                     + f" Showing the first {_ANSWER_LIMIT}; the rest follow as you go.")
        self._enable_review(True)
        self.queue_list.setCurrentItem(self.queue_list.topLevelItem(0))

    def _enable_review(self, on: bool) -> None:
        for button in (self.accept_button, self.reject_button, self.flag_button, self.accept_all_button):
            button.setEnabled(on)

    def _current_row(self):
        item = self.queue_list.currentItem()
        if item is None or self._queue.empty:
            return None
        return self._queue.iloc[int(item.data(0, Qt.ItemDataRole.UserRole))]

    def _on_queue_selected(self) -> None:
        row = self._current_row()
        if row is None:
            self.answer_label.setText("")
            return
        rule = next((c.exclusion_criteria for c in self._codes()
                     if c.name == row["code_name"] and (c.exclusion_criteria or "").strip()), "")
        leave_out = f"<br><i>Leave it out when: {_plain(rule)}</i>" if rule else ""
        self.answer_label.setText(
            f"<b>{row['code_name']}</b>: the answer is<br>{_plain(str(row['excerpt_text']))}{leave_out}")

    def _reviewer(self) -> str:
        return self.reviewer_edit.text().strip() or self._service.analyst_name or "analyst"

    def _review(self, verdict: str) -> None:
        row = self._current_row()
        if row is None:
            return
        wc.review(self._service.project, row["decision_id"], verdict, self._reviewer(),
                  model_assigned=bool(row.get("model_assigned", False)))
        self._service.notify_changed()
        self._refresh_queue()

    def _accept_all(self) -> None:
        if self._queue.empty:
            return
        for _i, row in self._queue.iterrows():
            wc.review(self._service.project, row["decision_id"], "accept", self._reviewer())
        self._service.notify_changed()
        self._say(f"Accepted {len(self._queue)} codes.", "success")
        self._refresh_queue()


def _plain(text: str) -> str:
    """Answer text for a rich-text label: shown as written, never read as markup."""
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace("\n", "<br>"))
