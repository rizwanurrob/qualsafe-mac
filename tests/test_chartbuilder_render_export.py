"""
Chart Builder themes, renderer and export.

The renderer is checked by handing its spec to Altair (which validates against the
Vega-Lite schema) and, for images, to vl-convert -- the same path the front ends
use. A chart builder that emits *nearly* valid Vega-Lite fails as a blank panel.
"""

from __future__ import annotations

import json
import re
import struct
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.chartbuilder import export, themes
from core.chartbuilder.aggregate import ChartBuildError
from core.chartbuilder.build import build_data
from core.chartbuilder.config import ChartConfig
from core.chartbuilder.render import AVAILABLE_TYPES, build_spec, figure_size, wrap_label

AGREE = ["Strongly disagree", "Somewhat disagree", "Neutral", "Somewhat agree",
         "Strongly agree"]
IMPORTANCE = ["Not at all", "Slightly", "Moderately", "Very", "Extremely",
              "No opinion"]


def _survey(n=120):
    rows = []
    for i in range(n):
        rows.append({"Q": AGREE[(i * 7 + i // 3) % 5], "Year": ["A", "B", "C"][i % 3]})
    return pd.DataFrame(rows)


# ── themes ────────────────────────────────────────────────────────────────────

def test_the_default_theme_is_the_default_and_uses_the_specified_hexes():
    t = themes.get_theme(None)
    assert t.name == "QualSafe default" and ChartConfig().theme.name == t.name
    assert (t.primary, t.secondary, t.neutral) == ("#BC912C", "#15284B", "#A7A8AA")
    assert t.tertiary[0] == "#B7B4D8" and t.title == "#15284B"
    assert t.background == "#FFFFFF"
    assert t.categorical[:4] == ["#BC912C", "#15284B", "#A7A8AA", "#B7B4D8"]


def test_agreement_scale_maps_to_the_specified_colours():
    m = themes.category_colors(AGREE, themes.BUILT_IN_DEFAULT)
    assert [m[c] for c in AGREE] == ["#A7A8AA", "#B7B4D8", "#15284B", "#BC912C", "#BC912C"]


def test_importance_scale_maps_to_the_specified_colours():
    m = themes.category_colors(IMPORTANCE, themes.BUILT_IN_DEFAULT)
    assert [m[c] for c in IMPORTANCE] == ["#A7A8AA", "#15284B", "#15284B", "#BC912C",
                                          "#BC912C", "#B7B4D8"]


def test_scale_labels_with_suffixes_and_case_still_map():
    m = themes.category_colors(["not at all important", "Slightly important",
                                "VERY important"], themes.BUILT_IN_DEFAULT)
    assert list(m.values()) == ["#A7A8AA", "#15284B", "#BC912C"]


def test_a_nominal_question_is_not_painted_as_a_scale():
    assert themes.detect_scale(["Never", "Cat", "Dog", "Bird"]) is None
    m = themes.category_colors(["Cat", "Dog", "Bird", "Fish"], themes.BUILT_IN_DEFAULT)
    assert list(m.values()) == themes.BUILT_IN_DEFAULT.categorical[:4]


def test_manual_override_beats_scale_and_scale_can_be_switched_off():
    m = themes.category_colors(AGREE, themes.BUILT_IN_DEFAULT,
                               overrides={"Neutral": "#ff0000"})
    assert m["Neutral"] == "#FF0000" and m["Strongly agree"] == "#BC912C"
    off = themes.category_colors(AGREE, themes.BUILT_IN_DEFAULT, scale="none")
    assert list(off.values()) == themes.BUILT_IN_DEFAULT.categorical[:5]


def test_scale_roles_follow_the_active_theme():
    m = themes.category_colors(AGREE, themes.OKABE_ITO)
    assert m["Strongly agree"] == themes.OKABE_ITO.primary
    assert m["Strongly disagree"] == themes.OKABE_ITO.neutral


def test_adjacent_duplicate_colours_are_detected():
    m = themes.category_colors(AGREE, themes.BUILT_IN_DEFAULT)
    assert themes.adjacent_duplicates(AGREE, m)
    assert not themes.adjacent_duplicates(["a", "b"], {"a": "#111111", "b": "#222222"})


def test_hex_entry_is_normalised_and_bad_hex_refused():
    assert themes.normalize_hex("bc912c") == "#BC912C"
    assert themes.normalize_hex("#abc") == "#AABBCC"
    with pytest.raises(ValueError, match="not a hex colour"):
        themes.normalize_hex("gold")
    with pytest.raises(ValueError):
        themes.Theme(name="x", primary="#12345", secondary="#000000",
                     tertiary=[], neutral="#000000")


def test_custom_theme_round_trips_and_missing_theme_falls_back_to_default():
    custom = themes.Theme(name="Mine", primary="#112233", secondary="#445566",
                          tertiary=["#778899"], neutral="#AABBCC")
    again = themes.Theme.from_dict(json.loads(json.dumps(custom.to_dict())))
    assert again == custom
    assert themes.get_theme("Mine", {"Mine": custom}) is custom
    assert themes.get_theme("Deleted Theme") is themes.BUILT_IN_DEFAULT


def test_single_series_bars_are_default_gold_and_groups_use_gold_then_blue():
    df = pd.DataFrame({"Q": ["a", "b", "a", "c"] * 10, "G": ["x", "y"] * 20})
    d, _ = build_data(df, ChartConfig(column="Q"))
    assert set(d.table["color"]) == {"#BC912C"} and d.color_by == "none"
    d, _ = build_data(df, ChartConfig(column="Q", group_by=["G"], chart_type="grouped_bar"))
    assert dict(zip(d.table["group"], d.table["color"])) == {"x": "#BC912C", "y": "#15284B"}


def test_color_column_follows_the_semantic_scale_on_a_single_question():
    d, _ = build_data(_survey(), ChartConfig(column="Q", sort="custom"))
    assert d.color_by == "category" and d.scale == "agreement"
    got = dict(zip(d.table["category"], d.table["color"]))
    assert got["Strongly disagree"] == "#A7A8AA" and got["Somewhat agree"] == "#BC912C"
    assert d.stack_border is False or isinstance(d.stack_border, bool)


# ── renderer ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def alt():
    return pytest.importorskip("altair")


def _spec(cfg, df=None):
    d, t = build_data(df if df is not None else _survey(), cfg)
    return build_spec(d, cfg, t), d


@pytest.mark.parametrize("ctype,group", [
    ("bar", False), ("bar_horizontal", False), ("pie", False), ("donut", False),
    ("grouped_bar", True), ("stacked_bar", True), ("normalized_bar", True),
    ("heatmap", True), ("bar", True)])
def test_every_available_type_is_valid_vega_lite(alt, ctype, group):
    cfg = ChartConfig(column="Q", chart_type=ctype, group_by=["Year"] if group else [])
    cfg.labels.title, cfg.labels.footnote = "T", "Source: X"
    spec, _ = _spec(cfg)
    alt.Chart.from_dict(spec)                     # validates against the schema
    assert spec["autosize"]["type"] == "fit"


def test_every_chart_type_in_the_brief_is_available_and_misuse_says_so():
    assert set(AVAILABLE_TYPES) == {"bar", "bar_horizontal", "grouped_bar", "stacked_bar",
                                    "normalized_bar", "pie", "donut", "heatmap", "line",
                                    "area", "scatter", "histogram", "box"}
    with pytest.raises(ChartBuildError, match="grouping field"):
        _spec(ChartConfig(column="Q", chart_type="heatmap"))
    with pytest.raises(ChartBuildError, match="needs one numeric or date field"):
        _spec(ChartConfig(kind="matrix", columns=["Q", "Year"], chart_type="histogram"))


def test_grouped_data_never_becomes_a_plain_bar():
    spec, _ = _spec(ChartConfig(column="Q", chart_type="bar_horizontal", group_by=["Year"]))
    enc = spec["layer"][0]["encoding"]
    assert "yOffset" in enc


def test_category_order_reaches_the_axis_and_wraps_long_labels():
    df = pd.DataFrame({"Q": ["Relationships with friends, family, partners, or roommates"] * 3
                       + ["Other"] * 2})
    cfg = ChartConfig(column="Q")
    cfg.display.max_label_chars = 20
    spec, d = _spec(cfg, df)
    order = spec["layer"][0]["encoding"]["y"]["sort"]
    assert len(order) == 2 and "\n" in order[0]
    assert max(len(line) for line in order[0].split("\n")) <= 20
    cfg.display.wrap_labels = False
    spec, _ = _spec(cfg, df)
    assert "\n" not in spec["layer"][0]["encoding"]["y"]["sort"][0]
    assert wrap_label("short", 20) == "short"


def test_titles_footnote_and_axis_titles_and_size_options():
    cfg = ChartConfig(column="Q")
    cfg.labels.title, cfg.labels.subtitle = "Belonging", "Fall 2026"
    cfg.labels.footnote = "Source: OIR"
    cfg.labels.x_title = "Share of students"
    spec, d = _spec(cfg)
    assert spec["title"]["text"] == "Belonging" and spec["title"]["color"] == "#15284B"
    assert spec["title"]["subtitle"] == "Fall 2026"
    foot = spec["layer"][-1]["encoding"]["text"]["value"]
    assert "Source: OIR" in foot and "valid response" in foot
    assert spec["layer"][0]["encoding"]["x"]["title"] == "Share of students"
    sizes = {}
    for size in ("small", "medium", "large", "xlarge"):
        cfg.display.size = size
        s, _ = _spec(cfg)
        sizes[size] = (s["title"]["fontSize"], s["layer"][0]["encoding"]["y"]["scale"]["paddingInner"])
    assert [v[0] for v in sizes.values()] == sorted(v[0] for v in sizes.values())
    assert [v[1] for v in sizes.values()] == sorted((v[1] for v in sizes.values()), reverse=True)
    assert len({v for v in sizes.values()}) == 4


def test_gridlines_axis_range_data_labels_and_legend_position():
    cfg = ChartConfig(column="Q", group_by=["Year"], chart_type="grouped_bar")
    cfg.display.gridlines = False
    cfg.display.axis_min, cfg.display.axis_max = 0, 80
    cfg.labels.legend_position = "bottom"
    spec, _ = _spec(cfg)
    x = spec["layer"][0]["encoding"]["x"]
    assert x["axis"]["grid"] is False
    assert (x["scale"]["domainMin"], x["scale"]["domainMax"]) == (0, 80)
    assert spec["layer"][0]["encoding"]["color"]["legend"]["orient"] == "bottom"
    cfg.labels.legend_position = "none"
    assert _spec(cfg)[0]["layer"][0]["encoding"]["color"]["legend"] is None
    with_labels = len(_spec(cfg)[0]["layer"])
    cfg.display.data_labels = False
    assert len(_spec(cfg)[0]["layer"]) == with_labels - 1


def test_stacked_segments_add_up_and_narrow_ones_lose_their_label():
    df = pd.DataFrame({"Q": ["a"] * 90 + ["b"] * 8 + ["c"] * 2})
    cfg = ChartConfig(column="Q", chart_type="normalized_bar")
    spec, d = _spec(cfg, df)
    rows = spec["data"]["values"]
    assert rows[0]["start"] == 0 and rows[-1]["end"] == pytest.approx(100)
    assert [r["end"] for r in rows][:-1] == [r["start"] for r in rows][1:]
    shown = {r["category"]: r["show_label"] for r in rows}
    assert shown == {"a": True, "b": True, "c": False}


def test_stacked_uses_white_border_only_when_neighbours_share_a_colour():
    cfg = ChartConfig(column="Q", chart_type="normalized_bar", sort="custom")
    cfg.recode.order = AGREE
    spec, d = _spec(cfg)
    assert d.stack_border and spec["layer"][0]["mark"]["stroke"] == "#FFFFFF"
    cfg.theme.semantic_scale = "none"
    spec, d = _spec(cfg)
    assert not d.stack_border and spec["layer"][0]["mark"]["strokeWidth"] == 0


def test_figure_presets_and_custom_size():
    cfg = ChartConfig()
    assert figure_size(cfg) == (1280, 720)
    cfg.figure.preset = "4:3"
    assert figure_size(cfg) == (1024, 768)
    cfg.figure.preset, cfg.figure.width, cfg.figure.height = "Custom", 500, 400
    assert figure_size(cfg) == (500, 400)
    cfg.figure.width = 5
    assert figure_size(cfg)[0] == 200                       # clamped, never zero


def test_transparent_background_is_honoured():
    cfg = ChartConfig(column="Q")
    assert _spec(cfg)[0]["background"] == "#FFFFFF"
    cfg.figure.transparent = True
    assert _spec(cfg)[0]["background"] == "transparent"


# ── export ────────────────────────────────────────────────────────────────────

def _png_size(data: bytes):
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    return struct.unpack(">II", data[16:24])


@pytest.mark.skipif(not export.image_export_available(), reason="vl-convert missing")
def test_png_is_exactly_the_figure_size_at_each_dpi():
    cfg = ChartConfig(column="Q")
    cfg.labels.title = "T"; cfg.labels.footnote = "Source"
    spec, _ = _spec(cfg)
    assert _png_size(export.render_image(spec, "png", 96)) == (1280, 720)
    assert _png_size(export.render_image(spec, "png", 150)) == (2000, 1125)
    assert _png_size(export.render_image(spec, "png", 300)) == (4000, 2250)
    assert export.export_pixels(cfg, 300) == (4000, 2250)


@pytest.mark.skipif(not export.image_export_available(), reason="vl-convert missing")
def test_svg_and_pdf_export_and_bad_format_is_refused():
    spec, _ = _spec(ChartConfig(column="Q"))
    assert export.render_image(spec, "svg").lstrip().startswith(b"<svg")
    assert export.render_image(spec, "pdf")[:4] == b"%PDF"
    with pytest.raises(ValueError, match="Unknown image format"):
        export.render_image(spec, "gif")


@pytest.mark.skipif(not export.image_export_available(), reason="vl-convert missing")
def test_transparent_png_has_an_alpha_channel():
    cfg = ChartConfig(column="Q")
    cfg.figure.transparent = True
    spec, _ = _spec(cfg)
    png = export.render_image(spec, "png", 96)
    assert png[25] == 6                    # IHDR colour type 6 = RGBA


# ── filenames ─────────────────────────────────────────────────────────────────

def test_filenames_are_windows_legal():
    assert export.safe_filename('Q1: How "welcome" do you feel? <a/b>', "PNG") == \
        "Q1_How_welcome_do_you_feel_a_b.png"
    for reserved in ("CON", "nul", "COM1", "lpt9.txt"):
        assert not export.safe_stem(reserved).upper().startswith(("CON", "NUL", "COM1", "LPT9"))
    assert export.safe_stem("...   ") == "chart" and export.safe_stem("") == "chart"
    assert export.safe_stem("trailing dot.") == "trailing_dot"
    assert not re.search(r'[<>:"/\\|?*]', export.safe_stem('a<b>c:d"e/f\\g|h?i*j'))


def test_very_long_field_names_are_shortened_with_a_hash_and_stay_distinct():
    a = "How much do you agree that " + "the university supports students " * 20 + "A"
    b = "How much do you agree that " + "the university supports students " * 20 + "B"
    fa, fb = export.safe_filename(a, "png"), export.safe_filename(b, "png")
    assert len(fa) <= 130 and fa.endswith(".png") and fa != fb
    assert export.safe_filename(a, "png") == fa                       # deterministic


def test_full_path_stays_under_windows_max_path():
    deep = "C:\\Users\\someone\\OneDrive - QualSafe default\\Institutional Research\\" \
           "Surveys\\2026\\Entering Student Survey\\Charts for the Board Presentation"
    name = "Question " * 60
    out = export.safe_filename(name, "svg", deep)
    assert len(deep) + 1 + len(out) <= 240 < 260
    with pytest.raises(ValueError, match="folder path is too long"):
        export.safe_filename(name, "png", "C:\\" + "x" * 300)


def test_default_chart_filename_uses_title_else_field_and_type():
    cfg = ChartConfig(column="Belonging", chart_type="donut")
    assert export.chart_filename(cfg, "png") == "Belonging_donut.png"
    cfg.labels.title = "Sense of belonging?"
    assert export.chart_filename(cfg, "svg", suffix="dark") == \
        "Sense_of_belonging_donut_dark.svg"


# ── tables ────────────────────────────────────────────────────────────────────

def test_summary_table_columns_totals_and_grouping():
    df = pd.DataFrame({"Q": ["a", "a", "b", "", "b", "b"], "G": ["x", "x", "x", "x", "y", "y"]})
    cfg = ChartConfig(column="Q")
    d, _ = build_data(df, cfg)
    t = export.summary_table(d, cfg)
    assert list(t.columns) == ["Response", "Count", "Percent", "Valid N"]
    assert t.loc[0].tolist() == ["b", 3, 60.0, 5]
    t = export.summary_table(d, cfg, totals=True, missing_n=True)
    assert t.iloc[-1].tolist() == ["Total", 5, 100.0, 5, 1]
    cfg = ChartConfig(column="Q", group_by=["G"], chart_type="grouped_bar")
    d, _ = build_data(df, cfg)
    t = export.summary_table(d, cfg, totals=True)
    assert list(t.columns)[:2] == ["Response", "G"]
    assert (t["Response"] == "Total").sum() == 2


def test_csv_and_xlsx_exports_round_trip():
    import io
    df = pd.DataFrame({"Q": ["It\u2019s fine", "Café", "Café"]})
    cfg = ChartConfig(column="Q")
    cfg.labels.title = "Title"
    d, _ = build_data(df, cfg)
    t = export.summary_table(d, cfg)
    raw = export.table_csv(t)
    assert raw.startswith(b"\xef\xbb\xbf")
    back = pd.read_csv(io.BytesIO(raw), encoding="utf-8-sig")
    assert back["Response"].tolist() == ["Café", "It\u2019s fine"]
    book = pd.read_excel(io.BytesIO(export.table_xlsx(t, d, cfg)), sheet_name=None)
    assert set(book) == {"Summary", "Notes"} and book["Summary"]["Count"].tolist() == [2, 1]
    assert "Title" in book["Notes"]["Value"].tolist()
    assert export.table_tsv(t).splitlines()[0] == "Response\tCount\tPercent\tValid N"
