"""
Aggregation engine: a frame and a `ChartConfig` become the **canonical
chart-ready table**. It draws nothing and knows no chart type; a bar, a pie and a
stacked bar are all renderings of the same table, which is what keeps the numbers
identical across them.

Canonical columns (`CANONICAL_COLUMNS`), one row per category x group:

    category       display label of the category (after merge / rename)
    group          grouping label ("" when there is no grouping field; the item
                   for a matrix question)
    count          the numerator: respondents who chose this category
    denominator    the base the percent is taken over (NaN for measures)
    percent        100 * count / denominator (NaN for measures)
    value          the number the chart plots (percent, count, or the measure)
    valid_n        valid responses in this group
    missing_n      blank / missing-token responses in this group
    sort_order     0-based position of the category
    display_label  the text drawn on the bar, e.g. "93% (519/558)"
    color          hex colour of whatever the chart colours by

Four question kinds share one assembly step (`_assemble`); each has a `_prepare_*`
that turns the frame into the same two small tables:

    long   one row per (respondent, category chosen): rid, cat, grp[, num]
    resp   one row per respondent-unit: grp, valid, miss

so the numbers cannot differ between kinds by accident. *single*: one row per
respondent. *matrix*: one respondent-unit per respondent per item, the item is the
group. *multi* (select-all): one respondent, several `long` rows; the base counts
respondents, not selections, so percentages need not sum to 100.

Rules that decide the numbers
-----------------------------
- Blank cells and the missing tokens are **never in the denominator** by default
  (`denominator == "valid"`). "All rows" and a custom N are explicit choices.
- Categories the analyst excluded leave the valid base too, for single and matrix
  questions: they asked for a chart of the remaining answers. (In a select-all
  question the respondent still answered, so they stay in the base.)
- "Show blanks as a category" adds the category and its count but does *not*
  change the base, so percentages stay comparable with the hidden-blank chart;
  a warning says so when that makes the total exceed 100%.
- Missing groups: a row whose *grouping* value is blank is dropped unless blanks
  are shown, in which case it forms a group of its own.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import product
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from core.chartbuilder import clean, labels, profile, transform
from core.chartbuilder.config import MEASURE_AGGREGATIONS, NUMERIC_CHARTS, ChartConfig

CANONICAL_COLUMNS = ["category", "group", "count", "denominator", "percent",
                     "value", "valid_n", "missing_n", "sort_order",
                     "display_label", "color"]

_AGG_NAMES = {"sum": "Sum", "mean": "Mean", "median": "Median", "min": "Minimum",
              "max": "Maximum", "distinct": "Distinct count"}

MULTI_NOTE = "multiple selections allowed"


class ChartBuildError(ValueError):
    """The request cannot be charted. The message is written for the analyst."""


@dataclass
class ChartData:
    table: pd.DataFrame
    categories: List[str]
    groups: List[str]
    group_fields: List[str]
    valid_n: int
    missing_n: int
    n_rows: int
    value_title: str
    is_percent: bool
    base_note: str = ""
    warnings: List[str] = field(default_factory=list)
    kind: str = "single"
    color_by: str = "none"           # "category" | "group" | "none"
    scale: Optional[str] = None      # semantic scale detected/used, if any
    stack_border: bool = False       # white border between same-colour neighbours
    #: Free-form extras for the UI: parsing reports, dropped categories, etc.
    notes: Dict[str, object] = field(default_factory=dict)


@dataclass
class _Prepared:
    long: pd.DataFrame               # rid, cat, grp[, num]
    resp: pd.DataFrame               # grp, valid, miss
    groups: List[str]
    group_fields: List[str]
    source_labels: List[str]         # distinct cleaned source labels
    warnings: List[str] = field(default_factory=list)
    order_hint: Optional[List[str]] = None
    is_measure: bool = False
    notes: Dict[str, object] = field(default_factory=dict)


def _need_columns(frame: pd.DataFrame, names) -> None:
    for name in names:
        if name and name not in frame.columns:
            raise ChartBuildError(f"The field '{name}' is not in this dataset.")


def _sort_categories(cats: List[str], totals: Dict[str, float], sort: str,
                     order: List[str], first_seen: Dict[str, int]) -> List[str]:
    if sort == "alpha":
        return sorted(cats, key=lambda c: c.casefold())
    if sort == "source":
        return sorted(cats, key=lambda c: first_seen[c])
    if sort == "scale":
        from core.chartbuilder.survey import order_by_scale
        ordered, _ = order_by_scale(sorted(cats, key=lambda c: first_seen[c]))
        return ordered
    if sort == "custom":
        rank = {c: i for i, c in enumerate(order)}
        return sorted(cats, key=lambda c: (rank.get(c, len(rank)), first_seen[c]))
    reverse = sort == "desc"
    return sorted(cats, key=lambda c: (-totals[c] if reverse else totals[c],
                                       first_seen[c]))


def aggregate(frame: pd.DataFrame, cfg: ChartConfig) -> ChartData:
    """Build the canonical table for any question kind."""
    problems = cfg.problems()
    if problems:
        raise ChartBuildError(problems[0])
    if cfg.chart_type in NUMERIC_CHARTS:
        if cfg.kind != "single":
            raise ChartBuildError(
                f"A {cfg.chart_type} chart needs one numeric or date field; "
                "matrix, select-all and free-text questions use the bar and pie charts.")
        from core.chartbuilder.numeric import aggregate_numeric
        return aggregate_numeric(frame, cfg)
    if cfg.kind == "text":
        return _aggregate_text(frame, cfg)
    prepare = {"single": _prepare_single, "matrix": _prepare_matrix,
               "multi": _prepare_multi}.get(cfg.kind)
    if prepare is None:
        raise ChartBuildError(f"Unknown question kind '{cfg.kind}'.")
    return _assemble(prepare(frame, cfg), cfg)


# ── preparation: one function per question kind ───────────────────────────────

def _filtered(frame: pd.DataFrame, cfg: ChartConfig) -> pd.DataFrame:
    rc = cfg.recode
    mask = transform.filter_mask(frame, cfg.filters,
                                 collapse_whitespace=rc.collapse_whitespace,
                                 missing_tokens=rc.missing_tokens)
    return frame.loc[mask]


def _group_labels(sub: pd.DataFrame, cfg: ChartConfig):
    """(label per row, keep mask). Rows with a blank group value are dropped
    unless blanks are shown, in which case they form their own group."""
    rc = cfg.recode
    if not cfg.group_by:
        return pd.Series("", index=sub.index, dtype=object), \
            pd.Series(True, index=sub.index)
    parts = [clean.normalize_series(sub[g], collapse_whitespace=rc.collapse_whitespace,
                                    missing_tokens=rc.missing_tokens)
             for g in cfg.group_by]
    blank = pd.concat([p.isna() for p in parts], axis=1).any(axis=1)
    label = pd.Series([" / ".join(str(v) for v in row) for row in zip(*parts)],
                      index=sub.index, dtype=object)
    if rc.show_missing:
        return label.where(~blank, rc.missing_label), pd.Series(True, index=sub.index)
    return label, ~blank


def _first_seen(values) -> List[str]:
    return list(dict.fromkeys(v for v in values if isinstance(v, str)))


def _profile_warnings(frame: pd.DataFrame, columns: List[str], tokens,
                      check_multiselect: bool) -> List[str]:
    out: List[str] = []
    for name in columns:
        col = profile.profile_column(frame[name], missing_tokens=tokens)
        if col.kind == profile.NUMERIC:
            out.append(
                f"'{name}' is a numeric field being charted as categories. "
                "That is right for scale codes such as 1-5; for a measurement, "
                "use a histogram or a mean instead.")
        if check_multiselect and col.multiselect_delimiter:
            out.append(
                f"'{name}' looks like a select-all-that-apply field (several "
                f"answers per cell, separated by {col.multiselect_delimiter}). "
                "Counting whole cells will not count each choice.")
    return out


def _prepare_single(frame: pd.DataFrame, cfg: ChartConfig) -> _Prepared:
    rc = cfg.recode
    tokens, cw = rc.missing_tokens, rc.collapse_whitespace
    _need_columns(frame, [cfg.column, cfg.value_field, *cfg.group_by,
                          *[f.column for f in cfg.filters]])
    is_measure = cfg.aggregation in MEASURE_AGGREGATIONS
    sub = _filtered(frame, cfg)

    cleaned = clean.normalize_series(sub[cfg.column], collapse_whitespace=cw,
                                     missing_tokens=tokens)
    sources = _first_seen(cleaned)
    problems = transform.recode_problems(rc, sources)
    if problems:
        raise ChartBuildError(problems[0])
    rec = transform.apply_recode(cleaned, rc)

    group, keep = _group_labels(sub, cfg)
    sub, group = sub.loc[keep], group[keep]
    rec = transform.Recoded(rec.display[keep], rec.source[keep],
                            rec.missing[keep], rec.excluded[keep])

    num = None
    if is_measure:
        raw = clean.normalize_series(sub[cfg.value_field], collapse_whitespace=cw,
                                     missing_tokens=tokens)
        num = raw if cfg.aggregation == "distinct" else clean.to_numbers(
            sub[cfg.value_field], collapse_whitespace=cw, missing_tokens=tokens)

    rows = pd.DataFrame({"cat": rec.display.values, "grp": group.values,
                         "miss": rec.missing.values, "exc": rec.excluded.values})
    if num is not None:
        rows["num"] = num.values
    rows["valid"] = ~rows["miss"] & ~rows["exc"]
    if is_measure:
        rows["valid"] &= rows["num"].notna()
    rows["rid"] = range(len(rows))

    long = rows[rows["valid"]].drop(columns=["miss", "exc", "valid"])
    groups = _first_seen(rows["grp"]) if cfg.group_by else [""]
    warnings = _profile_warnings(frame, [cfg.column], tokens, check_multiselect=True)
    return _Prepared(long=long, resp=rows[["grp", "valid", "miss"]], groups=groups,
                     group_fields=list(cfg.group_by), source_labels=sources,
                     warnings=warnings, is_measure=is_measure)


def _prepare_matrix(frame: pd.DataFrame, cfg: ChartConfig) -> _Prepared:
    rc = cfg.recode
    tokens, cw = rc.missing_tokens, rc.collapse_whitespace
    _need_columns(frame, [*cfg.columns, *[f.column for f in cfg.filters]])
    if len(set(cfg.columns)) != len(cfg.columns):
        raise ChartBuildError("A column is listed twice in the matrix question.")
    names = [rc.item_rename.get(c, c) for c in cfg.columns]
    if len(set(names)) != len(names):
        raise ChartBuildError("Two matrix items would have the same display name. "
                              "Rename one of them.")
    sub = _filtered(frame, cfg)

    cleaned = {c: clean.normalize_series(sub[c], collapse_whitespace=cw,
                                         missing_tokens=tokens) for c in cfg.columns}
    sources = _first_seen(v for c in cfg.columns for v in cleaned[c])
    problems = transform.recode_problems(rc, sources)
    if problems:
        raise ChartBuildError(problems[0])

    longs, resps = [], []
    for col, name in zip(cfg.columns, names):
        rec = transform.apply_recode(cleaned[col], rc)
        valid = ~rec.missing & ~rec.excluded
        rid = np.arange(len(sub))
        longs.append(pd.DataFrame({"rid": rid[valid.values],
                                   "cat": rec.display[valid].values, "grp": name}))
        resps.append(pd.DataFrame({"grp": name, "valid": valid.values,
                                   "miss": rec.missing.values}))
    warnings = _profile_warnings(frame, list(cfg.columns), tokens, check_multiselect=False)
    return _Prepared(long=pd.concat(longs, ignore_index=True),
                     resp=pd.concat(resps, ignore_index=True), groups=names,
                     group_fields=["Item"], source_labels=sources, warnings=warnings)


def _prepare_multi(frame: pd.DataFrame, cfg: ChartConfig) -> _Prepared:
    from core.chartbuilder import survey

    rc = cfg.recode
    tokens, cw = rc.missing_tokens, rc.collapse_whitespace
    _need_columns(frame, [cfg.column, *cfg.group_by, *[f.column for f in cfg.filters]])
    sub = _filtered(frame, cfg)
    cleaned = clean.normalize_series(sub[cfg.column], collapse_whitespace=cw,
                                     missing_tokens=tokens)
    group, keep = _group_labels(sub, cfg)
    sub, group, cleaned = sub.loc[keep], group[keep], cleaned[keep]

    parsed = survey.parse_multi(cleaned, cfg.multi)
    flat = pd.Series([c for picked in parsed.choices for c in (picked or [])],
                     dtype=object)
    sources = _first_seen(flat)
    problems = transform.recode_problems(rc, sources)
    if problems:
        raise ChartBuildError(problems[0])
    rec = transform.apply_recode(flat, rc) if len(flat) else None

    shown = list(rec.display) if rec is not None else []
    rids, cats, grps, k = [], [], [], 0
    group_values = list(group.values)
    for rid, picked in enumerate(parsed.choices):
        for _ in (picked or []):
            label = shown[k]
            k += 1
            if isinstance(label, str):
                rids.append(rid)
                cats.append(label)
                grps.append(group_values[rid])
    long = pd.DataFrame({"rid": rids, "cat": cats, "grp": grps})
    miss = np.array([c is None for c in parsed.choices], dtype=bool)
    resp = pd.DataFrame({"grp": group_values, "valid": ~miss, "miss": miss})
    # Missing respondents as "No response" rows are added by `_assemble` from `resp`.

    warnings = survey.ambiguity_warnings(cleaned, cfg.multi)
    if cfg.multi.mode == "known" and parsed.unmatched:
        top = ", ".join(f"'{p}' ({n})" for p, n in parsed.unmatched.most_common(3))
        total = sum(parsed.unmatched.values())
        warnings.append(
            f"{total} piece(s) in {len(parsed.unmatched)} distinct form(s) did not "
            f"match any known choice and were not charted, for example {top}. Add "
            "them to the choice list, or turn on 'include unmatched'.")
    hint = None
    if cfg.multi.mode == "known":
        mapped = transform.apply_recode(pd.Series(cfg.multi.choices, dtype=object), rc)
        hint = [c for c in mapped.display if isinstance(c, str)]
    groups = _first_seen(resp["grp"]) if cfg.group_by else [""]
    return _Prepared(long=long, resp=resp, groups=groups,
                     group_fields=list(cfg.group_by), source_labels=sources,
                     warnings=warnings, order_hint=hint,
                     notes={"unmatched": dict(parsed.unmatched)})


# ── assembly: shared by every kind ────────────────────────────────────────────

def _assemble(prep: _Prepared, cfg: ChartConfig) -> ChartData:
    rc = cfg.recode
    long, resp, groups = prep.long, prep.resp, prep.groups
    is_measure = prep.is_measure
    warnings = list(prep.warnings)

    group_valid = {g: int(((resp["grp"] == g) & resp["valid"]).sum()) for g in groups}
    group_missing_n = {g: int(((resp["grp"] == g) & resp["miss"]).sum()) for g in groups}
    group_rows = {g: int((resp["grp"] == g).sum()) for g in groups}
    total_valid, total_missing = sum(group_valid.values()), sum(group_missing_n.values())
    total_rows = int(len(resp))

    categories = _first_seen(long["cat"])
    if prep.order_hint:
        known = [c for c in prep.order_hint if c in categories]
        categories = known + [c for c in categories if c not in known]
    first_seen = {c: i for i, c in enumerate(categories)}

    def base_for(g: str) -> float:
        if cfg.denominator == "custom":
            return float(cfg.custom_denominator)
        grouped = cfg.percent_base == "group" or cfg.kind == "matrix"
        if cfg.denominator == "all_rows":
            return float(group_rows[g] if grouped else total_rows)
        return float(group_valid[g] if grouped else total_valid)

    once = long.drop_duplicates(["rid", "cat", "grp"])
    counts = once.groupby(["cat", "grp"], sort=False).size().to_dict()
    measures: Dict[tuple, float] = {}
    if is_measure:
        by = long.groupby(["cat", "grp"], sort=False)["num"]
        reduce = {"sum": by.sum, "mean": by.mean, "median": by.median,
                  "min": by.min, "max": by.max, "distinct": by.nunique}[cfg.aggregation]
        measures = reduce().to_dict()

    rows = []
    for cat, g in product(categories, groups):
        n = int(counts.get((cat, g), 0))
        if is_measure:
            value, den, pct = measures.get((cat, g), np.nan), np.nan, np.nan
        else:
            den = base_for(g)
            pct = 100.0 * n / den if den else np.nan
            value = pct if cfg.aggregation == "percent" else float(n)
        rows.append((cat, g, n, den, pct, value))

    show_blank = rc.show_missing and not is_measure
    if show_blank and total_missing:
        for g in groups:
            n = group_missing_n[g]
            den = base_for(g)
            pct = 100.0 * n / den if den else np.nan
            rows.append((rc.missing_label, g, n, den, pct,
                         pct if cfg.aggregation == "percent" else float(n)))
        if cfg.denominator == "valid":
            warnings.append(
                f"'{rc.missing_label}' is shown as a category, but percentages "
                "are still of valid responses, so the bars can add to more than "
                "100%. Choose 'all rows' as the base to include blanks in it.")

    table = pd.DataFrame(rows, columns=["category", "group", "count",
                                        "denominator", "percent", "value"])
    table["valid_n"] = table["group"].map(group_valid).fillna(0).astype(int)
    table["missing_n"] = table["group"].map(group_missing_n).fillna(0).astype(int)

    real = categories
    body = table[table["category"].isin(real)]
    totals = (body.groupby("category")["value"].max()
              if is_measure and cfg.aggregation != "sum"
              else body.groupby("category")["value"].sum())
    ordered = _sort_categories(real, totals.to_dict(), cfg.sort, rc.order, first_seen)

    limit = cfg.display.max_categories
    if limit and len(ordered) > limit:
        by_size = sorted(real, key=lambda c: (-totals[c], first_seen[c]))[:limit]
        warnings.append(f"Showing the {limit} largest of {len(ordered)} categories; "
                        "the rest are left out (not combined).")
        ordered = [c for c in ordered if c in set(by_size)]
        table = table[table["category"].isin(ordered) | (table["category"] == rc.missing_label)]
    if show_blank and total_missing:
        ordered.append(rc.missing_label)
    rank = {c: i for i, c in enumerate(ordered)}
    group_rank = {g: i for i, g in enumerate(groups)}
    table = table.assign(sort_order=table["category"].map(rank).astype(int),
                         _g=table["group"].map(group_rank)) \
                 .sort_values(["sort_order", "_g"], kind="stable") \
                 .drop(columns="_g").reset_index(drop=True)

    lead = "count" if cfg.aggregation == "count" else "percent"
    d = cfg.display
    if is_measure:
        table["display_label"] = table["value"].map(
            lambda v: labels.measure_label(v, max(d.decimals, 1), d.thousands_separator))
    else:
        table["display_label"] = [
            labels.display_label(c, den, p, show_percent=d.show_percent,
                                 show_count=d.show_count, show_valid_n=d.show_valid_n,
                                 decimals=d.decimals, thousands=d.thousands_separator,
                                 lead=lead)
            for c, den, p in zip(table["count"], table["denominator"], table["percent"])]
    table["color"] = ""

    if len(categories) > profile.HIGH_CARDINALITY and not limit:
        warnings.append(f"{len(categories)} categories is a lot to read. Filter, "
                        "combine categories, or chart only the top few.")
    if not is_measure:
        small = [g or "all responses" for g in groups
                 if 0 < group_valid[g] < profile.SMALL_N]
        if small:
            warnings.append(
                f"Percentages for {', '.join(small)} rest on fewer than "
                f"{profile.SMALL_N} valid responses; read them with caution.")
    for group in clean.similar_label_groups(prep.source_labels):
        warnings.append("These labels differ only by " + group["reason"] + " and were "
                        "not merged: " + ", ".join(repr(x) for x in group["labels"]) + ".")

    if is_measure:
        value_title = f"{_AGG_NAMES[cfg.aggregation]} of {cfg.value_field}"
    elif cfg.kind == "multi":
        value_title = ("Percent" if cfg.aggregation == "percent" else "Number") + \
            f" of respondents selecting each option; {MULTI_NOTE}"
    elif cfg.aggregation == "percent":
        value_title = "Percent of respondents"
    else:
        value_title = "Count"

    if is_measure or cfg.denominator == "custom":
        base_note = ""
    elif cfg.kind == "multi":
        base_note = (f"Valid N = respondents with a valid response (N = {total_valid:,}); "
                     "percentages can add to more than 100%.")
    elif cfg.kind == "matrix":
        base_note = "Percent of respondents with a valid response to each item."
    elif cfg.denominator == "all_rows":
        base_note = f"Percent of all {total_rows:,} rows."
    else:
        base_note = f"Percent of respondents with a valid response (N = {total_valid:,})."

    return ChartData(
        table=table[CANONICAL_COLUMNS], categories=ordered,
        groups=groups if (cfg.group_by or cfg.kind == "matrix") else [],
        group_fields=prep.group_fields, valid_n=total_valid, missing_n=total_missing,
        n_rows=total_rows, value_title=value_title,
        is_percent=cfg.aggregation == "percent", base_note=base_note,
        warnings=warnings, kind=cfg.kind, notes=prep.notes)


# ── free text ─────────────────────────────────────────────────────────────────

def _aggregate_text(frame: pd.DataFrame, cfg: ChartConfig) -> ChartData:
    from core.chartbuilder import survey

    _need_columns(frame, [cfg.column, *[f.column for f in cfg.filters]])
    sub = _filtered(frame, cfg)
    summary = survey.text_summary(sub[cfg.column], missing_tokens=cfg.recode.missing_tokens,
                                  top=cfg.display.max_categories or 25)
    data = survey.keyword_chart_data(summary, cfg)
    data.kind = "text"
    data.notes["summary"] = summary
    return data
