"""
The codebook as a real tree, with drag-to-reparent.

`core.model.Code` already describes arbitrary-depth nesting via `parent_id`; the
Streamlit page can only expose that as a "Parent code" dropdown, which means
reorganising a codebook is a sequence of blind selectbox edits with no view of
the shape you are producing. A `QTreeView` over this model shows the hierarchy
and lets you drag a code onto its new parent.

Design notes:

* **The model is a read-only projection plus a drop signal.** It does not write
  to the store. A drop emits `reparent_requested(code_id, new_parent_id)` and the
  view turns that into an undoable command -- keeping the "no widget touches the
  store" rule, and keeping reparenting on the undo stack where a structural edit
  belongs.
* **Cycles are rejected before the drop is offered.** `Project.set_code_parent`
  already refuses a move that would make a code its own ancestor; doing the same
  check in `canDropMimeData` means the cursor shows "no" during the drag instead
  of raising an error after it. Same rule, enforced twice on purpose -- the store
  is the authority, the model is the affordance.
* **Rows are ordered by name**, not by `code_id`. `Project.get_codebook()`
  returns insertion order, which is meaningless to a reader.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from PySide6.QtCore import QAbstractItemModel, QMimeData, QModelIndex, Qt, Signal

from core.ux.fields import origin_label

#: MIME type for an internal drag of one code. Private to this application.
CODE_MIME = "application/x-qualsafe-code-id"

#: The id used for "no parent" in drop handling -- a drop on blank space makes a
#: code a root, which is how you promote a child out of a branch.
ROOT_ID = ""


class CodebookModel(QAbstractItemModel):
    """Tree of `core.model.Code`, with application counts.

    Columns: name, applications, definition.
    """

    #: A drag-and-drop reparent was requested: (code_id, new_parent_id or "").
    reparent_requested = Signal(str, str)

    COLUMNS = ("Code", "Uses", "Definition")

    def __init__(self, parent: Optional[Any] = None) -> None:
        super().__init__(parent)
        self._codes: Dict[str, Any] = {}
        self._children: Dict[str, List[str]] = {ROOT_ID: []}
        self._parent_of: Dict[str, str] = {}
        self._freq: Dict[str, int] = {}

    # -- population ----------------------------------------------------------
    def set_codebook(self, codes: Sequence[Any], frequency: Dict[str, int]) -> None:
        """Rebuild from `Project.get_codebook()` + `Project.code_frequency()`."""
        self.beginResetModel()
        self._codes = {c.code_id: c for c in codes}
        self._freq = dict(frequency or {})
        self._children = {ROOT_ID: []}
        self._parent_of = {}
        for code in codes:
            self._children.setdefault(code.code_id, [])
        for code in codes:
            # A code whose parent has been deleted is an orphan, not an error:
            # show it at the root so it stays reachable and fixable. The
            # codebook-health panel reports it separately.
            parent = code.parent_id if code.parent_id in self._codes else ROOT_ID
            self._parent_of[code.code_id] = parent
            self._children[parent].append(code.code_id)
        for siblings in self._children.values():
            siblings.sort(key=lambda cid: (self._codes[cid].name or "").lower())
        self.endResetModel()

    def code(self, code_id: str) -> Optional[Any]:
        return self._codes.get(code_id)

    def code_id_at(self, index: QModelIndex) -> str:
        return index.internalPointer() if index.isValid() else ROOT_ID

    def index_for_code(self, code_id: str) -> QModelIndex:
        """The index of `code_id`, or an invalid index when it is not present."""
        if code_id not in self._codes:
            return QModelIndex()
        parent_id = self._parent_of.get(code_id, ROOT_ID)
        row = self._children[parent_id].index(code_id)
        return self.createIndex(row, 0, code_id)

    def descendants(self, code_id: str) -> List[str]:
        """Every code beneath `code_id`, used to refuse a cyclic drop."""
        out: List[str] = []
        stack = list(self._children.get(code_id, []))
        while stack:
            current = stack.pop()
            out.append(current)
            stack.extend(self._children.get(current, []))
        return out

    # -- QAbstractItemModel --------------------------------------------------
    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: D102
        return len(self._children.get(self.code_id_at(parent), []))

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: D102
        return len(self.COLUMNS)

    def index(self, row: int, column: int,  # noqa: D102
              parent: QModelIndex = QModelIndex()) -> QModelIndex:
        siblings = self._children.get(self.code_id_at(parent), [])
        if not (0 <= row < len(siblings)) or not (0 <= column < len(self.COLUMNS)):
            return QModelIndex()
        return self.createIndex(row, column, siblings[row])

    def parent(self, index: QModelIndex = QModelIndex()) -> QModelIndex:  # noqa: D102
        if not index.isValid():
            return QModelIndex()
        parent_id = self._parent_of.get(index.internalPointer(), ROOT_ID)
        if parent_id == ROOT_ID:
            return QModelIndex()
        grandparent = self._parent_of.get(parent_id, ROOT_ID)
        return self.createIndex(self._children[grandparent].index(parent_id), 0, parent_id)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):  # noqa: D102
        if not index.isValid():
            return None
        code = self._codes.get(index.internalPointer())
        if code is None:
            return None
        if role == Qt.ItemDataRole.UserRole:
            return code.code_id
        if role == Qt.ItemDataRole.DisplayRole:
            if index.column() == 0:
                return code.name
            if index.column() == 1:
                return str(self._freq.get(code.code_id, 0))
            return " ".join((code.definition or "").split())
        if role == Qt.ItemDataRole.ToolTipRole:
            uses = self._freq.get(code.code_id, 0)
            definition = (code.definition or "").strip() or "(no definition yet)"
            return (f"{code.name}\n{definition}\n\n{uses} application(s) · "
                    f"{origin_label(code.origin)} · created by {code.created_by}")
        return None

    def headerData(self, section: int, orientation: Qt.Orientation,  # noqa: D102
                   role: int = Qt.ItemDataRole.DisplayRole):
        if (orientation == Qt.Orientation.Horizontal
                and role == Qt.ItemDataRole.DisplayRole):
            return self.COLUMNS[section]
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:  # noqa: D102
        base = (Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        if not index.isValid():
            # A drop on empty space promotes a code to the root.
            return base | Qt.ItemFlag.ItemIsDropEnabled
        return base | Qt.ItemFlag.ItemIsDragEnabled | Qt.ItemFlag.ItemIsDropEnabled

    # -- drag and drop -------------------------------------------------------
    def supportedDropActions(self) -> Qt.DropAction:  # noqa: D102
        return Qt.DropAction.MoveAction

    def mimeTypes(self) -> List[str]:  # noqa: D102
        return [CODE_MIME]

    def mimeData(self, indexes: Sequence[QModelIndex]) -> QMimeData:  # noqa: D102
        data = QMimeData()
        for index in indexes:
            if index.isValid():
                data.setData(CODE_MIME, index.internalPointer().encode("utf-8"))
                break
        return data

    def canDropMimeData(self, data: QMimeData, action: Qt.DropAction,  # noqa: D102
                        row: int, column: int, parent: QModelIndex) -> bool:
        if not data.hasFormat(CODE_MIME):
            return False
        dragged = bytes(data.data(CODE_MIME)).decode("utf-8")
        target = self.code_id_at(parent)
        if dragged not in self._codes:
            return False
        if target == dragged:
            return False                       # a code cannot parent itself
        if target and target in self.descendants(dragged):
            return False                       # would create a cycle
        if self._parent_of.get(dragged, ROOT_ID) == target:
            return False                       # already there; nothing to do
        return True

    def dropMimeData(self, data: QMimeData, action: Qt.DropAction,  # noqa: D102
                     row: int, column: int, parent: QModelIndex) -> bool:
        if not self.canDropMimeData(data, action, row, column, parent):
            return False
        dragged = bytes(data.data(CODE_MIME)).decode("utf-8")
        # The model does not mutate: the view owns the store write so it can be
        # pushed onto the undo stack.
        self.reparent_requested.emit(dragged, self.code_id_at(parent))
        return False      # False: no rows moved *by the model*; a reload follows
