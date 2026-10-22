"""
Numeric and time charts: histogram, box plot, scatter, line and area.

These draw from the rows themselves (a distribution, a spread, a relationship, a
trend) rather than from counts of categories, so they have their own aggregation.
They still return the same `ChartData` and share the canonical columns, with a few
extension columns (`bin_start`, `q1`, `x`, ...) that the renderer and the summary
table read. Nothing here knows how a chart is drawn.

How each one reads the configuration
------------------------------------
- **Histogram**: `column` is a numeric field; count or percent of rows per bin;
  `Split by` overlays one histogram per group on shared bins.
- **Box plot**: `column` is the numeric field; `Split by` gives one box per group.
  Whiskers reach the furthest value within 1.5 x IQR of the box (Tukey); values
  beyond are drawn as points and counted, never trimmed away.
- **Scatter**: `column` is x and the measure field is y (both numeric); `Split by`
  colours the points; only rows with *both* values are plotted, and the rest are
  counted in a warning.
- **Line / area**: `column` is the x field. A date field is grouped into periods
  (`display.time_grain`, chosen from the span when "auto") with empty periods shown
  as zero for counts and sums and left as gaps for means. Any other field is read
  as ordered categories (numeric order when every label is a number). The value
  is the count, the percent of all rows in each period, or a summary of the
  measure field.

Rules kept from the categorical charts: blanks and missing tokens never count,
text in a numeric field is counted and reported instead of quietly dropped, and
a request that cannot be drawn returns a sentence, never a different chart.
"""

from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from core.chartbuilder import clean, labels, profile
from core.chartbuilder.aggregate import (
    CANONICAL_COLUMNS, ChartBuildError, ChartData, _filtered, _first_seen,
    _group_labels, _need_columns, _sort_categories)
from core.chartbuilder.config import MEASURE_AGGREGATIONS, ChartConfig

MAX_BINS = 60
#: The share of a field's answers that must read as dates for it to be a date axis.
#: Below it the field is read as ordered categories; above it the stragglers are
#: reported ("could not be read") rather than quietly dropped.
DATE_SHARE = 0.8
#: Below this many values a quartile is an artefact of the sample, so say so.
FEW_VALUES = 5
#: Above this many points a scatter is slow to draw and hard to read.
MANY_POINTS = 5000

_GRAIN_FREQ = {"day": "D", "week": "W-SUN", "month": "M", "quarter": "Q", "year": "Y"}
_AGG_NAMES = {"sum": "Sum", "mean": "Mean", "median": "Median", "min": "Minimum",
              "max": "Maximum", "distinct": "Distinct count"}


def aggregate_numeric(frame: pd.DataFrame, cfg: ChartConfig) -> ChartData:
    """Dispatch on the chart type. Raises `ChartBuildError` with a sentence."""
    _need_columns(frame, [cfg.column, cfg.value_field, *cfg.group_by,
                          *[f.column for f in cfg.filters]])
    builder = {"histogram": _histogram, "box": _box, "scatter": _scatter,
               "line": _series, "area": _series}[cfg.chart_type]
    return builder(frame, cfg)


# ── shared helpers ────────────────────────────────────────────────────────────

def _numbers(sub: pd.DataFrame, name: str, cfg: ChartConfig, warnings: List[str]) -> pd.Series:
    rc = cfg.recode
    nums = clean.to_numbers(sub[name], collapse_whitespace=rc.collapse_whitespace,
                            missing_tokens=rc.missing_tokens)
    bad = clean.count_non_numeric(sub[name], nums, rc.missing_tokens)
    if bad:
        warnings.append(f"{bad:,} value(s) in '{name}' are not numbers and were left out.")
    return nums


def _decimals(cfg: ChartConfig, default: int = 1) -> int:
    return max(cfg.display.decimals, default)


def _edge(value: float) -> str:
    """A bin edge as short text: whole numbers plain, others to 3 significant digits."""
    if float(value).is_integer():
        return f"{int(value):,}"
    return f"{value:.3g}"


def _label_column(table: pd.DataFrame, cfg: ChartConfig, lead: str) -> pd.DataFrame:
    d = cfg.display
    table["display_label"] = [
        labels.display_label(c, den, p, show_percent=d.show_percent, show_count=d.show_count,
                             show_valid_n=d.show_valid_n, decimals=d.decimals,
                             thousands=d.thousands_separator, lead=lead)
        for c, den, p in zip(table["count"], table["denominator"], table["percent"])]
    return table


