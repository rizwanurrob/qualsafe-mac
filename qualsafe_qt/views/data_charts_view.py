"""
Data Charts (desktop): build a chart from any CSV or Excel file.

The desktop half of the Chart Builder. Everything that decides a number, a colour
or a figure lives in `core/chartbuilder/`, which imports no front end; this module
is widgets in, a `ChartConfig` out, an image back. The Streamlit page
(`app/data_charts_page.py`) is the other skin over the same engine, so a chart
made here and the same chart made there are the same figure.

The picture is **the exported image**, rendered by `vl-convert` and shown scaled
to the panel. That is a deliberate choice over painting with `QPainter` like the
project-codings chart screen: line, area and scatter need real axes, and one
renderer means Windows, macOS and the web build produce identical figures. The
price is that the preview is an image, not hover-interactive.

This screen is independent of the open project (it charts a file, not codings),
so it keeps its own undo history rather than sharing the project's `QUndoStack`.
Undo covers the choices about the numbers (fields, filters, recode, sort,
denominator), not titles or colours (`SHAPING_FIELDS`).

Two rules that keep it testable: nothing here opens a modal dialog on a path a
test can reach (a modal blocks forever under the offscreen platform), and file
choosers go through `_ask_save_path` / `_ask_open_path`, which tests replace.
"""

from __future__ import annotations

import hashlib
import html
import json
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QImage, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QFormLayout,
    QFrame, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QPlainTextEdit, QPushButton, QScrollArea, QSizePolicy, QSpinBox, QSplitter,
    QStackedWidget, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

from core.chartbuilder import (
    clean, export, loader, profile, recode_table, recommend, sample, store, survey, themes,
    vocab)
from core.chartbuilder.aggregate import ChartBuildError
from core.chartbuilder.build import build_data
from core.chartbuilder.config import (
    FIGURE_PRESETS, MEASURE_AGGREGATIONS, SHAPING_FIELDS, ChartConfig, EditHistory,
    FilterRule)
from core.chartbuilder.render import build_spec
from qualsafe_qt.theme import banner_style, banner_text
from qualsafe_qt.widgets.info_tip import InfoTip
from qualsafe_qt.widgets.more_options import CONTROL_TYPES, MoreOptions
from core.ux.help import tips as shared_tips
from qualsafe_qt.widgets.theme_dialog import ThemeDialog

#: Milliseconds to wait after the last change before redrawing, so typing a
#: title does not draw a chart per keystroke.
DEBOUNCE_MS = 150
#: Resolution of the on-screen preview (crisp on a 2x display, still quick).
PREVIEW_DPI = 192
#: The four steps of the Charts activity (core/ux/activities.py), in order.
STEP_KEYS = ("open", "question", "adjust", "save")
_NO_FILE = "No file open. Nothing leaves this computer, and the file is never changed."
_GRID_COLUMNS = ["Category", "Rows", "Include", "Display name", "Combine into",
                 "Position", "Colour"]


class _Preview(QLabel):
    """A picture that scales to the space it is given, keeping its shape."""

    def __init__(self) -> None:
        super().__init__()
        self._pixmap: Optional[QPixmap] = None
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(QSize(240, 160))
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)

    def set_image(self, pixmap: Optional[QPixmap]) -> None:
        self._pixmap = pixmap
        self._rescale()

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt name)
        super().resizeEvent(event)
        self._rescale()

    def _rescale(self) -> None:
        if self._pixmap is None or self._pixmap.isNull():
            self.setPixmap(QPixmap())
            return
        self.setPixmap(self._pixmap.scaled(self.size(), Qt.KeepAspectRatio,
                                           Qt.SmoothTransformation))


def _combo(options: Dict[str, str]) -> QComboBox:
    box = QComboBox()
    for key, label in options.items():
        box.addItem(label, key)
    return box


def _set_combo(box: QComboBox, key: str) -> None:
    index = box.findData(key)
    box.setCurrentIndex(index if index >= 0 else 0)


def _with_tip(label: str, widget: QWidget) -> QWidget:
    """`widget` with its (i) beside it, when the label has a tip; otherwise `widget` itself."""
    tip_id = shared_tips.for_label(label)
    if not tip_id:
        return widget
    holder = QWidget()
    row = QHBoxLayout(holder)
    row.setContentsMargins(0, 0, 0, 0)
    row.addWidget(widget, 1)
    row.addWidget(InfoTip(tip_id, about=label), 0, Qt.AlignmentFlag.AlignTop)
    return holder


def _group(title: str, *rows) -> QGroupBox:
    """A titled box; each row is (label, widget) or a lone widget."""
    box = QGroupBox(title)
    form = QFormLayout(box)
    form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
    for row in rows:
        if isinstance(row, tuple):
            form.addRow(row[0], _with_tip(row[0], row[1]))
        else:
            form.addRow(row)
    return box


def _form(*rows) -> QWidget:
    """Labelled rows with no box around them."""
    holder = QWidget()
    form = QFormLayout(holder)
    form.setContentsMargins(0, 0, 0, 0)
    form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
    for row in rows:
        if isinstance(row, tuple):
            form.addRow(row[0], _with_tip(row[0], row[1]))
        else:
            form.addRow(row)
    return holder


def _fold(*parts: QWidget) -> MoreOptions:
    """A closed "More options" panel holding `parts`, titled with how many controls are inside."""
    more = MoreOptions("More options")
    for part in parts:
        more.body_layout.addWidget(part)
    more._count = sum(
        1 for w in more.body.findChildren(QWidget)
        if isinstance(w, CONTROL_TYPES) and not w.objectName().startswith("qt_")
        and not (isinstance(w, QLineEdit) and isinstance(w.parent(), (QComboBox, QSpinBox, QDoubleSpinBox))))
    more._refresh_title()
    return more


