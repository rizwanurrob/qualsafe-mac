"""
Saved charts and custom themes: the two things the Chart Builder remembers.

Both are plain JSON in a per-user folder, so an analyst can read them, back them
up, or email one to a colleague. Neither UI does any of this itself.

What is stored, and why it is safe to store
-------------------------------------------
- **Custom themes** are colours and a name. Preferences, nothing more; they are
  saved as soon as they are made.
- **A saved chart** is a `ChartConfig` (fields, filters, recode, colours, labels,
  size) plus the *structure* of the file it was made for (name, sheet, column
  names). It is written only when the analyst presses "Save chart", like an
  export, and never contains a data value from a row. It does hold the category
  labels the analyst renamed or excluded (answer options such as "Very
  important"), which is the point: it is what makes the chart reproducible.

The uploaded data is never stored here or anywhere else.

Reproducibility
---------------
Opening the same *structure* again gives the same chart. Opening a different file
never guesses: `fit_to_frame` drops the choices that name a column the file does
not have and says so in a sentence for each, and reports recode entries that name
a category the data no longer contains. Saving is strict; loading is forgiving
(unknown keys ignored, an older version still opens) so an old chart is not lost
to a newer program, and a chart from a newer version is refused with a reason
rather than half-read.

Saving under a name that already exists **replaces** it (compared without regard
to case), because a library of "Q4 belonging", "Q4 Belonging" and "q4 belonging
(2)" is a library nobody can use.
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd

from core.chartbuilder import recode_table
from core.chartbuilder.config import CONFIG_VERSION, ChartConfig
from core.chartbuilder.export import safe_stem
from core.chartbuilder.themes import BUILTIN_THEMES, Theme

CHART_FORMAT = "qualsafe-chart"
CHART_FILE_VERSION = 1
THEME_FORMAT = "qualsafe-themes"
THEME_FILE_VERSION = 1
CHART_SUFFIX = ".qchart.json"
APP_FOLDER = "QualSafe"


class StoreError(ValueError):
    """A saved chart or theme could not be read or written. Written for the analyst."""


# ── where things live ─────────────────────────────────────────────────────────

def data_dir(root: Optional[Path] = None) -> Path:
    """The Chart Builder's per-user folder.

    `QNW_SETTINGS_DIR` (the override the rest of the app and its tests use) wins;
    otherwise the platform's user-data location, which survives an uninstall and a
    reinstall of the program: `%APPDATA%` on Windows, `~/Library/Application
    Support` on macOS, `$XDG_DATA_HOME` or `~/.local/share` elsewhere.
    """
    if root is not None:
        return Path(root)
    override = os.environ.get("QNW_SETTINGS_DIR", "").strip()
    if override:
        return Path(override) / "chartbuilder"
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / APP_FOLDER / "chartbuilder"


def charts_dir(root: Optional[Path] = None) -> Path:
    return data_dir(root) / "charts"


def themes_path(root: Optional[Path] = None) -> Path:
    return data_dir(root) / "themes.json"


def _write_atomic(path: Path, text: str) -> None:
    """Write via a temp file and rename, so a crash never leaves half a file."""
    tmp = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        with os.fdopen(handle, "w", encoding="utf-8") as out:
            out.write(text)
        os.replace(tmp, path)
    except OSError as error:
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass
        raise StoreError(f"Could not save to {path.parent}: {error.strerror or error}") from error


# ── saved charts ──────────────────────────────────────────────────────────────

@dataclass
class SavedChart:
    name: str
    config: ChartConfig
    dataset: Dict[str, object] = field(default_factory=dict)
    saved_at: str = ""
    note: str = ""
    path: Optional[Path] = None

    @property
    def chart_type(self) -> str:
        return self.config.chart_type

    @property
    def dataset_name(self) -> str:
        return str(self.dataset.get("name", ""))


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def chart_to_text(saved: SavedChart) -> str:
    return json.dumps({
        "format": CHART_FORMAT, "version": CHART_FILE_VERSION,
        "config_version": CONFIG_VERSION, "name": saved.name,
        "saved_at": saved.saved_at or _now(), "note": saved.note,
        "dataset": saved.dataset, "config": saved.config.to_dict()},
        indent=2, ensure_ascii=False)


def chart_from_text(text: str, path: Optional[Path] = None) -> SavedChart:
    """Read a saved chart. Raises `StoreError` with a sentence if it is not one."""
    try:
        data = json.loads(text)
    except (ValueError, TypeError) as error:
        raise StoreError("That is not a chart file (it is not valid JSON).") from error
    if not isinstance(data, dict) or data.get("format") != CHART_FORMAT:
        raise StoreError("That file is not a QualSafe chart.")
    version = data.get("version", 1)
    if not isinstance(version, int) or version > CHART_FILE_VERSION:
        raise StoreError("This chart was saved by a newer version of the program. "
                         "Update QualSafe to open it.")
    config = ChartConfig.from_dict(data.get("config"))
    dataset = data.get("dataset") if isinstance(data.get("dataset"), dict) else {}
    return SavedChart(name=str(data.get("name") or (path.stem if path else "Chart")),
                      config=config, dataset=dataset, saved_at=str(data.get("saved_at", "")),
                      note=str(data.get("note", "")), path=path)


def chart_to_bytes(saved: SavedChart) -> bytes:
    return chart_to_text(saved).encode("utf-8")


def chart_from_bytes(data: bytes) -> SavedChart:
    try:
        return chart_from_text(data.decode("utf-8-sig"))
    except UnicodeDecodeError as error:
        raise StoreError("That is not a chart file (it is not text).") from error


def _find(name: str, root: Optional[Path]) -> Optional[Path]:
    wanted = name.strip().casefold()
    folder = charts_dir(root)
    if not folder.exists():
        return None
    for path in sorted(folder.glob("*" + CHART_SUFFIX)):
        try:
            if chart_from_text(path.read_text(encoding="utf-8-sig"), path).name.strip().casefold() == wanted:
                return path
        except (OSError, StoreError):
            continue
    return None


def save_chart(name: str, cfg: ChartConfig, dataset: Optional[Dict[str, object]] = None, *,
               note: str = "", root: Optional[Path] = None) -> Path:
    """Save (or replace, by name) a chart. Returns the file written."""
    name = (name or "").strip()
    if not name:
        raise StoreError("Give the chart a name to save it.")
    existing = _find(name, root)
    if existing is not None:
        path = existing
    else:
        stem = safe_stem(name, max_chars=60)
        path = charts_dir(root) / (stem + CHART_SUFFIX)
        n = 2
        while path.exists():                   # two names that slug alike are still two charts
            path = charts_dir(root) / f"{stem}-{n}{CHART_SUFFIX}"
            n += 1
    saved = SavedChart(name=name, config=cfg.copy(), dataset=dict(dataset or cfg.dataset),
                       saved_at=_now(), note=note)
    _write_atomic(path, chart_to_text(saved))
    return path


@dataclass
class ChartInfo:
    name: str
    saved_at: str
    dataset_name: str
    chart_type: str
    path: Path


def list_charts(root: Optional[Path] = None) -> List[ChartInfo]:
    """Saved charts, newest first. A file that cannot be read is skipped, not fatal."""
    folder = charts_dir(root)
    out: List[ChartInfo] = []
    if not folder.exists():
        return out
    for path in folder.glob("*" + CHART_SUFFIX):
        try:
            saved = chart_from_text(path.read_text(encoding="utf-8-sig"), path)
        except (OSError, StoreError):
            continue
        out.append(ChartInfo(saved.name, saved.saved_at, saved.dataset_name,
                             saved.chart_type, path))
    return sorted(out, key=lambda c: (c.saved_at, c.name), reverse=True)


def load_chart(name: str, root: Optional[Path] = None) -> SavedChart:
    path = _find(name, root)
    if path is None:
        raise StoreError(f"There is no saved chart called '{name}'.")
    try:
        return chart_from_text(path.read_text(encoding="utf-8-sig"), path)
    except OSError as error:
        raise StoreError(f"Could not read '{name}': {error.strerror or error}") from error


def delete_chart(name: str, root: Optional[Path] = None) -> bool:
    path = _find(name, root)
    if path is None:
        return False
    path.unlink()
    return True


# ── fitting a saved chart to the file that is open ────────────────────────────

def _referenced_columns(cfg: ChartConfig) -> List[str]:
    cols = [cfg.column, *cfg.columns, *cfg.group_by, cfg.value_field,
            *[f.column for f in cfg.filters]]
    return list(dict.fromkeys(c for c in cols if c))


def fit_to_frame(cfg: ChartConfig, frame: pd.DataFrame) -> Tuple[ChartConfig, List[str]]:
    """The saved config as it applies to `frame`, and a sentence per difference.

    Choices naming a column the file does not have are dropped (the chart is then
    incomplete and says what is missing); nothing else is changed. Recode entries
    that name a category the data does not contain are reported, not removed: they
    do no harm, and removing them would lose the analyst's work if the category
    comes back in next year's file.
    """
    have = {str(c) for c in frame.columns}
    out = cfg.copy()
    notes: List[str] = []
    missing = [c for c in _referenced_columns(cfg) if c not in have]
    if missing:
        notes.append("This chart uses field(s) that are not in this file: "
                     + ", ".join(f"'{c}'" for c in missing)
                     + ". Those choices were cleared; pick them again.")
    out.column = out.column if out.column in have else ""
    out.columns = [c for c in out.columns if c in have]
    out.group_by = [c for c in out.group_by if c in have]
    out.value_field = out.value_field if out.value_field in have else ""
    out.filters = [f for f in out.filters if f.column in have]
    if any(f.column not in have for f in cfg.filters):
        notes.append("Filters on missing fields were removed.")
    saved_cols = cfg.dataset.get("columns") if isinstance(cfg.dataset, dict) else None
    if saved_cols and not missing and set(saved_cols) != have:
        added = sorted(have - set(saved_cols))
        if added:
            notes.append(f"This file has {len(added)} field(s) the chart was not made "
                         "with. That does not change the chart.")
    if out.column or out.columns:
        present = set(recode_table.source_categories(frame, out)["Category"])
        rc = out.recode
        named = set(rc.exclude) | set(rc.rename) | {m for merge in rc.merges for m in merge.members}
        stale = sorted(named - present)
        if stale and (present or named):
            notes.append(f"{len(stale)} relabel/combine/exclude choice(s) name categories this "
                         "data does not contain: " + ", ".join(f"'{s}'" for s in stale[:5])
                         + (" and others" if len(stale) > 5 else "") + ". They have no effect here.")
    out.dataset = {"name": cfg.dataset.get("name", "") if isinstance(cfg.dataset, dict) else "",
                   "sheet": cfg.dataset.get("sheet") if isinstance(cfg.dataset, dict) else None,
                   "columns": [str(c) for c in frame.columns]}
    return out, notes


# ── custom themes ─────────────────────────────────────────────────────────────

def _theme_taken(name: str, custom: Dict[str, Theme]) -> Optional[str]:
    wanted = name.strip().casefold()
    for existing in list(BUILTIN_THEMES) + list(custom):
        if existing.casefold() == wanted:
            return existing
    return None


def load_themes(root: Optional[Path] = None) -> Dict[str, Theme]:
    """The saved custom themes by name. A damaged file is set aside (never lost,
    never fatal) and treated as empty."""
    path = themes_path(root)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        if data.get("format") != THEME_FORMAT:
            raise ValueError("not a theme file")
        themes: Dict[str, Theme] = {}
        for entry in data.get("themes", []):
            try:
                theme = Theme.from_dict(entry)
            except (ValueError, TypeError, KeyError):
                continue                      # one bad entry must not hide the others
            themes[theme.name] = theme
        return themes
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        try:
            path.replace(path.with_suffix(".json.bad"))
        except OSError:
            pass
        return {}


def _write_themes(themes: Dict[str, Theme], root: Optional[Path]) -> None:
    _write_atomic(themes_path(root), json.dumps(
        {"format": THEME_FORMAT, "version": THEME_FILE_VERSION,
         "themes": [t.to_dict() for t in themes.values()]}, indent=2))


def save_theme(theme: Theme, root: Optional[Path] = None) -> Dict[str, Theme]:
    """Save a custom theme, replacing one of the same name. Built-in names are
    refused (a custom "QualSafe default" would silently change the default)."""
    custom = load_themes(root)
    clash = _theme_taken(theme.name, {})
    if clash:
        raise StoreError(f"'{clash}' is a built-in theme. Choose another name.")
    for existing in list(custom):
        if existing.casefold() == theme.name.strip().casefold():
            del custom[existing]
    theme.name = theme.name.strip()
    theme.builtin = False
    custom[theme.name] = theme
    _write_themes(custom, root)
    return custom


def delete_theme(name: str, root: Optional[Path] = None) -> Dict[str, Theme]:
    custom = load_themes(root)
    if name in BUILTIN_THEMES:
        raise StoreError("Built-in themes cannot be deleted.")
    custom.pop(name, None)
    _write_themes(custom, root)
    return custom


def theme_to_bytes(theme: Theme) -> bytes:
    return json.dumps({"format": THEME_FORMAT, "version": THEME_FILE_VERSION,
                       "themes": [theme.to_dict()]}, indent=2).encode("utf-8")


def theme_from_bytes(data: bytes) -> Theme:
    """The first theme in a shared theme file."""
    try:
        payload = json.loads(data.decode("utf-8-sig"))
        if payload.get("format") != THEME_FORMAT:
            raise ValueError
        return Theme.from_dict(payload["themes"][0])
    except (ValueError, TypeError, KeyError, IndexError, AttributeError, UnicodeDecodeError) as error:
        raise StoreError("That is not a QualSafe theme file.") from error
