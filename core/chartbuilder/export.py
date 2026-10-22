"""
Export engine: chart images, summary tables, and safe file names.

Images come from `vl-convert` (offline, no browser). Figure sizes are in pixels
at 96 per inch, so a 16:9 preset of 1280 x 720 is a 13.33 x 7.5 inch slide: at
150 DPI it exports as 2000 x 1125 px and at 300 DPI as 4000 x 2250 px, and the
PNG records that DPI so Word and PowerPoint place it at the intended size.

File names are the part that bites on Windows. A survey question is often a
sentence, and a long question in a deep OneDrive folder overflows MAX_PATH (260)
and fails with an error that names neither the cause nor the fix. `safe_filename`
strips what Windows forbids, avoids reserved device names, and shortens the stem
so the *whole path* fits, appending a short hash when it had to cut so two long
names that share a prefix cannot collide.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import threading
import unicodedata
from typing import Any, Dict, Optional

import pandas as pd

from core.chartbuilder.aggregate import ChartData
from core.chartbuilder.config import ChartConfig

PIXELS_PER_INCH = 96
DPI_PRESETS = (72, 96, 150, 300, 600)
IMAGE_FORMATS = ("png", "svg", "pdf")

#: Windows MAX_PATH is 260 including the terminating NUL; leave headroom for
#: "-copy (2)" style suffixes an OS or sync client may add.
DEFAULT_MAX_PATH = 240
_MIN_STEM = 12
_RESERVED = {"CON", "PRN", "AUX", "NUL",
             *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
_FORBIDDEN = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


# ── file names ────────────────────────────────────────────────────────────────

def safe_stem(text: str, max_chars: int = 80) -> str:
    """A readable, Windows-legal file stem from any string."""
    text = unicodedata.normalize("NFKC", text or "").strip()
    text = _FORBIDDEN.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip(" .")
    text = re.sub(r"[\s_]+", "_", text).strip("_") or "chart"
    if text.split(".")[0].upper() in _RESERVED:
        text = f"_{text}"
    if len(text) > max_chars:
        digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]
        text = f"{text[:max_chars - 9].rstrip('_.')}-{digest}"
    return text


def safe_filename(name: str, ext: str, directory: Optional[str] = None, *,
                  max_path: int = DEFAULT_MAX_PATH) -> str:
    """`stem.ext` whose full path, joined to `directory`, is at most `max_path`.

    Raises ValueError if the directory alone leaves no room for a usable name,
    which is worth telling the analyst (save somewhere shallower) rather than
    truncating to nothing.
    """
    ext = "." + ext.lstrip(".").lower()
    room = max_path - len(ext)
    if directory:
        room -= len(os.path.abspath(directory)) + 1
    if room < _MIN_STEM:
        raise ValueError(
            "The folder path is too long to save a file in. Choose a folder "
            "closer to the drive root.")
    return safe_stem(name, max_chars=min(room, 120)) + ext


def chart_filename(cfg: ChartConfig, fmt: str, directory: Optional[str] = None,
                   *, suffix: str = "") -> str:
    """Default file name: the title, else the field, plus the chart type."""
    base = cfg.labels.title or cfg.column or (cfg.columns[0] if cfg.columns else "chart")
    stem = f"{base}_{cfg.chart_type}{('_' + suffix) if suffix else ''}"
    return safe_filename(stem, fmt, directory)


# ── images ────────────────────────────────────────────────────────────────────

def image_export_available() -> bool:
    try:
        import vl_convert  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


def _vlc():
    try:
        import vl_convert as vlc
    except Exception as error:  # noqa: BLE001
        raise RuntimeError(
            "Image export needs vl-convert-python (pip install "
            "vl-convert-python). The chart definition can still be saved.") from error
    return vlc


_WARMING: Dict[str, Any] = {"thread": None}
_WARM_LOCK = threading.Lock()
_WARM_SPEC = {"$schema": "https://vega.github.io/schema/vega-lite/v5.json",
              "data": {"values": [{"a": "x", "b": 1}]}, "mark": "bar",
              "encoding": {"x": {"field": "a", "type": "nominal"}, "y": {"field": "b", "type": "quantitative"}}}


def warm_renderer() -> Optional[threading.Thread]:
    """Start the image renderer in the background, once per process; return the thread (or None).

    The first image a process draws starts a JavaScript engine and loads fonts: about 6 s measured,
    about 11 s on the first chart in the app, against under 1 s after. Doing it while Home is on screen
    means the first chart is as quick as the next. The call releases the interpreter lock, so the page
    does not stall (measured: the main thread's worst pause was 0.01 s). Never raises: if the renderer
    is missing the chart screens already say so.
    """
    with _WARM_LOCK:
        if _WARMING["thread"] is not None:
            return None
        if not image_export_available():
            _WARMING["thread"] = False
            return None

        def run() -> None:
            try:
                _vlc().vegalite_to_png(json.dumps(_WARM_SPEC), scale=1)
            except Exception:  # noqa: BLE001 - a warm-up must never become an error
                return
            try:
                # then one real chart, through the same path the screen uses, so the modules and the
                # layered spec the screen draws are warm too
                from core.chartbuilder.build import build_data
                from core.chartbuilder.render import build_spec
                cfg = ChartConfig()
                cfg.column = "Q"
                data, theme = build_data(pd.DataFrame({"Q": ["a", "b", "a", "c", "a", "b"]}), cfg)
                render_image(build_spec(data, cfg, theme), "png", 96)
            except Exception:  # noqa: BLE001
                pass

        thread = threading.Thread(target=run, name="qualsafe-warm-renderer", daemon=True)
        _WARMING["thread"] = thread
        thread.start()
        return thread


def export_pixels(cfg: ChartConfig, dpi: int) -> tuple:
    from core.chartbuilder.render import figure_size
    w, h = figure_size(cfg)
    scale = dpi / PIXELS_PER_INCH
    return int(round(w * scale)), int(round(h * scale))


def render_image(spec: Dict[str, Any], fmt: str, dpi: int = 300) -> bytes:
    """The figure as PNG, SVG or PDF bytes. `dpi` matters for PNG only (SVG and
    PDF are vector)."""
    fmt = fmt.lower()
    if fmt not in IMAGE_FORMATS:
        raise ValueError(f"Unknown image format '{fmt}'. Use one of {IMAGE_FORMATS}.")
    vlc = _vlc()
    text = json.dumps(spec)
    if fmt == "png":
        # vl-convert's output is width * scale * ppi / 72 pixels. With ppi set to
        # the DPI (so the file records it) a scale of 72/96 gives width * dpi / 96.
        return vlc.vegalite_to_png(text, scale=72 / PIXELS_PER_INCH, ppi=dpi)
    if fmt == "svg":
        return vlc.vegalite_to_svg(text).encode("utf-8")
    return vlc.vegalite_to_pdf(text)


# ── tables ────────────────────────────────────────────────────────────────────

def summary_table(data: ChartData, cfg: ChartConfig, *, totals: bool = False,
                  valid_n: bool = True, missing_n: bool = False) -> pd.DataFrame:
    """The table behind the chart, in reader-friendly columns.

    Grouped charts include the grouping fields (one column each when the joined
    group label splits cleanly, otherwise a single "Group" column).
    """
    if data.kind == "numeric":
        return _numeric_table(data, cfg, valid_n=valid_n, missing_n=missing_n)
    t = data.table
    out = pd.DataFrame({"Response": t["category"]})
    key_cols: list = []
    fields = data.group_fields
    if fields:
        joined = t["group"].astype(str)
        parts = joined.str.split(" / ")
        if len(fields) > 1 and parts.map(len).eq(len(fields)).all():
            for i, name in enumerate(fields):
                out[name] = parts.map(lambda p, i=i: p[i])
                key_cols.append(name)
        else:
            name = " / ".join(fields)
            out[name] = joined
            key_cols.append(name)
    proportional = cfg.aggregation in ("percent", "count")
    if proportional:
        out["Count"] = pd.to_numeric(t["count"], errors="coerce").fillna(0).astype(int)
        # An empty table (a text column with no keywords) holds object columns.
        out["Percent"] = pd.to_numeric(t["percent"], errors="coerce").round(max(cfg.display.decimals, 1))
        if valid_n:
            out["Valid N"] = t["valid_n"]
    else:
        out[data.value_title] = t["value"].round(max(cfg.display.decimals, 2))
        out["N"] = t["count"].astype(int)
    if missing_n:
        out["Missing N"] = t["missing_n"]
    if totals and proportional:
        blocks = out.groupby(key_cols, sort=False) if key_cols else [(None, out)]
        rows = []
        for _, block in blocks:
            row = {c: "" for c in out.columns}
            row["Response"] = "Total"
            for k in key_cols:
                row[k] = block[k].iloc[0]
            row["Count"] = int(block["Count"].sum())
            row["Percent"] = round(float(block["Percent"].sum()), 1)
            if valid_n:
                row["Valid N"] = block["Valid N"].iloc[0]
            if missing_n:
                row["Missing N"] = block["Missing N"].iloc[0]
            rows.append(row)
        out = pd.concat([out, pd.DataFrame(rows)], ignore_index=True)
    return out


def _numeric_table(data: ChartData, cfg: ChartConfig, *, valid_n: bool,
                   missing_n: bool) -> pd.DataFrame:
    """The table behind a histogram, box plot, scatter, line or area chart."""
    t = data.table
    chart = data.notes.get("chart")
    group_name = " / ".join(data.group_fields)
    dec = max(cfg.display.decimals, 1)
    if chart == "histogram":
        out = pd.DataFrame({"Range": t["category"]})
        if group_name:
            out[group_name] = t["group"]
        out["Count"] = t["count"].astype(int)
        out["Percent"] = t["percent"].round(dec)
    elif chart == "box":
        out = pd.DataFrame({group_name or cfg.column: t["category"], "N": t["count"].astype(int),
                            "Min": t["min"], "25th percentile": t["q1"], "Median": t["median"],
                            "75th percentile": t["q3"], "Max": t["max"], "Mean": t["mean"].round(dec + 1),
                            "Values beyond the whiskers": t["n_outliers"].astype(int)})
    elif chart == "scatter":
        out = pd.DataFrame({cfg.column: t["x"], cfg.value_field: t["y"]})
        if group_name:
            out[group_name] = t["group"]
        return out
    else:
        out = pd.DataFrame({str(data.notes.get("x_title") or "Period"): t["category"]})
        if group_name:
            out[group_name] = t["group"]
        out[data.value_title] = t["value"].round(max(cfg.display.decimals, 2))
        out["Rows"] = t["count"].astype(int)
    if valid_n and chart in ("histogram",):
        out["Valid N"] = t["valid_n"]
    if missing_n and chart in ("histogram", "box"):
        out["Missing N"] = t["missing_n"]
    return out


def table_csv(frame: pd.DataFrame) -> bytes:
    """UTF-8 with a BOM, so Excel on Windows opens accents and curly quotes right."""
    return frame.to_csv(index=False).encode("utf-8-sig")


def table_tsv(frame: pd.DataFrame) -> str:
    """Tab-separated text for the clipboard; pastes into Excel and Word as cells."""
    return frame.to_csv(index=False, sep="\t")


def table_xlsx(frame: pd.DataFrame, data: ChartData, cfg: ChartConfig) -> bytes:
    """A workbook: the summary sheet, and a Notes sheet saying what it rests on."""
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as book:
        frame.to_excel(book, sheet_name="Summary", index=False)
        sheet = book.sheets["Summary"]
        for i, col in enumerate(frame.columns, start=1):
            width = max([len(str(col))] + [len(str(v)) for v in frame[col].head(200)])
            sheet.column_dimensions[sheet.cell(1, i).column_letter].width = min(width + 3, 60)
        notes = [("Title", cfg.labels.title), ("Subtitle", cfg.labels.subtitle),
                 ("Field", cfg.column or ", ".join(cfg.columns)),
                 ("Aggregation", cfg.aggregation), ("Valid N", data.valid_n),
                 ("Missing N", data.missing_n), ("Base", data.base_note),
                 ("Footnote", cfg.labels.footnote)]
        notes += [("Warning", w) for w in data.warnings]
        pd.DataFrame(notes, columns=["Item", "Value"]).to_excel(
            book, sheet_name="Notes", index=False)
    return buffer.getvalue()
