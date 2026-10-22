"""Tests for chart color schemes and image export (v3.9.9)."""

from __future__ import annotations

import json

import pandas as pd
import pytest

import core.theme as theme
from core import viz_export


# ── Color schemes ───────────────────────────────────────────────────────────
def test_named_schemes_exist_and_are_nonempty():
    assert theme.DEFAULT_HEATMAP_SCHEME in theme.HEATMAP_SCHEMES
    for name, stops in theme.HEATMAP_SCHEMES.items():
        assert isinstance(stops, list) and len(stops) >= 3, name
        assert all(s.startswith("#") for s in stops), name


def test_heatmap_range_falls_back_to_default():
    assert theme.heatmap_range("no-such-scheme") == theme.HEATMAP_SCHEMES[theme.DEFAULT_HEATMAP_SCHEME]
    assert theme.heatmap_range("Green → Orange") == theme.HEATMAP_SCHEMES["Green → Orange"]


# ── Export ──────────────────────────────────────────────────────────────────
def _chart():
    import altair as alt
    df = pd.DataFrame({"a": ["x", "y"], "b": ["p", "q"], "v": [1, 2]})
    return alt.Chart(df).mark_rect().encode(x="a:N", y="b:N", color="v:Q")


def test_spec_is_valid_json_always():
    pytest.importorskip("altair")
    spec = viz_export.chart_spec(_chart())
    parsed = json.loads(spec)
    assert "mark" in parsed or "encoding" in parsed


def test_available_formats_is_a_list():
    fmts = viz_export.available_image_formats()
    assert isinstance(fmts, list)
    assert set(fmts) <= {"png", "svg"}


def test_png_and_svg_render_when_vl_convert_present():
    pytest.importorskip("vl_convert")
    pytest.importorskip("altair")
    chart = _chart()
    png = viz_export.chart_to_png(chart)
    assert isinstance(png, bytes) and png[:8] == b"\x89PNG\r\n\x1a\n"  # PNG magic
    svg = viz_export.chart_to_svg(chart)
    assert isinstance(svg, str) and "<svg" in svg


def test_png_raises_actionable_error_without_vl_convert(monkeypatch):
    # Simulate vl-convert being absent even if it's installed in this env.
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name == "vl_convert":
            raise ImportError("no vl_convert")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    assert viz_export.image_export_available() is False
    with pytest.raises(RuntimeError):
        viz_export.chart_to_png(_chart())
