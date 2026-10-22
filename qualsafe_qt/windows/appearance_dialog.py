"""
Appearance: skin, text size, code palette, and heatmap colours in one place.

Previously these were scattered — the skin was a checkbox in the View menu, the
heatmap ramp was a dropdown on one analysis tab and was not remembered, code
colours could not be changed at all, and text size could not be changed at all.
That last one matters more than it sounds for a tool whose main activity is
reading transcripts for hours.

Everything here is a **preference**, so it persists through the settings
whitelist — never anything derived from a response, a document, or a code.
Per-code colour overrides are the exception and deliberately do *not* live here:
they belong to the project, so they travel with it to a colleague.
"""

from __future__ import annotations

from typing import Dict, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QGroupBox,
    QHBoxLayout, QLabel, QVBoxLayout, QWidget,
)

from core.theme import DEFAULT_HEATMAP_SCHEME, HEATMAP_SCHEMES, heatmap_range
from qualsafe_qt.theme import (
    CATEGORY_PALETTES, DEFAULT_CATEGORY_PALETTE, category_colors,
)

#: Bounds on the base font size. Below 8pt Qt's own chrome stops fitting; above
#: 18pt a three-pane layout stops being three panes on a laptop.
MIN_FONT_PT = 8.0
MAX_FONT_PT = 18.0
DEFAULT_FONT_PT = 10.5


class _Swatches(QWidget):
    """A row of colour chips, so a palette choice is visible before it applies."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._colors = []
        self.setMinimumHeight(26)

    def set_colors(self, colors) -> None:
        self._colors = [QColor(c) for c in colors]
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: D102 - Qt override
        if not self._colors:
            return
        painter = QPainter(self)
        width = max(8, self.width() // max(1, len(self._colors)))
        for index, color in enumerate(self._colors):
            painter.fillRect(index * width, 2, width - 2, self.height() - 4, color)


class AppearanceDialog(QDialog):
    """Preview-as-you-go appearance settings.

    Emits `changed` on every adjustment rather than only on OK, because the point
    of a colour choice is seeing it. `rejected` restores what was there before —
    a preview that cannot be backed out of is a trap.
    """

    changed = Signal(dict)

    def __init__(self, current: Dict[str, object],
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Appearance")
        self.setMinimumWidth(520)
        self._initial = dict(current)

        self.mode = QComboBox()
        self.mode.addItem("Dark", "dark")
        self.mode.addItem("Light", "light")
        index = self.mode.findData(current.get("theme_mode", "dark"))
        self.mode.setCurrentIndex(max(0, index))

        self.font_pt = QDoubleSpinBox()
        self.font_pt.setRange(MIN_FONT_PT, MAX_FONT_PT)
        self.font_pt.setSingleStep(0.5)
        self.font_pt.setSuffix(" pt")
        self.font_pt.setValue(float(current.get("font_pt", DEFAULT_FONT_PT)))
        self.font_pt.setToolTip(
            "The base text size for the whole app, including the document "
            "reader. Reading transcripts is most of the work here.")

        self.palette = QComboBox()
        for name in CATEGORY_PALETTES:
            self.palette.addItem(name, name)
        index = self.palette.findData(
            current.get("category_palette", DEFAULT_CATEGORY_PALETTE))
        self.palette.setCurrentIndex(max(0, index))
        self.palette.setToolTip(
            "Colours for codes — the reader's margin stripes, highlights, and "
            "the frequency chart.\n"
            "Okabe-Ito is designed for colour-vision deficiency.")
        self.palette_swatches = _Swatches()

        self.heatmap = QComboBox()
        for name in HEATMAP_SCHEMES:
            self.heatmap.addItem(name, name)
        index = self.heatmap.findData(
            current.get("heatmap_scheme", DEFAULT_HEATMAP_SCHEME))
        self.heatmap.setCurrentIndex(max(0, index))
        self.heatmap.setToolTip(
            "The ramp for the co-occurrence matrix. Every ramp keeps low counts "
            "visible rather than fading them into the background.")
        self.heatmap_swatches = _Swatches()

        for widget in (self.mode, self.palette, self.heatmap):
            widget.currentIndexChanged.connect(self._emit)
        self.font_pt.valueChanged.connect(self._emit)

        skin = QGroupBox("Skin and text")
        skin_form = QFormLayout(skin)
        skin_form.addRow("Theme", self.mode)
        skin_form.addRow("Text size", self.font_pt)

        colours = QGroupBox("Colours")
        colours_layout = QVBoxLayout(colours)
        code_row = QFormLayout()
        code_row.addRow("Code colours", self.palette)
        colours_layout.addLayout(code_row)
        colours_layout.addWidget(self.palette_swatches)
        heat_row = QFormLayout()
        heat_row.addRow("Heatmap ramp", self.heatmap)
        colours_layout.addLayout(heat_row)
        colours_layout.addWidget(self.heatmap_swatches)
        colours_layout.addWidget(_note(
            "Individual codes can be given their own colour on the Codebook "
            "screen. Those are saved in the project, so they travel with it."))

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self._revert)

        layout = QVBoxLayout(self)
        layout.addWidget(skin)
        layout.addWidget(colours)
        layout.addWidget(buttons)
        self._refresh_swatches()

    def settings(self) -> Dict[str, object]:
        return {
            "theme_mode": self.mode.currentData(),
            "font_pt": float(self.font_pt.value()),
            "category_palette": self.palette.currentData(),
            "heatmap_scheme": self.heatmap.currentData(),
        }

    def _refresh_swatches(self) -> None:
        mode = self.mode.currentData() or "dark"
        self.palette_swatches.set_colors(
            category_colors(mode, self.palette.currentData()))
        self.heatmap_swatches.set_colors(heatmap_range(self.heatmap.currentData()))

    def _emit(self) -> None:
        self._refresh_swatches()
        self.changed.emit(self.settings())

    def _revert(self) -> None:
        """Cancel restores what was there before — a live preview must be
        reversible, or trying a palette becomes a commitment."""
        self.changed.emit(dict(self._initial))
        self.reject()


def _note(text: str) -> QLabel:
    label = QLabel(f"<i>{text}</i>")
    label.setWordWrap(True)
    label.setTextFormat(Qt.TextFormat.RichText)
    return label
