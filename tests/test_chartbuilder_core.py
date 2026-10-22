"""
Chart Builder core: loading, profiling, cleaning, config/undo, recode, and the
aggregation engine that produces the canonical table.

The numbers asserted here are worked by hand in the comments; none is copied from
the program's own output.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.chartbuilder import clean, labels, loader, profile
from core.chartbuilder.aggregate import CANONICAL_COLUMNS, ChartBuildError, aggregate
from core.chartbuilder.build import build_data
from core.chartbuilder.config import (
    ChartConfig, EditHistory, FilterRule, Merge)


def _frame(**cols):
    return pd.DataFrame(cols)


# ── loader ────────────────────────────────────────────────────────────────────

def test_csv_delimiter_is_sniffed():
    for delim in (",", ";", "\t", "|"):
        raw = delim.join(["a", "b"]) + "\n" + delim.join(["1", "x"]) + "\n"
        t = loader.load_bytes(raw.encode(), "d.csv")
        assert list(t.frame.columns) == ["a", "b"], repr(delim)
        assert t.delimiter == delim


def test_cp1252_csv_loads_and_says_so():
    raw = "q\nIt’s fine\n".encode("cp1252")
    t = loader.load_bytes(raw, "d.csv")
    assert t.frame["q"][0] == "It’s fine"
    assert t.encoding == "cp1252" and t.notes


def test_csv_keeps_na_tokens_and_leading_zeros_as_text():
    t = loader.load_bytes(b"id,ans\n007,NA\n008,None\n009,\n", "d.csv")
    assert list(t.frame["id"]) == ["007", "008", "009"]
    assert list(t.frame["ans"]) == ["NA", "None", ""]


def test_duplicate_headers_are_numbered_not_lost():
    t = loader.load_bytes(b"q,q,\n1,2,3\n", "d.csv")
    assert list(t.frame.columns) == ["q", "q (2)", "Column 3"]
    assert any("repeated" in n for n in t.notes)


def test_excel_lists_sheets_and_loads_the_chosen_one():
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as book:
        pd.DataFrame({"a": [1, 2]}).to_excel(book, sheet_name="First", index=False)
        pd.DataFrame({"b": ["x", None, "z"]}).to_excel(book, sheet_name="Second", index=False)
    data = buf.getvalue()
    assert loader.list_sheets(data, "w.xlsx") == ["First", "Second"]
    t = loader.load_bytes(data, "w.xlsx", sheet="Second")
    assert t.sheet == "Second" and t.n_rows == 3 and t.sheets == ["First", "Second"]
    assert list(t.frame["b"]) == ["x", "", "z"]          # blank is "" like CSV
    with pytest.raises(ValueError, match="Sheet 'Nope'"):
        loader.load_bytes(data, "w.xlsx", sheet="Nope")


def test_unsupported_and_empty_files_are_refused_in_words():
    with pytest.raises(loader.UnsupportedFileError, match=r"\.pdf"):
        loader.load_bytes(b"x", "d.pdf")
    with pytest.raises(ValueError, match="empty"):
        loader.load_bytes(b"", "d.csv")


def test_loading_does_not_modify_the_source_bytes(tmp_path):
    p = tmp_path / "d.csv"
    p.write_bytes(b"a,b\n 1 ,NA\n")
    before = p.read_bytes()
    t = loader.load_path(p)
    clean.normalize_series(t.frame["a"])
    assert p.read_bytes() == before
    assert t.frame["a"][0] == " 1 "                        # frame itself untouched


# ── profiling ─────────────────────────────────────────────────────────────────

def test_type_inference():
    f = _frame(
        cat=["Yes", "No", "Yes", "No"],
        num=["1.5", "2", "3", "4"],
        day=["2026-01-01", "2026-02-03", "2026-03-04", "2026-04-05"],
        flag=["true", "false", "TRUE", "False"],
        essay=["x" * 90, "y" * 95, "z" * 80, "w" * 100],
        blank=["", "NA", "null", ""])
    p = profile.profile_table(f)
    kinds = {c.name: c.kind for c in p.columns}
    assert kinds == {"cat": "categorical", "num": "numeric", "day": "datetime",
                     "flag": "boolean", "essay": "text", "blank": "empty"}
    assert (p.n_rows, p.n_cols) == (4, 6)


def test_missing_counts_and_tokens_are_reported():
    f = _frame(q=["a", "", "NA", "None", "null", "b"])
    col = profile.profile_column(f["q"])
    assert col.n_missing == 4 and col.n_valid == 2
    assert col.missing_tokens_found == {"NA": 1, "None": 1, "null": 1}
    assert any("Treated as missing" in w for w in col.warnings)


def test_numeric_scale_codes_are_flagged_for_categorical_use():
    col = profile.profile_column(pd.Series([1, 2, 3, 4, 5, 3, 3, 2], name="lik"))
    assert col.kind == "numeric" and col.numeric_like_scale
    wide = profile.profile_column(pd.Series(range(200), name="score"))
    assert not wide.numeric_like_scale


def test_multiselect_is_detected_but_free_text_is_not():
    multi = pd.Series(["a; b", "b; c", "a; c", "a; b; c", "c"] * 6, name="m")
    assert profile.profile_column(multi).multiselect_delimiter == "semicolon"
    prose = pd.Series([f"I think, on balance, that thing number {i} matters"
                       for i in range(30)], name="p")   # 1 piece in 3 is unique
    assert profile.profile_column(prose).multiselect_delimiter is None


def test_high_cardinality_warning():
    col = profile.profile_column(pd.Series([f"prog {i % 40}" for i in range(80)], name="p"))
    assert any("distinct values" in w for w in col.warnings)


# ── cleaning ──────────────────────────────────────────────────────────────────

def test_normalize_strips_and_nulls_the_listed_tokens():
    s = pd.Series([" Yes ", "yes", "", "NULL", "null", "NaN", "None", "N/A", "NA",
                   "(blank)", "<null>", None, float("nan"), "  "])
    out = clean.normalize_series(s)
    assert list(out.dropna()) == ["Yes", "yes"]
    assert out.isna().sum() == 12


def test_collapse_whitespace_is_optional():
    s = pd.Series(["a  b", "a b"])
    assert list(clean.normalize_series(s)) == ["a  b", "a b"]
    assert list(clean.normalize_series(s, collapse_whitespace=True)) == ["a b", "a b"]


def test_similar_labels_are_reported_not_merged():
    assert clean.similar_label_groups(["a  b", "a b", "c"]) == \
        [{"labels": ["a  b", "a b"], "reason": "whitespace"}]
    assert clean.similar_label_groups(["Yes", "yes"])[0]["reason"] == "case"


def test_whole_floats_read_as_integers():
    assert clean.label_of(3.0) == "3" and clean.label_of(2.5) == "2.5"
    assert clean.label_of(True) == "True"


# ── labels ────────────────────────────────────────────────────────────────────

def test_data_label_keeps_numerator_and_valid_n_distinct():
    assert labels.display_label(519, 558, 93.0) == "93% (519/558)"
    assert labels.display_label(519, 558, 93.0, show_valid_n=False) == "93% (519)"
    assert labels.display_label(519, 558, 93.0, show_count=False) == "93% of 558"
    assert labels.display_label(519, 558, 93.0, show_percent=False) == "519/558"
    assert labels.display_label(519, 558, 93.0, lead="count") == "519/558 (93%)"


def test_percent_rounds_half_up_not_to_even():
    assert labels.format_percent(12.5) == "13%" and labels.format_percent(13.5) == "14%"
    assert labels.format_percent(12.25, 1) == "12.3%"


# ── config, history ───────────────────────────────────────────────────────────

def test_config_round_trips_through_json_and_ignores_unknown_keys():
    cfg = ChartConfig(column="Q1", group_by=["Year"], chart_type="grouped_bar")
    cfg.recode.rename = {"a": "A"}
    cfg.recode.merges = [Merge("Agree", ["Somewhat agree", "Strongly agree"])]
    cfg.filters = [FilterRule("Year", "in", ["1", "2"])]
    cfg.labels.title = "T"
    import json
    back = ChartConfig.from_dict(json.loads(json.dumps(cfg.to_dict())))
    assert back.to_dict() == cfg.to_dict()
    assert back.recode.merges[0].members == ["Somewhat agree", "Strongly agree"]
    future = cfg.to_dict() | {"from_the_future": 1}
    assert ChartConfig.from_dict(future).column == "Q1"
    assert ChartConfig.from_dict(None).theme.name == "QualSafe default"


def test_config_problems_are_sentences():
    assert "Choose a field" in ChartConfig().problems()[0]
    assert any("value field" in p for p in ChartConfig(column="a", aggregation="mean").problems())
    assert any("pie" in p for p in ChartConfig(column="a", chart_type="pie",
                                                group_by=["b"]).problems())
    assert ChartConfig(column="a").problems() == []


def test_edit_history_undoes_every_kind_of_edit():
    h = EditHistory(ChartConfig(column="Q"))
    c = h.current; c.filters = [FilterRule("Y", "in", ["1"])]; h.push(c)
    c = h.current; c.recode.rename = {"a": "b"}; h.push(c)
    c = h.current; c.sort = "alpha"; h.push(c)
    c = h.current; c.recode.merges = [Merge("X", ["a", "b"])]; h.push(c)
    assert h.current.recode.merges and h.can_undo
    assert not h.undo().recode.merges
    assert h.undo().sort == "desc"
    assert h.undo().recode.rename == {}
    assert h.undo().filters == []
    assert not h.can_undo and h.current.column == "Q"
    assert h.redo().filters and h.can_redo


def test_history_ignores_no_op_edits_and_reset_is_undoable():
    h = EditHistory(ChartConfig(column="Q"))
    h.push(h.current)
    assert not h.can_undo
    h.reset()
    assert h.current.column == "" and h.can_undo
    assert h.undo().column == "Q"


# ── aggregation: the numbers ──────────────────────────────────────────────────

SURVEY = _frame(
    Q=["Yes", "Yes", "No", "Maybe", "Yes", "No", "", "NA", "  ", "Yes"],
    Year=["A", "A", "A", "B", "B", "B", "A", "B", "A", "B"],
    Score=["10", "20", "30", "40", "50", "60", "70", "x", "", "5"])


def _cell(data, category, group=""):
    t = data.table
    return t[(t["category"] == category) & (t["group"] == group)].iloc[0]


def test_blanks_and_tokens_are_out_of_the_denominator():
    # 10 rows: 3 blank/token -> 7 valid. Yes=4, No=2, Maybe=1.
    d, _ = build_data(SURVEY, ChartConfig(column="Q"))
    yes = _cell(d, "Yes")
    assert (yes["count"], yes["denominator"], d.valid_n, d.missing_n) == (4, 7, 7, 3)
    assert yes["percent"] == pytest.approx(400 / 7)
    assert list(d.table.columns) == CANONICAL_COLUMNS
    assert d.table["percent"].sum() == pytest.approx(100.0)


def test_all_rows_and_custom_denominators_are_explicit_choices():
    d, _ = build_data(SURVEY, ChartConfig(column="Q", denominator="all_rows"))
    assert _cell(d, "Yes")["denominator"] == 10
    assert _cell(d, "Yes")["percent"] == pytest.approx(40.0)
    d, _ = build_data(SURVEY, ChartConfig(column="Q", denominator="custom",
                                          custom_denominator=200))
    assert _cell(d, "Yes")["percent"] == pytest.approx(2.0)
    assert _cell(d, "Yes")["display_label"] == "2% (4/200)"
    with pytest.raises(ChartBuildError, match="greater than zero"):
        aggregate(SURVEY, ChartConfig(column="Q", denominator="custom"))


def test_showing_blanks_adds_a_category_without_changing_the_base():
    cfg = ChartConfig(column="Q")
    cfg.recode.show_missing = True
    d, _ = build_data(SURVEY, cfg)
    blank = _cell(d, "No response")
    assert blank["count"] == 3 and d.categories[-1] == "No response"
    assert _cell(d, "Yes")["denominator"] == 7
    assert any("more than 100%" in w for w in d.warnings)
    cfg.denominator = "all_rows"
    d, _ = build_data(SURVEY, cfg)
    assert not any("more than 100%" in w for w in d.warnings)
    assert d.table[d.table["category"] != ""]["percent"].sum() == pytest.approx(100.0)


def test_count_and_percent_switch_changes_only_the_plotted_value():
    p, _ = build_data(SURVEY, ChartConfig(column="Q", aggregation="percent"))
    c, _ = build_data(SURVEY, ChartConfig(column="Q", aggregation="count"))
    assert list(p.table["count"]) == list(c.table["count"])
    assert _cell(p, "Yes")["value"] == pytest.approx(400 / 7)
    assert _cell(c, "Yes")["value"] == 4
    assert _cell(p, "Yes")["display_label"].startswith("57%")
    assert _cell(c, "Yes")["display_label"].startswith("4/7")     # count leads


def test_sort_orders():
    def order(**kw):
        d, _ = build_data(SURVEY, ChartConfig(column="Q", **kw))
        return d.categories
    assert order(sort="desc") == ["Yes", "No", "Maybe"]
    assert order(sort="asc") == ["Maybe", "No", "Yes"]
    assert order(sort="alpha") == ["Maybe", "No", "Yes"]
    assert order(sort="source") == ["Yes", "No", "Maybe"]
    cfg = ChartConfig(column="Q", sort="custom")
    cfg.recode.order = ["Maybe", "Yes"]                       # "No" is unlisted -> last
    d, _ = build_data(SURVEY, cfg)
    assert d.categories == ["Maybe", "Yes", "No"]
    assert list(d.table["sort_order"].unique()) == [0, 1, 2]


def test_ties_keep_source_order():
    f = _frame(Q=["b", "a", "b", "a"])
    d, _ = build_data(f, ChartConfig(column="Q", sort="desc"))
    assert d.categories == ["b", "a"]


def test_rename_is_display_only_and_never_edits_the_data():
    before = SURVEY.copy(deep=True)
    cfg = ChartConfig(column="Q")
    cfg.recode.rename = {"Yes": "Agreed"}
    d, _ = build_data(SURVEY, cfg)
    assert "Agreed" in d.categories and "Yes" not in d.categories
    pd.testing.assert_frame_equal(SURVEY, before)


def test_regrouping_combines_categories_and_recounts():
    cfg = ChartConfig(column="Q")
    cfg.recode.merges = [Merge("Not yes", ["No", "Maybe"])]
    d, _ = build_data(SURVEY, cfg)
    assert _cell(d, "Not yes")["count"] == 3            # No 2 + Maybe 1
    assert set(d.categories) == {"Yes", "Not yes"} and d.valid_n == 7


def test_colliding_recode_is_refused_not_silently_merged():
    cfg = ChartConfig(column="Q")
    cfg.recode.rename = {"No": "Yes"}
    with pytest.raises(ChartBuildError, match="display name of"):
        aggregate(SURVEY, cfg)
    cfg = ChartConfig(column="Q")
    cfg.recode.merges = [Merge("A", ["No"]), Merge("B", ["No"])]
    with pytest.raises(ChartBuildError, match="only once"):
        aggregate(SURVEY, cfg)


def test_excluding_a_category_removes_it_from_the_base_too():
    cfg = ChartConfig(column="Q")
    cfg.recode.exclude = ["Maybe"]
    d, _ = build_data(SURVEY, cfg)
    assert "Maybe" not in d.categories and d.valid_n == 6
    assert _cell(d, "Yes")["percent"] == pytest.approx(100 * 4 / 6)


def test_filter_then_count():
    cfg = ChartConfig(column="Q", filters=[FilterRule("Year", "eq", ["A"])])
    d, _ = build_data(SURVEY, cfg)               # A rows: Yes,Yes,No,"", "  " -> 3 valid
    assert d.valid_n == 3 and _cell(d, "Yes")["count"] == 2


@pytest.mark.parametrize("op,values,expected", [
    # Score cells: 10 20 30 40 50 60 70 "x" "" 5
    ("gt", ["30"], 4),            # 40 50 60 70
    ("le", ["30"], 4),            # 10 20 30 5
    ("between", ["20", "50"], 4), # 20 30 40 50
    ("not_missing", [], 9),       # only the "" cell is missing; "x" is text, not blank
    ("is_missing", [], 1),
    ("contains", ["0"], 7)])
def test_numeric_and_text_filters(op, values, expected):
    from core.chartbuilder.transform import filter_mask
    mask = filter_mask(SURVEY, [FilterRule("Score", op, values)])
    assert int(mask.sum()) == expected


def test_grouping_gives_per_group_denominators():
    cfg = ChartConfig(column="Q", group_by=["Year"], chart_type="grouped_bar")
    d, _ = build_data(SURVEY, cfg)
    # Year A valid Q: Yes,Yes,No -> 3.  Year B valid Q: Maybe,Yes,No,Yes -> 4.
    assert _cell(d, "Yes", "A")["denominator"] == 3
    assert _cell(d, "Yes", "A")["percent"] == pytest.approx(200 / 3)
    assert _cell(d, "Yes", "B")["count"] == 2 and _cell(d, "Yes", "B")["denominator"] == 4
    assert _cell(d, "Maybe", "A")["count"] == 0          # the grid is complete
    assert d.groups == ["A", "B"]
    assert d.table.groupby("group")["percent"].sum().round(6).tolist() == [100.0, 100.0]


def test_percent_of_grand_total_instead_of_of_group():
    cfg = ChartConfig(column="Q", group_by=["Year"], percent_base="total")
    d, _ = build_data(SURVEY, cfg)
    assert _cell(d, "Yes", "A")["denominator"] == 7
    assert d.table["percent"].sum() == pytest.approx(100.0)


def test_two_grouping_fields_join_their_labels():
    f = _frame(Q=["a", "b", "a", "b"], G1=["x", "x", "y", "y"], G2=["p", "q", "p", "q"])
    d, _ = build_data(f, ChartConfig(column="Q", group_by=["G1", "G2"],
                                     chart_type="grouped_bar"))
    assert d.groups == ["x / p", "x / q", "y / p", "y / q"]


def test_rows_with_a_blank_group_are_dropped_and_counted_once_shown():
    f = _frame(Q=["a", "a", "b"], G=["x", "", "x"])
    d, _ = build_data(f, ChartConfig(column="Q", group_by=["G"], chart_type="grouped_bar"))
    assert d.groups == ["x"] and d.valid_n == 2
    cfg = ChartConfig(column="Q", group_by=["G"], chart_type="grouped_bar")
    cfg.recode.show_missing = True
    d, _ = build_data(f, cfg)
    assert d.groups == ["x", "No response"]


@pytest.mark.parametrize("agg,expected", [("sum", 10 + 20 + 30), ("mean", 20.0),
                                          ("median", 20.0), ("min", 10.0), ("max", 30.0),
                                          # distinct counts labels, so "oops" is one too
                                          ("distinct", 4)])
def test_measure_aggregations_ignore_non_numeric_and_blank_values(agg, expected):
    f = _frame(K=["a"] * 5, V=["10", "20", "30", "oops", ""])
    d, _ = build_data(f, ChartConfig(column="K", aggregation=agg, value_field="V"))
    row = _cell(d, "a")
    assert row["value"] == expected
    if agg != "distinct":
        assert row["count"] == 3              # 'oops' and blank do not contribute
    assert pd.isna(row["percent"]) and pd.isna(row["denominator"])


def test_measure_needs_a_value_field():
    with pytest.raises(ChartBuildError, match="value field"):
        aggregate(SURVEY, ChartConfig(column="Q", aggregation="mean"))


def test_small_n_numeric_and_multiselect_warnings():
    d, _ = build_data(SURVEY, ChartConfig(column="Q"))
    assert any("fewer than 30" in w for w in d.warnings)
    nums = _frame(Q=[str(i % 5 + 1) for i in range(100)])
    d, _ = build_data(nums, ChartConfig(column="Q"))
    assert any("numeric field" in w for w in d.warnings)
    multi = _frame(Q=["a; b", "b; c", "a; c", "a; b; c", "c"] * 8)
    d, _ = build_data(multi, ChartConfig(column="Q"))
    assert any("select-all-that-apply" in w for w in d.warnings)


def test_whitespace_variants_warn_and_do_not_merge():
    f = _frame(Q=["Very  good", "Very good", "Very good"])
    d, _ = build_data(f, ChartConfig(column="Q"))
    assert set(d.categories) == {"Very  good", "Very good"}
    assert any("not merged" in w for w in d.warnings)
    cfg = ChartConfig(column="Q")
    cfg.recode.collapse_whitespace = True                # the analyst's explicit choice
    d, _ = build_data(f, cfg)
    assert d.categories == ["Very good"]


def test_unknown_column_is_a_sentence():
    with pytest.raises(ChartBuildError, match="'Nope'"):
        aggregate(SURVEY, ChartConfig(column="Nope"))


def test_xls_without_xlrd_says_how_to_fix_it(monkeypatch):
    def refuse(*args, **kwargs):
        raise ImportError("no xlrd")
    monkeypatch.setattr(pd, "ExcelFile", refuse)
    with pytest.raises(ImportError, match="pip install xlrd"):
        loader.load_bytes(b"not really an xls", "old.xls")


def test_xlrd_is_declared_wherever_openpyxl_is():
    root = Path(__file__).resolve().parents[1]
    for name in ("requirements.txt", "requirements-light.txt", "requirements-compat.txt"):
        assert "xlrd" in (root / name).read_text(encoding="utf-8"), name
    project = (root / "pyproject.toml").read_text(encoding="utf-8")
    assert project.count('"xlrd') == 2                      # dependencies + light extra


# ── scoped undo, and the category grid ────────────────────────────────────────

def test_scoped_history_undoes_shaping_edits_but_not_the_title():
    from core.chartbuilder.config import SHAPING_FIELDS
    h = EditHistory(ChartConfig(column="Q"), fields=SHAPING_FIELDS)
    cfg = h.current
    cfg.filters = [FilterRule("Y", "in", ["1"])]
    h.push(cfg)
    cfg.sort = "alpha"
    h.push(cfg)
    live = h.restore_into(cfg)
    live.labels.title = "My title"
    live.display.size = "large"
    h.push(live)                                   # presentation edits are not steps
    assert h.can_undo and not h.can_redo
    live = h.restore_into(h.undo() and live)       # step back over "sort"
    assert live.sort == "desc" and live.filters and live.labels.title == "My title"
    live = h.restore_into(h.undo() and live)
    assert live.filters == [] and live.display.size == "large"
    assert not h.can_undo


def _grid(cfg=None):
    from core.chartbuilder import recode_table
    return recode_table.category_table(SURVEY, cfg or ChartConfig(column="Q"))


def test_category_grid_lists_source_labels_in_source_order_with_counts():
    g = _grid()
    assert g["Category"].tolist() == ["Yes", "No", "Maybe"]
    assert g["Rows"].tolist() == [4, 2, 1]              # blanks and tokens are not categories
    assert g["Include"].all() and g["Position"].isna().all()


def test_grid_edits_become_a_recode_and_the_chart_follows():
    from core.chartbuilder import recode_table
    g = _grid()
    g.loc[g["Category"] == "Maybe", "Include"] = False
    g.loc[g["Category"] == "Yes", "Display name"] = "Agreed"
    g.loc[g["Category"] == "No", "Combine into"] = "Not agreed"
    rc = recode_table.recode_from_table(g)
    assert rc.exclude == ["Maybe"] and rc.rename == {"Yes": "Agreed"}
    assert [(m.label, m.members) for m in rc.merges] == [("Not agreed", ["No"])]
    cfg = ChartConfig(column="Q", recode=rc)
    d, _ = build_data(SURVEY, cfg)
    assert set(d.categories) == {"Agreed", "Not agreed"} and d.valid_n == 6


def test_grid_combine_gathers_rows_with_the_same_new_name():
    from core.chartbuilder import recode_table
    g = _grid()
    g.loc[g["Category"].isin(["No", "Maybe"]), "Combine into"] = "Other"
    rc = recode_table.recode_from_table(g)
    assert [(m.label, sorted(m.members)) for m in rc.merges] == [("Other", ["Maybe", "No"])]
    d, _ = build_data(SURVEY, ChartConfig(column="Q", recode=rc))
    assert d.table.set_index("category").loc["Other", "count"] == 3


def test_grid_position_sets_a_manual_order_and_round_trips():
    from core.chartbuilder import recode_table
    g = _grid()
    g.loc[g["Category"] == "Maybe", "Position"] = 1
    g.loc[g["Category"] == "Yes", "Position"] = 2
    rc = recode_table.recode_from_table(g)
    assert rc.order == ["Maybe", "Yes", "No"]           # unplaced rows follow in source order
    d, _ = build_data(SURVEY, ChartConfig(column="Q", sort="custom", recode=rc))
    assert d.categories == ["Maybe", "Yes", "No"]
    again = recode_table.category_table(SURVEY, ChartConfig(column="Q", recode=rc))
    assert recode_table.recode_from_table(again).order == rc.order


def test_grid_keeps_settings_it_does_not_carry():
    from core.chartbuilder import recode_table
    base = ChartConfig(column="Q").recode
    base.show_missing, base.missing_label, base.collapse_whitespace = True, "Skipped", True
    rc = recode_table.recode_from_table(_grid(), base)
    assert (rc.show_missing, rc.missing_label, rc.collapse_whitespace) == (True, "Skipped", True)


def test_grid_for_matrix_and_multi_questions():
    from core.chartbuilder import recode_table
    from core.chartbuilder.config import MultiSelect
    m = pd.DataFrame({"A": ["Yes", "No"], "B": ["No", "Maybe"]})
    g = recode_table.category_table(m, ChartConfig(kind="matrix", columns=["A", "B"]))
    assert g["Category"].tolist() == ["Yes", "No", "Maybe"] and g["Rows"].tolist() == [1, 2, 1]
    multi = pd.DataFrame({"C": ["x, y", "y", ""]})
    g = recode_table.category_table(multi, ChartConfig(
        kind="multi", column="C", multi=MultiSelect(mode="simple")))
    assert g.set_index("Category")["Rows"].to_dict() == {"x": 1, "y": 2}
