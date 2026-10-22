"""
The category table: one editable grid that carries five of the brief's controls
(include/exclude, rename, combine, reorder, and the counts that motivate them).

    Category | Rows | Include | Display name | Combine into | Position

`source_categories` lists what is in the data (after filters, for the field or
fields being charted); `recode_from_table` turns the analyst's edits back into a
`Recode`. Both are pure, so the grid works the same in any front end and the
conversion can be tested without one.

Semantics, kept simple on purpose:

- **Include** off -> the category is left out (and out of the base).
- **Display name** differs from Category -> a display-only rename.
- **Combine into** holds a name -> every row with that same name becomes one new
  category; Display name is ignored for those rows (the new name *is* the label).
- **Position** filled in -> a manual order (lowest first). Rows without a
  position follow, in source order.

The data itself is never edited; this only produces a `Recode`.
"""

from __future__ import annotations

from typing import Dict, List, Optional

import pandas as pd

from core.chartbuilder import clean, transform
from core.chartbuilder.config import ChartConfig, Merge, Recode

COLUMNS = ["Category", "Rows", "Include", "Display name", "Combine into", "Position"]


def source_categories(frame: pd.DataFrame, cfg: ChartConfig) -> pd.DataFrame:
    """Distinct labels being charted, in source order, with how many rows have each.

    Uses the same cleaning and filters as the chart, and *not* the recode, so the
    grid always shows the original labels the analyst is editing. Select-all
    questions list the parsed choices; matrix questions the union over columns.
    """
    from core.chartbuilder import survey

    rc = cfg.recode
    cols = list(cfg.columns) if cfg.kind == "matrix" else [cfg.column]
    cols = [c for c in cols if c and c in frame.columns]
    if not cols:
        return pd.DataFrame(columns=["Category", "Rows"])
    mask = transform.filter_mask(frame, cfg.filters,
                                 collapse_whitespace=rc.collapse_whitespace,
                                 missing_tokens=rc.missing_tokens)
    sub = frame.loc[mask]
    labels: List[str] = []
    for col in cols:
        cleaned = clean.normalize_series(sub[col], collapse_whitespace=rc.collapse_whitespace,
                                         missing_tokens=rc.missing_tokens)
        if cfg.kind == "multi":
            parsed = survey.parse_multi(cleaned, cfg.multi)
            labels.extend(c for picked in parsed.choices for c in (picked or []))
        else:
            labels.extend(v for v in cleaned if isinstance(v, str))
    counts: Dict[str, int] = {}
    for label in labels:
        counts[label] = counts.get(label, 0) + 1
    return pd.DataFrame({"Category": list(counts), "Rows": list(counts.values())})


def category_table(frame: pd.DataFrame, cfg: ChartConfig) -> pd.DataFrame:
    """The grid, pre-filled from the current recode so edits are not lost."""
    base = source_categories(frame, cfg)
    rc = cfg.recode
    member_of = {m: merge.label for merge in rc.merges for m in merge.members}
    position = {label: i + 1 for i, label in enumerate(rc.order)}
    rows = []
    for cat, n in zip(base["Category"], base["Rows"]):
        merged = member_of.get(cat, "")
        shown = merged or rc.rename.get(cat, cat)
        rows.append({"Category": cat, "Rows": int(n), "Include": cat not in rc.exclude,
                     "Display name": rc.rename.get(cat, cat) if not merged else cat,
                     "Combine into": merged,
                     "Position": position.get(shown) if rc.order else None})
    return pd.DataFrame(rows, columns=COLUMNS)


def _blank(value) -> bool:
    return value is None or (isinstance(value, float) and value != value) \
        or str(value).strip() == ""


def recode_from_table(table: pd.DataFrame, base: Optional[Recode] = None) -> Recode:
    """A `Recode` from the edited grid. Fields the grid does not carry
    (blank handling, whitespace, tokens, item names) are kept from `base`."""
    out = Recode(**{k: v for k, v in vars(base or Recode()).items()})
    out.exclude, out.rename, out.merges, out.order = [], {}, [], []
    groups: Dict[str, List[str]] = {}
    shown: Dict[str, str] = {}
    for _, row in table.iterrows():
        cat = str(row["Category"])
        if not bool(row["Include"]):
            out.exclude.append(cat)
            continue
        combine = "" if _blank(row["Combine into"]) else str(row["Combine into"]).strip()
        if combine:
            groups.setdefault(combine, []).append(cat)
            shown[cat] = combine
            continue
        name = cat if _blank(row["Display name"]) else str(row["Display name"]).strip()
        if name != cat:
            out.rename[cat] = name
        shown[cat] = name
    out.merges = [Merge(label, members) for label, members in groups.items()]

    positioned = [(float(r["Position"]), i, str(r["Category"]))
                  for i, (_, r) in enumerate(table.iterrows())
                  if not _blank(r["Position"]) and str(r["Category"]) in shown]
    if positioned:
        placed = [shown[c] for _, _, c in sorted(positioned)]
        rest = [shown[str(c)] for c in table["Category"] if str(c) in shown]
        out.order = list(dict.fromkeys(placed + rest))
    return out
