"""
Settings > General: your name, how the app looks, and whether it is offline.

The first tab of Settings. Models and Project and backups are the other two.
Each setting here already existed behind a menu (Edit > analyst name, View >
Appearance); this puts them where a person looks for settings. The window does
the saving; this widget only shows the values and says when one changes.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QRadioButton,
    QStyle, QVBoxLayout, QWidget,
)

from qualsafe_qt.theme import muted_span, success_span, warning_span


class GeneralSettings(QWidget):
    """Analyst name, light or dark, and the offline status."""

    analyst_name_changed = Signal(str)
    theme_changed = Signal(str)          # "light" | "dark"
    appearance_requested = Signal()      # open the full Appearance dialog

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(14)

        # -- your name --------------------------------------------------------
        name_box = QGroupBox("Your name")
        name_layout = QVBoxLayout(name_box)
        name_layout.addWidget(self._hint(
            "Saved with every code you apply, so a second coder's work can be "
            "told apart from yours."))
        row = QHBoxLayout()
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("For example: Dana Reyes")
        self.name_edit.setMinimumWidth(300)
        self.name_edit.setMaximumWidth(420)
        self.name_edit.returnPressed.connect(self._save_name)
        row.addWidget(self.name_edit)
        self.name_button = QPushButton("Save name")
        self.name_button.clicked.connect(self._save_name)
        row.addWidget(self.name_button)
        row.addStretch(1)
        name_layout.addLayout(row)
        outer.addWidget(name_box)

        # -- appearance -------------------------------------------------------
        look_box = QGroupBox("How it looks")
        look_layout = QVBoxLayout(look_box)
        theme_row = QHBoxLayout()
        self.dark_radio = QRadioButton("Dark")
        self.light_radio = QRadioButton("Light")
        self.dark_radio.setChecked(True)
        self.light_radio.toggled.connect(
            lambda light: self.theme_changed.emit("light" if light else "dark"))
        theme_row.addWidget(self.dark_radio)
        theme_row.addWidget(self.light_radio)
        theme_row.addStretch(1)
        look_layout.addLayout(theme_row)
        self.more_look_button = QPushButton("Text size and colours…")
        self.more_look_button.setToolTip(
            "Text size, the colours used for codes, and the heatmap colours.")
        self.more_look_button.clicked.connect(self.appearance_requested.emit)
        look_layout.addWidget(self.more_look_button, 0, Qt.AlignmentFlag.AlignLeft)
        outer.addWidget(look_box)

        # -- offline ----------------------------------------------------------
        offline_box = QGroupBox("Privacy")
        offline_layout = QVBoxLayout(offline_box)
        status_row = QHBoxLayout()
        self.offline_icon = QLabel()      # a real icon: font glyphs vary by machine
        self.offline_icon.setFixedWidth(22)
        status_row.addWidget(self.offline_icon)
        self.offline_label = QLabel()
        self.offline_label.setTextFormat(Qt.TextFormat.RichText)
        self.offline_label.setWordWrap(True)
        status_row.addWidget(self.offline_label, 1)
        offline_layout.addLayout(status_row)
        offline_layout.addWidget(self._hint(
            "Your text is analysed on this computer and never uploaded. Models "
            "are downloaded separately, in the Models tab."))
        outer.addWidget(offline_box)
        outer.addStretch(1)

    # -- values ---------------------------------------------------------------
    def set_analyst_name(self, name: str) -> None:
        self.name_edit.setText(name)

    def set_theme_mode(self, mode: str) -> None:
        for button, wanted in ((self.light_radio, "light"), (self.dark_radio, "dark")):
            button.blockSignals(True)
            button.setChecked(mode == wanted)
            button.blockSignals(False)

    def set_offline(self, enforced: bool, mode: str = "") -> None:
        """Icon and word, never colour alone."""
        icon = (QStyle.StandardPixmap.SP_DialogApplyButton if enforced
                else QStyle.StandardPixmap.SP_MessageBoxWarning)
        self.offline_icon.setPixmap(self.style().standardIcon(icon).pixmap(18, 18))
        if enforced:
            self.offline_label.setText(success_span(
                "Offline mode is on.", bold=True, mode=mode)
                + " Analysis cannot reach the internet.")
        else:
            self.offline_label.setText(warning_span(
                "Offline mode is off.", mode=mode)
                + " Model downloads are meant to be a separate, deliberate step.")

    # -- internals ------------------------------------------------------------
    def _save_name(self) -> None:
        self.analyst_name_changed.emit(self.name_edit.text().strip())

    def _hint(self, text: str) -> QLabel:
        label = QLabel(muted_span(text))
        label.setTextFormat(Qt.TextFormat.RichText)
        label.setWordWrap(True)
        return label
