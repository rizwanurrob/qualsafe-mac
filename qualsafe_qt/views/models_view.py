"""
Model Manager: get the local models, and see what is actually on this machine.

The Qt counterpart of `app/model_manager.py`, and the screen without which a
fresh install cannot run the pipeline at all — an empty Hugging Face cache means
`ModelNotDownloadedError` and no way to fix it from inside the app.

Two things this screen is structurally careful about:

**Downloading never lifts offline mode.** `core.model_manager.download_model`
shells out to `tools/download_models.py` in a **subprocess**, so this process's
`HF_HUB_OFFLINE` / `TRANSFORMERS_OFFLINE` flags are never touched. That is the
whole reason model *acquisition* is separated from model *use* (invariant #2),
and there is an upstream test asserting the env vars survive a download. The
subprocess call is wrapped in a worker thread here only so the window stays
responsive during a multi-gigabyte fetch — it does not change the isolation.

**It tells you when the analysis engine is missing, not just the models.** The
desktop build can be installed without the transformer stack (torch,
transformers, sentence-transformers), which is several gigabytes and only the
pipeline and codebook-similarity need. Without it, downloading a model cannot
work and the reason has nothing to do with the network — so the screen says
which of the two is missing rather than reporting a confusing failure.
"""

from __future__ import annotations

import importlib.util
from typing import Dict, List, Optional

import pandas as pd
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import (
    QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
    QScrollArea, QTableView, QVBoxLayout, QWidget,
)

from core import engine_install
from core.model_manager import (
    DEFAULT_MODELS, ROLE_GUIDANCE, ROLE_LABELS, ROLES,
)
from core.offline import human_size, is_offline_enforced, model_cache_status
from qualsafe_qt.models.dataframe_model import DataFrameModel
from qualsafe_qt.theme import success_color, success_span, warning_color, warning_span
from qualsafe_qt.services.project_service import ProjectService
from qualsafe_qt.services.tasks import run_task
from qualsafe_qt.views.analysis_view import _hint, _table_view

#: The packages the transformer path needs. Checked by spec, never imported —
#: importing torch to find out whether torch exists costs seconds and memory.
ENGINE_PACKAGES = ("torch", "transformers", "sentence_transformers")


def engine_installed() -> bool:
    """True when the transformer stack is present on this machine."""
    return all(importlib.util.find_spec(name) is not None
               for name in ENGINE_PACKAGES)


def missing_engine_packages() -> List[str]:
    return [name for name in ENGINE_PACKAGES
            if importlib.util.find_spec(name) is None]


