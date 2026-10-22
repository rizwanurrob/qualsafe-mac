#!/usr/bin/env python
"""
Charts (the activity): four steps, Open, Pick a question, Adjust, Save (Update 3, phase 4b, item
4b.5f). The chart is drawn beside the controls at every step; each step shows only what it needs and
folds the rest under More options. The step comes from `app.shared.nav`.

Data Charts: the Chart Builder page for an uploaded CSV or Excel file.

The other "Chart Builder" page (`charts_page.py`) pivots a project's *codings*.
This one starts from any table (a survey export, an enrolment file) and is where
the survey structures live: Likert matrices with top/bottom boxes, select-all
questions, free text, recoding, themes and export.

Everything that decides a number, a colour or a figure is in `core/chartbuilder/`;
this module is widgets in, `ChartConfig` out, image back. Per `app/__init__` it
imports only `core/` and Streamlit, never `streamlit_app`.

How state works, because Streamlit reruns the whole script on every click:

- The **`ChartConfig`** (as a dict) is the one source of truth, in session state.
  Each run rebuilds it from the widgets, so every change shows immediately, and
  nothing needs "Generate".
- Widget keys carry a **generation** number. Undo, redo, reset and "load
  suggestions" bump it, which makes every widget rebuild from the config instead
  of remembering its old value.
- **Undo** covers the choices about the numbers (fields, filters, recode, sort,
  denominator), not the title or colours (`SHAPING_FIELDS`).
- The **category grid** is seeded once per set of categories and edits are read
  back as a `Recode`; an untouched grid changes nothing, so a rerun cannot
  silently rewrite the recode.

The uploaded file is read into memory and never written anywhere or altered.
"""

from __future__ import annotations

import hashlib
import json
from typing import Dict, List, Optional

import pandas as pd
import streamlit as st
from app.shared.caveat import caveat
from app.shared.layout import stretch, content

from app.shared import help_ui, nav
from core.chartbuilder import (
    export, loader, profile, recode_table, recommend, sample, store, survey, themes, vocab)
from core.chartbuilder.aggregate import ChartBuildError
from core.chartbuilder.build import build_data
from core.chartbuilder.config import (
    AGGREGATIONS, FIGURE_PRESETS, MEASURE_AGGREGATIONS, SHAPING_FIELDS, ChartConfig,
    EditHistory, FilterRule, MultiSelect)
from core.chartbuilder.render import AVAILABLE_TYPES, build_spec

_CHART_LABELS = vocab.CHART_LABELS
_KIND_LABELS = vocab.KIND_LABELS
_AGG_LABELS = vocab.AGG_LABELS
_SORT_LABELS = vocab.SORT_LABELS
_DENOM_LABELS = vocab.DENOM_LABELS
_OP_LABELS = vocab.OP_LABELS
_DELIMS = vocab.DELIM_LABELS
_LEGEND = vocab.LEGEND_LABELS
_SIZES = vocab.SIZE_LABELS
_DPIS = vocab.DPIS


# ── state ─────────────────────────────────────────────────────────────────────

def _gen() -> int:
    return int(st.session_state.get("dc_gen", 0))


def _k(name: str) -> str:
    return f"dc{_gen()}_{name}"


def _bump() -> None:
    st.session_state["dc_gen"] = _gen() + 1


def _config() -> ChartConfig:
    return ChartConfig.from_dict(st.session_state.get("dc_cfg"))


def _store(cfg: ChartConfig) -> None:
    st.session_state["dc_cfg"] = cfg.to_dict()


def _history() -> EditHistory:
    hist = st.session_state.get("dc_hist")
    if hist is None:
        hist = EditHistory(_config(), fields=SHAPING_FIELDS)
        st.session_state["dc_hist"] = hist
    return hist


def _undo() -> None:
    hist = _history()
    hist.undo()
    _store(hist.restore_into(_config()))
    _bump()


def _redo() -> None:
    hist = _history()
    hist.redo()
    _store(hist.restore_into(_config()))
    _bump()


def _reset_chart() -> None:
    """Back to a blank chart on the same data. The reset is itself undoable."""
    fresh = ChartConfig(dataset=_config().dataset)
    _history().push(fresh)
    _store(fresh)
    _bump()


def _apply_suggestions(choices: List[str]) -> None:
    cfg = _config()
    cfg.multi.choices = choices
    cfg.multi.mode = "known"
    _store(cfg)
    _bump()


def _switch_kind(kind: str) -> None:
    cfg = _config()
    cfg.kind = kind
    _store(cfg)
    _bump()


# ── data ──────────────────────────────────────────────────────────────────────

def _load(upload, show_sample: bool = True) -> Optional[loader.LoadedTable]:
    """The current table: the upload if there is one, else the sample, else what
    was loaded before. Reloaded only when the file or the chosen sheet changes."""
    S = st.session_state
    if upload is not None:
        data = upload.getvalue()
        key = (upload.name, len(data), hashlib.md5(data).hexdigest())
        sheet = None
        if upload.name.lower().endswith((".xlsx", ".xlsm", ".xls")):
            try:
                sheets = loader.list_sheets(data, upload.name)
            except ImportError as error:
                st.error(str(error))
                return None
            except Exception as error:  # noqa: BLE001
                st.error(f"That workbook could not be read: {error}")
                return None
            sheet = st.selectbox("Sheet", sheets, key="dc_sheet") if len(sheets) > 1 \
                else sheets[0]
        cache_key = key + (sheet,)
        if S.get("dc_table_key") != cache_key:
            try:
                table = loader.load_bytes(data, upload.name, sheet=sheet)
            except Exception as error:  # noqa: BLE001
                st.error(f"That file could not be read: {error}")
                return None
            _adopt(table, cache_key)
    elif show_sample and st.button("Use the sample spreadsheet", key="dc_sample",
                                   help="A made-up spreadsheet of 240 students' answers to numbers-and-choices "
                                        "questions, to try the chart steps with."):
        table = loader.LoadedTable(name="sample_survey.csv", frame=sample.sample_frame(),
                                   kind="csv", encoding="utf-8", delimiter=",")
        _adopt(table, ("sample",))
        st.rerun()
    return S.get("dc_table")


def _adopt(table: loader.LoadedTable, key) -> None:
    S = st.session_state
    S["dc_table"], S["dc_table_key"] = table, key
    S["dc_profile_key"] = None
    fresh = ChartConfig(dataset=table.structure())
    S["dc_cfg"] = fresh.to_dict()
    S["dc_hist"] = EditHistory(fresh, fields=SHAPING_FIELDS)
    S.pop("dc_export", None)
    S.pop("dc_load_notes", None)
    _bump()


