"""
Data Management: the project file, its backups, and the right to be forgotten.

This screen exists because `core/erasure.py` has always worked and has never
been reachable — awkward for a tool whose whole pitch is careful handling of
personal data. If a participant withdraws, the researcher must be able to act
on that without a Python prompt.

Four things, in the order a researcher needs them.

**What this project is** — where the file lives, how big it is, what is in it,
and who is recorded as the analyst. The analyst name was buried in a menu; it
belongs here, because it is stamped on every coding and is what makes agreement
analysis attributable.

**Backups** — `core/backups.py` already snapshots before every destructive
operation, keeps the newest five, and can restore. None of that was visible, so
a safety net nobody could see was barely a safety net.

**A portable archive** — the whole project folder as one zip, for moving between
machines or handing to a colleague.

**Erasing a participant** — the irreversible one, and the reason for the care
in `_erase()` below.

## The trap in erasure

`erase_respondent()` takes a **pre-erase backup**, and that backup contains the
un-erased data. So an erasure that leaves backups in place has not actually
erased anything — it has moved it next door. `core/erasure.py` says as much in
a comment and defers to "the UI" to handle it; this screen is that UI, so the
backup purge is offered in the same dialog rather than left as a second step
someone forgets.

The other honest limit, stated on screen: this unlinks files, it does not shred
them. On a journalling filesystem or an SSD with wear levelling, recovery by a
determined party is not excluded. Saying so is better than implying a guarantee
the software cannot make.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import (
    QCheckBox, QFileDialog, QFrame, QGroupBox, QHBoxLayout, QInputDialog,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton,
    QScrollArea, QVBoxLayout, QWidget,
)

from qualsafe_qt.services.project_service import ProjectService
from qualsafe_qt.services.tasks import run_task
from qualsafe_qt.theme import muted_span, success_span, warning_span

#: Typed to confirm an erasure. A click is too cheap for something irreversible.
ERASE_CONFIRMATION = "ERASE"


def _human_bytes(count: int) -> str:
    value = float(count)
    for unit in ("bytes", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:,.0f} {unit}" if unit == "bytes" else f"{value:,.1f} {unit}"
        value /= 1024
    return f"{value:,.1f} GB"


class DataView(QWidget):
    """Project file, backups, archive, and participant erasure."""

    status = Signal(str)
    #: The analyst name was changed here; the window saves it with the preferences.
    analyst_name_changed = Signal(str)
    #: A restore or an import replaces the store under the app; the shell
    #: reopens rather than this view reaching into the service's connection.
    project_replaced = Signal(Path)

    def __init__(self, service: ProjectService, undo: QUndoStack,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._service = service
        self._undo = undo
        self._backups: List[Path] = []

        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        inner = QWidget()
        body = QVBoxLayout(inner)
        scroll.setWidget(inner)
        outer.addWidget(scroll, 1)

        body.addWidget(self._build_project_box())
        body.addWidget(self._build_backups_box())
        body.addWidget(self._build_archive_box())
        body.addWidget(self._build_erasure_box())
        body.addStretch(1)

        self.message = QLabel()
        self.message.setWordWrap(True)
        self.message.setTextFormat(Qt.TextFormat.RichText)
        outer.addWidget(self.message)

        self._service.project_changed.connect(self.refresh)
        self.refresh()

    # -- construction --------------------------------------------------------
    def _build_project_box(self) -> QGroupBox:
        box = QGroupBox("This project")
        layout = QVBoxLayout(box)

        self.project_path = QLabel()
        self.project_path.setWordWrap(True)
        self.project_path.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.project_path)

        self.project_stats = QLabel()
        self.project_stats.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(self.project_stats)

        row = QHBoxLayout()
        row.addWidget(QLabel("Your analyst name:"))
        self.analyst_name = QLineEdit()
        self.analyst_name.setPlaceholderText("e.g. R. Ahmed")
        self.analyst_name.setToolTip(
            "Recorded on every coding you make, so agreement analysis can tell "
            "your codings from a colleague's.")
        self.analyst_name.editingFinished.connect(self._save_analyst_name)
        row.addWidget(self.analyst_name, 1)
        layout.addLayout(row)

        hint = QLabel(muted_span(
            "Stamped on your codings. Set it before coding, not after — it is "
            "what makes agreement analysis attributable."))
        hint.setWordWrap(True)
        hint.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(hint)
        return box

    def _build_backups_box(self) -> QGroupBox:
        box = QGroupBox("Backups")
        layout = QVBoxLayout(box)
        layout.addWidget(QLabel(
            "A snapshot is taken automatically before anything destructive — "
            "restoring a codebook version, merging, erasing. The newest five "
            "are kept."))

        self.backup_list = QListWidget()
        self.backup_list.setMaximumHeight(140)
        layout.addWidget(self.backup_list)

        row = QHBoxLayout()
        self.backup_now = QPushButton("Back up now")
        self.backup_now.clicked.connect(self._backup_now)
        row.addWidget(self.backup_now)
        self.restore_button = QPushButton("Restore the selected backup…")
        self.restore_button.clicked.connect(self._restore)
        row.addWidget(self.restore_button)
        row.addStretch(1)
        layout.addLayout(row)
        return box

    def _build_archive_box(self) -> QGroupBox:
        box = QGroupBox("Portable archive")
        layout = QVBoxLayout(box)
        layout.addWidget(QLabel(
            "The whole project folder as a single zip — the project file, its "
            "run output, and its reports. For moving to another machine or "
            "handing to a colleague who has this program."))
        contains = QLabel(warning_span(
            "Contains your source text. Treat it like the transcripts that "
            "went into it.", bold=False))
        contains.setWordWrap(True)
        contains.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(contains)

        row = QHBoxLayout()
        self.export_archive = QPushButton("Export archive…")
        self.export_archive.clicked.connect(self._export_archive)
        row.addWidget(self.export_archive)
        row.addStretch(1)
        layout.addLayout(row)
        return box

    def _build_erasure_box(self) -> QGroupBox:
        box = QGroupBox("Erase a participant")
        layout = QVBoxLayout(box)
        layout.addWidget(QLabel(
            "If someone withdraws their consent, this removes their response "
            "from the project file, from the run output, from any quotes in a "
            "generated report, and from the caches."))

        caveat = QLabel(warning_span(
            "Irreversible, and honest about its limits: this deletes files, it "
            "does not shred them. It also cannot reach copies you have already "
            "sent elsewhere.", bold=False))
        caveat.setWordWrap(True)
        caveat.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(caveat)

        row = QHBoxLayout()
        row.addWidget(QLabel("Response id:"))
        self.erase_id = QLineEdit()
        self.erase_id.setPlaceholderText("the id of the response to remove")
        row.addWidget(self.erase_id, 1)
        layout.addLayout(row)

        self.purge_backups = QCheckBox(
            "Also delete this project's backups")
        self.purge_backups.setChecked(True)
        self.purge_backups.setToolTip(
            "Erasure takes a backup first, and that backup still contains the "
            "response. Leaving it in place means the data has been moved, not "
            "erased.")
        layout.addWidget(self.purge_backups)

        purge_note = QLabel(muted_span(
            "Leave this ticked for a genuine withdrawal-of-consent request. "
            "Untick it only if you are correcting a mistake and may need to "
            "undo."))
        purge_note.setWordWrap(True)
        purge_note.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(purge_note)

        row2 = QHBoxLayout()
        row2.addStretch(1)
        self.erase_button = QPushButton("Erase this participant…")
        self.erase_button.clicked.connect(self._erase)
        row2.addWidget(self.erase_button)
        layout.addLayout(row2)
        return box

    # -- state ---------------------------------------------------------------
    def refresh(self) -> None:
        is_open = self._service.is_open
        for widget in (self.backup_now, self.restore_button,
                       self.export_archive, self.erase_button,
                       self.analyst_name, self.erase_id):
            widget.setEnabled(is_open)

        if not is_open:
            self.project_path.setText(warning_span(
                "No project is open.", bold=False))
            self.project_stats.setText("")
            self.backup_list.clear()
            return

        path = Path(self._service.path)
        size = path.stat().st_size if path.exists() else 0
        self.project_path.setText(f"<b>{path.name}</b><br>{path.parent}")
        self.project_stats.setText(self._describe(path, size))
        self.analyst_name.setText(self._service.analyst_name)
        self._reload_backups()

    def _describe(self, path: Path, size: int) -> str:
        try:
            project = self._service.project
            sources = project.count_sources()
            codes = len(project.get_codebook())
        except Exception:  # noqa: BLE001 - a stats line must never break the screen
            return muted_span(_human_bytes(size))
        return muted_span(
            f"{_human_bytes(size)} · {sources:,} source(s) · {codes:,} code(s)")

    def _reload_backups(self) -> None:
        from core.backups import list_backups

        self.backup_list.clear()
        self._backups = list_backups(self._service.path)
        if not self._backups:
            item = QListWidgetItem("No backups yet.")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.backup_list.addItem(item)
            self.restore_button.setEnabled(False)
            return
        for backup in self._backups:
            size = backup.stat().st_size if backup.exists() else 0
            self.backup_list.addItem(f"{backup.name}   ({_human_bytes(size)})")
        self.backup_list.setCurrentRow(0)
        self.restore_button.setEnabled(True)

    # -- actions -------------------------------------------------------------
    def _save_analyst_name(self) -> None:
        name = self.analyst_name.text().strip()
        if name and name != self._service.analyst_name:
            self._service.set_analyst_name(name)
            self.analyst_name_changed.emit(name)
            self.status.emit(f"Your codings will be recorded as {name}.")

    def _backup_now(self) -> None:
        from core.backups import backup_store

        made = backup_store(self._service.path, reason="manual")
        if made is None:
            self.message.setText(warning_span(
                "Could not write a backup.", bold=False))
            return
        self._reload_backups()
        self.message.setText(success_span(f"Backed up to {made.name}"))
        self.status.emit("Backup written.")

    def _restore(self) -> None:
        row = self.backup_list.currentRow()
        if row < 0 or row >= len(self._backups):
            return
        backup = self._backups[row]

        answer = QMessageBox.warning(
            self, "Restore this backup?",
            f"This replaces the current project with <b>{backup.name}</b>."
            "<br><br>Anything coded since that snapshot will be gone from the "
            "project.<br><br>The current state is backed up first, so this is "
            "itself undoable.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel)
        if answer != QMessageBox.StandardButton.Yes:
            return

        from core.backups import restore_backup

        path = Path(self._service.path)
        # Close first: the file is about to be replaced underneath the
        # connection that has it open.
        self._service.close()
        try:
            restore_backup(path, backup)
        except Exception as exc:  # noqa: BLE001 - report, do not crash
            self.message.setText(warning_span(f"Restore failed: {exc}",
                                              bold=False))
            self._service.open(path)
            return
        self._service.open(path)
        self._undo.clear()  # the stack refers to a project state that is gone
        self.message.setText(success_span(f"Restored {backup.name}"))
        self.status.emit("Backup restored.")
        self.refresh()

    def _export_archive(self) -> None:
        store = Path(self._service.path)
        suggested = store.with_suffix(".zip")
        chosen, _ = QFileDialog.getSaveFileName(
            self, "Export the project archive", str(suggested),
            "Zip archive (*.zip)")
        if not chosen:
            return

        self.message.setText(muted_span("Writing the archive…"))
        run_task(
            _write_archive, store, Path(chosen),
            on_finished=lambda path: self._on_archive_written(Path(str(path))),
            on_failed=lambda msg, _tb: self.message.setText(
                warning_span(f"Could not write the archive: {msg}", bold=False)),
            reads_store=True,
        )

    def _on_archive_written(self, path: Path) -> None:
        size = path.stat().st_size if path.exists() else 0
        self.message.setText(success_span(
            f"Wrote {path.name} ({_human_bytes(size)})"))
        self.status.emit(f"Archive written to {path}")

    def _erase(self) -> None:
        response_id = self.erase_id.text().strip()
        if not response_id:
            self.message.setText(warning_span(
                "Enter the response id to erase.", bold=False))
            return

        purge = self.purge_backups.isChecked()
        detail = (
            f"This permanently removes response <b>{response_id}</b> from this "
            "project, its run output, its reports, and its caches."
            "<br><br>"
        )
        detail += (
            "Backups will also be deleted, because the pre-erasure backup "
            "would otherwise still contain this response."
            if purge else
            warning_span(
                "Backups will be KEPT — and the pre-erasure backup will still "
                "contain this response. That is not a complete erasure.",
                bold=False)
        )
        detail += ("<br><br>This cannot be undone. Type "
                   f"<b>{ERASE_CONFIRMATION}</b> to confirm.")

        typed, ok = QInputDialog.getText(
            self, "Erase a participant", detail, QLineEdit.EchoMode.Normal, "")
        if not ok or typed.strip() != ERASE_CONFIRMATION:
            self.status.emit("Erasure cancelled.")
            return

        store = Path(self._service.path)
        project_dir = store.parent
        self._service.close()
        try:
            report = _erase_respondent(project_dir, response_id, store, purge)
        except Exception as exc:  # noqa: BLE001 - report, do not crash
            self._service.open(store)
            self.message.setText(warning_span(f"Erasure failed: {exc}",
                                              bold=False))
            return

        self._service.open(store)
        self._undo.clear()
        counts = report.get("store_counts") or {}
        self.message.setText(success_span(
            "Erased. "
            + ", ".join(f"{v} {k}" for k, v in counts.items())
            + (". Backups deleted." if purge else ". Backups kept.")))
        self.status.emit("Participant erased.")
        self.refresh()


# -- worker-side helpers (module level so they pickle cleanly and stay testable)


def _write_archive(store: Path, out_path: Path) -> Path:
    from core.project_archive import export_project_archive

    out_path.write_bytes(export_project_archive(str(store)))
    return out_path


def _erase_respondent(project_dir: Path, response_id: str, store: Path,
                      purge_backups: bool) -> dict:
    """Erase, and optionally remove the backups that still hold the data.

    This used to do the work itself, because the engine could not be edited from
    this fork: `core.erasure` deleted the rows but never VACUUMed, so the erased
    response stayed legible in the `.qnw` bytes, and the pre-erase backup held a
    whole un-erased copy beside it.

    That fix has landed upstream (PORTED_BACK.md §11), in `core/` where it
    belongs, so this is now a thin call. Keeping the local copy would have meant
    two implementations of an erasure guarantee, which is the one place in this
    program where a silent divergence is least acceptable.

    Kept as a function rather than inlined into the widget so the call stays
    testable without Qt.
    """
    from core.erasure import erase_respondent

    return erase_respondent(project_dir, response_id, store_path=store,
                            purge_backups=purge_backups)