class ModelsView(QWidget):
    """Cache status, per-role model choice, downloads, and cache maintenance."""

    status = Signal(str)
    #: A role's model changed: (role, model_id). The shell persists it.
    model_chosen = Signal(str, str)

    def __init__(self, service: ProjectService, undo_stack: QUndoStack,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._service = service
        self._undo = undo_stack
        self._chosen: Dict[str, str] = dict(DEFAULT_MODELS)
        self._role_edits: Dict[str, QLineEdit] = {}
        self._role_buttons: Dict[str, List[QPushButton]] = {}
        self._downloading = False
        self._installing = False

        self._build_ui()
        self.refresh()

    # -- construction --------------------------------------------------------
    def _build_ui(self) -> None:
        self.engine_label = _hint("")
        self.engine_label.setWordWrap(True)

        self.engine_button = QPushButton("Install the analysis engine…")
        self.engine_button.clicked.connect(self._install_engine)
        self.engine_button.setToolTip(
            "Download PyTorch, transformers and sentence-transformers once (about 1 GB), into a folder of\n"
            "your own outside the program. Needed for suggested codes; needs the internet this one time.")
        self.engine_progress = _hint("")
        self.engine_progress.setWordWrap(True)

        self.offline_label = _hint("")

        self.cache_table = _table_view()
        self.cache_table.setSortingEnabled(False)
        self.cache_model = DataFrameModel()
        self.cache_table.setModel(self.cache_model)
        self.cache_table.setMaximumHeight(150)
        self.cache_table.setToolTip(
            "Each model this project would use, whether it is downloaded, and\n"
            "how much disk it takes.")

        refresh_button = QPushButton("Re-check the cache")
        refresh_button.clicked.connect(self.refresh)
        refresh_button.setToolTip(
            "Look again at what is on this machine. Needs no network.")

        cache_box = QGroupBox("What is on this machine")
        cache_layout = QVBoxLayout(cache_box)
        cache_layout.addWidget(self.engine_label)
        cache_layout.addWidget(self.engine_button)
        cache_layout.addWidget(self.engine_progress)
        cache_layout.addWidget(self.offline_label)
        cache_layout.addWidget(self.cache_table)
        cache_layout.addWidget(refresh_button)

        roles_box = QGroupBox("Models by role")
        roles_layout = QVBoxLayout(roles_box)
        roles_layout.addWidget(_hint(
            "<i>Point any role at a different Hugging Face model, not just the "
            "defaults. Downloads run in a separate process, so analysis itself "
            "never has the network enabled — only model weights are fetched, "
            "never your data.</i>"))
        for role in ROLES:
            roles_layout.addWidget(self._build_role_row(role))

        self.remove_edit = QLineEdit()
        self.remove_edit.setPlaceholderText("e.g. facebook/bart-large-mnli")
        self.remove_edit.setToolTip(
            "The model id to delete from this machine's cache.")
        remove_button = QPushButton("Remove from cache")
        remove_button.clicked.connect(self._remove)
        remove_button.setToolTip(
            "Free the disk space. The model can be downloaded again later.")
        remove_row = QHBoxLayout()
        remove_row.addWidget(self.remove_edit, 1)
        remove_row.addWidget(remove_button)

        maintenance = QGroupBox("Cache maintenance")
        maintenance_layout = QVBoxLayout(maintenance)
        maintenance_layout.addWidget(_hint(
            "<i>Remove a model from this machine's Hugging Face cache to reclaim "
            "disk. It can always be downloaded again.</i>"))
        maintenance_layout.addLayout(remove_row)

        # Five stacked boxes are taller than a modest window, and Qt clips
        # rather than scrolling by default -- which silently cut the model id
        # fields and their buttons in half. Scroll the whole page.
        inner = QWidget()
        inner_layout = QVBoxLayout(inner)
        inner_layout.setContentsMargins(0, 0, 0, 0)
        inner_layout.addWidget(cache_box)
        inner_layout.addWidget(roles_box)
        inner_layout.addWidget(maintenance)
        inner_layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidget(inner)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addWidget(scroll)

    def _build_role_row(self, role: str) -> QWidget:
        edit = QLineEdit(self._chosen.get(role, DEFAULT_MODELS[role]))
        edit.setToolTip(
            "A Hugging Face model id, like org-name/model-name.")
        self._role_edits[role] = edit

        download = QPushButton("Download && use")
        download.clicked.connect(lambda _c=False, r=role: self._download(r))
        download.setToolTip(
            "One-time, and it can take several minutes. Runs in a separate "
            "process so this app stays offline.")
        use_cached = QPushButton("Use (already cached)")
        use_cached.clicked.connect(lambda _c=False, r=role: self._use_cached(r))
        use_cached.setToolTip(
            "Select this model without downloading — only works if it is "
            "already in the cache.")
        reset = QPushButton("Reset to default")
        reset.clicked.connect(lambda _c=False, r=role: self._reset(r))
        self._role_buttons[role] = [download, use_cached, reset]

        buttons = QHBoxLayout()
        buttons.addWidget(download)
        buttons.addWidget(use_cached)
        buttons.addWidget(reset)
        buttons.addStretch(1)

        # QGroupBox reads "&" as a keyboard mnemonic, so ROLE_LABELS'
        # "clustering & similarity" renders as "clustering _similarity".
        box = QGroupBox(ROLE_LABELS[role].replace("&", "&&"))
        layout = QVBoxLayout(box)
        layout.addWidget(_hint(f"<i>{ROLE_GUIDANCE[role]}</i>"))
        layout.addWidget(edit)
        layout.addLayout(buttons)
        return box

    # -- state ---------------------------------------------------------------
    def set_chosen_models(self, chosen: Dict[str, str]) -> None:
        """Load the persisted per-role choices (called by the shell at start-up)."""
        for role in ROLES:
            value = (chosen or {}).get(role) or DEFAULT_MODELS[role]
            self._chosen[role] = value
            if role in self._role_edits:
                self._role_edits[role].setText(value)
        self.refresh()

    def chosen_models(self) -> Dict[str, str]:
        return dict(self._chosen)

    def refresh(self) -> None:
        """Re-read the cache and the engine status. Needs no network."""
        missing = missing_engine_packages()
        self.engine_button.setVisible(bool(missing))
        self.engine_button.setEnabled(not self._installing)
        if missing:
            self.engine_label.setText(
                "<span style='color:" + warning_color() + "'><b>The analysis engine is "
                "not installed.</b></span> Missing: <code>"
                + "</code>, <code>".join(missing) + "</code>. "
                "Reading, coding, the codebook, analysis, search, and query all "
                "work without it — the pipeline and the codebook's similarity "
                "check do not, and models cannot be downloaded until it is "
                "present.")
        else:
            self.engine_label.setText(
                "<span style='color:" + success_color() + "'><b>The analysis engine is "
                "installed.</b></span> The pipeline can run once the models "
                "below are cached.")

        self.offline_label.setText(
            success_span("Offline mode is armed: analysis cannot reach the network. "
                         "Downloads happen in a separate process.")
            if is_offline_enforced() else
            warning_span("Offline mode is <b>not</b> armed in this process — "
                         "HF_HUB_OFFLINE / TRANSFORMERS_OFFLINE are not both set.",
                         bold=False))

        rows = model_cache_status(sorted(set(self._chosen.values())))
        self.cache_model.set_frame(pd.DataFrame([{
            "model": r["model"],
            "status": ("unknown" if r["cached"] is None
                       else ("cached" if r["cached"] else "MISSING")),
            "size": human_size(float(r["size_bytes"])) if r["size_bytes"] else "—",
            "detail": r["detail"],
        } for r in rows], columns=["model", "status", "size", "detail"]))

    def missing_models(self) -> List[str]:
        """Chosen models that are not in the cache — what blocks a pipeline run."""
        return [r["model"] for r in model_cache_status(sorted(set(self._chosen.values())))
                if r["cached"] is False]

    # -- actions -------------------------------------------------------------
    def _set_buttons_enabled(self, enabled: bool) -> None:
        for buttons in self._role_buttons.values():
            for button in buttons:
                button.setEnabled(enabled)

    def _download(self, role: str) -> None:
        """Fetch a model in a subprocess, on a worker thread.

        The subprocess is the privacy guarantee (this process never has the hub
        enabled); the worker thread is only so a multi-gigabyte download does not
        freeze the window.
        """
        model_id = self._role_edits[role].text().strip()
        if not model_id:
            QMessageBox.information(self, "Name a model",
                                    "Enter a Hugging Face model id first.")
            return
        if missing_engine_packages():
            QMessageBox.information(
                self, "The analysis engine is not installed",
                "Downloading a model needs the analysis engine (the "
                "transformer stack: "
                f"{', '.join(missing_engine_packages())}), which is not "
                "installed on this machine.\n\n"
                "Everything except the pipeline and the codebook's similarity "
                "check works without it.")
            return
        if self._downloading:
            return

        self._downloading = True
        self._set_buttons_enabled(False)
        self.status.emit(f"Downloading {model_id} — one-time, may take minutes…")

        run_task(
            _download_model, model_id, role,
            on_finished=lambda result, r=role: self._on_downloaded(result, r),
            on_failed=lambda msg, _tb: self._on_download_failed(msg),
            on_done=self._on_download_done,
        )

    def _install_engine(self) -> None:
        """Install the analysis engine into the per-user folder, on a worker thread (core/engine_install.py)."""
        if self._installing:
            return
        folder = engine_install.engine_dir()
        answer = QMessageBox.question(
            self, "Install the analysis engine?",
            "The analysis engine (PyTorch, transformers and sentence-transformers) is needed for "
            "automatic suggested codes. Everything else works without it.\n\n"
            "QualSafe will download about 1 GB, once, and keep it in a folder of your own outside the "
            f"program:\n{folder}\n\n"
            "This needs an internet connection and can take 10 to 30 minutes. Your data is not involved. "
            "You can keep working meanwhile.",
            QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes,
            QMessageBox.StandardButton.Cancel)
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._installing = True
        self.engine_button.setEnabled(False)
        self.engine_progress.setText("Starting…")
        self.status.emit("Installing the analysis engine: one time, may take a while…")
        run_task(
            _install_engine_task, wants_progress=True,
            on_progress=lambda _fraction, message: self.engine_progress.setText(message[:200]),
            on_finished=self._on_engine_installed,
            on_failed=lambda message, _tb: self._on_engine_failed(message, ""),
            on_done=self._on_engine_done)

    def _on_engine_installed(self, result: Dict[str, object]) -> None:
        if result.get("ok"):
            self.engine_progress.setText("")
            self.status.emit("The analysis engine is installed.")
            QMessageBox.information(
                self, "The analysis engine is installed",
                "Done. You can now download the models below, then run automatic suggested codes.\n\n"
                "If anything still says the engine is missing, close QualSafe and open it again.")
        else:
            self._on_engine_failed(str(result.get("message") or "It did not finish."), str(result.get("log") or ""))

    def _on_engine_failed(self, message: str, log: str) -> None:
        self.engine_progress.setText("")
        self.status.emit("Installing the analysis engine failed.")
        detail = ("\n\nWhat pip said last:\n" + log[-1200:]) if log else ""
        QMessageBox.warning(
            self, "The analysis engine did not install",
            message + "\n\nNothing is broken: press the button to try again, and it carries on from where "
            "it stopped. It needs an internet connection." + detail)

    def _on_engine_done(self) -> None:
        self._installing = False
        self.refresh()

    def _on_download_done(self) -> None:
        self._downloading = False
        self._set_buttons_enabled(True)
        self.refresh()

    def _on_downloaded(self, result: Dict[str, object], role: str) -> None:
        if result.get("ok"):
            model_id = str(result.get("model") or "")
            self._chosen[role] = model_id
            self.model_chosen.emit(role, model_id)
            self.status.emit(f"{ROLE_LABELS[role]} model set to {model_id} and cached.")
        else:
            QMessageBox.warning(self, "Download failed",
                                str(result.get("message") or "Unknown error."))
            self.status.emit("Download failed.")

    def _on_download_failed(self, message: str) -> None:
        QMessageBox.critical(self, "Download failed", message)
        self.status.emit("Download failed.")

    def _use_cached(self, role: str) -> None:
        model_id = self._role_edits[role].text().strip()
        if not model_id:
            return
        self._chosen[role] = model_id
        self.model_chosen.emit(role, model_id)
        self.refresh()
        self.status.emit(f"{ROLE_LABELS[role]} model set to {model_id}.")

    def _reset(self, role: str) -> None:
        self._role_edits[role].setText(DEFAULT_MODELS[role])
        self._chosen[role] = DEFAULT_MODELS[role]
        self.model_chosen.emit(role, DEFAULT_MODELS[role])
        self.refresh()

    def _remove(self) -> None:
        from core.model_manager import remove_from_cache

        model_id = self.remove_edit.text().strip()
        if not model_id:
            return
        confirmed = QMessageBox.question(
            self, "Remove from the cache?",
            f"Delete '{model_id}' from this machine's Hugging Face cache?\n\n"
            "It can be downloaded again later.",
            QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes,
            QMessageBox.StandardButton.Cancel)
        if confirmed != QMessageBox.StandardButton.Yes:
            return
        try:
            freed = remove_from_cache(model_id)
        except Exception as exc:  # noqa: BLE001 - report, never crash
            QMessageBox.critical(self, "Could not remove that model", str(exc))
            return
        self.status.emit(
            f"Removed {model_id} — {human_size(float(freed))} freed." if freed
            else f"{model_id} was not in the cache.")
        self.refresh()


def _install_engine_task(progress_callback=None) -> Dict[str, object]:
    """Worker body: install the engine, reporting pip's lines. Never raises: a failure comes back as data."""
    def report(line: str) -> None:
        if progress_callback is not None:
            progress_callback(0.0, line)

    try:
        return engine_install.install(progress=report)
    except engine_install.EngineInstallError as error:
        return {"ok": False, "message": str(error), "log": error.log}


def _download_model(model_id: str, role: str) -> Dict[str, object]:
    """Worker body. Module-level, so it holds no widget and no connection."""
    from core.model_manager import download_model

    return download_model(model_id, role)