def _profile(table: loader.LoadedTable, cfg: ChartConfig) -> profile.TableProfile:
    S = st.session_state
    key = (S.get("dc_table_key"), tuple(cfg.recode.missing_tokens or ()))
    if S.get("dc_profile_key") != key:
        S["dc_profile"] = profile.profile_table(
            table.frame, missing_tokens=cfg.recode.missing_tokens)
        S["dc_profile_key"] = key
    return S["dc_profile"]


def _idx(options: List[str], value: str, default: int = 0) -> int:
    return options.index(value) if value in options else default


# ── sections ──────────────────────────────────────────────────────────────────

def _section_data(table: loader.LoadedTable, prof: profile.TableProfile,
                  cfg: ChartConfig) -> None:
    a, b = st.columns(2)
    a.metric("Rows", f"{prof.n_rows:,}")
    b.metric("Columns", f"{prof.n_cols:,}")
    how = table.kind.upper() if table.kind != "csv" else "CSV"
    detail = [f"sheet '{table.sheet}'"] if table.sheet else []
    if table.encoding:
        detail.append(f"{table.encoding} text")
    if table.delimiter:
        detail.append("delimiter " + {"	": "tab"}.get(table.delimiter, f"'{table.delimiter}'"))
    st.caption(f"{table.name}: read as {how}" + (f" ({', '.join(detail)})" if detail else "") + ".")
    for note in table.notes:
        st.info(note)
    st.caption("The file is never changed. Everything below works on a copy in memory.")
    st.markdown("**First rows**")
    st.dataframe(table.frame.head(15), **stretch(), hide_index=True)
    st.markdown("**Fields**")
    st.dataframe(prof.as_frame(), **stretch(), hide_index=True)
    flagged = [(col.name, w) for col in prof.columns for w in col.warnings]
    if flagged:
        with st.expander(f"{len(flagged)} thing(s) to know about these fields"):
            for name, warning in flagged:
                st.markdown(f"- **{name}**: {warning}")
    with st.expander("More options"):
        cfg.recode.collapse_whitespace = st.checkbox(
            "Treat repeated spaces inside a label as one",
            value=cfg.recode.collapse_whitespace, key=_k("cw"),
            help="Leading and trailing spaces are always ignored. Turn this on if labels "
                 "like 'Very  good' and 'Very good' should count as one.")
        tokens = st.text_input(
            "Answers treated as blank (comma separated; leave empty for none)",
            value=", ".join(t for t in (cfg.recode.missing_tokens
                                        if cfg.recode.missing_tokens is not None
                                        else ["NULL", "null", "NaN", "None", "N/A", "NA",
                                              "(blank)", "<null>"]) if t),
            key=_k("tokens"),
            help="Empty cells always count as blank. Blanks are never in the base of a "
                 "percentage unless you choose that below.")
        parsed = [t.strip() for t in tokens.split(",") if t.strip()]
        cfg.recode.missing_tokens = None if set(parsed) == {
            "NULL", "null", "NaN", "None", "N/A", "NA", "(blank)", "<null>"} else [""] + parsed


def _section_question(table: loader.LoadedTable, prof: profile.TableProfile,
                      cfg: ChartConfig) -> None:
    cols = [str(c) for c in table.frame.columns]
    kinds = list(_KIND_LABELS)
    cfg.kind = st.radio("What kind of question?", kinds, index=_idx(kinds, cfg.kind),
                        format_func=_KIND_LABELS.get, key=_k("kind"))
    previous = st.session_state.get("dc_prev_kind", cfg.kind)
    if previous != cfg.kind:
        # A Likert matrix reads in scale order, not by frequency, and back again.
        if cfg.kind == "matrix" and cfg.sort == "desc":
            cfg.sort = "scale"
        elif previous == "matrix" and cfg.sort == "scale":
            cfg.sort = "desc"
        # Programmatic changes need widgets rebuilt from the config (new keys),
        # or a widget keeps showing its old value and overwrites the change.
        st.session_state["dc_prev_kind"] = cfg.kind
        _store(cfg)
        _bump()
        st.rerun()
    st.session_state["dc_prev_kind"] = cfg.kind
    if cfg.kind == "matrix":
        cfg.columns = st.multiselect(
            "Columns that make up the matrix (one per statement)", cols,
            default=[c for c in cfg.columns if c in cols], key=_k("columns"))
    else:
        cfg.column = st.selectbox("Field to analyse", [""] + cols,
                                  index=_idx([""] + cols, cfg.column),
                                  format_func=lambda c: c or "Choose a field", key=_k("field"))
        col = prof.column(cfg.column) if cfg.column in cols else None
        # A recognised agreement or frequency scale reads along the scale, not by how many chose each point.
        # Done once per field, so a later choice of another order sticks.
        if cfg.kind == "single" and cfg.column in cols and st.session_state.get("dc_scale_checked") != cfg.column:
            st.session_state["dc_scale_checked"] = cfg.column
            if cfg.sort == "desc" and _field_is_scale(table, cfg.column):
                cfg.sort = "scale"
                _store(cfg)
                _bump()
                st.rerun()
        if col is not None:
            if cfg.kind == "single" and col.kind == profile.TEXT:
                st.info("This looks like free text. Summarise it as free text instead of "
                        "one bar per response.")
                st.button("Switch to free text", key=_k("to_text"),
                          on_click=_switch_kind, args=("text",))
            if cfg.kind == "single" and col.multiselect_delimiter:
                st.info(f"Cells hold several answers (separated by {col.multiselect_delimiter}).")
                st.button("Treat as select-all-that-apply", key=_k("to_multi"),
                          on_click=_switch_kind, args=("multi",))

    if cfg.kind == "multi":
        _multi_controls(table, cfg)
    _question_more(table, prof, cfg, cols)


def _can_split_by(prof: profile.TableProfile, column: str) -> bool:
    """Whether a chart can sensibly be drawn once per value of this field.

    Not an ID (nearly every row different), not free text or long sentences, not cells that hold several answers,
    and not a continuous number (use a chart of that number instead). A field the person already chose stays."""
    col = prof.column(column)
    if col is None:
        return True
    if col.kind == profile.TEXT or col.multiselect_delimiter:
        return False
    if col.n_unique > 30:
        return False                                  # an ID, a date, a free number: too many charts to read
    if col.kind == profile.NUMERIC and col.n_unique > 12:
        return False
    sentences = [s for s in col.samples if isinstance(s, str)]
    if sentences and sum(len(s) for s in sentences) / len(sentences) > 40:
        return False                                  # long answers: free text that repeats
    return True


