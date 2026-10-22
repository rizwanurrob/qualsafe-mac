#!/usr/bin/env python
"""
Check that this machine can actually run QualSafe.

Written for handing the tool to colleagues: when something is wrong on someone
else's laptop, the failure usually surfaces deep inside a run as an opaque
traceback. This checks the things that actually break — Python version, missing
libraries, absent models, an unreadable project store — and says which one it is,
in a sentence, before any real work is attempted.

    python tools/verify_install.py

Exit code 0 means ready to use; 1 means something below needs attention. Touches
the network only if you pass --check-models (and even then only to read the local
cache — it downloads nothing).
"""

from __future__ import annotations

import argparse
import importlib
import platform
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

OK, WARN, FAIL = "  OK  ", " WARN ", " FAIL "

# (import name, human name, is it required to run at all?)
LIBRARIES = [
    ("pandas", "pandas", True),
    ("numpy", "numpy", True),
    ("streamlit", "Streamlit", True),
    ("sklearn", "scikit-learn", True),
    ("yaml", "PyYAML", True),
    ("altair", "Altair", True),
    ("docx", "python-docx (Word export)", True),
    ("openpyxl", "openpyxl (Excel export)", True),
    ("xlrd", "xlrd (legacy .xls files in the chart builder)", False),
    ("pdfplumber", "pdfplumber (PDF documents)", True),
    ("vl_convert", "vl-convert-python (chart images)", False),
    ("torch", "PyTorch (the analysis engine)", False),
    ("transformers", "Transformers", False),
    ("sentence_transformers", "sentence-transformers", False),
    ("pyreadstat", "pyreadstat (SPSS .sav files)", False),
]


def _line(status: str, label: str, detail: str = "") -> None:
    print(f"[{status}] {label}" + (f"\n         {detail}" if detail else ""))


def check_python() -> bool:
    major, minor = sys.version_info[:2]
    version = f"{major}.{minor}.{sys.version_info[2]}"
    if (major, minor) < (3, 9):
        _line(FAIL, f"Python {version} is too old.",
              "Install Python 3.12 and re-run the installer.")
        return False
    if (major, minor) > (3, 12):
        _line(FAIL, f"Python {version} is too new for the analysis libraries.",
              "NumPy 1.x and PyTorch have no builds for 3.13+, so pip compiles a "
              "broken NumPy. Install Python 3.12 and re-run the installer.")
        return False
    _line(OK, f"Python {version} on {platform.system()} {platform.release()}")
    return True


def check_libraries() -> bool:
    ready = True
    missing_optional = []
    for module, label, required in LIBRARIES:
        try:
            importlib.import_module(module)
        except Exception:  # noqa: BLE001 - a broken install raises more than ImportError
            if required:
                _line(FAIL, f"{label} is missing or broken.",
                      "Re-run the installer (install_windows.bat / install_mac_linux.sh).")
                ready = False
            else:
                missing_optional.append(label)
        else:
            if required:
                _line(OK, label)
    for label in missing_optional:
        _line(WARN, f"{label} not installed — the features that need it are unavailable.")
    return ready


def check_store() -> bool:
    """Create, write, and read a throwaway project — the whole storage path."""
    try:
        from core.documents import add_document
        from core.project import SCHEMA_VERSION, Project

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "verify.qnw"
            with Project.create(path) as proj:
                sid = add_document(proj, "verify", "the cost of housing")
                assert proj.count_sources() == 1
                fts = proj.fts_available()
                if fts:
                    assert proj.fts_match_source_ids("housing") == [sid]
        _line(OK, f"Project store works (schema v{SCHEMA_VERSION}"
                  + (", full-text search enabled)" if fts else ", no FTS5 — search will scan)"))
        if not fts:
            _line(WARN, "This SQLite has no FTS5; search still works but scans the text.")
        return True
    except Exception as exc:  # noqa: BLE001
        _line(FAIL, "Could not create a project file.", str(exc))
        return False


def check_models(verbose: bool) -> bool:
    """Report model cache status. Never downloads."""
    try:
        from core.offline import human_size, model_cache_status
        from core.model_manager import DEFAULT_MODELS

        rows = model_cache_status(sorted(set(DEFAULT_MODELS.values())))
    except Exception as exc:  # noqa: BLE001
        _line(WARN, "Could not read the model cache.", str(exc))
        return True

    missing = [r for r in rows if r["cached"] is False]
    for row in rows:
        if verbose or row["cached"] is not True:
            status = OK if row["cached"] else WARN
            size = human_size(float(row["size_bytes"])) if row["size_bytes"] else ""
            _line(status, f"{row['model']} {size}".strip())
    if missing:
        _line(WARN, f"{len(missing)} model(s) not downloaded — analysis will stop until "
                    f"they are.",
              "Fix from the app's Model Manager page, or: "
              "python tools/download_models.py")
    else:
        _line(OK, "All default models are cached; analysis can run fully offline.")
    return True


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Check this machine can run QualSafe.")
    parser.add_argument("--check-models", action="store_true",
                        help="Also report the model cache (reads locally; no download).")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    print("QualSafe — installation check")
    print("-" * 62)
    results = [check_python(), check_libraries(), check_store()]
    if args.check_models:
        results.append(check_models(args.verbose))
    print("-" * 62)

    if all(results):
        print("Ready. Start the app with run_app_windows.bat "
              "(or bash run_app_mac_linux.sh).")
        return 0
    print("Not ready — see the FAIL line(s) above.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
