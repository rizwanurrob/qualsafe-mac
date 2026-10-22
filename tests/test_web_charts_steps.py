"""Charts on the web: four real steps, each with few controls and one main button (item 4b.5f)."""

from __future__ import annotations

from pathlib import Path

from core.ux import words
from tests import webkit

ROOT = Path(__file__).resolve().parents[1]


def _sample(step: str = "open"):
    at = webkit.start("")
    webkit.go(at, "Data Charts")                       # the Charts activity, step 1
    next(b for b in at.button if b.key == "dc_sample").click().run()
    assert not at.exception, at.exception
    if step != "open":
        at.session_state["step_charts"] = step
        at.run()
        assert not at.exception, at.exception
    return at


def _keys(controls):
    return [getattr(c, "key", None) for c in controls]


def test_the_empty_open_step_offers_a_file_and_the_sample_only():
    at = webkit.start("")
    webkit.go(at, "Data Charts")
    shown = webkit.describe(webkit.visible_controls(at))
    assert shown == ["file_uploader:dc_upload", "button:dc_sample"], shown
    assert at.session_state["activity"] == "charts" and at.session_state["step_charts"] == "open"


def test_open_shows_the_data_and_one_main_button_with_the_blank_settings_folded():
    at = _sample("open")
    visible = webkit.visible_controls(at)
    assert len(visible) <= webkit.MAX_VISIBLE_CONTROLS, webkit.describe(visible)
    assert [b.key for b in webkit.primary_buttons(at)] == ["dc_next_open"]
    inside = {k for k in _keys(webkit.all_controls(at))}
    outside = {k for k in _keys(visible)}
    assert any(str(k).endswith("_tokens") for k in inside) and not any(str(k).endswith("_tokens") for k in outside)


def test_the_picture_of_the_data_is_drawn_beside_every_step():
    for step in ("open", "question", "adjust", "save"):
        at = _sample(step)
        assert at.session_state["step_charts"] == step
        assert not at.exception, (step, at.exception)


def test_pick_a_question_shows_the_question_and_folds_split_by_and_summarise():
    at = _sample("question")
    visible = webkit.visible_controls(at)
    assert len(visible) <= webkit.MAX_VISIBLE_CONTROLS, webkit.describe(visible)
    outside = [str(k) for k in _keys(visible)]
    assert any(k.endswith("_field") for k in outside) and any(k.endswith("_kind") for k in outside)
    assert not any(k.endswith("_group") or k.endswith("_agg") for k in outside)
    inside = [str(k) for k in _keys(webkit.all_controls(at))]
    assert any(k.endswith("_group") for k in inside)
    assert [b.key for b in webkit.primary_buttons(at)] == ["dc_next_question"]


def test_choosing_a_question_picks_the_chart_that_fits_on_this_step_already():
    at = _sample("question")
    field = next(s for s in at.selectbox if str(s.key).endswith("_field"))
    field.set_value("Class year").run()
    assert not at.exception, at.exception
    assert at.session_state["dc_cfg"]["column"] == "Class year"
    assert at.session_state["dc_cfg"]["chart_type"] not in ("", None)
    assert at.session_state["dc_built"] is not None


def test_adjust_shows_few_controls_and_folds_the_rest():
    at = _sample("question")
    next(s for s in at.selectbox if str(s.key).endswith("_field")).set_value("Class year").run()
    at.session_state["step_charts"] = "adjust"
    at.run()
    assert not at.exception, at.exception
    visible = webkit.visible_controls(at)
    assert len(visible) <= webkit.MAX_VISIBLE_CONTROLS, webkit.describe(visible)
    outside = [str(k) for k in _keys(visible)]
    assert any(k.endswith("_chart") for k in outside) and any(k.endswith("_title") for k in outside)
    assert [b.key for b in webkit.primary_buttons(at)] == ["dc_next_adjust"]
    for folded in ("_size", "_dl", "_grid", "_preset", "_blanks", "_denom"):
        assert not any(k.endswith(folded) for k in outside), folded


def test_save_offers_the_picture_and_keeping_the_chart_and_folds_the_rest():
    at = _sample("question")
    next(s for s in at.selectbox if str(s.key).endswith("_field")).set_value("Class year").run()
    at.session_state["step_charts"] = "save"
    at.run()
    assert not at.exception, at.exception
    visible = webkit.visible_controls(at)
    assert len(visible) <= webkit.MAX_VISIBLE_CONTROLS, webkit.describe(visible)
    outside = [str(k) for k in _keys(visible)]
    assert any(k.endswith("_fmt") for k in outside) and any(k.endswith("_chart_name") for k in outside)
    assert not any(k.endswith("_dpi") or k.endswith("_transp") for k in outside)
    assert webkit.primary_buttons(at) == [] or all("prep" in str(b.key) for b in webkit.primary_buttons(at))


def test_the_next_buttons_walk_the_four_steps_and_the_step_rail_follows():
    at = _sample("open")
    for here, there in (("open", "question"), ("question", "adjust"), ("adjust", "save")):
        next(b for b in at.button if b.key == f"dc_next_{here}").click().run()
        assert not at.exception, at.exception
        assert at.session_state["step_charts"] == there
    assert not any(str(b.key).startswith("dc_next_") for b in at.button)       # nothing after Save
    rail = next(r for r in at.sidebar.radio if r.key == "rail_charts")
    assert rail.value == "4 Save"


def test_a_step_without_a_file_points_back_to_open():
    at = webkit.start("")
    webkit.go(at, "Data Charts")
    at.session_state["step_charts"] = "adjust"
    at.run()
    assert any(b.key == "dc_go_open" for b in at.button)
    next(b for b in at.button if b.key == "dc_go_open").click().run()
    assert at.session_state["step_charts"] == "open"


def test_the_words_on_the_new_step_buttons_are_plain():
    text = (ROOT / "app" / "data_charts_page.py").read_text(encoding="utf-8")
    new = [s for s in words.ui_strings(text) if s.startswith(("Next:", "Go to Open", "Open a", "Keep this",
                                                              "Prepare the"))]
    assert new
    for string in new:
        assert words.find_never(string) == [] and words.find_replace(string) == [], string


def test_an_agreement_scale_reads_along_the_scale_not_by_count():
    """The belonging question was drawn Somewhat agree first (most chosen), which scrambles the scale."""
    at = _sample("question")
    next(s for s in at.selectbox if str(s.key).endswith("_field")).set_value("I feel like I belong here").run()
    assert not at.exception, at.exception
    assert at.session_state["dc_cfg"]["sort"] == "scale"
    at.session_state["step_charts"] = "adjust"
    at.run()
    assert not at.exception, at.exception
    order_box = next(s for s in at.selectbox if str(s.key).endswith("_sort"))
    assert order_box.options[0].startswith("Scale order") and order_box.value == "scale"


def test_a_field_that_is_not_a_scale_keeps_most_to_fewest():
    at = _sample("question")
    next(s for s in at.selectbox if str(s.key).endswith("_field")).set_value("Class year").run()
    assert not at.exception, at.exception
    assert at.session_state["dc_cfg"]["sort"] == "desc"


def test_split_by_offers_only_fields_a_chart_can_be_split_by():
    at = _sample("question")
    next(s for s in at.selectbox if str(s.key).endswith("_field")).set_value("I feel like I belong here").run()
    split = next(m for m in at.multiselect if str(m.key).endswith("_group"))
    offered = set(split.options)
    assert {"Class year", "Residence", "First generation"} <= offered
    for nonsense in ("Respondent", "Comment", "Concerns", "Survey date", "Hours per week"):
        assert nonsense not in offered, nonsense