def _field_is_scale(table: loader.LoadedTable, column: str) -> bool:
    """True when the field's answers are the points of a recognised ordered scale (Likert and the like)."""
    from core.chartbuilder.themes import detect_scale

    try:
        values = [str(v) for v in table.frame[column].dropna().unique()]
    except Exception:  # noqa: BLE001 - a guess about ordering must never break the page
        return False
    return bool(values) and detect_scale(values) is not None


def _question_more(table: loader.LoadedTable, prof: profile.TableProfile, cfg: ChartConfig,
                   cols: List[str]) -> None:
    """Split by, and how to summarise: folded away; the question itself is on the page."""
    with st.expander("More options"):
        _question_more_body(table, prof, cfg, cols)


def _question_more_body(table: loader.LoadedTable, prof: profile.TableProfile, cfg: ChartConfig,
                        cols: List[str]) -> None:
    if cfg.kind in ("single", "multi"):
        # The analysed field cannot also be the split, so it leaves the options
        # and, if it was chosen before, the default (Streamlit refuses a default
        # that is not an option).
        split_options = [c for c in cols if c != cfg.column and (_can_split_by(prof, c) or c in cfg.group_by)]
        cfg.group_by = st.multiselect(
            "Split by (optional)", split_options,
            default=[c for c in cfg.group_by if c in split_options], key=_k("group"),
            help=help_ui.tip("chart.split"))
    if cfg.kind == "matrix":
        cfg.aggregation = st.radio("Show", ["percent", "count"],
                                   index=_idx(["percent", "count"], cfg.aggregation),
                                   format_func=_AGG_LABELS.get, horizontal=True,
                                   key=_k("agg_pc"))
    elif cfg.kind == "text":
        cfg.aggregation = st.radio("Show", ["percent", "count"],
                                   index=_idx(["percent", "count"], cfg.aggregation),
                                   format_func=lambda a: "Percent of responses" if a == "percent"
                                   else "Number of responses", horizontal=True, key=_k("agg_t"))
    elif cfg.kind == "multi":
        cfg.aggregation = st.radio("Show", ["percent", "count"],
                                   index=_idx(["percent", "count"], cfg.aggregation),
                                   format_func=_AGG_LABELS.get, horizontal=True, key=_k("agg_m"))
    elif cfg.chart_type == "box":
        st.caption("A box plot shows the spread of the field above: one box per "
                   "'Split by' group.")
        cfg.value_field = ""
    elif cfg.chart_type == "scatter":
        numeric = [c.name for c in prof.columns if c.kind == profile.NUMERIC and c.name != cfg.column]
        st.caption("Horizontal axis: the field above. Vertical axis: choose another number.")
        cfg.value_field = st.selectbox(
            "Vertical axis", [""] + numeric, index=_idx([""] + numeric, cfg.value_field),
            format_func=lambda c: c or "Choose a numeric field", key=_k("value_y"))
    elif cfg.chart_type == "histogram":
        cfg.aggregation = st.radio("Show", ["percent", "count"],
                                   index=_idx(["percent", "count"], cfg.aggregation),
                                   format_func=_AGG_LABELS.get, horizontal=True, key=_k("agg_h"))
        cfg.value_field = ""
    else:
        aggs = list(AGGREGATIONS)
        cfg.aggregation = st.selectbox("Summarise as", aggs,
                                       index=_idx(aggs, cfg.aggregation),
                                       format_func=_AGG_LABELS.get, key=_k("agg"))
        if cfg.aggregation in MEASURE_AGGREGATIONS:
            numeric = [c.name for c in prof.columns if c.kind == profile.NUMERIC]
            pool = cols if cfg.aggregation == "distinct" else numeric
            cfg.value_field = st.selectbox(
                "Measure", [""] + pool, index=_idx([""] + pool, cfg.value_field),
                format_func=lambda c: c or "Choose a numeric field", key=_k("value"))
            if not pool:
                st.warning("There is no numeric field to summarise in this file.")
        else:
            cfg.value_field = ""


def _multi_controls(table: loader.LoadedTable, cfg: ChartConfig) -> None:
    m = cfg.multi
    modes = ["known", "simple"]
    m.mode = st.radio(
        "How to read each cell", modes, index=_idx(modes, m.mode),
        format_func=lambda x: "Known choices (safe when a choice contains a comma)"
        if x == "known" else "Split at the delimiter (simple)", key=_k("mode"))
    keys = list(_DELIMS)
    m.delimiter = st.selectbox("Answers in a cell are separated by", keys,
                               index=_idx(keys, m.delimiter),
                               format_func=_DELIMS.get, key=_k("delim"))
    if m.delimiter == "custom":
        m.custom_delimiter = st.text_input("Separator", value=m.custom_delimiter,
                                           key=_k("custom_delim"))
    if m.mode == "known":
        text = st.text_area("The response choices, one per line",
                            value="\n".join(m.choices), height=140, key=_k("choices"),
                            help="Type or paste the choices exactly as the question "
                                 "offered them. A choice may contain the separator.")
        m.choices = [line.strip() for line in text.splitlines() if line.strip()]
        if cfg.column in table.frame.columns:
            if st.button("Suggest choices from the data", key=_k("suggest")):
                cleaned = table.frame[cfg.column]
                from core.chartbuilder import clean
                found = survey.suggest_choices(
                    clean.normalize_series(cleaned, missing_tokens=cfg.recode.missing_tokens),
                    m.delimiter_char())
                _apply_suggestions([s.choice for s in found])
                st.rerun()
        m.include_unmatched = st.checkbox(
            "Also chart pieces that are not on the list", value=m.include_unmatched,
            key=_k("unmatched"),
            help="Off by default: unmatched pieces are counted and reported instead.")
    else:
        st.caption("Simple splitting cuts a choice that contains the separator into "
                   "pieces. You will be warned if that looks like happening.")


def _filter_values(table: loader.LoadedTable, column: str, cfg: ChartConfig) -> List[str]:
    from core.chartbuilder import clean
    cleaned = clean.normalize_series(table.frame[column], collapse_whitespace=cfg.recode.collapse_whitespace,
                                     missing_tokens=cfg.recode.missing_tokens)
    return list(dict.fromkeys(v for v in cleaned if isinstance(v, str)))[:500]