def _finish(table: pd.DataFrame, extra: List[str], *, categories, groups, group_fields,
            valid_n, missing_n, n_rows, value_title, is_percent, base_note, warnings,
            notes) -> ChartData:
    for col in CANONICAL_COLUMNS:
        if col not in table.columns:
            table[col] = "" if col in ("color", "display_label") else np.nan
    table = table[CANONICAL_COLUMNS + extra]
    return ChartData(table=table, categories=list(categories), groups=list(groups),
                     group_fields=list(group_fields), valid_n=int(valid_n),
                     missing_n=int(missing_n), n_rows=int(n_rows), value_title=value_title,
                     is_percent=is_percent, base_note=base_note, warnings=warnings,
                     kind="numeric", notes=notes)


# ── histogram ─────────────────────────────────────────────────────────────────

def bin_edges(values: np.ndarray, bins: int = 0) -> np.ndarray:
    """Bin edges for `values`: `bins` equal bins, or numpy's rule when 0."""
    if bins and bins > 0:
        return np.histogram_bin_edges(values, bins=min(int(bins), MAX_BINS))
    edges = np.histogram_bin_edges(values, bins="auto")
    if len(edges) - 1 > MAX_BINS:
        edges = np.histogram_bin_edges(values, bins=MAX_BINS)
    return edges


def _histogram(frame: pd.DataFrame, cfg: ChartConfig) -> ChartData:
    if cfg.aggregation in MEASURE_AGGREGATIONS:
        raise ChartBuildError("A histogram counts rows: choose Count or Percent.")
    warnings: List[str] = []
    sub = _filtered(frame, cfg)
    group, keep = _group_labels(sub, cfg)
    sub, group = sub.loc[keep], group[keep]
    nums = _numbers(sub, cfg.column, cfg, warnings)
    n_rows, valid = int(len(sub)), nums.notna()
    if not valid.any():
        raise ChartBuildError(f"'{cfg.column}' has no numbers to plot.")
    edges = bin_edges(nums[valid].to_numpy(), cfg.display.bins)
    groups = _first_seen(group[valid]) if cfg.group_by else [""]
    rows = []
    for g in groups:
        vals = nums[valid & (group == g)].to_numpy()
        counts, _ = np.histogram(vals, bins=edges)
        den = float(len(vals))
        for i, n in enumerate(counts):
            pct = 100.0 * n / den if den else np.nan
            rows.append({
                "category": f"{_edge(edges[i])} to {_edge(edges[i + 1])}", "group": g,
                "count": int(n), "denominator": den, "percent": pct,
                "value": pct if cfg.aggregation == "percent" else float(n),
                "valid_n": int(den), "missing_n": int((group == g).sum() - den),
                "sort_order": i, "bin_start": float(edges[i]), "bin_end": float(edges[i + 1])})
    table = _label_column(pd.DataFrame(rows), cfg,
                          "count" if cfg.aggregation == "count" else "percent")
    if table["valid_n"].min() < profile.SMALL_N:
        warnings.append(f"The histogram rests on fewer than {profile.SMALL_N} values in at "
                        "least one group; the shape may not mean much.")
    note = "The last bin includes its upper edge."
    return _finish(
        table, ["bin_start", "bin_end"], categories=list(dict.fromkeys(table["category"])),
        groups=groups if cfg.group_by else [], group_fields=list(cfg.group_by),
        valid_n=int(valid.sum()), missing_n=n_rows - int(valid.sum()), n_rows=n_rows,
        value_title="Percent of responses" if cfg.aggregation == "percent" else "Number of responses",
        is_percent=cfg.aggregation == "percent", base_note=note, warnings=warnings,
        notes={"chart": "histogram", "x_title": cfg.column, "edges": edges.tolist()})


# ── box plot ──────────────────────────────────────────────────────────────────

def box_stats(values: np.ndarray) -> Dict[str, float]:
    """Quartiles, Tukey whiskers and outliers for one set of values."""
    q1, med, q3 = np.percentile(values, [25, 50, 75])
    iqr = q3 - q1
    lo_fence, hi_fence = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    inside = values[(values >= lo_fence) & (values <= hi_fence)]
    return {"min": float(values.min()), "q1": float(q1), "median": float(med),
            "q3": float(q3), "max": float(values.max()), "mean": float(values.mean()),
            "whisker_lo": float(inside.min()), "whisker_hi": float(inside.max()),
            "n": int(len(values)),
            "outliers": [float(v) for v in values[(values < lo_fence) | (values > hi_fence)]]}


