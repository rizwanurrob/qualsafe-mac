"""
"More options": the controls most people never touch, one click away.

Design rule 2 of Update 3: at most seven controls visible on a step before this
panel is opened, with defaults chosen for the person who does not know what an
option means. Nothing is removed; it is folded away. The panel starts closed,
says how many options are inside, and a screen reader hears it as a button that
expands a section.

`visible_controls()` counts what is on show, so a test (and anyone auditing a
screen) can check the rule instead of trusting it.
"""

from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import Qt, Signal
from core.ux.help import tips as shared_tips
from qualsafe_qt.widgets.info_tip import InfoTip
from PySide6.QtWidgets import (
    QAbstractButton, QComboBox, QDoubleSpinBox, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QPlainTextEdit, QSpinBox, QTextEdit, QToolButton, QVBoxLayout, QWidget,
)

#: What counts as a control. A list or text box is one control however many rows it has.
CONTROL_TYPES = (QAbstractButton, QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox,
                 QListWidget, QPlainTextEdit, QTextEdit)

#: The most controls a step may show before its More options are opened.
MAX_VISIBLE_CONTROLS = 7


class MoreOptions(QWidget):
    """A closed-by-default section: a toggle button and a panel of labelled rows."""

    toggled = Signal(bool)

    def __init__(self, title: str = "More options", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._title = title
        self._count = 0

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)

        self.toggle = QToolButton()
        self.toggle.setCheckable(True)
        self.toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.toggle.setAutoRaise(True)
        self.toggle.setAccessibleName(title)
        self.toggle.toggled.connect(self._on_toggled)
        outer.addWidget(self.toggle, 0, Qt.AlignmentFlag.AlignLeft)

        self.body = QFrame()
        self.body.setFrameShape(QFrame.Shape.NoFrame)
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(22, 0, 0, 0)
        self.body_layout.setSpacing(8)
        self.body.setVisible(False)
        outer.addWidget(self.body)

        self._refresh_title()

    # -- building ------------------------------------------------------------
    def add_row(self, label: str, widget: QWidget, *, caption: Optional[QLabel] = None,
                tip: Optional[str] = None) -> QLabel:
        """Add `widget` with a caption on its left. Returns the caption label.

        A small (i) goes beside the caption when there is a tip for it: `tip` names one
        (`core/ux/help/tips.py`), or the label itself finds one."""
        row = QHBoxLayout()
        text = caption or QLabel(label)
        text.setMinimumWidth(150)
        text.setWordWrap(True)
        tip_id = tip or shared_tips.for_label(label)
        if tip_id:
            holder = QHBoxLayout()
            holder.setContentsMargins(0, 0, 0, 0)
            holder.addWidget(text, 1, Qt.AlignmentFlag.AlignTop)
            holder.addWidget(InfoTip(tip_id, about=label), 0, Qt.AlignmentFlag.AlignTop)
            row.addLayout(holder)
        else:
            row.addWidget(text, 0, Qt.AlignmentFlag.AlignTop)
        row.addWidget(widget, 1)
        self.body_layout.addLayout(row)
        self._count += 1
        self._refresh_title()
        return text

    def add_note(self, text: str) -> QLabel:
        note = QLabel(text)
        note.setWordWrap(True)
        self.body_layout.addWidget(note)
        return note

    # -- state ---------------------------------------------------------------
    def set_expanded(self, expanded: bool) -> None:
        self.toggle.setChecked(expanded)

    def is_expanded(self) -> bool:
        return self.toggle.isChecked()

    def _on_toggled(self, on: bool) -> None:
        self.body.setVisible(on)
        self.toggle.setArrowType(Qt.ArrowType.DownArrow if on else Qt.ArrowType.RightArrow)
        self.toggled.emit(on)

    def _refresh_title(self) -> None:
        suffix = f" ({self._count})" if self._count else ""
        self.toggle.setText(self._title + suffix)


def count_controls(root: QWidget) -> int:
    """How many controls are inside `root`, shown or not (the number in a panel's title)."""
    return sum(
        1 for w in root.findChildren(QWidget)
        if isinstance(w, CONTROL_TYPES) and not w.objectName().startswith("qt_")
        and not w.property("infoTip")
        and not (isinstance(w, QLineEdit) and isinstance(w.parent(), (QComboBox, QSpinBox, QDoubleSpinBox))))


def visible_controls(root: QWidget) -> List[QWidget]:
    """The controls a person can see inside `root` right now.

    Controls in a closed More options panel are hidden, so they do not count.
    Qt's own parts (a combo's inner line edit, scroll bars) are skipped."""
    found = []
    for widget in root.findChildren(QWidget):
        if not isinstance(widget, CONTROL_TYPES):
            continue
        if widget.objectName().startswith("qt_") or not widget.isVisibleTo(root):
            continue
        if widget.property("infoTip"):                 # help, not a control of the step
            continue
        if isinstance(widget, QLineEdit) and isinstance(widget.parent(), (QComboBox, QSpinBox, QDoubleSpinBox)):
            continue
        found.append(widget)
    return found