def _filters(table: loader.LoadedTable, cfg: ChartConfig) -> None:
    cols = [str(c) for c in table.frame.columns]
    for i, rule in enumerate(list(cfg.filters)):
        left, right = st.columns([5, 1])
        shown = ", ".join(map(str, rule.values))
        left.markdown(f"**{rule.column}** {_OP_LABELS.get(rule.op, rule.op)} {shown}")
        if right.button("Remove", key=_k(f"rmfilter{i}")):
            cfg.filters.pop(i)
            _store(cfg)
            _bump()
            st.rerun()
    with st.expander("Add a filter", expanded=not cfg.filters):
        col = st.selectbox("Field", [""] + cols, key=_k("f_col"),
                           format_func=lambda c: c or "Choose a field")
        if col:
            op = st.selectbox("Keep rows where it", list(_OP_LABELS),
                              format_func=_OP_LABELS.get, key=_k("f_op"))
            values: List[str] = []
            if op in ("in", "not_in"):
                values = st.multiselect("Values", _filter_values(table, col, cfg),
                                        key=_k("f_vals"))
            elif op == "between":
                lo = st.text_input("From", key=_k("f_lo"))
                hi = st.text_input("To", key=_k("f_hi"))
                values = [v for v in (lo, hi) if v]
            elif op not in ("is_missing", "not_missing"):
                values = [st.text_input("Value", key=_k("f_val"))]
            ready = op in ("is_missing", "not_missing") or (
                all(values) and len(values) >= (2 if op == "between" else 1))
            if st.button("Add filter", key=_k("f_add"), disabled=not ready):
                cfg.filters.append(FilterRule(col, op, values))
                _store(cfg)
                _bump()
                st.rerun()


def _grid_signature(cfg: ChartConfig) -> str:
    payload = json.dumps([cfg.kind, cfg.column, cfg.columns, cfg.to_dict()["filters"],
                          cfg.recode.missing_tokens, cfg.recode.collapse_whitespace,
                          cfg.to_dict()["multi"], _gen()], default=str)
    return hashlib.md5(payload.encode()).hexdigest()[:10]


def _normalized(df: pd.DataFrame) -> pd.DataFrame:
    return df.reset_index(drop=True).astype(object).where(df.notna(), "").astype(str)


def _category_grid(table: loader.LoadedTable, cfg: ChartConfig) -> None:
    S = st.session_state
    if not (cfg.column or cfg.columns):
        return
    sig = _grid_signature(cfg)
    base_key = f"dc_grid_base_{sig}"
    if base_key not in S:
        S[base_key] = recode_table.category_table(table.frame, cfg)
    base = S[base_key]
    if base.empty:
        return
    st.caption("Untick to leave a category out. Type a new name to relabel it, or the "
               "same name on several rows to combine them. Give a Position to set "
               "your own order. The file's values are never changed.")
    edited = st.data_editor(
        base, key=f"dc_grid_{sig}", hide_index=True, **stretch(),
        disabled=["Category", "Rows"],
        column_config={
            "Include": st.column_config.CheckboxColumn("Include"),
            "Position": st.column_config.NumberColumn("Position", min_value=1, step=1),
            "Combine into": st.column_config.TextColumn(
                "Combine into", help="Same text on several rows makes one new category."),
            "Display name": st.column_config.TextColumn("Display name")})
    if not _normalized(edited).equals(_normalized(base)):
        cfg.recode = recode_table.recode_from_table(edited, cfg.recode)
        if edited["Position"].notna().any() and cfg.sort != "custom":
            cfg.sort = "custom"


def _item_names(cfg: ChartConfig) -> None:
    if cfg.kind != "matrix" or not cfg.columns:
        return
    with st.expander("Shorter names for the statements"):
        grid = pd.DataFrame({"Column": cfg.columns,
                             "Shown as": [cfg.recode.item_rename.get(c, c) for c in cfg.columns]})
        edited = st.data_editor(grid, hide_index=True, **stretch(),
                                disabled=["Column"], key=_k("items"))
        cfg.recode.item_rename = {c: n for c, n in zip(edited["Column"], edited["Shown as"])
                                  if str(n).strip() and n != c}


def _section_refine(table: loader.LoadedTable, cfg: ChartConfig) -> None:
    hist = _history()
    a, b, c = st.columns(3)
    a.button("Undo", key=_k("undo"), disabled=not hist.can_undo, on_click=_undo,
             **stretch(), help="Steps back through filters, recoding and sorting.")
    b.button("Redo", key=_k("redo"), disabled=not hist.can_redo, on_click=_redo,
             **stretch())
    c.button("Reset chart", key=_k("reset"), on_click=_reset_chart, **stretch(),
             help="Clears every choice for this file. Undo brings them back.")
    st.markdown("**Filters**")
    _filters(table, cfg)
    with st.expander("More options"):
        st.markdown("**Blank answers**")
        show = st.radio("Blank answers", ["hide", "show"], index=1 if cfg.recode.show_missing else 0,
                        format_func=lambda x: "Leave out" if x == "hide" else "Show as their own category",
                        horizontal=True, key=_k("blanks"), label_visibility="collapsed")
        cfg.recode.show_missing = show == "show"
        if cfg.recode.show_missing:
            cfg.recode.missing_label = st.text_input("Name for blanks", value=cfg.recode.missing_label,
                                                     key=_k("blank_label")) or "No response"
        numeric_chart = vocab.is_numeric_chart(cfg.chart_type)
        if not numeric_chart:
            st.markdown("**Categories**")
            _category_grid(table, cfg)
            _item_names(cfg)
        if not numeric_chart or cfg.chart_type == "box":
            sorts = vocab.MATRIX_SORTS if cfg.kind == "matrix" else vocab.OTHER_SORTS
            if cfg.kind == "single" and cfg.column and _field_is_scale(table, cfg.column):
                sorts = ["scale"] + list(vocab.OTHER_SORTS)
            if cfg.sort not in sorts:
                cfg.sort = sorts[0]
            cfg.sort = st.selectbox("Order", sorts, index=_idx(sorts, cfg.sort),
                                    format_func=_SORT_LABELS.get, key=_k("sort"))
        if not numeric_chart and (cfg.aggregation in ("percent", "count") or cfg.kind != "single"):
            denoms = list(_DENOM_LABELS)
            cfg.denominator = st.radio("Percentages are of", denoms,
                                       index=_idx(denoms, cfg.denominator),
                                       format_func=_DENOM_LABELS.get, key=_k("denom"))
            if cfg.denominator == "custom":
                cfg.custom_denominator = st.number_input(
                    "Base number", min_value=1.0, value=float(cfg.custom_denominator or 100),
                    step=1.0, key=_k("custom_n"))
        if cfg.kind == "matrix":
            with st.expander("Top and bottom boxes"):
                tops = st.multiselect("Top boxes", [1, 2, 3], default=cfg.boxes.top,
                                      format_func=lambda n: f"Top {n}", key=_k("tops"))
                bottoms = st.multiselect("Bottom boxes", [1, 2, 3], default=cfg.boxes.bottom,
                                         format_func=lambda n: f"Bottom {n}", key=_k("bottoms"))
                cfg.boxes.top, cfg.boxes.bottom = sorted(tops), sorted(bottoms)
                cfg.boxes.exclude_off_scale = st.checkbox(
                    "Leave 'No opinion' style answers out of the base of a box",
                    value=cfg.boxes.exclude_off_scale, key=_k("offscale"))


