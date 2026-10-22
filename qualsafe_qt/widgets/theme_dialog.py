"""
A small dialog for making a colour theme: a name, seven colours, a few extras.

It holds no rules of its own. `core.chartbuilder.themes.build_theme` turns the
fields into a `Theme` and decides what is a valid colour, so the words on a
refused hex are the same here as on the web page, and the OK button is simply
enabled while `theme()` succeeds. Each colour has a swatch beside it so a
mistyped hex is visible before it is saved.

The dialog is never opened by anything a test can reach without going through
`DataChartsView._open_theme_dialog` (a modal blocks forever under the offscreen
platform), so tests construct it directly and read `theme()`.
"""

from __future__ import annotations

from typing import Dict, Optional

from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QVBoxLayout,
    QWidget,
)

from core.chartbuilder import themes

#: (label, attribute on Theme) in the order they are asked for.
COLOUR_FIELDS = [("Primary", "primary"), ("Secondary", "secondary"), ("Neutral", "neutral"),
                 ("Background", "background"), ("Text", "text"), ("Title", "title"),
                 ("Gridlines", "gridline")]


class ThemeDialog(QDialog):
    def __init__(self, parent: Optional[QWidget] = None, base: Optional[themes.Theme] = None) -> None:
        super().__init__(parent)
        base = base or themes.BUILT_IN_DEFAULT
        self.setWindowTitle("Make a colour theme")
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("A name for this theme")
        self.colour_edits: Dict[str, QLineEdit] = {}
        self._swatches: Dict[str, QLabel] = {}
        self.tertiary_edit = QLineEdit(", ".join(base.tertiary))
        self.palette_edit = QLineEdit()
        self.palette_edit.setPlaceholderText("Blank: derived from the colours above")
        self.error_label = QLabel("")
        self.error_label.setWordWrap(True)

        form = QFormLayout()
        form.addRow("Name", self.name_edit)
        for label, attr in COLOUR_FIELDS:
            edit = QLineEdit(getattr(base, attr))
            swatch = QLabel()
            swatch.setFixedSize(28, 18)
            row = QWidget()
            layout = QHBoxLayout(row)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.addWidget(edit, 1)
            layout.addWidget(swatch)
            form.addRow(f"{label} (hex)", row)
            self.colour_edits[attr] = edit
            self._swatches[attr] = swatch
            edit.textChanged.connect(self._check)
        form.addRow("Other colours (hex, comma separated)", self.tertiary_edit)
        form.addRow("Colour order for categories", self.palette_edit)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        root = QVBoxLayout(self)
        root.addLayout(form)
        root.addWidget(self.error_label)
        root.addWidget(self.buttons)
        for edit in (self.name_edit, self.tertiary_edit, self.palette_edit):
            edit.textChanged.connect(self._check)
        self._check()

    def theme(self) -> themes.Theme:
        """The theme the fields describe. Raises `ValueError` in words."""
        values = {attr: edit.text() for attr, edit in self.colour_edits.items()}
        return themes.build_theme(self.name_edit.text(), tertiary=self.tertiary_edit.text(),
                                  palette=self.palette_edit.text(), **values)

    def _check(self) -> None:
        for attr, edit in self.colour_edits.items():
            try:
                self._swatches[attr].setStyleSheet(
                    f"background:{themes.normalize_hex(edit.text())};border:1px solid #888;")
            except ValueError:
                self._swatches[attr].setStyleSheet("background:transparent;border:1px dashed #c33;")
        try:
            self.theme()
        except ValueError as error:
            self.error_label.setText(str(error))
            self.buttons.button(QDialogButtonBox.Ok).setEnabled(False)
        else:
            self.error_label.setText("")
            self.buttons.button(QDialogButtonBox.Ok).setEnabled(True)
