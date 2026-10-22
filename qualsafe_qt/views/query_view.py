"""
Query & Synthesis: where coding turns into findings.

The Qt counterpart of `app/query_page.py`. Four tabs:

* **Query** — boolean retrieval over codes (AND / OR / NOT / brackets / NEAR/n),
  at the excerpt, source, or case unit.
* **Matrix** — cross-tabulate codes against codes, descriptors, or cases.
* **Framework matrix** — cases down the side, themes across the top, each cell
  summarising what that case said about that theme.
* **Cases** — create the rows of that matrix, singly or in bulk from a descriptor.

Two things carried carefully across:

**The unit matters and the tool says so.** The same query answers differently at
"the same passage", "anywhere in the same document", and "anywhere in the same
person's material". The control is prominent and its help text spells out the
difference, because a query whose unit the analyst has not thought about is a
finding they cannot defend.

**A drafted cell is a draft.** `analysis.framework.draft_cell_summary` verifies
every quote the model proposes against the source and drops anything altered —
the same anti-hallucination check interview summaries use. The draft is never
saved until the analyst saves it, and the count of dropped quotes is shown, not
hidden. The LLM call runs on a worker thread, so a slow local model does not
freeze the window.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

import pandas as pd
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QFileDialog, QGroupBox,
    QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMessageBox, QPlainTextEdit, QPushButton, QSplitter, QTableView, QTabWidget,
    QVBoxLayout, QWidget,
)

from qualsafe_qt.models.dataframe_model import DataFrameModel
from qualsafe_qt.theme import banner_style, banner_text
from qualsafe_qt.services.project_service import ProjectService
from qualsafe_qt.services.tasks import run_task
from qualsafe_qt.views.analysis_view import _hint, _table_view
from qualsafe_qt.widgets.more_options import MoreOptions, count_controls

#: Memo target type used to persist a saved query. Matches `app/query_page`.
SAVED_QUERY_TYPE = "saved_query"
#: How many passages to list for a query result or a framework cell.
_MAX_SHOWN = 60


class QueryView(QWidget):
    """Query / Matrix / Framework matrix / Cases."""

    status = Signal(str)
    #: Take me to this passage in the reader: (source_id, char_start, char_end).
    open_in_reader = Signal(str, int, int)

    def __init__(self, service: ProjectService, undo_stack: QUndoStack,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._service = service
        self._undo = undo_stack
        self._coding = pd.DataFrame()
        self._result_rows: List[Dict[str, Any]] = []
        self._cells: Dict[Any, List[str]] = {}
        self._case_labels: Dict[str, str] = {}
        self._matrix = pd.DataFrame()

        self._build_ui()
        service.project_changed.connect(lambda _p: self.refresh())
        service.store_changed.connect(self.refresh)
        self.refresh()

    # -- construction --------------------------------------------------------
    def _build_ui(self) -> None:
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_query_tab(), "Query")
        self.tabs.addTab(self._build_matrix_tab(), "Matrix")
        self.tabs.addTab(self._build_framework_tab(), "Framework matrix")
        self.tabs.addTab(self._build_cases_tab(), "Cases")

        self.empty_label = _hint("<i>No project open.</i>")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addWidget(self.empty_label)
        layout.addWidget(self.tabs, 1)

    def _build_query_tab(self) -> QWidget:
        self.query_edit = QLineEdit()
        self.query_edit.setPlaceholderText(
            'Cost AND NOT FirstGen        "Cost worry" NEAR/200 dropout')
        self.query_edit.returnPressed.connect(self.run_query)
        self.query_edit.setToolTip(
            "Combine codes with AND, OR, NOT, brackets, and NEAR/n.\n"
            'Put multi-word code names in "quotes". Press Enter to run.')

        self.unit = QComboBox()
        for label, value in (("the same passage", "excerpt"),
                             ("the same document", "source"),
                             ("the same case", "case")):
            self.unit.addItem(label, value)
        self.unit.setToolTip(
            "Where the codes must co-occur.\n"
            "Passage: the same piece of text.\n"
            "Document: anywhere in the same document or response.\n"
            "Case: anywhere in the same person's material.\n"
            "The same query gives different answers at each — pick the one you mean.")
        self.unit.currentIndexChanged.connect(self.run_query)

        run_button = QPushButton("Run")
        run_button.clicked.connect(self.run_query)
        run_button.setDefault(True)

        self.saved_queries = QComboBox()
        self.saved_queries.setToolTip("Load a query you saved earlier.")
        # (load/save buttons get their tooltips below)
        load_button = QPushButton("Load")
        load_button.clicked.connect(self._load_saved_query)
        load_button.setToolTip("Put the selected saved query back in the box and run it.")
        save_button = QPushButton("Save this query…")
        save_button.clicked.connect(self._save_query)
        save_button.setToolTip(
            "Name and keep this query, so a question you will ask again\n"
            "does not have to be retyped.")

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Query"))
        row1.addWidget(self.query_edit, 1)
        row1.addWidget(QLabel("Codes co-occur within"))
        row1.addWidget(self.unit)
        row1.addWidget(run_button)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Saved"))
        row2.addWidget(self.saved_queries, 1)
        row2.addWidget(load_button)
        row2.addWidget(save_button)

        self.query_summary = _hint("")
        self.query_warning = _hint("")
        self.query_warning.setVisible(False)
        self.query_warning.setStyleSheet(banner_style("warning"))

        self.results_table = _table_view()
        self.results_model = DataFrameModel()
        self.results_table.setModel(self.results_model)
        self.results_table.doubleClicked.connect(self._open_result)
        self.results_table.setToolTip(
            "Double-click a passage to open it in the reader.")
        export_hint = None

        export_button = QPushButton("Export passages (.csv)…")
        export_button.clicked.connect(self._export_results)
        export_button.setToolTip(
            "Write the listed passages and their codes to a CSV file.")

        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.addWidget(_hint(
            "<i>Combine codes with <b>AND</b>, <b>OR</b>, <b>NOT</b>, brackets, "
            "and <b>NEAR/n</b> (within n characters). Put multi-word code names "
            'in "quotes".</i>'))
        layout.addLayout(row1)
        layout.addLayout(row2)
        layout.addWidget(self.query_warning)
        layout.addWidget(self.query_summary)
        layout.addWidget(self.results_table, 1)
        layout.addWidget(export_button)
        return tab

    def _build_matrix_tab(self) -> QWidget:
        self.matrix_axis = QComboBox()
        self.matrix_axis.currentIndexChanged.connect(self._refresh_matrix)
        self.matrix_axis.setToolTip(
            "Code x Code: how often two codes land on the same passage.\n"
            "Code x Respondent detail: themes by a respondent attribute.\n"
            "Code x Case: passages per code, per person or site.")
        self.matrix_descriptor = QComboBox()
        self.matrix_descriptor.currentIndexChanged.connect(self._refresh_matrix)
        self.matrix_descriptor.setToolTip("Which attribute to break themes down by.")
        self.matrix_normalize = QCheckBox("Prevalence within each group")
        self.matrix_normalize.setToolTip(
            "Normalises by group size, so a large subgroup does not look more "
            "themed simply for being large.")
        self.matrix_normalize.toggled.connect(self._refresh_matrix)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Axes"))
        controls.addWidget(self.matrix_axis)
        controls.addWidget(QLabel("Group by"))
        controls.addWidget(self.matrix_descriptor)
        controls.addWidget(self.matrix_normalize)
        controls.addStretch(1)

        self.matrix_table = _table_view()
        self.matrix_table.setSortingEnabled(False)
        self.matrix_model = DataFrameModel(default_precision=1)
        self.matrix_table.setModel(self.matrix_model)
        self.matrix_table.setToolTip("Every cell counts distinct items, not applications.")
        self.matrix_caption = _hint("")

        export_button = QPushButton("Export matrix (.csv)…")
        export_button.clicked.connect(self._export_matrix)

        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.addWidget(_hint(
            "<i>Cross-tabulate codes against another axis. Every cell counts "
            "distinct items, so a code applied twice to one item counts "
            "once.</i>"))
        layout.addLayout(controls)
        layout.addWidget(self.matrix_caption)
        layout.addWidget(self.matrix_table, 1)
        layout.addWidget(export_button)
        return tab

    def _build_framework_tab(self) -> QWidget:
        # Checkboxes rather than multi-selection: "which themes are columns" is a
        # set of independent yes/no choices, and a fully-selected multi-select
        # list renders as one solid block of highlight colour that says nothing.
        self.fw_codes = QListWidget()
        self.fw_codes.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.fw_codes.setMaximumHeight(140)
        self.fw_codes.itemChanged.connect(lambda _item: self._refresh_framework())
        self.fw_codes.setToolTip(
            "Which themes become the columns of the matrix.\n"
            "More than about six stops being readable on a page.")
        self.fw_uncased = QCheckBox("Include material with no case")
        self.fw_uncased.setToolTip(
            "Gathers everything not assigned to a case under one row, so it is "
            "not invisible.")
        self.fw_uncased.toggled.connect(self._refresh_framework)

        self.fw_grid = _table_view()
        self.fw_grid.setSortingEnabled(False)
        self.fw_grid_model = DataFrameModel()
        self.fw_grid.setModel(self.fw_grid_model)
        self.fw_grid.clicked.connect(self._select_cell_from_grid)
        self.fw_grid.setToolTip(
            "Cases down the side, themes across the top. Each number is how many\n"
            "passages that case has for that theme. Click a cell to work on it.")

        self.fw_case = QComboBox()
        self.fw_case.currentIndexChanged.connect(self._refresh_cell)
        self.fw_code = QComboBox()
        self.fw_code.currentIndexChanged.connect(self._refresh_cell)
        self.fw_case.setToolTip("Which case (person, site, or group) this cell is for.")
        self.fw_code.setToolTip("Which theme this cell is about.")

        self.fw_passages = QPlainTextEdit()
        self.fw_passages.setReadOnly(True)
        self.fw_summary = QPlainTextEdit()
        self.fw_summary.setPlaceholderText(
            "What did this case say about this theme?")
        self.fw_passages.setToolTip(
            "Everything this case said that carries this theme.")
        self.fw_summary.setToolTip(
            "Your summary of this cell. This is the cell of the framework matrix\n"
            "you would put in a paper.")
        self.fw_cell_label = _hint("")

        self.fw_draft_button = QPushButton("Draft with the local language model")
        self.fw_draft_button.clicked.connect(self._draft_cell)
        self.fw_draft_button.setToolTip(
            "Requires Ollama running locally. Every quote it offers is checked "
            "verbatim against the source; anything altered is dropped. The draft "
            "is not saved until you save it.")
        save_button = QPushButton("Save cell")
        save_button.clicked.connect(self._save_cell)
        save_button.setToolTip("Save this cell summary into the project.")

        cell_buttons = QHBoxLayout()
        cell_buttons.addWidget(self.fw_draft_button)
        cell_buttons.addWidget(save_button)
        cell_buttons.addStretch(1)

        export_button = QPushButton("Export grid (.csv)…")
        export_button.clicked.connect(self._export_framework)
        # A cell is picked by clicking the grid; the pickers, the no-case option and the
        # export are for the less common ways in, so they are folded away.
        self.fw_more = MoreOptions("More options")
        self.fw_more.add_row("Case", self.fw_case)
        self.fw_more.add_row("Theme", self.fw_code)
        self.fw_more.body_layout.addWidget(self.fw_uncased)
        self.fw_more.body_layout.addWidget(export_button)
        self.fw_more._count = count_controls(self.fw_more.body)
        self.fw_more._refresh_title()

        cell_box = QGroupBox("Cell")
        cell_layout = QVBoxLayout(cell_box)
        cell_layout.addWidget(self.fw_cell_label)
        cell_layout.addWidget(QLabel("The passages behind this cell"))
        cell_layout.addWidget(self.fw_passages, 1)
        cell_layout.addWidget(QLabel("Cell summary"))
        cell_layout.addWidget(self.fw_summary, 1)
        cell_layout.addLayout(cell_buttons)
        cell_layout.addWidget(self.fw_more)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(QLabel("Themes (columns)"))
        left_layout.addWidget(self.fw_codes)
        left_layout.addWidget(self.fw_grid, 1)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(cell_box)
        splitter.setSizes([760, 700])

        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.addWidget(_hint(
            "<i>Cases down the side, themes across the top; each cell says what "
            "that case said about that theme. Click a cell in the grid to work "
            "on it.</i>"))
        layout.addWidget(splitter, 1)
        return tab

    def _build_cases_tab(self) -> QWidget:
        self.cases_table = _table_view()
        self.cases_model = DataFrameModel()
        self.cases_table.setModel(self.cases_model)
        self.cases_table.setToolTip(
            "Cases in this project, and how many sources belong to each.")

        self.case_name = QLineEdit()
        self.case_name.setPlaceholderText("New case name")
        self.case_kind = QComboBox()
        self.case_kind.addItems(["person", "site", "group"])
        self.case_name.setToolTip("A name for the person, site, or group.")
        self.case_kind.setToolTip(
            "What kind of unit this is. Free text elsewhere in the file —\n"
            "these three cover most projects.")
        create_button = QPushButton("Create case")
        create_button.clicked.connect(self._create_case)
        create_button.setToolTip("Create one case. Assign documents to it on the Documents screen.")

        create_row = QHBoxLayout()
        create_row.addWidget(self.case_name, 1)
        create_row.addWidget(self.case_kind)
        create_row.addWidget(create_button)

        self.bulk_field = QComboBox()
        bulk_button = QPushButton("Create cases from this field")
        bulk_button.clicked.connect(self._bulk_create_cases)
        self.bulk_field.setToolTip(
            "Make one case per distinct value of this field, assigning every\n"
            "source automatically. Running it twice reuses the cases.")
        bulk_button.setToolTip("Create the cases and assign their sources.")

        bulk_row = QHBoxLayout()
        bulk_row.addWidget(QLabel("Field"))
        bulk_row.addWidget(self.bulk_field, 1)
        bulk_row.addWidget(bulk_button)

        bulk_box = QGroupBox("Create cases in bulk")
        bulk_layout = QVBoxLayout(bulk_box)
        bulk_layout.addWidget(_hint(
            "<i>Turn a respondent detail (or the wide-form respondent id) into one case "
            "per value, assigning every source automatically — the quick way to "
            "make survey data case-based.</i>"))
        bulk_layout.addLayout(bulk_row)

        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.addWidget(_hint(
            "<i>A case is the person, site, or group a document or response "
            "belongs to — the row of a framework matrix.</i>"))
        layout.addWidget(self.cases_table, 1)
        layout.addLayout(create_row)
        layout.addWidget(bulk_box)
        return tab

    # -- data ----------------------------------------------------------------
    def refresh(self) -> None:
        if not self._service.is_open:
            self.empty_label.setText("<i>No project open.</i>")
            self.empty_label.setVisible(True)
            self.tabs.setVisible(False)
            return
        self._coding = self._service.coding_spans_table()
        if self._coding.empty:
            self.empty_label.setText(
                "<i>Nothing is coded in this project yet — code some passages "
                "on the Documents screen first.</i>")
            self.empty_label.setVisible(True)
            self.tabs.setVisible(False)
            return
        self.empty_label.setVisible(False)
        self.tabs.setVisible(True)
        self._refresh_saved_queries()
        self._refresh_matrix_axes()
        self._refresh_framework_codes()
        self._refresh_cases()

    # -- query ---------------------------------------------------------------
    def _refresh_saved_queries(self) -> None:
        self.saved_queries.clear()
        for memo in self._service.list_memos(SAVED_QUERY_TYPE):
            name, _sep, text = memo.text.partition("\n")
            self.saved_queries.addItem(name, text)

    def _load_saved_query(self) -> None:
        text = self.saved_queries.currentData()
        if text:
            self.query_edit.setText(text)
            self.run_query()

    def _save_query(self) -> None:
        text = self.query_edit.text().strip()
        if not text:
            return
        name, ok = QInputDialog.getText(self, "Save this query",
                                        "Name it (e.g. 'Cost without first-gen'):")
        if not ok or not name.strip():
            return
        self._service.add_memo(SAVED_QUERY_TYPE, "", f"{name.strip()}\n{text}")
        self.status.emit(f"Saved query '{name.strip()}'.")

    def run_query(self) -> None:
        from analysis.query import QueryError, run_query

        text = self.query_edit.text().strip()
        if not text or self._coding.empty:
            return
        unit = self.unit.currentData()
        try:
            result = run_query(self._coding, text, unit=unit)
        except QueryError as exc:
            # A malformed query is user input; say what is wrong, do not crash.
            self.query_warning.setText(banner_text("warning", f"<b>{_escape(str(exc))}</b>"))
            self.query_warning.setVisible(True)
            self.query_summary.setText("")
            self.results_model.set_frame(pd.DataFrame())
            return

        if result["unknown_codes"]:
            self.query_warning.setText(banner_text("warning",
                "<b>Not in this project's codebook:</b> "
                + ", ".join(f"<code>{_escape(c)}</code>"
                            for c in result["unknown_codes"])
                + " — check the spelling, or quote a multi-word name."))
            self.query_warning.setVisible(True)
        else:
            self.query_warning.setVisible(False)

        unit_label = {"excerpt": "passage", "source": "document",
                      "case": "case"}[unit]
        self.query_summary.setText(
            f"<b>{len(result['unit_ids'])}</b> {unit_label}(s) match, covering "
            f"<b>{len(result['excerpt_ids'])}</b> passage(s). "
            "Double-click a passage to open it in the reader.")
        self._show_results(result["excerpt_ids"])

    def _show_results(self, excerpt_ids: List[str]) -> None:
        codes_by_excerpt = (self._coding.groupby("excerpt_id")["code_name"]
                            .apply(lambda s: ", ".join(sorted(set(s)))).to_dict())
        spans = (self._coding.drop_duplicates("excerpt_id")
                 .set_index("excerpt_id")[["source_id", "char_start", "char_end"]])
        rows = []
        for excerpt_id in excerpt_ids[:_MAX_SHOWN]:
            excerpt = self._service.get_excerpt(excerpt_id)
            if excerpt is None or excerpt_id not in spans.index:
                continue
            span = spans.loc[excerpt_id]
            rows.append({
                "passage": " ".join((excerpt.text or "").split()),
                "codes": codes_by_excerpt.get(excerpt_id, ""),
                "_source_id": span["source_id"],
                "_start": int(span["char_start"]),
                "_end": int(span["char_end"]),
            })
        self._result_rows = rows
        # The underscore-prefixed navigation columns are for the double-click
        # handler, not for reading; keep them out of the table.
        self.results_model.set_frame(
            pd.DataFrame([{k: v for k, v in r.items() if not k.startswith("_")}
                          for r in rows]))
        if len(excerpt_ids) > _MAX_SHOWN:
            self.status.emit(
                f"Showing the first {_MAX_SHOWN} of {len(excerpt_ids)} passages.")

    def _open_result(self, index) -> None:
        if 0 <= index.row() < len(self._result_rows):
            row = self._result_rows[index.row()]
            self.open_in_reader.emit(row["_source_id"], row["_start"], row["_end"])

    def _export_results(self) -> None:
        self._export(self.results_model.frame, "query_results.csv", index=False)

    # -- matrix --------------------------------------------------------------
    def _refresh_matrix_axes(self) -> None:
        descriptors = self._service.descriptor_table()
        keys = sorted(set(descriptors["key"])) if not descriptors.empty else []

        self.matrix_axis.blockSignals(True)
        self.matrix_axis.clear()
        self.matrix_axis.addItem("Code × Code", "code")
        if keys:
            self.matrix_axis.addItem("Code × Respondent detail", "descriptor")
        self.matrix_axis.addItem("Code × Case", "case")
        self.matrix_axis.blockSignals(False)

        self.matrix_descriptor.blockSignals(True)
        self.matrix_descriptor.clear()
        self.matrix_descriptor.addItems(keys)
        self.matrix_descriptor.blockSignals(False)
        self._refresh_matrix()

    def _refresh_matrix(self) -> None:
        if not self._service.is_open or self._coding.empty:
            return
        axis = self.matrix_axis.currentData()
        is_descriptor = axis == "descriptor"
        self.matrix_descriptor.setEnabled(is_descriptor)
        self.matrix_normalize.setEnabled(is_descriptor)

        if axis == "code":
            from analysis.cooccurrence import cooccurrence_matrix

            table, _drill = cooccurrence_matrix(self._service.coding_table())
            self.matrix_caption.setText(
                "<i>How often two codes are applied to the same passage.</i>")
        elif is_descriptor:
            from analysis.crosstab import code_by_descriptor

            key = self.matrix_descriptor.currentText()
            if not key:
                return
            table, _drill = code_by_descriptor(
                self._service.coding_table(), self._service.descriptor_table(), key,
                normalize="group_size" if self.matrix_normalize.isChecked() else None)
            self.matrix_caption.setText(
                f"<i>Codes by <b>{_escape(key)}</b>.</i>")
        else:
            cased = self._coding[self._coding["case_id"] != ""]
            if cased.empty:
                self.matrix_model.set_frame(pd.DataFrame())
                self.matrix_caption.setText(
                    "<i>No documents are assigned to a case yet — see the Cases "
                    "tab.</i>")
                return
            table = (cased.drop_duplicates(["excerpt_id", "code_name", "case_name"])
                     .pivot_table(index="code_name", columns="case_name",
                                  values="excerpt_id", aggfunc="count", fill_value=0))
            self.matrix_caption.setText(
                "<i>Passages per code, per case.</i>")
        self._matrix = table
        self.matrix_model.set_frame(table)

    def _export_matrix(self) -> None:
        self._export(self._matrix, "matrix.csv", index=True)

    # -- framework matrix ----------------------------------------------------
    def _chosen_codes(self) -> List[str]:
        """Themes ticked as framework columns, in codebook order."""
        return [self.fw_codes.item(i).text()
                for i in range(self.fw_codes.count())
                if self.fw_codes.item(i).checkState() == Qt.CheckState.Checked]

    def _refresh_framework_codes(self) -> None:
        codes = sorted(set(self._coding["code_name"]))
        chosen = set(self._chosen_codes())
        self.fw_codes.blockSignals(True)
        self.fw_codes.clear()
        for name in codes:
            item = QListWidgetItem(name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            # Default to the first six, matching the Streamlit page — a
            # framework matrix wider than that stops being readable.
            ticked = name in chosen if chosen else name in codes[:6]
            item.setCheckState(Qt.CheckState.Checked if ticked
                               else Qt.CheckState.Unchecked)
            self.fw_codes.addItem(item)
        self.fw_codes.blockSignals(False)
        self._refresh_framework()

    def _refresh_framework(self) -> None:
        from analysis.framework import UNCASED, framework_cells, framework_grid

        if not self._service.is_open or self._coding.empty:
            return
        codes = self._chosen_codes()
        cases = self._service.list_cases()
        include_uncased = self.fw_uncased.isChecked()
        if not codes:
            self.fw_grid_model.set_frame(pd.DataFrame())
            return

        self._cells = framework_cells(self._coding, code_names=codes,
                                      include_uncased=include_uncased)
        labels = {c.case_id: c.name for c in cases}
        if include_uncased:
            labels[UNCASED] = UNCASED
        self._case_labels = labels
        self.fw_grid_model.set_frame(framework_grid(self._cells, labels, codes))

        self.fw_case.blockSignals(True)
        previous_case = self.fw_case.currentData()
        self.fw_case.clear()
        for case_id, label in labels.items():
            self.fw_case.addItem(label, case_id)
        index = self.fw_case.findData(previous_case)
        if index >= 0:
            self.fw_case.setCurrentIndex(index)
        self.fw_case.blockSignals(False)

        self.fw_code.blockSignals(True)
        previous_code = self.fw_code.currentText()
        self.fw_code.clear()
        self.fw_code.addItems(codes)
        if previous_code in codes:
            self.fw_code.setCurrentText(previous_code)
        self.fw_code.blockSignals(False)
        self._refresh_cell()

    def _select_cell_from_grid(self, index) -> None:
        frame = self.fw_grid_model.frame
        if frame.empty or index.column() == 0:
            return
        case_label = str(frame.iat[index.row(), 0])
        code_name = str(frame.columns[index.column()])
        case_index = self.fw_case.findText(case_label)
        if case_index >= 0:
            self.fw_case.setCurrentIndex(case_index)
        code_index = self.fw_code.findText(code_name)
        if code_index >= 0:
            self.fw_code.setCurrentIndex(code_index)

    def _refresh_cell(self) -> None:
        case_id = self.fw_case.currentData()
        code_name = self.fw_code.currentText()
        if not case_id or not code_name:
            self.fw_cell_label.setText("")
            self.fw_passages.clear()
            self.fw_summary.clear()
            return
        excerpt_ids = self._cells.get((case_id, code_name), [])
        self.fw_cell_label.setText(
            f"<b>{len(excerpt_ids)}</b> passage(s) coded "
            f"<b>{_escape(code_name)}</b> for "
            f"<b>{_escape(self.fw_case.currentText())}</b>.")
        passages = self._service.cell_excerpt_texts(excerpt_ids[:20])
        self.fw_passages.setPlainText(
            "\n\n".join(f"• {p}" for p in passages) or "(none)")
        stored = self._service.cell_summary(case_id, code_name)
        self.fw_summary.setPlainText(stored.text if stored is not None else "")
        self.fw_draft_button.setEnabled(bool(passages))

    def _draft_cell(self) -> None:
        """Draft a cell with the local LLM, on a worker thread.

        The Ollama call can take tens of seconds on a local model; running it on
        the GUI thread would freeze the window for the duration. Every quote it
        returns is verified against the source by `draft_cell_summary` before it
        gets here, and the draft is not saved until the analyst saves it.
        """
        case_id = self.fw_case.currentData()
        code_name = self.fw_code.currentText()
        case_label = self.fw_case.currentText()
        excerpt_ids = self._cells.get((case_id, code_name), [])
        passages = self._service.cell_excerpt_texts(excerpt_ids)
        if not passages:
            return
        model = "llama3.2:3b"
        self.fw_draft_button.setEnabled(False)
        self.fw_draft_button.setText("Drafting…")
        self.status.emit(f"Drafting this cell with {model} (local)…")

        run_task(
            _draft_cell, passages, code_name, case_label, model,
            on_finished=self._on_draft_ready,
            on_failed=lambda msg, _tb: self.status.emit(f"Draft failed: {msg}"),
            on_done=lambda: (self.fw_draft_button.setEnabled(True),
                             self.fw_draft_button.setText("Draft with the local language model")),
        )

    def _on_draft_ready(self, out: Dict[str, Any]) -> None:
        from analysis.framework import format_cell

        if out["note"] != "ok":
            QMessageBox.information(
                self, "Could not draft this cell",
                f"{out['note']}\n\nThis needs Ollama running locally. Nothing "
                "has been changed.")
            return
        self.fw_summary.setPlainText(format_cell(out["summary"], out["quotes"]))
        message = "Draft ready — review and edit before saving. Nothing is saved yet."
        if out["dropped"]:
            message += (f"  {out['dropped']} proposed quote(s) were not verbatim "
                        "in the passages and were dropped.")
        self.status.emit(message)

    def _save_cell(self) -> None:
        case_id = self.fw_case.currentData()
        code_name = self.fw_code.currentText()
        if not case_id or not code_name:
            return
        self._service.set_cell_summary(case_id, code_name,
                                       self.fw_summary.toPlainText())
        self.status.emit(f"Saved the '{code_name}' cell for "
                         f"'{self.fw_case.currentText()}'.")

    def _export_framework(self) -> None:
        self._export(self.fw_grid_model.frame, "framework_matrix.csv", index=False)

    # -- cases ---------------------------------------------------------------
    def _refresh_cases(self) -> None:
        cases = self._service.list_cases()
        rows = [{"case": c.name, "kind": c.kind,
                 "sources": len(self._service.case_sources(c.case_id))}
                for c in cases]
        self.cases_model.set_frame(pd.DataFrame(
            rows, columns=["case", "kind", "sources"]))

        descriptors = self._service.descriptor_table()
        options = sorted(set(descriptors["key"])) if not descriptors.empty else []
        if (self._coding["respondent_id"] != "").any():
            options = ["respondent_id"] + options
        self.bulk_field.clear()
        self.bulk_field.addItems(options)
        self.bulk_field.setEnabled(bool(options))

    def _create_case(self) -> None:
        name = self.case_name.text().strip()
        if not name:
            return
        self._service.add_case(name, self.case_kind.currentText())
        self.case_name.clear()
        self.status.emit(f"Created case '{name}'.")

    def _bulk_create_cases(self) -> None:
        field = self.bulk_field.currentText()
        if not field:
            return
        made = self._bulk_create(field)
        self.status.emit(f"Created or updated {made} case(s) from '{field}'.")

    def _bulk_create(self, field: str) -> int:
        """One case per distinct value of `field`, with its sources assigned.

        Mirrors `app/query_page._bulk_create_cases`, including the naming rule
        (`field: value`, except respondent ids which stand alone) so cases built
        in either front end collide rather than duplicate.
        """
        descriptors = self._service.descriptor_table()
        if field == "respondent_id":
            pairs = (self._coding[self._coding["respondent_id"] != ""]
                     [["respondent_id", "source_id"]].drop_duplicates().values.tolist())
        else:
            subset = descriptors[descriptors["key"] == field]
            pairs = subset[["value", "source_id"]].drop_duplicates().values.tolist()

        by_value: Dict[str, List[str]] = {}
        for value, source_id in pairs:
            if str(value).strip():
                by_value.setdefault(str(value), []).append(source_id)

        existing = {c.name: c.case_id for c in self._service.list_cases()}
        for value, source_ids in by_value.items():
            label = str(value) if field == "respondent_id" else f"{field}: {value}"
            case_id = existing.get(label) or self._service.add_case(label)
            existing[label] = case_id
            for source_id in source_ids:
                self._service.assign_source_to_case(case_id, source_id)
        return len(by_value)

    # -- export --------------------------------------------------------------
    def _export(self, frame: pd.DataFrame, suggested: str, *, index: bool) -> None:
        if frame is None or frame.empty:
            QMessageBox.information(self, "Nothing to export",
                                    "There is no table to write yet.")
            return
        path, _filter = QFileDialog.getSaveFileName(
            self, "Export", suggested, "CSV (*.csv)")
        if not path:
            return
        try:
            frame.to_csv(path, index=index, encoding="utf-8")
        except OSError as exc:
            QMessageBox.critical(self, "Could not write the file", str(exc))
            return
        self.status.emit(f"Exported to {path}.")


def _draft_cell(passages, code_name: str, case_label: str, model: str) -> Dict[str, Any]:
    """Worker body: the Ollama round trip plus verbatim quote verification.

    Module-level, so it demonstrably holds no widget and no database connection.
    """
    from analysis.framework import draft_cell_summary
    from engines.ollama_client import OllamaClient

    client = OllamaClient()

    def generate(prompt: str, schema: Dict[str, Any]) -> Dict[str, Any]:
        return client.generate_json(model, prompt, schema)

    return draft_cell_summary(passages, code_name=code_name,
                              case_label=case_label, generate_json=generate)


def _escape(text: str) -> str:
    import html

    return html.escape(str(text))