def _available_charts(cfg: ChartConfig, prof: Optional[profile.TableProfile] = None) -> List[str]:
    kind = ""
    if prof is not None and cfg.column:
        try:
            kind = prof.column(cfg.column).kind
        except KeyError:
            kind = ""
    return vocab.available_charts(cfg.kind, bool(cfg.group_by), kind)


def _section_chart(table: loader.LoadedTable, prof: profile.TableProfile, cfg: ChartConfig,
                   recs: List[recommend.Recommendation], show: bool = True) -> None:
    """Which chart. The choice (and the controls for it) are shown on the Adjust step only, but the
    chart that fits the question is picked on every step, so it is drawn as soon as there is one."""
    types = _available_charts(cfg, prof)
    primary = next((r.chart_type for r in recs if r.primary), None)
    if cfg.chart_type not in types:
        cfg.chart_type = primary if primary in types else types[0]

    def label(t: str) -> str:
        return _CHART_LABELS[t] + ("  ★ suggested" if t == primary else "")

    if show:
        cfg.chart_type = st.selectbox("Chart", types, index=_idx(types, cfg.chart_type),
                                      format_func=label, key=_k("chart"))
    # A new field is a new question: start from the suggested chart for it. The
    # analyst can pick anything else afterwards.
    subject = (cfg.kind, cfg.column, tuple(cfg.columns))
    if st.session_state.get("dc_prev_subject", subject) != subject and primary in types:
        cfg.chart_type = primary
    st.session_state["dc_prev_subject"] = subject
    previous = st.session_state.get("dc_prev_chart", cfg.chart_type)
    if previous != cfg.chart_type:
        # A newly chosen trend or distribution chart needs a matching summary;
        # rebuild the widgets from the config so the change is not overwritten.
        settled = vocab.settle_aggregation(cfg.chart_type, cfg.aggregation)
        st.session_state["dc_prev_chart"] = cfg.chart_type
        if settled != cfg.aggregation:
            cfg.aggregation = settled
        _store(cfg)
        _bump()
        st.rerun()
    st.session_state["dc_prev_chart"] = cfg.chart_type
    if not show:
        return
    reason = next((r.reason for r in recs if r.chart_type == cfg.chart_type), "")
    if reason:
        st.caption(reason)
    unavailable = [r for r in recs if not r.available]
    if unavailable:
        st.caption("Coming soon for this data: "
                   + ", ".join(_CHART_LABELS.get(r.chart_type, r.chart_type) for r in unavailable))
    if cfg.chart_type == "histogram":
        cfg.display.bins = int(st.number_input("Number of bins (0 = chosen for me)", 0, 60,
                                               value=cfg.display.bins, key=_k("bins")))
    if cfg.chart_type in ("line", "area"):
        grains = list(vocab.TIME_GRAIN_LABELS)
        cfg.display.time_grain = st.selectbox(
            "Each point is one", grains, index=_idx(grains, cfg.display.time_grain),
            format_func=vocab.TIME_GRAIN_LABELS.get, key=_k("grain"),
            help="Only applies when the field is a date.")
    if cfg.chart_type == "scatter":
        cfg.display.trend_line = st.checkbox("Draw a line of best fit", value=cfg.display.trend_line,
                                             key=_k("trend"))
    sizes = list(_SIZES)
    L = cfg.labels
    L.title = st.text_input("Title", value=L.title, key=_k("title"))
    with st.expander("Titles and labels"):
        L.subtitle = st.text_input("Subtitle", value=L.subtitle, key=_k("subtitle"))
        L.footnote = st.text_area("Footnote or source", value=L.footnote, height=68, key=_k("foot"))
        L.x_title = st.text_input("Horizontal axis title", value=L.x_title, key=_k("xt"))
        L.y_title = st.text_input("Vertical axis title", value=L.y_title, key=_k("yt"))
        L.legend_title = st.text_input("Legend title", value=L.legend_title, key=_k("lt"))
        keys = list(_LEGEND)
        L.legend_position = st.selectbox("Legend", keys, index=_idx(keys, L.legend_position),
                                         format_func=_LEGEND.get, key=_k("lp"))
    with st.expander("Numbers on the chart"):
        D = cfg.display
        D.data_labels = st.checkbox("Show data labels", value=D.data_labels, key=_k("dl"))
        D.show_percent = st.checkbox("Percent", value=D.show_percent, key=_k("sp"))
        D.show_count = st.checkbox("Count (how many chose it)", value=D.show_count, key=_k("sc"))
        D.show_valid_n = st.checkbox("Valid N (the base), shown as 93% (519/558)",
                                     value=D.show_valid_n, key=_k("sv"))
        D.decimals = int(st.number_input("Decimal places", 0, 3, value=D.decimals, key=_k("dec")))
        D.thousands_separator = st.checkbox("Thousands separator", value=D.thousands_separator,
                                            key=_k("ths"))
    with st.expander("Axes and labels"):
        D = cfg.display
        D.gridlines = st.checkbox("Gridlines", value=D.gridlines, key=_k("grid"))
        lo = st.text_input("Axis minimum (blank = automatic)",
                           value="" if D.axis_min is None else str(D.axis_min), key=_k("amin"))
        hi = st.text_input("Axis maximum (blank = automatic)",
                           value="" if D.axis_max is None else str(D.axis_max), key=_k("amax"))
        D.axis_min, D.axis_max = _number(lo), _number(hi)
        D.wrap_labels = st.checkbox("Wrap long labels", value=D.wrap_labels, key=_k("wrap"))
        D.max_label_chars = int(st.slider("Longest label line (characters)", 10, 60,
                                          D.max_label_chars, key=_k("mlc")))
        D.max_categories = int(st.number_input(
            "Show only the largest N categories (0 = all)", 0, 200, value=D.max_categories,
            key=_k("maxcat")))
    with st.expander("Size and shape"):
        cfg.display.size = st.radio("Size of bars and text", sizes, index=_idx(sizes, cfg.display.size),
                                    format_func=_SIZES.get, horizontal=True, key=_k("size"))
        if cfg.chart_type in ("grouped_bar", "stacked_bar", "normalized_bar"):
            cfg.display.orientation = st.radio(
                "Direction", ["horizontal", "vertical"],
                index=0 if cfg.display.orientation != "vertical" else 1,
                format_func=str.capitalize, horizontal=True, key=_k("orient"))
        F = cfg.figure
        presets = list(FIGURE_PRESETS) + ["Custom"]
        F.preset = st.selectbox("Shape", presets, index=_idx(presets, F.preset), key=_k("preset"))
        if F.preset == "Custom":
            F.width = int(st.number_input("Width (px)", 300, 4000, value=F.width, key=_k("fw")))
            F.height = int(st.number_input("Height (px)", 200, 4000, value=F.height, key=_k("fh")))


