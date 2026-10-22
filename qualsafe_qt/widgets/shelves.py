"""
Drag-and-drop shelves — the part of a chart builder Streamlit could not have.

`V5_PLAN.md` §B1a records the decision and its reasoning. In the web build the
shelves are dropdowns, because no Streamlit shelf component exists, the obvious
package has a documented history of loading from a CDN (disqualifying for a
program that promises no network at run time), and vendoring one would buy the
same number of interactions with worse accessibility.

Qt is the opposite case. `QListWidget` drag and `dropEvent` are native, this is a
few hundred lines, and dragging a field onto a shelf is genuinely better than
picking it from a list — you can see the fields and the shelves at once.

**Both builds emit the same `ChartRequest`**, so the two cannot drift into
drawing different charts from what looks like the same setup.

Two things worth keeping if this is edited:

* **A shelf must be clearable without a menu.** Every drop replaces, and Delete
  or Backspace on a focused shelf empties it. A builder you can only add to is a
  builder you have to restart to correct.
* **The aggregate lives on the shelf, not in a toolbar.** "Sum of weight" is a
  property of that shelf, and putting it elsewhere makes an analyst look in two
  places to answer what a bar means.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence

from PySide6.QtCore import QMimeData, Qt, Signal
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QFrame, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QPushButton, QVBoxLayout, QWidget,
)

from core.chart_spec import AGGREGATES
from qualsafe_qt.theme import color, muted_span

#: Our own MIME type. A plain-text drag would let any text in the app land on a
#: shelf, including a passage from the reader.
FIELD_MIME = "application/x-qualsafe-field"

_AGGREGATE_LABELS = {
    "": "as it is",
    "count": "Count of rows",
    "distinct": "Count of distinct values",
    "sum": "Sum",
    "mean": "Mean",
    "median": "Median",
    "min": "Minimum",
    "max": "Maximum",
}


class FieldList(QListWidget):
    """The draggable field palette."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setToolTip("Drag a field onto a shelf. Double-click sends it to the "
                        "first empty shelf.")

    def set_fields(self, field_types: Dict[str, str], *, label=None, hide=None,
                   type_word=None) -> None:
        """Fill the palette. By default every field shows under its own name with its
        type's first four letters; a screen can pass `label` (a name to show), `hide`
        (a field to leave out) and `type_word` (a type in plain words) instead."""
        self.clear()
        for name in sorted(field_types, key=lambda n: (label(n) if label else n).lower()):
            if hide is not None and hide(name):
                continue
            shown = label(name) if label else name
            kind = type_word(field_types[name]) if type_word else field_types[name][:4]
            item = QListWidgetItem(f"{shown}   ({kind})")
            item.setData(Qt.ItemDataRole.UserRole, name)
            item.setToolTip(f"{shown} — {type_word(field_types[name]) if type_word else field_types[name]}")
            self.addItem(item)

    def startDrag(self, _actions) -> None:  # noqa: D102 - Qt override
        item = self.currentItem()
        if item is None:
            return
        # The field name comes from UserRole, never from the display text: the
        # label carries a type suffix, and round-tripping identity through a
        # display string is the trap PORTED_BACK.md §3 records.
        payload = QMimeData()
        payload.setData(FIELD_MIME, str(item.data(Qt.ItemDataRole.UserRole)).encode())
        drag = QDrag(self)
        drag.setMimeData(payload)
        drag.exec(Qt.DropAction.CopyAction)


