"""
The codebook: a real tree you can drag, plus health, suggestions, and history.

The Qt counterpart of `app/codebook.py`. The engine already models arbitrary-
depth nesting (`Code.parent_id`), but Streamlit can only offer that as a "Parent
code" dropdown — so reorganising a codebook there is a series of blind selectbox
edits with no view of the shape you are building. Here the hierarchy is visible
and you drag a code onto its new parent.

What is deliberately **not** on the undo stack: merge and delete. Both move or
cascade *applications*, and a codebook snapshot restores codes, not the coding
that was reassigned — so an "undo" that only put the code back would be a lie
about what was recovered. They are confirmed with a dialog that says what will
happen, and they clear the undo stack, because commands recorded before a
structural change can no longer be trusted to mean what they said.

Per `qualsafe_qt/__init__`, this module imports only `core/`, `analysis/`,
`qualsafe_qt.*`, and Qt.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QColor, QUndoStack
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
    QFormLayout, QGroupBox, QHBoxLayout, QHeaderView, QInputDialog, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMenu, QMessageBox, QPlainTextEdit,
    QPushButton, QSplitter, QTabWidget, QTreeView, QVBoxLayout, QWidget,
)

from qualsafe_qt.commands import AddCodeCommand, EditCodeCommand, ReparentCodeCommand
from qualsafe_qt.models.codebook_model import CodebookModel
from qualsafe_qt.widgets.more_options import MoreOptions, count_controls
from qualsafe_qt.services.project_service import ProjectService
from qualsafe_qt.colors import code_colors
from qualsafe_qt.theme import success_span
from qualsafe_qt.services.tasks import run_task

#: Cosine-similarity floor for merge suggestions. Matches `app/codebook.py`.
_SIMILARITY_THRESHOLD = 0.80
#: The embedding model the Streamlit build defaults to for this check.
_DEFAULT_EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


def _wrap(layout) -> QWidget:
    """A layout as a widget, so it can sit in a QFormLayout row."""
    holder = QWidget()
    holder.setLayout(layout)
    return holder


class _DiaryNoteDialog(QDialog):
    """Add a research-diary note: pick a kind of thinking, then write.

    The prompts are Saldaña's (2013, pp. 43-49) in plain words. A note is stored
    as a project memo whose first line is the topic, so it can be found and
    sorted later without a schema change.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        from core.ux.guide import MEMO_TOPICS

        self._topics = list(MEMO_TOPICS)
        self.setWindowTitle("Add a diary note")
        self.setMinimumWidth(480)
        self.topic_box = QComboBox()
        for title, _prompt in self._topics:
            self.topic_box.addItem(title)
        self.prompt_label = _hint("")
        self.text_edit = QPlainTextEdit()
        self.text_edit.setPlaceholderText(
            "Write it like a letter to a friend. It does not need to be tidy.")
        self.text_edit.setMinimumHeight(140)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("What are you thinking about?"))
        layout.addWidget(self.topic_box)
        layout.addWidget(self.prompt_label)
        layout.addWidget(self.text_edit, 1)
        layout.addWidget(buttons)
        self.topic_box.currentIndexChanged.connect(self._show_prompt)
        self._show_prompt()

    def _show_prompt(self) -> None:
        index = self.topic_box.currentIndex()
        if 0 <= index < len(self._topics):
            self.prompt_label.setText(f"<i>{self._topics[index][1]}</i>")

    def topic(self) -> str:
        return self.topic_box.currentText()

    def text(self) -> str:
        return self.text_edit.toPlainText().strip()


def _hint(text: str) -> QLabel:
    """An explanatory label that wraps.

    Without `setWordWrap`, a QLabel demands its whole single-line width as a
    layout minimum -- which silently forced the detail panel wide enough to
    squeeze the codebook tree, the one thing this screen exists to show.
    """
    label = QLabel(text)
    label.setWordWrap(True)
    label.setTextFormat(Qt.TextFormat.RichText)
    return label