def _box(frame: pd.DataFrame, cfg: ChartConfig) -> ChartData:
    warnings: List[str] = []
    sub = _filtered(frame, cfg)
    group, keep = _group_labels(sub, cfg)
    sub, group = sub.loc[keep], group[keep]
    nums = _numbers(sub, cfg.column, cfg, warnings)
    n_rows, valid = int(len(sub)), nums.notna()
    if not valid.any():
        raise ChartBuildError(f"'{cfg.column}' has no numbers to plot.")
    names = _first_seen(group[valid]) if cfg.group_by else [""]
    stats = {g: box_stats(nums[valid & (group == g)].to_numpy()) for g in names}
    first_seen = {g: i for i, g in enumerate(names)}
    order = _sort_categories(names, {g: stats[g]["median"] for g in names}, cfg.sort,
                             cfg.recode.order, first_seen)
    rows, outliers = [], []
    for i, g in enumerate(order):
        s = stats[g]
        label = g or cfg.column
        rows.append({
            "category": label, "group": g, "count": s["n"], "denominator": np.nan,
            "percent": np.nan, "value": s["median"], "valid_n": s["n"],
            "missing_n": int((group == g).sum() - s["n"]), "sort_order": i,
            "display_label": labels.measure_label(s["median"], _decimals(cfg),
                                                  cfg.display.thousands_separator),
            "min": s["min"], "q1": s["q1"], "median": s["median"], "q3": s["q3"],
            "max": s["max"], "mean": s["mean"], "whisker_lo": s["whisker_lo"],
            "whisker_hi": s["whisker_hi"], "n_outliers": len(s["outliers"])})
        outliers.extend({"category": label, "group": g, "value": v} for v in s["outliers"])
    thin = [g or cfg.column for g in order if stats[g]["n"] < FEW_VALUES]
    if thin:
        warnings.append(f"Fewer than {FEW_VALUES} values for {', '.join(thin)}: the quartiles "
                        "are not reliable.")
    extra = ["min", "q1", "median", "q3", "max", "mean", "whisker_lo", "whisker_hi", "n_outliers"]
    return _finish(
        pd.DataFrame(rows), extra, categories=[r["category"] for r in rows],
        groups=[g for g in order if g] if cfg.group_by else [],
        group_fields=list(cfg.group_by), valid_n=int(valid.sum()),
        missing_n=n_rows - int(valid.sum()), n_rows=n_rows, value_title=cfg.column,
        is_percent=False,
        base_note="Box: 25th to 75th percentile, line at the median. Whiskers reach the "
                  "furthest value within 1.5 x the box height; points are beyond that.",
        warnings=warnings,
        notes={"chart": "box", "x_title": cfg.column,
               "outliers": pd.DataFrame(outliers, columns=["category", "group", "value"])})


# ── scatter ───────────────────────────────────────────────────────────────────

