"""
Charts: build a figure by dragging fields onto shelves, then put it in a report.

The Analysis screen answers the questions the program decided are interesting.
This answers the analyst's. It is the desktop half of `V5_PLAN.md` §B1, and the
half where drag-and-drop is actually worth having — see `widgets/shelves.py` for
why the web build uses dropdowns instead.

Everything that decides *what a chart is* lives in `core/chart_spec.py`, and
everything that computes *the numbers* lives in `core.chart_spec.aggregate`.
This module drags, paints, and saves. That division is what makes a figure built
here identical to the same figure built in the web app rather than merely
similar.

**The point of the screen is the last button.** A chart nobody can get out of the
program is a chart that does not go in the paper, so a figure saves as a PNG at
two or three times screen resolution, and the numbers behind it save as a CSV
that stands on its own. The CSV matters as much as the image: it is what a
reviewer can check and what a co-author can re-plot.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

import pandas as pd
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFrame, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QPushButton, QRadioButton, QScrollArea, QSpinBox,
    QStyle, QVBoxLayout, QWidget,
)

from analysis.crosstab import join_descriptors
from core.chart_spec import (
    MARKS, SHELVES, ChartRequest, Shelf, aggregate, can_build, infer_field_types,
    problems, suggested_charts,
)
from core.ux.fields import friendly, is_technical, type_word
from qualsafe_qt.services.project_service import ProjectService
from qualsafe_qt.theme import muted_span, warning_span
from qualsafe_qt.widgets.chart_canvas import NOT_PAINTABLE, ChartCanvas
from qualsafe_qt.widgets.more_options import MoreOptions
from qualsafe_qt.widgets.shelves import FieldList, ShelfRow
from qualsafe_qt.widgets.wrapping import WrappingLabel

#: Marks whose shelves are not axes, so the row labels them differently.
_ARCS = {"pie", "donut"}


def _signature(request: ChartRequest) -> tuple:
    """What the shelves can express: the mark and each shelf's field and aggregate.
    (A ready-made chart also carries a sort and a title, which the shelves do not.)"""
    return (request.mark, tuple((key, request.shelf(key).field,
                                 request.shelf(key).aggregate or None) for key in SHELVES))


class ChartsView(QWidget):
    """Pick a chart of your results and see it. The builder is under More options."""

    status = Signal(str)

    def __init__(self, service: ProjectService, undo: QUndoStack,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._service = service
        self._undo = undo
        self._frame = pd.DataFrame()
        self._field_types: Dict[str, str] = {}
        self._plotted = pd.DataFrame()
        self._loading_suggestions = False
        self._applying = False

        # The page scrolls when the builder is open, rather than squeezing the chart.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)
        scroll.setWidget(content)
        root = QVBoxLayout(content)

        root.addWidget(WrappingLabel(
            "<i>Pick a chart of your results and QualSafe draws it. Give it a title, save "
            "the picture or the numbers for a report, or open More options to build your own.</i>"))

        # -- pick a chart ------------------------------------------------------
        self.suggestions = QComboBox()
        self.suggestions.setToolTip(
            "Ready-made charts for these results. Choosing one draws it straight away.")
        self.suggestions.currentIndexChanged.connect(self._on_suggestion_chosen)
        pick = QHBoxLayout()
        pick.addWidget(QLabel("<b>Which chart?</b>"))
        pick.addWidget(self.suggestions, 1)
        root.addLayout(pick)

        # -- the chart, its title, and the two things to take away ---------------
        self.canvas = ChartCanvas()
        self.canvas.setMinimumHeight(340)
        root.addWidget(self.canvas, 1)

        self.title = QLineEdit()
        self.title.setPlaceholderText("Optional. Appears on the figure and names the file")
        self.title.textChanged.connect(self._refresh_chart)
        title_row = QHBoxLayout()
        title_row.addWidget(QLabel("Title"))
        title_row.addWidget(self.title, 1)
        root.addLayout(title_row)

        root.addLayout(self._build_export_row())

        # A warning gets an icon and words, never colour alone.
        self._problem_icon = QLabel()
        self._problem_icon.setPixmap(self.style().standardIcon(
            QStyle.StandardPixmap.SP_MessageBoxWarning).pixmap(16, 16))
        self._problem_icon.setFixedWidth(20)
        self._problem_icon.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._problem = QLabel()
        self._problem.setWordWrap(True)
        self._problem.setTextFormat(Qt.TextFormat.RichText)
        problem_row = QHBoxLayout()
        problem_row.addWidget(self._problem_icon)
        problem_row.addWidget(self._problem, 1)
        root.addLayout(problem_row)
        self._problem_icon.hide()

        # -- the builder, folded away -----------------------------------------
        self.more = MoreOptions("More options: build your own chart")
        self._build_builder(self.more)
        root.addWidget(self.more)

        # Same pattern as every other view: subscribe here rather than have the
        # main window fan out, so a screen added later cannot be forgotten.
        service.project_changed.connect(lambda _path: self.refresh())
        service.store_changed.connect(self.refresh)

        self._on_mark_changed()
        self.refresh()

    # -- construction --------------------------------------------------------

    def _build_builder(self, more: MoreOptions) -> None:
        """Everything about building a chart by hand: what to chart, the type,
        the fields, the shelves, charts kept with the project, the print scale."""
        self.source_codings = QRadioButton("Theme codes")
        self.source_codings.setChecked(True)
        self.source_codings.setToolTip(
            "One row for each time a theme was applied, with its coder and weight.")
        self.source_descriptors = QRadioButton("Theme codes with respondent details")
        self.source_descriptors.setToolTip(
            "The same rows, with each respondent's details (program, class year) beside "
            "them. Use this to compare groups.")
        source = QWidget()
        source_layout = QHBoxLayout(source)
        source_layout.setContentsMargins(0, 0, 0, 0)
        for button in (self.source_codings, self.source_descriptors):
            button.toggled.connect(self._reload)
            source_layout.addWidget(button)
        self.row_count = QLabel()
        self.row_count.setTextFormat(Qt.TextFormat.RichText)
        source_layout.addWidget(self.row_count, 1)
        more.add_row("What to chart", source)

        self.mark = QComboBox()
        for key, kind in MARKS.items():
            self.mark.addItem(kind.label, key)
        self.mark.currentIndexChanged.connect(self._on_mark_changed)
        self.mark_hint = QLabel()
        self.mark_hint.setWordWrap(True)
        self.mark_hint.setTextFormat(Qt.TextFormat.RichText)
        mark_box = QWidget()
        mark_layout = QVBoxLayout(mark_box)
        mark_layout.setContentsMargins(0, 0, 0, 0)
        mark_layout.addWidget(self.mark)
        mark_layout.addWidget(self.mark_hint)
        more.add_row("Chart type", mark_box)

        self.fields = FieldList()
        self.fields.setMaximumHeight(150)
        self.fields.itemDoubleClicked.connect(self._send_to_first_empty)
        self.show_technical = QCheckBox("Show technical fields (identifiers)")
        self.show_technical.setToolTip(
            "Identifiers such as a coding's ID. They are hidden because charting them "
            "gives one bar per row.")
        self.show_technical.toggled.connect(self._reload_fields)
        fields_box = QWidget()
        fields_layout = QVBoxLayout(fields_box)
        fields_layout.setContentsMargins(0, 0, 0, 0)
        fields_layout.addWidget(self.fields)
        fields_layout.addWidget(self.show_technical)
        more.add_row("Fields", fields_box)

        self.shelf_row = ShelfRow(labeler=friendly)
        self.shelf_row.changed.connect(self._refresh_chart)
        more.add_row("Where they go", self.shelf_row)

        more.add_row("Kept with this project", self._build_saved_box())

        self.scale = QSpinBox()
        self.scale.setRange(1, 4)
        self.scale.setValue(2)
        self.scale.setSuffix("x")
        self.scale.setToolTip(
            "2x or 3x for print. A screen-resolution image looks soft once a "
            "document is printed or zoomed.")
        more.add_row("Picture size", self.scale)

    def _build_saved_box(self) -> QWidget:
        """Charts kept with the project, so a figure can be redrawn later.

        The image and the CSV export a moment. This exports the method: reopen a
        saved chart after another twenty interviews and it draws against the
        project as it stands then, which is the question a study that keeps
        collecting data actually has.
        """
        box = QWidget()
        layout = QHBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)

        self.saved_charts = QComboBox()
        self.saved_charts.setToolTip(
            "Charts saved with this project. Opening one re-runs it against the "
            "data as it stands now.")
        layout.addWidget(self.saved_charts, 1)

        self.open_saved = QPushButton("Open")
        self.open_saved.clicked.connect(self._open_saved_chart)
        layout.addWidget(self.open_saved)

        self.delete_saved = QPushButton("Delete")
        self.delete_saved.clicked.connect(self._delete_saved_chart)
        layout.addWidget(self.delete_saved)

        layout.addSpacing(12)
        self.save_name = QLineEdit()
        self.save_name.setPlaceholderText("Name this chart to save it")
        self.save_name.setToolTip(
            "Saving by name replaces a chart of the same name rather than adding "
            "a second one: an analyst who tweaks a figure and saves it again "
            "means that figure.")
        layout.addWidget(self.save_name, 1)

        self.save_chart = QPushButton("Save")
        self.save_chart.clicked.connect(self._save_chart)
        layout.addWidget(self.save_chart)
        return box

    # -- saved charts --------------------------------------------------------

    def _reload_saved(self) -> None:
        self.saved_charts.clear()
        if not self._service.is_open:
            self.saved_charts.setEnabled(False)
            self.open_saved.setEnabled(False)
            self.delete_saved.setEnabled(False)
            return
        charts = self._service.project.list_charts()
        for chart in charts:
            self.saved_charts.addItem(chart.name, chart)
        has_any = bool(charts)
        self.saved_charts.setEnabled(has_any)
        self.open_saved.setEnabled(has_any)
        self.delete_saved.setEnabled(has_any)

    def _save_chart(self) -> None:
        from core.chart_spec import request_to_dict
        from core.model import SavedChart

        name = self.save_name.text().strip()
        if not name or not self._service.is_open:
            return
        request = self.request()
        if not can_build(request, self._field_types):
            # Said in the status bar, not a modal. The page is already showing
            # what is wrong with the shelves a few pixels above this button, so
            # a dialog would interrupt to repeat it -- and a modal in a save
            # path is also what made the first version of the test for this
            # block forever instead of failing.
            self.status.emit(
                "Fill the shelves first: a chart that cannot be drawn cannot be "
                "re-run either.")
            return

        source = ("codings_with_descriptors"
                  if self.source_descriptors.isChecked() else "codings")
        self._service.project.save_chart(SavedChart(
            chart_id="", name=name, spec=request_to_dict(request), source=source))
        self._service.notify_changed()
        self.save_name.clear()
        self._reload_saved()
        self.status.emit(f"Saved “{name}” with this project")

    def _open_saved_chart(self) -> None:
        from core.chart_spec import request_from_dict

        chart = self.saved_charts.currentData()
        if chart is None:
            return
        self.source_descriptors.setChecked(chart.source == "codings_with_descriptors")
        self._apply_request(request_from_dict(chart.spec))
        self.status.emit(f"Opened “{chart.name}”, re-run against this project")

    def _delete_saved_chart(self) -> None:
        chart = self.saved_charts.currentData()
        if chart is None or not self._service.is_open:
            return
        self._service.project.delete_chart(chart.name)
        self._service.notify_changed()
        self._reload_saved()

    def _apply_request(self, request: ChartRequest) -> None:
        """Push a ChartRequest into the widgets. Shared by suggestions and by
        opening a saved chart, so the two cannot behave differently."""
        self._applying = True       # the shelves are filled one by one: judge the result once
        try:
            index = self.mark.findData(request.mark)
            if index >= 0:
                self.mark.setCurrentIndex(index)   # rebuilds the shelves
            for key, shelf in self.shelf_row.shelves().items():
                source = request.shelf(key)
                shelf.set_aggregate(source.aggregate or "")
                shelf.set_field(source.field)
            self.title.setText(request.title)
        finally:
            self._applying = False
        self._refresh_chart()

    def _build_export_row(self) -> QHBoxLayout:
        """The two things you take away: a picture, and the numbers behind it."""
        row = QHBoxLayout()
        self.save_image = QPushButton("Save picture…")
        self.save_image.setProperty("main", True)    # the one filled button on this screen
        self.save_image.clicked.connect(self._save_image)
        self.save_image.setToolTip("The chart as a picture to paste into a document.")
        row.addWidget(self.save_image)

        self.save_data = QPushButton("Save the numbers…")
        self.save_data.clicked.connect(self._save_data)
        self.save_data.setToolTip(
            "The values the chart shows, as a spreadsheet. A reviewer can check them and "
            "a co-author can chart them again, so save them beside the picture.")
        row.addWidget(self.save_data)
        row.addStretch(1)
        return row

    # -- data ----------------------------------------------------------------

    def refresh(self) -> None:
        self._reload()

    def _reload(self) -> None:
        if not self._service.is_open:
            self._frame = pd.DataFrame()
            self._field_types = {}
            self.fields.set_fields({})
            self.row_count.setText(muted_span("No project open."))
            self.suggestions.clear()
            self.canvas.set_message("Open a project and pick a chart of its results.")
            return

        coding = self._service.coding_table()
        descriptors = (self._service.descriptor_table()
                       if self.source_descriptors.isChecked() else None)

        if descriptors is not None and not descriptors.empty:
            self._frame = join_descriptors(coding, descriptors)
            source = "codings joined to respondent details"
        else:
            self._frame = coding
            source = "codings"
            if self.source_descriptors.isChecked():
                source = "codings (this project has no respondent details yet)"

        self._field_types = infer_field_types(self._frame)
        self._reload_fields()
        self.row_count.setText(
            muted_span(f"{len(self._frame):,} rows from {source} · "
                       f"{len(self._field_types)} field(s)"))
        self._reload_suggestions()
        self._reload_saved()
        self._refresh_chart()

    def _reload_fields(self) -> None:
        """Show the fields under plain names; identifiers only when asked for."""
        technical = self.show_technical.isChecked()
        self.fields.set_fields(self._field_types, label=friendly, type_word=type_word,
                               hide=None if technical else is_technical)

    def _reload_suggestions(self) -> None:
        self._loading_suggestions = True
        try:
            self.suggestions.clear()
            # The frame goes in so identifiers and huge categories are filtered by
            # what they hold, not only by what they are called.
            for request in suggested_charts(self._field_types, frame=self._frame,
                                            label=friendly, prefer=("code_name",)):
                self.suggestions.addItem(request.title or request.mark, request)
        finally:
            self._loading_suggestions = False
        # Nothing drawn yet: draw the first, so the screen opens on a chart. A chart the
        # person built is never replaced by a reload.
        if self.suggestions.count() and self._shelves_are_empty():
            self.suggestions.setCurrentIndex(0)
            self._apply_suggestion()
        elif self.suggestions.count():
            self._select_matching_suggestion()

    def _shelves_are_empty(self) -> bool:
        return not any(entry["field"] for entry in self.shelf_row.assignment().values())

    def _select_matching_suggestion(self) -> None:
        """After a reload: keep the ready-made choice that is on screen, or none if the
        chart is the person's own."""
        mine = _signature(self.request())
        self._loading_suggestions = True
        self.suggestions.setCurrentIndex(-1)
        for i in range(self.suggestions.count()):
            data = self.suggestions.itemData(i)
            if isinstance(data, ChartRequest) and _signature(data) == mine:
                self.suggestions.setCurrentIndex(i)
                break
        self._loading_suggestions = False

    def _show_no_suggestion(self) -> None:
        """The chart on screen is the person's own, so no ready-made one is selected."""
        self._loading_suggestions = True
        self.suggestions.setCurrentIndex(-1)
        self._loading_suggestions = False

    def _on_suggestion_chosen(self) -> None:
        if not self._loading_suggestions:
            self._apply_suggestion()

    def _matches_suggestion(self) -> bool:
        chosen = self.suggestions.currentData()
        if not isinstance(chosen, ChartRequest):
            return False
        return _signature(chosen) == _signature(self.request())

    # -- interaction ---------------------------------------------------------

    def _on_mark_changed(self) -> None:
        key = str(self.mark.currentData() or "bar")
        kind = MARKS[key]
        self.mark_hint.setText(muted_span(kind.hint))
        keys = [name for name in SHELVES
                if name in kind.requires or name in kind.optional]
        self.shelf_row.build(keys, arc=key in _ARCS)
        self._refresh_chart()

    def _send_to_first_empty(self, item) -> None:
        shelf = self.shelf_row.first_empty()
        if shelf is not None:
            shelf.set_field(str(item.data(Qt.ItemDataRole.UserRole)))

    def _apply_suggestion(self) -> None:
        request = self.suggestions.currentData()
        if not isinstance(request, ChartRequest):
            return
        self._apply_request(request)

    def request(self) -> ChartRequest:
        """The `ChartRequest` the shelves currently describe."""
        assignment = self.shelf_row.assignment()
        shelves = {}
        for key in SHELVES:
            entry = assignment.get(key, {})
            shelves[key] = Shelf(field=entry.get("field", ""),
                                 aggregate=entry.get("aggregate") or None)
        return ChartRequest(mark=str(self.mark.currentData() or "bar"),
                            x=shelves["x"], y=shelves["y"],
                            color=shelves["color"], facet=shelves["facet"],
                            title=self.title.text().strip())

    def _refresh_chart(self) -> None:
        if self._frame.empty:
            self._problem.clear()
            self._problem_icon.hide()
            return

        request = self.request()
        found = problems(request, self._field_types)
        if (not self._applying and self.suggestions.currentIndex() >= 0
                and not self._matches_suggestion()):
            self._show_no_suggestion()

        if not can_build(request, self._field_types):
            self._problem.setText("<br>".join(warning_span(p) for p in found))
            self._problem_icon.setVisible(bool(found))
            self.canvas.set_message(
                "Pick a chart above, or open More options to build your own.")
            self._plotted = pd.DataFrame()
            self._set_export_enabled(False)
            return

        # Advice, not errors — a pie with many slices is a bad idea, not a
        # refusal. Shown in the same place so nothing is hidden by being valid.
        self._problem.setText("<br>".join(muted_span(p) for p in found))
        self._problem_icon.hide()

        try:
            self._plotted = aggregate(self._frame, request, self._field_types)
        except Exception as exc:  # noqa: BLE001 - never blank the screen
            self._problem.setText(warning_span(f"Could not work that out: {exc}"))
            self._problem_icon.show()
            self._plotted = pd.DataFrame()
            self.canvas.set_message("Nothing to plot.")
            self._set_export_enabled(False)
            return

        self.canvas.set_chart(request, self._plotted)
        # The numbers exist even when this canvas cannot paint the mark, so the
        # CSV stays available — the analyst can still plot it elsewhere.
        self._set_export_enabled(not self._plotted.empty,
                                 image=request.mark not in NOT_PAINTABLE)

    def _set_export_enabled(self, enabled: bool, *, image: bool = True) -> None:
        self.save_data.setEnabled(enabled)
        self.save_image.setEnabled(enabled and image)

    # -- export --------------------------------------------------------------

    def _default_name(self) -> str:
        title = self.title.text().strip() or "chart"
        return "".join(c if c.isalnum() or c in " -_" else "_" for c in title).strip()

    def _save_image(self) -> None:
        path, _filter = QFileDialog.getSaveFileName(
            self, "Save the figure", f"{self._default_name()}.png", "PNG image (*.png)")
        if not path:
            return
        image = self.canvas.to_image(scale=self.scale.value())
        if not image.save(path):
            QMessageBox.warning(self, "Could not save",
                                "The image could not be written to that location.")
            return
        self.status.emit(f"Figure saved to {Path(path).name}")

    def _save_data(self) -> None:
        if self._plotted.empty:
            return
        path, _filter = QFileDialog.getSaveFileName(
            self, "Save the numbers", f"{self._default_name()}.csv",
            "Comma-separated values (*.csv)")
        if not path:
            return
        try:
            self._plotted.to_csv(path, index=False)
        except Exception as exc:  # noqa: BLE001 - a locked file is the usual cause
            QMessageBox.warning(self, "Could not save", str(exc))
            return
        self.status.emit(f"Chart data saved to {Path(path).name}")

    # -- appearance ----------------------------------------------------------

    def set_theme_mode(self, mode: str, palette: str = "") -> None:
        """Named to match every other view, so the main window treats them alike."""
        self.canvas.set_theme_mode(mode, palette)