class CodebookView(QWidget):
    """Tree + detail panel over the project's codebook."""

    status = Signal(str)

    def __init__(self, service: ProjectService, undo_stack: QUndoStack,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._service = service
        self._undo = undo_stack
        self._selected_code_id = ""
        self._theme_mode = "dark"
        self._suggestions: List[Dict[str, Any]] = []

        self._build_ui()
        service.project_changed.connect(lambda _p: self.refresh())
        service.store_changed.connect(self.refresh)
        self.refresh()      # render the empty state rather than a blank panel
        self._refresh_main()

    # -- construction --------------------------------------------------------
    def _build_ui(self) -> None:
        self.model = CodebookModel(self)
        self.model.reparent_requested.connect(self._on_reparent_requested)

        self.tree = QTreeView()
        self.tree.setModel(self.model)
        self.tree.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.tree.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._show_context_menu)
        self.tree.setAlternatingRowColors(True)
        self.tree.setToolTip(
            "Drag a code onto another to nest it, or onto empty space to make it "
            "a top-level code. Right-click for more.")
        header = self.tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.tree.selectionModel().selectionChanged.connect(self._on_selection_changed)

        add_button = self.add_button = QPushButton("Add a code")
        add_button_tip = (
            "Create a new top-level code. Right-click a code in the tree to\n"
            "add one underneath it instead.")
        add_button.clicked.connect(self._add_code)
        add_button.setToolTip(add_button_tip)
        export_button = self.export_button = QPushButton("Save these codes to a file…")
        export_button.clicked.connect(self._export_yaml)
        import_button = self.import_button = QPushButton("Add codes from a file…")
        import_button.clicked.connect(self._import_yaml)
        export_button.setToolTip(
            "Names, definitions, and hierarchy — no data. Reuse it in the next "
            "project or share it with a colleague.")
        import_button.setToolTip(
            "Additive: codes you already have (same name) are left untouched and "
            "reported, never overwritten.")

        buttons = QHBoxLayout()
        buttons.addWidget(add_button)
        buttons.addStretch(1)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(6, 6, 6, 6)
        self.summary_label = QLabel()
        left_layout.addWidget(self.summary_label)
        left_layout.addWidget(self.tree, 1)
        left_layout.addLayout(buttons)

        # Name, definition and Save are what this step is for. Everything else
        # (colour, notes, checks, similar codes, earlier versions, sharing) is
        # in one More options panel.
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_code_tab(), "Colour and notes")
        self.tabs.addTab(self._build_health_tab(), "Checks")
        self.tabs.addTab(self._build_suggestions_tab(), "Similar codes")
        self.tabs.addTab(self._build_history_tab(), "Earlier versions")
        self.tabs.addTab(self._build_diary_tab(), "Research diary")
        share = QWidget()
        share_layout = QVBoxLayout(share)
        share_layout.addWidget(_hint(
            "<i>Names, definitions and the way codes are grouped, with no data. Reuse them "
            "in the next project or share them. Adding codes never overwrites one you already have.</i>"))
        share_layout.addWidget(import_button)
        share_layout.addWidget(export_button)
        share_layout.addStretch(1)
        self.tabs.addTab(share, "Share")
        self.code_more = MoreOptions("More options")
        self.code_more.body_layout.addWidget(self.tabs)
        self.code_more._count = count_controls(self.code_more.body)
        self.code_more._refresh_title()

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.addWidget(self.edit_box)
        right_layout.addWidget(self.code_more)
        right_layout.addStretch(1)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setCollapsible(0, False)
        # Stretch factors only divide space *beyond* each pane's size hint, and
        # the detail panel's forms hint large enough to swallow the tree. An
        # explicit split gives the hierarchy the room it needs to be readable,
        # which is the entire reason this screen exists.
        splitter.setSizes([900, 620])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(splitter)

    def _build_code_tab(self) -> QWidget:
        self.name_edit = QLineEdit()
        # (tooltip set below, once the widget exists)
        self.definition_edit = QPlainTextEdit()
        self.definition_edit.setPlaceholderText(
            "What does this code mean? What counts, and what does not?")
        self.definition_edit.setFixedHeight(90)
        self.name_edit.setToolTip("What this code is called, everywhere in the project.")
        self.definition_edit.setToolTip(
            "What counts as this code, and what does not.\n"
            "A code without a definition is not reproducible — nobody else can\n"
            "apply it the same way, including you in six months.")

        # The rest of a codebook entry (Saldaña 2013, p. 25): when to use the
        # code, when to leave it out, and examples. Writing "leave it out when"
        # is what lets a second coder apply the code the same way.
        self.use_when_edit = QPlainTextEdit()
        self.use_when_edit.setPlaceholderText(
            "e.g. The person says they cannot pay for something.")
        self.use_when_edit.setFixedHeight(54)
        self.use_when_edit.setToolTip(
            "The conditions under which this code applies.")
        self.leave_out_edit = QPlainTextEdit()
        self.leave_out_edit.setPlaceholderText(
            "e.g. A general remark about money with no hardship.")
        self.leave_out_edit.setFixedHeight(54)
        self.leave_out_edit.setToolTip(
            "The look-alikes that should not get this code. This is the single\n"
            "most useful line for agreement between two coders.")
        self.examples_edit = QPlainTextEdit()
        self.examples_edit.setPlaceholderText("One example passage per line.")
        self.examples_edit.setFixedHeight(64)
        self.examples_edit.setToolTip(
            "Typical passages that carry this code, one per line. They stay in\n"
            "the project file; the audit trail records only how many.")

        self.parent_label = QLabel("—")
        self.uses_label = QLabel("—")

        self.save_button = QPushButton("Save changes")
        self.save_button.setProperty("main", True)
        self.save_button.clicked.connect(self._save_code)
        self.save_button.setToolTip(
            "Save the name and definition (undoable with Ctrl+Z) and the coding\n"
            "rules (recorded in the project history).")

        # Per-code colour. Stored in the *project*, not this machine's settings,
        # so an analyst's scheme travels with the .qnw to a colleague.
        self.color_button = QPushButton("Choose colour…")
        self.color_button.clicked.connect(self._choose_color)
        self.color_button.setToolTip(
            "Pin this code to a colour of your choosing, used in the reader's\n"
            "margin stripes and highlights.\n"
            "Saved in the project, so it travels with the file to a colleague.")
        self.color_clear = QPushButton("Use the palette")
        self.color_clear.clicked.connect(lambda: self._set_color(None))
        self.color_clear.setToolTip(
            "Go back to the automatic colour from the palette\n"
            "(View > Appearance).")
        self.color_swatch = QLabel()
        self.color_swatch.setFixedSize(28, 20)
        color_row = QHBoxLayout()
        color_row.addWidget(self.color_swatch)
        color_row.addWidget(self.color_button)
        color_row.addWidget(self.color_clear)
        color_row.addStretch(1)

        form = QFormLayout()
        form.addRow("Name", self.name_edit)
        form.addRow("Definition", self.definition_edit)
        form.addRow("Parent", self.parent_label)
        form.addRow("Times used", self.uses_label)

        # The coding rules are one click away, not on the first screen: seven controls at most.
        rules_form = QFormLayout()
        rules_form.addRow("Use this code when", self.use_when_edit)
        rules_form.addRow("Leave it out when", self.leave_out_edit)
        rules_form.addRow("Examples", self.examples_edit)
        self.rules_more = MoreOptions("Coding rules")
        self.rules_more.body_layout.addLayout(rules_form)
        self.rules_more._count = count_controls(self.rules_more.body)
        self.rules_more._refresh_title()

        edit_box = self.edit_box = QGroupBox("Edit this code")
        edit_layout = QVBoxLayout(edit_box)
        edit_layout.addLayout(form)
        edit_layout.addWidget(self.rules_more)
        edit_layout.addWidget(self.save_button)

        # Per-code memos: the analyst's reasoning about this theme.
        self.memo_list = QListWidget()
        self.memo_list.setToolTip("Your notes about this code.")
        # A memo is prose, not a row in a table: wrap it rather than making the
        # analyst scroll sideways to read their own reasoning.
        self.memo_list.setWordWrap(True)
        self.memo_list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        memo_add = QPushButton("Add memo…")
        memo_add.clicked.connect(self._add_memo)
        memo_add.setToolTip(
            "Record why this code exists, what you decided about edge cases,\n"
            "or how it changed. Memos are the audit trail of your thinking.")
        memo_del = QPushButton("Delete selected")
        memo_del.clicked.connect(self._delete_memo)
        memo_del.setToolTip("Delete the selected memo. This cannot be undone.")
        memo_buttons = QHBoxLayout()
        memo_buttons.addWidget(memo_add)
        memo_buttons.addWidget(memo_del)
        memo_buttons.addStretch(1)

        memo_box = QGroupBox("Memos on this code")
        memo_layout = QVBoxLayout(memo_box)
        memo_layout.addWidget(self.memo_list, 1)
        memo_layout.addLayout(memo_buttons)

        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.addWidget(QLabel("Colour"))
        layout.addWidget(_wrap(color_row))
        layout.addWidget(memo_box, 1)
        return tab

    def _build_health_tab(self) -> QWidget:
        self.health_label = QLabel()
        self.health_label.setWordWrap(True)
        self.health_label.setTextFormat(Qt.TextFormat.RichText)
        self.health_label.setAlignment(
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.health_label.setToolTip(
            "Hygiene checks. Fix any of these with the tree and the Code tab.")

        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.addWidget(_hint(
            "<i>Hygiene checks over the codebook — most useful after a merge "
            "adds emergent codes. Fix any of these with the controls on the "
            "left.</i>"))
        layout.addWidget(self.health_label, 1)
        return tab

    def _build_suggestions_tab(self) -> QWidget:
        self.find_similar_button = QPushButton("Find similar codes")
        self.find_similar_button.clicked.connect(self._find_similar)
        self.find_similar_button.setToolTip(
            "Compares what codes mean using a model on this computer, offline. Runs in the\n"
            "background.")

        self.suggestions_list = QListWidget()
        self.suggestions_list.setToolTip(
            "Nothing is merged automatically — review each pair.")
        self.merge_pair_button = QPushButton("Merge the selected pair…")
        self.merge_pair_button.clicked.connect(self._merge_selected_pair)
        self.merge_pair_button.setEnabled(False)
        self.suggestions_list.itemSelectionChanged.connect(
            lambda: self.merge_pair_button.setEnabled(
                bool(self.suggestions_list.selectedItems())))

        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.addWidget(_hint(
            "<i>Suggestions from meaning, not spelling: codes whose name and "
            "definition are semantically similar (e.g. 'Cost worry' ≈ "
            "'Financial stress'). Nothing is merged automatically.</i>"))
        layout.addWidget(self.find_similar_button)
        layout.addWidget(self.suggestions_list, 1)
        layout.addWidget(self.merge_pair_button)
        return tab

    def _build_history_tab(self) -> QWidget:
        self.version_list = QListWidget()
        tag_button = QPushButton("Tag the codebook as it is now…")
        tag_button.clicked.connect(self._tag_version)
        self.restore_button = QPushButton("Restore to the selected version…")
        self.restore_button.clicked.connect(self._restore_version)
        self.restore_button.setEnabled(False)
        self.version_list.itemSelectionChanged.connect(
            lambda: self.restore_button.setEnabled(
                bool(self.version_list.selectedItems())))

        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.addWidget(_hint(
            "<i>The codebook snapshots itself before every merge, delete, and "
            "reparent. Tag a version before a big reorganisation.</i>"))
        layout.addWidget(tag_button)
        layout.addWidget(self.version_list, 1)
        layout.addWidget(self.restore_button)
        return tab

    def _build_diary_tab(self) -> QWidget:
        self.diary_list = QListWidget()
        self.diary_list.setWordWrap(True)
        self.diary_list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.diary_list.setToolTip("Your notes about the whole project, newest first.")
        self.diary_add = QPushButton("Add a diary note…")
        self.diary_add.clicked.connect(self._add_diary_note)
        self.diary_add.setToolTip(
            "Notes about the project as a whole: your position, your question,\n"
            "problems, worries about ethics, what to do next.")
        self.diary_delete = QPushButton("Delete selected")
        self.diary_delete.clicked.connect(self._delete_diary_note)
        self.diary_delete.setToolTip("Delete the selected note. This cannot be undone.")

        buttons = QHBoxLayout()
        buttons.addWidget(self.diary_add)
        buttons.addWidget(self.diary_delete)
        buttons.addStretch(1)

        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.addWidget(_hint(
            "<i>A research diary: write down what you think is happening, what is "
            "going wrong, and what you assume. It becomes part of your audit trail "
            "and the raw material for your methods section. Notes about one code "
            "go on the Code tab instead.</i>"))
        layout.addLayout(buttons)
        layout.addWidget(self.diary_list, 1)
        return tab

    # -- data ----------------------------------------------------------------
    def set_theme_mode(self, mode: str, palette: str = "") -> None:
        self._theme_mode = mode if mode in ("dark", "light") else "dark"
        self._refresh_color_swatch()

    def refresh(self) -> None:
        if not self._service.is_open:
            self.model.set_codebook([], {})
            self.summary_label.setText("<i>No project open.</i>")
            self.health_label.setText("")
            self.version_list.clear()
            self.memo_list.clear()
            self.diary_list.clear()
            self._set_editor_enabled(False)
            return

        codes = self._service.codebook()
        frequency = self._service.code_frequency()
        self.model.set_codebook(codes, frequency)
        self.tree.expandAll()
        applied = sum(1 for c in codes if frequency.get(c.code_id, 0))
        self.summary_label.setText(
            f"<b>{len(codes)} code(s)</b>, {applied} applied.")

        if self._selected_code_id and self.model.code(self._selected_code_id):
            self._select_code(self._selected_code_id)
        else:
            self._selected_code_id = ""
            self._set_editor_enabled(False)
        self._refresh_health()
        self._refresh_versions()
        self._refresh_diary()

    def _refresh_diary(self) -> None:
        self.diary_list.clear()
        notes = sorted(self._service.list_memos("project"),
                       key=lambda m: (m.created_at, m.memo_id), reverse=True)
        for memo in notes:
            first, _sep, body = memo.text.partition("\n")
            summary = " ".join(body.split()) or " ".join(first.split())
            stamp = (memo.created_at or "")[:10]
            item = QListWidgetItem(f"{stamp} · {first.strip()} — {summary}"
                                   if body.strip() else f"{stamp} · {first.strip()}")
            item.setData(Qt.ItemDataRole.UserRole, memo.memo_id)
            item.setToolTip(memo.text)
            self.diary_list.addItem(item)

    def _refresh_health(self) -> None:
        health = self._service.codebook_health()
        if health["is_clean"]:
            self.health_label.setText(
                success_span("<b>No issues found</b> — every code is applied "
                             "and defined."))
            return
        rows = []
        for label, key, why in [
            ("Never applied", "dead",
             "created but never used — merge or delete"),
            ("Applied once", "singletons",
             "may be too specific, or may be a genuine outlier"),
            ("Missing a definition", "undefined",
             "a code without a definition is not reproducible"),
            ("Parent code missing", "orphans",
             "shown at the top level until reparented"),
            ("Nested very deep", "too_deep",
             "usually a reparent gone wrong"),
        ]:
            entries = health[key]
            if not entries:
                continue
            names = ", ".join(d["name"] for d in entries[:12])
            if len(entries) > 12:
                names += f", … (+{len(entries) - 12})"
            rows.append(f"<p><b>{label}</b> ({len(entries)}) — <i>{why}</i><br>{names}</p>")
        self.health_label.setText("".join(rows))

    def _refresh_versions(self) -> None:
        self.version_list.clear()
        for version in self._service.list_codebook_versions():
            label = f"{version['created_at']} · {version['trigger']}"
            if version["note"]:
                label += f" · {version['note']}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, version["version_id"])
            self.version_list.addItem(item)

    def _refresh_memos(self) -> None:
        self.memo_list.clear()
        if not self._selected_code_id:
            return
        for memo in self._service.list_memos("code", self._selected_code_id):
            item = QListWidgetItem(" ".join(memo.text.split()))
            item.setData(Qt.ItemDataRole.UserRole, memo.memo_id)
            item.setToolTip(memo.text)
            self.memo_list.addItem(item)

    # -- selection -----------------------------------------------------------
    def _set_editor_enabled(self, enabled: bool) -> None:
        for widget in (self.name_edit, self.definition_edit, self.use_when_edit,
                       self.leave_out_edit, self.examples_edit, self.save_button):
            widget.setEnabled(enabled)
        if not enabled:
            self.name_edit.clear()
            self.definition_edit.clear()
            self.use_when_edit.clear()
            self.leave_out_edit.clear()
            self.examples_edit.clear()
            self.parent_label.setText("—")
            self.uses_label.setText("—")

    def _select_code(self, code_id: str) -> None:
        index = self.model.index_for_code(code_id)
        if index.isValid():
            self.tree.setCurrentIndex(index)

    def _on_selection_changed(self) -> None:
        index = self.tree.currentIndex()
        code_id = self.model.code_id_at(index)
        code = self.model.code(code_id)
        if code is None:
            self._selected_code_id = ""
            self._set_editor_enabled(False)
            self.memo_list.clear()
            self._refresh_main()
            return
        self._selected_code_id = code_id
        self._set_editor_enabled(True)
        self.name_edit.setText(code.name)
        self.definition_edit.setPlainText(code.definition or "")
        self.use_when_edit.setPlainText(code.inclusion_criteria or "")
        self.leave_out_edit.setPlainText(code.exclusion_criteria or "")
        self.examples_edit.setPlainText("\n".join(code.examples or []))
        parent = self.model.code(code.parent_id or "")
        self.parent_label.setText(parent.name if parent else "(top level)")
        self.uses_label.setText(str(self._service.code_frequency().get(code_id, 0)))
        self._refresh_color_swatch()
        self._refresh_memos()
        self._refresh_main()

    def _refresh_main(self) -> None:
        """One filled button: Add a code until a code is chosen, then Save changes."""
        chosen = bool(self._selected_code_id)
        for button, on in ((self.save_button, chosen), (self.add_button, not chosen)):
            if bool(button.property("main")) != on:
                button.setProperty("main", on)
                button.style().unpolish(button)
                button.style().polish(button)

    def current_code_id(self) -> str:
        return self._selected_code_id

    # -- editing -------------------------------------------------------------
    def _choose_color(self) -> None:
        from PySide6.QtWidgets import QColorDialog

        if not self._selected_code_id:
            return
        code = self._service.get_code(self._selected_code_id)
        current = self._service.code_color_overrides().get(code.name, "")
        initial = QColor(current) if current else QColor("#5A9BC4")
        chosen = QColorDialog.getColor(initial, self, f"Colour for '{code.name}'")
        if chosen.isValid():
            self._set_color(chosen.name())

    def _set_color(self, hex_color) -> None:
        if not self._selected_code_id:
            return
        code = self._service.get_code(self._selected_code_id)
        self._service.set_code_color(code.name, hex_color)
        self.status.emit(
            f"'{code.name}' now uses {hex_color}." if hex_color
            else f"'{code.name}' follows the palette again.")

    def _refresh_color_swatch(self) -> None:
        code = self._service.get_code(self._selected_code_id) if self._selected_code_id else None
        if code is None:
            self.color_swatch.setStyleSheet("")
            return
        override = self._service.code_color_overrides().get(code.name, "")
        colors = code_colors([c.name for c in self._service.codebook()],
                             self._theme_mode,
                             overrides=self._service.code_color_overrides())
        shown = override or colors.get(code.name, QColor("#888888")).name()
        self.color_swatch.setStyleSheet(
            f"background:{shown};border:1px solid palette(mid);border-radius:3px;")
        self.color_clear.setEnabled(bool(override))

    def _save_code(self) -> None:
        if not self._selected_code_id:
            return
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Name required", "A code needs a name.")
            return
        code_id = self._selected_code_id
        # Read every field first: pushing the edit refreshes the screen, which
        # reloads the editors from the store and would discard what is typed.
        use_when = self.use_when_edit.toPlainText().strip()
        leave_out = self.leave_out_edit.toPlainText().strip()
        examples = [line.strip() for line in
                    self.examples_edit.toPlainText().splitlines() if line.strip()]
        self._undo.push(EditCodeCommand(
            self._service, code_id, name,
            self.definition_edit.toPlainText().strip()))
        # The coding rules are not on the undo stack: they are written to the
        # project history instead. Only changed fields are written, so saving a
        # rename does not add a history entry about rules nobody touched.
        stored = self._service.get_code(code_id)
        rules_changed = stored is not None and (
            use_when != (stored.inclusion_criteria or "").strip()
            or leave_out != (stored.exclusion_criteria or "").strip()
            or examples != [e.strip() for e in (stored.examples or [])])
        if rules_changed:
            self._service.set_code_rules(
                code_id, use_when=use_when, leave_out_when=leave_out,
                examples=examples)
            self.status.emit(
                f"Saved '{name}' and its coding rules.  "
                "(Ctrl+Z undoes the name and definition only.)")
            return
        self.status.emit(f"Saved '{name}'.  (Ctrl+Z to undo)")

    def _add_code(self, parent_id: Optional[str] = None) -> None:
        name, ok = QInputDialog.getText(self, "Add a code", "Code name:")
        if not ok or not name.strip():
            return
        command = AddCodeCommand(self._service, name.strip(), "", parent_id)
        self._undo.push(command)
        if command.code_id:
            self._selected_code_id = command.code_id
            self._select_code(command.code_id)
        self.status.emit(f"Added '{name.strip()}'.  (Ctrl+Z to undo)")

    def _on_reparent_requested(self, code_id: str, new_parent_id: str) -> None:
        try:
            self._undo.push(ReparentCodeCommand(self._service, code_id, new_parent_id))
        except ValueError as exc:
            # The model refuses cyclic drops, so this is the store's belt-and-
            # braces check firing — report it rather than swallowing it.
            QMessageBox.warning(self, "Could not move that code", str(exc))
            return
        code = self._service.get_code(code_id)
        target = self._service.get_code(new_parent_id) if new_parent_id else None
        self.status.emit(
            f"Moved '{code.name if code else code_id}' "
            f"{'under ' + target.name if target else 'to the top level'}."
            "  (Ctrl+Z to undo)")

    # -- context menu --------------------------------------------------------
    def _show_context_menu(self, point) -> None:
        index = self.tree.indexAt(point)
        code_id = self.model.code_id_at(index)
        code = self.model.code(code_id)
        menu = QMenu(self)

        add_root = QAction("Add a top-level code…", self)
        add_root.triggered.connect(lambda: self._add_code(None))
        menu.addAction(add_root)

        if code is not None:
            add_child = QAction(f"Add a code under '{code.name}'…", self)
            add_child.triggered.connect(lambda: self._add_code(code_id))
            menu.addAction(add_child)
            menu.addSeparator()

            promote = QAction("Move to the top level", self)
            promote.setEnabled(bool(code.parent_id))
            promote.triggered.connect(lambda: self._on_reparent_requested(code_id, ""))
            menu.addAction(promote)

            merge = QAction(f"Merge '{code.name}' into…", self)
            merge.triggered.connect(lambda: self._merge_code(code_id))
            menu.addAction(merge)

            delete = QAction(f"Delete '{code.name}'…", self)
            delete.triggered.connect(lambda: self._delete_code(code_id))
            menu.addAction(delete)

        menu.exec(self.tree.viewport().mapToGlobal(point))

    # -- merge and delete (not undoable; see the module docstring) -----------
    def _merge_code(self, from_id: str) -> None:
        codes = [c for c in self._service.codebook() if c.code_id != from_id]
        if not codes:
            QMessageBox.information(self, "Nothing to merge into",
                                    "There is only one code in this codebook.")
            return
        source = self._service.get_code(from_id)
        target = _pick_code(self, codes, f"Merge '{source.name}' into which code?")
        if target is None:
            return
        self._do_merge(from_id, target)

    def _do_merge(self, from_id: str, into_id: str) -> None:
        source = self._service.get_code(from_id)
        target = self._service.get_code(into_id)
        uses = self._service.code_frequency().get(from_id, 0)
        confirmed = QMessageBox.warning(
            self, "Merge codes?",
            f"Merge '{source.name}' into '{target.name}'?\n\n"
            f"• {uses} application(s) move to '{target.name}'\n"
            f"• any codes nested under '{source.name}' move to '{target.name}'\n"
            f"• memos on '{source.name}' move to '{target.name}'\n"
            f"• '{source.name}' is then deleted\n\n"
            "The codebook is snapshotted first, so the code can be restored from "
            "History — but the applications stay merged. This is not undoable "
            "with Ctrl+Z.",
            QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes,
            QMessageBox.StandardButton.Cancel)
        if confirmed != QMessageBox.StandardButton.Yes:
            return
        try:
            self._service.merge_codes(from_id, into_id)
        except ValueError as exc:
            QMessageBox.warning(self, "Could not merge", str(exc))
            return
        # Earlier undo entries may name a code that no longer exists, so they can
        # no longer be trusted to mean what they said.
        self._undo.clear()
        self._selected_code_id = into_id
        self.status.emit(f"Merged '{source.name}' into '{target.name}'.")

    def _delete_code(self, code_id: str) -> None:
        code = self._service.get_code(code_id)
        uses = self._service.code_frequency().get(code_id, 0)
        children = len(self.model.descendants(code_id))
        warning = f"Delete '{code.name}'?\n\n"
        if uses:
            warning += (f"• {uses} application(s) of this code will be deleted "
                        f"with it — that coding is lost\n")
        else:
            warning += "• it has never been applied, so no coding is affected\n"
        if children:
            warning += f"• {children} nested code(s) move to the top level\n"
        warning += ("\nThe codebook is snapshotted first, so the code can be "
                    "restored from History — but its applications cannot. "
                    "Consider merging instead. This is not undoable with Ctrl+Z.")
        confirmed = QMessageBox.warning(
            self, "Delete code?", warning,
            QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes,
            QMessageBox.StandardButton.Cancel)
        if confirmed != QMessageBox.StandardButton.Yes:
            return
        self._service.delete_code(code_id)
        self._undo.clear()
        self._selected_code_id = ""
        self.status.emit(f"Deleted '{code.name}'.")

    # -- similarity suggestions (worker thread) ------------------------------
    def _find_similar(self) -> None:
        """Embed every code and rank pairs by cosine similarity.

        On a worker: this loads the sentence-transformer model, which takes
        seconds on a cold cache and would freeze the window. The GUI thread
        never touches the store here — `similar_code_pairs` is a pure function
        over a list of codes read before the task starts.
        """
        codes = self._service.codebook()
        if len(codes) < 2:
            QMessageBox.information(self, "Not enough codes",
                                    "At least two codes are needed to compare.")
            return
        self.find_similar_button.setEnabled(False)
        self.find_similar_button.setText("Comparing codes…")
        self.status.emit("Comparing what the codes mean…")

        run_task(
            _compute_similar_pairs, codes,
            on_finished=self._on_similar_found,
            on_failed=self._on_similar_failed,
            on_done=self._reset_similar_button,
        )

    def _reset_similar_button(self) -> None:
        self.find_similar_button.setEnabled(True)
        self.find_similar_button.setText("Find similar codes")

    def _on_similar_found(self, pairs: List[Dict[str, Any]]) -> None:
        self._suggestions = pairs
        self.suggestions_list.clear()
        if not pairs:
            self.status.emit("No code pairs cleared the similarity threshold.")
            return
        for pair in pairs:
            item = QListWidgetItem(
                f"{pair['name_a']}  ≈  {pair['name_b']}   ({pair['similarity']:.2f})")
            item.setData(Qt.ItemDataRole.UserRole, pair)
            self.suggestions_list.addItem(item)
        self.status.emit(f"{len(pairs)} similar pair(s) — review each before merging.")

    def _on_similar_failed(self, message: str, _traceback: str) -> None:
        # A missing model is an ordinary, expected state (models are downloaded
        # in a separate step by design), so it gets an explanation, not a crash
        # report.
        QMessageBox.information(self, "Could not compare codes", message)
        self.status.emit("Similarity check did not run.")

    def _merge_selected_pair(self) -> None:
        items = self.suggestions_list.selectedItems()
        if not items:
            return
        pair = items[0].data(Qt.ItemDataRole.UserRole)
        self._do_merge(pair["code_id_a"], pair["code_id_b"])
        self.suggestions_list.clear()
        self._suggestions = []

    # -- versions ------------------------------------------------------------
    def _tag_version(self) -> None:
        note, ok = QInputDialog.getText(
            self, "Tag this codebook", "Note (e.g. 'before spring reorg'):")
        if not ok:
            return
        self._service.tag_codebook_version(note.strip())
        self.status.emit("Codebook tagged.")

    def _restore_version(self) -> None:
        items = self.version_list.selectedItems()
        if not items:
            return
        version_id = items[0].data(Qt.ItemDataRole.UserRole)
        confirmed = QMessageBox.warning(
            self, "Restore the codebook?",
            f"Restore the codebook to:\n\n{items[0].text()}\n\n"
            "• codes in both keep their coding\n"
            "• codes added after the snapshot are deleted, with their coding\n\n"
            "The project file is backed up first, and the current codebook is "
            "snapshotted, so this is itself reversible.",
            QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes,
            QMessageBox.StandardButton.Cancel)
        if confirmed != QMessageBox.StandardButton.Yes:
            return
        try:
            self._service.restore_codebook_version(version_id)
        except Exception as exc:  # noqa: BLE001 - report, never crash
            QMessageBox.critical(self, "Restore failed", str(exc))
            return
        self._undo.clear()
        self._selected_code_id = ""
        self.status.emit("Codebook restored. A backup of the project was saved first.")

    # -- memos ---------------------------------------------------------------
    def _add_memo(self) -> None:
        if not self._selected_code_id:
            return
        text, ok = QInputDialog.getMultiLineText(
            self, "Add a memo",
            "Your note about this code. Not sure what to write? Why you chose "
            "this name, what you decided about borderline passages, a passage "
            "that tested it, or how your thinking changed.")
        if not ok or not text.strip():
            return
        self._service.add_memo("code", self._selected_code_id, text.strip())
        self.status.emit("Memo saved.")

    def _add_diary_note(self) -> None:
        if not self._service.is_open:
            return
        dialog = _DiaryNoteDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted or not dialog.text():
            return
        self._service.add_memo("project", None, f"{dialog.topic()}\n{dialog.text()}")
        self.status.emit("Diary note saved.")

    def _delete_diary_note(self) -> None:
        items = self.diary_list.selectedItems()
        if not items:
            return
        self._service.delete_memo(items[0].data(Qt.ItemDataRole.UserRole))
        self.status.emit("Diary note deleted.")

    def _delete_memo(self) -> None:
        items = self.memo_list.selectedItems()
        if not items:
            return
        self._service.delete_memo(items[0].data(Qt.ItemDataRole.UserRole))
        self.status.emit("Memo deleted.")

    # -- YAML exchange -------------------------------------------------------
    def _export_yaml(self) -> None:
        if not self._service.is_open:
            return
        path, _filter = QFileDialog.getSaveFileName(
            self, "Export the codebook", "codebook.yaml", "YAML (*.yaml *.yml)")
        if not path:
            return
        try:
            from pathlib import Path

            Path(path).write_text(self._service.export_codebook_yaml(),
                                  encoding="utf-8")
        except OSError as exc:
            QMessageBox.critical(self, "Could not write the file", str(exc))
            return
        self.status.emit(f"Codebook exported to {path}.")

    def _import_yaml(self) -> None:
        if not self._service.is_open:
            return
        path, _filter = QFileDialog.getOpenFileName(
            self, "Import a codebook", "", "YAML (*.yaml *.yml);;All files (*)")
        if not path:
            return
        try:
            from pathlib import Path

            result = self._service.import_codebook_yaml(
                Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, "Could not import that codebook", str(exc))
            return
        message = (f"Created {len(result['created'])} code(s); skipped "
                   f"{len(result['skipped_existing'])} already present.")
        if result["parents_unresolved"]:
            message += f" Unresolved parents: {', '.join(result['parents_unresolved'])}."
        self._undo.clear()      # imported ids are new; earlier undo entries are stale
        self.status.emit(message)


def _compute_similar_pairs(codes) -> List[Dict[str, Any]]:
    """Worker body: embed the codes and rank similar pairs.

    A module-level function rather than a closure so it is picklable-ish and,
    more importantly, obviously free of any reference to a widget or the open
    `Project` — a worker thread must touch neither.
    """
    from analysis.code_similarity import embed_with_model, similar_code_pairs

    return similar_code_pairs(
        codes,
        lambda texts: embed_with_model(texts, _DEFAULT_EMBEDDING_MODEL),
        threshold=_SIMILARITY_THRESHOLD,
    )


def _pick_code(parent: QWidget, codes, prompt: str) -> Optional[str]:
    """Modal picker returning a code_id, or None when cancelled."""
    dialog = QDialog(parent)
    dialog.setWindowTitle("Choose a code")
    combo = QComboBox()
    for code in sorted(codes, key=lambda c: (c.name or "").lower()):
        combo.addItem(code.name, code.code_id)
    buttons = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)

    layout = QVBoxLayout(dialog)
    layout.addWidget(QLabel(prompt))
    layout.addWidget(combo)
    layout.addWidget(buttons)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    return combo.currentData()
