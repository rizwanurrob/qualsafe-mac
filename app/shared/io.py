"""
Loading data files and managing working files on disk.

Extracted from the former monolithic `streamlit_app.py` (v4, Phase 0.1).
Per `app/__init__`, this module imports only from `core/`, `analysis/`,
`exports/`, `app.shared`, and Streamlit — never from `streamlit_app`.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List
import pandas as pd
from typing import Tuple
import streamlit as st

from app.shared.constants import SESSION_INPUT_DIR, STREAMLIT_OUTPUT_DIR


def _read_sav(path_or_buffer) -> pd.DataFrame:
    """SPSS .sav via the optional pyreadstat dependency (v3.8.2, item 8.11)."""
    try:
        import pyreadstat  # noqa: F401
    except ImportError as exc:
        raise ValueError(
            "SPSS .sav files need the optional 'pyreadstat' package. Install it "
            "with:  pip install pyreadstat   (or export the file as CSV from SPSS)."
        ) from exc
    import pyreadstat

    df, _meta = pyreadstat.read_sav(str(path_or_buffer))
    return df


def load_uploaded_file(uploaded_file: Any) -> pd.DataFrame:
    """Load user-uploaded file into DataFrame."""
    return load_uploaded_file_with_note(uploaded_file)[0]


def load_uploaded_file_with_note(uploaded_file: Any) -> Tuple[pd.DataFrame, str]:
    """Load an upload, and anything the analyst should be told about it.

    An uploaded CSV is the case most likely to have come straight out of Excel,
    so it is the path that needs the encoding fallback most — and the one a
    path-based helper could not serve, because an upload is a buffer with no
    filename on disk.
    """
    from core.encodings import read_csv_bytes

    suffix = Path(uploaded_file.name).suffix.lower()
    if suffix == ".csv":
        found = read_csv_bytes(_uploaded_bytes(uploaded_file))
        return found.frame, found.note()
    return _load_uploaded_other(uploaded_file, suffix), ""


def _uploaded_bytes(uploaded_file: Any) -> bytes:
    """The upload's bytes, however the framework chose to hand them over."""
    if hasattr(uploaded_file, "getvalue"):
        return uploaded_file.getvalue()
    if hasattr(uploaded_file, "seek"):
        uploaded_file.seek(0)
    return uploaded_file.read()


def _load_uploaded_other(uploaded_file: Any, suffix: str) -> pd.DataFrame:
    """Everything except CSV, which its caller has already handled."""
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(uploaded_file)
    if suffix == ".json":
        return pd.read_json(uploaded_file)
    if suffix == ".sav":
        # pyreadstat needs a real file path; buffer -> temp file.
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".sav", delete=False) as tmp:
            tmp.write(uploaded_file.getvalue())
            tmp_path = tmp.name
        try:
            return _read_sav(tmp_path)
        finally:
            Path(tmp_path).unlink(missing_ok=True)
    raise ValueError("Unsupported file type. Upload CSV, Excel, JSON, or SPSS .sav.")


def load_file_from_path(path: Path) -> pd.DataFrame:
    """Load a local file from path into DataFrame.

    CSV and JSON go through `core.encodings`, which falls back past UTF-8 and
    records what it did. `read_with_encoding_note` is the variant that returns
    the note for display; this one keeps the plain-frame signature its callers
    expect.
    """
    return read_with_encoding_note(path)[0]


def read_with_encoding_note(path: Path) -> Tuple[pd.DataFrame, str]:
    """Load a file, and return anything the analyst should be told about it.

    The note is non-empty only when the file was not UTF-8. Excel on Windows
    writes cp1252 unless the user chooses "CSV UTF-8", and reading that as UTF-8
    raises on the first curly apostrophe -- which free-text survey answers are
    full of, because Word and Excel insert them automatically.
    """
    from core.encodings import read_csv, read_json

    suffix = path.suffix.lower()
    if suffix == ".csv":
        found = read_csv(path)
        return found.frame, found.note()
    if suffix == ".json":
        found = read_json(path)
        return found.frame, found.note()
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(path), ""
    if suffix == ".sav":
        return _read_sav(path), ""
    raise ValueError(f"Unsupported file type: {suffix}")