def _number(text: str) -> Optional[float]:
    try:
        return float(text) if text.strip() else None
    except ValueError:
        return None


def _custom_themes() -> Dict[str, themes.Theme]:
    """The custom themes: read from the per-user folder once per session."""
    S = st.session_state
    if "dc_custom_themes" not in S:
        S["dc_custom_themes"] = store.load_themes()
    return S["dc_custom_themes"]


def _section_theme(data_categories: List[str], cfg: ChartConfig) -> None:
    S = st.session_state
    custom = _custom_themes()
    names = list(themes.BUILTIN_THEMES) + list(custom)
    cfg.theme.name = st.selectbox("Colour theme", names, index=_idx(names, cfg.theme.name),
                                  key=_k("theme"))
    scales = ["auto", "none", *themes.SCALE_PRESETS]
    cfg.theme.semantic_scale = st.selectbox(
        "Colours for ordered answers", scales, index=_idx(scales, cfg.theme.semantic_scale),
        format_func=lambda s: {"auto": "Detect automatically", "none": "Off (theme palette)"}.get(
            s, s.capitalize() + " scale"), key=_k("scale"),
        help="Recognised scales (agree/disagree, importance, satisfaction, frequency) "
             "are coloured low to high with the theme's colours.")
    if data_categories:
        with st.expander("Set a colour for one category"):
            rows = pd.DataFrame({"Category": data_categories,
                                 "Colour (#RRGGBB, blank = automatic)": [
                                     cfg.theme.color_overrides.get(c, "") for c in data_categories]})
            edited = st.data_editor(rows, hide_index=True, **stretch(),
                                    disabled=["Category"], key=_k("colours"))
            overrides, bad = {}, []
            for cat, hexv in zip(edited["Category"], edited.iloc[:, 1]):
                if str(hexv).strip():
                    try:
                        overrides[cat] = themes.normalize_hex(str(hexv))
                    except ValueError:
                        bad.append(cat)
            cfg.theme.color_overrides = overrides
            if bad:
                st.warning("Not a colour, so ignored: " + ", ".join(bad)
                           + ". Use a hex code such as #BC912C.")
    with st.expander("Make my own theme"):
        _custom_theme_form(custom)
    if cfg.theme.name in custom:
        left, right = st.columns(2)
        if left.button("Delete this theme", key=_k("ct_delete")):
            try:
                S["dc_custom_themes"] = store.delete_theme(cfg.theme.name)
            except store.StoreError as error:
                st.error(str(error))
            else:
                cfg.theme = ChartConfig().theme
                _store(cfg)
                _bump()
                st.rerun()
        right.download_button("Share this theme", store.theme_to_bytes(custom[cfg.theme.name]),
                              file_name=export.safe_filename(cfg.theme.name, "json"),
                              mime="application/json", key=_k("ct_share"))
    incoming = st.file_uploader("Add a theme file someone sent you", type=["json"], key=_k("ct_upload"))
    if incoming is not None and S.get("dc_theme_upload") != (incoming.name, incoming.size):
        S["dc_theme_upload"] = (incoming.name, incoming.size)
        try:
            theme = store.theme_from_bytes(incoming.getvalue())
            S["dc_custom_themes"] = store.save_theme(theme)
        except (store.StoreError, ValueError) as error:
            st.error(str(error))
        else:
            st.success(f"Added '{theme.name}'. Pick it in the list above.")
    if st.button("Reset to the default", key=_k("default")):
        cfg.theme = ChartConfig().theme
        _store(cfg)
        _bump()
        st.rerun()


def _custom_theme_form(custom: Dict[str, themes.Theme]) -> None:
    S = st.session_state
    base = themes.BUILT_IN_DEFAULT
    name = st.text_input("Theme name", key=_k("ct_name"))
    fields = {}
    cols = st.columns(2)
    for i, (label, default) in enumerate([
            ("Primary", base.primary), ("Secondary", base.secondary),
            ("Neutral", base.neutral), ("Background", base.background),
            ("Text", base.text), ("Title", base.title), ("Gridlines", base.gridline)]):
        fields[label] = cols[i % 2].text_input(label + " (hex)", value=default, key=_k(f"ct_{label}"))
    tertiary = st.text_input("Other colours (hex, comma separated)", value=", ".join(base.tertiary),
                             key=_k("ct_tert"))
    palette = st.text_input("Colour order for categories (hex, comma separated; blank = derive)",
                            value="", key=_k("ct_pal"))
    if st.button("Save theme", key=_k("ct_save"), disabled=not name.strip()):
        try:
            theme = themes.build_theme(
                name, primary=fields["Primary"], secondary=fields["Secondary"],
                neutral=fields["Neutral"], background=fields["Background"], text=fields["Text"],
                title=fields["Title"], gridline=fields["Gridlines"], tertiary=tertiary,
                palette=palette)
            S["dc_custom_themes"] = store.save_theme(theme)
        except (ValueError, store.StoreError) as error:
            st.error(str(error))
        else:
            st.success(f"Saved '{theme.name}'. It will be here next time too. Pick it in the list above.")


# ── saved charts ──────────────────────────────────────────────────────────────

def _apply_loaded(fitted: ChartConfig, notes: List[str]) -> None:
    """Make a saved chart the current one. Widgets are rebuilt from it (new
    generation), and the 'what changed' trackers are set to it so the next run
    does not treat the loaded field as a new question and swap the chart."""
    S = st.session_state
    theme_known = fitted.theme.name in themes.BUILTIN_THEMES or fitted.theme.name in _custom_themes()
    if not theme_known:
        notes = notes + [f"The theme '{fitted.theme.name}' is not on this computer, so the "
                         "The default colours are used. Add the theme file to get it back."]
    S["dc_cfg"] = fitted.to_dict()
    _history().push(fitted)
    S["dc_load_notes"] = notes
    S["dc_prev_kind"], S["dc_prev_chart"] = fitted.kind, fitted.chart_type
    S["dc_prev_subject"] = (fitted.kind, fitted.column, tuple(fitted.columns))
    S.pop("dc_export", None)
    _bump()


def _load_saved(name: str) -> None:
    S = st.session_state
    try:
        chart = store.load_chart(name)
    except store.StoreError as error:
        S["dc_load_notes"] = [str(error)]
        return
    fitted, notes = store.fit_to_frame(chart.config, S["dc_table"].frame)
    _apply_loaded(fitted, notes)


