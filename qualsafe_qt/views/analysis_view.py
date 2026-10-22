"""
Analysis: frequency, co-occurrence, code x descriptor, agreement, adjudication,
deviant cases, saturation.

The Qt counterpart of `app/analysis_page.py`. Everything here reads the same
pure functions the Streamlit page reads — `analysis.frequency`,
`analysis.cooccurrence`, `analysis.crosstab`, `analysis.agreement`,
`analysis.disagreement` — so the numbers are the same numbers. What changes is
that every count is a click away from the evidence behind it, in a pane that
stays on screen instead of a drill-down that costs a rerun.

Two things this screen is careful about, both non-negotiable:

* **Kappa only** (invariant #5). Per-code binary Cohen's kappa, always shown
  beside percent agreement, prevalence, and an insufficient-N flag. No AC1, no
  Krippendorff's alpha. The kappa paradox — high agreement, low kappa, on a rare
  code — is only legible when those columns travel together, so they are never
  separated.
* **A coder is compared with a coder, or with the engine, never mixed up**
  (invariant #6). Coder-vs-coder lists only raters whose id starts with `human`,
  so a model's codings can never pass for a second person. The adjudicated set
  is listed last, for checking a coder against the reconciliation; its caveat
  says that is not an inter-rater figure. The pipeline's engine is compared in
  its own mode, *coder vs engine*, labelled as such, with the caveats the
  reports carry (`core.agreement_pairs.compare_with_engine`); its disagreements
  can be read but not reconciled, because reconciling is between people.
* **Span coding is compared on a unit** (review F4): two coders' highlights
  rarely match to the character, so documents both have finished are compared
  sentence by sentence (or paragraph), via `core.agreement_pairs`.

* **Deviant cases propose, they never label** (review G4, Silverman ch. 17-18).
  The tab offers a reading order for one code and says so; nothing it shows is
  saved. **Saturation is code saturation only**, human coders by default, with
  the engine's caveats printed above the curve and no "saturated" verdict.

Adjudication writes to a separate `human_adjudicated` rater and never modifies
either coder's original codings, because kappa depends on them.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pandas as pd
from PySide6.QtCore import QPointF, Qt, Signal, Slot
from PySide6.QtGui import QColor, QPainter, QPen, QUndoStack
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QGroupBox, QHBoxLayout, QHeaderView, QLabel,
    QListWidget, QListWidgetItem, QMessageBox, QPushButton, QSlider, QSpinBox,
    QSplitter, QTableView, QTabWidget, QTextBrowser, QVBoxLayout, QWidget,
)

from core.ux.fields import friendly
from qualsafe_qt.models.dataframe_model import DataFrameModel
from qualsafe_qt.widgets.caveat import CaveatNote
from qualsafe_qt.widgets.more_options import MoreOptions
from qualsafe_qt.theme import (
    DEFAULT_CATEGORY_PALETTE,
    banner_style, icon_html, color, muted_color, success_color, success_span, warning_color,
)
from qualsafe_qt.services.project_service import ProjectService
from qualsafe_qt.services.tasks import run_task
from qualsafe_qt.widgets.charts import BarChart, Heatmap
from qualsafe_qt.widgets.network_canvas import NetworkCanvas

#: Kappa at or above this is "substantial"; below it a code is routed to review.
#: The survey comparison of a coder with the pipeline's engine (not a unit).
_ENGINE_MODE = "Survey responses: coder vs engine"
#: What the agreement tab can compare, and the unit each uses ("" = responses).
_COMPARE_ON = {"Survey responses": "", _ENGINE_MODE: "",
               "Document sentences": "sentence", "Document paragraphs": "paragraph"}

#: Matches `analysis.agreement.low_agreement_codes`'s default.
_KAPPA_FLOOR = 0.6
#: How many drill-back excerpts to render at once. A code with 4,000
#: applications should not build 4,000 widgets to answer "show me some".
_MAX_DRILL = 60
#: Display order for the kappa table. Every column `per_code_kappa` returns is
#: present — invariant #5 requires κ to travel with percent agreement,
#: prevalence, and the insufficient-N flag — but κ leads, because it is the
#: number the reader came for and it was scrolling off the right edge.
_KAPPA_COLUMN_ORDER = [
    "code", "kappa", "reliable", "percent_agreement", "note",
    "prevalence_human", "prevalence_model",
    "n_items", "n_human", "n_model", "n_both",
]


def _hint(text: str) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setTextFormat(Qt.TextFormat.RichText)
    return label


def _table_view() -> QTableView:
    view = QTableView()
    view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    view.setSortingEnabled(True)
    view.setAlternatingRowColors(True)
    view.horizontalHeader().setSectionResizeMode(
        QHeaderView.ResizeMode.ResizeToContents)
    view.horizontalHeader().setStretchLastSection(True)
    return view


class AnalysisView(QWidget):
    """Frequency / Co-occurrence / Code x Descriptor / Agreement."""

    status = Signal(str)
    #: Take me to this passage in the reader: (source_id, char_start, char_end).
    open_in_reader = Signal(str, int, int)

    def __init__(self, service: ProjectService, undo_stack: QUndoStack,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._service = service
        self._undo = undo_stack
        #: Swapped in by tests so the reading order can be checked without the
        #: language model. None means the project's own model.
        self._embed = None
        self._deviant_token = 0
        self._deviant_report = None
        self._theme_mode = "dark"
        self._palette_name = DEFAULT_CATEGORY_PALETTE
        self._coding = pd.DataFrame()
        self._descriptors = pd.DataFrame()
        self._cooc_drill: Dict[Any, List[str]] = {}
        self._crosstab_drill: Dict[Any, List[str]] = {}
        self._disagreements: List[dict] = []

        self._build_ui()
        service.project_changed.connect(lambda _p: self.refresh())
        service.store_changed.connect(self.refresh)
        self.refresh()

    # -- construction --------------------------------------------------------
    def _build_ui(self) -> None:
        self.tabs = QTabWidget()
        # Plain names, in the order a reader asks the questions: how often, for whom,
        # together, and do the coders agree. The network is a specialist view.
        self.tabs.addTab(self._build_frequency_tab(), "How often")
        self.tabs.addTab(self._build_crosstab_tab(), "By group")
        self.tabs.addTab(self._build_cooccurrence_tab(), "Together")
        self.tabs.addTab(self._build_agreement_tab(), "Agreement (Cohen's κ)")
        self.tabs.addTab(self._build_network_tab(), "More: Network")
        self.tabs.addTab(self._build_deviant_tab(), "More: Deviant cases")
        self.tabs.addTab(self._build_saturation_tab(), "More: Saturation")

        self.empty_label = _hint(
            "<i>No coding in this project yet. Code some passages on the "
            "Documents screen, then come back.</i>")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addWidget(self.empty_label)
        layout.addWidget(self.tabs, 1)

    def _build_frequency_tab(self) -> QWidget:
        self.freq_chart = BarChart()
        self.freq_chart.bar_clicked.connect(self._drill_frequency)
        self.freq_chart.setToolTip(
            "How often each code was applied.\n"
            "Click a bar to read the passages behind it.")
        self.freq_table = _table_view()
        self.freq_model = DataFrameModel()
        self.freq_table.setModel(self.freq_model)
        self.freq_table.clicked.connect(self._on_freq_row_clicked)
        self.freq_table.setToolTip(
            "The same counts as numbers. Click a row to read its passages;\n"
            "click a column header to sort.")

        self.freq_evidence = _EvidencePane()

        upper = QSplitter(Qt.Orientation.Horizontal)
        upper.addWidget(self.freq_chart)
        upper.addWidget(self.freq_table)
        upper.setSizes([700, 480])

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(upper)
        splitter.addWidget(self.freq_evidence)
        splitter.setSizes([420, 320])

        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.addWidget(_hint(
            "<i>How often each code was applied. Click a bar or a row to read "
            "the passages behind it.</i>"))
        layout.addWidget(splitter, 1)
        return tab

    def _build_cooccurrence_tab(self) -> QWidget:
        from core.theme import HEATMAP_SCHEMES

        self.cooc_unit = QComboBox()
        self.cooc_unit.addItem("Per passage", "excerpt_id")
        self.cooc_unit.addItem("Per document (source)", "source_id")
        self.cooc_unit.setToolTip(
            "Per passage: codes applied to the same piece of text.\n"
            "Per document: codes raised anywhere in the same document.")
        self.cooc_unit.currentIndexChanged.connect(self._refresh_cooccurrence)

        # Which coder's work the matrix is built from. Co-occurrence over a mix
        # of raters answers a question nobody asked -- see `_refresh_cooccurrence`.
        self.cooc_rater = QComboBox()
        self.cooc_rater.setToolTip(
            "Whose codings to count.\n"
            "'All coders' includes everyone who coded — which mixes human and "
            "machine judgement in one matrix.\n"
            "Pick a single coder for a matrix that one person actually asserted.")
        self.cooc_rater.currentIndexChanged.connect(self._refresh_cooccurrence)

        self.cooc_scheme = QComboBox()
        self.cooc_scheme.addItems(list(HEATMAP_SCHEMES.keys()))
        self.cooc_scheme.currentTextChanged.connect(
            lambda name: (self.cooc_heatmap.set_scheme(name), None)[1])
        self.cooc_scheme.setToolTip(
            "The colour ramp. Every ramp keeps low counts visible rather than\n"
            "fading them into the background.\n"
            "Set a default in View > Appearance.")

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Unit"))
        controls.addWidget(self.cooc_unit)
        controls.addSpacing(16)
        controls.addWidget(QLabel("Coder"))
        controls.addWidget(self.cooc_rater)
        controls.addSpacing(16)
        controls.addWidget(QLabel("Colours"))
        controls.addWidget(self.cooc_scheme)
        controls.addStretch(1)

        self.cooc_warning = CaveatNote("warning")
        self.cooc_warning.setVisible(False)

        self.cooc_heatmap = Heatmap()
        self.cooc_heatmap.cell_clicked.connect(self._drill_cooccurrence)
        self.cooc_heatmap.setToolTip(
            "Darker means the two codes were applied together more often.\n"
            "Hover for the exact count; click a cell to read the passages.\n"
            "The diagonal is each code's own total, not a co-occurrence.")
        self.cooc_evidence = _EvidencePane()

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.cooc_heatmap)
        splitter.addWidget(self.cooc_evidence)
        splitter.setSizes([760, 440])

        self.cooc_caption = _hint("")

        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.addLayout(controls)
        layout.addWidget(self.cooc_warning)
        layout.addWidget(self.cooc_caption)
        layout.addWidget(splitter, 1)
        return tab

    def _build_network_tab(self) -> QWidget:
        """The same relationships as the heatmap, drawn as a map.

        A heatmap answers *how often do these two co-occur*. It does not show
        the shape of a codebook — which codes cluster, which sits alone, which
        one bridges two groups — and that shape is what ATLAS.ti, MAXQDA and
        NVivo each ship a view for and this program did not.

        Its own unit and coder controls rather than shared ones: a researcher
        reads the matrix for a pair and the map for the whole frame, and having
        one jump when the other is adjusted is worse than a little duplication.
        """
        from analysis.code_network import DEFAULT_MIN_STRENGTH

        self.network_unit = QComboBox()
        self.network_unit.addItem("Per passage", "excerpt_id")
        self.network_unit.addItem("Per document (source)", "source_id")
        self.network_unit.currentIndexChanged.connect(self._refresh_network)

        self.network_rater = QComboBox()
        self.network_rater.setToolTip(
            "Whose codings to count.\n"
            "'All coders' mixes human and machine judgement, which inflates\n"
            "co-occurrence wherever two coders read the same passage "
            "differently.")
        self.network_rater.currentIndexChanged.connect(self._refresh_network)

        self.network_strength = QSlider(Qt.Orientation.Horizontal)
        self.network_strength.setRange(0, 100)
        self.network_strength.setValue(int(DEFAULT_MIN_STRENGTH * 100))
        self.network_strength.setFixedWidth(160)
        self.network_strength.setToolTip(
            "Minimum relationship strength (Jaccard): of the passages carrying\n"
            "either code, the share carrying both.\n"
            "Raise it for the strongest structure only; lower it to see\n"
            "everything, noise included.")
        self.network_strength.valueChanged.connect(self._refresh_network)
        self.network_strength_label = QLabel()

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Unit"))
        controls.addWidget(self.network_unit)
        controls.addSpacing(16)
        controls.addWidget(QLabel("Coder"))
        controls.addWidget(self.network_rater)
        controls.addSpacing(16)
        controls.addWidget(QLabel("Min. strength"))
        controls.addWidget(self.network_strength)
        controls.addWidget(self.network_strength_label)
        controls.addStretch(1)

        self.network_canvas = NetworkCanvas()
        self.network_canvas.setToolTip(
            "Codes applied to the same units, placed by how strongly they\n"
            "co-occur. Circle size is how much the code was used; a dashed\n"
            "outline means no relationship survived the threshold.\n"
            "Click an edge to read the passages behind it.")
        self.network_canvas.edge_clicked.connect(self._drill_network_edge)
        self.network_evidence = _EvidencePane()

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.network_canvas)
        splitter.addWidget(self.network_evidence)
        splitter.setSizes([760, 440])

        self.network_caption = _hint("")
        self.network_caption.setWordWrap(True)
        self.network_note = CaveatNote("note")
        self.network_note.setVisible(False)

        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.addLayout(controls)
        layout.addWidget(splitter, 1)
        layout.addWidget(self.network_caption)
        layout.addWidget(self.network_note)
        return tab

    def _refresh_network(self) -> None:
        """Rebuild the map, and print what it hid.

        The caveats come from the shared module rather than being written here,
        so the desktop build and the web build qualify the same picture in the
        same words.
        """
        from analysis.code_network import build_code_network

        if self._coding.empty:
            return

        strength = self.network_strength.value() / 100.0
        self.network_strength_label.setText(f"{strength:.2f}")

        unit = self.network_unit.currentData() or "excerpt_id"
        rater = self.network_rater.currentData()
        coding = self._coding
        if rater:
            coding = coding[coding["rater_id"] == rater]

        network = build_code_network(coding, unit=unit, min_strength=strength)
        self._network = network
        self.network_canvas.set_network(network)

        if not network.usable:
            self.network_caption.setText(f"<i>{network.refusal}</i>")
            self.network_note.setVisible(False)
            return

        whose = "all coders" if rater is None else f"<b>{rater}</b> only"
        notes = "<br>".join(f"· {note}" for note in network.caveats())
        self.network_caption.setText(
            f"<i>{len(network.nodes)} code(s), {len(network.edges)} "
            f"relationship(s), {whose}.</i>")
        self.network_note.setText(notes)
        self.network_note.setVisible(True)

    def _refresh_network_raters(self) -> None:
        previous = self.network_rater.currentData()
        self.network_rater.blockSignals(True)
        self.network_rater.clear()
        self.network_rater.addItem("All coders", None)
        for rater in self._contributing_raters():
            self.network_rater.addItem(rater, rater)
        if previous:
            index = self.network_rater.findData(previous)
            if index >= 0:
                self.network_rater.setCurrentIndex(index)
        self.network_rater.blockSignals(False)

    def _drill_network_edge(self, code_a: str, code_b: str) -> None:
        """Read the passages behind a relationship.

        Reading them is the only way to tell an apt pairing from a redundant
        code from one long response that happened to attract both — which the
        caveats state, and which this makes possible rather than merely
        recommended.
        """
        network = getattr(self, "_network", None)
        if network is None:
            return
        key = (code_a, code_b) if code_a < code_b else (code_b, code_a)
        ids = network.edge_units.get(key, [])
        if not ids:
            self.network_evidence.show_message(
                f"No stored passages for '{code_a}' and '{code_b}'.")
            return
        title = f"{len(ids)} passage(s) carry both '{code_a}' and '{code_b}'"
        if (self.network_unit.currentData() or "excerpt_id") == "excerpt_id":
            self.network_evidence.show_excerpts(title, ids, self._service)
        else:
            self.network_evidence.show_sources(title, ids, self._service)

    def _build_crosstab_tab(self) -> QWidget:
        self.ct_key = QComboBox()
        self.ct_key.currentIndexChanged.connect(self._refresh_crosstab)
        self.ct_key.setToolTip(
            "A respondent or document attribute. The table breaks each theme "
            "down by it.")
        self.ct_mode = QComboBox()
        self.ct_mode.addItem("Counts (distinct sources)", None)
        self.ct_mode.addItem("% within group (normalised)", "group_size")
        self.ct_mode.addItem("% with 95% intervals", "intervals")
        self.ct_mode.setToolTip(
            "Use % within group when subgroups differ in size — 10 of 20 "
            "first-generation students is a bigger deal than 15 of 200 others.")
        self.ct_mode.currentIndexChanged.connect(self._refresh_crosstab)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Group by"))
        controls.addWidget(self.ct_key)
        controls.addSpacing(16)
        controls.addWidget(QLabel("Show"))
        controls.addWidget(self.ct_mode)
        # Interval view only: which coder, and one group-vs-group comparison.
        self.ct_rater = QComboBox()
        self.ct_rater.setToolTip("Report the prevalence one coder asserted, not a pool.")
        self.ct_rater.currentIndexChanged.connect(self._refresh_crosstab)
        self.ct_compare_code = QComboBox()
        self.ct_compare_a = QComboBox()
        self.ct_compare_b = QComboBox()
        for combo in (self.ct_compare_code, self.ct_compare_a, self.ct_compare_b):
            combo.currentIndexChanged.connect(self._refresh_comparison)
        self.ct_interval_controls = QWidget()
        interval_row = QHBoxLayout(self.ct_interval_controls)
        interval_row.setContentsMargins(0, 0, 0, 0)
        for label, widget in (("Coder", self.ct_rater), ("Compare", self.ct_compare_code),
                              ("A", self.ct_compare_a), ("B", self.ct_compare_b)):
            interval_row.addWidget(QLabel(label))
            interval_row.addWidget(widget)
        self.ct_interval_controls.setVisible(False)
        controls.addWidget(self.ct_interval_controls)
        controls.addStretch(1)

        self.ct_table = _table_view()
        self.ct_table.setSortingEnabled(False)   # a crosstab's row order is its index
        self.ct_model = DataFrameModel(default_precision=1)
        self.ct_table.setModel(self.ct_model)
        self.ct_table.clicked.connect(self._drill_crosstab)
        self.ct_table.setToolTip(
            "Themes down the side, subgroups across the top.\n"
            "Click any cell to read the sources behind it.")
        self.ct_evidence = _EvidencePane()

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self.ct_table)
        splitter.addWidget(self.ct_evidence)
        splitter.setSizes([420, 320])

        self.ct_note = CaveatNote("note")      # what to keep in mind about the numbers
        self.ct_note.setVisible(False)
        self.ct_caption = _hint(
            "<i>Theme prevalence by subgroup. Click a cell to read the sources "
            "behind it.</i>")

        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.addLayout(controls)
        layout.addWidget(self.ct_caption)
        layout.addWidget(self.ct_note)
        layout.addWidget(splitter, 1)
        return tab

    def _build_agreement_tab(self) -> QWidget:
        self.rater_a = QComboBox()
        self.rater_b = QComboBox()
        for combo in (self.rater_a, self.rater_b):
            combo.currentIndexChanged.connect(self._refresh_agreement)
        self.min_support = QSpinBox()
        self.min_support.setRange(2, 15)
        self.min_support.setValue(5)
        self.min_support.setToolTip(
            "A kappa computed on a code appearing only 2–3 times is noise. "
            "Codes below this many occurrences are flagged insufficient-N "
            "instead of getting an unstable number.")
        self.min_support.valueChanged.connect(self._refresh_agreement)

        self.compare_on = QComboBox()
        self.compare_on.addItems(list(_COMPARE_ON))
        self.compare_on.setToolTip(
            "Survey responses compare whole-response codings.\n"
            "Coder vs engine compares a coder with the analysis engine's coding\n"
            "of the same responses (the figure the reports print).\n"
            "Documents compare span coding -- yours, or a colleague's imported\n"
            "from NVivo, MAXQDA or ATLAS.ti -- one sentence or paragraph at a time.")
        self.compare_on.currentIndexChanged.connect(self._refresh_raters)
        self._set_rater_tooltips()
        self.span_documents = QListWidget()
        self.span_documents.setToolTip(
            "Documents both coders have coded. Tick the ones both have finished:\n"
            "only those are compared, because in an unfinished document the\n"
            "sentences nobody has reached yet would count as \"no code applies\".")
        self.span_documents.setMaximumHeight(120)
        self.span_documents.itemChanged.connect(self._document_finished_changed)
        self.span_documents.setVisible(False)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Compare"))
        controls.addWidget(self.compare_on)
        controls.addSpacing(16)
        controls.addWidget(QLabel("Coder A"))
        controls.addWidget(self.rater_a)
        controls.addWidget(QLabel("Coder B"))
        controls.addWidget(self.rater_b)
        controls.addSpacing(16)
        controls.addWidget(QLabel("Fewest answers per theme"))
        controls.addWidget(self.min_support)
        controls.addStretch(1)

        self.model_note = _hint("")
        self.model_note.setVisible(False)
        self.kappa_summary = _hint("")
        self.kappa_table = _table_view()
        self.kappa_model = DataFrameModel(
            precision={"kappa": 3, "percent_agreement": 3,
                       "prevalence_human": 3, "prevalence_model": 3})
        self.kappa_table.setModel(self.kappa_model)
        # The per-code rows are the substance of an IRR report — one visible row
        # under a summary line is not a table, it is a teaser.
        self.kappa_table.setMinimumHeight(210)
        self.kappa_table.setToolTip(
            "One row per code.\n"
            "kappa: agreement corrected for chance. Rough reading — below 0.4\n"
            "poor, 0.4-0.6 moderate, 0.6-0.8 substantial, above 0.8 strong.\n"
            "reliable: whether enough items carried the code to trust the number.\n"
            "prevalence: how often each coder used it — a rare code can show high\n"
            "agreement and a low kappa, which is why both are shown.")
        self.routed_label = _hint("")

        self.disagreement_list = QListWidget()
        self.disagreement_list.setWordWrap(True)
        self.disagreement_list.currentRowChanged.connect(self._show_disagreement)
        self.disagreement_list.setToolTip(
            "Items the two coders coded differently.\n"
            "A tick means you have already resolved it.")
        self.adjudication_panel = _AdjudicationPanel()
        self.adjudication_panel.resolved.connect(self._save_adjudication)

        reconcile = QSplitter(Qt.Orientation.Horizontal)
        reconcile.addWidget(self.disagreement_list)
        reconcile.addWidget(self.adjudication_panel)
        reconcile.setSizes([560, 620])

        # Reconciling is a separate job from reading agreement, so it is folded away.
        reconcile.setMinimumHeight(260)
        self.reconcile_more = MoreOptions("More options: reconcile disagreements")
        self.reconcile_more.add_note(
            "<i>The items the two coders coded differently. Resolving one saves it as a "
            "separate reconciled coder: neither coder's original codes change, because "
            "agreement depends on them.</i>")
        self.reconcile_more.body_layout.addWidget(reconcile)

        top = QWidget()
        top_layout = QVBoxLayout(top)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.addWidget(self.model_note)
        top_layout.addWidget(self.span_documents)
        top_layout.addWidget(self.kappa_summary)
        top_layout.addWidget(self.kappa_table, 1)
        top_layout.addWidget(self.routed_label)

        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.addLayout(controls)
        layout.addWidget(_hint(
            "<i>Per-code Cohen's κ, shown beside percent agreement and "
            "prevalence so rare-code paradoxes stay visible. Coder vs coder "
            "lists only people; the analysis engine is compared in its own "
            "mode, <b>coder vs engine</b>, never as a second coder.</i>"))
        layout.addWidget(top, 1)
        layout.addWidget(self.reconcile_more)
        return tab

    # -- deviant cases -------------------------------------------------------
    def _build_deviant_tab(self) -> QWidget:
        """Responses that carry a code but do not read like it.

        Ported from `app/analysis_page._render_deviant_tab`, with the same rule:
        this **proposes passages to re-read** and never calls any of them
        deviant. Distance from the centre of a code is a property of the
        language model, not a finding about the data, and nothing here is
        written into the project.
        """
        from analysis.deviant_cases import DEFAULT_TOP_N

        self.dev_code = QComboBox()
        self.dev_code.setToolTip(
            "The code to check. The number is how many times you applied it.")
        self.dev_code.currentIndexChanged.connect(self._clear_deviant_results)
        self.dev_count = QSpinBox()
        self.dev_count.setRange(3, 20)
        self.dev_count.setValue(DEFAULT_TOP_N)
        self.dev_count.setToolTip("How many passages to offer for re-reading.")
        self.dev_run = QPushButton("Find them")
        self.dev_run.clicked.connect(self._find_deviants)
        self.dev_run.setToolTip(
            "Reads the passages with the language model that runs on this\n"
            "computer. It takes a few seconds the first time.")

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Code"))
        controls.addWidget(self.dev_code, 1)
        controls.addSpacing(16)
        controls.addWidget(QLabel("How many"))
        controls.addWidget(self.dev_count)
        controls.addSpacing(16)
        controls.addWidget(self.dev_run)

        self.dev_message = _hint("")
        self.dev_caveats = _hint("")
        self.dev_caveats.setVisible(False)
        self.dev_caveats.setStyleSheet(banner_style("warning"))

        self.dev_list = QListWidget()
        self.dev_list.setWordWrap(True)
        self.dev_list.currentRowChanged.connect(self._show_deviant)
        self.dev_list.itemActivated.connect(lambda _item: self._open_deviant())
        self.dev_list.setToolTip(
            "Passages to re-read, furthest first. This is a reading order,\n"
            "not a verdict. Click one to read it; double-click to open it in\n"
            "the reader.")
        self.dev_passage = _EvidencePane()
        self.dev_passage.show_message(
            "Pick a code and press Find them. Click a passage to read it.")
        self.dev_open = QPushButton("Open in the reader")
        self.dev_open.setEnabled(False)
        self.dev_open.clicked.connect(self._open_deviant)
        self.dev_open.setToolTip("Go to this passage in the document it came from.")

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(self.dev_passage, 1)
        right_layout.addWidget(self.dev_open)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.dev_list)
        splitter.addWidget(right)
        splitter.setSizes([520, 660])

        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.addWidget(_hint(
            "<i>For one code, the passages furthest from how you have used that "
            "code elsewhere. They are worth re-reading: some will be genuine "
            "outliers that sharpen the analysis, and some will be miscodings. "
            "The program proposes what to read; it does not decide that any of "
            "them is deviant, and nothing here is saved to your project.</i>"))
        layout.addLayout(controls)
        layout.addWidget(self.dev_message)
        layout.addWidget(self.dev_caveats)
        layout.addWidget(splitter, 1)
        return tab

    def _refresh_deviant_codes(self) -> None:
        previous = self.dev_code.currentData()
        counts = self._coding["code_name"].value_counts()
        self.dev_code.blockSignals(True)
        self.dev_code.clear()
        for name, n in counts.items():
            self.dev_code.addItem(f"{name}  ({n})", name)
        index = self.dev_code.findData(previous)
        self.dev_code.setCurrentIndex(index if index >= 0 else 0)
        self.dev_code.blockSignals(False)
        self._clear_deviant_results()

    def _clear_deviant_results(self, *_args) -> None:
        """Drop a reading order that no longer matches what is on screen."""
        from analysis.deviant_cases import MIN_APPLICATIONS

        self._deviant_token += 1        # a result still on its way is now stale
        self._deviant_report = None
        self.dev_list.clear()
        self.dev_open.setEnabled(False)
        self.dev_caveats.setVisible(False)
        self.dev_run.setEnabled(True)
        code = self.dev_code.currentData()
        if not code or self._coding.empty:
            self.dev_message.setText("<i>Nothing is coded yet.</i>")
            return
        n = int((self._coding["code_name"] == code).sum())
        if n < MIN_APPLICATIONS:
            self.dev_message.setText(
                f"<i>“{_escape(code)}” is on {n} passage(s). Below "
                f"{MIN_APPLICATIONS} the centre of a code sits close to every "
                "passage, so distance from it says nothing. Code a few more "
                "first.</i>")
            self.dev_run.setEnabled(False)
            return
        self.dev_message.setText(
            "<i>This reads the passages with the language model on this "
            "computer, so it needs the analysis engine installed and takes a "
            "few seconds the first time.</i>")

    def _find_deviants(self) -> None:
        from analysis.deviant_cases import coded_responses

        code = self.dev_code.currentData()
        if not code or not self._service.is_open:
            return
        self._clear_deviant_results()
        if not self.dev_run.isEnabled():
            return
        # The store is read here: a database connection belongs to the thread
        # that opened it. Only the reading, which is slow, goes to the worker.
        collected = coded_responses(self._service.project, code)
        token = self._deviant_token
        self.dev_run.setEnabled(False)
        self.dev_message.setText("<i>Reading the passages…</i>")
        run_task(
            _rank_deviants, token, collected["texts"], collected["identifiers"],
            code, int(self.dev_count.value()), self._embed,
            on_finished=self._deviants_ready,
            on_failed=self._deviants_failed)

    @Slot(object)
    def _deviants_ready(self, outcome) -> None:
        token, report = outcome
        if token != self._deviant_token:
            return                       # the code changed while it was reading
        self.dev_run.setEnabled(True)
        if report is None:
            self.dev_message.setText(
                "<b>This needs the analysis engine</b> (the language model), "
                "which is not installed here. Everything else on this screen "
                "works without it.")
            return
        if not report.usable:
            self.dev_message.setText(f"<i>{_escape(report.refusal)}</i>")
            return
        self._deviant_report = report
        self.dev_message.setText(
            f"<i>{len(report.candidates)} of {report.considered} passages "
            f"coded “{_escape(report.code_name)}”, furthest first.</i>")
        self.dev_caveats.setText(
            "<br>".join(f"· {_escape(note)}" for note in report.caveats()))
        self.dev_caveats.setVisible(True)
        for candidate in report.candidates:
            quote = " ".join(candidate.text.split())
            quote = quote if len(quote) <= 110 else quote[:107] + "…"
            entry = QListWidgetItem(f"{candidate.why()}\n{quote}")
            entry.setData(Qt.ItemDataRole.UserRole, candidate)
            self.dev_list.addItem(entry)
        self.dev_list.setCurrentRow(0)

    @Slot(str, str)
    def _deviants_failed(self, message: str, _trace: str) -> None:
        self.dev_run.setEnabled(True)
        self.dev_message.setText(
            f"<b>Could not read the passages:</b> {_escape(message)}")

    def _current_deviant(self):
        item = self.dev_list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _show_deviant(self, _row: int) -> None:
        candidate = self._current_deviant()
        self.dev_open.setEnabled(candidate is not None)
        if candidate is None:
            return
        source = self._service.source_lookup().get(candidate.source_id)
        label = (source.label or source.source_id) if source else ""
        self.dev_passage.setHtml(
            f"<p style='color:{muted_color()}'><i>{_escape(candidate.why())}</i></p>"
            + (f"<p style='color:{muted_color()}'>{_escape(str(label))}</p>"
               if label else "")
            + _quote_block(candidate.text))

    def _open_deviant(self) -> None:
        candidate = self._current_deviant()
        if candidate is None:
            return
        excerpt = self._service.excerpt_lookup().get(candidate.excerpt_id)
        if excerpt is None:
            self.status.emit("That passage is no longer in the project.")
            return
        self.open_in_reader.emit(
            excerpt.source_id, int(excerpt.char_start), int(excerpt.char_end))

    # -- saturation ----------------------------------------------------------
    def _build_saturation_tab(self) -> QWidget:
        """New codes against sources coded -- and every reason not to over-read it.

        Ported from `app/analysis_page._render_saturation_tab`. This is *code*
        saturation only (no new labels appeared), human coders by default, and
        the caveats the engine returns sit above the curve, because a figure
        quoted in a methods section travels without whatever sat below it. There
        is no "saturated" verdict anywhere on this tab.
        """
        self.sat_humans = QCheckBox("Human coding only")
        self.sat_humans.setChecked(True)
        self.sat_humans.setToolTip(
            "A model applying a fixed list of labels reaches a flat curve at\n"
            "once and has discovered nothing, so including it flatters the curve.")
        self.sat_humans.toggled.connect(self._refresh_saturation)
        self.sat_order = QCheckBox("Sources are in collection order")
        self.sat_order.setToolTip(
            "Tick only if the order the sources were added is really the order\n"
            "the data was collected. Saturation is a claim about sequence.")
        self.sat_order.toggled.connect(self._refresh_saturation)

        controls = QHBoxLayout()
        controls.addWidget(self.sat_humans)
        controls.addSpacing(16)
        controls.addWidget(self.sat_order)
        controls.addStretch(1)

        self.sat_message = _hint("")
        self.sat_caveats = _hint("")
        self.sat_caveats.setStyleSheet(banner_style("warning"))
        self.sat_summary = _hint("")
        self.sat_chart = _CurveChart()
        self.sat_chart.setMinimumHeight(180)
        self.sat_chart.setToolTip(
            "Codes discovered so far (up) against sources coded (across).\n"
            "A curve that flattens means later sources produced no new labels.")
        self.sat_table = _table_view()
        self.sat_table.setSortingEnabled(False)   # the order is the point
        self.sat_model = DataFrameModel()
        self.sat_table.setModel(self.sat_model)

        self.sat_sentence = QTextBrowser()
        self.sat_sentence.setMaximumHeight(80)
        self.sat_copy = QPushButton("Copy")
        self.sat_copy.clicked.connect(
            lambda: QApplication.clipboard().setText(
                self.sat_sentence.toPlainText()))
        self.sat_copy.setToolTip("Copy this sentence for your methods section.")

        sentence_row = QHBoxLayout()
        sentence_row.addWidget(self.sat_sentence, 1)
        sentence_row.addWidget(self.sat_copy, 0, Qt.AlignmentFlag.AlignTop)

        self.sat_body = QWidget()
        body = QVBoxLayout(self.sat_body)
        body.setContentsMargins(0, 0, 0, 0)
        body.addWidget(self.sat_caveats)
        body.addWidget(self.sat_summary)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.sat_chart)
        splitter.addWidget(self.sat_table)
        splitter.setSizes([700, 480])
        body.addWidget(splitter, 1)
        body.addWidget(QLabel("<b>For your methods section</b>"))
        body.addLayout(sentence_row)
        body.addWidget(_hint(
            "<i>Copy this, then add which of the cautions above apply to your "
            "study. The program deliberately does not say whether saturation "
            "was reached: that is a judgement about your design, not a "
            "number.</i>"))

        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.addWidget(_hint(
            "<i>How many new codes each source added, in order. A curve that "
            "flattens means later sources stopped producing new labels. This is "
            "<b>code</b> saturation only: it says nothing about whether the "
            "codes you have are richly enough understood.</i>"))
        layout.addLayout(controls)
        layout.addWidget(self.sat_message)
        layout.addWidget(self.sat_body, 1)
        return tab

    def _refresh_saturation(self, *_args) -> None:
        from analysis.saturation import (
            saturation_caveats, saturation_curve, saturation_summary)

        if self._coding.empty or not self._service.is_open:
            return
        sources = self._service.project.list_sources()          # labels only: the order comes from below
        curve = saturation_curve(
            self._coding, source_order=self._service.project.source_ids_in_ingestion_order(),
            humans_only=self.sat_humans.isChecked())
        self.sat_model.set_frame(pd.DataFrame())
        self.sat_chart.set_curve(curve)
        if curve.empty:
            self.sat_body.setVisible(False)
            self.sat_message.setVisible(True)
            self.sat_message.setText(
                "<i>No human coding yet, so there is no discovery to plot. Code "
                "some passages by hand and the curve appears.</i>"
                if self.sat_humans.isChecked() else "<i>Nothing coded yet.</i>")
            return

        summary = saturation_summary(curve)
        notes = saturation_caveats(
            curve, codes=self._service.codebook(),
            order_is_collection_order=self.sat_order.isChecked())
        labels = {s.source_id: (s.label or s.source_id) for s in sources}
        shown = pd.DataFrame({
            "Order": curve["position"],
            "Source": [labels.get(str(i), str(i)) for i in curve["source_id"]],
            "New codes": curve["new_codes"],
            "Codes so far": curve["cumulative_codes"],
        })
        self.sat_model.set_frame(shown)
        self.sat_message.setVisible(False)
        self.sat_body.setVisible(True)
        self.sat_caveats.setText("<br>".join(f"· {_escape(n)}" for n in notes))
        self.sat_summary.setText(
            f"<b>{summary.codes_found}</b> codes found · last new code at source "
            f"<b>#{summary.last_new_code_at}</b> · <b>{summary.plateau_length}</b> "
            "source(s) since")
        self.sat_sentence.setPlainText(summary.as_sentence())

    # -- data ----------------------------------------------------------------
    def set_theme_mode(self, mode: str, palette: str = "",
                       heatmap_scheme: str = "") -> None:
        self._theme_mode = mode if mode in ("dark", "light") else "dark"
        self._palette_name = palette or self._palette_name
        self.freq_chart.set_theme_mode(self._theme_mode)
        self.cooc_heatmap.set_theme_mode(self._theme_mode)
        if heatmap_scheme:
            index = self.cooc_scheme.findText(heatmap_scheme)
            if index >= 0:
                self.cooc_scheme.setCurrentIndex(index)
            self.cooc_heatmap.set_scheme(heatmap_scheme)

    def refresh(self) -> None:
        if not self._service.is_open:
            self._show_empty("<i>No project open.</i>")
            return
        self._coding = self._service.coding_table()
        self._descriptors = self._service.descriptor_table()
        if self._coding.empty:
            self._show_empty(
                "<i>No coding in this project yet. Code some passages on the "
                "Documents screen, then come back.</i>")
            return

        self.empty_label.setVisible(False)
        self.tabs.setVisible(True)
        self._refresh_frequency()
        self._refresh_cooc_raters()
        self._refresh_cooccurrence()
        self._refresh_network_raters()
        self._refresh_network()
        self._refresh_descriptor_keys()
        self._refresh_raters()
        self._refresh_deviant_codes()
        self._refresh_saturation()

    def _show_empty(self, message: str) -> None:
        self.empty_label.setText(message)
        self.empty_label.setVisible(True)
        self.tabs.setVisible(False)

    # -- frequency -----------------------------------------------------------
    def _refresh_frequency(self) -> None:
        from analysis.frequency import code_frequency

        freq = code_frequency(self._coding)
        self._freq_frame = freq
        self.freq_chart.set_data(
            [(row["code_name"], row["n"]) for _i, row in freq.iterrows()])
        self.freq_model.set_frame(freq[["code_name", "n"]].copy())

    def _on_freq_row_clicked(self, index) -> None:
        name = self.freq_model.value_at(index.row(),
                                        self.freq_model.column_index("code_name"))
        if name:
            self._drill_frequency(str(name))

    def _drill_frequency(self, code_name: str) -> None:
        rows = self._freq_frame[self._freq_frame["code_name"] == code_name]
        if rows.empty:
            return
        excerpt_ids = list(rows.iloc[0]["excerpt_ids"])
        self.freq_evidence.show_excerpts(
            f"{len(excerpt_ids)} passage(s) coded '{code_name}'",
            excerpt_ids, self._service)

    # -- co-occurrence -------------------------------------------------------
    def _refresh_cooccurrence(self) -> None:
        """Rebuild the matrix for the chosen unit and coder.

        **Why the coder filter exists.** `app/analysis_page._render_cooc_tab`
        builds the matrix from the whole `coding_table()`, so in a project where
        the pipeline auto-coded and an analyst hand-coded, a passage the analyst
        marked *Financial concerns* and the model marked *Advising* registers as
        a co-occurrence of the two — a pairing neither of them asserted. It is
        also unstable in a way a finding should not be: rerun the pipeline with
        a different model and the "themes travel together" matrix moves, though
        no human changed their mind.

        The default stays "all coders" so the number matches the Streamlit build
        (a project must not read differently in the two front ends), but when
        more than one rater has contributed the mixing is stated rather than
        silent, and one click gives the single-coder view. Same pattern as the
        kappa caveats: the caveat travels with the number.
        """
        from analysis.cooccurrence import cooccurrence_matrix

        if self._coding.empty:
            return
        group_col = self.cooc_unit.currentData() or "excerpt_id"
        rater = self.cooc_rater.currentData()
        coding = self._coding
        if rater:
            coding = coding[coding["rater_id"] == rater]

        matrix, drill = cooccurrence_matrix(coding, group_col=group_col)
        self._cooc_drill = drill
        self.cooc_heatmap.set_matrix(matrix)

        raters = self._contributing_raters()
        if rater is None and len(raters) > 1:
            self.cooc_warning.setText(
                f"<b>This matrix mixes {len(raters)} coders.</b> "
                f"({', '.join(raters)}). A passage one coder marked <i>A</i> and "
                "another marked <i>B</i> counts as an A+B co-occurrence, which "
                "neither of them claimed. Pick a single coder above for a "
                "matrix one person actually asserted.")
            self.cooc_warning.setVisible(True)
        else:
            self.cooc_warning.setVisible(False)

        whose = "all coders" if rater is None else f"<b>{rater}</b> only"
        if group_col == "source_id":
            self.cooc_caption.setText(
                f"<i>Codes raised anywhere in the same document, {whose}. The "
                "diagonal is each code's own total and is drawn muted — it is "
                "not a co-occurrence.</i>")
        else:
            self.cooc_caption.setText(
                f"<i>Codes applied to the same passage, {whose}. With "
                "whole-response passages this is <b>co-mention within one "
                "response</b>, not same-sentence overlap.</i>")

    def _contributing_raters(self) -> List[str]:
        """Rater ids that actually applied a code in this project."""
        if self._coding.empty or "rater_id" not in self._coding.columns:
            return []
        return sorted({str(r) for r in self._coding["rater_id"].dropna() if str(r)})

    def _refresh_cooc_raters(self) -> None:
        previous = self.cooc_rater.currentData()
        self.cooc_rater.blockSignals(True)
        self.cooc_rater.clear()
        self.cooc_rater.addItem("All coders", None)
        for rater in self._contributing_raters():
            self.cooc_rater.addItem(rater, rater)
        if previous:
            index = self.cooc_rater.findData(previous)
            if index >= 0:
                self.cooc_rater.setCurrentIndex(index)
        self.cooc_rater.blockSignals(False)

    def _drill_cooccurrence(self, code_a: str, code_b: str) -> None:
        key = (code_a, code_b) if (code_a, code_b) in self._cooc_drill else (code_b, code_a)
        ids = self._cooc_drill.get(key, [])
        if not ids:
            self.cooc_evidence.show_message(
                f"'{code_a}' and '{code_b}' never co-occur in this unit.")
            return
        title = f"{len(ids)} unit(s) carry both '{code_a}' and '{code_b}'"
        if (self.cooc_unit.currentData() or "excerpt_id") == "excerpt_id":
            self.cooc_evidence.show_excerpts(title, ids, self._service)
        else:
            self.cooc_evidence.show_sources(title, ids, self._service)

    # -- code x descriptor ---------------------------------------------------
    def _refresh_descriptor_keys(self) -> None:
        self.ct_key.blockSignals(True)
        self.ct_key.clear()
        if not self._descriptors.empty:
            for key in sorted(self._descriptors["key"].unique().tolist()):
                self.ct_key.addItem(friendly(str(key)), str(key))        # shown readable, kept as stored
        self.ct_key.blockSignals(False)
        self._refresh_crosstab()

    def _group_key(self) -> str:
        """The stored name of the respondent detail the table is grouped by (the list shows it readable)."""
        return str(self.ct_key.currentData() or "")

    def _refresh_crosstab(self) -> None:
        from analysis.crosstab import code_by_descriptor

        if self._descriptors.empty or not self._group_key():
            self.ct_model.set_frame(pd.DataFrame())
            self.ct_caption.setText(
                "<i>No respondent details in this project. These are attributes of "
                "each respondent or document (program, class year, site); they come "
                "from a survey's designated columns, or from cases.</i>")
            self.ct_note.setVisible(False)
            return
        self.ct_interval_controls.setVisible(self.ct_mode.currentData() == "intervals")
        if self.ct_mode.currentData() != "intervals":
            self.ct_note.setVisible(False)
        if self.ct_mode.currentData() == "intervals":
            self._refresh_prevalence_intervals()
            return
        table, drill = code_by_descriptor(
            self._coding, self._descriptors, self._group_key(),
            normalize=self.ct_mode.currentData())
        self._crosstab_drill = drill
        self.ct_model.set_frame(table)
        suffix = ("% of each group's sources coded with the theme"
                  if self.ct_mode.currentData() else "distinct sources per cell")
        self.ct_caption.setText(
            f"<i>Theme prevalence by <b>{self.ct_key.currentText()}</b> — "
            f"{suffix}. Click a cell to read the sources behind it.</i>")

    def _refresh_prevalence_intervals(self) -> None:
        """Prevalence per group with 95% Wilson intervals (analysis.prevalence)."""
        from analysis.prevalence import CAVEATS, display_table, pooling_caveat, prevalence_table

        raters = sorted(self._coding["rater_id"].dropna().unique())
        wanted = self.ct_rater.currentData()
        self.ct_rater.blockSignals(True)
        self.ct_rater.clear()
        self.ct_rater.addItem("All coders (pooled)", None)
        for rater in raters:
            self.ct_rater.addItem(rater, rater)
        index = self.ct_rater.findData(wanted)
        self.ct_rater.setCurrentIndex(index if index >= 0 else 0)
        self.ct_rater.blockSignals(False)
        rater = self.ct_rater.currentData()

        self._prevalence = prevalence_table(self._coding, self._descriptors,
                                            self._group_key(), rater_id=rater)
        self._crosstab_drill = {}
        self.ct_model.set_frame(display_table(self._prevalence))
        shown = self._coding if rater is None else self._coding[self._coding["rater_id"] == rater]
        notes = [pooling_caveat(shown)] + CAVEATS
        self.ct_caption.setText(
            f"<i>Theme prevalence by <b>{self.ct_key.currentText()}</b>, with 95% intervals. "
            "Click a cell to read the sources behind it.</i>")
        self.ct_note.setText("<br>".join(n for n in notes if n))
        self.ct_note.setVisible(True)

        for combo, values in ((self.ct_compare_code, sorted(self._prevalence["code"].unique())),
                              (self.ct_compare_a, list(dict.fromkeys(self._prevalence["group"]))),
                              (self.ct_compare_b, list(dict.fromkeys(self._prevalence["group"])))):
            current = combo.currentText()
            combo.blockSignals(True)
            combo.clear()
            combo.addItems([str(v) for v in values])
            if current in [str(v) for v in values]:
                combo.setCurrentText(current)
            combo.blockSignals(False)
        if self.ct_compare_b.count() > 1 and self.ct_compare_b.currentIndex() == self.ct_compare_a.currentIndex():
            self.ct_compare_b.blockSignals(True)
            self.ct_compare_b.setCurrentIndex(1)
            self.ct_compare_b.blockSignals(False)
        self._refresh_comparison()

    def _refresh_comparison(self) -> None:
        from analysis.prevalence import compare_groups, describe_difference

        table = getattr(self, "_prevalence", None)
        if (table is None or table.empty or self.ct_mode.currentData() != "intervals"
                or self.ct_compare_a.currentText() == self.ct_compare_b.currentText()):
            self.ct_evidence.show_message("")
            return
        by_text = {str(g): g for g in table["group"]}
        result = compare_groups(table, self.ct_compare_code.currentText(),
                                by_text.get(self.ct_compare_a.currentText()),
                                by_text.get(self.ct_compare_b.currentText()))
        self.ct_evidence.show_message(describe_difference(result))

    def _drill_crosstab(self, index) -> None:
        frame = self.ct_model.frame
        if frame.empty or self.ct_mode.currentData() == "intervals":
            return
        code_name = str(frame.index[index.row()])
        value = str(frame.columns[index.column()])
        source_ids = self._crosstab_drill.get((code_name, value), [])
        self.ct_evidence.show_sources(
            f"{len(source_ids)} source(s) coded '{code_name}' where "
            f"{self.ct_key.currentText()} = {value}",
            source_ids, self._service)

    # -- agreement -----------------------------------------------------------
    def _model_comparison_note(self) -> str:
        """Point to where the machine coding in this project can be compared.

        Silence would look like an oversight: the model's codings are visibly in
        the project. The pipeline's engine is compared in the *coder vs engine*
        mode. The text-search auto-coder never is (a search is not a coder), and
        a Laya run is checked by calibration, on a random sample, instead.
        """
        if self._engine_mode():
            return ""
        machine = sorted({r for r in self._contributing_raters()
                          if not r.startswith("human")})
        if not machine:
            return ""
        engines = set(self._service.engine_rater_ids())
        parts = []
        if engines & set(machine):
            parts.append(
                "This project also contains the analysis engine's coding. It is "
                "not listed as a coder here; compare it under <b>Compare → "
                f"{_ENGINE_MODE}</b>.")
        others = [r for r in machine if r not in engines]
        if others:
            parts.append(
                f"Other machine coding ({', '.join(others)}) is never compared: "
                "text-search auto-coding is a search, not a coder, and a structured "
                "(Laya) run is checked by calibration on a random sample.")
        return "<i>" + " ".join(parts) + "</i>"

    def _engine_mode(self) -> bool:
        return self.compare_on.currentText() == _ENGINE_MODE

    def _set_rater_tooltips(self) -> None:
        if self._engine_mode():
            self.rater_a.setToolTip("The coder: a person.")
            self.rater_b.setToolTip(
                "The analysis engine, one run at a time, most recent first.\n"
                "Runs are never pooled: two runs are two different coders.")
        else:
            self.rater_a.setToolTip(
                "The first coder. Only people are listed here; the analysis\n"
                "engine has its own mode, Coder vs engine.")
            self.rater_b.setToolTip("The second coder to compare against.")

    def _span_unit(self) -> str:
        """"" for survey responses, else "sentence" / "paragraph"."""
        return _COMPARE_ON.get(self.compare_on.currentText(), "")

    def _refresh_raters(self) -> None:
        self._set_rater_tooltips()
        if self._engine_mode():
            humans = self._service.human_rater_ids()
            primary = self._service.primary_human_id()
            for combo, items, default in (
                    (self.rater_a, humans, primary),
                    (self.rater_b, self._service.engine_rater_ids(), None)):
                combo.blockSignals(True)
                combo.clear()
                combo.addItems(items)
                if default in items:
                    combo.setCurrentText(default)
                combo.blockSignals(False)
            self._refresh_agreement()
            return
        raters = (self._service.span_rater_ids() if self._span_unit()
                  else self._service.human_rater_ids())
        for combo in (self.rater_a, self.rater_b):
            combo.blockSignals(True)
            previous = combo.currentText()
            combo.clear()
            combo.addItems(raters)
            if previous in raters:
                combo.setCurrentText(previous)
            combo.blockSignals(False)
        if len(raters) > 1 and self.rater_b.currentText() == self.rater_a.currentText():
            self.rater_b.blockSignals(True)
            self.rater_b.setCurrentIndex(1)
            self.rater_b.blockSignals(False)
        self._refresh_agreement()

    def _refresh_agreement(self) -> None:
        from analysis.agreement import (
            agreement_summary, low_agreement_codes, per_code_kappa,
        )

        self.disagreement_list.clear()
        self._disagreements = []
        self.adjudication_panel.clear()
        self.span_documents.setVisible(bool(self._span_unit()))
        if self._span_unit():
            self._refresh_span_agreement()
            return

        raters = self._service.human_rater_ids()
        self.model_note.setText(self._model_comparison_note())
        self.model_note.setVisible(bool(self.model_note.text()))
        if self._engine_mode():
            if not raters or not self._service.engine_rater_ids():
                self.kappa_summary.setText(
                    "<i>Coder vs engine needs a person's coding and an analysis "
                    "run in this project: run the analysis, then code some of its "
                    "responses (ideally a random sample).</i>")
                self.kappa_model.set_frame(pd.DataFrame())
                self.routed_label.setText("")
                return
        elif len(raters) < 2:
            self.kappa_summary.setText(
                "<i>Agreement needs two human coders in this project. A second "
                "coder arrives by importing their <code>.qnw</code> (Data "
                "Management, not yet ported) or by reconciling — an adjudicated "
                "set is itself a coder.</i>")
            self.kappa_model.set_frame(pd.DataFrame())
            self.routed_label.setText("")
            return

        name_a, name_b = self.rater_a.currentText(), self.rater_b.currentText()
        if not name_a or not name_b or name_a == name_b:
            self.kappa_summary.setText("<i>Pick two different coders.</i>")
            self.kappa_model.set_frame(pd.DataFrame())
            return

        comparison = (self._service.compare_with_engine(name_a, name_b)
                      if self._engine_mode()
                      else self._service.compare_raters(name_a, name_b))
        if comparison is None:
            self.kappa_summary.setText(
                "<b>These coders share no items.</b> κ is only defined on "
                "responses both of them reviewed.")
            self.kappa_model.set_frame(pd.DataFrame())
            self.routed_label.setText("")
            return
        labels_a, labels_b = comparison.labels_a, comparison.labels_b
        overlap = set(labels_a) & set(labels_b)

        kappa = per_code_kappa(labels_a, labels_b,
                              min_support=self.min_support.value())
        # Reordered for reading, not changed: κ is the headline number and was
        # scrolled off the right edge behind eight support columns. Putting κ,
        # its reliability flag, and percent agreement adjacent is what makes the
        # kappa paradox visible at a glance — high agreement beside a low κ on a
        # rare code. Every column `per_code_kappa` returns is still shown
        # (invariant #5); only the order differs.
        self.kappa_model.set_frame(kappa[_KAPPA_COLUMN_ORDER].copy())
        # `per_code_kappa` names its two raters `human` and `model` — right for
        # the human-vs-AI case it was written for, and misleading here, where
        # both are people. Labelling coder B's columns "model" is the exact
        # confusion invariant #6 exists to prevent, so the headers carry the
        # real coder ids.
        self.kappa_model.set_header_labels({
            "n_human": f"n · {name_a}",
            "n_model": f"n · {name_b}",
            "prevalence_human": f"prevalence · {name_a}",
            "prevalence_model": f"prevalence · {name_b}",
            "n_both": "n · both",
            "n_items": "shared items",
            "percent_agreement": "% agreement",
            "kappa": "κ",
        })
        summary = agreement_summary(kappa)

        caveat = ""
        if overlap != set(labels_a) or overlap != set(labels_b):
            caveat = (f"<br><span style='color:{warning_color()}'>{icon_html('warning')} The coders overlap on "
                      f"{len(overlap)} of {len(set(labels_a) | set(labels_b))} "
                      f"item(s); κ is computed on that intersection — correct, "
                      f"but note the N.</span>")
        for note in comparison.caveats:
            caveat += f"<br><span style='color:{warning_color()}'>{icon_html('warning')} {note}</span>"
        heading = (f"<b>{_escape(name_a)} vs the analysis engine ({_escape(name_b)})</b><br>"
                   if self._engine_mode() else "")
        self.kappa_summary.setText(
            f"{heading}<b>{len(overlap)}</b> shared item(s) · "
            f"<b>{summary['n_reliable']}</b> of {summary['n_codes']} code(s) had "
            f"enough support · mean κ <b>{_fmt(summary['mean_kappa'])}</b> · "
            f"support-weighted mean κ <b>{_fmt(summary['weighted_mean_kappa'])}</b>"
            f"{caveat}")

        routed = low_agreement_codes(kappa, threshold=_KAPPA_FLOOR)
        self.routed_label.setText(
            "<span style='color:" + warning_color() + f"'><b>{icon_html('warning')} Route to human review</b> "
            f"(κ &lt; {_KAPPA_FLOOR} or insufficient support): "
            f"{', '.join(routed)}</span>" if routed else
            success_span("Every code cleared the agreement floor."))

        self._load_disagreements(labels_a, labels_b, name_a, name_b)

    def _refresh_span_agreement(self) -> None:
        """Two coders' span coding on sentences or paragraphs (review F4)."""
        from analysis.agreement import agreement_summary, per_code_kappa

        name_a, name_b = self.rater_a.currentText(), self.rater_b.currentText()
        self.span_documents.blockSignals(True)
        self.span_documents.clear()
        self.kappa_model.set_frame(pd.DataFrame())
        self.routed_label.setText("")
        if not name_a or not name_b or name_a == name_b:
            self.span_documents.blockSignals(False)
            self.kappa_summary.setText(
                "<i>Pick two different coders. A colleague's span coding arrives "
                "by importing their .qdpx on the Data screen.</i>")
            return
        documents = self._service.documents_in_common(name_a, name_b)
        for source_id, title, finished in documents:
            item = QListWidgetItem(title)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if finished else Qt.CheckState.Unchecked)
            item.setData(Qt.ItemDataRole.UserRole, source_id)
            self.span_documents.addItem(item)
        self.span_documents.blockSignals(False)
        if not documents:
            self.kappa_summary.setText("<b>These coders have no document in common.</b>")
            return
        comparison = self._service.span_comparison(name_a, name_b, self._span_unit())
        if comparison is None:
            self.kappa_summary.setText(
                "<i>Tick the documents above that both coders have finished.</i>")
            return
        kappa = per_code_kappa(comparison.labels_a, comparison.labels_b,
                              min_support=self.min_support.value())
        if kappa.empty:
            self.kappa_summary.setText("<i>Neither coder applied a code in the finished "
                                       "documents.</i>")
            return
        self.kappa_model.set_frame(kappa[_KAPPA_COLUMN_ORDER].copy())
        summary = agreement_summary(kappa)
        notes = "".join(f"<br><i>{note}</i>" for note in comparison.caveats)
        self.kappa_summary.setText(
            f"<b>{len(comparison.labels_a)}</b> {comparison.unit}(s) · "
            f"mean κ <b>{_fmt(summary['mean_kappa'])}</b>{notes}")

    def _document_finished_changed(self, item: QListWidgetItem) -> None:
        source_id = item.data(Qt.ItemDataRole.UserRole)
        if not source_id:
            return
        self._service.set_document_finished(
            source_id, item.checkState() == Qt.CheckState.Checked,
            raters=[self.rater_a.currentText(), self.rater_b.currentText()])
        self._refresh_agreement()

    def _load_disagreements(self, labels_a, labels_b, name_a: str, name_b: str) -> None:
        from analysis.disagreement import disagreements

        self._disagreements = disagreements(labels_a, labels_b)
        self._rater_names = (name_a, name_b)
        self._adjudicated = self._service.rater_labels("human_adjudicated")
        for item in self._disagreements:
            excerpt = self._service.get_excerpt(item["excerpt_id"])
            quote = " ".join((excerpt.text if excerpt else "").split())[:90]
            resolved = "✓ " if item["excerpt_id"] in self._adjudicated else ""
            entry = QListWidgetItem(f"{resolved}{quote}…")
            entry.setData(Qt.ItemDataRole.UserRole, item)
            self.disagreement_list.addItem(entry)
        if not self._disagreements:
            self.disagreement_list.addItem(
                QListWidgetItem("The two coders agree on every shared item."))

    def _show_disagreement(self, row: int) -> None:
        if not (0 <= row < len(self._disagreements)):
            self.adjudication_panel.clear()
            return
        item = self._disagreements[row]
        excerpt = self._service.get_excerpt(item["excerpt_id"])
        self.adjudication_panel.show_item(
            item, excerpt.text if excerpt else "(passage unavailable)",
            self._rater_names,
            sorted(self._adjudicated.get(item["excerpt_id"], set())),
            already_resolved=item["excerpt_id"] in self._adjudicated)
        if self._engine_mode():
            self.adjudication_panel.set_read_only(
                "Shown to read, not to resolve: reconciling is between two people, "
                "and the engine's coding is not a person's.")

    def _save_adjudication(self, excerpt_id: str, codes: List[str]) -> None:
        try:
            self._service.record_adjudications({excerpt_id: codes})
        except Exception as exc:  # noqa: BLE001 - report, never crash the screen
            QMessageBox.critical(self, "Could not save the resolution", str(exc))
            return
        self.status.emit(
            f"Resolved to {', '.join(codes) if codes else '(no code)'} — saved as "
            "human_adjudicated.")


