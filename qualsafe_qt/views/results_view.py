"""
Results & Reports: turn a project into documents a person can read.

Everything on this screen already existed in `exports/` and was simply
unreachable -- the reports, the workbook, the shareable bundle. For a research
tool the **methods appendix** is the load-bearing one: engine, models,
thresholds, coders, per-code kappa for every comparable rater pair, adjudication
count, codebook version, and the caveats that travel with those numbers. It is
what makes a run answerable to a reviewer or an IRB, and until now nothing in
this app could produce it.

Three rules shape the layout.

**Redaction is a per-report decision, shown next to the button.** The engine's
posture is not uniform and pretending otherwise would be worse than saying so:
the bundle and the Word report can carry verbatim quotes if you ask, the Excel
workbook never can, and the codebook report only carries examples on request.
Each option here states what the file will contain, because "did this leave the
building with quotes in it" is the question a researcher has to answer later.

**Writing runs on a worker.** A Word report over a large project takes seconds,
and a frozen window during an export is indistinguishable from a crash. Each
job is handed the `.qnw` *path*, never the open `Project` -- a sqlite connection
belongs to the thread that opened it, so the worker opens its own.

**Nothing is written where the user cannot see it.** Every button asks for a
destination first; there is no "exported to somewhere" outcome.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDesktopServices, QUndoStack
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFrame, QGroupBox, QHBoxLayout, QLabel,
    QMessageBox, QPushButton, QScrollArea, QSpinBox, QStyle, QVBoxLayout, QWidget,
)

from qualsafe_qt.services.project_service import ProjectService
from qualsafe_qt.services.tasks import run_task
from qualsafe_qt.theme import muted_span, success_span, warning_span
from qualsafe_qt.widgets.more_options import MoreOptions

#: The three reports most people want, in this order. Everything else is under
#: "More reports" (Update 3, step 5: the report you need, not a menu of eight).
MAIN_REPORTS = ("report", "workbook", "methods")

#: What a file is, in words, for the Save button.
_FILE_WORDS = {".docx": "Word document", ".xlsx": "spreadsheet", ".zip": "zip file"}


def _size_text(size: int) -> str:
    """`24,311 bytes` is not how anyone reads a file size."""
    if size < 1024:
        return f"{size} bytes"
    if size < 1024 * 1024:
        return f"{size / 1024:.0f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


@dataclass(frozen=True)
class ReportKind:
    """One producible artefact.

    `builder` takes (store_path, out_path, options) and returns the written
    path. Keeping it a plain callable means every entry is testable without Qt
    and without this screen.
    """

    key: str
    title: str
    blurb: str
    #: What a reader would see in the file. Stated because redaction differs
    #: per report and a researcher has to be able to answer for it.
    contains: str
    suffix: str
    filter: str
    builder: Callable[..., Path]


def _codebook_report(store: Path, out: Path, *, include_examples: bool = False,
                     **_: object) -> Path:
    from exports.codebook_report import build_codebook_report

    return build_codebook_report(str(store), out,
                                 include_examples=include_examples)


def _methods_appendix(store: Path, out: Path, *, min_support: int = 5,
                      **_: object) -> Path:
    from exports.methods_appendix import build_methods_appendix

    return build_methods_appendix(str(store), out, min_support=min_support)


def _analysis_report(store: Path, out: Path, *, include_raw_text: bool = False,
                     include_memos: bool = True, **_: object) -> Path:
    from exports.docx_report import build_docx_report

    return build_docx_report(str(store), out,
                             include_raw_text=include_raw_text,
                             include_memos=include_memos)


def _workbook(store: Path, out: Path, **_: object) -> Path:
    from exports.excel_workbook import build_analysis_workbook

    return build_analysis_workbook(str(store), out)


def _joint_display(store: Path, out: Path, *, descriptor_key: str = "",
                   include_quotes: bool = True, normalize: bool = True,
                   **_: object) -> Path:
    """The mixed-methods table: themes by subgroup, with the analyst's inferences.

    Built here rather than passed in from the Analysis screen because a report is
    generated from the project as it stands, and re-reading the store is what
    makes that true. The integration statements are memos, so they come back with
    it.
    """
    from analysis.joint_display import build_joint_display
    from core.project import Project

    with Project.open(store) as project:
        coding = project.coding_table()
        descriptors = project.descriptor_table()
        key = descriptor_key or _first_descriptor_key(descriptors)
        display = build_joint_display(
            coding, descriptors, key, project=project, normalize=normalize,
            inferences=_saved_inferences(project, key))

    if out.suffix.lower() == ".xlsx":
        from exports.joint_display_export import build_joint_display_workbook

        return build_joint_display_workbook(display, out)

    from exports.joint_display_export import build_joint_display_docx

    return build_joint_display_docx(
        display, out, include_quotes=include_quotes,
        title=f"Joint Display — themes by {key}")


def _first_descriptor_key(descriptors) -> str:
    if descriptors is None or descriptors.empty:
        return ""
    return sorted(descriptors["key"].astype(str).unique())[0]


def _saved_inferences(project, descriptor_key: str) -> dict:
    """Integration statements written on the Analysis screen, keyed by theme.

    Same storage the Streamlit build uses, so a project carries its inferences
    between the two.
    """
    out = {}
    try:
        memos = project.list_memos(target_type="joint_display")
    except Exception:  # noqa: BLE001 - a display must export without its memos
        return out
    prefix = f"{descriptor_key}::"
    for memo in memos:
        target = getattr(memo, "target_id", "") or ""
        if target.startswith(prefix):
            out[target[len(prefix):]] = memo.text
    return out


def _audit_docx(store: Path, out: Path, *, include_memo_text: bool = False,
                **_: object) -> Path:
    from exports.audit_trail import build_audit_trail_docx

    return build_audit_trail_docx(str(store), out, include_memo_text=include_memo_text)


def _audit_xlsx(store: Path, out: Path, *, include_memo_text: bool = False,
                **_: object) -> Path:
    from exports.audit_trail import build_audit_trail_xlsx

    return build_audit_trail_xlsx(str(store), out, include_memo_text=include_memo_text)


def _bundle(store: Path, out: Path, *, include_raw_text: bool = False,
            include_memos: bool = False, **_: object) -> Path:
    from exports.bundle import build_bundle

    return build_bundle(str(store), out, include_raw_text=include_raw_text,
                        include_memos=include_memos)


#: Ordered by what a researcher reaches for, not by what was easiest to wire.
REPORT_KINDS: List[ReportKind] = [
    ReportKind(
        key="methods",
        title="Methods && reliability appendix",
        blurb=("What a reviewer or an ethics board asks for: how the answers "
               "were coded and by whom, how well the coders agree on each "
               "theme, and the limits that go with those numbers."),
        contains="No response text. Codes, coders, and agreement statistics only.",
        suffix=".docx",
        filter="Word document (*.docx)",
        builder=_methods_appendix,
    ),
    ReportKind(
        key="codebook",
        title="Codebook report",
        blurb=("The codebook as a document: hierarchy, definitions, and how "
               "often each code was applied."),
        contains=("Names, definitions, and counts. Example quotes only if you "
                  "tick the box."),
        suffix=".docx",
        filter="Word document (*.docx)",
        builder=_codebook_report,
    ),
    ReportKind(
        key="report",
        title="Analysis report",
        blurb=("A written report of your results: how often each theme came "
               "up, which themes occur together, agreement between coders, and "
               "your memos."),
        contains=("Codes, counts, and memos. Verbatim quotes only if you tick "
                  "the box."),
        suffix=".docx",
        filter="Word document (*.docx)",
        builder=_analysis_report,
    ),
    ReportKind(
        key="workbook",
        title="Analysis workbook",
        blurb=("Every table behind the analysis, as a spreadsheet you can "
               "sort, chart, or hand to a statistician."),
        contains="Never contains response text. Safe to email.",
        suffix=".xlsx",
        filter="Excel workbook (*.xlsx)",
        builder=_workbook,
    ),
    ReportKind(
        key="joint",
        title="Joint display",
        blurb=("The mixed-methods table: each theme against a group, with an "
               "example quote and the integration statement you wrote on the "
               "Analysis screen. Word for a findings chapter, Excel for a "
               "working file."),
        contains=("Word carries one quote per theme unless you untick the box; "
                  "the Excel version never carries response text."),
        suffix=".docx",
        filter="Word document (*.docx);;Excel workbook (*.xlsx)",
        builder=_joint_display,
    ),
    ReportKind(
        key="bundle",
        title="Shareable bundle",
        blurb=("A zip of the codebook, the analysis tables, and a written "
               "summary — for a collaborator who does not have this program."),
        contains=("Quotes are removed by default, and the written summary is "
                  "made from the cleaned tables."),
        suffix=".zip",
        filter="Zip archive (*.zip)",
        builder=_bundle,
    ),
    ReportKind(
        key="audit",
        title="Audit trail",
        blurb=("Every dated decision in the project, oldest first: codebook "
               "changes with before and after, coding sessions, reconciliation, "
               "imports, backups and erasures. What a confirmability audit "
               "asks for."),
        contains=("No response text and no response ids. Memo text only if you "
                  "tick the box (a memo can quote a response)."),
        suffix=".docx",
        filter="Word document (*.docx)",
        builder=_audit_docx,
    ),
    ReportKind(
        key="audit_xlsx",
        title="Audit trail (spreadsheet)",
        blurb="The same record as a spreadsheet, to filter by person or kind of decision.",
        contains=("No response text and no response ids. Memo text only if you "
                  "tick the box on the Word version above."),
        suffix=".xlsx",
        filter="Excel workbook (*.xlsx)",
        builder=_audit_xlsx,
    ),
]


class ResultsView(QWidget):
    """Produce reports from the open project."""

    status = Signal(str)

    def __init__(self, service: ProjectService, undo: QUndoStack,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._service = service
        self._undo = undo
        self._busy = False
        self._buttons: dict[str, QPushButton] = {}
        self._last_written: Optional[Path] = None

        outer = QVBoxLayout(self)

        # A warning gets an icon and words, never colour alone.
        self._headline_icon = QLabel()
        self._headline_icon.setPixmap(self.style().standardIcon(
            QStyle.StandardPixmap.SP_MessageBoxWarning).pixmap(16, 16))
        self._headline_icon.setFixedWidth(20)
        self.headline = QLabel()
        self.headline.setWordWrap(True)
        headline_row = QHBoxLayout()
        headline_row.addWidget(self._headline_icon)
        headline_row.addWidget(self.headline, 1)
        outer.addLayout(headline_row)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        inner = QWidget()
        self._body = QVBoxLayout(inner)
        scroll.setWidget(inner)
        outer.addWidget(scroll, 1)

        # -- per-report options, declared before the boxes that use them ------
        self.codebook_examples = QCheckBox(
            "Include example quotes for each code")
        self.codebook_examples.setToolTip(
            "Adds up to two verbatim quotes per code. The file then contains "
            "response text.")

        self.report_raw_text = QCheckBox("Include verbatim quotes")
        self.report_raw_text.setToolTip(
            "Off by default. With this on, the report contains response text "
            "exactly as written.")
        self.report_memos = QCheckBox("Include memos")
        self.report_memos.setChecked(True)

        self.bundle_raw_text = QCheckBox("Include verbatim quotes")
        self.bundle_raw_text.setToolTip(
            "Off by default. Leave it off and no response text appears "
            "anywhere in the zip.")
        self.bundle_memos = QCheckBox("Include memos")

        self.audit_memo_text = QCheckBox("Include memo text")
        self.audit_memo_text.setToolTip(
            "Off by default: a memo can quote a response. Applies to both the "
            "Word and the spreadsheet version.")

        self.min_support = QSpinBox()
        self.min_support.setRange(1, 100)
        self.min_support.setValue(5)
        self.min_support.setMaximumWidth(90)
        self.min_support.setToolTip(
            "Codes applied fewer times than this are reported as "
            "insufficient-N rather than given a kappa that cannot be read.")
        # A labelled row rather than a spin-box prefix: with the caption inside
        # the control the box stretched the full width of the group and read as
        # a text field.
        self._min_support_row = QWidget()
        _row = QHBoxLayout(self._min_support_row)
        _row.setContentsMargins(0, 0, 0, 0)
        _row.addWidget(QLabel("Fewest answers a theme needs before agreement (κ) is reported:"))
        _row.addWidget(self.min_support)
        _row.addStretch(1)

        self.joint_descriptor = QComboBox()
        self.joint_descriptor.setToolTip(
            "The subgroup axis — a respondent attribute such as class year or "
            "programme. This is the quantitative half of the display.")
        self.joint_quotes = QCheckBox("Include one quote per theme (Word only)")
        self.joint_quotes.setChecked(True)
        self.joint_quotes.setToolTip(
            "A joint display without its qualitative half is a crosstab. The "
            "quotes are verbatim response text, so this is a deliberate choice.")
        self.joint_normalize = QCheckBox("Show % within each subgroup")
        self.joint_normalize.setChecked(True)
        self.joint_normalize.setToolTip(
            "On, because subgroups are rarely equal: 10 of 20 first-generation "
            "students is a bigger deal than 15 of 200, and raw counts invert "
            "that comparison. The count is shown beside every percentage.")

        self._joint_descriptor_row = QWidget()
        _joint_row = QHBoxLayout(self._joint_descriptor_row)
        _joint_row.setContentsMargins(0, 0, 0, 0)
        _joint_row.addWidget(QLabel("Compare across:"))
        _joint_row.addWidget(self.joint_descriptor, 1)

        options = {
            "methods": [self._min_support_row],
            "joint": [self._joint_descriptor_row, self.joint_normalize,
                      self.joint_quotes],
            "codebook": [self.codebook_examples],
            "report": [self.report_raw_text, self.report_memos],
            "bundle": [self.bundle_raw_text, self.bundle_memos],
            "audit": [self.audit_memo_text],
        }
        by_key = {kind.key: kind for kind in REPORT_KINDS}
        for key in MAIN_REPORTS:
            self._body.addWidget(self._build_box(by_key[key], options.get(key, [])))
        # The rest of the reports, folded away but all still here.
        self.more_reports = MoreOptions("More reports")
        for kind in REPORT_KINDS:
            if kind.key not in MAIN_REPORTS:
                self.more_reports.body_layout.addWidget(
                    self._build_box(kind, options.get(kind.key, [])))
                self.more_reports._count += 1
        self.more_reports._refresh_title()
        self._body.addWidget(self.more_reports)
        self._body.addStretch(1)

        # What was just written, with a link to its folder (a link, not another button).
        self.message = QLabel()
        self.message.setWordWrap(True)
        self.message.setTextFormat(Qt.TextFormat.RichText)
        self.message.setTextInteractionFlags(
            Qt.TextInteractionFlag.LinksAccessibleByMouse
            | Qt.TextInteractionFlag.LinksAccessibleByKeyboard)
        self.message.linkActivated.connect(lambda _href: self._reveal_last())
        outer.addWidget(self.message)

        self._service.project_changed.connect(self.refresh)
        self.refresh()

    # -- construction --------------------------------------------------------
    def _build_box(self, kind: ReportKind,
                   option_widgets: List[QWidget]) -> QGroupBox:
        # `&&` because QGroupBox reads a single `&` as a keyboard mnemonic and
        # would render "Methods & reliability" as "Methods _reliability".
        box = QGroupBox(kind.title)
        layout = QVBoxLayout(box)

        blurb = QLabel(kind.blurb)
        blurb.setWordWrap(True)
        layout.addWidget(blurb)

        contains = QLabel(muted_span("Contains: " + kind.contains))
        contains.setWordWrap(True)
        contains.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(contains)

        for widget in option_widgets:
            layout.addWidget(widget)

        row = QHBoxLayout()
        row.addStretch(1)
        button = QPushButton(f"Save as {_FILE_WORDS.get(kind.suffix, kind.suffix)}…")
        if kind.key == MAIN_REPORTS[0]:
            button.setProperty("main", True)     # the one filled button on this screen
        button.clicked.connect(lambda _=False, k=kind: self._save(k))
        self._buttons[kind.key] = button
        row.addWidget(button)
        layout.addLayout(row)
        return box

    # -- state ---------------------------------------------------------------
    def refresh(self) -> None:
        """Enable or disable everything according to whether a project is open."""
        is_open = self._service.is_open
        self._headline_icon.setVisible(not is_open)
        if not is_open:
            self.headline.setText(warning_span(
                "No project is open. Open or create one to produce reports.",
                bold=False, icon=False))     # the icon beside it is the status mark
        else:
            name = Path(self._service.path).name
            self.headline.setText(
                f"Reports are generated from <b>{name}</b> as it stands now.")
        for button in self._buttons.values():
            button.setEnabled(is_open and not self._busy)
        self._refresh_descriptors(is_open)

    def _refresh_descriptors(self, is_open: bool) -> None:
        """A joint display needs a descriptor; without one there is nothing to
        put across the top, so the button says so rather than writing an empty
        table."""
        current = self.joint_descriptor.currentText()
        self.joint_descriptor.clear()
        keys = []
        if is_open:
            descriptors = self._service.descriptor_table()
            if descriptors is not None and not descriptors.empty:
                keys = sorted(descriptors["key"].astype(str).unique())
        self.joint_descriptor.addItems(keys)
        if current in keys:
            self.joint_descriptor.setCurrentText(current)
        self.joint_descriptor.setEnabled(bool(keys))

        button = self._buttons.get("joint")
        if button is not None:
            button.setEnabled(is_open and bool(keys) and not self._busy)
            button.setToolTip(
                "" if keys else
                "This project has no respondent details, so there is no group "
                "to put across the top of a joint display.")

    def _options(self, kind: ReportKind) -> dict:
        if kind.key == "methods":
            return {"min_support": self.min_support.value()}
        if kind.key == "codebook":
            return {"include_examples": self.codebook_examples.isChecked()}
        if kind.key == "report":
            return {"include_raw_text": self.report_raw_text.isChecked(),
                    "include_memos": self.report_memos.isChecked()}
        if kind.key == "bundle":
            return {"include_raw_text": self.bundle_raw_text.isChecked(),
                    "include_memos": self.bundle_memos.isChecked()}
        if kind.key in ("audit", "audit_xlsx"):
            return {"include_memo_text": self.audit_memo_text.isChecked()}
        if kind.key == "joint":
            return {"descriptor_key": str(self.joint_descriptor.currentText() or ""),
                    "include_quotes": self.joint_quotes.isChecked(),
                    "normalize": self.joint_normalize.isChecked()}
        return {}

    # -- writing -------------------------------------------------------------
    def _save(self, kind: ReportKind) -> None:
        store = self._service.path
        if store is None:
            return

        suggested = Path(store).with_name(
            f"{Path(store).stem}_{kind.key}{kind.suffix}")
        chosen, _ = QFileDialog.getSaveFileName(
            self, f"Save the {kind.title.replace('&&', '&').lower()}",
            str(suggested), kind.filter)
        if not chosen:
            return

        options = self._options(kind)
        if options.get("include_raw_text") and not self._confirm_raw_text(kind):
            return

        self._busy = True
        self.refresh()
        self.message.setText(muted_span(f"Writing {Path(chosen).name}…"))
        self.status.emit(f"Writing {Path(chosen).name}…")

        # The worker opens its own Project from the path. Handing it the GUI
        # thread's open connection would use a sqlite handle across threads.
        run_task(
            kind.builder, Path(store), Path(chosen),
            on_finished=self._on_written,
            on_failed=self._on_failed,
            on_done=self._on_done,
            reads_store=True,
            **options,
        )

    def _confirm_raw_text(self, kind: ReportKind) -> bool:
        """Verbatim quotes leave the project. Say so once, plainly."""
        answer = QMessageBox.warning(
            self, "This file will contain response text",
            f"The {kind.title.replace('&&', '&').lower()} will include "
            "participants' words exactly as they were written.\n\n"
            "Anyone you send it to can read them. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel)
        return answer == QMessageBox.StandardButton.Yes

    def _on_written(self, path: object) -> None:
        written = Path(str(path))
        self._last_written = written
        size = written.stat().st_size if written.exists() else 0
        self.message.setText(success_span(
            f"Saved {written.name} ({_size_text(size)}). ") + '<a href="folder">Show in folder</a>')
        self.status.emit(f"Saved {written}")

    def _on_failed(self, message: str, _traceback: str) -> None:
        self.message.setText(warning_span(f"Could not write the file: {message}",
                                          bold=False))
        self.status.emit("The report could not be written.")

    def _on_done(self) -> None:
        self._busy = False
        self.refresh()

    def _reveal_last(self) -> None:
        if self._last_written is None:
            return
        QDesktopServices.openUrl(
            _folder_url(self._last_written.parent))


def _folder_url(folder: Path):
    from PySide6.QtCore import QUrl

    return QUrl.fromLocalFile(str(folder))