def _scatter(frame: pd.DataFrame, cfg: ChartConfig) -> ChartData:
    if not cfg.value_field:
        raise ChartBuildError("A scatter needs a second numeric field for the vertical axis "
                              "(the measure).")
    warnings: List[str] = []
    sub = _filtered(frame, cfg)
    group, keep = _group_labels(sub, cfg)
    sub, group = sub.loc[keep], group[keep]
    x = _numbers(sub, cfg.column, cfg, warnings)
    y = _numbers(sub, cfg.value_field, cfg, warnings)
    n_rows = int(len(sub))
    both = x.notna() & y.notna()
    if not both.any():
        raise ChartBuildError(f"No row has a number in both '{cfg.column}' and "
                              f"'{cfg.value_field}'.")
    dropped = n_rows - int(both.sum())
    if dropped:
        warnings.append(f"{dropped:,} of {n_rows:,} rows lack a number in one of the two fields "
                        "and are not plotted.")
    if int(both.sum()) > MANY_POINTS:
        warnings.append(f"{int(both.sum()):,} points is a lot for a scatter; overlapping points "
                        "will hide each other.")
    groups = _first_seen(group[both]) if cfg.group_by else [""]
    table = pd.DataFrame({
        "category": "", "group": group[both].values, "count": 1, "denominator": np.nan,
        "percent": np.nan, "value": y[both].values, "valid_n": int(both.sum()),
        "missing_n": dropped, "sort_order": range(int(both.sum())), "display_label": "",
        "x": x[both].values, "y": y[both].values})
    notes: Dict[str, object] = {"chart": "scatter", "x_title": cfg.column,
                                "y_title": cfg.value_field}
    base = ""
    xs, ys = x[both].to_numpy(), y[both].to_numpy()
    if len(xs) >= 3 and np.ptp(xs) > 0:
        slope, intercept = np.polyfit(xs, ys, 1)
        r = float(np.corrcoef(xs, ys)[0, 1]) if np.ptp(ys) > 0 else float("nan")
        notes["fit"] = {"slope": float(slope), "intercept": float(intercept), "r": r,
                        "n": int(len(xs))}
        if cfg.display.trend_line:
            base = (f"Line of best fit: {cfg.value_field} = {intercept:.3g} + "
                    f"{slope:.3g} x {cfg.column} (r = {r:.2f}, n = {len(xs):,}).")
    return _finish(
        table, ["x", "y"], categories=[], groups=groups if cfg.group_by else [],
        group_fields=list(cfg.group_by), valid_n=int(both.sum()), missing_n=dropped,
        n_rows=n_rows, value_title=cfg.value_field, is_percent=False, base_note=base,
        warnings=warnings, notes=notes)


# ── line and area ─────────────────────────────────────────────────────────────

def choose_grain(span_days: float) -> str:
    """The period for an automatic time axis, from the span the dates cover."""
    if span_days <= 90:
        return "day"
    if span_days <= 3 * 365:
        return "month"
    return "year"


def _period_label(period: pd.Period, grain: str) -> str:
    if grain == "day":
        return period.strftime("%Y-%m-%d")
    if grain == "week":
        return "Week of " + period.start_time.strftime("%Y-%m-%d")
    if grain == "month":
        return period.strftime("%Y-%m")
    if grain == "quarter":
        return f"{period.year} Q{period.quarter}"
    return str(period.year)


def _looks_like_dates(sub: pd.Series, cfg: ChartConfig) -> Optional[pd.Series]:
    """Parsed datetimes when most of the field reads as dates, else None."""
    text = clean.normalize_series(sub, collapse_whitespace=cfg.recode.collapse_whitespace,
                                  missing_tokens=cfg.recode.missing_tokens)
    answered = text.notna()
    if not answered.any():
        return None
    looks = text[answered].map(lambda s: bool(profile._DATE_HINT.match(s)))
    if looks.mean() < DATE_SHARE:
        return None
    parsed = pd.to_datetime(text.where(looks.reindex(text.index, fill_value=False)),
                            errors="coerce", format="mixed")
    return parsed if parsed[answered].notna().mean() >= DATE_SHARE else None


