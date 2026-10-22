"""
The pipeline path: load data, set themes, run the analysis.

The Qt counterpart of `app/data_setup.py`, `app/theme_setup.py`, and
`app/run_analysis.py`, as three tabs of one screen — they are one task, and
Streamlit split them into pages mainly because a page is its whole viewport.

**The reason this screen exists in the fork at all is the last tab.**
`run_pipeline` takes minutes: it embeds every response, searches for a cluster
count, runs a zero-shot pass, and optionally calls a local LLM per response.
Streamlit runs that on the thread serving the page, so the app is inert until it
finishes. Here it runs on a `QThreadPool` worker, wired to a real progress bar
through the `progress_callback(fraction, message)` the pipeline already accepts,
and the window stays usable — you can read documents while it works.

Three things this screen is careful about:

* **The PII gate is per-load and never persisted.** Loading a different file
  re-arms it. It is the moment the analyst takes responsibility for what goes
  into the tool, and a remembered attestation is not an attestation.
* **A preview is never the project of record.** `build_config(preview=True)`
  caps the rows and refuses to write a `.qnw`, so a quick look cannot quietly
  become the analysis.
* **The worker opens its own store.** `run_pipeline` writes the `.qnw` itself,
  on its own thread, because a `sqlite3` connection belongs to the thread that
  made it. When it finishes, the service reconnects so the other screens see the
  new coding.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QCheckBox, QComboBox, QDoubleSpinBox,
    QFileDialog, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
    QRadioButton, QSpinBox, QSplitter, QTableView, QTabWidget, QVBoxLayout, QWidget,
)

from core.model_manager import DEFAULT_MODELS
from qualsafe_qt.models.dataframe_model import DataFrameModel
from qualsafe_qt.pipeline_config import (
    PREVIEW_ROWS, SUPPORTED_TABLE_SUFFIXES, RunSettings, build_config,
    estimate_runtime_minutes, label_packs, load_table, mapping_is_ready,
    parse_labels,
    question_values, write_config_snapshot,
)
from qualsafe_qt.views.answers_view import HandCodingView
from qualsafe_qt.views.written_codebook_view import WrittenCodebookView
from qualsafe_qt.widgets.more_options import MoreOptions
from qualsafe_qt.widgets.wrapping import WrappingLabel
from qualsafe_qt.theme import warning_span
from qualsafe_qt.services.project_service import ProjectService
from core.ux import coding_choices
from qualsafe_qt.services.tasks import run_task
from qualsafe_qt.views.analysis_view import _hint, _table_view

#: Where runs land, mirroring `app/shared/constants.STREAMLIT_OUTPUT_DIR`'s role.
_OUTPUT_DIR_NAME = "output_qt"
#: Rows shown in the data preview table.
_PREVIEW_ROWS_SHOWN = 200


_EMPTY_FILE_TEXT = "<i>No answers loaded yet. Open a spreadsheet, or try the sample.</i>"

#: The ways to code survey answers: (key, title, when to use it, available, why not).
#: Same words as the web app (`core/ux/coding_choices.py`); all three are available here.
CODING_CHOICES = tuple((key, title, when, True, "") for key, title, when in coding_choices.CHOICES)


def _checked(widget: QListWidget) -> list:
    """Names of the ticked rows of a checkable list."""
    return [widget.item(i).text() for i in range(widget.count())
            if widget.item(i).checkState() == Qt.CheckState.Checked]


def _set_checked(widget: QListWidget, names: list) -> None:
    wanted = set(map(str, names))
    widget.blockSignals(True)
    for i in range(widget.count()):
        item = widget.item(i)
        item.setCheckState(Qt.CheckState.Checked if item.text() in wanted
                           else Qt.CheckState.Unchecked)
    widget.blockSignals(False)


class PipelineView(QWidget):
    """Data / Themes / Run."""

    status = Signal(str)
    #: A run finished and wrote a project store; the shell should open it.
    project_written = Signal(str)

    def __init__(self, service: ProjectService, undo_stack: QUndoStack,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._service = service
        self._undo = undo_stack
        self._frame: Optional[pd.DataFrame] = None
        self._loaded_from = ""
        #: Which dataset the PII attestation was given for. Loading a different
        #: file changes this and re-arms the gate.
        self._confirmed_for = ""
        self._running = False
        #: Returns {role: model_id}. The shell points this at the Model
        #: Manager's selection, so a chosen model actually changes the run
        #: rather than being a setting that does nothing.
        self.model_provider = None

        self._build_ui()
        self._refresh_enabled()

    # -- construction --------------------------------------------------------
    def _build_ui(self) -> None:
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_data_tab(), "1 · Data")
        self.tabs.addTab(self._build_themes_tab(), "2 · Themes")
        self.tabs.addTab(self._build_run_tab(), "3 · Run")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addWidget(self.tabs)

    def _build_data_tab(self) -> QWidget:
        # The one filled button on this step: nothing else can happen until a file is open.
        self.load_button = QPushButton("Open a data file…")
        self.load_button.setProperty("main", True)
        self.load_button.clicked.connect(self._load_file)
        self.load_button.setToolTip(
            "Open a CSV, Excel, JSON, or SPSS .sav file of survey responses.")
        self.sample_button = QPushButton("Try the sample")
        self.sample_button.clicked.connect(self._load_sample)
        self.sample_button.setToolTip(
            "A 40-row synthetic education survey that pairs with the default "
            "label pack — nothing real, safe to experiment with.")

        self.file_label = WrappingLabel(_EMPTY_FILE_TEXT)

        buttons = QHBoxLayout()
        buttons.addWidget(self.load_button)
        buttons.addWidget(self.sample_button)
        buttons.addStretch(1)

        # -- the privacy gate: asked again on every load, never remembered --
        self.pii_summary = WrappingLabel("")
        self.pii_confirm = QCheckBox(
            "I confirm this dataset has been reviewed and is appropriate to "
            "process locally on this machine")
        self.pii_confirm.toggled.connect(self._on_pii_confirmed)
        self.pii_confirm.setToolTip(
            "Required before a run. Asked again whenever you load different\n"
            "data, and never remembered between sessions.")
        gate_box = QGroupBox("Before analysing")
        gate_layout = QVBoxLayout(gate_box)
        gate_layout.addWidget(WrappingLabel(
            "<i>QualSafe scans for names, email addresses and numbers that could "
            "identify someone. It is a rough check and can miss things, so look "
            "through the file yourself too. You are asked again whenever you load "
            "a different file.</i>"))
        gate_layout.addWidget(self.pii_summary)
        # The long list of what the scan cannot see stays beside its result, one
        # click away: a caveat shortened and placed next to the number, never removed.
        from privacy.scan import SCANNER_LIMITS
        self.pii_limits = MoreOptions("What can this scan miss?")
        self.pii_limits.add_note(SCANNER_LIMITS)
        gate_layout.addWidget(self.pii_limits)
        gate_layout.addWidget(self.pii_confirm)
        self.gate_box = gate_box

        # -- the mapping widgets (the same objects as before; only where they sit changes) --
        self.mode = QComboBox()
        self.mode.addItem("One row per answer (long)", "long")
        self.mode.addItem("One column per question (wide)", "wide")
        self.mode.setToolTip(
            "Long: each row is one answer, with a column saying which question.\n"
            "Wide: each row is one respondent and each question is its own "
            "column — reshaped before analysis, with a unique id for every answer.\n"
            "QualSafe works this out from the file; change it here if it is wrong.")
        self.mode.currentIndexChanged.connect(self._on_mode_changed)

        self.text_column = QComboBox()
        self.text_columns = QListWidget()
        self.text_columns.setSelectionMode(
            QAbstractItemView.SelectionMode.NoSelection)
        self.text_columns.setMaximumHeight(120)
        self.text_columns.itemChanged.connect(lambda _i: self._refresh_enabled())
        self.question_column = QComboBox()
        self.question_manual = QLineEdit()
        self.question_manual.setPlaceholderText(
            "…or type the question these answers respond to")
        self.id_column = QComboBox()
        self.id_column.setToolTip(
            "The column that identifies a respondent. Read as text throughout, "
            "so an id like 101 never becomes 101.0 and detaches its coding.")
        self.descriptors = QListWidget()
        self.descriptors.setSelectionMode(
            QAbstractItemView.SelectionMode.NoSelection)
        self.descriptors.setMaximumHeight(120)
        self.descriptors.setToolTip(
            "Respondent details (program, class year, first-generation "
            "status) kept alongside the answers so you can compare groups.")
        self.text_column.setToolTip(
            "The column holding what people wrote — the answers, not the\n"
            "questions. Never picked for you, because picking wrong analyses the\n"
            "prompts and still succeeds.")
        self.text_columns.setToolTip(
            "In wide data, which columns are questions. Each becomes its own\n"
            "answer per respondent.")
        self.question_column.setToolTip(
            "The column saying which question each answer responds to.\n"
            "Leave as (none) if every row answers the same question.")
        self.question_manual.setToolTip(
            "Used when there is no question column — the label these answers\n"
            "are reported under.")
        for combo in (self.text_column, self.question_column, self.id_column):
            combo.currentIndexChanged.connect(self._refresh_enabled)

        # -- the one choice that matters: which column holds the answers --
        self.answers_caption = QLabel("Answers are in column")
        answers_row = QHBoxLayout()
        answers_row.addWidget(self.answers_caption)
        answers_row.addWidget(self.text_column, 1)
        answers_row.addWidget(self.text_columns, 1)
        self.suggestion_label = WrappingLabel("")
        self.suggestion_button = QPushButton("Use suggested columns")
        self.suggestion_button.setToolTip(
            "QualSafe looked at your file and thinks it knows where the answers are. "
            "This fills in those columns; nothing is chosen until you click.")
        self.suggestion_button.clicked.connect(self._apply_suggestion)
        self.suggestion_label.hide()
        self.suggestion_button.hide()
        self._suggestion = None
        answers_box = QWidget()
        answers_layout = QVBoxLayout(answers_box)
        answers_layout.setContentsMargins(0, 0, 0, 0)
        answers_layout.addLayout(answers_row)
        answers_layout.addWidget(self.suggestion_label)
        answers_layout.addWidget(self.suggestion_button, 0, Qt.AlignmentFlag.AlignLeft)
        self.answers_box = answers_box

        # -- everything else, folded away --
        self.more_options = MoreOptions("More options")
        self.more_options.add_row("Layout", self.mode)
        self.more_options.add_row("Question column", self.question_column)
        self.more_options.add_row("Question label", self.question_manual)
        self.more_options.add_row("Respondent ID column", self.id_column)
        self.more_options.add_row("Respondent details to keep", self.descriptors)
        self.mapping_box = self.more_options

        self.preview_table = _table_view()
        self.preview_table.setSortingEnabled(False)
        self.preview_model = DataFrameModel()
        self.preview_table.setModel(self.preview_model)
        # A long repeated question must not push the answers off the screen.
        self.preview_table.horizontalHeader().setMaximumSectionSize(320)
        self.preview_table.setToolTip(
            "The first rows of the file as loaded, so you can check the columns\n"
            "are what you expect before choosing them.")

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addLayout(buttons)
        left_layout.addWidget(self.file_label)
        left_layout.addWidget(answers_box)
        left_layout.addWidget(gate_box)
        left_layout.addWidget(self.more_options)
        left_layout.addStretch(1)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(self.preview_table)
        splitter.setSizes([620, 900])

        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.addWidget(splitter)
        self._sync_mode_widgets()
        return tab

    def _build_themes_tab(self) -> QWidget:
        self.labels_edit = QPlainTextEdit()
        self.labels_edit.setPlaceholderText(
            "One theme per line, for example:\n\nFinancial concerns\nSense of belonging\n"
            "Academic difficulty")
        self.labels_edit.textChanged.connect(self._refresh_enabled)
        self.labels_edit.setToolTip(
            "One theme per line. These become the codes in your project, so name\n"
            "them the way you want them to read in a findings table.")

        # Start from a ready-made set (or write your own below).
        self.pack_pick = QComboBox()
        self.pack_pick.setToolTip("Ready-made sets of themes for common survey topics.")
        self.pack_pick.currentIndexChanged.connect(self._update_pack_preview)
        self.pack_button = QPushButton("Use this set")
        self.pack_button.setProperty("main", True)    # the one filled button on this step
        self.pack_button.clicked.connect(self._load_label_pack)
        self.pack_button.setToolTip("Put these themes in the box below. You can still edit them.")
        self.pack_preview = WrappingLabel("")

        self.codebook_button = QPushButton("Use the codes already in my project")
        self.codebook_button.clicked.connect(self._labels_from_codebook)
        self.codebook_button.setToolTip(
            "Puts the code names from the open project in the box below, so a new run\n"
            "codes against the codes you have been building by hand.")
        self.codebook_note = WrappingLabel("")

        self.labels_summary = WrappingLabel("")

        # The rarely used extra, folded away.
        self.per_question = QPlainTextEdit()
        self.per_question.setPlaceholderText(
            "One question per line, then its themes:\n"
            "What was hardest? :: Cost | Belonging | Coursework")
        self.per_question.setMaximumHeight(110)
        self.per_question.setToolTip(
            "Optional. Give one question its own themes, one per line, as\n"
            "Question :: Theme A | Theme B")
        self.themes_more = MoreOptions("More options")
        self.themes_more.add_row("Different themes for one question", self.per_question)

        pack_row = QHBoxLayout()
        pack_row.addWidget(QLabel("Start from a ready-made set"))
        pack_row.addWidget(self.pack_pick, 1)
        pack_row.addWidget(self.pack_button)

        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.addWidget(WrappingLabel(
            "<i>Your themes are the topics you want to find in the answers. Write your "
            "own, or start from a ready-made set and change it. QualSafe suggests which "
            "answers fit each theme, and you check them.</i>"))
        layout.addLayout(pack_row)
        layout.addWidget(self.pack_preview)
        layout.addWidget(self.codebook_button, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.codebook_note)
        layout.addWidget(QLabel("Your themes (one per line)"))
        layout.addWidget(self.labels_edit, 1)
        layout.addWidget(self.labels_summary)
        layout.addWidget(self.themes_more)
        self._service.project_changed.connect(lambda _p: self._refresh_codebook_button())
        self._service.store_changed.connect(self._refresh_codebook_button)
        self._refresh_codebook_button()
        return tab

    def _build_run_tab(self) -> QWidget:
        self.engine = QComboBox()
        self.engine.addItem("Built in: fast, works offline (the default)", "transformer")
        self.engine.addItem("Local language model (Ollama): slower, gives a reason for each suggestion",
                            "llm")
        self.engine.setToolTip(
            "The built-in method needs no extra setup. The local language model runs on "
            "this computer through Ollama (nothing leaves it) and adds a reason for each "
            "suggestion. If Ollama is not available, the run uses the built-in method.")
        self.engine.currentIndexChanged.connect(self._on_engine_changed)

        self.llm_model = QLineEdit("llama3.2:3b")
        self.llm_temperature = QDoubleSpinBox()
        self.llm_temperature.setRange(0.0, 1.0)
        self.llm_temperature.setSingleStep(0.05)
        self.llm_temperature.setValue(0.1)
        self.llm_seed = QSpinBox()
        self.llm_seed.setRange(0, 10_000_000)
        self.llm_seed.setValue(42)
        self.llm_model.setToolTip("The Ollama model name, for example llama3.2:3b.")
        self.llm_temperature.setToolTip(
            "Lower is more consistent. 0.1 is a sensible default for coding.")
        self.llm_seed.setToolTip(
            "A fixed number makes a run repeatable, which matters if you are\n"
            "going to report the result.")

        self.llm_row = QWidget()
        llm_layout = QHBoxLayout(self.llm_row)
        llm_layout.setContentsMargins(0, 0, 0, 0)
        llm_layout.addWidget(QLabel("Model"))
        llm_layout.addWidget(self.llm_model, 1)
        llm_layout.addWidget(QLabel("Temperature"))
        llm_layout.addWidget(self.llm_temperature)
        llm_layout.addWidget(QLabel("Seed"))
        llm_layout.addWidget(self.llm_seed)
        self.llm_row.setVisible(False)

        self.use_sentiment = QCheckBox("Rate each answer as positive or negative")
        self.use_sentiment.setChecked(True)
        self.use_sentiment.setToolTip("Adds a positive or negative reading to every answer. Quick.")
        self.use_zero_shot = QCheckBox("Suggest a code for every answer (the main step)")
        self.use_zero_shot.setChecked(True)
        self.use_zero_shot.setToolTip(
            "The main step: suggest which of your themes fits each answer.\n"
            "Turning this off leaves you with groups of similar answers but no codes.")
        self.use_question_theme = QCheckBox("Also find groups of similar answers within each question")
        self.use_question_theme.setChecked(True)
        self.use_question_theme.setToolTip(
            "Looks for themes inside each question separately, without using your\n"
            "list. Useful for spotting what you did not expect.")
        self.use_question_zero_shot = QCheckBox("Suggest codes per question, using that question's own themes (slower)")
        self.use_question_zero_shot.setToolTip(
            "Codes each question against its own theme list. Roughly doubles the run time.")
        self.save_store = QCheckBox("Also save a project file (.qnw)")
        self.save_store.setChecked(True)
        self.save_store.setToolTip(
            "One file holding the answers, your codes and the suggestions: reopen it here\n"
            "or send it to a colleague. The spreadsheet outputs are written either way.")
        for box in (self.use_sentiment, self.use_zero_shot, self.use_question_theme,
                    self.use_question_zero_shot):
            box.toggled.connect(self._refresh_estimate)

        include = QWidget()
        include_layout = QVBoxLayout(include)
        include_layout.setContentsMargins(0, 0, 0, 0)
        for box in (self.use_sentiment, self.use_zero_shot,
                    self.use_question_theme, self.use_question_zero_shot,
                    self.save_store):
            include_layout.addWidget(box)

        self.strict_enabled = QCheckBox("Flag suggestions I should check myself")
        self.strict_top1 = QDoubleSpinBox()
        self.strict_top1.setRange(0.0, 1.0)
        self.strict_top1.setSingleStep(0.05)
        self.strict_top1.setValue(0.55)
        self.strict_margin = QDoubleSpinBox()
        self.strict_margin.setRange(0.0, 0.5)
        self.strict_margin.setSingleStep(0.01)
        self.strict_margin.setValue(0.10)
        self.strict_enabled.setToolTip(
            "Rather than always guessing, mark a suggestion Needs your review when the\n"
            "method is not confident, so you can look at it yourself.")
        self.strict_top1.setToolTip("How confident the best theme must be before it is accepted.")
        self.strict_margin.setToolTip(
            "How far ahead of the second-best theme the best one must be.\n"
            "Stops a near tie being reported as a decision.")

        flag = QWidget()
        flag_layout = QVBoxLayout(flag)
        flag_layout.setContentsMargins(0, 0, 0, 0)
        flag_layout.addWidget(self.strict_enabled)
        threshold_row = QHBoxLayout()
        threshold_row.addWidget(QLabel("Confidence needed"))
        threshold_row.addWidget(self.strict_top1)
        threshold_row.addWidget(QLabel("Lead over the next theme"))
        threshold_row.addWidget(self.strict_margin)
        threshold_row.addStretch(1)
        flag_layout.addLayout(threshold_row)
        flag_layout.addWidget(WrappingLabel(
            "<i>The two methods score differently, so each keeps its own limits. "
            "You are editing the limits for the method chosen above.</i>"))

        self.estimate_label = WrappingLabel("")
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setVisible(False)
        self.progress.setToolTip("Progress through the stages of the run.")
        self.progress_label = WrappingLabel("")
        self.progress_label.setVisible(False)

        self.preview_button = QPushButton(f"Quick preview ({PREVIEW_ROWS} answers)")
        self.preview_button.clicked.connect(lambda: self._run(preview=True))
        self.preview_button.setToolTip(
            "A fast look at what the results will contain. Never saved as a project and\n"
            "never touches the project you have open.")
        self.run_button = QPushButton("Run the analysis")
        self.run_button.setProperty("main", True)    # the one filled button here
        self.run_button.clicked.connect(lambda: self._run(preview=False))
        self.run_button.setToolTip(
            "Suggest codes for every answer and write a project. Runs in the background:\n"
            "the window stays usable.")

        run_row = QHBoxLayout()
        run_row.addWidget(self.preview_button)
        run_row.addWidget(self.run_button)
        run_row.addStretch(1)

        self.summary_label = WrappingLabel("")
        self.blockers_label = WrappingLabel("")

        # -- how to code: the choice, with when to use each --
        self.choice_title = QLabel("<b>How do you want to code the answers?</b>")
        self.choice_group = QButtonGroup(self)
        self.choice_buttons: Dict[str, QRadioButton] = {}
        choices = QWidget()
        choices_layout = QVBoxLayout(choices)
        choices_layout.setContentsMargins(0, 0, 0, 0)
        choices_layout.setSpacing(2)
        for key, title, when, available, why_not in CODING_CHOICES:
            radio = QRadioButton(title)
            radio.setEnabled(available)
            radio.setChecked(key == "suggest")
            radio.toggled.connect(self._on_choice_changed)
            self.choice_group.addButton(radio)
            self.choice_buttons[key] = radio
            choices_layout.addWidget(radio)
            note = when if available else f"{when} <b>{why_not}</b>"
            detail = WrappingLabel(f"<i>{note}</i>")
            detail.setContentsMargins(24, 0, 0, 6)
            choices_layout.addWidget(detail)

        # -- everything about the one available method, folded away --
        self.code_more = MoreOptions("More options")
        self.code_more.add_row("Method", self.engine)
        self.code_more.add_row("Local language model", self.llm_row)
        self.code_more.add_row("What to include", include)
        self.code_more.add_row("Check suggestions", flag)

        # The written codebook is its own short path; it takes the place of these.
        self.written = WrittenCodebookView(self._service, output_root=self._output_root)
        self.written.setVisible(False)
        self.written.back_requested.connect(lambda: self.choice_buttons["suggest"].setChecked(True))
        self.written.status.connect(self.status)
        self.hand = HandCodingView(self._service, output_root=self._output_root)
        self.hand.setVisible(False)
        self.hand.back_requested.connect(lambda: self.choice_buttons["suggest"].setChecked(True))
        self.hand.status.connect(self.status)
        run_holder = QWidget()
        run_holder.setLayout(run_row)
        run_row.setContentsMargins(0, 0, 0, 0)
        self._choice_parts = [self.choice_title, choices]
        self._suggest_parts = [self.estimate_label, self.blockers_label, run_holder,
                               self.progress_label, self.progress, self.code_more,
                               self.summary_label]

        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.addWidget(self.choice_title)
        layout.addWidget(choices)
        layout.addWidget(self.estimate_label)
        layout.addWidget(self.blockers_label)
        layout.addWidget(run_holder)
        layout.addWidget(self.progress_label)
        layout.addWidget(self.progress)
        layout.addWidget(self.code_more)
        layout.addWidget(self.summary_label, 1)
        layout.addWidget(self.written, 1)
        layout.addWidget(self.hand, 1)
        return tab

    # -- progress (core/ux/progress.py) --------------------------------------
    def progress_state(self) -> dict:
        """Where this screen is, as paths, column names and the theme list.

        Never the data: no row, answer or preview text, and never the privacy
        confirmation. The gate is asked again whenever the file is loaded.
        """
        state = {
            "ingestion_mode": self.mode.currentData() or "",
            "text_column": self.text_column.currentData() or "",
            "question_column": self.question_column.currentData() or "",
            "id_column": self.id_column.currentData() or "",
            "question_text_manual": self.question_manual.text(),
            "theme_labels_text": self.labels_edit.toPlainText(),
            "question_label_overrides_text": self.per_question.toPlainText(),
            "text_columns": _checked(self.text_columns),
            "descriptor_columns": _checked(self.descriptors),
        }
        if self._loaded_from:
            state["resume_path"] = self._loaded_from
        state["code_choice"] = self.code_choice()
        state["code_settings"] = self._code_settings()
        if self.code_choice() == "hand" and self.hand.current_answer_id():
            state["hand_answer"] = self.hand.current_answer_id()      # an id, never the answer
        return state

    def restore_progress(self, state: dict) -> bool:
        """Put the saved choices back. Reloading the file is a load, so the
        privacy gate comes back unchecked and has to be confirmed again.
        Returns False if the saved file is gone (the theme list is still restored)."""
        if isinstance(state.get("code_settings"), dict):
            self._apply_code_settings(state["code_settings"])
        if state.get("hand_answer"):
            self.hand.restore_answer(state["hand_answer"])
        if state.get("code_choice") in ("codebook", "hand") and state["code_choice"] in self.choice_buttons:
            self.choice_buttons[state["code_choice"]].setChecked(True)
        self.labels_edit.setPlainText(str(state.get("theme_labels_text", "")))
        self.per_question.setPlainText(str(state.get("question_label_overrides_text", "")))
        path = str(state.get("resume_path", ""))
        if not path or not Path(path).exists():
            return not path
        self._load(Path(path))
        if self._loaded_from != path:
            return False
        index = self.mode.findData(state.get("ingestion_mode"))
        if index >= 0:
            self.mode.setCurrentIndex(index)
        for combo, key in ((self.text_column, "text_column"),
                           (self.question_column, "question_column"),
                           (self.id_column, "id_column")):
            at = combo.findData(state.get(key, ""))
            if at >= 0:
                combo.setCurrentIndex(at)
        self.question_manual.setText(str(state.get("question_text_manual", "")))
        _set_checked(self.text_columns, state.get("text_columns") or [])
        _set_checked(self.descriptors, state.get("descriptor_columns") or [])
        self._clear_suggestion()
        self._refresh_enabled()
        return True

    def reset_session(self) -> None:
        """Back to a fresh screen: no file, no column choices, no theme list, and the
        privacy gate unchecked. Files on disk are not touched."""
        self._frame = None
        self._loaded_from = ""
        self._confirmed_for = ""
        self.pii_confirm.blockSignals(True)
        self.pii_confirm.setChecked(False)
        self.pii_confirm.blockSignals(False)
        self.file_label.setText(_EMPTY_FILE_TEXT)
        self._clear_suggestion()
        self.pii_summary.setText("")
        self.preview_model.set_frame(pd.DataFrame())
        self._populate_columns(pd.DataFrame())
        self.mode.setCurrentIndex(0)
        self.question_manual.clear()
        self.labels_edit.clear()
        self.per_question.clear()
        self._reset_code_settings()
        self._refresh_enabled()

    # -- loading data --------------------------------------------------------
    def _load_file(self) -> None:
        pattern = " ".join(f"*{s}" for s in SUPPORTED_TABLE_SUFFIXES)
        path, _filter = QFileDialog.getOpenFileName(
            self, "Open a data file", "", f"Data files ({pattern});;All files (*)")
        if path:
            self._load(Path(path))

    def _load_sample(self) -> None:
        sample = Path(__file__).resolve().parents[2] / "data" / "sample_survey_education.csv"
        if not sample.exists():
            QMessageBox.warning(self, "Sample missing",
                                f"Could not find {sample}.")
            return
        self._load(sample)

    def _load(self, path: Path) -> None:
        try:
            from core.run_config import load_table_with_note

            frame, encoding_note = load_table_with_note(path)
        except Exception as exc:  # noqa: BLE001 - a bad file is user input
            QMessageBox.critical(self, "Could not read that file", str(exc))
            return
        if encoding_note:
            # The web build warns here too. A fallback nobody is told about is
            # the silent-mojibake case core/encodings.py exists to prevent, and
            # both builds have to qualify a file the same way.
            QMessageBox.information(self, "About this file", encoding_note)
        if frame.empty:
            QMessageBox.warning(self, "Empty file", "That file has no rows.")
            return

        self._frame = frame
        self._loaded_from = str(path)
        # Re-arm the gate: attestation is per dataset and is never persisted.
        self._confirmed_for = ""
        self.pii_confirm.blockSignals(True)
        self.pii_confirm.setChecked(False)
        self.pii_confirm.blockSignals(False)

        self.file_label.setText(
            f"<b>{_escape(path.name)}</b> — {len(frame):,} row(s), "
            f"{len(frame.columns)} column(s)")
        self.preview_model.set_frame(frame.head(_PREVIEW_ROWS_SHOWN))
        self._run_pii_scan(frame)
        self._populate_columns(frame)
        self._offer_suggestion(frame)
        self._refresh_enabled()
        self.status.emit(f"Loaded {path.name}.")

    def _offer_suggestion(self, frame: pd.DataFrame) -> None:
        """Say where the answers look to be, and wait for a click.

        Only the layout (long or wide) is set for you. The answers column is never
        chosen without the person pressing the button, because a wrong pick that
        runs is worse than one more click; a sample of what is in the column is
        shown so a wrong suggestion is easy to spot."""
        from core.ux.columns import sample_of, suggest_columns

        self._suggestion = suggest_columns(frame)
        if self._suggestion is None:
            self._clear_suggestion()
            return
        index = self.mode.findData(self._suggestion.shape)
        if index >= 0:
            self.mode.setCurrentIndex(index)
        lines = [f"• {_escape(line)}" for line in self._suggestion.describe()]
        example = sample_of(frame, self._suggestion.answers[0])
        if example:
            lines.append(f"<i>For example: “{_escape(example)}”</i>")
        self.suggestion_label.setText("<b>QualSafe thinks:</b><br>" + "<br>".join(lines))
        self.suggestion_label.show()
        self.suggestion_button.show()

    def _clear_suggestion(self) -> None:
        self._suggestion = None
        self.suggestion_label.hide()
        self.suggestion_button.hide()

    def _apply_suggestion(self) -> None:
        """The person agreed: fill in the columns that were suggested."""
        suggestion = self._suggestion
        if suggestion is None:
            return
        if suggestion.shape == "wide":
            _set_checked(self.text_columns, list(suggestion.answers))
        else:
            at = self.text_column.findData(suggestion.answers[0])
            if at >= 0:
                self.text_column.setCurrentIndex(at)
            at = self.question_column.findData(suggestion.question)
            if suggestion.question and at >= 0:
                self.question_column.setCurrentIndex(at)
        at = self.id_column.findData(suggestion.respondent)
        if suggestion.respondent and at >= 0:
            self.id_column.setCurrentIndex(at)
        self.suggestion_button.hide()
        self.suggestion_label.setText(
            "<b>Using:</b><br>" + "<br>".join(f"• {_escape(line)}" for line in suggestion.describe()))
        self._refresh_enabled()

    def _run_pii_scan(self, frame: pd.DataFrame) -> None:
        from privacy.scan import findings_headline, scan_frame

        findings = scan_frame(frame)
        parts = [f"<b>{_escape(findings_headline(findings))}</b>"]
        for finding in findings[:8]:
            parts.append(
                f"• {_escape(str(finding['signal']))} in "
                f"<code>{_escape(str(finding['column']))}</code> — "
                f"{finding['n_hits']} hit(s), e.g. "
                f"{_escape(str(finding['example_masked']))}")
        if len(findings) > 8:
            parts.append(f"• …and {len(findings) - 8} more signal(s)")
        self.pii_summary.setText("<br>".join(parts))

    def _populate_columns(self, frame: pd.DataFrame) -> None:
        columns = [str(c) for c in frame.columns]
        text_like = [c for c in columns
                     if frame[c].dtype == object or str(frame[c].dtype) == "string"]

        # Every mapping combo starts blank, including the text column. Guessing
        # it looks helpful and is not: the first text-like column in a long-form
        # survey is often the *question*, so an auto-pick would quietly analyse
        # the prompts instead of the answers, and the run would succeed. A
        # wrong default that runs is worse than one more click.
        for combo, options, blank in (
            (self.text_column, text_like or columns, True),
            (self.question_column, columns, True),
            (self.id_column, columns, True),
        ):
            combo.blockSignals(True)
            combo.clear()
            if blank:
                combo.addItem(
                    "(choose…)" if combo is self.text_column else "(none)", "")
            for name in options:
                combo.addItem(name, name)
            combo.blockSignals(False)

        for widget, options in ((self.text_columns, text_like or columns),
                                (self.descriptors, columns)):
            widget.blockSignals(True)
            widget.clear()
            for name in options:
                item = QListWidgetItem(name)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Unchecked)
                widget.addItem(item)
            widget.blockSignals(False)
        self._on_mode_changed()

    def _on_mode_changed(self) -> None:
        self._sync_mode_widgets()
        self._refresh_enabled()

    def _sync_mode_widgets(self) -> None:
        """Show the answers control that fits the layout (one column, or a list)."""
        wide = self.mode.currentData() == "wide"
        self.text_column.setVisible(not wide)
        self.text_columns.setVisible(wide)
        self.answers_caption.setText(
            "Question columns (each one a question)" if wide else "Answers are in column")
        self.text_column.setEnabled(not wide)
        self.question_column.setEnabled(not wide)
        self.question_manual.setEnabled(not wide)
        self.text_columns.setEnabled(wide)

    def _on_pii_confirmed(self, checked: bool) -> None:
        self._confirmed_for = self._loaded_from if checked else ""
        self._refresh_enabled()

    # -- themes --------------------------------------------------------------
    def showEvent(self, event) -> None:  # noqa: D102 - Qt override
        super().showEvent(event)
        if self.pack_pick.count() == 0:
            self._populate_label_packs()

    def _populate_label_packs(self) -> None:
        packs = label_packs()
        self.pack_pick.clear()
        for name, labels in packs.items():
            self.pack_pick.addItem(name, labels)
        self.pack_pick.setEnabled(bool(packs))
        self.pack_button.setEnabled(bool(packs))
        self._update_pack_preview()

    def _update_pack_preview(self) -> None:
        """Show what is in the chosen set before it is used."""
        labels = self.pack_pick.currentData() or []
        if not labels:
            self.pack_preview.setText("")
            return
        shown = ", ".join(_escape(str(x)) for x in labels[:5])
        more = f" and {len(labels) - 5} more" if len(labels) > 5 else ""
        self.pack_preview.setText(f"<i>{len(labels)} themes: {shown}{more}.</i>")

    def _load_label_pack(self) -> None:
        labels = self.pack_pick.currentData()
        if labels:
            self.labels_edit.setPlainText("\n".join(labels))

    def _refresh_codebook_button(self) -> None:
        """Offer the project's codes only when there are some, and say why not otherwise."""
        try:
            names = self._service.code_names() if self._service.is_open else []
        except Exception:  # noqa: BLE001 - a button's state must never break the screen
            names = []
        self.codebook_button.setEnabled(bool(names))
        if names:
            self.codebook_note.setText(f"<i>The open project has {len(names)} codes.</i>")
        elif self._service.is_open:
            self.codebook_note.setText("<i>The open project has no codes yet.</i>")
        else:
            self.codebook_note.setText("<i>No project is open.</i>")

    def _labels_from_codebook(self) -> None:
        names = sorted(self._service.code_names()) if self._service.is_open else []
        if not names:
            self._refresh_codebook_button()     # nothing to use; the note says why
            return
        self.labels_edit.setPlainText("\n".join(names))

    # -- settings ------------------------------------------------------------
    def _checked(self, widget: QListWidget) -> List[str]:
        return [widget.item(i).text() for i in range(widget.count())
                if widget.item(i).checkState() == Qt.CheckState.Checked]

    def settings(self) -> RunSettings:
        """The current choices, as the plain dataclass the config builder takes."""
        engine = self.engine.currentData()
        strict_top1 = float(self.strict_top1.value())
        strict_margin = float(self.strict_margin.value())
        models = dict(DEFAULT_MODELS)
        if self.model_provider is not None:
            models.update({k: v for k, v in self.model_provider().items() if v})
        return RunSettings(
            embedding_model=models["embedding"],
            sentiment_model=models["sentiment"],
            zero_shot_model=models["zero-shot"],
            ingestion_mode=self.mode.currentData() or "long",
            text_column=self.text_column.currentData() or "",
            text_columns=self._checked(self.text_columns),
            question_column=self.question_column.currentData() or "",
            question_text_manual=self.question_manual.text(),
            id_column=self.id_column.currentData() or "",
            descriptor_columns=self._checked(self.descriptors),
            labels_text=self.labels_edit.toPlainText(),
            per_question_labels_text=self.per_question.toPlainText(),
            engine_type=engine,
            llm_model=self.llm_model.text().strip() or "llama3.2:3b",
            llm_temperature=float(self.llm_temperature.value()),
            llm_seed=int(self.llm_seed.value()),
            use_sentiment=self.use_sentiment.isChecked(),
            use_zero_shot=self.use_zero_shot.isChecked(),
            use_question_theme=self.use_question_theme.isChecked(),
            use_question_zero_shot=self.use_question_zero_shot.isChecked(),
            save_project_store=self.save_store.isChecked(),
            use_strict_global=self.strict_enabled.isChecked(),
            # The active engine's pair is what the analyst just edited; the other
            # engine keeps its default, because the two scales are not comparable.
            strict_top1_transformer=strict_top1 if engine == "transformer" else 0.55,
            strict_margin_transformer=strict_margin if engine == "transformer" else 0.10,
            strict_top1_llm=strict_top1 if engine == "llm" else 0.70,
            strict_margin_llm=strict_margin if engine == "llm" else 0.10,
        )

    def code_choice(self) -> str:
        """Which way of coding is selected: "suggest", "codebook" (or "hand" once it exists)."""
        for key, radio in self.choice_buttons.items():
            if radio.isChecked():
                return key
        return "suggest"

    def _on_choice_changed(self, _checked: bool = False) -> None:
        if not hasattr(self, "written"):          # still being built
            return
        choice = self.code_choice()
        own_screen = choice in ("codebook", "hand")       # these take the place of the choices
        for part in self._choice_parts + self._suggest_parts:
            part.setVisible(not own_screen)
        self.written.setVisible(choice == "codebook")
        self.hand.setVisible(choice == "hand")
        if choice == "codebook":
            self.written.go_stage("codebook")
        elif choice == "hand":
            self._push_source()
            self.hand.begin()
        self._refresh_enabled()

    def _code_settings(self) -> dict:
        """The run's options as small values (never any text from the answers)."""
        return {
            "engine": self.engine.currentData() or "transformer",
            "sentiment": self.use_sentiment.isChecked(),
            "suggest": self.use_zero_shot.isChecked(),
            "groups": self.use_question_theme.isChecked(),
            "per_question": self.use_question_zero_shot.isChecked(),
            "save_project": self.save_store.isChecked(),
            "flag": self.strict_enabled.isChecked(),
            "confidence": round(self.strict_top1.value(), 4),
            "lead": round(self.strict_margin.value(), 4),
            "model": self.llm_model.text(),
            "temperature": round(self.llm_temperature.value(), 4),
            "seed": self.llm_seed.value(),
        }

    def _apply_code_settings(self, saved: dict) -> None:
        at = self.engine.findData(saved.get("engine"))
        if at >= 0:
            self.engine.setCurrentIndex(at)
        for box, key in ((self.use_sentiment, "sentiment"), (self.use_zero_shot, "suggest"),
                         (self.use_question_theme, "groups"),
                         (self.use_question_zero_shot, "per_question"),
                         (self.save_store, "save_project"), (self.strict_enabled, "flag")):
            if isinstance(saved.get(key), bool):
                box.setChecked(saved[key])
        for spin, key in ((self.strict_top1, "confidence"), (self.strict_margin, "lead"),
                          (self.llm_temperature, "temperature")):
            if isinstance(saved.get(key), (int, float)):
                spin.setValue(float(saved[key]))
        if isinstance(saved.get("seed"), int):
            self.llm_seed.setValue(saved["seed"])
        if isinstance(saved.get("model"), str) and saved["model"]:
            self.llm_model.setText(saved["model"])

    def _reset_code_settings(self) -> None:
        self.choice_buttons["suggest"].setChecked(True)
        self.engine.setCurrentIndex(0)
        for box, on in ((self.use_sentiment, True), (self.use_zero_shot, True),
                        (self.use_question_theme, True), (self.use_question_zero_shot, False),
                        (self.save_store, True), (self.strict_enabled, False)):
            box.setChecked(on)
        self.strict_top1.setValue(0.55)
        self.strict_margin.setValue(0.10)
        self.llm_model.setText("llama3.2:3b")
        self.llm_temperature.setValue(0.1)
        self.llm_seed.setValue(42)
        self.code_more.set_expanded(False)

    def _on_engine_changed(self) -> None:
        llm = self.engine.currentData() == "llm"
        self.llm_row.setVisible(llm)
        # Reset to the active engine's documented defaults rather than carrying
        # a transformer threshold onto an LLM score, which measures a different
        # thing entirely.
        self.strict_top1.setValue(0.70 if llm else 0.55)
        self.strict_margin.setValue(0.10)

    def _refresh_estimate(self) -> None:
        if self._frame is None:
            self.estimate_label.setText("")
            return
        # The label count is the dominant term: zero-shot runs the NLI model
        # once per (response, label), so twelve labels cost twice six.
        estimate = estimate_runtime_minutes(
            len(self._frame),
            use_sentiment=self.use_sentiment.isChecked(),
            use_zero_shot=self.use_zero_shot.isChecked(),
            use_question_theme=self.use_question_theme.isChecked(),
            use_question_zero_shot=self.use_question_zero_shot.isChecked(),
            n_labels=len(parse_labels(self.labels_edit.toPlainText())) or 6)
        self.estimate_label.setText(
            f"<i>Rough estimate: {estimate['cpu']} on this computer's processor, "
            f"{estimate['gpu']} with a graphics card (a guess, not measured). More themes "
            "take proportionally longer.</i>")

    def blockers(self) -> List[str]:
        """What still stands between here and a run. Shown, not guessed at."""
        problems = []
        if self._frame is None:
            problems.append("load a data file")
        elif not mapping_is_ready(self._frame, self.settings()):
            problems.append("choose the text column (or question columns, in "
                            "wide mode)")
        if self._frame is not None and self._confirmed_for != self._loaded_from:
            problems.append("confirm the review of this dataset above")
        if not parse_labels(self.labels_edit.toPlainText()):
            problems.append("write at least one theme on the Themes tab")

        # The one blocker that used to announce itself only after the run had
        # started. Each model was checked when its own stage first reached it,
        # so a partial download failed once per model, each time after more
        # waiting. It is knowable here, before anything runs, and it is cheap:
        # a directory listing of the model cache.
        # A fresh install has no analysis engine; a run would only end in a module error. Say what to do.
        from core import engine_install

        if not engine_install.installed():
            problems.append("install the analysis engine (Settings, then Models)")
        missing = self._missing_models()
        if missing:
            problems.append(f"{missing} (Models tab)")
        return problems

    def _missing_models(self) -> str:
        """What the configured run needs and this machine has not got.

        Advisory: a cache that cannot be read reports nothing, because this is
        here to spare somebody a wasted wait, not to become a new way for a run
        to be refused.
        """
        from core.model_readiness import describe_missing

        try:
            return describe_missing(self.settings()) or ""
        except Exception:  # noqa: BLE001 - never let a check block the screen
            return ""

    def _refresh_enabled(self) -> None:
        problems = self.blockers()
        ready = not problems and not self._running
        self.run_button.setEnabled(ready)
        self.preview_button.setEnabled(ready)
        self.blockers_label.setText(
            "" if not problems else
            "<i>Before running: " + "; ".join(_escape(p) for p in problems) + ".</i>")
        labels = parse_labels(self.labels_edit.toPlainText())
        self.labels_summary.setText(
            f"<i>{len(labels)} theme{'s' if len(labels) != 1 else ''}.</i>" if labels else
            "<i>No themes yet. Write one per line, or start from a ready-made set.</i>")
        self._refresh_estimate()
        self._push_source()

    def _push_source(self) -> None:
        """Hand the written-codebook screen the answers, but only once the privacy check
        for this file has been confirmed (the gate is asked again on every load)."""
        if not hasattr(self, "written"):
            return
        ready = self._frame is not None and self._confirmed_for == self._loaded_from
        args = (self._frame if ready else None,
                self.text_column.currentData() or "" if ready else "",
                self.id_column.currentData() or "" if ready else "")
        self.written.set_source(*args)
        self.hand.set_source(*args)
        if ready and self.code_choice() == "hand" and not self.hand.is_ready():
            self.hand.begin()          # the privacy check was just confirmed

    # -- running -------------------------------------------------------------
    def _output_root(self) -> Path:
        root = Path(__file__).resolve().parents[2] / _OUTPUT_DIR_NAME
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _run(self, *, preview: bool) -> None:
        """Start a pipeline run on a worker thread.

        `run_pipeline` opens its own `Project` to write the `.qnw`, on the worker
        thread, because a `sqlite3` connection belongs to the thread that made
        it. The service reconnects afterwards so the other screens see the run's
        coding instead of a stale snapshot.
        """
        if self._frame is None or self._running:
            return
        prefix = "preview_" if preview else "run_"
        run_dir = self._output_root() / (prefix + datetime.now().strftime("%Y%m%d_%H%M%S"))
        try:
            config = build_config(self._frame, self.settings(), run_dir,
                                  preview=preview)
            write_config_snapshot(config, run_dir)
        except ValueError as exc:
            QMessageBox.warning(self, "Could not start the run", str(exc))
            return

        self._running = True
        self._refresh_enabled()
        self.progress.setValue(0)
        self.progress.setVisible(True)
        self.progress_label.setVisible(True)
        self.progress_label.setText("<i>Starting…</i>")
        self.summary_label.setText("")
        self.status.emit("Preview run started…" if preview else "Survey analysis started…")

        run_task(
            _run_pipeline, config,
            wants_progress=True, reads_store=True,
            on_progress=self._on_progress,
            on_finished=lambda summary: self._on_finished(summary, run_dir, preview),
            on_failed=self._on_failed,
            on_done=self._on_run_done,
        )

    def _on_progress(self, fraction: float, message: str) -> None:
        percent = int(max(0.0, min(1.0, fraction)) * 100)
        self.progress.setValue(percent)
        self.progress_label.setText(f"<i>{_escape(message)}  ·  {percent}%</i>")

    def _on_run_done(self) -> None:
        self._running = False
        self.progress.setVisible(False)
        self.progress_label.setVisible(False)
        self._refresh_enabled()

    def _on_finished(self, summary: Dict[str, Any], run_dir: Path,
                     preview: bool) -> None:
        parts = [
            "<b>Preview complete.</b> " if preview else "<b>Run complete.</b> ",
            f"{summary.get('total_responses', '—')} response(s), ",
            f"{summary.get('clusters_found', '—')} group(s) of similar answers, ",
            f"{summary.get('questions_coded', '—')}/"
            f"{summary.get('questions_total', '—')} question(s) coded, ",
            f"{summary.get('possible_outliers', 0)} possible outlier(s).",
        ]
        skipped = summary.get("questions_skipped") or []
        if skipped:
            parts.append("<br>" + warning_span(
                f"{len(skipped)} question(s) had no labels configured and "
                "were skipped.", bold=False))
        if preview:
            parts.append(
                f"<br><i>This was a preview of the first {PREVIEW_ROWS} rows. "
                "It was not saved as a project.</i>")
        parts.append(f"<br>Output: <code>{_escape(str(run_dir))}</code>")
        self.summary_label.setText("".join(parts))

        store = summary.get("project_store")
        if store and not preview:
            self.project_written.emit(str(store))
            self.status.emit(f"Run complete — project written to {store}.")
        else:
            self.status.emit("Preview complete." if preview else "Run complete.")

    def _on_failed(self, message: str, traceback_text: str) -> None:
        # A missing model is an ordinary, expected state — downloads are a
        # separate, explicit step by design — so it gets an explanation rather
        # than a crash report.
        if "not in your local cache" in message or "ModelNotDownloaded" in traceback_text:
            QMessageBox.information(self, "A model needs downloading first", message)
        else:
            QMessageBox.critical(self, "The run failed", message)
        self.summary_label.setText(warning_span(_escape(message), bold=False))
        self.status.emit("Run failed.")


def _run_pipeline(config: Dict[str, Any], progress_callback=None) -> Dict[str, Any]:
    """Worker body. Module-level, so it demonstrably holds no widget.

    `analyze_survey` is imported here rather than at module scope so that
    importing this view does not drag in the transformer stack — the offline
    flags are armed long before this runs, but a lazy import also keeps the app's
    start-up fast and the test suite torch-free.
    """
    from analyze_survey import run_pipeline

    return run_pipeline(config, progress_callback=progress_callback)


def _escape(text: str) -> str:
    import html

    return html.escape(str(text))
