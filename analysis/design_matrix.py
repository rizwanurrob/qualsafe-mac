#!/usr/bin/env python
"""
The case-level design matrix — one row per case, ready to model (`V6_PLAN.md` §2).

Every model in v6 rests on this table, so an error here is an error in every
result built on top of it, invisibly. That is why this module exists separately
from the models and why it is this heavily commented.

**The unit is the point.** `analysis/crosstab.join_descriptors` returns one row
per *coding*, which is right for charts and wrong for regression: a respondent
with six codes would enter the model six times and one with a single code once,
so the sample would be weighted by how much the analyst coded each person. That
is an artifact of the coding process, not a property of the data. This returns
one row per case, and the case is declared rather than inferred.

What a row looks like
---------------------
======================  ==========================================  ============
column                  from                                        type
======================  ==========================================  ============
``case_id``             ``source_id`` or ``respondent_id``           key
``code::Cost``          one column per code                         0/1 or count
``desc::class_year``    the descriptor table, pivoted                number or 0/1
``n_codes``             derived                                      count
======================  ==========================================  ============

Four decisions, each a place this could go quietly wrong
--------------------------------------------------------
**Absent is zero; missing is missing.** A code that was not applied to a case is
a real zero — the analyst read it and did not apply the code. A descriptor that
was never collected is unknown, and turning it into a zero would invent data.
Conflating the two is the most common way a survey matrix lies, so they are kept
apart: code columns are never null, descriptor columns can be.

**The rater is a filter, and pooling is reported.** Codings from a human and a
transformer in one matrix build a variable neither of them asserted, and unlike
a co-occurrence heatmap — where it merely inflates a count — a regression will
report a coefficient and a standard error for it. `PORTED_BACK.md` §5 recorded
this trap for co-occurrence; the consequences are worse here.

**Categorical descriptors get a named reference level.** One-hot encoding with
an unstated baseline produces coefficients nobody can interpret: "program_B =
0.4" means nothing until you know it is relative to program A. The reference is
chosen deterministically (first in sort order) and returned, not left implicit.

**"Parses as a number" is not "is a number".** Class year, ZIP code, cohort,
Likert response and respondent id are all numeric in *form*, and treating one as
continuous asserts that the step from 2024 to 2025 means the same as 2025 to
2026 — a modelling decision, made silently, by a type check. This module cannot
know the analyst's intent, so it does two things instead of guessing: it reports
every descriptor it read as a number, and it flags the ones with suspiciously
few distinct values. `categorical=` forces the question the other way. The
inverse problem, numbers stored as text, is `chart_spec._is_numeric_in_disguise`.

**Near-constant columns are dropped and listed.** A code on 2 of 200 cases
cannot support a coefficient. Keeping it produces a huge standard error that
reads as a finding to anyone skimming, so such columns leave the matrix and are
named in the report.

Nothing here fits a model or imports a front end.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

import pandas as pd

#: Column-name prefixes. Namespaced because a descriptor called `weight`,
#: `coder` or — really — the same word as a code would otherwise collide, and a
#: silently overwritten column is a wrong model rather than an error.
CODE_PREFIX = "code::"
DESC_PREFIX = "desc::"

#: A column varying on fewer than this many cases cannot support a coefficient.
#: Two cases out of two hundred is a story about two people, not a variable.
MIN_VARYING = 5

#: …or on fewer than this share of them, whichever is larger. Guards the other
#: end: 5 of 5000 is still nothing.
MIN_VARYING_SHARE = 0.02

#: How a code becomes a number.
ENCODINGS = ("binary", "count")

#: What counts as a case.
UNITS = ("source_id", "respondent_id")

#: A numeric descriptor with no more distinct values than this is probably a
#: category wearing numerals -- class year, cohort, a Likert response. Not
#: converted automatically, because sometimes it really is a number; flagged,
#: so the analyst decides rather than the type check.
SUSPICIOUS_NUMERIC_LEVELS = 8


@dataclass(frozen=True)
class DesignMatrix:
    """A modelling table, and everything needed to qualify it."""

    frame: pd.DataFrame
    unit: str
    encoding: str
    #: Rater whose codings built the code columns; None means every rater was
    #: pooled, which is reported rather than assumed harmless.
    rater_id: Optional[str] = None
    #: Raters that actually contributed, so pooling can be described precisely.
    raters_pooled: List[str] = field(default_factory=list)
    #: Categorical descriptor -> the level its dummies are relative to.
    reference_levels: Dict[str, str] = field(default_factory=dict)
    #: Descriptors read as continuous numbers -> how many distinct values
    #: they had. Reported because reading one as a number is a modelling
    #: decision, and an unreported decision is one nobody can disagree with.
    numeric_descriptors: Dict[str, int] = field(default_factory=dict)
    #: Columns removed for having too little variation, with the reason.
    dropped: Dict[str, str] = field(default_factory=dict)
    #: Set when no matrix could be built, saying why in a sentence.
    refusal: str = ""

    @property
    def usable(self) -> bool:
        return not self.refusal and not self.frame.empty

    @property
    def n_cases(self) -> int:
        return 0 if self.frame.empty else len(self.frame)

    def code_columns(self) -> List[str]:
        return [c for c in self.frame.columns if c.startswith(CODE_PREFIX)]

    def descriptor_columns(self) -> List[str]:
        return [c for c in self.frame.columns if c.startswith(DESC_PREFIX)]

    def caveats(self) -> List[str]:
        """What has to be said about any model fitted on this."""
        notes: List[str] = []
        if self.rater_id is None and len(self.raters_pooled) > 1:
            notes.append(
                f"The code columns pool {len(self.raters_pooled)} coders "
                f"({', '.join(self.raters_pooled)}). A case one coder marked A "
                "and another marked B carries both, which neither of them "
                "claimed. Pick a single coder for variables one person actually "
                "asserted.")
        machine = [r for r in self.raters_pooled
                   if not str(r).startswith("human")]
        if machine and (self.rater_id is None or self.rater_id in machine):
            notes.append(
                f"Codes from an automated coder ({', '.join(machine)}) are in "
                "this matrix. They are estimates, not measurements: error in a "
                "predictor pulls its coefficient toward zero, and any effect "
                "reported for one is a lower bound at best.")
        if self.dropped:
            listed = ", ".join(sorted(self.dropped)[:5])
            more = f" and {len(self.dropped) - 5} more" if len(self.dropped) > 5 else ""
            notes.append(
                f"{len(self.dropped)} column(s) were dropped for too little "
                f"variation to model: {listed}{more}.")
        if self.reference_levels:
            pairs = ", ".join(f"{key} vs “{level}”"
                              for key, level in sorted(self.reference_levels.items()))
            notes.append(
                f"Categorical descriptors are compared against a reference "
                f"level: {pairs}.")
        suspicious = sorted(k for k, levels in self.numeric_descriptors.items()
                            if levels <= SUSPICIOUS_NUMERIC_LEVELS)
        if suspicious:
            listed = ", ".join(
                f"{key} ({self.numeric_descriptors[key]} distinct values)"
                for key in suspicious)
            notes.append(
                f"Read as a continuous number: {listed}. A model will assume "
                "the steps between those values are equal and meaningful — "
                "true for age, not for a class year or a cohort. Pass them as "
                "categorical if that is not what you want.")
        if self.unit == "source_id":
            notes.append(
                "The case is the document. If one respondent contributed "
                "several documents they appear several times; group by "
                "respondent instead if that is not what you want.")
        return notes

    def describe(self) -> str:
        """One line for a caption or a log."""
        whose = "all coders" if self.rater_id is None else self.rater_id
        per = "document" if self.unit == "source_id" else "respondent"
        counted = "applied or not" if self.encoding == "binary" else "counted"
        return (f"{self.n_cases} case(s), one per {per}; "
                f"{len(self.code_columns())} theme column(s) ({counted}); "
                f"{len(self.descriptor_columns())} respondent-detail column(s); "
                f"coded by {whose}")


def build_design_matrix(
    coding_df: pd.DataFrame,
    descriptor_df: Optional[pd.DataFrame] = None,
    *,
    unit: str = "source_id",
    encoding: str = "binary",
    rater_id: Optional[str] = None,
    categorical: Optional[Sequence[str]] = None,
    min_varying: Optional[int] = None,
    drop_near_constant: bool = True,
) -> DesignMatrix:
    """One row per case, one column per code, descriptors alongside.

    `unit` is `source_id` (per document) or `respondent_id` (per person, across
    their documents — only meaningful for wide-form survey ingestion).

    `encoding` is `binary` (did this case carry the code) or `count` (how many
    times). Binary is the default because in survey mode an excerpt is usually
    the whole response, so a count would mostly measure how many excerpts a
    document was split into rather than anything about the respondent.
    """
    if unit not in UNITS:
        raise ValueError(f"unit must be one of {UNITS}, not {unit!r}")
    if encoding not in ENCODINGS:
        raise ValueError(f"encoding must be one of {ENCODINGS}, not {encoding!r}")

    if coding_df is None or coding_df.empty:
        return DesignMatrix(
            frame=pd.DataFrame(), unit=unit, encoding=encoding, rater_id=rater_id,
            refusal="Nothing is coded yet, so there is nothing to model.")

    for column in (unit, "code_name"):
        if column not in coding_df.columns:
            return DesignMatrix(
                frame=pd.DataFrame(), unit=unit, encoding=encoding,
                rater_id=rater_id,
                refusal=f"The coding table has no “{column}” column, so a "
                        f"case-level matrix cannot be built from it.")

    raters_pooled = _raters(coding_df)

    coding = coding_df
    if rater_id is not None:
        if "rater_id" not in coding.columns:
            return DesignMatrix(
                frame=pd.DataFrame(), unit=unit, encoding=encoding,
                rater_id=rater_id,
                refusal="The coding table records no coder, so it cannot be "
                        "filtered to one.")
        coding = coding[coding["rater_id"] == rater_id]
        raters_pooled = [rater_id]

    coding = coding[coding[unit].notna()]
    if coding.empty:
        whose = "" if rater_id is None else f" by {rater_id}"
        return DesignMatrix(
            frame=pd.DataFrame(), unit=unit, encoding=encoding, rater_id=rater_id,
            raters_pooled=raters_pooled,
            refusal=f"No codings{whose} carry a {unit}, so there are no cases "
                    "to model.")

    frame = _code_columns(coding, unit=unit, encoding=encoding)

    if descriptor_df is not None and not descriptor_df.empty:
        frame, references, numerics = _add_descriptors(
            frame, descriptor_df, coding, unit=unit,
            categorical=set(categorical or ()))
    else:
        references, numerics = {}, {}

    dropped: Dict[str, str] = {}
    if drop_near_constant:
        frame, dropped = _drop_near_constant(
            frame, min_varying=min_varying, keep={"case_id"})

    refusal = ""
    if len(frame) < 2:
        refusal = (f"Only {len(frame)} case(s) after grouping by {unit}. A model "
                   "needs cases to compare.")
    elif not any(c.startswith(CODE_PREFIX) or c.startswith(DESC_PREFIX)
                 for c in frame.columns):
        refusal = ("Every column had too little variation to model. With this "
                   "much coding there is nothing a model could fit.")

    return DesignMatrix(
        frame=pd.DataFrame() if refusal else frame,
        unit=unit, encoding=encoding, rater_id=rater_id,
        raters_pooled=raters_pooled, reference_levels=references,
        numeric_descriptors=numerics, dropped=dropped, refusal=refusal)


def matrix_from_project(project, *, unit: str = "source_id",
                        encoding: str = "binary",
                        rater_id: Optional[str] = None,
                        **kwargs: Any) -> DesignMatrix:
    """Build the matrix for a project's coding and descriptors."""
    return build_design_matrix(
        project.coding_table(), project.descriptor_table(),
        unit=unit, encoding=encoding, rater_id=rater_id, **kwargs)