class DataChartsView(QWidget):
    """Upload a table, pick a question, get a chart you can put in a report."""

    status = Signal(str)
    #: The person asked to go to another step ("Next"); the shell moves its rail.
    step_requested = Signal(str)

    def __init__(self, service=None, undo=None, parent: Optional[QWidget] = None,
                 storage_root: Optional[Path] = None) -> None:
        super().__init__(parent)
        # `service` and `undo` are accepted so the shell can build every screen the
        # same way; this one charts a file, not the open project. `storage_root`
        # points saved charts and themes somewhere else (tests); normally None,
        # meaning the per-user folder.
        self._root = storage_root
        self._table: Optional[loader.LoadedTable] = None
        self._profile: Optional[profile.TableProfile] = None
        self._cfg = ChartConfig()
        self._hist = EditHistory(self._cfg, fields=SHAPING_FIELDS)
        self._custom_themes: Dict[str, themes.Theme] = store.load_themes(storage_root)
        self._built = None                 # (ChartData, Theme, spec) or an error string
        self._png: Optional[bytes] = None
        self._syncing = False
        self._grid_signature = ""
        self._sheet_source: Optional[Path] = None
        self._subject: tuple = ("single", "", ())
        self._kind_manual = False          # the person chose the kind of question themselves
        self._step = STEP_KEYS[0]

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(DEBOUNCE_MS)
        self._timer.timeout.connect(self._render)

        root = QVBoxLayout(self)
        self._build_toolbar()
        output = self._build_output()
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._build_pages())
        splitter.addWidget(output)
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 7)
        splitter.setSizes([460, 780])
        root.addWidget(splitter, 1)
        self._update_visibility()
        self._show_empty()
        self.set_step(STEP_KEYS[0])

    # ── construction ─────────────────────────────────────────────────────────

    def _build_toolbar(self) -> None:
        """The buttons of the Open step and Undo / Redo / Reset (placed by `_build_pages`)."""
        self.open_button = QPushButton("Open a CSV or Excel file…")
        self.open_button.setProperty("main", True)    # the one filled button until a file is open
        self.sample_button = QPushButton("Try the sample survey")
        self.undo_button = QPushButton("Undo")
        self.redo_button = QPushButton("Redo")
        self.reset_button = QPushButton("Reset chart")
        self.undo_button.setToolTip("Steps back through filters, recoding and sorting.")
        self.reset_button.setToolTip("Clears every choice for this file. Undo brings them back.")
        self.file_label = QLabel(_NO_FILE)
        self.file_label.setWordWrap(True)
        self.open_button.clicked.connect(self._choose_file)
        self.sample_button.clicked.connect(self._sample_clicked)
        self.undo_button.clicked.connect(self.undo)
        self.redo_button.clicked.connect(self.redo)
        self.reset_button.clicked.connect(self.reset_chart)

    def _build_pages(self) -> QWidget:
        """One page per step. A page shows the few things that step needs; the rest is
        in its More options. The controls are the same ones as ever, only arranged."""
        # data
        self.sheet_combo = QComboBox()
        self.sheet_combo.currentIndexChanged.connect(self._sheet_changed)
        self.sheet_combo.setVisible(False)
        self.summary_label = QLabel("")
        self.summary_label.setWordWrap(True)
        self.notes_label = QLabel("")
        self.notes_label.setWordWrap(True)
        self.fields_table = QTableWidget(0, 5)
        self.fields_table.setHorizontalHeaderLabels(["Question", "Type", "Answered", "Blank", "Different answers"])
        self.fields_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.fields_table.setMinimumHeight(140)
        self.fields_table.setMaximumHeight(220)
        self.fields_table.verticalHeader().setVisible(False)
        self.collapse_check = QCheckBox("Treat repeated spaces inside a label as one")
        self.tokens_edit = QLineEdit()
        self.tokens_edit.setToolTip("Empty cells always count as blank. Blanks are never in the "
                                    "base of a percentage unless you choose that below.")
        self.tokens_edit.setPlaceholderText("Answers treated as blank, comma separated")
        self.tokens_edit.setText(", ".join(["NULL", "null", "NaN", "None", "N/A", "NA",
                                            "(blank)", "<null>"]))
        self.collapse_check.toggled.connect(self._quality_changed)
        self.tokens_edit.textChanged.connect(self._quality_changed)

        # question
        self.kind_combo = _combo(vocab.KIND_LABELS)
        self.field_combo = QComboBox()
        self.columns_list = QListWidget()
        self.columns_list.setSelectionMode(QAbstractItemView.MultiSelection)
        self.columns_list.setMaximumHeight(120)
        self.group_list = QListWidget()
        self.group_list.setSelectionMode(QAbstractItemView.MultiSelection)
        self.group_list.setMaximumHeight(100)
        self.agg_combo = _combo(vocab.AGG_LABELS)
        self.pc_combo = _combo({"percent": "Percent", "count": "Count"})
        self.measure_combo = QComboBox()
        self.kind_hint = QLabel("")
        self.kind_hint.setWordWrap(True)
        self.kind_combo.currentIndexChanged.connect(self._kind_changed)
        self.field_combo.currentIndexChanged.connect(self._question_changed)
        self.columns_list.itemSelectionChanged.connect(self._question_changed)
        self.group_list.itemSelectionChanged.connect(self._question_changed)
        self.agg_combo.currentIndexChanged.connect(self._question_changed)
        self.pc_combo.currentIndexChanged.connect(self._question_changed)
        self.measure_combo.currentIndexChanged.connect(self._question_changed)

        # the builders only make the widgets; the pages below arrange them
        self._build_multi_group()
        self._build_refine_group()
        self._build_chart_group()
        self._build_theme_group()
        self._build_saved_group()

        self.next_buttons: Dict[str, QPushButton] = {}
        self._stack = QStackedWidget()
        for key, page in zip(STEP_KEYS, (self._page_open(), self._page_question(),
                                         self._page_adjust(), self._page_save())):
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(page)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            scroll.setFrameShape(QFrame.NoFrame)
            self._stack.addWidget(scroll)
        self._stack.setMinimumWidth(400)
        return self._stack

    def _next_button(self, step: str, text: str) -> QPushButton:
        button = QPushButton(text)
        target = STEP_KEYS[STEP_KEYS.index(step) + 1]
        button.clicked.connect(lambda _=False, k=target: self.go_step(k))
        self.next_buttons[step] = button
        return button

    @staticmethod
    def _column(*parts) -> QWidget:
        holder = QWidget()
        col = QVBoxLayout(holder)
        for part in parts:
            if isinstance(part, QHBoxLayout):
                col.addLayout(part)
            else:
                col.addWidget(part)
        col.addStretch(1)
        return holder

    @staticmethod
    def _row(*widgets) -> QHBoxLayout:
        row = QHBoxLayout()
        for w in widgets:
            row.addWidget(w)
        row.addStretch(1)
        return row

    def _page_open(self) -> QWidget:
        self._next_button("open", "Next: pick a question")
        more = _fold(self.fields_table, self.collapse_check, _form(("Blank answers", self.tokens_edit)))
        return self._column(
            self._row(self.open_button, self.sample_button), self.file_label, self.sheet_combo,
            self.summary_label, self.notes_label, self.next_buttons["open"], more)

    def _page_question(self) -> QWidget:
        self._q_rows = {}
        main_form = QFormLayout()
        more_form = QFormLayout()
        for form, key, label, widget in [
                (main_form, "field", "Question to chart", self.field_combo),
                (main_form, "columns", "Questions in the grid", self.columns_list),
                (main_form, "hint", "", self.kind_hint),
                (main_form, "chart", "Chart", self.chart_combo),
                (main_form, "chart_hint", "", self.chart_hint),
                (more_form, "kind", "Kind of question", self.kind_combo),
                (more_form, "group", "Split by (optional)", self.group_list),
                (more_form, "agg", "Summarise as", self.agg_combo),
                (more_form, "pc", "Show", self.pc_combo),
                (more_form, "measure", "Measure", self.measure_combo)]:
            holder = _with_tip(label, widget)
            form.addRow(label, holder)
            self._q_rows[key] = (form.labelForField(holder), holder)
        main = QWidget()
        main.setLayout(main_form)
        main_form.setContentsMargins(0, 0, 0, 0)
        more_holder = QWidget()
        more_holder.setLayout(more_form)
        more_form.setContentsMargins(0, 0, 0, 0)
        self._next_button("question", "Next: adjust the chart")
        more = _fold(more_holder, self.multi_box)
        return self._column(main, self.next_buttons["question"], more)

    def _page_adjust(self) -> QWidget:
        self._next_button("adjust", "Next: save it")
        for button in (self.undo_button, self.redo_button):
            button.setMaximumWidth(120)
        filters = _group("Leave some rows out", self.filters_list, self.remove_filter_button,
                         self.filter_add_row)
        blanks = _group("Blank answers and percentages",
                        ("Blank answers", self.blank_combo), ("Name for blanks", self.blank_label_edit),
                        ("Percentages are of", self.denom_combo), ("Base number", self.denom_spin),
                        ("Top / bottom boxes", self.boxes_row), self.offscale_check)
        labels = _group("Words on the chart",
                        ("Subtitle", self.subtitle_edit), ("Footnote or source", self.footnote_edit),
                        ("Horizontal axis title", self.xtitle_edit),
                        ("Vertical axis title", self.ytitle_edit),
                        ("Legend title", self.legend_title_edit), ("Legend", self.legend_combo),
                        self.labels_check, self.percent_check, self.count_check, self.validn_check,
                        ("Decimal places", self.decimals_spin), self.grid_check,
                        ("Axis minimum", self.axis_min_edit), ("Axis maximum", self.axis_max_edit),
                        self.wrap_check, ("Longest label line", self.wrap_spin),
                        ("Show only the largest N", self.maxcat_spin))
        shape = _group("Shape and size",
                       ("Direction", self.orient_combo), ("Size of bars and text", self.size_combo),
                       ("Number of bins", self.bins_spin), ("Each point is one", self.grain_combo),
                       self.trend_check, ("Figure shape", self.preset_combo),
                       ("Width (px)", self.width_spin), ("Height (px)", self.height_spin))
        colours = _group("Colours", ("Colours for ordered answers", self.scale_combo),
                         self.default_button, self.new_theme_button, self.delete_theme_button,
                         self.share_theme_button, self.import_theme_button)
        more = _fold(filters, blanks, labels, shape, colours, self.reset_button)
        return self._column(
            _form(("Title", self.title_edit), ("Order", self.sort_combo),
                  ("Colours", self.theme_combo)),
            self.categories_label, self.grid, self._row(self.undo_button, self.redo_button),
            self.next_buttons["adjust"], more)

    def _page_save(self) -> QWidget:
        self.save_picture_button.setProperty("main", True)
        saved = _group("Keep this chart for later", self.saved_note, ("Saved charts", self.saved_combo),
                       self._row(self.open_saved_button, self.delete_saved_button),
                       self.export_chart_button, self.import_chart_button)
        picture = _group("Picture file", ("File type", self.format_combo), ("Sharpness", self.dpi_combo),
                         self.transparent_check)
        table = _group("Table", self.totals_check, self.validn_col_check, self.missing_col_check,
                       self.save_responses_button)
        more = _fold(picture, table, saved)
        return self._column(
            self._row(self.save_picture_button, self.copy_picture_button), self.size_label,
            self._row(self.save_table_button, self.copy_table_button),
            _form(("Name", self.chart_name_edit)), self.save_chart_button, more)

    def _build_multi_group(self) -> QGroupBox:
        self.multi_mode_combo = _combo({
            "known": "Known choices (safe when a choice contains a comma)",
            "simple": "Split at the delimiter (simple)"})
        self.delim_combo = _combo(vocab.DELIM_LABELS)
        self.custom_delim_edit = QLineEdit()
        self.custom_delim_edit.setPlaceholderText("Separator")
        self.choices_edit = QPlainTextEdit()
        self.choices_edit.setPlaceholderText("The response choices, one per line, exactly as the "
                                             "question offered them. A choice may contain the separator.")
        self.choices_edit.setMaximumHeight(130)
        self.suggest_button = QPushButton("Suggest choices from the data")
        self.unmatched_check = QCheckBox("Also chart pieces that are not on the list")
        self.multi_box = _group("Select-all question", ("Read each cell as", self.multi_mode_combo),
                                ("Separated by", self.delim_combo), ("", self.custom_delim_edit),
                                self.choices_edit, self.suggest_button, self.unmatched_check)
        self.multi_mode_combo.currentIndexChanged.connect(self._multi_changed)
        self.delim_combo.currentIndexChanged.connect(self._multi_changed)
        self.custom_delim_edit.textChanged.connect(self._multi_changed)
        self.choices_edit.textChanged.connect(self._multi_changed)
        self.unmatched_check.toggled.connect(self._multi_changed)
        self.suggest_button.clicked.connect(self.suggest_choices)
        return self.multi_box

    def _build_refine_group(self) -> None:
        self.filters_list = QListWidget()
        self.filters_list.setMaximumHeight(80)
        self.remove_filter_button = QPushButton("Remove selected filter")
        self.filter_col = QComboBox()
        self.filter_op = _combo(vocab.OP_LABELS)
        self.filter_values = QLineEdit()
        self.filter_values.setPlaceholderText("value; another value (matched exactly)")
        self.add_filter_button = QPushButton("Add filter")
        self.blank_combo = _combo({"hide": "Leave blank answers out",
                                  "show": "Show them as their own category"})
        self.blank_label_edit = QLineEdit("No response")
        self.categories_label = QLabel("Categories: untick to leave one out, or type a new name")
        self.grid = QTableWidget(0, len(_GRID_COLUMNS))
        self.grid.setHorizontalHeaderLabels(_GRID_COLUMNS)
        self.grid.verticalHeader().setVisible(False)
        self.grid.setMinimumHeight(180)
        self.grid.setToolTip("Untick to leave a category out. Type a new name to relabel it, or "
                             "the same name on several rows to combine them. Give a Position to "
                             "set your own order. Colour takes a hex code such as #BC912C. The "
                             "file's values are never changed.")
        self.sort_combo = _combo(vocab.SORT_LABELS)
        self.denom_combo = _combo(vocab.DENOM_LABELS)
        self.denom_spin = QDoubleSpinBox()
        self.denom_spin.setRange(1, 1e9)
        self.denom_spin.setDecimals(0)
        self.denom_spin.setValue(100)
        self.top_checks = {n: QCheckBox(f"Top {n}") for n in (1, 2, 3)}
        self.bottom_checks = {n: QCheckBox(f"Bottom {n}") for n in (1, 2, 3)}
        self.offscale_check = QCheckBox("Leave 'No opinion' style answers out of a box's base")
        boxes = QWidget()
        bl = QHBoxLayout(boxes)
        bl.setContentsMargins(0, 0, 0, 0)
        for w in (*self.top_checks.values(), *self.bottom_checks.values()):
            bl.addWidget(w)
        self.boxes_row = boxes
        # Two short rows rather than one long one, so the panel never needs a
        # horizontal scrollbar.
        add_holder = QWidget()
        add_rows = QVBoxLayout(add_holder)
        add_rows.setContentsMargins(0, 0, 0, 0)
        top, bottom = QHBoxLayout(), QHBoxLayout()
        top.addWidget(self.filter_col, 1)
        top.addWidget(self.filter_op, 1)
        bottom.addWidget(self.filter_values, 1)
        bottom.addWidget(self.add_filter_button)
        add_rows.addLayout(top)
        add_rows.addLayout(bottom)

        self.remove_filter_button.clicked.connect(self._remove_filter)
        self.add_filter_button.clicked.connect(self._add_filter)
        self.blank_combo.currentIndexChanged.connect(self._refine_changed)
        self.blank_label_edit.textChanged.connect(self._refine_changed)
        self.sort_combo.currentIndexChanged.connect(self._refine_changed)
        self.denom_combo.currentIndexChanged.connect(self._refine_changed)
        self.denom_spin.valueChanged.connect(self._refine_changed)
        self.grid.itemChanged.connect(self._grid_changed)
        for w in (*self.top_checks.values(), *self.bottom_checks.values(), self.offscale_check):
            w.toggled.connect(self._refine_changed)

        self.filter_add_row = add_holder

    def _build_chart_group(self) -> None:
        self.chart_combo = QComboBox()
        self.bins_spin = QSpinBox()
        self.bins_spin.setRange(0, 60)
        self.bins_spin.setSpecialValueText("chosen for me")
        self.grain_combo = _combo(vocab.TIME_GRAIN_LABELS)
        self.grain_combo.setToolTip("Only applies when the field is a date.")
        self.trend_check = QCheckBox("Draw a line of best fit")
        self.chart_hint = QLabel("")
        self.chart_hint.setWordWrap(True)
        self.size_combo = _combo(vocab.SIZE_LABELS)
        self.orient_combo = _combo({"horizontal": "Horizontal", "vertical": "Vertical"})
        self.title_edit, self.subtitle_edit = QLineEdit(), QLineEdit()
        self.footnote_edit = QPlainTextEdit()
        self.footnote_edit.setMaximumHeight(56)
        self.xtitle_edit, self.ytitle_edit, self.legend_title_edit = QLineEdit(), QLineEdit(), QLineEdit()
        self.legend_combo = _combo(vocab.LEGEND_LABELS)
        self.labels_check = QCheckBox("Show data labels")
        self.percent_check = QCheckBox("Percent")
        self.count_check = QCheckBox("Count (how many chose it)")
        self.validn_check = QCheckBox("Valid N (the base), as 93% (519/558)")
        self.decimals_spin = QSpinBox()
        self.decimals_spin.setRange(0, 3)
        self.grid_check = QCheckBox("Gridlines")
        self.axis_min_edit, self.axis_max_edit = QLineEdit(), QLineEdit()
        self.axis_min_edit.setPlaceholderText("automatic")
        self.axis_max_edit.setPlaceholderText("automatic")
        self.wrap_check = QCheckBox("Wrap long labels")
        self.wrap_spin = QSpinBox()
        self.wrap_spin.setRange(10, 60)
        self.maxcat_spin = QSpinBox()
        self.maxcat_spin.setRange(0, 200)
        self.maxcat_spin.setSpecialValueText("all")
        self.preset_combo = QComboBox()
        for name in list(FIGURE_PRESETS) + ["Custom"]:
            self.preset_combo.addItem(name, name)
        self.width_spin, self.height_spin = QSpinBox(), QSpinBox()
        self.width_spin.setRange(300, 4000)
        self.height_spin.setRange(200, 4000)

        self.chart_combo.currentIndexChanged.connect(self._display_changed)
        for w in (self.size_combo, self.orient_combo, self.legend_combo, self.preset_combo,
                  self.grain_combo):
            w.currentIndexChanged.connect(self._display_changed)
        self.trend_check.toggled.connect(self._display_changed)
        self.bins_spin.valueChanged.connect(self._display_changed)
        for w in (self.title_edit, self.subtitle_edit, self.xtitle_edit, self.ytitle_edit,
                  self.legend_title_edit, self.axis_min_edit, self.axis_max_edit):
            w.textChanged.connect(self._display_changed)
        self.footnote_edit.textChanged.connect(self._display_changed)
        for w in (self.labels_check, self.percent_check, self.count_check, self.validn_check,
                  self.grid_check, self.wrap_check):
            w.toggled.connect(self._display_changed)
        for w in (self.decimals_spin, self.wrap_spin, self.maxcat_spin, self.width_spin,
                  self.height_spin):
            w.valueChanged.connect(self._display_changed)

    def _build_theme_group(self) -> None:
        self.theme_combo = QComboBox()
        self.scale_combo = QComboBox()
        self.scale_combo.addItem("Detect automatically", "auto")
        self.scale_combo.addItem("Off (theme palette)", "none")
        for name in themes.SCALE_PRESETS:
            self.scale_combo.addItem(name.capitalize() + " scale", name)
        self.default_button = QPushButton("Reset to the default")
        self.new_theme_button = QPushButton("Make my own theme…")
        self.delete_theme_button = QPushButton("Delete this theme")
        self.share_theme_button = QPushButton("Share this theme…")
        self.import_theme_button = QPushButton("Add a theme file…")
        self.new_theme_button.clicked.connect(self._open_theme_dialog)
        self.delete_theme_button.clicked.connect(self.delete_current_theme)
        self.share_theme_button.clicked.connect(self.share_current_theme)
        self.import_theme_button.clicked.connect(self.import_theme_file)
        self.theme_combo.currentIndexChanged.connect(self._theme_changed)
        self.scale_combo.currentIndexChanged.connect(self._theme_changed)
        self.default_button.clicked.connect(self.reset_theme)
        self._refill_themes()

    def _build_saved_group(self) -> None:
        self.chart_name_edit = QLineEdit()
        self.chart_name_edit.setPlaceholderText("A name for this chart")
        self.save_chart_button = QPushButton("Keep this chart")
        self.saved_combo = QComboBox()
        self.open_saved_button = QPushButton("Open")
        self.delete_saved_button = QPushButton("Delete")
        self.export_chart_button = QPushButton("Save as a file to share…")
        self.import_chart_button = QPushButton("Open a chart file…")
        note = QLabel("Saved charts remember the choices, not the data. Open one on the same "
                      "kind of file later and it draws the same chart. Saving under the same "
                      "name replaces it.")
        note.setWordWrap(True)
        self.save_chart_button.clicked.connect(lambda: self.save_current_chart())
        self.open_saved_button.clicked.connect(lambda: self.open_saved_chart())
        self.delete_saved_button.clicked.connect(lambda: self.delete_saved_chart())
        self.export_chart_button.clicked.connect(self.export_chart_file)
        self.import_chart_button.clicked.connect(self.import_chart_file)
        self.saved_note = note
        self.refresh_saved_list()

    def _build_output(self) -> QWidget:
        holder = QWidget()
        col = QVBoxLayout(holder)
        self.problem_label = QLabel("")
        self.problem_label.setWordWrap(True)
        self.problem_label.setTextFormat(Qt.PlainText)
        self.notes_label_out = QLabel("")
        self.notes_label_out.setWordWrap(True)
        self.notes_label_out.setTextFormat(Qt.RichText)
        self.notes_label_out.setStyleSheet(banner_style("note"))
        self.notes_label_out.setVisible(False)
        self.warning_label = QLabel("")
        self.warning_label.setWordWrap(True)
        self.warning_label.setTextFormat(Qt.RichText)
        self.warning_label.setStyleSheet(banner_style("warning"))
        self.warning_label.setVisible(False)
        self.preview = _Preview()
        self.format_combo = _combo({"png": "PNG", "svg": "SVG", "pdf": "PDF"})
        self.dpi_combo = QComboBox()
        for dpi in vocab.DPIS:
            self.dpi_combo.addItem(f"{dpi} DPI", dpi)
        self.dpi_combo.setCurrentIndex(vocab.DPIS.index(300))
        self.transparent_check = QCheckBox("Transparent background")
        self.save_picture_button = QPushButton("Save picture…")
        self.copy_picture_button = QPushButton("Copy picture")
        self.size_label = QLabel("")
        self.save_picture_button.clicked.connect(self.save_picture)
        self.copy_picture_button.clicked.connect(self.copy_picture)
        self.format_combo.currentIndexChanged.connect(self._export_changed)
        self.dpi_combo.currentIndexChanged.connect(self._export_changed)
        self.transparent_check.toggled.connect(self._export_changed)
        self.tabs = QTabWidget()
        self.table_widget = QTableWidget()
        self.table_widget.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table_widget.setSortingEnabled(True)
        self.totals_check = QCheckBox("Totals")
        self.validn_col_check = QCheckBox("Valid N")
        self.validn_col_check.setChecked(True)
        self.missing_col_check = QCheckBox("Missing N")
        self.save_table_button = QPushButton("Save table…")
        self.copy_table_button = QPushButton("Copy table")
        self.save_responses_button = QPushButton("Save the text responses…")
        self.boxes_table = QTableWidget()
        self.boxes_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tabs.addTab(self.table_widget, "The numbers")
        self.tabs.addTab(self.boxes_table, "Top and bottom boxes")
        self.totals_check.toggled.connect(self._refresh_table)
        self.validn_col_check.toggled.connect(self._refresh_table)
        self.missing_col_check.toggled.connect(self._refresh_table)
        self.save_table_button.clicked.connect(self.save_table)
        self.copy_table_button.clicked.connect(self.copy_table)
        self.save_responses_button.clicked.connect(self.save_responses)

        col.addWidget(self.problem_label)
        col.addWidget(self.notes_label_out)
        col.addWidget(self.warning_label)
        col.addWidget(self.preview, 3)
        col.addWidget(self.tabs, 2)
        return holder

    # ── steps ────────────────────────────────────────────────────────────────

    def set_step(self, key: str) -> None:
        """Show one step's page. The picture stays; the numbers show once there is something to adjust."""
        if key not in STEP_KEYS:
            return
        self._step = key
        self._stack.setCurrentIndex(STEP_KEYS.index(key))
        self.tabs.setVisible(key in ("adjust", "save"))

    def current_step(self) -> str:
        return self._step

    def go_step(self, key: str) -> None:
        """Move to a step from inside the screen (the Next buttons); the shell follows."""
        self.set_step(key)
        self.step_requested.emit(key)

    def _set_main(self, button: QPushButton, on: bool) -> None:
        """Mark the one filled button of the screen. The style must be re-read to show it."""
        if bool(button.property("main")) == on:
            return
        button.setProperty("main", on)
        button.style().unpolish(button)
        button.style().polish(button)

    def _refresh_main(self) -> None:
        """The filled button is Open until a file is open, then the Next button of each step."""
        has_file = self._table is not None
        self._set_main(self.open_button, not has_file)
        self._set_main(self.next_buttons["open"], has_file)
        self.next_buttons["open"].setEnabled(has_file)
        self.next_buttons["question"].setEnabled(isinstance(self._built, tuple))
        self._set_main(self.next_buttons["question"], isinstance(self._built, tuple))
        self._set_main(self.next_buttons["adjust"], True)
        self.next_buttons["adjust"].setEnabled(isinstance(self._built, tuple))

    def _sample_clicked(self) -> None:
        self.load_sample()
        self.go_step("question")

    # ── loading ──────────────────────────────────────────────────────────────

    def _ask_open_path(self, title: str = "Open a CSV or Excel file",
                       filter_text: str = "Data files (*.csv *.tsv *.txt *.xlsx *.xlsm *.xls);;All files (*)") -> str:
        path, _ = QFileDialog.getOpenFileName(self, title, "", filter_text)
        return path

    def _ask_save_path(self, default: str, filter_text: str) -> str:
        path, _ = QFileDialog.getSaveFileName(self, "Save", default, filter_text)
        return path

    def _choose_file(self) -> None:
        path = self._ask_open_path()
        if path and self.open_path(path):
            self.go_step("question")

    def open_path(self, path: str, sheet: Optional[str] = None) -> bool:
        """Read a file into memory. The file itself is never written or changed."""
        try:
            table = loader.load_path(path, sheet=sheet)
        except Exception as error:  # noqa: BLE001
            self.file_label.setText(f"That file could not be read: {error}")
            self.status.emit("Could not read that file.")
            return False
        self._sheet_source = Path(path)
        self.load_table(table)
        return True

    # -- progress (core/ux/progress.py) --------------------------------------
    def progress_state(self) -> dict:
        """The file and the chart choices that are names and settings.

        Not saved: filter values, renamed or merged categories, colour overrides
        (they are values from the spreadsheet) and the spreadsheet itself.
        The built-in sample has no file, so it has no saved place.
        """
        source = getattr(self, "_sheet_source", None)
        if self._table is None or source is None:
            return {}
        c = self._cfg
        return {
            "file_path": str(source),
            "question": c.column,
            "chart_type": c.chart_type,
            "chart_settings": {
                "kind": c.kind, "columns": list(c.columns), "group_by": list(c.group_by),
                "value_field": c.value_field, "aggregation": c.aggregation,
                "sort": c.sort, "title": c.labels.title,
            },
        }

    def restore_progress(self, state: dict) -> bool:
        """Reopen the file and put the chart choices back. False if the file is gone."""
        path = str(state.get("file_path", ""))
        if not path or not Path(path).exists() or not self.open_path(path):
            return False
        cols = set(self._columns())
        settings = state.get("chart_settings") or {}
        c = self._cfg
        if settings.get("kind"):
            c.kind = str(settings["kind"])
        if state.get("question") in cols:
            c.column = str(state["question"])
        c.columns = [x for x in settings.get("columns", []) if x in cols]
        c.group_by = [x for x in settings.get("group_by", []) if x in cols]
        if settings.get("value_field") in cols:
            c.value_field = str(settings["value_field"])
        for field_name in ("aggregation", "sort"):
            if settings.get(field_name):
                setattr(c, field_name, str(settings[field_name]))
        if state.get("chart_type"):
            c.chart_type = str(state["chart_type"])
        c.labels.title = str(settings.get("title", ""))
        self._hist = EditHistory(self._cfg, fields=SHAPING_FIELDS)
        self._sync_from_cfg()
        self.flush()
        return True

    def reset_session(self) -> None:
        """Back to a fresh screen: no file, no chart choices. Files on disk are not touched."""
        self._timer.stop()
        self._table = None
        self._profile = None
        self._cfg = ChartConfig()
        self._hist = EditHistory(self._cfg, fields=SHAPING_FIELDS)
        self._built = None
        self._png = None
        self._grid_signature = ""
        self._sheet_source = None
        self._subject = ("single", "", ())
        self.file_label.setText(_NO_FILE)
        self._kind_manual = False
        self.summary_label.setText("")
        self.notes_label.setText("")
        self.notes_label.setVisible(False)
        self.notes_label_out.setVisible(False)
        self.fields_table.setRowCount(0)
        self.sheet_combo.clear()
        self.sheet_combo.setVisible(False)
        self._populate_columns()
        self._sync_from_cfg()
        self._show_empty()

    def load_sample(self) -> None:
        self._sheet_source = None       # the sample is not a file on disk
        self.load_table(loader.LoadedTable(name="sample_survey.csv", frame=sample.sample_frame(),
                                           kind="csv", encoding="utf-8", delimiter=","))

    def load_table(self, table: loader.LoadedTable) -> None:
        self._table = table
        self._cfg = ChartConfig(dataset=table.structure())
        self._hist = EditHistory(self._cfg, fields=SHAPING_FIELDS)
        self._subject = ("single", "", ())
        self._kind_manual = False
        self._grid_signature = ""
        self._show_notes([])
        self._refresh_profile()
        self._populate_columns()
        detail = [f"sheet '{table.sheet}'"] if table.sheet else []
        if table.encoding:
            detail.append(f"{table.encoding} text")
        self.file_label.setText(f"{table.name}: read as {table.kind.upper()}"
                                + (f" ({', '.join(detail)})" if detail else "")
                                + ". The file is never changed.")
        self.notes_label.setText("\n".join(table.notes))
        self.notes_label.setVisible(bool(table.notes))
        self._sync_sheets(table)
        self._sync_from_cfg()
        self.flush()
        self.status.emit(f"Loaded {table.name}: {table.n_rows:,} rows, {table.n_cols:,} columns.")

    def _sync_sheets(self, table: loader.LoadedTable) -> None:
        self._syncing = True
        self.sheet_combo.clear()
        for name in table.sheets:
            self.sheet_combo.addItem(name, name)
        if table.sheet:
            self.sheet_combo.setCurrentIndex(max(self.sheet_combo.findData(table.sheet), 0))
        self.sheet_combo.setVisible(len(table.sheets) > 1)
        self._syncing = False

    def _sheet_changed(self) -> None:
        if self._syncing or self._table is None or self._table.kind != "excel":
            return
        path = getattr(self, "_sheet_source", None)
        sheet = self.sheet_combo.currentData()
        if path and sheet and sheet != self._table.sheet:
            self.open_path(str(path), sheet=sheet)

    def _columns(self) -> List[str]:
        return [str(c) for c in self._table.frame.columns] if self._table else []

    def _refresh_profile(self) -> None:
        if self._table is None:
            return
        self._profile = profile.profile_table(self._table.frame,
                                              missing_tokens=self._cfg.recode.missing_tokens)
        self.summary_label.setText(
            f"{self._profile.n_rows:,} rows × {self._profile.n_cols:,} columns")
        self.fields_table.setRowCount(len(self._profile.columns))
        for r, col in enumerate(self._profile.columns):
            for c, value in enumerate([col.name, col.kind, col.n_valid, col.n_missing, col.n_unique]):
                item = QTableWidgetItem()
                item.setData(Qt.DisplayRole, value)
                if col.warnings and c == 0:
                    item.setToolTip("\n".join(col.warnings))
                self.fields_table.setItem(r, c, item)
        self.fields_table.resizeColumnsToContents()

    def _populate_columns(self) -> None:
        cols = self._columns()
        self._syncing = True
        self.field_combo.clear()
        self.field_combo.addItem("Choose a field", "")
        for c in cols:
            self.field_combo.addItem(c, c)
        for lst in (self.columns_list, self.group_list):
            lst.clear()
            for c in cols:
                lst.addItem(QListWidgetItem(c))
        self.filter_col.clear()
        for c in cols:
            self.filter_col.addItem(c, c)
        self.measure_combo.clear()
        self.measure_combo.addItem("Choose a field", "")
        for c in cols:
            self.measure_combo.addItem(c, c)
        self._syncing = False

    # ── config <-> widgets ───────────────────────────────────────────────────

    def config(self) -> ChartConfig:
        return self._cfg.copy()

    def _sync_from_cfg(self) -> None:
        """Set every widget from the config (after load, undo, redo, reset)."""
        c = self._cfg
        self._syncing = True
        try:
            _set_combo(self.kind_combo, c.kind)
            _set_combo(self.field_combo, c.column)
            for lst, chosen in ((self.columns_list, c.columns), (self.group_list, c.group_by)):
                for i in range(lst.count()):
                    lst.item(i).setSelected(lst.item(i).text() in chosen)
            _set_combo(self.agg_combo, c.aggregation)
            _set_combo(self.pc_combo, c.aggregation if c.aggregation in vocab.PERCENT_OR_COUNT
                       else "percent")
            _set_combo(self.measure_combo, c.value_field)
            m = c.multi
            _set_combo(self.multi_mode_combo, m.mode)
            _set_combo(self.delim_combo, m.delimiter)
            self.custom_delim_edit.setText(m.custom_delimiter)
            self.choices_edit.setPlainText("\n".join(m.choices))
            self.unmatched_check.setChecked(m.include_unmatched)
            self._fill_filters()
            _set_combo(self.blank_combo, "show" if c.recode.show_missing else "hide")
            self.blank_label_edit.setText(c.recode.missing_label)
            self.collapse_check.setChecked(c.recode.collapse_whitespace)
            tokens = c.recode.missing_tokens
            if tokens is not None:
                self.tokens_edit.setText(", ".join(t for t in tokens if t))
            self._fill_sorts()
            _set_combo(self.sort_combo, c.sort)
            _set_combo(self.denom_combo, c.denominator)
            self.denom_spin.setValue(float(c.custom_denominator or 100))
            for n, box in self.top_checks.items():
                box.setChecked(n in c.boxes.top)
            for n, box in self.bottom_checks.items():
                box.setChecked(n in c.boxes.bottom)
            self.offscale_check.setChecked(c.boxes.exclude_off_scale)
            self._sync_display()
            self._refill_themes()
            _set_combo(self.theme_combo, c.theme.name)
            _set_combo(self.scale_combo, c.theme.semantic_scale)
        finally:
            self._syncing = False
        self._update_visibility()

    def _sync_display(self) -> None:
        c = self._cfg
        L, D, F = c.labels, c.display, c.figure
        self.title_edit.setText(L.title)
        self.subtitle_edit.setText(L.subtitle)
        self.footnote_edit.setPlainText(L.footnote)
        self.xtitle_edit.setText(L.x_title)
        self.ytitle_edit.setText(L.y_title)
        self.legend_title_edit.setText(L.legend_title)
        _set_combo(self.legend_combo, L.legend_position)
        _set_combo(self.size_combo, D.size)
        _set_combo(self.orient_combo, D.orientation)
        self.labels_check.setChecked(D.data_labels)
        self.percent_check.setChecked(D.show_percent)
        self.count_check.setChecked(D.show_count)
        self.validn_check.setChecked(D.show_valid_n)
        self.decimals_spin.setValue(D.decimals)
        self.grid_check.setChecked(D.gridlines)
        self.axis_min_edit.setText("" if D.axis_min is None else str(D.axis_min))
        self.axis_max_edit.setText("" if D.axis_max is None else str(D.axis_max))
        self.wrap_check.setChecked(D.wrap_labels)
        self.wrap_spin.setValue(D.max_label_chars)
        self.maxcat_spin.setValue(D.max_categories)
        self.bins_spin.setValue(D.bins)
        _set_combo(self.grain_combo, D.time_grain)
        self.trend_check.setChecked(D.trend_line)
        _set_combo(self.preset_combo, F.preset)
        self.width_spin.setValue(F.width)
        self.height_spin.setValue(F.height)
        self.transparent_check.setChecked(F.transparent)
        self._fill_charts()

    def _fill_sorts(self) -> None:
        sorts = vocab.MATRIX_SORTS if self._cfg.kind == "matrix" else vocab.OTHER_SORTS
        self.sort_combo.clear()
        for key in sorts:
            self.sort_combo.addItem(vocab.SORT_LABELS[key], key)

    def _fill_charts(self) -> None:
        c = self._cfg
        types = vocab.available_charts(c.kind, bool(c.group_by), self._column_kind())
        recs = self._recommendations()
        primary = next((r.chart_type for r in recs if r.primary), None)
        if c.chart_type not in types:
            c.chart_type = primary if primary in types else types[0]
        was = self._syncing
        self._syncing = True
        self.chart_combo.clear()
        for t in types:
            self.chart_combo.addItem(vocab.CHART_LABELS[t] + ("  ★ suggested" if t == primary else ""), t)
        _set_combo(self.chart_combo, c.chart_type)
        self._syncing = was
        reason = next((r.reason for r in recs if r.chart_type == c.chart_type), "")
        soon = [vocab.CHART_LABELS.get(r.chart_type, r.chart_type) for r in recs if not r.available]
        self.chart_hint.setText(reason + (f"  Coming soon for this data: {', '.join(soon)}." if soon else ""))

    def _column_kind(self) -> str:
        if self._profile is None or not self._cfg.column:
            return ""
        try:
            return self._profile.column(self._cfg.column).kind
        except KeyError:
            return ""

    def _set_row(self, widget: QWidget, on: bool) -> None:
        """Show or hide a form row: the field and its label together."""
        widget.setVisible(on)
        form = widget.parentWidget().layout() if widget.parentWidget() else None
        label = form.labelForField(widget) if isinstance(form, QFormLayout) else None
        if label is not None:
            label.setVisible(on)

    def _recommendations(self) -> List[recommend.Recommendation]:
        cats = self._built[0].categories if isinstance(self._built, tuple) else []
        return recommend.recommend(self._cfg, self._profile, n_categories=len(cats) or None,
                                   categories=cats or None)

    def _update_visibility(self) -> None:
        kind, ct = self._cfg.kind, self._cfg.chart_type
        single = kind == "single"
        numeric_chart = single and vocab.is_numeric_chart(ct)
        show = {"chart": True, "chart_hint": True,
                "kind": True, "field": kind != "matrix", "columns": kind == "matrix",
                "hint": bool(self.kind_hint.text()),
                "group": kind in ("single", "multi"),
                "agg": single and ct not in ("box", "scatter", "histogram"),
                "pc": kind in ("matrix", "multi", "text") or (single and ct == "histogram"),
                "measure": single and (ct == "scatter" or (
                    ct not in ("box", "histogram") and self._cfg.aggregation in MEASURE_AGGREGATIONS))}
        for key, (label, widget) in self._q_rows.items():
            widget.setVisible(show[key])
            if label is not None:
                label.setVisible(show[key])
        measure_label = self._q_rows["measure"][0]
        if measure_label is not None:
            measure_label.setText("Vertical axis" if ct == "scatter" and single else "Measure")
        self.categories_label.setVisible(not numeric_chart)
        self.grid.setVisible(not numeric_chart)
        self._set_row(self.sort_combo, not numeric_chart or ct == "box")
        self._set_row(self.denom_combo, not numeric_chart)
        self._set_row(self.bins_spin, ct == "histogram")
        self._set_row(self.grain_combo, ct in ("line", "area"))
        self.trend_check.setVisible(ct == "scatter")
        self.multi_box.setVisible(kind == "multi")
        known = self._cfg.multi.mode == "known"
        self.choices_edit.setVisible(known)
        self.suggest_button.setVisible(known)
        self.unmatched_check.setVisible(known)
        self.custom_delim_edit.setVisible(self._cfg.multi.delimiter == "custom")
        self.boxes_row.setVisible(kind == "matrix")
        self.offscale_check.setVisible(kind == "matrix")
        self.denom_spin.setVisible(self._cfg.denominator == "custom" and not numeric_chart)
        self.blank_label_edit.setVisible(self._cfg.recode.show_missing)
        self.orient_combo.setEnabled(self._cfg.chart_type in
                                     ("grouped_bar", "stacked_bar", "normalized_bar"))
        custom_size = self._cfg.figure.preset == "Custom"
        self.width_spin.setEnabled(custom_size)
        self.height_spin.setEnabled(custom_size)
        self.save_responses_button.setVisible(kind == "text")
        custom_theme = self._cfg.theme.name in self._custom_themes
        self.delete_theme_button.setEnabled(custom_theme)
        self.share_theme_button.setEnabled(custom_theme)
        self.tabs.setTabVisible(1, kind == "matrix")

    # ── handlers: each writes the config, then schedules a redraw ────────────

    def _touch(self) -> None:
        """A choice changed: record it for undo, and redraw shortly."""
        if self._syncing:
            return
        self._hist.push(self._cfg)
        self._update_visibility()
        self._timer.start()

    def _kind_changed(self) -> None:
        if self._syncing:
            return
        self._kind_manual = True           # the person chose; stop choosing for them
        previous = self._cfg.kind
        self._cfg.kind = self.kind_combo.currentData()
        if self._cfg.kind == "matrix" and self._cfg.sort == "desc":
            self._cfg.sort = "scale"
        elif previous == "matrix" and self._cfg.sort == "scale":
            self._cfg.sort = "desc"
        self._syncing = True
        self._fill_sorts()
        _set_combo(self.sort_combo, self._cfg.sort)
        self._syncing = False
        self._question_changed()

    def _selected(self, lst: QListWidget) -> List[str]:
        return [lst.item(i).text() for i in range(lst.count()) if lst.item(i).isSelected()]

    def _question_changed(self) -> None:
        if self._syncing:
            return
        c = self._cfg
        c.column = self.field_combo.currentData() or ""
        c.columns = self._selected(self.columns_list)
        c.group_by = [g for g in self._selected(self.group_list) if g != c.column]
        self._choose_kind(c)
        if c.kind == "single":
            if c.chart_type == "histogram":
                c.aggregation = self.pc_combo.currentData() or "percent"
                c.value_field = ""
            elif c.chart_type == "box":
                c.value_field = ""
            elif c.chart_type == "scatter":
                c.value_field = self.measure_combo.currentData() or ""
            else:
                c.aggregation = self.agg_combo.currentData() or "percent"
                c.value_field = self.measure_combo.currentData() or "" \
                    if c.aggregation in MEASURE_AGGREGATIONS else ""
        else:
            c.aggregation = self.pc_combo.currentData() or "percent"
            c.value_field = ""
        subject = (c.kind, c.column, tuple(c.columns))
        if subject != self._subject:
            # A new field is a new question: start from the suggested chart for it.
            self._subject = subject
            types = vocab.available_charts(c.kind, bool(c.group_by), self._column_kind())
            recs = recommend.recommend(c, self._profile)
            primary = next((r.chart_type for r in recs if r.primary), None)
            if primary in types and primary != c.chart_type:
                c.chart_type = primary
                c.aggregation = vocab.settle_aggregation(c.chart_type, c.aggregation)
                self._hist.push(c)
                self._sync_from_cfg()
                self._timer.start()
                return
        self._hint_for_field()
        self._touch()

    def _kind_for(self, column: str) -> str:
        """The kind of question a column looks like: free text, select-all, or one choice."""
        if self._profile is None or column not in self._columns():
            return "single"
        col = self._profile.column(column)
        if col.kind == profile.TEXT:
            return "text"
        if col.multiselect_delimiter:
            return "multi"
        return "single"

    def _choose_kind(self, c: ChartConfig) -> None:
        """Pick the kind of question from the column, unless the person picked it (or it is a grid)."""
        if self._kind_manual or c.kind == "matrix" or not c.column or c.column == self._subject[1]:
            return
        wanted = self._kind_for(c.column)
        if wanted == c.kind:
            return
        c.kind = wanted
        if wanted == "multi":
            col = self._profile.column(c.column)
            c.multi.delimiter = col.multiselect_delimiter
            cleaned = clean.normalize_series(self._table.frame[c.column],
                                             missing_tokens=c.recode.missing_tokens)
            found = survey.suggest_choices(cleaned, c.multi.delimiter_char())
            c.multi.choices = [f.choice for f in found]
            c.multi.mode = "known"
        self._syncing = True
        self._fill_sorts()
        _set_combo(self.sort_combo, c.sort)
        self._syncing = False

    def _hint_for_field(self) -> None:
        text = ""
        if self._cfg.kind == "single" and self._cfg.chart_type == "box":
            text = "A box plot shows the spread of the field above: one box per 'Split by' group."
        elif self._cfg.kind == "single" and self._cfg.chart_type == "scatter":
            text = "Horizontal axis: the field above. Vertical axis: choose another number."
        elif self._cfg.kind == "text" and not self._kind_manual:
            text = "This looks like free text, so the chart summarises the responses."
        elif self._cfg.kind == "multi" and not self._kind_manual:
            text = "Each cell holds several answers, so each choice is counted on its own."
        elif self._profile and self._cfg.column in self._columns() and self._cfg.kind == "single":
            col = self._profile.column(self._cfg.column)
            if col.kind == profile.TEXT:
                text = "This looks like free text. Choose “Free text” above to summarise it."
            elif col.multiselect_delimiter:
                text = (f"Cells hold several answers (separated by {col.multiselect_delimiter}). "
                        "Choose “Select all that apply” above.")
        self.kind_hint.setText(text)

    def _multi_changed(self) -> None:
        if self._syncing:
            return
        m = self._cfg.multi
        m.mode = self.multi_mode_combo.currentData()
        m.delimiter = self.delim_combo.currentData()
        m.custom_delimiter = self.custom_delim_edit.text()
        m.choices = [ln.strip() for ln in self.choices_edit.toPlainText().splitlines() if ln.strip()]
        m.include_unmatched = self.unmatched_check.isChecked()
        self._touch()

    def suggest_choices(self) -> None:
        if self._table is None or self._cfg.column not in self._columns():
            return
        cleaned = clean.normalize_series(self._table.frame[self._cfg.column],
                                         missing_tokens=self._cfg.recode.missing_tokens)
        found = survey.suggest_choices(cleaned, self._cfg.multi.delimiter_char())
        self._cfg.multi.choices = [s.choice for s in found]
        self._cfg.multi.mode = "known"
        self._hist.push(self._cfg)
        self._sync_from_cfg()
        self.flush()

    def _quality_changed(self) -> None:
        if self._syncing:
            return
        rc = self._cfg.recode
        rc.collapse_whitespace = self.collapse_check.isChecked()
        parsed = [t.strip() for t in self.tokens_edit.text().split(",") if t.strip()]
        defaults = {"NULL", "null", "NaN", "None", "N/A", "NA", "(blank)", "<null>"}
        rc.missing_tokens = None if set(parsed) == defaults else [""] + parsed
        self._refresh_profile()
        self._touch()

    def _refine_changed(self) -> None:
        if self._syncing:
            return
        c = self._cfg
        c.recode.show_missing = self.blank_combo.currentData() == "show"
        c.recode.missing_label = self.blank_label_edit.text() or "No response"
        c.sort = self.sort_combo.currentData() or c.sort
        c.denominator = self.denom_combo.currentData() or "valid"
        c.custom_denominator = float(self.denom_spin.value()) if c.denominator == "custom" else None
        c.boxes.top = [n for n, b in self.top_checks.items() if b.isChecked()]
        c.boxes.bottom = [n for n, b in self.bottom_checks.items() if b.isChecked()]
        c.boxes.exclude_off_scale = self.offscale_check.isChecked()
        self._touch()

    def _display_changed(self) -> None:
        if self._syncing:
            return
        c = self._cfg
        previous = c.chart_type
        c.chart_type = self.chart_combo.currentData() or c.chart_type
        L, D, F = c.labels, c.display, c.figure
        D.bins, D.time_grain = self.bins_spin.value(), self.grain_combo.currentData() or "auto"
        D.trend_line = self.trend_check.isChecked()
        if c.chart_type != previous:
            # A newly chosen trend or distribution chart needs a matching summary.
            c.aggregation = vocab.settle_aggregation(c.chart_type, c.aggregation)
            self._hist.push(c)
            self._sync_from_cfg()
            self._timer.start()
            return
        L.title, L.subtitle = self.title_edit.text(), self.subtitle_edit.text()
        L.footnote = self.footnote_edit.toPlainText()
        L.x_title, L.y_title = self.xtitle_edit.text(), self.ytitle_edit.text()
        L.legend_title = self.legend_title_edit.text()
        L.legend_position = self.legend_combo.currentData()
        D.size = self.size_combo.currentData()
        D.orientation = self.orient_combo.currentData()
        D.data_labels = self.labels_check.isChecked()
        D.show_percent = self.percent_check.isChecked()
        D.show_count = self.count_check.isChecked()
        D.show_valid_n = self.validn_check.isChecked()
        D.decimals = self.decimals_spin.value()
        D.gridlines = self.grid_check.isChecked()
        D.axis_min, D.axis_max = _number(self.axis_min_edit.text()), _number(self.axis_max_edit.text())
        D.wrap_labels = self.wrap_check.isChecked()
        D.max_label_chars = self.wrap_spin.value()
        D.max_categories = self.maxcat_spin.value()
        F.preset = self.preset_combo.currentData()
        F.width, F.height = self.width_spin.value(), self.height_spin.value()
        self._touch()

    def _theme_changed(self) -> None:
        if self._syncing:
            return
        self._cfg.theme.name = self.theme_combo.currentData() or self._cfg.theme.name
        self._cfg.theme.semantic_scale = self.scale_combo.currentData() or "auto"
        self._touch()

    def _refill_themes(self) -> None:
        was = self._syncing
        self._syncing = True
        self.theme_combo.clear()
        for name in list(themes.BUILTIN_THEMES) + list(self._custom_themes):
            self.theme_combo.addItem(name, name)
        _set_combo(self.theme_combo, self._cfg.theme.name)
        self._syncing = was

    def reset_theme(self) -> None:
        self._cfg.theme = ChartConfig().theme
        self._sync_from_cfg()
        self.flush()

    def _export_changed(self) -> None:
        if self._syncing:
            return
        self._cfg.figure.transparent = self.transparent_check.isChecked()
        self._cfg.figure.dpi = self.dpi_combo.currentData()
        self._cfg.figure.format = self.format_combo.currentData()
        self._update_export_label()
        self._timer.start()

    # ── filters ──────────────────────────────────────────────────────────────

    def _fill_filters(self) -> None:
        self.filters_list.clear()
        for rule in self._cfg.filters:
            shown = ", ".join(map(str, rule.values))
            self.filters_list.addItem(f"{rule.column} {vocab.OP_LABELS.get(rule.op, rule.op)} {shown}".strip())

    def _add_filter(self) -> None:
        col = self.filter_col.currentData()
        op = self.filter_op.currentData()
        if not col:
            return
        values = [v.strip() for v in self.filter_values.text().split(";") if v.strip()]
        needs = 0 if op in ("is_missing", "not_missing") else (2 if op == "between" else 1)
        if len(values) < needs:
            self.status.emit("That filter needs a value.")
            return
        self._cfg.filters.append(FilterRule(col, op, values))
        self.filter_values.clear()
        self._hist.push(self._cfg)
        self._fill_filters()
        self._timer.start()

    def _remove_filter(self) -> None:
        row = self.filters_list.currentRow()
        if 0 <= row < len(self._cfg.filters):
            self._cfg.filters.pop(row)
            self._hist.push(self._cfg)
            self._fill_filters()
            self._timer.start()

    # ── category grid ────────────────────────────────────────────────────────

    def _signature(self) -> str:
        c = self._cfg
        payload = json.dumps([c.kind, c.column, c.columns, c.to_dict()["filters"],
                              c.recode.missing_tokens, c.recode.collapse_whitespace,
                              c.to_dict()["multi"]], default=str)
        return hashlib.md5(payload.encode()).hexdigest()

    def _refresh_grid(self) -> None:
        """Rebuild the grid when the categories on offer change (never on an
        edit to the grid itself, so typing in it is not interrupted)."""
        sig = self._signature()
        if sig == self._grid_signature or self._table is None:
            return
        self._grid_signature = sig
        rows = recode_table.category_table(self._table.frame, self._cfg)
        overrides = self._cfg.theme.color_overrides
        self._syncing = True
        self.grid.setRowCount(len(rows))
        for r, rec in enumerate(rows.itertuples(index=False)):
            cat, n, include, display, combine, pos = rec
            values = [cat, n, include, display, combine, "" if pos is None or pos != pos else int(pos),
                      overrides.get(cat, "")]
            for c, value in enumerate(values):
                item = QTableWidgetItem()
                if c in (0, 1):
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                    item.setData(Qt.DisplayRole, value)
                elif c == 2:
                    item.setFlags((item.flags() | Qt.ItemIsUserCheckable) & ~Qt.ItemIsEditable)
                    item.setCheckState(Qt.Checked if value else Qt.Unchecked)
                else:
                    item.setText(str(value))
                self.grid.setItem(r, c, item)
        self.grid.resizeColumnsToContents()
        self._syncing = False

    def _grid_frame(self) -> pd.DataFrame:
        rows = []
        for r in range(self.grid.rowCount()):
            def text(c):
                it = self.grid.item(r, c)
                return it.text().strip() if it else ""
            pos = text(5)
            rows.append({"Category": self.grid.item(r, 0).data(Qt.DisplayRole),
                         "Rows": self.grid.item(r, 1).data(Qt.DisplayRole),
                         "Include": self.grid.item(r, 2).checkState() == Qt.Checked,
                         "Display name": text(3), "Combine into": text(4),
                         "Position": float(pos) if _number(pos) is not None else None})
        return pd.DataFrame(rows, columns=["Category", "Rows", "Include", "Display name",
                                           "Combine into", "Position"])

    def _grid_changed(self, _item=None) -> None:
        if self._syncing or self._table is None:
            return
        frame = self._grid_frame()
        self._cfg.recode = recode_table.recode_from_table(frame, self._cfg.recode)
        if frame["Position"].notna().any() and self._cfg.sort != "custom":
            self._cfg.sort = "custom"
            self._syncing = True
            _set_combo(self.sort_combo, "custom")
            self._syncing = False
        overrides, bad = {}, []
        for r in range(self.grid.rowCount()):
            hexv = self.grid.item(r, 6).text().strip()
            if hexv:
                try:
                    overrides[self.grid.item(r, 0).data(Qt.DisplayRole)] = themes.normalize_hex(hexv)
                except ValueError:
                    bad.append(self.grid.item(r, 0).data(Qt.DisplayRole))
        self._cfg.theme.color_overrides = overrides
        if bad:
            self.status.emit("Not a colour, so ignored: " + ", ".join(bad) + ". Use a hex code such as #BC912C.")
        self._touch()

    # ── undo / redo / reset ──────────────────────────────────────────────────

    def _restore(self) -> None:
        self._cfg = self._hist.restore_into(self._cfg)
        self._subject = (self._cfg.kind, self._cfg.column, tuple(self._cfg.columns))
        self._grid_signature = ""
        self._sync_from_cfg()
        self.flush()

    def undo(self) -> None:
        if self._hist.can_undo:
            self._hist.undo()
            self._restore()

    def redo(self) -> None:
        if self._hist.can_redo:
            self._hist.redo()
            self._restore()

    def reset_chart(self) -> None:
        """Back to a blank chart on the same data. The reset is itself undoable."""
        if self._table is None:
            return
        fresh = ChartConfig(dataset=self._cfg.dataset)
        self._hist.push(fresh)
        self._cfg = fresh
        self._subject = ("single", "", ())
        self._grid_signature = ""
        self._sync_from_cfg()
        self.flush()

    # ── drawing ──────────────────────────────────────────────────────────────

    def _show_empty(self) -> None:
        self.problem_label.setText("Open a file, or try the sample survey, to begin.")
        self.preview.set_image(None)
        self._refresh_main()

    def flush(self) -> None:
        """Draw now (tests, and after undo). Normally the debounce timer does this."""
        self._timer.stop()
        self._render()

    def _render(self) -> None:
        if self._table is None:
            self._show_empty()
            return
        self._refresh_grid()
        try:
            data, theme = build_data(self._table.frame, self._cfg, self._custom_themes)
            spec = build_spec(data, self._cfg, theme)
            self._built = (data, theme, spec)
        except (ChartBuildError, KeyError) as error:
            self._built = str(error.args[0] if error.args else error)
        self._fill_charts()
        self._refresh_main()
        self.undo_button.setEnabled(self._hist.can_undo)
        self.redo_button.setEnabled(self._hist.can_redo)
        if isinstance(self._built, str):
            self.problem_label.setText(self._built)
            self.warning_label.setVisible(False)
            self.preview.set_image(None)
            self._png = None
            self._clear_tables()
            self._update_export_label()
            return
        data, _theme, spec = self._built
        self.problem_label.setText("")
        self.warning_label.setText(banner_text("warning", "<br>".join(
            "• " + html.escape(w, quote=False) for w in data.warnings)))
        self.warning_label.setVisible(bool(data.warnings))
        self._png = None
        if export.image_export_available():
            try:
                self._png = export.render_image(spec, "png", PREVIEW_DPI)
            except Exception as error:  # noqa: BLE001
                self.problem_label.setText(f"The chart could not be drawn: {error}")
        else:
            self.problem_label.setText("Pictures need the vl-convert package, which is not installed.")
        pixmap = QPixmap()
        if self._png:
            pixmap.loadFromData(self._png)
        self.preview.set_image(pixmap if self._png else None)
        self._refresh_table()
        self._update_export_label()

    def _update_export_label(self) -> None:
        if self._table is None:
            self.size_label.setText("")
            return
        w, h = export.export_pixels(self._cfg, self.dpi_combo.currentData() or 300)
        if self.format_combo.currentData() == "png":
            self.size_label.setText(f"{w:,} × {h:,} px")
        else:
            self.size_label.setText("vector")

    def _clear_tables(self) -> None:
        self.table_widget.setRowCount(0)
        self.table_widget.setColumnCount(0)
        self.boxes_table.setRowCount(0)
        self.boxes_table.setColumnCount(0)

    def _summary(self) -> Optional[pd.DataFrame]:
        if not isinstance(self._built, tuple):
            return None
        return export.summary_table(self._built[0], self._cfg, totals=self.totals_check.isChecked(),
                                    valid_n=self.validn_col_check.isChecked(),
                                    missing_n=self.missing_col_check.isChecked())

    @staticmethod
    def _fill_table(widget: QTableWidget, frame: pd.DataFrame, sortable: bool = True) -> None:
        widget.setSortingEnabled(False)
        widget.setRowCount(len(frame))
        widget.setColumnCount(len(frame.columns))
        widget.setHorizontalHeaderLabels([str(c) for c in frame.columns])
        for r, row in enumerate(frame.itertuples(index=False)):
            for c, value in enumerate(row):
                item = QTableWidgetItem()
                item.setData(Qt.DisplayRole, value if isinstance(value, (int, float, str)) else str(value))
                widget.setItem(r, c, item)
        widget.resizeColumnsToContents()
        widget.setSortingEnabled(sortable)

    def _refresh_table(self) -> None:
        frame = self._summary()
        if frame is None:
            return
        self._fill_table(self.table_widget, frame)
        if self._cfg.kind == "matrix":
            self._fill_table(self.boxes_table, survey.box_summary(self._built[0], self._cfg),
                             sortable=False)

    # ── export ───────────────────────────────────────────────────────────────

    def _default_name(self, ext: str, suffix: str = "") -> str:
        return export.chart_filename(self._cfg, ext, suffix=suffix)

    def _spec_for_export(self) -> dict:
        data, theme, _ = self._built
        return build_spec(data, self._cfg, theme)

    def picture_bytes(self, fmt: Optional[str] = None, dpi: Optional[int] = None) -> bytes:
        """The chart as PNG/SVG/PDF bytes, at the chosen (or given) format and DPI."""
        if not isinstance(self._built, tuple):
            raise ChartBuildError("There is no chart to export yet.")
        self._cfg.figure.transparent = self.transparent_check.isChecked()
        return export.render_image(self._spec_for_export(),
                                   fmt or self.format_combo.currentData(),
                                   dpi or self.dpi_combo.currentData())

    def save_picture(self) -> Optional[str]:
        if not isinstance(self._built, tuple):
            self.status.emit("There is no chart to save yet.")
            return None
        fmt = self.format_combo.currentData()
        try:
            default = self._default_name(fmt)
        except ValueError as error:
            self.status.emit(str(error))
            return None
        path = self._ask_save_path(default, f"{fmt.upper()} (*.{fmt})")
        if not path:
            return None
        try:
            Path(path).write_bytes(self.picture_bytes())
        except Exception as error:  # noqa: BLE001
            self.status.emit(f"Could not save the picture: {error}")
            return None
        self.status.emit(f"Saved {Path(path).name}.")
        return path

    def copy_picture(self) -> bool:
        """Put the chart on the clipboard as an image (paste into PowerPoint or Word)."""
        if not isinstance(self._built, tuple):
            return False
        try:
            image = QImage.fromData(self.picture_bytes("png"))
        except Exception as error:  # noqa: BLE001
            self.status.emit(f"Could not copy the picture: {error}")
            return False
        QGuiApplication.clipboard().setImage(image)
        self.status.emit("Copied the picture to the clipboard.")
        return True

    def save_table(self) -> Optional[str]:
        frame = self._summary()
        if frame is None:
            return None
        path = self._ask_save_path(self._default_name("csv", "table"),
                                   "CSV (*.csv);;Excel (*.xlsx)")
        if not path:
            return None
        if path.lower().endswith(".xlsx"):
            Path(path).write_bytes(export.table_xlsx(frame, self._built[0], self._cfg))
        else:
            Path(path).write_bytes(export.table_csv(frame))
        self.status.emit(f"Saved {Path(path).name}.")
        return path

    def copy_table(self) -> bool:
        frame = self._summary()
        if frame is None:
            return False
        QGuiApplication.clipboard().setText(export.table_tsv(frame))
        self.status.emit("Copied the table. Paste it into Excel or Word.")
        return True

    def save_responses(self) -> Optional[str]:
        if self._table is None or not self._cfg.column:
            return None
        answers = survey.responses_frame(self._table.frame, self._cfg.column,
                                         missing_tokens=self._cfg.recode.missing_tokens)
        path = self._ask_save_path(self._default_name("csv", "responses"), "CSV (*.csv)")
        if not path:
            return None
        Path(path).write_bytes(export.table_csv(answers))
        self.status.emit(f"Saved {len(answers):,} responses.")
        return path

    # ── saved charts ─────────────────────────────────────────────────────────

    def _show_notes(self, notes: List[str]) -> None:
        self.notes_label_out.setText(banner_text("note", "<br>".join(
            "• " + html.escape(n, quote=False) for n in notes)))
        self.notes_label_out.setVisible(bool(notes))

    def refresh_saved_list(self, select: str = "") -> None:
        was = self._syncing
        self._syncing = True
        self.saved_combo.clear()
        for chart in store.list_charts(self._root):
            self.saved_combo.addItem(f"{chart.name}  ({chart.dataset_name or 'no file'})", chart.name)
        if select:
            index = self.saved_combo.findData(select)
            if index >= 0:
                self.saved_combo.setCurrentIndex(index)
        self._syncing = was
        has = self.saved_combo.count() > 0
        self.open_saved_button.setEnabled(has)
        self.delete_saved_button.setEnabled(has)

    def save_current_chart(self, name: Optional[str] = None) -> bool:
        """Save the chart as it is now, under `name` (or the name box, or the title)."""
        if self._table is None:
            self.status.emit("Open a file first.")
            return False
        name = (name or self.chart_name_edit.text() or self._cfg.labels.title).strip()
        try:
            store.save_chart(name, self._cfg, self._table.structure(), root=self._root)
        except store.StoreError as error:
            self.status.emit(str(error))
            return False
        self.refresh_saved_list(select=name)
        self.status.emit(f"Saved '{name}'. Saving under the same name again replaces it.")
        return True

    def _apply_loaded(self, fitted: ChartConfig, notes: List[str]) -> None:
        known = fitted.theme.name in themes.BUILTIN_THEMES or fitted.theme.name in self._custom_themes
        if not known:
            notes = notes + [f"The theme '{fitted.theme.name}' is not on this computer, so the "
                             "The default colours are used. Add the theme file to get it back."]
        self._cfg = fitted
        self._hist.push(fitted)
        self._subject = (fitted.kind, fitted.column, tuple(fitted.columns))
        self._grid_signature = ""
        self._show_notes(notes)
        self._sync_from_cfg()
        self.flush()

    def open_saved_chart(self, name: Optional[str] = None) -> bool:
        if self._table is None:
            self.status.emit("Open a file first.")
            return False
        name = name or self.saved_combo.currentData()
        try:
            chart = store.load_chart(name or "", root=self._root)
        except store.StoreError as error:
            self.status.emit(str(error))
            return False
        fitted, notes = store.fit_to_frame(chart.config, self._table.frame)
        self._apply_loaded(fitted, notes)
        self.status.emit(f"Opened '{chart.name}'.")
        return True

    def delete_saved_chart(self, name: Optional[str] = None) -> bool:
        name = name or self.saved_combo.currentData()
        done = bool(name) and store.delete_chart(name, root=self._root)
        self.refresh_saved_list()
        return done

    def export_chart_file(self) -> Optional[str]:
        if self._table is None:
            return None
        name = (self.chart_name_edit.text() or self._cfg.labels.title or "chart").strip()
        saved = store.SavedChart(name, self._cfg, self._table.structure())
        path = self._ask_save_path(export.safe_filename(name, "qchart.json"), "QualSafe chart (*.json)")
        if not path:
            return None
        Path(path).write_bytes(store.chart_to_bytes(saved))
        self.status.emit(f"Saved {Path(path).name}.")
        return path

    def import_chart_file(self, path: Optional[str] = None) -> bool:
        if self._table is None:
            self.status.emit("Open a file first.")
            return False
        path = path or self._ask_open_path("Open a chart file", "QualSafe chart (*.json);;All files (*)")
        if not path:
            return False
        try:
            chart = store.chart_from_bytes(Path(path).read_bytes())
        except (store.StoreError, OSError) as error:
            self.status.emit(str(error))
            return False
        fitted, notes = store.fit_to_frame(chart.config, self._table.frame)
        self._apply_loaded(fitted, notes)
        self.status.emit(f"Opened '{chart.name}'.")
        return True

    # ── custom themes ────────────────────────────────────────────────────────

    def _open_theme_dialog(self) -> None:
        dialog = ThemeDialog(self, base=themes.get_theme(self._cfg.theme.name, self._custom_themes))
        if dialog.exec() == QDialog.Accepted:
            try:
                self.save_theme(dialog.theme())
            except ValueError as error:
                self.status.emit(str(error))

    def save_theme(self, theme: themes.Theme) -> bool:
        """Keep a custom theme (on disk, for next time) and use it for this chart."""
        try:
            self._custom_themes = store.save_theme(theme, self._root)
        except store.StoreError as error:
            self.status.emit(str(error))
            return False
        self._cfg.theme.name = theme.name
        self._hist.push(self._cfg)
        self._sync_from_cfg()
        self.flush()
        self.status.emit(f"Saved the theme '{theme.name}'. It will be here next time too.")
        return True

    def delete_current_theme(self) -> bool:
        name = self._cfg.theme.name
        if name not in self._custom_themes:
            self.status.emit("Only your own themes can be deleted.")
            return False
        self._custom_themes = store.delete_theme(name, self._root)
        self._cfg.theme = ChartConfig().theme
        self._sync_from_cfg()
        self.flush()
        return True

    def share_current_theme(self) -> Optional[str]:
        theme = self._custom_themes.get(self._cfg.theme.name)
        if theme is None:
            self.status.emit("Only your own themes can be shared.")
            return None
        path = self._ask_save_path(export.safe_filename(theme.name, "json"), "QualSafe theme (*.json)")
        if not path:
            return None
        Path(path).write_bytes(store.theme_to_bytes(theme))
        return path

    def import_theme_file(self, path: Optional[str] = None) -> bool:
        path = path or self._ask_open_path("Add a theme file", "QualSafe theme (*.json);;All files (*)")
        if not path:
            return False
        try:
            theme = store.theme_from_bytes(Path(path).read_bytes())
        except (store.StoreError, OSError) as error:
            self.status.emit(str(error))
            return False
        return self.save_theme(theme)


def _number(text: str) -> Optional[float]:
    try:
        return float(text) if str(text).strip() else None
    except ValueError:
        return None
