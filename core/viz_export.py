#!/usr/bin/env python
"""
Chart export helpers (v3.9.9).

Turn an Altair chart into a downloadable image (PNG / SVG) or its Vega-Lite spec,
so a figure can go straight into a Word/PowerPoint report. Rendering is done by
`vl-convert` — a self-contained, **offline** converter (no browser, no network),
consistent with the tool's local-first promise. If it isn't installed, image
export degrades gracefully (the spec + data still download, and the chart's own
"⋯" menu still saves PNG/SVG client-side).

Kept out of the Streamlit layer so the conversion is testable in isolation; the UI
wires these to download buttons.
"""

from __future__ import annotations

from typing import Any, List


def image_export_available() -> bool:
    """True when server-side PNG/SVG rendering is possible (vl-convert present)."""
    try:
        import vl_convert  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


def available_image_formats() -> List[str]:
    """Image formats we can render right now (empty if vl-convert is missing)."""
    return ["png", "svg"] if image_export_available() else []


def chart_spec(chart: Any) -> str:
    """The chart's Vega-Lite JSON spec — always available, offline, reproducible."""
    return chart.to_json()


def chart_to_png(chart: Any, *, scale: float = 2.0) -> bytes:
    """Render an Altair chart to PNG bytes (2x scale by default for crisp figures).

    Raises RuntimeError with an actionable message if vl-convert isn't installed.
    """
    try:
        import vl_convert as vlc
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            "PNG export needs vl-convert-python (pip install vl-convert-python)."
        ) from exc
    return vlc.vegalite_to_png(chart.to_json(), scale=scale)


def chart_to_svg(chart: Any) -> str:
    """Render an Altair chart to an SVG string (vector; scales without blur)."""
    try:
        import vl_convert as vlc
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            "SVG export needs vl-convert-python (pip install vl-convert-python)."
        ) from exc
    return vlc.vegalite_to_svg(chart.to_json())