def _delete_saved(name: str) -> None:
    store.delete_chart(name)


def _section_saved(table: loader.LoadedTable, cfg: ChartConfig) -> None:
    S = st.session_state
    st.caption("Saved charts remember the choices, not the data. Open one on the same kind "
               "of file later and it draws the same chart.")
    name = st.text_input("Name this chart", key=_k("chart_name"),
                         value=cfg.labels.title if cfg.labels.title else "")
    if st.button("Keep this chart", key=_k("chart_save"), disabled=not name.strip()):
        try:
            store.save_chart(name, cfg, table.structure())
        except store.StoreError as error:
            st.error(str(error))
        else:
            st.success(f"Kept '{name.strip()}'. Keeping it again under the same name replaces it.")
    with st.expander("More options"):
        _saved_more(table, cfg, name)


def _saved_more(table: loader.LoadedTable, cfg: ChartConfig, name: str) -> None:
    """The charts you have kept, and sharing one as a file."""
    S = st.session_state
    charts = store.list_charts()
    if charts:
        labels = {c.name: f"{c.name}  ({c.dataset_name or 'no file'})" for c in charts}
        chosen = st.selectbox("Charts you kept", list(labels), format_func=labels.get, key=_k("chart_pick"))
        left, right = st.columns(2)
        left.button("Open", key=_k("chart_open"), on_click=_load_saved, args=(chosen,),
                    **stretch())
        right.button("Delete", key=_k("chart_delete"), on_click=_delete_saved, args=(chosen,),
                     **stretch())
    saved_now = store.SavedChart(name.strip() or cfg.labels.title or "chart", cfg, table.structure())
    st.download_button("Save this chart as a file to share", store.chart_to_bytes(saved_now),
                       file_name=export.safe_filename(saved_now.name, "qchart.json"),
                       mime="application/json", key=_k("chart_file"))
    incoming = st.file_uploader("Open a chart file", type=["json"], key=_k("chart_upload"))
    if incoming is not None and S.get("dc_chart_upload") != (incoming.name, incoming.size):
        S["dc_chart_upload"] = (incoming.name, incoming.size)
        try:
            chart = store.chart_from_bytes(incoming.getvalue())
        except store.StoreError as error:
            st.error(str(error))
        else:
            fitted, notes = store.fit_to_frame(chart.config, table.frame)
            _apply_loaded(fitted, notes)
            st.rerun()


# ── output ────────────────────────────────────────────────────────────────────

def _key_for(cfg: ChartConfig, custom: Dict[str, themes.Theme]) -> str:
    return hashlib.md5((json.dumps(cfg.to_dict(), sort_keys=True, default=str)
                        + json.dumps({n: t.to_dict() for n, t in custom.items()},
                                     sort_keys=True)
                        + str(st.session_state.get("dc_table_key"))).encode()).hexdigest()


def _build(table: loader.LoadedTable, cfg: ChartConfig):
    """(ChartData, Theme, spec) or an error string. Cached per configuration."""
    S = st.session_state
    custom = _custom_themes()
    key = _key_for(cfg, custom)
    if S.get("dc_built_key") == key:
        return S["dc_built"]
    try:
        data, theme = build_data(table.frame, cfg, custom)
        spec = build_spec(data, cfg, theme)
        result = (data, theme, spec)
    except (ChartBuildError, KeyError) as error:
        result = str(error.args[0] if error.args else error)
    S["dc_built_key"], S["dc_built"] = key, result
    return result


_COMPOSED = ("vconcat", "hconcat", "concat", "facet", "repeat")


def _screen_spec(spec: dict) -> Optional[dict]:
    """The spec fitted to the page, for drawing in the browser; None for composed charts.

    Charts made of several panels have no fluid width in Vega-Lite, so they keep the picture preview.
    A fixed size becomes the width of the column, with the same proportions, so the chart fills the
    space it is given on any screen."""
    if any(k in spec for k in _COMPOSED):
        return None
    import copy

    fitted = copy.deepcopy(spec)
    width, height = fitted.get("width"), fitted.get("height")
    if isinstance(width, (int, float)) and isinstance(height, (int, float)) and width > 0:
        fitted["width"] = "container"
        fitted["height"] = max(220, int(round(height * _SCREEN_WIDTH / width)))
    fitted["autosize"] = {"type": "fit", "contains": "padding"}
    _scale_text(fitted, _TEXT_SCALE)
    return fitted


_SCREEN_WIDTH = 640         # about the width of the chart column, to keep the proportions
#: The spec's text is sized for the saved picture (1280 wide); the column is about half that, so text
#: kept at full size crowds bar labels and clips long notes (seen in the browser pane). A little under
#: full size reads clearly and leaves the same room as the picture.
_TEXT_SCALE = 0.75


def _scale_text(node, factor: float) -> None:
    """Multiply every font size in a spec, in place (`fontSize`, `labelFontSize`, `titleFontSize`...)."""
    if isinstance(node, dict):
        for key, value in node.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool) and key.lower().endswith("fontsize"):
                node[key] = round(value * factor, 1)
            else:
                _scale_text(value, factor)
    elif isinstance(node, list):
        for item in node:
            _scale_text(item, factor)


def _preview(spec: dict, key: str) -> None:
    """Draw the chart on screen.

    In the browser (Vega-Lite): the picture renderer on the server takes 3 to 5 s for every chart, so
    the preview waited on it each time a choice changed. The saved picture still comes from the
    renderer (Save step), so what is saved is what the renderer draws; the preview may differ a
    little in fonts. Composed charts, and a machine without the browser library, keep the picture."""
    S = st.session_state
    screen = _screen_spec(spec)
    if screen is not None:
        st.vega_lite_chart(screen, **stretch(), theme=None)
        return
    if export.image_export_available():
        if S.get("dc_png_key") != key:
            try:
                S["dc_png"] = export.render_image(spec, "png", 96)
                S["dc_png_key"] = key
            except Exception as error:  # noqa: BLE001
                S["dc_png"] = None
                st.error(f"The chart could not be drawn: {error}")
        if S.get("dc_png"):
            st.image(S["dc_png"], **stretch())
            return
    import altair as alt
    chart = alt.VConcatChart.from_dict(spec) if "vconcat" in spec else alt.Chart.from_dict(spec)
    st.altair_chart(chart, theme=None, **content())


