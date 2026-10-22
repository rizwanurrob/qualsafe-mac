"""
Search: find a phrase anywhere in the corpus, read it in context, code it.

The Qt counterpart of `app/search_page.py`. This is what an analyst does in the
first hour, before a codebook exists — so it has to be fast and it has to lead
somewhere.

The Qt-specific win: **a hit is a place, not just a line of text.** Double-click
one and the Documents screen opens that document with the matched characters
selected, ready to code by hand. `core.search.SearchHit` has carried exact
offsets since v4; Streamlit could print them but had nowhere to send them.

Auto-coding writes under `core.autocode.AUTOCODE_RATER` (`auto_textsearch`),
which is deliberately **not** a `human*` id — so a regex can never be picked as
a coder in the agreement screen. Same invariant (#6) that keeps the model out,
for the same reason: a pattern match is not a second analyst.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pandas as pd
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QPushButton, QSpinBox, QSplitter, QTableView,
    QTabWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from qualsafe_qt.models.dataframe_model import DataFrameModel
from qualsafe_qt.services.project_service import ProjectService
from qualsafe_qt.services.tasks import run_task
from qualsafe_qt.views.analysis_view import _hint, _table_view
from qualsafe_qt.widgets.charts import BarChart
from qualsafe_qt.widgets.more_options import MoreOptions

#: Matches `app/search_page._FREQ_SOURCE_CAP`: cap the corpus read so a huge
#: project cannot hang the screen.
_FREQ_SOURCE_CAP = 2000
#: Below this many total hits, every source group opens so the KWIC lines are
#: visible without a click. Above it, groups stay collapsed so the tree is
#: navigable rather than a wall.
_EXPAND_HIT_LIMIT = 60


class SearchView(QWidget):
    """Corpus search + KWIC + auto-code, and word frequency."""

    status = Signal(str)
    #: Take me to this passage in the reader: (source_id, char_start, char_end).
    open_in_reader = Signal(str, int, int)

    def __init__(self, service: ProjectService, undo_stack: QUndoStack,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._service = service
        self._undo = undo_stack
        self._theme_mode = "dark"
        self._hits: List[Any] = []
        self._case_ids: Dict[str, str] = {}

        self._build_ui()
        service.project_changed.connect(lambda _p: self.refresh())
        service.store_changed.connect(self._refresh_filters)
        self.refresh()

    # -- construction --------------------------------------------------------
    def _build_ui(self) -> None:
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_search_tab(), "Search")
        self.tabs.addTab(self._build_words_tab(), "Word frequency")

        self.empty_label = _hint("<i>No project open.</i>")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addWidget(self.empty_label)
        layout.addWidget(self.tabs, 1)

    def _build_search_tab(self) -> QWidget:
        self.query_edit = QLineEdit()
        self.query_edit.setPlaceholderText(
            "e.g. tuition    or    advis    or    cost of .*")
        self.query_edit.setClearButtonEnabled(True)
        self.query_edit.returnPressed.connect(self.run_search)
        self.query_edit.setToolTip(
            "What to look for. Press Enter to search.\n"
            "Switch to Regex for patterns like cost.*worry.")

        self.mode = QComboBox()
        self.mode.addItem("Words as typed", "text")
        self.mode.addItem("A pattern (for advanced searches)", "regex")
        self.mode.setToolTip(
            "Words as typed: look for exactly what you wrote.\n"
            "A pattern: a regular expression, for things like cost.*worry.")

        self.whole_word = QCheckBox("Whole word")
        self.whole_word.setChecked(True)
        self.whole_word.setToolTip(
            "On: 'cost' matches the word cost, not 'costume' — and uses the fast "
            "full-text index.\nOff: substring match (finds 'advis' inside "
            "'advisor'), which has to scan the text.")
        self.match_case = QCheckBox("Match case")
        self.match_case.setToolTip(
            "Off: Cost and cost both match. On: only the exact casing.")

        self.type_filter = QComboBox()
        self.case_filter = QComboBox()
        self.case_filter.setToolTip("Limit to sources belonging to one case.")
        self.code_filter = QComboBox()
        self.code_filter.setToolTip(
            "Limit to sources that already carry this code.")
        self.limit = QSpinBox()
        self.limit.setRange(10, 2000)
        self.limit.setValue(200)
        self.limit.setSingleStep(10)
        self.type_filter.setToolTip(
            "Limit to one kind of source — documents, or survey responses.")
        self.limit.setToolTip(
            "Stop after this many hits, so a common word stays fast.\n"
            "The result summary says when the cap was reached.")

        self.search_button = QPushButton("Search")
        self.search_button.clicked.connect(self.run_search)
        self.search_button.setDefault(True)
        self.search_button.setToolTip("Run the search. Shortcut: Enter.")

        self.search_button.setProperty("main", True)    # the one filled button on this screen
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Find"))
        row1.addWidget(self.query_edit, 1)
        row1.addWidget(self.search_button)

        # How to match, where to look, how many to show, and giving every hit a theme:
        # all still here, one click away.
        match_row = QWidget()
        match_layout = QHBoxLayout(match_row)
        match_layout.setContentsMargins(0, 0, 0, 0)
        match_layout.addWidget(self.whole_word)
        match_layout.addWidget(self.match_case)
        match_layout.addStretch(1)
        where_row = QWidget()
        where_layout = QHBoxLayout(where_row)
        where_layout.setContentsMargins(0, 0, 0, 0)
        for caption, combo in (("Kind", self.type_filter), ("Case", self.case_filter),
                               ("Theme", self.code_filter)):
            where_layout.addWidget(QLabel(caption))
            where_layout.addWidget(combo)
        where_layout.addStretch(1)
        self.search_more = MoreOptions("More options")
        self.search_more.add_row("Search for", self.mode)
        self.search_more.add_row("Match", match_row)
        self.search_more.add_row("Only look in", where_row)
        self.search_more.add_row("Show at most", self.limit)
        self.search_more.add_row("Give every hit a theme", self._build_autocode_box())

        self.result_summary = _hint("")

        # Hits grouped by source. A tree rather than a flat list because "which
        # documents is this in" is half the question.
        self.hits_tree = QTreeWidget()
        self.hits_tree.setHeaderLabels(["Hit", "Characters"])
        self.hits_tree.setColumnWidth(0, 720)
        self.hits_tree.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        self.hits_tree.itemDoubleClicked.connect(self._open_hit)
        self.hits_tree.setToolTip(
            "Double-click a hit to open it in the reader with the match "
            "selected, ready to code by hand.")

        self.before_table = _table_view()
        self.before_model = DataFrameModel()
        self.before_table.setModel(self.before_model)
        self.before_table.setToolTip(
            "Words that most often come immediately before your term,\n"
            "across every hit.")
        self.after_table = _table_view()
        self.after_model = DataFrameModel()
        self.after_table.setModel(self.after_model)
        self.after_table.setToolTip(
            "Words that most often come immediately after your term.")

        context_box = QGroupBox("Words around the term")
        context_layout = QHBoxLayout(context_box)
        before_pane = QVBoxLayout()
        before_pane.addWidget(QLabel("Before"))
        before_pane.addWidget(self.before_table)
        after_pane = QVBoxLayout()
        after_pane.addWidget(QLabel("After"))
        after_pane.addWidget(self.after_table)
        context_layout.addLayout(before_pane)
        context_layout.addLayout(after_pane)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.hits_tree)
        splitter.addWidget(context_box)
        splitter.setSizes([900, 380])

        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.addLayout(row1)
        layout.addWidget(self.result_summary)
        layout.addWidget(splitter, 1)
        layout.addWidget(self.search_more)
        return tab

    def _build_autocode_box(self) -> QWidget:
        self.autocode_name = QComboBox()
        self.autocode_name.setEditable(True)
        self.autocode_name.setToolTip(
            "An existing code name, or type a new one to create.")
        self.autocode_button = QPushButton("Code all hits")
        self.autocode_button.clicked.connect(self._autocode)
        self.autocode_button.setEnabled(False)
        self.autocode_button.setToolTip(
            "Apply the code to every hit above at once.\n"
            "Saved separately from your own coding, and reversible.")

        self.undo_pick = QComboBox()
        self.undo_button = QPushButton("Remove auto-coding")
        self.undo_button.clicked.connect(self._remove_autocoded)
        self.undo_button.setToolTip(
            "Removes codings made by text search only — your own coding and the "
            "model's are untouched.")
        self.undo_pick.setToolTip(
            "Which auto-coded code to remove, or all of them.")

        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(_hint(
            "<i>Gives a theme to every hit above. Each becomes a passage covering exactly "
            "the matched words, saved under a separate text-search coder, so it never "
            "counts toward agreement between coders.</i>"))
        controls = QHBoxLayout()
        controls.addWidget(QLabel("Theme to apply"))
        controls.addWidget(self.autocode_name, 1)
        controls.addWidget(self.autocode_button)
        controls.addSpacing(24)
        controls.addWidget(QLabel("Undo"))
        controls.addWidget(self.undo_pick)
        controls.addWidget(self.undo_button)
        layout.addLayout(controls)
        return box

    def _build_words_tab(self) -> QWidget:
        self.wf_type = QComboBox()
        self.wf_type.currentIndexChanged.connect(self._recount_words)
        self.wf_top_n = QSpinBox()
        self.wf_top_n.setRange(10, 100)
        self.wf_top_n.setValue(30)
        self.wf_top_n.valueChanged.connect(self._recount_words)
        self.wf_min_len = QSpinBox()
        self.wf_min_len.setRange(1, 8)
        self.wf_min_len.setValue(3)
        self.wf_min_len.valueChanged.connect(self._recount_words)
        self.wf_stops = QCheckBox("Remove common English stop words")
        self.wf_stops.setChecked(True)
        self.wf_stops.setToolTip("Filters 'the', 'and', 'is'… Turn off for raw counts.")
        self.wf_stops.toggled.connect(self._recount_words)
        self.wf_extra = QLineEdit()
        self.wf_extra.setPlaceholderText("also ignore (comma-separated): student, course")
        self.wf_extra.editingFinished.connect(self._recount_words)
        self.wf_type.setToolTip("Count words in one kind of source only.")
        self.wf_top_n.setToolTip("How many of the most frequent terms to show.")
        self.wf_min_len.setToolTip(
            "Ignore words shorter than this — mostly filler at 1-2 characters.")
        self.wf_extra.setToolTip(
            "Words to leave out, comma-separated. Useful for terms that appear\n"
            "in every response because they were in the question.")

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Type"))
        controls.addWidget(self.wf_type)
        controls.addWidget(QLabel("Terms"))
        controls.addWidget(self.wf_top_n)
        controls.addWidget(QLabel("Min length"))
        controls.addWidget(self.wf_min_len)
        controls.addWidget(self.wf_stops)
        controls.addWidget(self.wf_extra, 1)

        self.wf_chart = BarChart()
        self.wf_table = _table_view()
        self.wf_model = DataFrameModel()
        self.wf_table.setModel(self.wf_model)
        self.wf_chart.setToolTip("The most frequent terms in your documents.")
        self.wf_table.setToolTip(
            "count: total occurrences.\n"
            "documents: how many sources contain the term at least once —\n"
            "this separates a word one person repeated from one everyone used.")
        self.wf_caption = _hint("")

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.wf_chart)
        splitter.addWidget(self.wf_table)
        splitter.setSizes([820, 480])

        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.addWidget(_hint(
            "<i>The words your documents actually use — a first look before any "
            "codebook exists. <code>documents</code> is how many sources contain "
            "the term at least once: the column that separates a word one person "
            "repeated from a word everyone used.</i>"))
        layout.addLayout(controls)
        layout.addWidget(self.wf_caption)
        layout.addWidget(splitter, 1)
        return tab

    # -- data ----------------------------------------------------------------
    def set_theme_mode(self, mode: str, palette: str = "") -> None:
        self._theme_mode = mode if mode in ("dark", "light") else "dark"
        self.wf_chart.set_theme_mode(self._theme_mode)

    def refresh(self) -> None:
        if not self._service.is_open:
            self.empty_label.setText("<i>No project open.</i>")
            self.empty_label.setVisible(True)
            self.tabs.setVisible(False)
            return
        if self._service.count_sources() == 0:
            self.empty_label.setText(
                "<i>This project has no text in it yet. Import documents on the "
                "Documents screen.</i>")
            self.empty_label.setVisible(True)
            self.tabs.setVisible(False)
            return
        self.empty_label.setVisible(False)
        self.tabs.setVisible(True)
        self._refresh_filters()
        self._recount_words()

    def _refresh_filters(self) -> None:
        if not self._service.is_open:
            return
        types = self._service.source_types()
        for combo in (self.type_filter, self.wf_type):
            previous = combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("All types", None)
            for source_type in types:
                combo.addItem(source_type, source_type)
            index = combo.findData(previous)
            if index >= 0:
                combo.setCurrentIndex(index)
            combo.blockSignals(False)

        cases = self._service.list_cases()
        self._case_ids = {c.name: c.case_id for c in cases}
        self.case_filter.blockSignals(True)
        self.case_filter.clear()
        self.case_filter.addItem("All cases", None)
        for case in cases:
            self.case_filter.addItem(case.name, case.case_id)
        self.case_filter.blockSignals(False)
        self.case_filter.setEnabled(bool(cases))

        codes = sorted(self._service.code_names())
        self.code_filter.blockSignals(True)
        self.code_filter.clear()
        self.code_filter.addItem("Any code", None)
        for name in codes:
            self.code_filter.addItem(name, name)
        self.code_filter.blockSignals(False)

        current = self.autocode_name.currentText()
        self.autocode_name.blockSignals(True)
        self.autocode_name.clear()
        self.autocode_name.addItems(codes)
        self.autocode_name.setCurrentText(current)
        self.autocode_name.blockSignals(False)

        self.undo_pick.clear()
        self.undo_pick.addItem("All auto-coded", None)
        for name in codes:
            self.undo_pick.addItem(name, name)

        if not self._service.fts_available():
            self.result_summary.setText(
                "<i>This SQLite has no FTS5 index, so searches scan the text "
                "directly. Results are identical, just slower.</i>")

    # -- search --------------------------------------------------------------
    def run_search(self) -> None:
        query = self.query_edit.text().strip()
        if not query or not self._service.is_open:
            return
        try:
            hits = self._service.search(
                query,
                mode=self.mode.currentData(),
                case_sensitive=self.match_case.isChecked(),
                whole_word=self.whole_word.isChecked(),
                source_type=self.type_filter.currentData(),
                case_id=self.case_filter.currentData(),
                code_name=self.code_filter.currentData(),
                limit=self.limit.value(),
            )
        except ValueError as exc:
            # A malformed regex is user input, not a crash.
            QMessageBox.warning(self, "Could not run that search", str(exc))
            return
        self._show_hits(hits, query)

    def _show_hits(self, hits: List[Any], query: str) -> None:
        self._hits = hits
        self.hits_tree.clear()
        self.autocode_button.setEnabled(bool(hits))

        if not hits:
            self.result_summary.setText("<b>No matches.</b>")
            self.before_model.set_frame(pd.DataFrame())
            self.after_model.set_frame(pd.DataFrame())
            return

        by_source: Dict[Any, List[Any]] = {}
        for hit in hits:
            by_source.setdefault(
                (hit.source_id, hit.source_label, hit.source_type), []).append(hit)

        capped = " — capped at the maximum" if len(hits) >= self.limit.value() else ""
        self.result_summary.setText(
            f"<b>{len(hits)}</b> hit(s) in <b>{len(by_source)}</b> source(s)"
            f"{capped}. Double-click a hit to open it in the reader.")

        for (source_id, label, source_type), source_hits in by_source.items():
            title = label or (source_hits[0].metadata or {}).get("title") or source_id
            parent = QTreeWidgetItem(
                [f"{title}  ·  {source_type}", f"{len(source_hits)} hit(s)"])
            parent.setData(0, Qt.ItemDataRole.UserRole, None)
            self.hits_tree.addTopLevelItem(parent)
            for hit in source_hits:
                # KWIC on one line. The match is bracketed rather than coloured
                # because a QTreeWidget cell is plain text; the offsets column
                # carries the precision.
                line = (f"…{' '.join(hit.left.split())} "
                        f"[{hit.match_text}] "
                        f"{' '.join(hit.right.split())}…")
                child = QTreeWidgetItem(
                    [line, f"{hit.char_start}–{hit.char_end}"])
                child.setData(0, Qt.ItemDataRole.UserRole, hit)
                parent.addChild(child)
            # Expand on total hits, not on how many documents they fall across.
            # The Streamlit page keys this on source count because its expanders
            # stack vertically and three open ones fill the page; a tree does
            # not have that problem, and a screenful of collapsed headers hides
            # the KWIC lines that are the entire point of the screen.
            parent.setExpanded(len(hits) <= _EXPAND_HIT_LIMIT)

        from analysis.lexical import context_profile

        profile = context_profile([(h.left, h.right) for h in hits])
        self.before_model.set_frame(profile["before"])
        self.after_model.set_frame(profile["after"])
        self.status.emit(f"{len(hits)} hit(s) for '{query}'.")

    def _open_hit(self, item: QTreeWidgetItem, _column: int) -> None:
        """Send a hit to the reader — the thing Streamlit had no way to do.

        `SearchHit` has always carried exact offsets; there was simply nowhere
        to send them. Here they become a selection in the document, ready to
        code by hand.
        """
        hit = item.data(0, Qt.ItemDataRole.UserRole)
        if hit is None:
            return
        self.open_in_reader.emit(hit.source_id, hit.char_start, hit.char_end)

    # -- auto-coding ---------------------------------------------------------
    def _autocode(self) -> None:
        code_name = self.autocode_name.currentText().strip()
        if not code_name:
            QMessageBox.information(self, "Name the code",
                                    "Type or pick a code to apply.")
            return
        if not self._hits:
            return
        confirmed = QMessageBox.question(
            self, "Code every hit?",
            f"Apply '{code_name}' to all {len(self._hits)} hit(s)?\n\n"
            "Each becomes a passage covering exactly the matched words, saved "
            "under the auto_textsearch coder. It stays separate from your own "
            "coding and never counts toward agreement between coders.\n\n"
            "Reversible with 'Remove auto-coding'.",
            QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes,
            QMessageBox.StandardButton.Yes)
        if confirmed != QMessageBox.StandardButton.Yes:
            return
        try:
            result = self._service.autocode_hits(
                self._hits, code_name, query=self.query_edit.text().strip())
        except Exception as exc:  # noqa: BLE001 - report, never crash
            QMessageBox.critical(self, "Auto-coding failed", str(exc))
            return
        self.status.emit(
            f"Applied '{code_name}' to {result['applications']} hit(s) "
            f"({result['excerpts_created']} new passage(s), "
            f"{result['skipped']} already coded).")

    def _remove_autocoded(self) -> None:
        code_name = self.undo_pick.currentData()
        removed = self._service.remove_autocoded(code_name)
        self.status.emit(f"Removed {removed} auto-coded application(s).")

    # -- word frequency ------------------------------------------------------
    def _recount_words(self) -> None:
        """Count words in the corpus, off the GUI thread.

        The store read stays here — a `sqlite3` connection belongs to the thread
        that opened it — and only the counting, which is the CPU-bound half,
        goes to a worker.
        """
        if not self._service.is_open:
            return
        from analysis.lexical import DEFAULT_STOPWORDS

        texts = self._service.corpus_texts(self.wf_type.currentData(),
                                           cap=_FREQ_SOURCE_CAP)
        if not texts:
            self.wf_model.set_frame(pd.DataFrame())
            self.wf_chart.set_data([])
            self.wf_caption.setText("<i>No text for this filter.</i>")
            return

        stops = set(DEFAULT_STOPWORDS) if self.wf_stops.isChecked() else set()
        stops |= {w.strip().lower()
                  for w in (self.wf_extra.text() or "").split(",") if w.strip()}
        capped = ("  Showing the first 2,000 sources."
                  if len(texts) >= _FREQ_SOURCE_CAP else "")
        self.wf_caption.setText(f"<i>Counting across {len(texts):,} source(s).{capped}</i>")

        run_task(
            _count_words, texts, stops, int(self.wf_min_len.value()),
            int(self.wf_top_n.value()),
            on_finished=lambda freq: self._show_word_frequency(freq, len(texts), capped),
            on_failed=lambda msg, _tb: self.status.emit(f"Word count failed: {msg}"),
        )

    def _show_word_frequency(self, freq: pd.DataFrame, n_texts: int,
                             capped: str) -> None:
        self.wf_model.set_frame(freq)
        self.wf_chart.set_data(
            [(row["term"], row["count"]) for _i, row in freq.iterrows()])
        if freq.empty:
            self.wf_caption.setText("<i>No words left after filtering.</i>")
        else:
            self.wf_caption.setText(
                f"<i>Across {n_texts:,} source(s).{capped}</i>")


def _count_words(texts, stopwords, min_length: int, top_n: int) -> pd.DataFrame:
    """Worker body. Module-level so it obviously holds no widget or connection."""
    from analysis.lexical import word_frequency

    return word_frequency(texts, stopwords=stopwords, min_length=min_length,
                          top_n=top_n)