# -- pieces -----------------------------------------------------------------


def _raters(coding_df: pd.DataFrame) -> List[str]:
    if "rater_id" not in coding_df.columns:
        return []
    return sorted({str(r) for r in coding_df["rater_id"].dropna() if str(r)})


def _code_columns(coding: pd.DataFrame, *, unit: str,
                  encoding: str) -> pd.DataFrame:
    """Pivot codings to one column per code.

    `fill_value=0` is correct here and only here: a code absent from a case was
    read and not applied, which is a real zero. Descriptors get no such
    treatment — see `_add_descriptors`.
    """
    counts = (coding.groupby([unit, "code_name"]).size()
              .unstack(fill_value=0).sort_index())
    if encoding == "binary":
        counts = (counts > 0).astype(int)
    counts.columns = [f"{CODE_PREFIX}{name}" for name in counts.columns]

    frame = counts.reset_index().rename(columns={unit: "case_id"})
    frame["case_id"] = frame["case_id"].astype(str)

    # Offered as a control: how much a case was coded at all. A theme's
    # coefficient can otherwise be picking up "this person wrote a lot".
    code_cols = [c for c in frame.columns if c.startswith(CODE_PREFIX)]
    frame["n_codes"] = frame[code_cols].sum(axis=1)
    return frame


