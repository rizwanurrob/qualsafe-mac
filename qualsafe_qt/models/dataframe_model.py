"""
One `QAbstractTableModel` over a pandas DataFrame, for every table in the app.

`analysis/*` are pure functions that return DataFrames — `code_frequency`,
`per_code_kappa`, `code_by_descriptor`, and the rest. Rather than unpacking each
one into a `QTableWidget` by hand (which is what the documents screen does for
its small corpus list, and which would not scale to a kappa table), everything
analytical goes through this adapter.

Three behaviours worth stating, because each one is a decision rather than a
default:

* **NaN renders as an em dash, not "nan".** A kappa that could not be computed is
  a real state in this tool (insufficient support), and "nan" in a results table
  reads like a bug to a reader who is about to quote the number.
* **Floats are formatted, not repr'd.** `0.6234000000000001` is noise.
  Per-column precision is available for the columns where it matters.
* **Sorting is on the underlying values**, not the display strings, so a kappa
  column sorts numerically and a "reliable" column groups correctly.
"""

from __future__ import annotations

import math
from typing import Any, Dict, Optional

import pandas as pd
from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt

#: What an unrepresentable number shows as. See the module docstring.
NA_DISPLAY = "—"


class DataFrameModel(QAbstractTableModel):
    """Read-only table model over a DataFrame.

    `precision` maps column name -> decimal places; anything not listed uses
    `default_precision`. `align_right` columns are numeric-aligned.
    """

    def __init__(
        self,
        frame: Optional[pd.DataFrame] = None,
        *,
        precision: Optional[Dict[str, int]] = None,
        default_precision: int = 3,
        header_labels: Optional[Dict[str, str]] = None,
        parent: Optional[Any] = None,
    ) -> None:
        super().__init__(parent)
        self._frame = frame if frame is not None else pd.DataFrame()
        self._precision = dict(precision or {})
        self._default_precision = default_precision
        self._header_labels = dict(header_labels or {})

    def set_header_labels(self, labels: Dict[str, str]) -> None:
        """Override displayed column headers, keyed by real column name.

        Needed because a DataFrame's column names are the *engine's* vocabulary,
        which is not always the reader's. `analysis.agreement.per_code_kappa`
        names its two raters `human` and `model` — accurate for the human-vs-AI
        case it was written for, and actively misleading when the comparison is
        two people. Renaming here keeps the engine untouched.
        """
        self._header_labels = dict(labels or {})
        if len(self._frame.columns):
            self.headerDataChanged.emit(
                Qt.Orientation.Horizontal, 0, len(self._frame.columns) - 1)

    # -- population ----------------------------------------------------------
    def set_frame(self, frame: pd.DataFrame) -> None:
        self.beginResetModel()
        self._frame = frame if frame is not None else pd.DataFrame()
        self.endResetModel()

    @property
    def frame(self) -> pd.DataFrame:
        return self._frame

    def value_at(self, row: int, column: int) -> Any:
        """The underlying (unformatted) value — for drill-back lookups."""
        if 0 <= row < len(self._frame) and 0 <= column < len(self._frame.columns):
            return self._frame.iat[row, column]
        return None

    def row_dict(self, row: int) -> Dict[str, Any]:
        """A whole row as a dict, keyed by column name."""
        if not (0 <= row < len(self._frame)):
            return {}
        return {str(col): self._frame.iat[row, i]
                for i, col in enumerate(self._frame.columns)}

    def column_index(self, name: str) -> int:
        """Position of a named column, or -1."""
        cols = [str(c) for c in self._frame.columns]
        return cols.index(name) if name in cols else -1

    # -- QAbstractTableModel -------------------------------------------------
    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: D102
        return 0 if parent.isValid() else len(self._frame)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: D102
        return 0 if parent.isValid() else len(self._frame.columns)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):  # noqa: D102
        if not index.isValid():
            return None
        value = self._frame.iat[index.row(), index.column()]

        if role == Qt.ItemDataRole.UserRole:
            return value          # raw, for callers that want the real object
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            return self._format(value, str(self._frame.columns[index.column()]))
        if role == Qt.ItemDataRole.TextAlignmentRole:
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            return int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        return None

    def headerData(self, section: int, orientation: Qt.Orientation,  # noqa: D102
                   role: int = Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            if 0 <= section < len(self._frame.columns):
                name = str(self._frame.columns[section])
                return self._header_labels.get(name, name.replace("_", " "))
            return None
        # Row headers carry the index, which matters for crosstabs (the index is
        # the code name) and is noise for a plain results table with a RangeIndex.
        if isinstance(self._frame.index, pd.RangeIndex):
            return None
        if 0 <= section < len(self._frame.index):
            return str(self._frame.index[section])
        return None

    def sort(self, column: int, order: Qt.SortOrder = Qt.SortOrder.AscendingOrder) -> None:  # noqa: D102
        if not (0 <= column < len(self._frame.columns)):
            return
        self.beginResetModel()
        self._frame = self._frame.sort_values(
            self._frame.columns[column],
            ascending=(order == Qt.SortOrder.AscendingOrder),
            kind="mergesort",          # stable: equal rows keep their order
            na_position="last",
        )
        self.endResetModel()

    # -- formatting ----------------------------------------------------------
    def _format(self, value: Any, column: str) -> str:
        if value is None:
            return NA_DISPLAY
        # pandas hands back numpy scalars, and `numpy.bool_` is NOT a subclass of
        # Python `bool` — so an isinstance check alone would render the kappa
        # table's `reliable` column as "True"/"False" instead of "yes"/"no", and
        # numpy floats would miss the NaN handling below.
        if hasattr(value, "item") and not isinstance(value, (list, tuple, set)):
            try:
                value = value.item()
            except (AttributeError, ValueError):
                pass
        if isinstance(value, bool):
            return "yes" if value else "no"
        if isinstance(value, float):
            if math.isnan(value):
                return NA_DISPLAY
            places = self._precision.get(column, self._default_precision)
            return f"{value:.{places}f}"
        if isinstance(value, (list, tuple, set)):
            return ", ".join(str(v) for v in value)
        text = str(value)
        return NA_DISPLAY if text in ("nan", "NaT", "None", "") else text