def postprocess_loaded_df(df: pd.DataFrame) -> pd.DataFrame:
    """Fixups applied to every freshly loaded dataset (v3.8.2).

    Currently: strip Qualtrics metadata rows (question-text + ImportId rows that
    would otherwise be coded as responses), with a visible notice. No-op on
    normal files.
    """
    from core.ingest import strip_qualtrics_metadata

    stripped, n_removed = strip_qualtrics_metadata(df)
    if n_removed:
        st.info(f"Qualtrics export detected — removed {n_removed} metadata row(s) "
                f"(question text / ImportId) that are not responses.")
    return stripped


def list_supported_files_in_folder(folder: Path) -> List[Path]:
    """List supported data files in a folder (non-recursive)."""
    if not folder.exists() or not folder.is_dir():
        return []
    supported = []
    for p in sorted(folder.iterdir()):
        if p.is_file() and p.suffix.lower() in {".csv", ".xlsx", ".xls", ".json", ".sav"}:
            supported.append(p)
    return supported


def save_df_for_pipeline(df: pd.DataFrame, source_name: str, target_dir: Path) -> Path:
    """Write the working frame where the run that consumes it will live.

    The pipeline reads its input from a file path, so the in-memory frame (which
    may be reshaped, filtered, or masked relative to the uploaded file) has to be
    snapshotted to disk first.

    That snapshot used to accumulate forever in a global `data/session_inputs/`
    folder that nothing ever cleaned up and no part of the UI mentioned — a
    growing pile of copies of the analyst's data, invisible to the person
    responsible for it. Writing it into the run's own directory instead means it
    lives and dies with the outputs it produced, it is visible next to them, and
    the run manifest's `input.file` pointer stays valid for the audit trail.

    The filename is stable (not timestamped): the run directory is already
    unique, and for the iterative workflow the snapshot is regenerated from
    current data on every click, so a timestamp would only pile up copies.
    """
    target_dir.mkdir(parents=True, exist_ok=True)
    out_path = target_dir / f"{source_name}.csv"
    df.to_csv(out_path, index=False)
    return out_path


def legacy_session_input_files() -> List[Path]:
    """Input snapshots left behind by versions <= 3.1, which wrote them globally."""
    if not SESSION_INPUT_DIR.exists():
        return []
    return sorted(p for p in SESSION_INPUT_DIR.glob("*.csv") if p.is_file())


def delete_paths(paths: List[Path]) -> Dict[str, List[str]]:
    """Delete files, reporting per-file failures instead of dying on the first one.

    Streamlit may still hold an open handle from a `pd.read_csv` on Windows, where
    that makes the unlink fail. One locked file must not abort the purge or
    surface as a stack trace.
    """
    deleted: List[str] = []
    failed: List[str] = []
    for p in paths:
        try:
            p.unlink()
            deleted.append(p.name)
        except Exception as exc:  # noqa: BLE001
            failed.append(f"{p.name}: {exc}")
    return {"deleted": deleted, "failed": failed}


def describe_working_files() -> pd.DataFrame:
    """Inventory the data copies this app has written to disk, for the UI panel."""
    rows: List[Dict[str, Any]] = []
    for path in legacy_session_input_files():
        stat = path.stat()
        rows.append(
            {
                "file": str(path),
                "location": "data/session_inputs (legacy)",
                "size_kb": round(stat.st_size / 1024, 1),
                "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
            }
        )
    if STREAMLIT_OUTPUT_DIR.exists():
        for path in sorted(STREAMLIT_OUTPUT_DIR.glob("run_*/*.csv")):
            stat = path.stat()
            rows.append(
                {
                    "file": str(path),
                    "location": f"output_streamlit/{path.parent.name}",
                    "size_kb": round(stat.st_size / 1024, 1),
                    "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
                }
            )
    return pd.DataFrame(rows)