def _add_descriptors(frame: pd.DataFrame, descriptor_df: pd.DataFrame,
                     coding: pd.DataFrame, *, unit: str,
                     categorical: set):
    """Join descriptors on, numeric where possible, dummies otherwise.

    Descriptors live per `source_id`. When the case is the respondent, a
    respondent's sources must agree on a value; the first is taken and this is
    a known simplification rather than a considered position — see
    `V6_PLAN.md`.

    No `fill_value` anywhere: a descriptor that was never collected stays NaN,
    because zero would be a measurement nobody made.
    """
    wide = descriptor_df.pivot_table(
        index="source_id", columns="key", values="value", aggfunc="first")

    if unit != "source_id":
        # Map each source to its case, then take one value per case.
        mapping = (coding[["source_id", unit]].dropna().drop_duplicates()
                   .set_index("source_id")[unit])
        wide = wide.join(mapping.rename("__case__"), how="inner")
        wide = wide.groupby("__case__").first()

    wide.index = wide.index.astype(str)
    wide = wide.reindex(frame["case_id"].tolist())

    references: Dict[str, str] = {}
    numerics: Dict[str, int] = {}
    for key in list(wide.columns):
        series = wide[key]
        numeric = pd.to_numeric(series, errors="coerce")
        forced = str(key) in categorical
        # Numeric only if essentially everything present parses as a number;
        # one stray "n/a" in a column of ages must not silently null the column.
        present = series.notna().sum()
        if not forced and present and numeric.notna().sum() >= present * 0.9:
            frame[f"{DESC_PREFIX}{key}"] = numeric.to_numpy()
            numerics[str(key)] = int(numeric.dropna().nunique())
            continue

        levels = sorted({str(v) for v in series.dropna()})
        if len(levels) < 2:
            continue                      # constant; nothing to compare against
        reference, *rest = levels
        references[str(key)] = reference
        for level in rest:
            column = f"{DESC_PREFIX}{key}={level}"
            dummy = (series.astype("object").map(
                lambda v, lvl=level: float("nan") if pd.isna(v)
                else (1 if str(v) == lvl else 0)))
            frame[column] = dummy.to_numpy()

    return frame, references, numerics


def _drop_near_constant(frame: pd.DataFrame, *, min_varying: Optional[int],
                        keep: Sequence[str]):
    """Remove columns too constant to model, and say which and why."""
    floor = min_varying if min_varying is not None else max(
        MIN_VARYING, int(round(len(frame) * MIN_VARYING_SHARE)))

    dropped: Dict[str, str] = {}
    for column in list(frame.columns):
        if column in keep:
            continue
        series = frame[column]
        present = series.notna()
        if present.sum() < 2:
            dropped[column] = "no values"
            continue
        values = series[present]
        if values.nunique() < 2:
            dropped[column] = "the same value on every case"
            continue
        if set(values.unique()) <= {0, 1}:
            minority = int(min(values.sum(), len(values) - values.sum()))
            if minority < floor:
                dropped[column] = (f"varies on only {minority} case(s); "
                                   f"{floor} needed")
    return frame.drop(columns=list(dropped)), dropped
