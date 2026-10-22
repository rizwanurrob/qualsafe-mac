"""
Data loader: a CSV or Excel file becomes a `LoadedTable`, and nothing is written
back. The frame is a private copy; every later stage returns new objects.

- **CSV**: encoding through `core.encodings` (utf-8, cp1252, latin-1, with a
  report of what happened), delimiter sniffed from the first few KB. Everything
  is read as *text* with pandas' NA guessing switched off, so ``NA``/``None``/
  ``null`` reach the missing-value rules intact instead of being silently turned
  into NaN, and an id like ``007`` stays ``007``.
- **Excel**: every sheet is listed; one is loaded at a time. Cells keep their
  native types (dates stay dates) and empty cells become the empty string so
  "blank" is one thing whichever file type it came from.
- **.xls** needs the optional ``xlrd`` package; without it the error says so.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Union

import pandas as pd

from core import encodings

CSV_SUFFIXES = {".csv", ".tsv", ".txt"}
EXCEL_SUFFIXES = {".xlsx", ".xlsm", ".xls"}
SUPPORTED_SUFFIXES = CSV_SUFFIXES | EXCEL_SUFFIXES

#: Delimiters offered to the sniffer, most common first.
_DELIMITERS = ",;\t|"
_SNIFF_CHARS = 16384


class UnsupportedFileError(ValueError):
    """A file type this loader does not read. The message says which are."""


@dataclass
class LoadedTable:
    """A dataset as loaded, and how it was read."""

    name: str
    frame: pd.DataFrame
    kind: str                                   # "csv" | "excel"
    sheet: Optional[str] = None
    sheets: List[str] = field(default_factory=list)
    encoding: Optional[str] = None
    delimiter: Optional[str] = None
    notes: List[str] = field(default_factory=list)

    @property
    def n_rows(self) -> int:
        return int(len(self.frame))

    @property
    def n_cols(self) -> int:
        return int(len(self.frame.columns))

    def structure(self) -> dict:
        """What a saved chart needs to recognise "the same data" later."""
        return {"name": self.name, "sheet": self.sheet,
                "columns": [str(c) for c in self.frame.columns]}


def sniff_delimiter(data: bytes) -> str:
    """The delimiter of a delimited text file, or a comma when unsure.

    Decoded as latin-1 for sniffing only: delimiters are ASCII, and latin-1
    cannot fail, so the sniff never depends on the (separately handled) encoding.
    """
    sample = data[:_SNIFF_CHARS].decode("latin-1", errors="replace")
    try:
        return csv.Sniffer().sniff(sample, delimiters=_DELIMITERS).delimiter
    except csv.Error:
        first = sample.splitlines()[0] if sample.splitlines() else ""
        counts = {d: first.count(d) for d in _DELIMITERS}
        best = max(counts, key=counts.get)
        return best if counts[best] else ","


def _dedupe_headers(frame: pd.DataFrame, notes: List[str]) -> pd.DataFrame:
    """Give repeated or blank headers distinct names, and say so."""
    seen: dict = {}
    names = []
    changed = False
    for i, raw in enumerate(frame.columns):
        name = str(raw).strip() or f"Column {i + 1}"
        if name.lower().startswith("unnamed:"):
            name = f"Column {i + 1}"
        if name in seen:
            seen[name] += 1
            name = f"{name} ({seen[name]})"
            changed = True
        else:
            seen[name] = 1
        names.append(name)
    if changed:
        notes.append("Some column headers were repeated; later copies were "
                     "numbered, e.g. 'Q1 (2)'. The file itself is unchanged.")
    out = frame.copy()
    out.columns = names
    return out


def _read_bytes(data: bytes, name: str) -> bytes:
    if not data:
        raise ValueError(f"{name} is empty.")
    return data


def load_csv_bytes(data: bytes, name: str = "data.csv", *,
                   delimiter: Optional[str] = None) -> LoadedTable:
    data = _read_bytes(data, name)
    sep = delimiter or sniff_delimiter(data)
    # header=None: pandas would rename repeated headers to "q.1" before we could
    # tell the analyst, so the header row is promoted here instead.
    read = encodings.read_csv_bytes(
        data, sep=sep, header=None, dtype=str, keep_default_na=False,
        na_filter=False, engine="python" if len(sep) > 1 else "c")
    notes: List[str] = []
    if read.note():
        notes.append(read.note())
    raw = read.frame
    frame = raw.iloc[1:].reset_index(drop=True)
    frame.columns = list(raw.iloc[0])
    return LoadedTable(name=name, frame=_dedupe_headers(frame, notes),
                       kind="csv", encoding=read.encoding, delimiter=sep,
                       notes=notes)


def list_sheets(data: bytes, name: str = "workbook.xlsx") -> List[str]:
    """Sheet names of an Excel workbook, in workbook order."""
    return list(_excel_file(data, name).sheet_names)


def _excel_file(data: bytes, name: str) -> pd.ExcelFile:
    suffix = Path(name).suffix.lower()
    engine = "xlrd" if suffix == ".xls" else "openpyxl"
    try:
        return pd.ExcelFile(io.BytesIO(_read_bytes(data, name)), engine=engine)
    except ImportError as error:
        raise ImportError(
            "Reading .xls files needs the optional 'xlrd' package "
            "(pip install xlrd). Saving the workbook as .xlsx also works."
        ) from error


def load_excel_bytes(data: bytes, name: str = "data.xlsx", *,
                     sheet: Union[str, int, None] = None) -> LoadedTable:
    book = _excel_file(data, name)
    sheets = list(book.sheet_names)
    if sheet is None:
        chosen = sheets[0]
    elif isinstance(sheet, int):
        chosen = sheets[sheet]
    elif sheet in sheets:
        chosen = sheet
    else:
        raise ValueError(f"Sheet {sheet!r} is not in {name}. "
                         f"Sheets: {', '.join(sheets)}.")
    frame = book.parse(chosen, dtype=object, na_filter=False)
    notes: List[str] = []
    return LoadedTable(name=name, frame=_dedupe_headers(frame, notes),
                       kind="excel", sheet=chosen, sheets=sheets, notes=notes)


def load_bytes(data: bytes, name: str, *, sheet: Union[str, int, None] = None,
               delimiter: Optional[str] = None) -> LoadedTable:
    """Load an upload by file name. The one entry point the UI calls."""
    suffix = Path(name).suffix.lower()
    if suffix in EXCEL_SUFFIXES:
        return load_excel_bytes(data, name, sheet=sheet)
    if suffix in CSV_SUFFIXES or not suffix:
        return load_csv_bytes(data, name, delimiter=delimiter)
    raise UnsupportedFileError(
        f"{name}: {suffix} files are not supported. Use CSV, TSV, XLSX or XLS.")


def load_path(path: Union[str, Path], *, sheet: Union[str, int, None] = None,
              delimiter: Optional[str] = None) -> LoadedTable:
    p = Path(path)
    return load_bytes(p.read_bytes(), p.name, sheet=sheet, delimiter=delimiter)