def _series(frame: pd.DataFrame, cfg: ChartConfig) -> ChartData:
    warnings: List[str] = []
    rc = cfg.recode
    is_measure = cfg.aggregation in MEASURE_AGGREGATIONS
    if is_measure and not cfg.value_field:
        raise ChartBuildError(f"'{cfg.aggregation}' needs a measure field to summarise.")
    sub = _filtered(frame, cfg)
    group, keep = _group_labels(sub, cfg)
    sub, group = sub.loc[keep], group[keep]
    n_rows = int(len(sub))
    if is_measure:
        vals = (clean.normalize_series(sub[cfg.value_field], missing_tokens=rc.missing_tokens)
                if cfg.aggregation == "distinct" else _numbers(sub, cfg.value_field, cfg, warnings))
    else:
        vals = pd.Series(1.0, index=sub.index)

    dates = _looks_like_dates(sub[cfg.column], cfg)
    x_kind, x_label, x_iso, x_order = "ordinal", None, None, None
    if dates is not None:
        ok = dates.notna()
        if int((~ok & clean.normalize_series(sub[cfg.column]).notna()).sum()):
            warnings.append("Some dates could not be read and were left out.")
        span = (dates[ok].max() - dates[ok].min()).days if ok.any() else 0
        grain = cfg.display.time_grain if cfg.display.time_grain in _GRAIN_FREQ else choose_grain(span)
        freq = _GRAIN_FREQ[grain]
        periods = dates[ok].dt.to_period(freq)
        full = pd.period_range(periods.min(), periods.max(), freq=freq)
        x_kind = "temporal"
        x_label = pd.Series(np.nan, index=sub.index, dtype=object)
        x_label[ok] = periods.map(lambda p: _period_label(p, grain)).values
        x_order = [_period_label(p, grain) for p in full]
        x_iso = {_period_label(p, grain): p.start_time.strftime("%Y-%m-%d") for p in full}
        notes_extra = {"grain": grain}
    else:
        x_label = clean.normalize_series(sub[cfg.column], collapse_whitespace=rc.collapse_whitespace,
                                         missing_tokens=rc.missing_tokens)
        seen = _first_seen(x_label)
        numeric = clean.to_numbers(pd.Series(seen)).notna().all() and len(seen) > 0
        if numeric:
            x_order = sorted(seen, key=lambda s: float(clean.to_numbers(pd.Series([s])).iloc[0]))
        elif cfg.sort == "alpha":
            x_order = sorted(seen, key=str.casefold)
        else:
            x_order = seen
        notes_extra = {}
    valid = x_label.notna() & (vals.notna())
    if not valid.any():
        raise ChartBuildError(f"'{cfg.column}' has nothing to plot after blanks are left out.")
    groups = _first_seen(group[valid]) if cfg.group_by else [""]
    frame_ = pd.DataFrame({"x": x_label[valid].values, "g": group[valid].values,
                           "v": vals[valid].values})
    total_by_group = frame_.groupby("g").size().to_dict()
    rows = []
    fill_zero = cfg.aggregation in ("count", "percent", "sum", "distinct") \
        and x_kind == "temporal"
    for g in groups:
        block = frame_[frame_["g"] == g]
        by = block.groupby("x")["v"]
        if cfg.aggregation in ("count", "percent"):
            agg = by.size()
        else:
            agg = {"sum": by.sum, "mean": by.mean, "median": by.median, "min": by.min,
                   "max": by.max, "distinct": by.nunique}[cfg.aggregation]()
        sizes = block.groupby("x").size()
        for i, x in enumerate(x_order):
            n = int(sizes.get(x, 0))
            if x in agg.index:
                v = float(agg[x])
            else:
                v = 0.0 if fill_zero else np.nan
            den = float(total_by_group[g]) if cfg.aggregation == "percent" else np.nan
            pct = 100.0 * n / den if cfg.aggregation == "percent" and den else np.nan
            rows.append({"category": x, "group": g, "count": n, "denominator": den,
                         "percent": pct, "value": pct if cfg.aggregation == "percent" else v,
                         "valid_n": int(total_by_group[g]), "missing_n": 0, "sort_order": i,
                         "x": x_iso.get(x, x) if x_iso else x})
    table = pd.DataFrame(rows)
    d = cfg.display
    if cfg.aggregation == "percent":
        table["display_label"] = table["percent"].map(lambda p: labels.format_percent(p, d.decimals))
    elif cfg.aggregation in ("count", "distinct"):
        table["display_label"] = table["value"].map(
            lambda v: labels.format_number(v, 0, d.thousands_separator))
    else:
        table["display_label"] = table["value"].map(
            lambda v: labels.format_number(v, _decimals(cfg), d.thousands_separator))
    if cfg.aggregation in ("count", "percent"):
        title = ("Number of responses" if cfg.aggregation == "count"
                 else "Percent of the group's responses in each period")
    else:
        title = f"{_AGG_NAMES[cfg.aggregation]} of {cfg.value_field}"
    if len(x_order) < 3:
        warnings.append("Only {} point(s) on the horizontal axis: a line needs a few more to "
                        "show a trend.".format(len(x_order)))
    return _finish(
        table, ["x"], categories=x_order, groups=groups if cfg.group_by else [],
        group_fields=list(cfg.group_by), valid_n=int(valid.sum()),
        missing_n=n_rows - int(valid.sum()), n_rows=n_rows, value_title=title,
        is_percent=cfg.aggregation == "percent", base_note="", warnings=warnings,
        notes={"chart": cfg.chart_type, "x_kind": x_kind, "x_title": cfg.column, **notes_extra})