def _fmt(value: float) -> str:
    """Kappa for display: an em dash when it could not be computed."""
    try:
        if value != value:          # NaN
            return "—"
    except TypeError:
        return "—"
    return f"{value:.3f}"


class _EvidencePane(QTextBrowser):
    """Where drill-back lands: the passages behind a number.

    A read-only browser rather than a list of widgets, because the content is
    prose that should wrap and scroll, and because building sixty containers per
    click is how a drill-down becomes slow.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setOpenExternalLinks(False)
        self.show_message("Click a bar, a cell, or a row to see the evidence "
                          "behind it.")

    def show_message(self, message: str) -> None:
        self.setHtml(f"<p style='color:{muted_color()}'><i>{_escape(message)}</i></p>")

    def show_excerpts(self, title: str, excerpt_ids, service) -> None:
        lookup = service.excerpt_lookup()
        parts = [f"<p><b>{_escape(title)}</b></p>"]
        shown = list(excerpt_ids)[:_MAX_DRILL]
        for excerpt_id in shown:
            excerpt = lookup.get(excerpt_id)
            if excerpt is None:
                continue
            parts.append(_quote_block(excerpt.text))
        if len(excerpt_ids) > _MAX_DRILL:
            parts.append(
                f"<p style='color:{muted_color()}'><i>Showing the first {_MAX_DRILL} of "
                f"{len(excerpt_ids)}.</i></p>")
        self.setHtml("".join(parts))

    def show_sources(self, title: str, source_ids, service) -> None:
        lookup = service.source_lookup()
        parts = [f"<p><b>{_escape(title)}</b></p>"]
        for source_id in list(source_ids)[:_MAX_DRILL]:
            source = lookup.get(source_id)
            if source is None:
                continue
            label = source.label or source.source_id
            parts.append(f"<p style='color:{muted_color()}'>{_escape(str(label))}</p>")
            parts.append(_quote_block((source.raw_text or "")[:600]))
        if len(source_ids) > _MAX_DRILL:
            parts.append(
                f"<p style='color:{muted_color()}'><i>Showing the first {_MAX_DRILL} of "
                f"{len(source_ids)}.</i></p>")
        self.setHtml("".join(parts))


class _AdjudicationPanel(QWidget):
    """Resolve one disagreement to an agreed set of codes."""

    #: (excerpt_id, chosen code names)
    resolved = Signal(str, list)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._excerpt_id = ""

        self.quote = QTextBrowser()
        self.quote.setMaximumHeight(150)
        self.who = _hint("")
        self.options = QListWidget()
        self.options.setSelectionMode(
            QAbstractItemView.SelectionMode.MultiSelection)
        self.options.setToolTip(
            "Every code either coder applied. Select the ones that should stand.")
        self.quote.setToolTip("The passage the two coders disagreed about.")
        self.save_button = QPushButton("Save resolution")
        self.save_button.clicked.connect(self._emit_resolution)
        self.save_button.setEnabled(False)
        self.save_button.setToolTip(
            "Save this resolution as the separate human_adjudicated coder.\n"
            "Neither coder's original codings change — kappa depends on them.")
        self.resolved_label = _hint("")

        layout = QVBoxLayout(self)
        layout.addWidget(self.quote)
        layout.addWidget(self.who)
        layout.addWidget(QLabel("Resolve to"))
        layout.addWidget(self.options, 1)
        layout.addWidget(self.resolved_label)
        layout.addWidget(self.save_button)
        self.clear()

    def set_read_only(self, reason: str) -> None:
        """Show the disagreement, but offer no resolution (coder vs engine)."""
        self.options.setEnabled(False)
        self.save_button.setEnabled(False)
        self.resolved_label.setText(f"<i>{_escape(reason)}</i>")

    def clear(self) -> None:
        self._excerpt_id = ""
        self.options.setEnabled(True)
        self.quote.setHtml(
            f"<p style='color:{muted_color()}'><i>Pick a disagreement on the left.</i></p>")
        self.who.setText("")
        self.options.clear()
        self.resolved_label.setText("")
        self.save_button.setEnabled(False)

    def show_item(self, item: dict, text: str, rater_names, prior: List[str],
                  *, already_resolved: bool) -> None:
        self._excerpt_id = item["excerpt_id"]
        name_a, name_b = rater_names
        self.quote.setHtml(_quote_block(text))
        self.who.setText(
            f"<b>{_escape(name_a)}:</b> {_escape(', '.join(item['a_codes']) or '(none)')}"
            f"<br><b>{_escape(name_b)}:</b> "
            f"{_escape(', '.join(item['b_codes']) or '(none)')}")

        self.options.clear()
        choices = sorted(set(item["a_codes"]) | set(item["b_codes"]) | set(prior))
        # Default to what both coders already agreed on, or to a previous
        # resolution when this item has been adjudicated before.
        preselected = set(prior) if already_resolved else set(item["agreed"])
        for name in choices:
            entry = QListWidgetItem(name)
            self.options.addItem(entry)
            entry.setSelected(name in preselected)
        self.resolved_label.setText(
            f"<span style='color:{success_color()}'>Already resolved to "
            f"{_escape(', '.join(prior) or '(no code)')} — saving again "
            f"replaces it.</span>" if already_resolved else "")
        self.save_button.setEnabled(True)

    def _emit_resolution(self) -> None:
        if not self._excerpt_id:
            return
        self.resolved.emit(
            self._excerpt_id,
            [item.text() for item in self.options.selectedItems()])


def _quote_block(text: str) -> str:
    return (f"<blockquote style='margin:6px 0;padding:6px 10px;"
            f"border-left:3px solid {color('red')}'>{_escape(text)}</blockquote>")


def _escape(text: str) -> str:
    import html

    return html.escape(str(text)).replace("\n", "<br>")


def _rank_deviants(token: int, texts, identifiers, code_name: str, top_n: int,
                   embed):
    """Worker body. Returns (token, report), or (token, None) without the model.

    Module-level so it holds no widget or database connection; the passages were
    read from the store on the GUI thread before it started.
    """
    from analysis.deviant_cases import find_deviant_cases

    try:
        return token, find_deviant_cases(
            texts, identifiers, code_name=code_name, top_n=top_n, embed=embed)
    except ImportError:
        return token, None


class _CurveChart(QWidget):
    """Codes discovered so far against sources coded: a line, nothing more.

    No threshold line and no shading past a "plateau": where a curve has
    flattened enough is the researcher's judgement, not a drawing choice.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._points: List[tuple] = []

    def set_curve(self, curve: pd.DataFrame) -> None:
        self._points = ([] if curve.empty else
                        list(zip(curve["position"], curve["cumulative_codes"])))
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        left, right, top, bottom = 40, 12, 12, 28
        width = self.width() - left - right
        height = self.height() - top - bottom
        axis = QColor(muted_color())
        painter.setPen(QPen(axis, 1))
        painter.drawLine(left, top, left, top + height)
        painter.drawLine(left, top + height, left + width, top + height)
        if not self._points or width <= 0 or height <= 0:
            return
        last_x = max(p[0] for p in self._points)
        top_y = max(p[1] for p in self._points) or 1
        painter.drawText(4, top + 10, str(top_y))
        painter.drawText(left, self.height() - 8, "Sources coded: 1 to " + str(last_x))
        painter.drawText(4, top + height, "0")

        def place(x, y) -> QPointF:
            span = (last_x - 1) or 1
            return QPointF(left + (x - 1) / span * width,
                           top + height - y / top_y * height)

        painter.setPen(QPen(QColor(color("red")), 2))
        placed = [place(x, y) for x, y in self._points]
        for a, b in zip(placed, placed[1:]):
            painter.drawLine(a, b)
        for point in placed:
            painter.drawEllipse(point, 3, 3)
