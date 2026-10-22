"""
Drop targets for a model spec (`V6_PLAN.md` §3, Phase C desktop half).

`widgets/shelves.py` gives the chart builder a `FieldList` palette and a `Shelf`
that holds **one** field. A model needs both shapes: Outcome and Treatment take
one field each, which `Shelf` already does, and Predictors and Controls take
many, which is what `MultiShelf` here adds.

It accepts the same `FIELD_MIME` drag as the chart shelves and reuses the same
palette, so the gesture a researcher already knows from building a figure builds
a model. That is the whole reason the model spec was written in the chart
spec's shape.

**Dropping a field onto Treatment is what turns prediction into inference**, so
that shelf is enabled only for a method that estimates an effect. The Streamlit
build disables its Treatment picker for the same reason and in the same words;
the constraint lives in `core/model_spec.problems()`, and both front ends only
have to avoid contradicting it.
"""

from __future__ import annotations

from typing import List, Optional, Sequence

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QFrame, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QPushButton, QVBoxLayout, QWidget,
)

from qualsafe_qt.theme import muted_span
from qualsafe_qt.widgets.shelves import FIELD_MIME


class MultiShelf(QFrame):
    """A drop target that holds any number of fields, in drop order."""

    changed = Signal()

    def __init__(self, key: str, label: str, hint: str = "", *, labeler=None,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.key = key
        self._label = label
        #: Turns a stored field name into what is shown (the stored name is unchanged).
        self._labeler = labeler or (lambda name: name)

        self.setAcceptDrops(True)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)

        heading = QLabel(label)
        heading.setToolTip(hint or f"Drag fields here to put them on {label}.")
        layout.addWidget(heading)

        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list.setToolTip(
            "Select and press Delete to take a field off this shelf.")
        self.list.setMinimumHeight(90)
        layout.addWidget(self.list, 1)

        row = QHBoxLayout()
        self.count_label = QLabel()
        row.addWidget(self.count_label, 1)
        self.clear_button = QPushButton("Clear")
        self.clear_button.setToolTip("Take every field off this shelf.")
        self.clear_button.clicked.connect(self.clear_fields)
        row.addWidget(self.clear_button)
        layout.addLayout(row)

        self._refresh()

    # -- state ---------------------------------------------------------------

    def fields(self) -> List[str]:
        return [self.list.item(i).data(Qt.ItemDataRole.UserRole)
                for i in range(self.list.count())]

    def add_field(self, name: str) -> None:
        """Add one field, ignoring a repeat.

        Silently rather than with a complaint: dropping a field twice is a slip,
        and the same field on a shelf twice would make its coefficient
        uninterpretable rather than merely untidy.
        """
        if not name or name in self.fields():
            return
        item = QListWidgetItem(self._labeler(name))
        item.setData(Qt.ItemDataRole.UserRole, name)
        self.list.addItem(item)
        self._refresh()
        self.changed.emit()

    def set_fields(self, names: Sequence[str]) -> None:
        self.list.clear()
        for name in names:
            if name and name not in self.fields():
                item = QListWidgetItem(self._labeler(name))
                item.setData(Qt.ItemDataRole.UserRole, name)
                self.list.addItem(item)
        self._refresh()
        self.changed.emit()

    def remove_selected(self) -> None:
        for item in self.list.selectedItems():
            self.list.takeItem(self.list.row(item))
        self._refresh()
        self.changed.emit()

    def clear_fields(self) -> None:
        if not self.list.count():
            return
        self.list.clear()
        self._refresh()
        self.changed.emit()

    def _refresh(self) -> None:
        count = self.list.count()
        self.count_label.setText(
            muted_span("nothing yet" if not count else f"{count} field(s)"))
        self.clear_button.setEnabled(bool(count))

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
        # UserRole, never the display text: the palette's label carries a type
        # suffix, and round-tripping identity through a display string is the
        # trap `PORTED_BACK.md` §3 records.
        self.add_field(bytes(event.mimeData().data(FIELD_MIME)).decode())
        event.acceptProposedAction()

    def keyPressEvent(self, event) -> None:  # noqa: D102 - Qt override
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.remove_selected()
            return
        super().keyPressEvent(event)