class Shelf(QFrame):
    """One drop target: a field, and how to aggregate it."""

    changed = Signal()

    def __init__(self, key: str, label: str, *, allow_aggregate: bool = True,
                 labeler=None, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.key = key
        self._field = ""
        self._allow_aggregate = allow_aggregate
        #: Turns the stored field name into what is shown on the shelf.
        self._labeler = labeler or (lambda name: name)

        self.setAcceptDrops(True)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)

        heading = QLabel(label)
        heading.setToolTip(f"Drag a field here to put it on {label}.")
        layout.addWidget(heading)

        row = QHBoxLayout()
        self.field_label = QLabel()
        self.field_label.setTextFormat(Qt.TextFormat.RichText)
        row.addWidget(self.field_label, 1)
        self.clear_button = QPushButton("✕")
        self.clear_button.setFixedWidth(24)
        self.clear_button.setToolTip("Take the field off this shelf.")
        self.clear_button.clicked.connect(self.clear_field)
        row.addWidget(self.clear_button)
        layout.addLayout(row)

        self.aggregate = QComboBox()
        # Every aggregate is offered whatever the field is. The rule about which
        # ones a column can support lives in `chart_spec.problems()` and is
        # explained in a sentence; hiding options here would put it in two
        # places and say nothing about why.
        for key_name in [""] + list(AGGREGATES):
            self.aggregate.addItem(_AGGREGATE_LABELS.get(key_name, key_name), key_name)
        self.aggregate.currentIndexChanged.connect(lambda _i: self.changed.emit())
        self.aggregate.setToolTip("How to reduce this field to one number per bar.")
        layout.addWidget(self.aggregate)
        self.aggregate.setVisible(allow_aggregate)

        self._refresh()

    # -- state ---------------------------------------------------------------

    def field(self) -> str:
        return self._field

    def aggregate_key(self) -> str:
        if not self._allow_aggregate:
            return ""
        return str(self.aggregate.currentData() or "")

    def set_field(self, name: str) -> None:
        self._field = name or ""
        self._refresh()
        self.changed.emit()

    def set_aggregate(self, key: str) -> None:
        index = self.aggregate.findData(key or "")
        if index >= 0:
            self.aggregate.setCurrentIndex(index)

    def clear_field(self) -> None:
        self.set_field("")

    def _refresh(self) -> None:
        if self._field:
            self.field_label.setText(f"<b>{self._labeler(self._field)}</b>")
        else:
            self.field_label.setText(muted_span("drop a field here"))
        self.clear_button.setEnabled(bool(self._field))
        self.setStyleSheet(
            f"QFrame {{ border: 1px solid {color('border')}; border-radius: 4px; }}"
            if self._field else
            f"QFrame {{ border: 1px dashed {color('border')}; border-radius: 4px; }}")

    # -- Qt overrides --------------------------------------------------------

    def dragEnterEvent(self, event) -> None:  # noqa: D102 - Qt override
        if event.mimeData().hasFormat(FIELD_MIME):
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:  # noqa: D102 - Qt override
        if event.mimeData().hasFormat(FIELD_MIME):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: D102 - Qt override
        if not event.mimeData().hasFormat(FIELD_MIME):
            return
        name = bytes(event.mimeData().data(FIELD_MIME)).decode()
        self.set_field(name)
        event.acceptProposedAction()

    def keyPressEvent(self, event) -> None:  # noqa: D102 - Qt override
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.clear_field()
            return
        super().keyPressEvent(event)


class ShelfRow(QWidget):
    """The shelves for one mark, rebuilt when the mark changes."""

    changed = Signal()

    #: Which shelves can carry an aggregate. Colour and facet describe
    #: categories, and `chart_spec` never reads an aggregate from them.
    AGGREGATABLE = {"x", "y"}

    LABELS = {"x": "X — across", "y": "Y — up", "color": "Colour",
              "facet": "Split by"}
    #: A pie has no axes, so calling its shelves X and Y would be a lie.
    ARC_LABELS = {"y": "Size", "color": "Slices"}

    def __init__(self, parent: Optional[QWidget] = None, *, labeler=None) -> None:
        super().__init__(parent)
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._shelves: Dict[str, Shelf] = {}
        self._labeler = labeler

    def set_labeler(self, labeler) -> None:
        """Show fields under other names (the stored name is unchanged)."""
        self._labeler = labeler
        for shelf in self._shelves.values():
            shelf._labeler = labeler or (lambda name: name)
            shelf._refresh()

    def build(self, keys: Sequence[str], *, arc: bool = False) -> None:
        """Rebuild for a mark, keeping whatever the surviving shelves held.

        Switching bar → stacked bar should not empty the shelves the analyst just
        filled; only shelves the new mark does not have go away.
        """
        kept = {key: (shelf.field(), shelf.aggregate_key())
                for key, shelf in self._shelves.items()}

        while self._layout.count():
            item = self._layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self._shelves = {}

        labels = self.ARC_LABELS if arc else self.LABELS
        for key in keys:
            shelf = Shelf(key, labels.get(key, self.LABELS.get(key, key.title())),
                          allow_aggregate=key in self.AGGREGATABLE, labeler=self._labeler)
            field, aggregate = kept.get(key, ("", ""))
            if field:
                shelf._field = field  # set directly: no signal during a rebuild
                shelf._refresh()
            shelf.set_aggregate(aggregate)
            shelf.changed.connect(self.changed.emit)
            self._layout.addWidget(shelf)
            self._shelves[key] = shelf

    def shelves(self) -> Dict[str, Shelf]:
        return dict(self._shelves)

    def first_empty(self) -> Optional[Shelf]:
        for shelf in self._shelves.values():
            if not shelf.field():
                return shelf
        return None

    def assignment(self) -> Dict[str, Dict[str, str]]:
        return {key: {"field": shelf.field(), "aggregate": shelf.aggregate_key()}
                for key, shelf in self._shelves.items()}
