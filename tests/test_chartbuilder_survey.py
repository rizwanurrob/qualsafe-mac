"""
Chart Builder survey structures: Likert matrices and top/bottom boxes,
select-all-that-apply parsing (including choices that contain the delimiter), free
text, and chart recommendations.

Expected numbers are worked by hand in the comments.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.chartbuilder import export, recommend, survey
from core.chartbuilder.aggregate import ChartBuildError, aggregate
from core.chartbuilder.build import build_data
from core.chartbuilder.config import ChartConfig, Merge, MultiSelect
from core.chartbuilder.profile import profile_table
from core.chartbuilder.render import build_spec

AGREE = ["Strongly disagree", "Somewhat disagree", "Neutral", "Somewhat agree",
         "Strongly agree"]

R1 = "Relationships with friends, family, partners, or roommates"
R2 = "Getting involved or finding community"
R3 = "Managing anxiety, stress, or feeling overwhelmed"
BRIEF_CELL = f"{R1},{R2},{R3}"          # the exact string from the brief (no spaces after ,)


# ── ordered scales ────────────────────────────────────────────────────────────

def test_likert_ordering_is_by_scale_not_alphabet_or_frequency():
    shuffled = ["Strongly agree", "Neutral", "No opinion", "Strongly disagree",
                "Somewhat agree", "Somewhat disagree"]
    ordered, scale = survey.order_by_scale(shuffled)
    assert scale == "agreement"
    assert ordered == ["Strongly disagree", "Somewhat disagree", "Neutral",
                       "Somewhat agree", "Strongly agree", "No opinion"]


def test_importance_scale_order_and_agree_disagree_are_not_confused():
    ordered, scale = survey.order_by_scale(
        ["Extremely", "No opinion", "Slightly", "Very", "Not at all", "Moderately"])
    assert scale == "importance"
    assert ordered == ["Not at all", "Slightly", "Moderately", "Very", "Extremely",
                       "No opinion"]
    five, _ = survey.order_by_scale(["Agree", "Strongly agree", "Disagree",
                                     "Strongly disagree", "Neutral"])
    assert five == ["Strongly disagree", "Disagree", "Neutral", "Agree", "Strongly agree"]


def test_unrecognised_categories_keep_the_data_order():
    cats = ["Cat", "Dog", "Bird"]
    assert survey.order_by_scale(cats) == (cats, None)


def _matrix_frame():
    """Item A: 10 answers, item B: 8 + 2 blanks. Numbers are easy to check."""
    a = ["Strongly agree"] * 4 + ["Somewhat agree"] * 3 + ["Neutral"] * 1 \
        + ["Somewhat disagree"] * 1 + ["Strongly disagree"] * 1
    b = ["Strongly agree"] * 1 + ["Somewhat agree"] * 2 + ["Neutral"] * 2 \
        + ["Somewhat disagree"] * 2 + ["Strongly disagree"] * 1 + ["", "NA"]
    return pd.DataFrame({"Belong": a, "Safe": b})


def _matrix_cfg(**kw):
    cfg = ChartConfig(kind="matrix", columns=["Belong", "Safe"],
                      sort=kw.pop("sort", "scale"),
                      aggregation=kw.pop("aggregation", "percent"),
                      chart_type=kw.pop("chart_type", "normalized_bar"), **kw)
    return cfg


def test_matrix_uses_items_as_groups_with_per_item_valid_n():
    d, _ = build_data(_matrix_frame(), _matrix_cfg())
    assert d.groups == ["Belong", "Safe"] and d.categories == AGREE
    t = d.table
    belong = t[t["group"] == "Belong"]
    safe = t[t["group"] == "Safe"]
    assert belong["valid_n"].iloc[0] == 10 and safe["valid_n"].iloc[0] == 8
    assert safe["missing_n"].iloc[0] == 2
    row = belong[belong["category"] == "Strongly agree"].iloc[0]
    assert (row["count"], row["denominator"], row["percent"]) == (4, 10, 40.0)
    assert row["display_label"] == "40% (4/10)"
    assert belong["percent"].sum() == pytest.approx(100) == safe["percent"].sum()


def test_matrix_needs_two_columns_and_refuses_a_grouping_field():
    with pytest.raises(ChartBuildError, match="two or more"):
        aggregate(_matrix_frame(), ChartConfig(kind="matrix", columns=["Belong"]))
    with pytest.raises(ChartBuildError, match="items as groups"):
        aggregate(_matrix_frame(), ChartConfig(kind="matrix", columns=["Belong", "Safe"],
                                               group_by=["Belong"]))


def test_matrix_item_rename_is_display_only_and_collisions_are_refused():
    cfg = _matrix_cfg()
    cfg.recode.item_rename = {"Belong": "I feel I belong here"}
    d, _ = build_data(_matrix_frame(), cfg)
    assert d.groups == ["I feel I belong here", "Safe"]
    cfg.recode.item_rename = {"Belong": "Same", "Safe": "Same"}
    with pytest.raises(ChartBuildError, match="same display name"):
        aggregate(_matrix_frame(), cfg)


def test_matrix_manual_order_beats_scale_order():
    cfg = _matrix_cfg(sort="custom")
    cfg.recode.order = list(reversed(AGREE))
    d, _ = build_data(_matrix_frame(), cfg)
    assert d.categories == list(reversed(AGREE))


# ── top / bottom box ──────────────────────────────────────────────────────────

def test_top_two_box_counts_and_labels_hand_checked():
    # Belong: SA 4 + SwA 3 = 7 of 10.  Safe: SA 1 + SwA 2 = 3 of 8 (blanks excluded).
    d, _ = build_data(_matrix_frame(), _matrix_cfg(aggregation="count"))
    box = survey.box_summary(d, _matrix_cfg())
    top2 = box[box["Box"] == "Top 2 boxes"].set_index("Item")
    assert top2.loc["Belong", ["Count", "Valid N", "Percent"]].tolist() == [7, 10, 70.0]
    assert top2.loc["Safe", ["Count", "Valid N", "Percent"]].tolist() == [3, 8, 37.5]
    assert top2.loc["Belong", "Label"] == "70% (7/10)"
    assert top2.loc["Belong", "Categories"] == "Somewhat agree + Strongly agree"


def test_all_four_standard_boxes_and_bottom_two():
    d, _ = build_data(_matrix_frame(), _matrix_cfg())
    cfg = _matrix_cfg()
    cfg.boxes.top, cfg.boxes.bottom = [1, 2], [1, 2]
    box = survey.box_summary(d, cfg)
    assert list(dict.fromkeys(box["Box"])) == ["Top 1 box", "Top 2 boxes",
                                               "Bottom 1 box", "Bottom 2 boxes"]
    b = box[(box["Item"] == "Safe") & (box["Box"] == "Bottom 2 boxes")].iloc[0]
    assert b["Count"] == 3 and b["Categories"] == "Strongly disagree + Somewhat disagree"


def test_custom_box_and_box_wider_than_the_scale_is_skipped():
    d, _ = build_data(_matrix_frame(), _matrix_cfg())
    cfg = _matrix_cfg()
    cfg.boxes.top, cfg.boxes.bottom = [5], []
    cfg.boxes.custom = [Merge("Favourable", ["Somewhat agree", "Strongly agree"])]
    box = survey.box_summary(d, cfg)
    assert list(box["Box"].unique()) == ["Favourable"]        # top-5 of 5 is everyone


def test_off_scale_answers_are_not_scale_points_and_the_base_is_a_choice():
    df = pd.DataFrame({"Q1": ["Very"] * 3 + ["Not at all"] * 2 + ["Moderately"] * 2 +
                       ["No opinion"] * 3,
                       "Q2": ["Very"] * 10})
    cfg = ChartConfig(kind="matrix", columns=["Q1", "Q2"], sort="scale",
                      aggregation="count")
    d, _ = build_data(df, cfg)
    assert d.categories[-1] == "No opinion"
    cfg.boxes.top, cfg.boxes.bottom = [1], []
    top = survey.box_summary(d, cfg)
    q1 = top[top["Item"] == "Q1"].iloc[0]
    assert (q1["Count"], q1["Valid N"], q1["Percent"]) == (3, 10, 30.0)   # base keeps No opinion
    cfg.boxes.exclude_off_scale = True
    q1 = survey.box_summary(d, cfg).query("Item == 'Q1'").iloc[0]
    assert (q1["Count"], q1["Valid N"]) == (3, 7)
    assert q1["Percent"] == pytest.approx(42.9, abs=0.05)


def test_valid_n_is_never_shown_as_the_count_selecting():
    d, _ = build_data(_matrix_frame(), _matrix_cfg())
    labels_ = set(d.table["display_label"])
    assert "40% (4/10)" in labels_
    assert all("%" in label and "/" in label for label in labels_)   # never a bare N


# ── matrix rendering ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("ctype", ["normalized_bar", "stacked_bar", "grouped_bar",
                                   "bar", "bar_horizontal", "heatmap", "pie", "donut"])
def test_every_matrix_chart_is_valid_vega_lite(ctype):
    alt = pytest.importorskip("altair")
    cfg = _matrix_cfg(chart_type=ctype,
                      aggregation="count" if ctype == "stacked_bar" else "percent")
    cfg.labels.title, cfg.labels.footnote = "T", "Source"
    d, t = build_data(_matrix_frame(), cfg)
    spec = build_spec(d, cfg, t)
    alt.Chart.from_dict(spec) if "layer" in spec else alt.VConcatChart.from_dict(spec)


def test_matrix_grouped_bar_puts_items_on_the_axis_and_responses_in_the_legend():
    cfg = _matrix_cfg(chart_type="grouped_bar")
    d, t = build_data(_matrix_frame(), cfg)
    spec = build_spec(d, cfg, t)
    enc = spec["layer"][0]["encoding"]
    assert enc["y"]["sort"] == ["Belong", "Safe"]
    assert enc["color"]["scale"]["domain"] == AGREE
    assert enc["color"]["scale"]["range"][0] == "#A7A8AA"        # Strongly disagree = silver
    # drawing swaps roles on a copy: the canonical data is unchanged
    assert set(d.table["group"]) == {"Belong", "Safe"}


def test_matrix_pies_make_one_panel_per_item_with_a_shared_legend():
    cfg = _matrix_cfg(chart_type="donut")
    d, t = build_data(_matrix_frame(), cfg)
    spec = build_spec(d, cfg, t)
    grid = spec["vconcat"][0]
    assert len(grid["concat"]) == 2
    assert grid["resolve"]["scale"]["color"] == "shared"
    assert [p["title"]["text"] for p in grid["concat"]] == [["Belong"], ["Safe"]]


# ── select-all: parsing ───────────────────────────────────────────────────────

CHOICES = [R1, R2, R3]


def test_brief_string_resolves_to_exactly_three_categories_with_known_choices():
    picked, extra = survey.match_known(BRIEF_CELL, CHOICES, ",")
    assert picked == [R1, R2, R3] and extra == []
    assert len(picked) == 3


def test_simple_split_fragments_the_same_string_which_is_why_known_mode_exists():
    pieces = survey.split_simple(BRIEF_CELL, ",")
    assert len(pieces) == 8                     # 4 + 1 + 3: simple split shatters R1 and R3
    assert R1 not in pieces


def test_known_matching_handles_spaces_case_order_and_repeats():
    cell = f"{R3}, {R2.upper()} ,  {R1} , {R3}"
    picked, extra = survey.match_known(cell, CHOICES, ",")
    assert picked == [R3, R2, R1] and extra == []      # canonical spelling, order kept, deduped


def test_a_choice_must_be_a_complete_phrase_not_a_prefix():
    # "Other" is a complete phrase up to the comma, so it matches; the rest is reported.
    picked, extra = survey.match_known("Other, please specify", ["Other"], ",")
    assert picked == ["Other"] and extra == ["please specify"]
    picked, extra = survey.match_known("Other, please specify",
                                       ["Other", "Other, please specify"], ",")
    assert picked == ["Other, please specify"] and extra == []       # longest first


def test_unmatched_pieces_are_returned_not_dropped_or_split_further():
    picked, extra = survey.match_known(f"{R1}, Something else entirely, {R2}", CHOICES, ",")
    assert picked == [R1, R2] and extra == ["Something else entirely"]


@pytest.mark.parametrize("delim,char", [("semicolon", ";"), ("pipe", "|"),
                                        ("custom", "~~")])
def test_other_delimiters(delim, char):
    cell = char.join(["a, b", "c", "d"])
    m = MultiSelect(mode="known", delimiter=delim, custom_delimiter="~~",
                    choices=["a, b", "c", "d"])
    assert survey.parse_multi(pd.Series([cell]), m).choices == [["a, b", "c", "d"]]


def test_newline_delimiter():
    cell = "\n".join([R1, R2])
    m = MultiSelect(mode="known", delimiter="newline", choices=CHOICES)
    assert survey.parse_multi(pd.Series([cell]), m).choices == [[R1, R2]]
    simple = MultiSelect(mode="simple", delimiter="newline")
    assert survey.parse_multi(pd.Series([cell]), simple).choices == [[R1, R2]]


def test_blank_cells_are_missing_not_empty_selections():
    m = MultiSelect(mode="known", choices=CHOICES)
    parsed = survey.parse_multi(pd.Series([BRIEF_CELL, float("nan"), R2]), m)
    assert parsed.choices == [[R1, R2, R3], None, [R2]] and parsed.n_valid == 2


def test_suggestions_rejoin_pieces_a_comma_cut_apart():
    cells = pd.Series([BRIEF_CELL, f"{R1},{R2}", R3, f"{R2},{R3}", R1] * 3)
    got = {s.choice: s for s in survey.suggest_choices(cells, ",")}
    assert set(got) == {R1, R2, R3}
    assert got[R1].fragments and len(got[R1].fragments) == 4
    assert got[R3].fragments == ["Managing anxiety", "stress", "or feeling overwhelmed"]
    assert got[R2].fragments == []


def test_suggestions_leave_genuinely_independent_pieces_alone():
    cells = pd.Series(["red, blue", "blue, green", "green, red", "red", "blue, red"] * 4)
    assert {s.choice for s in survey.suggest_choices(cells, ",")} == {"red", "blue", "green"}


# ── select-all: aggregation ───────────────────────────────────────────────────

def _multi_frame():
    return pd.DataFrame({
        "Concerns": [BRIEF_CELL, f"{R1},{R2}", R3, "", f"{R2},{R3}", "NA", R1],
        "Year": ["A", "A", "B", "B", "B", "A", "A"]})


def _multi_cfg(**kw):
    return ChartConfig(kind="multi", column="Concerns", chart_type="bar_horizontal",
                       multi=MultiSelect(mode="known", choices=CHOICES), **kw)


def test_multi_denominator_is_respondents_with_a_valid_response():
    # 7 rows, 2 blank -> 5 valid respondents. R1: rows 1,2,7 = 3. R2: 1,2,5 = 3. R3: 1,3,5 = 3.
    d, _ = build_data(_multi_frame(), _multi_cfg())
    assert d.valid_n == 5 and d.missing_n == 2
    for cat in CHOICES:
        row = d.table[d.table["category"] == cat].iloc[0]
        assert (row["count"], row["denominator"]) == (3, 5)
        assert row["percent"] == pytest.approx(60.0)
    assert set(d.categories) == set(CHOICES) and len(d.categories) == 3
    assert d.table["percent"].sum() == pytest.approx(180.0)        # need not sum to 100


def test_multi_chart_carries_the_required_label():
    d, t = build_data(_multi_frame(), _multi_cfg())
    assert d.value_title == ("Percent of respondents selecting each option; "
                             "multiple selections allowed")
    spec = build_spec(d, _multi_cfg(), t)
    assert spec["layer"][0]["encoding"]["x"]["title"] == d.value_title
    assert "more than 100%" in d.base_note
    counts, _ = build_data(_multi_frame(), _multi_cfg(aggregation="count"))
    assert counts.value_title.startswith("Number of respondents selecting each option")


def test_multi_sorts_highest_first_and_known_order_is_the_source_order():
    df = pd.DataFrame({"C": [R3, R3, R3, R2, R2, R1]})
    d, _ = build_data(df, _multi_cfg().__class__(kind="multi", column="C", sort="desc",
                                                 multi=MultiSelect(choices=CHOICES)))
    assert d.categories == [R3, R2, R1]
    d, _ = build_data(df, ChartConfig(kind="multi", column="C", sort="source",
                                      multi=MultiSelect(choices=CHOICES)))
    assert d.categories == CHOICES


def test_multi_grouping_uses_per_group_respondents():
    d, _ = build_data(_multi_frame(), _multi_cfg(group_by=["Year"]))
    a = d.table[(d.table["group"] == "A") & (d.table["category"] == R1)].iloc[0]
    # Year A valid respondents: rows 1,2,7 (row 6 is "NA") -> 3; all three chose R1.
    assert (a["count"], a["denominator"]) == (3, 3)


def test_multi_unmatched_pieces_are_reported_not_charted():
    df = pd.DataFrame({"C": [f"{R1}, Mystery answer", R2, "Mystery answer"]})
    d, _ = build_data(df, ChartConfig(kind="multi", column="C",
                                      multi=MultiSelect(choices=CHOICES)))
    assert "Mystery answer" not in d.categories
    assert d.notes["unmatched"] == {"Mystery answer": 2}
    assert any("did not match any known choice" in w for w in d.warnings)
    d, _ = build_data(df, ChartConfig(kind="multi", column="C",
                                      multi=MultiSelect(choices=CHOICES, include_unmatched=True)))
    assert "Mystery answer" in d.categories


def test_multi_simple_mode_warns_when_the_delimiter_looks_unsafe():
    df = pd.DataFrame({"C": [BRIEF_CELL, f"{R1},{R2}", R3, f"{R2},{R3}", R1] * 3})
    d, _ = build_data(df, ChartConfig(kind="multi", column="C",
                                      multi=MultiSelect(mode="simple")))
    assert any("cut them into pieces" in w for w in d.warnings)
    assert R1 not in d.categories                   # and the fragments show up, as warned


def test_multi_recode_rename_merge_and_exclude_apply_to_choices():
    cfg = _multi_cfg()
    cfg.recode.rename = {R1: "Relationships"}
    cfg.recode.merges = [Merge("Wellbeing", [R3, R2])]
    d, _ = build_data(_multi_frame(), cfg)
    assert set(d.categories) == {"Relationships", "Wellbeing"}
    w = d.table[d.table["category"] == "Wellbeing"].iloc[0]
    assert w["count"] == 4        # rows 1,2,3,5 chose R2 or R3 (a respondent counts once)
    cfg = _multi_cfg()
    cfg.recode.exclude = [R1]
    d, _ = build_data(_multi_frame(), cfg)
    assert R1 not in d.categories and d.valid_n == 5      # respondents stay in the base


def test_multi_config_problems_are_sentences():
    assert "list of response choices" in ChartConfig(kind="multi", column="C").problems()[0]
    assert any("custom delimiter" in p for p in ChartConfig(
        kind="multi", column="C", multi=MultiSelect(mode="simple", delimiter="custom")).problems())
    assert any("counted, not summed" in p for p in ChartConfig(
        kind="multi", column="C", aggregation="sum", value_field="x",
        multi=MultiSelect(mode="simple")).problems())


# ── free text ─────────────────────────────────────────────────────────────────

TEXT = pd.Series([
    "The advising office was helpful and friendly",
    "Advising was slow, but the office staff were helpful",
    "Financial aid was confusing",
    "", "N/A",
    "Housing costs are too high; financial aid did not cover housing"])


def test_text_summary_counts_responses_and_keywords_once_per_response():
    s = survey.text_summary(TEXT)
    assert (s.n_rows, s.n_responses, s.n_missing) == (6, 4, 2)
    kw = s.keywords.set_index("word")
    assert kw.loc["advising", "responses"] == 2 and kw.loc["helpful", "responses"] == 2
    assert kw.loc["housing", "mentions"] == 2 and kw.loc["housing", "responses"] == 1
    assert kw.loc["financial", "percent"] == 50.0
    assert "the" not in kw.index and "was" not in kw.index          # stop words gone
    assert s.mean_words == pytest.approx((7 + 9 + 4 + 11) / 4)


def test_text_field_is_not_forced_into_categories_but_can_be_asked_for():
    d, t = build_data(pd.DataFrame({"Comment": TEXT}),
                      ChartConfig(kind="text", column="Comment", aggregation="percent"))
    assert d.kind == "text" and d.valid_n == 4 and "advising" in d.categories
    assert d.table["display_label"].iloc[0].startswith("50% (2/4)")
    build_spec(d, ChartConfig(kind="text", column="Comment"), t)


def test_text_responses_export_skips_blanks_and_keeps_row_numbers():
    frame = pd.DataFrame({"Comment": TEXT, "ID": list("abcdef")})
    out = survey.responses_frame(frame, "Comment")
    assert out["Row"].tolist() == [2, 3, 4, 7]                     # spreadsheet rows
    assert len(out) == 4
    by_id = survey.responses_frame(frame, "Comment", id_column="ID")
    assert by_id["ID"].tolist() == ["a", "b", "c", "f"]
    assert export.table_csv(by_id).startswith(b"\xef\xbb\xbf")


def test_max_categories_keeps_the_largest_and_says_so():
    df = pd.DataFrame({"Q": ["a"] * 5 + ["b"] * 4 + ["c"] * 3 + ["d"] * 2 + ["e"]})
    cfg = ChartConfig(column="Q", sort="alpha")
    cfg.display.max_categories = 3
    d, _ = build_data(df, cfg)
    assert d.categories == ["a", "b", "c"]
    assert any("3 largest of 5" in w for w in d.warnings)


# ── recommendations ───────────────────────────────────────────────────────────

def _rec(cfg, frame=None, **kw):
    table = profile_table(frame) if frame is not None else None
    return recommend.recommend(cfg, table, **kw)


def test_recommendations_follow_the_brief_and_never_force_a_pie():
    assert _rec(ChartConfig(kind="matrix", columns=["a", "b"]))[0].chart_type == "normalized_bar"
    assert _rec(ChartConfig(kind="multi", column="c"))[0].chart_type == "bar_horizontal"
    few = _rec(ChartConfig(column="q"), n_categories=4)
    assert few[0].primary and few[0].chart_type == "bar_horizontal"
    assert {"donut", "pie"} <= {r.chart_type for r in few}
    many = _rec(ChartConfig(column="q"), n_categories=12)
    assert [r.chart_type for r in many][0] == "bar_horizontal"
    assert "pie" not in {r.chart_type for r in many}
    for recs in (few, many, _rec(ChartConfig(kind="matrix", columns=["a", "b"]))):
        assert recs[0].chart_type not in ("pie", "donut")
        assert sum(r.primary for r in recs) == 1


def test_ordered_scale_questions_do_not_get_a_pie_offered():
    recs = _rec(ChartConfig(column="q"), n_categories=5, categories=AGREE)
    assert "pie" not in {r.chart_type for r in recs}


def test_dates_numbers_and_pairs_recommend_the_right_marks():
    frame = pd.DataFrame({"when": ["2026-01-01", "2026-02-01", "2026-03-01"],
                          "score": [str(i * 3.7) for i in range(3)],
                          "age": ["21.5", "30.2", "44.9"]})
    line = _rec(ChartConfig(column="when"), frame)
    assert line[0].chart_type == "line" and line[0].available
    hist = _rec(ChartConfig(column="score"), frame)
    assert hist[0].chart_type == "histogram" and hist[0].available
    pair = _rec(ChartConfig(column="score", value_field="age"), frame)
    assert pair[0].chart_type == "scatter" and pair[0].available
    assert _rec(ChartConfig(column="q", group_by=["g"]), n_categories=3)[0].chart_type == "grouped_bar"
    assert next(r for r in few_bars() if r.chart_type == "bar").available


def few_bars():
    return _rec(ChartConfig(column="q"), n_categories=3)


def test_wrapped_category_labels_break_lines_through_an_expression():
    """Vega draws a string containing a newline on one line; only an array wraps."""
    df = pd.DataFrame({"C": [BRIEF_CELL] * 3})
    cfg = ChartConfig(kind="multi", column="C", multi=MultiSelect(choices=CHOICES))
    d, t = build_data(df, cfg)
    axis = build_spec(d, cfg, t)["layer"][0]["encoding"]["y"]["axis"]
    assert axis["labelExpr"] == "split(datum.label, '" + chr(92) + "n')"
    cfg.display.wrap_labels = False
    assert "labelExpr" not in build_spec(d, cfg, t)["layer"][0]["encoding"]["y"]["axis"]


def test_narrow_pie_slices_get_a_short_label_not_an_overlapping_one():
    df = pd.DataFrame({"Q": ["a"] * 80 + ["b"] * 14 + ["c"] * 4 + ["d"] * 2})
    cfg = ChartConfig(column="Q", chart_type="donut")
    d, t = build_data(df, cfg)
    rows = {r["category"]: r["arc_label"] for r in build_spec(d, cfg, t)["data"]["values"]}
    assert rows == {"a": "80% (80/100)", "b": "14% (14/100)", "c": "", "d": ""}
    df = pd.DataFrame({"Q": ["a"] * 88 + ["b"] * 8 + ["c"] * 4})
    d, t = build_data(df, cfg)
    rows = {r["category"]: r["arc_label"] for r in build_spec(d, cfg, t)["data"]["values"]}
    assert rows["b"] == "8%" and rows["c"] == ""
