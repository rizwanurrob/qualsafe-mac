"""
Render and interaction tests for the Data Charts page (Streamlit).

`AppTest` cannot drive a file uploader, so these start from the built-in sample
survey (the page's own "Try it" button), which is the same code path an upload
takes after loading. Widget keys carry a generation number, so widgets are found
by their key *suffix*.

What is asserted is what the analyst would see: the chart is built, the warnings
appear, undo steps back over a filter, and the select-all choices stay whole.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

APP_PATH = Path(__file__).resolve().parent.parent / "streamlit_app.py"

R1 = "Relationships with friends, family, partners, or roommates"


@pytest.fixture(autouse=True)
def _isolate_settings():
    with tempfile.TemporaryDirectory() as tmp:
        old = os.environ.get("QNW_SETTINGS_DIR")
        os.environ["QNW_SETTINGS_DIR"] = tmp
        yield
        if old is None:
            os.environ.pop("QNW_SETTINGS_DIR", None)
        else:
            os.environ["QNW_SETTINGS_DIR"] = old


STEPS = ("open", "question", "adjust", "save")


def _widget(at, kind: str, suffix: str):
    """A widget by the end of its key. Each of the four steps draws only its own controls, so if it
    is not on this step the others are opened in turn, as a person would click through them."""
    tried = []
    for step in (None,) + STEPS:
        if step is not None:
            at.session_state["step_charts"] = step
            at.run()
            assert not at.exception, at.exception
        found = [w for w in getattr(at, kind) if str(w.key).endswith("_" + suffix)]
        if found:
            return found[0]
        tried.append([w.key for w in getattr(at, kind)])
    raise AssertionError(f"no {kind} ending _{suffix} on any step; saw {tried}")


def _page():
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(APP_PATH), default_timeout=120)
    at.run()
    at.session_state["nav_target"] = "Data Charts"        # the Charts activity (phase 4b)
    at.run()
    assert not at.exception, at.exception
    return at


def _with_sample():
    at = _page()
    next(b for b in at.button if b.key == "dc_sample").click().run()
    assert not at.exception, at.exception
    return at


def _built(at):
    result = at.session_state["dc_built"]
    assert isinstance(result, tuple), result
    return result[0]


def test_empty_state_offers_a_file_and_the_sample():
    at = _page()
    assert any(b.key == "dc_sample" for b in at.button)
    assert "Open a spreadsheet" in " ".join(i.value for i in at.info)


def test_sample_loads_and_shows_rows_columns_and_missing_counts():
    at = _with_sample()
    table = at.session_state["dc_table"]
    assert table.n_rows == 240 and table.n_cols >= 8
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["Rows"] == "240" and metrics["Columns"] == str(table.n_cols)
    profile = at.session_state["dc_profile"]
    assert {c.name: c.kind for c in profile.columns}["Comment"] in ("categorical", "text")
    assert profile.column("Age").n_missing > 0


def test_choosing_a_field_builds_a_chart_with_a_suggested_type():
    at = _with_sample()
    _widget(at, "selectbox", "field").set_value("Class year").run()
    assert not at.exception, at.exception
    data = _built(at)
    assert set(data.categories) == {"First-year", "Sophomore", "Junior", "Senior"}
    assert at.get("vega_lite_chart"), "the chart is drawn on the page"
    assert "dc_png" not in at.session_state, "no picture is rendered on the server for the preview"
    assert at.session_state["dc_cfg"]["chart_type"] == "bar_horizontal"


def test_switching_to_percent_and_count_changes_the_plotted_value():
    at = _with_sample()
    _widget(at, "selectbox", "field").set_value("Class year").run()
    pct = _built(at).table["value"].sum()
    _widget(at, "selectbox", "agg").set_value("count").run()
    assert _built(at).table["value"].sum() == pytest.approx(240.0)
    assert pct == pytest.approx(100.0)


def test_split_by_makes_a_grouped_chart_with_per_group_bases():
    at = _with_sample()
    _widget(at, "selectbox", "field").set_value("First generation").run()
    _widget(at, "multiselect", "group").set_value(["Class year"]).run()
    assert not at.exception, at.exception
    data = _built(at)
    assert data.groups == ["First-year", "Sophomore", "Junior", "Senior"] or len(data.groups) == 4
    assert at.session_state["dc_cfg"]["group_by"] == ["Class year"]
    assert data.table["valid_n"].nunique() > 1              # each group has its own base


def test_matrix_question_builds_a_stacked_likert_chart_in_scale_order():
    at = _with_sample()
    _widget(at, "radio", "kind").set_value("matrix").run()
    _widget(at, "multiselect", "columns").set_value(
        ["I feel like I belong here", "I feel safe on campus"]).run()
    assert not at.exception, at.exception
    data = _built(at)
    assert data.kind == "matrix" and len(data.groups) == 2
    assert data.categories[:5] == ["Strongly disagree", "Somewhat disagree", "Neutral",
                                   "Somewhat agree", "Strongly agree"]
    assert data.categories[-1] == "No opinion"
    assert at.session_state["dc_cfg"]["chart_type"] == "normalized_bar"


def test_select_all_keeps_comma_containing_choices_whole():
    at = _with_sample()
    _widget(at, "radio", "kind").set_value("multi").run()
    _widget(at, "selectbox", "field").set_value("Concerns").run()
    at.run()
    choices = "\n".join([R1, "Getting involved or finding community",
                         "Managing anxiety, stress, or feeling overwhelmed",
                         "Paying for college", "Balancing work and classes"])
    _widget(at, "text_area", "choices").set_value(choices).run()
    assert not at.exception, at.exception
    data = _built(at)
    assert len(data.categories) == 5 and R1 in data.categories
    assert data.value_title.endswith("multiple selections allowed")


def test_suggest_choices_fills_the_list_and_rejoins_cut_choices():
    at = _with_sample()
    _widget(at, "radio", "kind").set_value("multi").run()
    _widget(at, "selectbox", "field").set_value("Concerns").run()
    _widget(at, "button", "suggest").click().run()
    assert not at.exception, at.exception
    choices = at.session_state["dc_cfg"]["multi"]["choices"]
    assert R1 in choices and "Managing anxiety, stress, or feeling overwhelmed" in choices
    assert len(choices) == 5


def test_a_filter_narrows_the_base_and_undo_steps_back_over_it():
    at = _with_sample()
    _widget(at, "selectbox", "field").set_value("First generation").run()
    before = _built(at).valid_n
    _widget(at, "selectbox", "f_col").set_value("Class year").run()
    _widget(at, "multiselect", "f_vals").set_value(["Senior"]).run()
    _widget(at, "button", "f_add").click().run()
    assert not at.exception, at.exception
    filtered = _built(at).valid_n
    assert 0 < filtered < before
    assert at.session_state["dc_cfg"]["filters"][0]["column"] == "Class year"
    _widget(at, "button", "undo").click().run()
    assert not at.exception, at.exception
    assert at.session_state["dc_cfg"]["filters"] == []
    assert _built(at).valid_n == before
    _widget(at, "button", "redo").click().run()
    assert _built(at).valid_n == filtered


def test_undo_does_not_undo_the_title():
    at = _with_sample()
    _widget(at, "selectbox", "field").set_value("Class year").run()
    _widget(at, "selectbox", "sort").set_value("alpha").run()
    _widget(at, "text_input", "title").set_value("My chart").run()
    _widget(at, "button", "undo").click().run()
    cfg = at.session_state["dc_cfg"]
    assert cfg["sort"] == "desc" and cfg["labels"]["title"] == "My chart"


def test_reset_chart_clears_choices_and_is_undoable():
    at = _with_sample()
    _widget(at, "selectbox", "field").set_value("Class year").run()
    _widget(at, "button", "reset").click().run()
    assert at.session_state["dc_cfg"]["column"] == ""
    _widget(at, "button", "undo").click().run()
    assert at.session_state["dc_cfg"]["column"] == "Class year"


def test_free_text_gives_a_keyword_chart_and_the_response_count():
    at = _with_sample()
    _widget(at, "radio", "kind").set_value("text").run()
    _widget(at, "selectbox", "field").set_value("Comment").run()
    assert not at.exception, at.exception
    data = _built(at)
    assert data.kind == "text" and data.valid_n < 240 and "helpful" in data.categories


def test_theme_and_size_and_labels_reach_the_spec():
    at = _with_sample()
    _widget(at, "selectbox", "field").set_value("Class year").run()
    _widget(at, "text_input", "title").set_value("Class year mix").run()
    _widget(at, "radio", "size").set_value("large").run()
    _widget(at, "selectbox", "theme").set_value("Grayscale").run()
    spec = at.session_state["dc_built"][2]
    assert spec["title"]["text"] == "Class year mix"
    assert spec["title"]["color"] == "#111111"                   # Grayscale title
    assert at.session_state["dc_cfg"]["display"]["size"] == "large"


def test_a_bad_hex_is_reported_not_crashed_on():
    at = _with_sample()
    _widget(at, "selectbox", "field").set_value("Class year").run()
    _widget(at, "text_input", "ct_name").set_value("Mine").run()
    _widget(at, "text_input", "ct_Primary").set_value("gold").run()
    _widget(at, "button", "ct_save").click().run()
    assert not at.exception, at.exception
    assert any("not a hex colour" in e.value for e in at.error)
    _widget(at, "text_input", "ct_Primary").set_value("#112233").run()
    _widget(at, "button", "ct_save").click().run()
    assert "Mine" in at.session_state["dc_custom_themes"]


def test_the_uploaded_data_is_not_modified():
    at = _with_sample()
    frame = at.session_state["dc_table"].frame.copy(deep=True)
    _widget(at, "selectbox", "field").set_value("Residence").run()
    _widget(at, "selectbox", "sort").set_value("alpha").run()
    import pandas as pd
    pd.testing.assert_frame_equal(at.session_state["dc_table"].frame, frame)


# ── numeric and time charts ──────────────────────────────────────────────────

def test_a_number_starts_as_a_histogram_and_a_date_as_a_line():
    at = _with_sample()
    _widget(at, "selectbox", "field").set_value("Hours per week").run()
    assert not at.exception, at.exception
    cfg = at.session_state["dc_cfg"]
    assert cfg["chart_type"] == "histogram" and cfg["aggregation"] == "percent"
    data = _built(at)
    assert data.kind == "numeric" and data.notes["chart"] == "histogram"
    assert at.get("vega_lite_chart"), "the chart is drawn on the page"
    assert "dc_png" not in at.session_state, "no picture is rendered on the server for the preview"
    _widget(at, "selectbox", "field").set_value("Survey date").run()
    assert not at.exception, at.exception
    assert at.session_state["dc_cfg"]["chart_type"] == "line"
    assert at.session_state["dc_cfg"]["aggregation"] == "count"
    assert _built(at).notes["x_kind"] == "temporal"


def test_bins_and_time_grain_controls_change_the_chart():
    at = _with_sample()
    _widget(at, "selectbox", "field").set_value("Hours per week").run()
    _widget(at, "number_input", "bins").set_value(5).run()
    assert not at.exception, at.exception
    assert len(_built(at).categories) == 5
    _widget(at, "selectbox", "field").set_value("Survey date").run()
    _widget(at, "selectbox", "grain").set_value("month").run()
    assert _built(at).categories == ["2025-09", "2025-10", "2025-11", "2025-12"]


def test_scatter_needs_a_vertical_axis_and_can_draw_a_line_of_best_fit():
    at = _with_sample()
    _widget(at, "selectbox", "field").set_value("Hours per week").run()
    _widget(at, "selectbox", "chart").set_value("scatter").run()
    assert not at.exception, at.exception
    assert isinstance(at.session_state["dc_built"], str)
    assert "second numeric field" in at.session_state["dc_built"]
    _widget(at, "selectbox", "value_y").set_value("Age").run()
    _widget(at, "checkbox", "trend").set_value(True).run()
    assert not at.exception, at.exception
    data = _built(at)
    assert data.notes["chart"] == "scatter" and data.base_note.startswith("Line of best fit")


def test_box_plot_by_group_and_switching_back_to_categories_restores_the_grid():
    at = _with_sample()
    _widget(at, "selectbox", "field").set_value("Hours per week").run()
    _widget(at, "selectbox", "chart").set_value("box").run()
    _widget(at, "multiselect", "group").set_value(["Class year"]).run()
    assert not at.exception, at.exception
    assert len(_built(at).table) == 4 and _built(at).notes["chart"] == "box"
    # Choosing the field that was the split must not crash (it cannot split itself).
    _widget(at, "selectbox", "field").set_value("Class year").run()
    assert not at.exception, at.exception
    assert at.session_state["dc_cfg"]["group_by"] == []
    assert at.session_state["dc_cfg"]["chart_type"] == "bar_horizontal"
    assert set(_built(at).categories) == {"First-year", "Sophomore", "Junior", "Senior"}


def test_a_chart_switched_to_area_counts_and_stacks_the_groups():
    at = _with_sample()
    _widget(at, "selectbox", "field").set_value("Survey date").run()
    _widget(at, "selectbox", "chart").set_value("area").run()
    _widget(at, "multiselect", "group").set_value(["First generation"]).run()
    assert not at.exception, at.exception
    assert at.session_state["dc_cfg"]["aggregation"] == "count"
    assert at.session_state["dc_built"][2]["layer"][0]["encoding"]["y"]["stack"] == "zero"


# ── saved charts and custom themes ───────────────────────────────────────────

def _saved_charts():
    from core.chartbuilder import store
    return store.list_charts()


def test_a_chart_can_be_saved_and_opened_again_after_a_reset():
    at = _with_sample()
    _widget(at, "selectbox", "field").set_value("Class year").run()
    _widget(at, "text_input", "title").set_value("Class mix").run()
    _widget(at, "selectbox", "sort").set_value("alpha").run()
    before = dict(at.session_state["dc_cfg"])
    _widget(at, "text_input", "chart_name").set_value("Fall class mix").run()
    _widget(at, "button", "chart_save").click().run()
    assert not at.exception, at.exception
    assert [c.name for c in _saved_charts()] == ["Fall class mix"]
    _widget(at, "button", "reset").click().run()
    assert at.session_state["dc_cfg"]["column"] == ""
    _widget(at, "button", "chart_open").click().run()
    assert not at.exception, at.exception
    assert at.session_state["dc_cfg"] == before
    assert set(_built(at).categories) == {"First-year", "Sophomore", "Junior", "Senior"}
    assert at.session_state["dc_load_notes"] == []


def test_saving_under_the_same_name_replaces_and_delete_removes():
    at = _with_sample()
    _widget(at, "selectbox", "field").set_value("Class year").run()
    _widget(at, "text_input", "chart_name").set_value("Mine").run()
    _widget(at, "button", "chart_save").click().run()
    _widget(at, "selectbox", "sort").set_value("alpha").run()
    _widget(at, "text_input", "chart_name").set_value("mine").run()
    _widget(at, "button", "chart_save").click().run()
    charts = _saved_charts()
    assert len(charts) == 1
    from core.chartbuilder import store
    assert store.load_chart("MINE").config.sort == "alpha"
    _widget(at, "button", "chart_delete").click().run()
    assert not at.exception, at.exception
    assert _saved_charts() == []


def test_a_loaded_chart_keeps_its_own_chart_type_instead_of_the_suggested_one():
    from core.chartbuilder import store
    from core.chartbuilder.config import ChartConfig
    cfg = ChartConfig(column="Class year", chart_type="donut")
    store.save_chart("Donut", cfg)
    at = _with_sample()
    _widget(at, "button", "chart_open").click().run()
    assert not at.exception, at.exception
    assert at.session_state["dc_cfg"]["chart_type"] == "donut"
    assert at.session_state["dc_cfg"]["column"] == "Class year"


def test_opening_a_chart_on_a_file_without_its_fields_says_which_are_missing():
    from core.chartbuilder import store
    from core.chartbuilder.config import ChartConfig
    cfg = ChartConfig(column="Class year", group_by=["Not in this file"])
    store.save_chart("Elsewhere", cfg, {"name": "other.csv", "columns": ["Class year"]})
    at = _with_sample()
    _widget(at, "button", "chart_open").click().run()
    assert not at.exception, at.exception
    cfg_now = at.session_state["dc_cfg"]
    assert cfg_now["column"] == "Class year" and cfg_now["group_by"] == []
    assert any("'Not in this file'" in w.value for w in at.warning)


def test_a_custom_theme_is_kept_between_sessions_and_can_be_deleted():
    at = _with_sample()
    _widget(at, "selectbox", "field").set_value("Class year").run()
    _widget(at, "text_input", "ct_name").set_value("Campus").run()
    _widget(at, "text_input", "ct_Primary").set_value("#112233").run()
    _widget(at, "button", "ct_save").click().run()
    assert not at.exception, at.exception
    from core.chartbuilder import store
    assert list(store.load_themes()) == ["Campus"]
    fresh = _with_sample()                                   # a new session: nothing carried in memory
    _widget(fresh, "selectbox", "field").set_value("Class year").run()
    options = _widget(fresh, "selectbox", "theme").options
    assert "Campus" in options
    _widget(fresh, "selectbox", "theme").set_value("Campus").run()
    assert set(_built(fresh).table["color"]) == {"#112233"}
    _widget(fresh, "button", "ct_delete").click().run()
    assert not fresh.exception, fresh.exception
    assert store.load_themes() == {} and fresh.session_state["dc_cfg"]["theme"]["name"] == "QualSafe default"


def test_a_theme_that_reuses_a_built_in_name_is_refused_in_words():
    at = _with_sample()
    _widget(at, "text_input", "ct_name").set_value("QualSafe default").run()
    _widget(at, "button", "ct_save").click().run()
    assert any("built-in theme" in e.value for e in at.error)


def test_the_screen_spec_fills_the_column_with_the_same_proportions_and_leaves_composed_charts_alone():
    from app.data_charts_page import _screen_spec

    spec = {"width": 1280, "height": 720, "layer": [{"mark": "bar"}], "autosize": {"type": "pad"}}
    fitted = _screen_spec(spec)
    assert fitted["width"] == "container" and fitted["height"] == 360
    assert spec["width"] == 1280                                  # the original is not changed
    assert _screen_spec({"vconcat": [{}, {}], "width": 100}) is None
    assert _screen_spec({"facet": {}, "spec": {}}) is None


def test_the_screen_spec_scales_every_font_size_and_nothing_else():
    from app.data_charts_page import _TEXT_SCALE, _screen_spec

    spec = {"width": 1280, "height": 720,
            "config": {"axis": {"labelFontSize": 20, "titleFontSize": 24}},
            "layer": [{"mark": {"type": "text", "fontSize": 16, "dx": 4}}, {"mark": {"type": "bar", "size": 30}}]}
    fitted = _screen_spec(spec)
    assert fitted["config"]["axis"]["labelFontSize"] == round(20 * _TEXT_SCALE, 1)
    assert fitted["layer"][0]["mark"]["fontSize"] == round(16 * _TEXT_SCALE, 1)
    assert fitted["layer"][0]["mark"]["dx"] == 4 and fitted["layer"][1]["mark"]["size"] == 30
    assert spec["config"]["axis"]["labelFontSize"] == 20                  # the original is untouched
