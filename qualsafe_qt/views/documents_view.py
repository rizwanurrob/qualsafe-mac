"""
Documents: the corpus list, the reader, and drag-to-select coding.

The Qt counterpart of `app/documents_page.py`, and the screen the fork exists
for. The Streamlit page splits into three tabs -- Library, Read, Code -- because
Streamlit reruns the whole script on every interaction and cannot hold three
panes in a useful relationship. Here they are one workspace: the corpus on the
left, the document in the middle, the codebook on the right, and coding happens
by dragging across the text.

What changed, and why it matters:

* **Selection is real.** No sentence ticking, no paste-and-locate. Drag, then
  press Enter (or a number key) to code what you selected. Paste-a-passage
  survives as a convenience in the Streamlit build; here it would be a slower
  way to do the thing the mouse already does.
* **Number keys apply codes.** Coding a transcript is hundreds of repetitions of
  "select, choose code". Binding the first nine codes to 1-9 turns each one into
  a drag and a keystroke.
* **Ctrl+Z works.** See `qualsafe_qt/commands.py`.

Per `qualsafe_qt/__init__`, this module imports only `core/`, `qualsafe_qt.*`,
and Qt.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QAction, QKeySequence, QUndoStack
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QFileDialog, QFormLayout, QFrame, QGroupBox,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMessageBox, QPushButton, QScrollArea, QSplitter, QStackedWidget, QTableWidget,
    QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from core import guide_mapping as gm
from core import speakers
from core.documents import coding_density, list_documents_in_folder, read_document
from privacy.scan import scan_frame, summarize_findings
from qualsafe_qt.colors import code_colors
from qualsafe_qt.theme import DEFAULT_CATEGORY_PALETTE
from qualsafe_qt.commands import ApplyCodesCommand, RemoveCodingCommand
from qualsafe_qt.theme import banner_style, banner_text
from qualsafe_qt.services.project_service import ProjectService
from qualsafe_qt.widgets.document_view import DocumentView
from qualsafe_qt.widgets.more_options import MoreOptions, count_controls
from qualsafe_qt.widgets.speaker_review import SpeakerReviewDialog
from qualsafe_qt.widgets.welcome import WelcomePanel

#: Codes bound to number keys. Nine is what fits on the home row of digits and
#: about as many as anyone holds in their head while reading.
_QUICK_CODE_KEYS = 9

#: The two steps of Interviews that this screen serves (core/ux/activities.py).
STEP_KEYS = ("add", "code")


class DocumentsView(QWidget):
    """Corpus list + reader + coding panel."""

    #: Something happened worth putting in the status bar.
    status = Signal(str)
    #: The person pressed Next; the shell moves its rail.
    step_requested = Signal(str)

    def __init__(self, service: ProjectService, undo_stack: QUndoStack,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._service = service
        self._undo = undo_stack
        self._source_id = ""
        self._theme_mode = "dark"
        self._palette_name = DEFAULT_CATEGORY_PALETTE
        #: Document lengths, cached by source_id. A document's text never
        #: changes after import, and reloading every document in the corpus to
        #: recompute a coverage percentage was the single most expensive thing
        #: in the coding loop -- see `_refresh_after_coding`.
        self._length_cache: Dict[str, int] = {}
        #: Spans for the document on screen, read once per refresh and shared by
        #: the reader, the coverage figure, and the corpus row.
        self._current_spans: List[Dict[str, Any]] = []

        self._step = STEP_KEYS[0]
        self._build_ui()
        self._install_shortcuts()
        self.set_step(STEP_KEYS[0])

        service.project_changed.connect(self._on_project_changed)
        # Coding fires `store_changed` on every application, so this is the hot
        # path: it must not rebuild the whole corpus list.
        service.store_changed.connect(self._refresh_after_coding)

    # -- construction --------------------------------------------------------
    def _build_ui(self) -> None:
        self.library = QTableWidget(0, 4)
        self.library.setHorizontalHeaderLabels(["Transcript", "Words", "Coded passages", "Share coded"])
        self.library.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.library.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.library.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.library.verticalHeader().setVisible(False)
        self.library.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch)
        for column in (1, 2, 3):
            self.library.horizontalHeader().setSectionResizeMode(
                column, QHeaderView.ResizeMode.ResizeToContents)
        self.library.itemSelectionChanged.connect(self._on_document_selected)
        self.library.setToolTip(
            "Every document in this project.\n"
            "Coded passages = how many passages you have coded; Share coded = how\n"
            "much of the text has at least one code.")

        self.import_button = QPushButton("Add transcripts from a folder…")
        self.import_button.clicked.connect(self._on_import_clicked)
        self.import_button.setToolTip(
            "Import .txt, .md, .docx, or .pdf files. Nothing leaves this machine.")

        self.add_note = QLabel("")
        self.add_note.setWordWrap(True)
        self.guide_note = QLabel("Matching an interview guide is in the web app for now.")
        self.guide_note.setWordWrap(True)
        self.speakers_button = QPushButton("Check who is speaking…")
        self.speakers_button.setEnabled(False)
        self.speakers_button.setToolTip(
            "Mark who is the interviewer and who is the participant in the selected "
            "transcript. QualSafe proposes; you confirm.")
        self.speakers_button.clicked.connect(lambda: self._review_speakers(self._source_id, force=True))
        self.speaker_label = QLabel("")
        self.speaker_label.setWordWrap(True)
        self.speaker_label.setVisible(False)
        self.next_button = QPushButton("Next: read and code")
        self.next_button.clicked.connect(lambda: self.go_step("code"))

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(6, 6, 6, 6)
        left_layout.addWidget(self.add_note)
        left_layout.addWidget(self.library, 1)
        left_layout.addWidget(self.import_button)
        left_layout.addWidget(self.speakers_button)
        left_layout.addWidget(self.guide_note)
        left_layout.addWidget(self.next_button)
        self._left = left

        # -- middle: the reader --
        self.reader = DocumentView()
        self.reader.selection_changed.connect(self._on_selection_changed)
        self.reader.span_activated.connect(self._on_span_activated)

        self.doc_title = QLabel("<i>No document selected.</i>")
        self.doc_title.setTextFormat(Qt.TextFormat.RichText)
        self.coverage_label = QLabel("")
        self.coverage_label.setStyleSheet("color: palette(mid);")

        self.warning_label = QLabel("")
        self.warning_label.setWordWrap(True)
        self.warning_label.setVisible(False)
        self.warning_label.setStyleSheet(banner_style("warning"))

        middle = QWidget()
        self._middle = middle
        middle_layout = QVBoxLayout(middle)
        middle_layout.setContentsMargins(6, 6, 6, 6)
        header = QHBoxLayout()
        header.addWidget(self.doc_title, 1)
        header.addWidget(self.coverage_label)
        middle_layout.addLayout(header)
        middle_layout.addWidget(self.speaker_label)
        middle_layout.addWidget(self.warning_label)
        middle_layout.addWidget(self.reader, 1)

        # -- right: the coding panel --
        right = self._build_coding_panel()
        self._right = right

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(middle)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 5)
        splitter.setStretchFactor(2, 2)
        splitter.setCollapsible(1, False)

        # A stack, not a hidden panel: with no project open the three-pane
        # layout renders as five empty boxes and no instruction, which is what
        # every new user used to meet (RELEASE_READINESS section 2.3). The
        # welcome occupies that space instead and is replaced the moment a
        # project opens, so nothing has to be dismissed.
        self.welcome = WelcomePanel()
        self._stack = QStackedWidget()
        self._stack.addWidget(self.welcome)
        self._stack.addWidget(splitter)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._stack)
        self._show_welcome_if_empty()

    def _show_welcome_if_empty(self) -> None:
        self._stack.setCurrentIndex(1 if self._service.is_open else 0)

    def _build_coding_panel(self) -> QWidget:
        self.selection_label = QLabel("<i>Select text in the document to code it.</i>")
        self.selection_label.setWordWrap(True)
        self.selection_label.setTextFormat(Qt.TextFormat.RichText)
        self.selection_label.setMinimumHeight(56)
        self.selection_label.setAlignment(
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.selection_label.setToolTip(
            "The passage you have selected, and the exact character positions\nthat will be stored with the coding.")

        self.code_list = QListWidget()
        self.code_list.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection)
        self.code_list.setToolTip(
            "Codes in this project. Select one or more, then Apply.\n"
            "The first nine are bound to keys 1-9.")
        self.code_list.itemDoubleClicked.connect(lambda _item: self._apply_selected_codes())

        self.new_code_edit = QLineEdit()
        self.new_code_edit.setPlaceholderText("…or type a new code and press Enter")
        self.new_code_edit.returnPressed.connect(self._apply_selected_codes)
        self.new_code_edit.setToolTip(
            "Type a code that does not exist yet and press Enter — it is\n"
            "created and applied to the selection in one step.")

        self.in_vivo_check = QCheckBox("Name the code after the passage (in-vivo)")
        self.in_vivo_check.setToolTip(
            "Create a code named after the selected text itself — in-vivo coding.")

        self.apply_button = QPushButton("Apply to selection")
        self.apply_button.setProperty("main", True)   # the one filled button here
        self.apply_button.clicked.connect(self._apply_selected_codes)
        self.apply_button.setEnabled(False)
        self.apply_button.setToolTip(
            "Apply the ticked codes to the selected passage.\n"
            "Shortcut: Enter. Or press 1-9 to apply a single code.")

        code_box = QGroupBox("Code the selection")
        code_layout = QVBoxLayout(code_box)
        code_layout.addWidget(self.selection_label)
        code_layout.addWidget(self.code_list, 1)
        code_layout.addWidget(self.new_code_edit)
        code_layout.addWidget(self.apply_button)

        # -- this analyst's codings in this document --
        self.my_codings = QListWidget()
        self.my_codings.setToolTip(
            "Your coded passages in this document. Click one to jump to it.")
        self.my_codings.itemClicked.connect(self._on_my_coding_clicked)
        self.remove_button = QPushButton("Remove selected coding")
        self.remove_button.clicked.connect(self._remove_selected_coding)
        self.remove_button.setEnabled(False)
        self.remove_button.setToolTip(
            "Remove the selected coding. Only affects your own work —\n"
            "a colleague's codings and the model's are untouched.\n"
            "Undoable with Ctrl+Z.")
        self.my_codings.itemSelectionChanged.connect(
            lambda: self.remove_button.setEnabled(bool(self.my_codings.selectedItems())))

        # Agreement on span coding compares only finished documents: in one
        # still being worked through, the sentences not reached yet would count
        # as "no code applies" (review finding F4).
        self.finished_check = QCheckBox("I've finished coding this document")
        self.finished_check.setToolTip(
            "Two coders' agreement is computed only on documents both have finished.")
        self.finished_check.setEnabled(False)
        self.finished_check.toggled.connect(self._on_finished_toggled)

        mine_box = QGroupBox("Your codings here")
        mine_layout = QVBoxLayout(mine_box)
        mine_layout.addWidget(self.my_codings, 1)
        mine_layout.addWidget(self.remove_button)

        # Rarely changed: how a new code is named, and marking a transcript finished.
        self.code_more = MoreOptions("More options")
        self.code_more.body_layout.addWidget(self.in_vivo_check)
        self.code_more.body_layout.addWidget(self.finished_check)
        self._build_guide_controls(self.code_more.body_layout)
        self.code_more._count = count_controls(self.code_more.body)
        self.code_more._refresh_title()

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(6, 6, 6, 6)
        right_layout.addWidget(code_box, 3)
        right_layout.addWidget(mine_box, 2)
        # The folded options can be long (the interview guide is in here): they scroll instead of
        # pushing the buttons above off the screen.
        self.code_more_scroll = QScrollArea()
        self.code_more_scroll.setWidgetResizable(True)
        self.code_more_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.code_more_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.code_more_scroll.setWidget(self.code_more)
        self.code_more_scroll.setMaximumHeight(44)
        self.code_more.toggled.connect(self._resize_more_options)
        right_layout.addWidget(self.code_more_scroll)
        return right

    def _resize_more_options(self, expanded: bool) -> None:
        """Closed: one line. Open: a tall enough window onto the options, which scroll."""
        self.code_more_scroll.setMinimumHeight(260 if expanded else 0)
        self.code_more_scroll.setMaximumHeight(360 if expanded else 44)

    def _build_guide_controls(self, layout) -> None:
        """Suggestions from an interview guide: folded under More options on the Code step."""
        layout.addWidget(QLabel("<b>Interview guide</b>"))
        self.guide_label = QLabel("No guide added yet.")
        self.guide_label.setWordWrap(True)
        self.guide_button = QPushButton("Add an interview guide…")
        self.guide_button.setToolTip(
            "A YAML file listing your themes and the questions you planned to ask. "
            "It is kept in the project.")
        self.guide_button.clicked.connect(self._on_guide_clicked)
        self.guide_suggest_button = QPushButton("Suggest codes from the guide")
        self.guide_suggest_button.setToolTip(
            "Match each question you asked, and the answer that followed, to your guide's "
            "themes. The matches are suggestions for you to read and correct.")
        self.guide_suggest_button.clicked.connect(self._on_guide_suggest)
        self.guide_remove_button = QPushButton("Remove the guide's suggestions")
        self.guide_remove_button.setToolTip(
            "Takes away only what the guide suggested in this transcript. Your own coding stays.")
        self.guide_remove_button.clicked.connect(self._on_guide_remove)
        self.guide_status = QLabel("")
        self.guide_status.setWordWrap(True)
        for widget in (self.guide_label, self.guide_button, self.guide_suggest_button,
                       self.guide_remove_button, self.guide_status):
            layout.addWidget(widget)
        self._guide_worker = None

    def _refresh_guide_controls(self) -> None:
        is_open = self._service.is_open
        template = self._service.interview_guide() if is_open else None
        busy = self._guide_worker is not None
        self.guide_label.setText(gm.describe(template) + "." if template else "No guide added yet.")
        self.guide_suggest_button.setEnabled(bool(template) and bool(self._source_id) and not busy)
        count = self._service.guide_suggestion_count(self._source_id) if is_open and self._source_id else 0
        self.guide_remove_button.setEnabled(count > 0 and not busy)
        self.guide_remove_button.setText(
            f"Remove the guide's suggestions ({count})" if count else "Remove the guide's suggestions")

    def _on_guide_clicked(self) -> None:
        if not self._service.is_open:
            QMessageBox.information(self, "No project", "Open or create a project first.")
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose an interview guide", "", "Interview guide (*.yaml *.yml);;All files (*)")
        if not path:
            return
        try:
            text = Path(path).read_text(encoding="utf-8")
            template = self._service.set_interview_guide(text)
        except (OSError, UnicodeDecodeError) as exc:
            QMessageBox.warning(self, "Could not read that file", str(exc))
            return
        except gm.GuideError as exc:
            QMessageBox.warning(self, "That guide cannot be used", str(exc))
            return
        self.guide_status.setText(f"Added. Its themes are now in your codebook. {gm.describe(template)}.")
        self._refresh_codebook()
        self._refresh_guide_controls()

    def _guide_unavailable(self) -> str:
        """Why the matching cannot run on this computer yet, or an empty string."""
        from core.model_readiness import missing_models
        from tools.setup_laya_env import has_engine

        if not has_engine():
            return ("Matching needs the analysis engine, which is not installed. "
                    "Open Settings, then Models, to add it. Hand coding does not need it.")
        embedding = "sentence-transformers/all-MiniLM-L6-v2"
        if missing_models({"models": {"embedding_model": embedding}, "sentiment": {"enabled": False}}):
            return ("Matching needs a small language model that is not on this computer yet. "
                    "Open Settings, then Models, to download it once.")
        return ""

    def _on_guide_suggest(self) -> None:
        template = self._service.interview_guide()
        if template is None or not self._source_id:
            return
        problem = self._guide_unavailable()
        if problem:
            QMessageBox.information(self, "Not ready yet", problem)
            return
        if not speakers.stored(self._service.document_metadata(self._source_id)):
            if not self._review_speakers(self._source_id, force=True):
                self.guide_status.setText("Say who is speaking first: the guide needs to know "
                                          "who asked and who answered.")
                return
        try:
            plan = self._service.guide_plan(self._source_id, template)
        except gm.GuideError as exc:
            QMessageBox.information(self, "Cannot match this transcript", str(exc))
            return
        self.guide_status.setText("Matching… the first time can take a few minutes while the model loads.")
        self._guide_worker = _GuideWorker(plan, guide_embedder(), self)
        self._guide_worker.done.connect(self._on_guide_done)
        self._refresh_guide_controls()
        self._guide_worker.start()

    def _on_guide_done(self, plan, matched, coverage, error: str) -> None:
        worker, self._guide_worker = self._guide_worker, None
        if worker is not None:
            worker.wait()
            worker.deleteLater()
        if error:
            self.guide_status.setText(f"Matching did not finish: {error}")
            self._refresh_guide_controls()
            return
        report = self._service.guide_apply(plan, matched, coverage)
        missed = len(report.guide_questions_missed)
        self.guide_status.setText(
            f"Suggested {report.suggestions} code(s) on {report.matched} of {report.pairs} answers. "
            f"{report.unclassified} answer(s) fit no theme: read those too. "
            f"{missed} guide question(s) were not asked. The suggestions are in the reader; "
            "correct them like any other.")
        self._refresh_reader()
        self._refresh_my_codings()
        self._refresh_guide_controls()
        self.status.emit(f"Guide: {report.suggestions} suggested code(s).")

    def _on_guide_remove(self) -> None:
        if not self._source_id:
            return
        answer = QMessageBox.question(
            self, "Remove the guide's suggestions",
            "Remove what the guide suggested in this transcript? Your own coding is not touched.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        removed = self._service.remove_guide_suggestions(self._source_id)
        self.guide_status.setText(f"Removed {removed} suggestion(s).")
        self._refresh_reader()
        self._refresh_guide_controls()

    def _install_shortcuts(self) -> None:
        """Keyboard coding: 1-9 apply a code, Enter applies the selected ones.

        Bound on this widget with `WidgetWithChildrenShortcut` so a digit typed
        into the new-code box stays a digit -- the shortcut only fires when
        focus is in the reader or the code list.
        """
        for index in range(1, _QUICK_CODE_KEYS + 1):
            action = QAction(f"Apply code {index}", self)
            action.setShortcut(QKeySequence(str(index)))
            action.setShortcutContext(
                Qt.ShortcutContext.WidgetWithChildrenShortcut)
            action.triggered.connect(
                lambda _checked=False, i=index: self._apply_quick_code(i))
            self.reader.addAction(action)

        expand = QAction("Expand selection to sentence", self)
        expand.setShortcut(QKeySequence("Ctrl+E"))
        expand.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        expand.triggered.connect(self.reader.expand_selection_to_sentence)
        self.reader.addAction(expand)

        apply_action = QAction("Apply selected codes", self)
        apply_action.setShortcut(QKeySequence(Qt.Key.Key_Return))
        apply_action.setShortcutContext(
            Qt.ShortcutContext.WidgetWithChildrenShortcut)
        apply_action.triggered.connect(self._apply_selected_codes)
        self.reader.addAction(apply_action)

    # -- steps ---------------------------------------------------------------
    def set_step(self, key: str) -> None:
        """Add transcripts: the list and the import button, nothing else. Code: the
        list, the reader and the coding panel. Same screen, two steps."""
        if key not in STEP_KEYS:
            return
        self._step = key
        adding = key == "add"
        # Beside the reader there is room for names and how much is coded, not the rest.
        self.library.setColumnHidden(1, not adding)
        self.library.setColumnHidden(2, not adding)
        self._middle.setVisible(not adding)
        self._right.setVisible(not adding)
        for widget in (self.import_button, self.speakers_button, self.guide_note, self.add_note,
                       self.next_button):
            widget.setVisible(adding)
        self._refresh_main()

    def current_step(self) -> str:
        return self._step

    def go_step(self, key: str) -> None:
        self.set_step(key)
        self.step_requested.emit(key)

    def _set_main(self, button: QPushButton, on: bool) -> None:
        if bool(button.property("main")) == on:
            return
        button.setProperty("main", on)
        button.style().unpolish(button)
        button.style().polish(button)

    def _refresh_main(self) -> None:
        """Add first; Next once there is something to read."""
        has_documents = self.library.rowCount() > 0
        self._set_main(self.import_button, not has_documents)
        self._set_main(self.next_button, has_documents)
        self.next_button.setEnabled(has_documents)
        if not self._service.is_open:
            self.add_note.setText("")
        elif has_documents:
            n = self.library.rowCount()
            self.add_note.setText(f"{n} transcript{'s' if n != 1 else ''} added.")
        else:
            self.add_note.setText("No transcripts yet. Add a folder of .txt, .docx, .md or .pdf files.")

    # -- data ----------------------------------------------------------------
    def set_theme_mode(self, mode: str, palette: str = "") -> None:
        self._theme_mode = mode if mode in ("dark", "light") else "dark"
        self._palette_name = palette or self._palette_name
        self.reader.set_theme_mode(self._theme_mode)
        if self._service.is_open:
            self._refresh_codebook()      # code colours come from the skin too
            self._refresh_reader()

    def _on_project_changed(self, _path: str) -> None:
        self._source_id = ""
        self._show_welcome_if_empty()
        self.refresh()

    def refresh(self) -> None:
        """Full reload: the corpus list, the codebook, and the reader.

        For a project change or an import. **Not** for a coding — see
        `_refresh_after_coding`, which is what the store's change signal is
        wired to.
        """
        if not self._service.is_open:
            self.library.setRowCount(0)
            self._refresh_main()
            self.code_list.clear()
            self.my_codings.clear()
            self.doc_title.setText("<i>No project open.</i>")
            self.reader.set_document("", "")
            self._length_cache.clear()
            self._refresh_guide_controls()
            return
        self._refresh_library()
        self._refresh_codebook()
        self._refresh_reader()
        if not self._source_id:
            # The heading still says "No project open." from before this project
            # opened; say what is true and what to do (UX-5).
            self.doc_title.setText(
                "<i>No documents yet. Choose “Import a folder…” to add transcripts.</i>"
                if self.library.rowCount() == 0 else "<i>No document selected.</i>")

    def _refresh_after_coding(self) -> None:
        """The hot path: one code applied, so update only what changed.

        A coding changes the reader's highlights, this analyst's coding list,
        possibly the codebook (a new code), and **one** row of the corpus list.
        The full `refresh()` also reloaded every document's text to recompute
        coverage percentages, which on a six-document corpus cost more than
        everything else in the loop put together. Coding is hundreds of
        repetitions; the per-action cost is the feature.
        """
        if not self._service.is_open:
            return
        self._refresh_codebook()
        self._refresh_reader()
        self._refresh_current_library_row()

    def _document_length(self, source_id: str) -> int:
        """Character count, cached. A document's text is immutable after import."""
        if source_id not in self._length_cache:
            if source_id == self.reader.source_id:
                self._length_cache[source_id] = len(self.reader.text)
            else:
                self._length_cache[source_id] = len(
                    self._service.document_text(source_id))
        return self._length_cache[source_id]

    def _refresh_library(self) -> None:
        table: pd.DataFrame = self._service.document_table()
        previously = self._source_id
        self.library.blockSignals(True)
        self.library.setRowCount(len(table))
        select_row = -1
        for row, (_index, record) in enumerate(table.iterrows()):
            source_id = str(record["source_id"])
            title = QTableWidgetItem(str(record["title"]))
            title.setData(Qt.ItemDataRole.UserRole, source_id)
            self.library.setItem(row, 0, title)
            self.library.setItem(row, 1, QTableWidgetItem(f"{int(record['words']):,}"))
            self._set_library_counts(row, source_id)
            if source_id == previously:
                select_row = row
        self.library.blockSignals(False)
        if select_row >= 0:
            self.library.selectRow(select_row)
        elif len(table) and not previously:
            self.library.selectRow(0)
        self._refresh_main()

    def _set_library_counts(self, row: int, source_id: str,
                            spans: Optional[List[Dict[str, Any]]] = None) -> None:
        """Fill the passages/coverage cells for one row.

        `spans` may be passed in when the caller already has them, which is how
        the coding path avoids a second query for the document on screen.
        """
        if spans is None:
            spans = self._service.coding_spans(source_id)
        self.library.setItem(row, 2, QTableWidgetItem(str(len(spans))))
        self.library.setItem(row, 3, QTableWidgetItem(
            f"{coding_density(self._document_length(source_id), spans):.0%}"))

    def _refresh_current_library_row(self) -> None:
        """Update only the selected document's counts — the only ones that moved."""
        if not self._source_id:
            return
        for row in range(self.library.rowCount()):
            item = self.library.item(row, 0)
            if item is not None and item.data(Qt.ItemDataRole.UserRole) == self._source_id:
                self.library.blockSignals(True)
                self._set_library_counts(row, self._source_id, self._current_spans)
                self.library.blockSignals(False)
                return

    def _refresh_codebook(self) -> None:
        # Preserve the ticked codes across the rebuild, keyed on the code *name*
        # rather than the row's label — the label carries a "1. " shortcut
        # prefix, and comparing against that silently dropped the selection on
        # every refresh. Coding is mostly "apply this same code to the next
        # passage", so losing the tick after each application is not cosmetic.
        selected = {item.data(Qt.ItemDataRole.UserRole)
                    for item in self.code_list.selectedItems()}
        names = sorted(self._service.code_names())
        colors = code_colors(names, self._theme_mode, palette=self._palette_name,
                                overrides=self._service.code_color_overrides())
        self.code_list.clear()
        for index, name in enumerate(names):
            label = f"{index + 1}. {name}" if index < _QUICK_CODE_KEYS else name
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, name)
            item.setForeground(colors[name])
            self.code_list.addItem(item)
            if name in selected:
                item.setSelected(True)

    def _refresh_reader(self) -> None:
        if not self._source_id or not self._service.is_open:
            return
        if self.reader.source_id != self._source_id:
            self.reader.set_document(self._source_id,
                                     self._service.document_text(self._source_id))
        self._show_speakers()
        # One query, three consumers: the reader's highlights, this analyst's
        # coding list, and the corpus row. Asking the store three times for the
        # same spans was most of the cost of applying a single code.
        spans = self._service.coding_spans(self._source_id)
        self._current_spans = spans
        length = self._document_length(self._source_id)
        all_codes = sorted({c for span in spans for c in span["codes"]})
        self.reader.set_spans(spans, code_colors(all_codes, self._theme_mode, palette=self._palette_name,
                        overrides=self._service.code_color_overrides()))
        self.coverage_label.setText(
            f"{len(spans)} coded passage(s) · {coding_density(length, spans):.0%} covered")

        if not self.reader.is_codeable:
            self.warning_label.setText(banner_text("warning",
                "This document's characters could not be mapped to the reader "
                "reliably, so coding is disabled for it. Coding it anyway could "
                "attach codes to the wrong passage. Please report this document."))
            self.warning_label.setVisible(True)
        else:
            self.warning_label.setVisible(False)

        self._refresh_my_codings()
        self._update_apply_enabled()
        self._refresh_guide_controls()

    def _show_speakers(self) -> None:
        """Italics for the interviewer's turns, and one line saying who is who."""
        meta = self._service.document_metadata(self._source_id)
        line = speakers.summary(meta)
        self.speaker_label.setText(f"{line}. The interviewer's words are in italics." if line else "")
        self.speaker_label.setVisible(bool(line))
        self._not_participant = speakers.spans_for(
            self.reader.text, meta, roles=("interviewer", "other"))
        self.reader.set_speaker_spans(self._not_participant)
        self.speakers_button.setEnabled(bool(self._source_id))

    def _review_speakers(self, source_id: str, *, force: bool = False) -> bool:
        """Propose who is speaking and let the person confirm. True if roles were saved.

        With one speaker there is nothing to confirm and nothing is asked or stored. The
        person can always skip: the transcript is then left exactly as it was."""
        if not source_id or not self._service.is_open:
            return False
        text = self._service.document_text(source_id)
        review = speakers.analyse(text)
        title = next((self.library.item(r, 0).text() for r in range(self.library.rowCount())
                      if self.library.item(r, 0).data(Qt.ItemDataRole.UserRole) == source_id), "")
        if not title:
            # Straight after an import the list has not been rebuilt yet: take the name from the project.
            source = self._service.project.get_source(source_id)
            title = (source.label if source is not None else "") or ""
        if not review.needs_roles:
            if force:
                QMessageBox.information(
                    self, "One speaker",
                    "QualSafe could not find two or more speakers in this transcript, so there "
                    "is nothing to mark. It needs lines that start like Interviewer: or Q:.")
            return False
        dialog = SpeakerReviewDialog(title, review, self)
        if dialog.exec() != SpeakerReviewDialog.DialogCode.Accepted:
            return False
        self._service.set_speakers(source_id, speakers.to_metadata(review, dialog.roles()))
        if source_id == self._source_id:
            self._show_speakers()
            self.reader.editor.viewport().update()
        return True

    def _refresh_my_codings(self) -> None:
        """This analyst's coded passages.

        Deliberately a second, rater-filtered query rather than a filter over
        `self._current_spans`. Those spans are unfiltered, so each one carries
        *every* code on that excerpt including a model's — filtering them by
        "the human touched this passage" would list machine codes as the
        analyst's own work and break invariant #6. `coding_spans(rater_id=...)`
        filters the codings, not just the passages, which is the distinction
        that matters.
        """
        from core.span_coding import HUMAN_RATER

        text = self.reader.text          # already loaded; do not re-read the store
        mine = self._service.coding_spans(self._source_id, rater_id=HUMAN_RATER)
        self.my_codings.clear()
        for span in mine:
            quote = " ".join(text[span["char_start"]:span["char_end"]].split())
            label = f"[{', '.join(span['codes'])}] {quote[:70]}"
            item = QListWidgetItem(label + ("…" if len(quote) > 70 else ""))
            item.setData(Qt.ItemDataRole.UserRole, span)
            item.setToolTip(quote[:400])
            self.my_codings.addItem(item)

    # -- interaction ---------------------------------------------------------
    def _on_document_selected(self) -> None:
        items = self.library.selectedItems()
        if not items:
            return
        source_id = self.library.item(items[0].row(), 0).data(Qt.ItemDataRole.UserRole)
        if not source_id or source_id == self._source_id:
            return
        self._source_id = source_id
        self.doc_title.setText(f"<b>{self.library.item(items[0].row(), 0).text()}</b>")
        self._refresh_reader()
        self._sync_finished_check()
        self.reader.editor.setFocus()

    def _sync_finished_check(self) -> None:
        self.finished_check.blockSignals(True)
        self.finished_check.setEnabled(bool(self._source_id))
        self.finished_check.setChecked(
            bool(self._source_id) and self._service.document_finished(self._source_id))
        self.finished_check.blockSignals(False)

    def _on_finished_toggled(self, checked: bool) -> None:
        if self._source_id:
            self._service.set_document_finished(self._source_id, checked)

    # -- progress (core/ux/progress.py) --------------------------------------
    def progress_state(self) -> dict:
        """Which document is open and how far down it is read. Never its text."""
        if not self._source_id:
            return {}
        return {"document": self._source_id,
                "scroll_position": int(self.reader.editor.verticalScrollBar().value())}

    def reset_session(self) -> None:
        """Forget which document was open and how far it was read. The project and
        its documents are not touched."""
        self._source_id = ""
        self.library.clearSelection()
        self.my_codings.clear()
        self.reader.set_document("", "")
        self.doc_title.setText("<i>No document selected.</i>")
        self._sync_finished_check()

    def restore_progress(self, state: dict) -> bool:
        """Open the saved document and scroll back to where it was left."""
        source_id = str(state.get("document", ""))
        for row in range(self.library.rowCount()):
            item = self.library.item(row, 0)
            if item is not None and item.data(Qt.ItemDataRole.UserRole) == source_id:
                self.library.selectRow(row)
                bar = self.reader.editor.verticalScrollBar()
                bar.setValue(int(state.get("scroll_position", 0) or 0))
                return True
        return not source_id

    def select_source_span(self, source_id: str, char_start: int,
                           char_end: int) -> bool:
        """Open a document and select a span. Returns False if it is not here.

        The entry point other screens use to hand this one a place: a search
        hit, a query result, a co-occurring passage. Selecting rather than just
        scrolling means the analyst can code it immediately — which is the whole
        reason a hit is worth navigating to.
        """
        for row in range(self.library.rowCount()):
            item = self.library.item(row, 0)
            if item is not None and item.data(Qt.ItemDataRole.UserRole) == source_id:
                self.library.selectRow(row)
                self.reader.select_span(char_start, char_end)
                self.reader.editor.setFocus()
                return True
        return False

    def _on_selection_changed(self, start: int, end: int, text: str) -> None:
        if start < 0:
            self.selection_label.setText(
                "<i>Select text in the document to code it.</i>")
        else:
            shown = " ".join(text.split())
            if len(shown) > 180:
                shown = shown[:180] + "…"
            self.selection_label.setText(
                f"<span style='color:palette(mid)'>characters {start}–{end} "
                f"({end - start})</span><br>“{_escape(shown)}”")
        self._update_apply_enabled()

    def _update_apply_enabled(self) -> None:
        ready = (
            self._service.is_open
            and bool(self._source_id)
            and self.reader.is_codeable
            and self.reader.selected_span() is not None
        )
        self.apply_button.setEnabled(ready)

    def _on_span_activated(self, excerpt_id: str) -> None:
        for row in range(self.my_codings.count()):
            item = self.my_codings.item(row)
            if item.data(Qt.ItemDataRole.UserRole)["excerpt_id"] == excerpt_id:
                self.my_codings.setCurrentItem(item)
                return

    def _on_my_coding_clicked(self, item: QListWidgetItem) -> None:
        span = item.data(Qt.ItemDataRole.UserRole)
        self.reader.select_span(span["char_start"], span["char_end"])

    # -- coding --------------------------------------------------------------
    def _chosen_code_names(self) -> List[str]:
        """Codes to apply: the ticked ones, a typed one, and/or the passage itself.

        Mirrors `app/documents_page._codes_to_apply` so both front ends build the
        same list from the same controls.
        """
        names = [item.data(Qt.ItemDataRole.UserRole)
                 for item in self.code_list.selectedItems()]
        typed = self.new_code_edit.text().strip()
        if typed:
            names.append(typed)
        if self.in_vivo_check.isChecked():
            passage = " ".join(self.reader.selected_text().split())[:80]
            if passage:
                names.append(passage)
        # Preserve order, drop duplicates.
        seen, ordered = set(), []
        for name in names:
            if name and name not in seen:
                seen.add(name)
                ordered.append(name)
        return ordered

    def _apply_quick_code(self, index: int) -> None:
        """Apply the Nth code in the list to the current selection (key 1-9)."""
        if index > self.code_list.count():
            return
        item = self.code_list.item(index - 1)
        self._code_selection([item.data(Qt.ItemDataRole.UserRole)])

    def _apply_selected_codes(self) -> None:
        self._code_selection(self._chosen_code_names())

    def _code_selection(self, code_names: List[str]) -> None:
        span = self.reader.selected_span()
        if span is None:
            self.status.emit("Select a passage in the document first.")
            return
        if not self.reader.is_codeable:
            self.status.emit("Coding is disabled for this document — see the warning above.")
            return
        if not code_names:
            self.status.emit("Choose at least one code, or type a new one.")
            return
        if speakers.lies_within(self.reader.text, span, getattr(self, "_not_participant", [])):
            answer = QMessageBox.question(
                self, "The interviewer's words",
                "That passage is the interviewer's words, not the participant's. Code it anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return
        try:
            command = ApplyCodesCommand(
                self._service, self._source_id, span[0], span[1], code_names)
            self._undo.push(command)
        except ValueError as exc:
            QMessageBox.warning(self, "Could not code that passage", str(exc))
            return
        self.new_code_edit.clear()
        self.in_vivo_check.setChecked(False)
        created = f" New code(s): {', '.join(command.created_codes)}." if command.created_codes else ""
        self.status.emit(
            f"Coded characters {span[0]}–{span[1]} with {', '.join(code_names)}.{created}"
            "  (Ctrl+Z to undo)")
        self.reader.editor.setFocus()

    def _remove_selected_coding(self) -> None:
        items = self.my_codings.selectedItems()
        if not items:
            return
        span = items[0].data(Qt.ItemDataRole.UserRole)
        self._undo.push(RemoveCodingCommand(
            self._service, self._source_id, span["excerpt_id"],
            span["char_start"], span["char_end"]))
        self.status.emit(
            f"Removed {len(span['codes'])} coding(s) from characters "
            f"{span['char_start']}–{span['char_end']}.  (Ctrl+Z to undo)")

    # -- import --------------------------------------------------------------
    def _on_import_clicked(self) -> None:
        """Import a folder of documents, behind the PII attestation gate.

        The gate is not decoration: it is the moment the analyst takes
        responsibility for what goes into the project, and it is recorded
        behaviour in the Streamlit build. The scan is assistive and says so.
        """
        if not self._service.is_open:
            QMessageBox.information(self, "No project", "Open or create a project first.")
            return
        folder = QFileDialog.getExistingDirectory(self, "Choose a folder of documents")
        if not folder:
            return
        found = list_documents_in_folder(folder)
        if not found:
            QMessageBox.information(
                self, "Nothing to import",
                "No .txt, .md, .docx, or .pdf files directly inside that folder.")
            return
        texts, unreadable = [], []
        for path in found:
            try:
                texts.append(read_document(path))
            except Exception as exc:  # noqa: BLE001 - one bad file must not stop the gate
                unreadable.append((path.name, str(exc)))
        findings = scan_frame(pd.DataFrame({"text": texts})) if texts else []

        if not _confirm_import(self, found, findings, unreadable):
            return
        result = self._service.import_documents(found)
        for source_id in result.get("imported_ids", []):
            self._review_speakers(source_id)        # one at a time; Skip leaves it as it was
        # An import adds rows, so the corpus list must be rebuilt — the cheap
        # coding-path refresh only touches the current row.
        self.refresh()
        parts = []
        if result["imported"]:
            parts.append(f"imported {len(result['imported'])}")
        if result["skipped"]:
            parts.append(f"skipped {len(result['skipped'])} already present")
        if result["failed"]:
            parts.append(f"{len(result['failed'])} failed")
            QMessageBox.warning(
                self, "Some files could not be read",
                "\n".join(f"{name}: {why}" for name, why in result["failed"]))
        self.status.emit("Import: " + ", ".join(parts) + ".")


def guide_embedder():
    """The embedder the guide matching uses (replaced in tests)."""
    from interview.matching import default_embed_fn

    return default_embed_fn()


class _GuideWorker(QThread):
    """Scores the answers against the guide off the main thread. It never touches the project:
    the result is handed back and kept by the window's own thread."""

    done = Signal(object, object, object, str)

    def __init__(self, plan, embed_fn, parent=None) -> None:
        super().__init__(parent)
        self._plan, self._embed_fn = plan, embed_fn

    def run(self) -> None:
        try:
            matched, coverage = gm.match(self._plan, self._embed_fn)
        except Exception as exc:  # noqa: BLE001 - say what happened instead of closing the window
            self.done.emit(self._plan, [], [], str(exc) or exc.__class__.__name__)
            return
        self.done.emit(self._plan, matched, coverage, "")


def _confirm_import(
    parent: QWidget,
    paths: List[Path],
    findings: List[Dict[str, Any]],
    unreadable: List[tuple],
) -> bool:
    """The PII gate. Returns True only on explicit attestation.

    Mirrors `app/documents_page._render_import_gate`: the files are read and
    scanned *before* the question is asked, so the analyst is attesting about
    content they have been shown something about — an attestation offered before
    the scan would be theatre. The scan is heuristic and the dialog says so;
    what the gate records is the analyst's judgement, not the regex's.
    """
    listing = "\n".join(f"  • {p.name}" for p in paths[:12])
    if len(paths) > 12:
        listing += f"\n  … and {len(paths) - 12} more"

    detail = [listing, "",
              "These files will be read into the project store on this machine. "
              "Nothing is uploaded anywhere.", ""]
    if unreadable:
        detail.append("Could not be read (they will be skipped):")
        detail += [f"  • {name}: {why}" for name, why in unreadable[:6]]
        detail.append("")
    detail.append(summarize_findings(findings))
    if findings:
        # `scan_frame` returns {column, signal, n_hits, example_masked}. Show the
        # masked example, never the matched value itself — a gate that prints the
        # email address it found has leaked it to anyone looking at the screen.
        for finding in findings[:8]:
            detail.append(
                f"  • {finding['signal']} — {finding['n_hits']} hit(s), "
                f"e.g. {finding['example_masked']}")
        if len(findings) > 8:
            detail.append(f"  … and {len(findings) - 8} more signal(s)")
        detail.append(
            "These are rough checks, not a verdict — they miss a name written "
            "mid-sentence and flag harmless numbers. Your review is what this "
            "gate records.")
    detail.append("")
    detail.append("Confirm that you have reviewed these documents and they are "
                  "appropriate to process here.")

    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Warning if findings else QMessageBox.Icon.Question)
    box.setWindowTitle("Confirm before importing")
    box.setText(f"Import {len(paths)} document(s)?")
    box.setInformativeText("\n".join(detail))
    box.setStandardButtons(
        QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes)
    box.setDefaultButton(QMessageBox.StandardButton.Cancel)
    box.button(QMessageBox.StandardButton.Yes).setText("I confirm — import")
    return box.exec() == QMessageBox.StandardButton.Yes


def _escape(text: str) -> str:
    """Escape for the rich-text selection label — a transcript may contain '<'."""
    import html

    return html.escape(text)
