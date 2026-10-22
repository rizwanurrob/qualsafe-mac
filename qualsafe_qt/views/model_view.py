"""
The Model screen (`V6_PLAN.md` Phase C, desktop half).

The Qt counterpart of `app/model_page.py`. Everything here reads the same pure
functions the web page reads — `core.model_spec`, `analysis.design_matrix`,
`analysis.models`, `analysis.double_lasso` — so the numbers are the same numbers
and the refusals are the same sentences. What changes is that the shelves are
real drop targets rather than pickers, and that the result stays on screen while
the spec is adjusted beside it.

The three decisions that carry the methodology are the same as the web page's,
because they are in the shared grammar rather than in either front end:

* **Treatment is enabled only for a method that estimates an effect.** Filling
  it is what turns prediction into inference, and requiring it means stating a
  hypothesis before the program will show a confidence interval.
* **Problems appear above the button, and blocking ones disable it.** An analyst
  should learn their project is too small before waiting for a fit.
* **The caveats are not collapsible.** A coefficient table looks authoritative
  whatever produced it.

Fitting happens on a worker thread. A gradient boosting fit on a few hundred
cases is fast but not instant, and a frozen window during it would be the sort
of thing that only shows up when somebody actually uses the program.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
from PySide6.QtCore import QObject, Qt, QThreadPool, QRunnable, Signal, Slot
from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QComboBox, QHBoxLayout, QHeaderView, QLabel,
    QPushButton, QRadioButton, QScrollArea, QSpinBox, QSplitter, QTableView, QVBoxLayout,
    QWidget,
)

from analysis.design_matrix import CODE_PREFIX, matrix_from_project
from core.model_spec import (
    METHODS, ModelRequest, Shelf as SpecShelf, can_run, describe, problems)
from core.ux import model_goals
from core.ux.fields import MODEL_KIND_WORDS, model_field_label
from qualsafe_qt.models.dataframe_model import DataFrameModel
from qualsafe_qt.services.project_service import ProjectService
from qualsafe_qt.theme import banner_style, banner_text, muted_span
from qualsafe_qt.widgets.model_shelves import MultiShelf
from qualsafe_qt.widgets.more_options import MoreOptions, count_controls
from qualsafe_qt.widgets.shelves import FieldList, Shelf
from qualsafe_qt.widgets.wrapping import WrappingLabel

#: The three things most people want to do, in plain words, and the method each one starts.
#: Every other method is under More options.
GOALS = model_goals.GOALS               # shared with the web app (core/ux/model_goals.py)
_CHOOSE = "(choose)"


class _CaveatPane(QScrollArea):
    """The caveats beside the numbers: rich text in a scroll area. It offers the few methods of a
    text browser the screen and its tests use, and is not itself a control."""

    def __init__(self) -> None:
        super().__init__()
        self._html = ""
        self._label = WrappingLabel("")
        self._label.setOpenExternalLinks(False)
        self.setWidgetResizable(True)
        self.setWidget(self._label)

    def setHtml(self, html: str) -> None:
        self._html = html
        self._label.setText(html)

    def toHtml(self) -> str:
        return self._html

    def toPlainText(self) -> str:
        from core.ux import caveats
        return caveats.plain(self._html)

#: How many code columns to put on Predictors when the screen first opens. A
#: sensible opening position beats an empty page, and the codes are what this
#: program has that a statistics package does not.
_DEFAULT_PREDICTORS = 20


class _FitSignals(QObject):
    done = Signal(object)
    failed = Signal(str)


class _FitJob(QRunnable):
    """One fit, off the UI thread."""

    def __init__(self, matrix, request: ModelRequest) -> None:
        super().__init__()
        self.signals = _FitSignals()
        self._matrix = matrix
        self._request = request

    @Slot()
    def run(self) -> None:                              # noqa: D102 - Qt override
        try:
            from analysis.models import fit

            self.signals.done.emit(fit(self._matrix, self._request))
        except Exception as error:                      # noqa: BLE001
            # Surfaced rather than swallowed: a modelling failure the analyst
            # cannot see is worse than one they can.
            self.signals.failed.emit(str(error))


class ModelView(QWidget):
    """Shelves for a model, the numbers, and everything qualifying them."""

    status = Signal(str)

    def __init__(self, service: ProjectService, undo_stack: QUndoStack,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._service = service
        self._undo = undo_stack
        self._matrix = None
        self._result = None
        self._pool = QThreadPool.globalInstance()

        self._build_ui()
        service.project_changed.connect(lambda _p: self.refresh())
        service.store_changed.connect(self.refresh)
        self.refresh()

    # -- construction --------------------------------------------------------

    def _build_ui(self) -> None:
        self.unit = QComboBox()
        self.unit.addItem("One case per document", "source_id")
        self.unit.addItem("One case per respondent", "respondent_id")
        self.unit.setToolTip(
            "What counts as a case. Per respondent only means something for\n"
            "wide-form survey data, where one person answered several questions.")
        self.unit.currentIndexChanged.connect(self.refresh)

        self.encoding = QComboBox()
        self.encoding.addItem("A code is applied or not (0/1)", "binary")
        self.encoding.addItem("A code counts how many times", "count")
        self.encoding.setToolTip(
            "0/1 is usually right in survey mode, where a passage is the whole\n"
            "response: a count would mostly measure how many pieces the\n"
            "response was split into.")
        self.encoding.currentIndexChanged.connect(self.refresh)

        self.rater = QComboBox()
        self.rater.setToolTip(
            "Whose codings build the variables.\n"
            "Pooling coders builds variables neither of them asserted, and a\n"
            "regression will report a coefficient for one anyway.")
        self.rater.currentIndexChanged.connect(self.refresh)

        self.method = QComboBox()
        for key, spec in METHODS.items():
            self.method.addItem(spec.display_label, key)
        self.method.currentIndexChanged.connect(self._on_method_changed)

        self.seed = QSpinBox()
        self.seed.setRange(0, 2_147_483_647)
        self.seed.setValue(20260829)
        self.seed.setToolTip("Fixed so the model can be reproduced. Recorded "
                             "with the result.")
        self.folds = QSpinBox()
        self.folds.setRange(2, 20)
        self.folds.setValue(5)
        self.folds.setToolTip("Cross-validation folds.")
        for widget in (self.seed, self.folds):
            widget.valueChanged.connect(self._validate)

        # -- the plain start: what do you want to do, which outcome, then Fit --
        self.goal_group = QButtonGroup(self)
        self.goal_group.setExclusive(False)       # a method chosen under More options leaves all three off
        self.goal_buttons: Dict[str, QRadioButton] = {}
        goals = QWidget()
        goals_layout = QVBoxLayout(goals)
        goals_layout.setContentsMargins(0, 0, 0, 0)
        goals_layout.addWidget(QLabel("<b>What would you like to do?</b>"))
        for key, method, text in GOALS:
            radio = QRadioButton(text)
            radio.toggled.connect(lambda on, m=method: on and self._choose_method(m))
            self.goal_group.addButton(radio)
            self.goal_buttons[key] = radio
            goals_layout.addWidget(radio)

        self.outcome_combo = QComboBox()
        self.outcome_combo.setToolTip("The thing you want to explain. You can also drag a field "
                                      "onto Outcome under More options.")
        self.outcome_combo.currentIndexChanged.connect(self._outcome_picked)
        self.treatment_combo = QComboBox()
        self.treatment_combo.setToolTip("The one thing you want a defensible effect for.")
        self.treatment_combo.currentIndexChanged.connect(self._treatment_picked)
        self.outcome_label = QLabel("What do you want to explain?")
        self.treatment_label = QLabel("The one thing whose effect you want")
        picks = QHBoxLayout()
        for label, combo in ((self.outcome_label, self.outcome_combo),
                             (self.treatment_label, self.treatment_combo)):
            picks.addWidget(label)
            picks.addWidget(combo, 1)
            picks.addSpacing(10)
        picks.addStretch(1)

        self.blurb = WrappingLabel("")

        # -- the shelves (More options): drag fields, choose predictors and controls --
        self.fields = FieldList()
        self.outcome = Shelf("outcome", "Outcome", allow_aggregate=False, labeler=model_field_label)
        self.treatment = Shelf("treatment", "Treatment", allow_aggregate=False,
                               labeler=model_field_label)
        self.predictors = MultiShelf(
            "predictors", "Predictors", "What the model may use.", labeler=model_field_label)
        self.controls = MultiShelf(
            "controls", "Controls",
            "Forced into the final model and never penalised out.", labeler=model_field_label)
        for shelf in (self.outcome, self.treatment, self.predictors,
                      self.controls):
            shelf.changed.connect(self._validate)
        self.outcome.changed.connect(self._shelf_changed)
        self.treatment.changed.connect(self._shelf_changed)

        # Outcome and Treatment take one field each; Predictors and Controls
        # take many. Stacking the two single-field shelves in one column groups
        # them by what they are, beside the shelves that hold a set.
        singles = QVBoxLayout()
        singles.setContentsMargins(0, 0, 0, 0)
        singles.addWidget(self.outcome)
        singles.addWidget(self.treatment)
        singles.addStretch(1)
        singles_holder = QWidget()
        singles_holder.setLayout(singles)

        shelf_row = QHBoxLayout()
        shelf_row.addWidget(singles_holder, 1)
        shelf_row.addWidget(self.predictors, 1)
        shelf_row.addWidget(self.controls, 1)
        shelf_holder = QWidget()
        shelf_holder.setLayout(shelf_row)

        fields_holder = QWidget()
        fields_layout = QVBoxLayout(fields_holder)
        fields_layout.setContentsMargins(0, 0, 0, 0)
        fields_layout.addWidget(QLabel("Fields"))
        fields_layout.addWidget(self.fields, 1)
        fields_holder.setMinimumHeight(200)

        drag = QWidget()
        drag_layout = QHBoxLayout(drag)
        drag_layout.setContentsMargins(0, 0, 0, 0)
        drag_layout.addWidget(fields_holder, 1)
        drag_layout.addWidget(shelf_holder, 3)

        self.problems = QLabel()
        self.problems.setWordWrap(True)
        self.problems.setTextFormat(Qt.TextFormat.RichText)
        self.problems.setStyleSheet(banner_style("warning"))
        self.problems.setVisible(False)

        self.summary = QLabel()
        self.summary.setWordWrap(True)

        self.run_button = QPushButton("Fit model")
        self.run_button.setProperty("main", True)     # the one filled button here
        self.run_button.clicked.connect(self._run)
        self.export_button = QPushButton("Export report…")
        self.export_button.setToolTip(
            "The table with its specification and caveats, as a Word\n"
            "document ready for a chapter. The design matrix is written\n"
            "beside it as CSV for anyone who wants R or Stata.")
        self.export_button.clicked.connect(self._export)
        self.export_button.setEnabled(False)
        run_row = QHBoxLayout()
        run_row.addWidget(self.run_button)
        run_row.addStretch(1)

        # -- More options: every method, the settings that keep it reproducible, the file --
        self.more = MoreOptions("More options")
        self.more.add_row("Method", self.method, tip="model.method")
        self.more.add_row("Cases", self.unit)
        self.more.add_row("Codes", self.encoding)
        self.more.add_row("Coder", self.rater)
        self.more.add_row("Seed", self.seed)
        self.more.add_row("Folds", self.folds)
        self.more.add_note("<i>Drag fields onto the shelves, or leave the codes it starts with.</i>")
        self.more.body_layout.addWidget(drag)
        self.more.body_layout.addWidget(self.export_button)
        self.more._count = count_controls(self.more.body)
        self.more._refresh_title()

        self.effect = QLabel()
        self.effect.setWordWrap(True)
        self.effect.setTextFormat(Qt.TextFormat.RichText)
        self.effect.setVisible(False)

        self.table = QTableView()
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSortingEnabled(True)
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table_model = DataFrameModel()
        self.table.setModel(self.table_model)

        # The caveats are not collapsible, and they appear with the numbers they qualify.
        self.caveats = _CaveatPane()
        self.caveats.setVisible(False)

        right = QSplitter(Qt.Orientation.Vertical)
        right.addWidget(self.table)
        right.addWidget(self.caveats)
        right.setSizes([360, 260])
        self._results = right

        self.empty_label = QLabel()
        self.empty_label.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addWidget(goals)
        layout.addLayout(picks)
        layout.addWidget(self.blurb)
        layout.addWidget(self.problems)
        layout.addWidget(self.summary)
        layout.addLayout(run_row)
        layout.addWidget(self.more)
        layout.addWidget(self.effect)
        layout.addWidget(self.empty_label)
        layout.addWidget(right, 1)

        # Starts on the readable tree, the gentlest of the three.
        self.method.setCurrentIndex(max(0, self.method.findData("decision_tree")))
        self._on_method_changed()

    # -- data ----------------------------------------------------------------

    def refresh(self) -> None:
        """Rebuild the design matrix for the current unit, coder and encoding."""
        if not self._service.is_open:
            self._show_empty("<i>No project open.</i>")
            return

        self._refresh_raters()
        self._matrix = matrix_from_project(
            self._service.project,
            unit=self.unit.currentData() or "source_id",
            encoding=self.encoding.currentData() or "binary",
            rater_id=self.rater.currentData())

        if not self._matrix.usable:
            self._show_empty(f"<i>{self._matrix.refusal}</i>")
            return

        self._set_body_visible(True)
        columns = [c for c in self._matrix.frame.columns if c != "case_id"]
        self.fields.set_fields({name: _kind(name) for name in columns}, label=model_field_label,
                               type_word=lambda kind: MODEL_KIND_WORDS.get(kind, kind))
        if not self.predictors.fields():
            self.predictors.set_fields(
                [c for c in columns if c.startswith(CODE_PREFIX)][:_DEFAULT_PREDICTORS])
        self._fill_pickers(columns)
        self.empty_label.setText(muted_span(self._matrix.describe()))
        self.empty_label.setVisible(True)
        self._validate()

    # -- the plain pickers ---------------------------------------------------

    def _fill_pickers(self, columns: List[str]) -> None:
        """Offer the fields by plain name, keeping what was picked. The shelves under More
        options hold the same choice (the dragged field wins when both change)."""
        for combo, shelf in ((self.outcome_combo, self.outcome), (self.treatment_combo, self.treatment)):
            chosen = shelf.field()
            combo.blockSignals(True)
            combo.clear()
            combo.addItem(_CHOOSE, "")
            for name in sorted(columns, key=lambda n: model_field_label(n).lower()):
                combo.addItem(model_field_label(name), name)
            index = combo.findData(chosen)
            combo.setCurrentIndex(index if index >= 0 else 0)
            combo.blockSignals(False)

    def _outcome_picked(self) -> None:
        name = self.outcome_combo.currentData() or ""
        if name:
            self._leave_out_of_predictors(name)
            self.outcome.set_field(name)
        else:
            self.outcome.clear_field()

    def _treatment_picked(self) -> None:
        name = self.treatment_combo.currentData() or ""
        if name:
            self._leave_out_of_predictors(name)
            self.treatment.set_field(name)
        else:
            self.treatment.clear_field()

    def _leave_out_of_predictors(self, name: str) -> None:
        """What you want to explain, or the effect of, cannot also be something that explains it.
        The codes the screen starts with as predictors lose it, so picking it just works."""
        fields = self.predictors.fields()
        if name in fields:
            self.predictors.set_fields([f for f in fields if f != name])

    def _shelf_changed(self) -> None:
        """A field dragged onto a shelf shows in its picker."""
        for combo, shelf in ((self.outcome_combo, self.outcome), (self.treatment_combo, self.treatment)):
            index = combo.findData(shelf.field())
            combo.blockSignals(True)
            combo.setCurrentIndex(index if index >= 0 else 0)
            combo.blockSignals(False)

    def _plain(self, text: str) -> str:
        """A sentence from the shared grammar with its internal column names in plain words."""
        text = text.replace("Drop a field on Outcome", "Choose what you want to explain")
        columns = [c for c in (self._matrix.frame.columns if self._matrix is not None else [])
                   if c != "case_id"]
        for name in sorted(columns, key=len, reverse=True):
            if name in text:
                text = text.replace(name, model_field_label(name))
        return text

    def _choose_method(self, method: str) -> None:
        """A goal was picked: use the method it starts."""
        index = self.method.findData(method)
        if index >= 0 and self.method.currentIndex() != index:
            self.method.setCurrentIndex(index)

    def goal(self) -> str:
        """Which of the three plain goals is chosen ('' when another method was picked)."""
        for key, radio in self.goal_buttons.items():
            if radio.isChecked():
                return key
        return ""

    def _refresh_raters(self) -> None:
        previous = self.rater.currentData()
        coding = self._service.coding_table()
        found = ([] if coding.empty or "rater_id" not in coding.columns
                 else sorted({str(r) for r in coding["rater_id"].dropna() if str(r)}))
        self.rater.blockSignals(True)
        self.rater.clear()
        self.rater.addItem("All coders", None)
        for rater in found:
            self.rater.addItem(rater, rater)
        if previous:
            index = self.rater.findData(previous)
            if index >= 0:
                self.rater.setCurrentIndex(index)
        self.rater.blockSignals(False)

    def _show_empty(self, message: str) -> None:
        self.empty_label.setText(message)
        self.empty_label.setVisible(True)
        self._set_body_visible(False)

    def _set_body_visible(self, visible: bool) -> None:
        for widget in (self.problems, self.summary, self.run_button,
                       self.effect, self.table):
            widget.setVisible(visible and widget is not self.effect)
        if not visible:
            self.caveats.setVisible(False)

    # -- spec ----------------------------------------------------------------

    def request(self) -> ModelRequest:
        method = self.method.currentData() or "ols"
        inferential = METHODS[method].inferential
        treatment = self.treatment.field()
        return ModelRequest(
            method=method,
            outcome=SpecShelf((self.outcome.field(),) if self.outcome.field() else ()),
            treatment=SpecShelf((treatment,) if treatment and inferential else ()),
            predictors=SpecShelf(tuple(self.predictors.fields())),
            controls=SpecShelf(tuple(self.controls.fields())),
            seed=int(self.seed.value()), folds=int(self.folds.value()))

    def _on_method_changed(self) -> None:
        """Treatment is enabled only where it means something."""
        method = self.method.currentData() or "ols"
        spec = METHODS[method]
        self.blurb.setText(muted_span(spec.blurb))
        self.treatment.setEnabled(spec.inferential)
        self.treatment_label.setVisible(spec.inferential)
        self.treatment_combo.setVisible(spec.inferential)
        # keep the three plain goals in step with the method (none when it is another method)
        for key, goal_method, _text in GOALS:
            radio = self.goal_buttons[key]
            radio.blockSignals(True)
            radio.setChecked(goal_method == method)
            radio.blockSignals(False)
        self.treatment.setToolTip(
            "The variable you want a defensible number for."
            if spec.inferential else
            "Only double lasso estimates an effect for one named variable.\n"
            "Switch method to use this shelf.")
        self._validate()

    def _validate(self) -> None:
        if self._matrix is None or not self._matrix.usable:
            return
        request = self.request()
        columns = [c for c in self._matrix.frame.columns if c != "case_id"]
        outcome = request.outcome.first
        levels = (int(self._matrix.frame[outcome].nunique())
                  if outcome in self._matrix.frame.columns else None)

        found = problems(request, columns, n_cases=self._matrix.n_cases,
                         outcome_levels=levels)
        runnable = can_run(request, columns, n_cases=self._matrix.n_cases,
                           outcome_levels=levels)

        if found:
            # Nothing chosen yet is a prompt, not a fault: a note, not a red banner.
            only_prompt = request.outcome.is_empty and len(found) == 1
            kind = "note" if only_prompt else ("warning" if runnable else "error")
            self.problems.setText(banner_text(kind, "<br>".join(f"· {self._plain(p)}" for p in found)))
            self.problems.setStyleSheet(banner_style(kind))
            self.problems.setVisible(True)
        else:
            self.problems.setVisible(False)

        self.summary.setText(muted_span(self._plain(describe(request))))
        self.run_button.setEnabled(runnable)

    # -- fitting -------------------------------------------------------------

    def _run(self) -> None:
        if self._matrix is None:
            return
        self.run_button.setEnabled(False)
        self.run_button.setText("Fitting…")
        self.status.emit("Fitting the model…")

        job = _FitJob(self._matrix, self.request())
        job.signals.done.connect(self._on_fitted)
        job.signals.failed.connect(self._on_failed)
        self._pool.start(job)

    def _on_failed(self, message: str) -> None:
        self.run_button.setText("Fit model")
        self._validate()
        self.problems.setText(banner_text("error", f"The fit failed: {message}"))
        self.problems.setStyleSheet(banner_style("error"))
        self.problems.setVisible(True)
        self.status.emit("The model could not be fitted.")

    def _on_fitted(self, result) -> None:
        self.run_button.setText("Fit model")
        self._validate()
        self._result = result

        if not result.usable:
            self.problems.setText(banner_text("error", f"{result.refusal}"))
            self.problems.setStyleSheet(banner_style("error"))
            self.problems.setVisible(True)
            self.caveats.setHtml("")
            self.caveats.setVisible(False)
            self.table_model.set_frame(pd.DataFrame())
            self.effect.setVisible(False)
            # A refused model must not be exportable: a document that
            # looks like a report and holds nothing still gets circulated.
            self.export_button.setEnabled(False)
            self.status.emit("The model was refused.")
            return

        self.table_model.set_frame(result.frame())
        self.export_button.setEnabled(True)
        self._render_effect(result)
        self._render_caveats(result)
        self.status.emit(result.describe())

    def _export(self) -> None:
        """Write the Word report and the design matrix beside it.

        Both, from one action. The report is what goes in a chapter and the
        matrix is what goes to R, and an analyst who wants one usually finds
        they wanted the other a week later.
        """
        from PySide6.QtWidgets import QFileDialog

        from exports.model_export import (
            RefusedModelError, build_model_docx, export_design_matrix)

        if self._result is None or not self._result.usable:
            return
        chosen, _ = QFileDialog.getSaveFileName(
            self, "Export the model report", "model_results.docx",
            "Word document (*.docx)")
        if not chosen:
            return

        target = Path(chosen)
        try:
            build_model_docx(self._result, self.request(), target,
                             matrix=self._matrix)
            if self._matrix is not None:
                export_design_matrix(self._matrix,
                                     target.with_name(target.stem + "_matrix.csv"))
        except RefusedModelError as error:
            self.status.emit(str(error))
            return
        except Exception as error:                      # noqa: BLE001
            self.status.emit(f"The export failed: {error}")
            return
        self.status.emit(f"Exported to {target.name}, with the design matrix "
                         "beside it.")


    def _render_effect(self, result) -> None:
        effect = result.effect
        if effect is None:
            self.effect.setVisible(False)
            return
        low, high = effect.interval
        text = (f"<b>Effect of {effect.treatment}:</b> "
                f"{effect.coefficient:.3f} "
                f"(95% interval {low:.3f} to {high:.3f}, "
                f"std. error {effect.std_error:.3f})")
        if effect.only_from_treatment:
            listed = ", ".join(effect.only_from_treatment[:4])
            text += ("<br>" + muted_span(
                f"Controls kept only because they predict the treatment: "
                f"{listed} — a single-selection lasso would have dropped these, "
                "and dropping them is what biases the estimate."))
        self.effect.setText(text)
        self.effect.setVisible(True)

    def _render_caveats(self, result) -> None:
        """Everything qualifying the numbers, in one place and never hidden."""
        rows = list(result.notes)
        rows.append(f"Seed {result.seed}. The same project and the same seed "
                    "give the same numbers.")
        if result.kind == "importance":
            rows.insert(0, "These are importances, not coefficients: they have "
                           "no direction and cannot say whether a code makes "
                           "the outcome more or less likely.")
        head = (f"<b>{result.describe()}</b>"
                f"<br>{result.n_cases} case(s) modelled"
                + (f" of {result.n_cases_before}"
                   if result.n_cases_before > result.n_cases else ""))
        body = "".join(f"<li>{note}</li>" for note in rows)
        self.caveats.setHtml(f"{head}<h4>How to read this</h4><ul>{body}</ul>")
        self.caveats.setVisible(True)


def _kind(column: str) -> str:
    """The palette's type suffix. Codes are counts, descriptors vary."""
    if column.startswith(CODE_PREFIX):
        return "code"
    if column.startswith("desc::"):
        return "descriptor"
    return "derived"