def _section_export(table: loader.LoadedTable, data, spec: dict, cfg: ChartConfig,
                    key: str) -> None:
    S = st.session_state
    st.markdown("**Picture**")
    if not export.image_export_available():
        st.warning("Picture export needs the vl-convert package, which is not installed.")
    else:
        fmt = st.selectbox("Format", ["png", "svg", "pdf"], format_func=str.upper, key=_k("fmt"))
        with st.expander("More options"):
            dpi = st.selectbox("Sharpness (dots per inch)", _DPIS, index=_DPIS.index(300),
                               key=_k("dpi"), help=help_ui.tip("chart.sharpness"))
            cfg.figure.transparent = st.checkbox("See-through background", value=cfg.figure.transparent,
                                                 key=_k("transp"))
        w, h = export.export_pixels(cfg, dpi)
        if fmt == "png":
            st.caption(f"{w:,} x {h:,} px.")
        stamp = (key, fmt, dpi, cfg.figure.transparent)
        if st.button(f"Prepare the {fmt.upper()}", key=_k("prep"), type="primary"):
            try:
                out_spec = build_spec(data, cfg, themes.get_theme(
                    cfg.theme.name, _custom_themes()))
                S["dc_export"] = (stamp, export.render_image(out_spec, fmt, dpi),
                                  export.chart_filename(cfg, fmt))
            except Exception as error:  # noqa: BLE001
                st.error(f"Could not prepare the picture: {error}")
        ready = S.get("dc_export")
        if ready and ready[0] == stamp:
            st.download_button(f"Download {ready[2]}", ready[1], file_name=ready[2],
                               mime={"png": "image/png", "svg": "image/svg+xml",
                                     "pdf": "application/pdf"}[fmt], key=_k("dl_img"))
        elif ready:
            st.caption("The chart changed since this was prepared. Prepare it again.")


def _section_table(frame: pd.DataFrame, data, cfg: ChartConfig) -> None:
    a, b, c = st.columns(3)
    totals = a.checkbox("Totals", value=False, key=_k("t_tot"))
    valid = b.checkbox("Valid N", value=True, key=_k("t_valid"))
    missing = c.checkbox("Missing N", value=False, key=_k("t_miss"))
    table = export.summary_table(data, cfg, totals=totals, valid_n=valid, missing_n=missing)
    st.dataframe(table, **stretch(), hide_index=True)
    left, right = st.columns(2)
    left.download_button("Download CSV", export.table_csv(table),
                         file_name=export.chart_filename(cfg, "csv", suffix="table"),
                         mime="text/csv", key=_k("dl_csv"))
    right.download_button("Download Excel", export.table_xlsx(table, data, cfg),
                          file_name=export.chart_filename(cfg, "xlsx", suffix="table"),
                          mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                          key=_k("dl_xlsx"))
    with st.expander("Copy the table"):
        st.caption("Use the copy button in the corner, then paste into Excel or Word.")
        st.code(export.table_tsv(table), language=None)
    if cfg.kind == "matrix":
        boxes = survey.box_summary(data, cfg)
        if not boxes.empty:
            st.markdown("**Top and bottom boxes**")
            st.caption("Count is how many chose a category in the box; Valid N is the base.")
            st.dataframe(boxes, **stretch(), hide_index=True)
            st.download_button("Download boxes (CSV)", export.table_csv(boxes),
                               file_name=export.chart_filename(cfg, "csv", suffix="boxes"),
                               mime="text/csv", key=_k("dl_boxes"))
    if cfg.kind == "text":
        answers = survey.responses_frame(frame, cfg.column,
                                         missing_tokens=cfg.recode.missing_tokens)
        st.markdown(f"**{len(answers):,} responses**")
        st.download_button("Download the responses (CSV)", export.table_csv(answers),
                           file_name=export.chart_filename(cfg, "csv", suffix="responses"),
                           mime="text/csv", key=_k("dl_resp"))


#: Keeps the chart in view while the controls beside it scroll. Streamlit has no
#: sticky column, so the column holding the anchor is pinned with CSS.
_STICKY_CSS = (
    "<style>div[data-testid='stColumn']:has(#dc-output-anchor)"
    "{position:sticky;top:3.6rem;align-self:flex-start;"
    "max-height:calc(100vh - 4.5rem);overflow-y:auto;}</style>")


# ── page ──────────────────────────────────────────────────────────────────────

STEPS = ("open", "question", "adjust", "save")
_NEXT = {"open": ("question", "Next: pick a question"), "question": ("adjust", "Next: adjust the chart"),
         "adjust": ("save", "Next: save")}


def _go_step(step_key: str) -> None:
    st.session_state["step_charts"] = step_key


def _next_button(step: str) -> None:
    if step in _NEXT:
        target, label = _NEXT[step]
        st.button(label, key=f"dc_next_{step}", type="primary", on_click=_go_step, args=(target,))


def render_data_charts_page() -> None:
    S = st.session_state
    step = nav.step_of("charts")
    upload = None
    if step == "open" or S.get("dc_table") is None:
        st.subheader("Your spreadsheet")
        upload = st.file_uploader("Open a CSV or Excel file", type=["csv", "tsv", "txt", "xlsx", "xlsm", "xls"],
                                  key="dc_upload", help="The file is read, never changed, and nothing leaves "
                                                        "this computer.")
    table = _load(upload, show_sample=step == "open" or S.get("dc_table") is None)
    if table is None:
        st.info("Open a spreadsheet, or use the sample spreadsheet, to begin.")
        if step != "open":
            st.button("Go to Open", key="dc_go_open", on_click=_go_step, args=("open",))
        return

    cfg = _config()
    prof = _profile(table, cfg)
    controls, output = st.columns([5, 7], gap="large")

    with controls:
        if step == "open":
            _section_data(table, prof, cfg)
        elif step == "question":
            _section_question(table, prof, cfg)
        elif step == "adjust":
            _section_refine(table, cfg)
        built = _build(table, cfg)
        cats = built[0].categories if isinstance(built, tuple) else []
        recs = recommend.recommend(cfg, prof, n_categories=len(cats) or None,
                                   categories=cats or None)
        _section_chart(table, prof, cfg, recs, show=step == "adjust")
        if step == "adjust":
            with st.expander("Colours"):
                _section_theme(cats, cfg)
        elif step == "save":
            _section_saved(table, cfg)
        _next_button(step)

    _history().push(cfg)
    _store(cfg)
    built = _build(table, cfg)

    with output:
        st.markdown('<span id="dc-output-anchor"></span>' + _STICKY_CSS, unsafe_allow_html=True)
        for note in S.get("dc_load_notes", []):
            caveat(note)
        problems = cfg.problems()
        if isinstance(built, str):
            st.info(built if not problems else problems[0])
            return
        data, theme, spec = built
        for warning in data.warnings:
            st.warning(warning)
        key = _key_for(cfg, _custom_themes())
        _preview(spec, key)
        if step == "save":
            _section_export(table, data, spec, cfg, key)
            with st.expander("The numbers behind the chart"):
                _section_table(table.frame, data, cfg)
