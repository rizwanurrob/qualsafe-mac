#!/usr/bin/env python
"""
Assistive PII scan (v3.1.1, Phase 0.5).

The FERPA/PII gate asks the analyst to confirm their file has been reviewed for
PII. That question is much easier to answer honestly with evidence in front of
you, so this module looks for the obvious signals and shows them next to the
checkbox.

Deliberately heuristics, not a verdict
--------------------------------------
Everything here is a *signal to review*, never a pass/fail. Two reasons:

1. It cannot be complete. A name mentioned mid-sentence ("my advisor Dr. Chen
   said...") is PII that no regex here will catch. Presenting this as a clean
   bill of health would make the tool's judgment a substitute for the analyst's,
   which is exactly backwards — they know their data, this does not.
2. Survey text is full of numbers that look like identifiers and aren't (years,
   prices, room numbers). If the scan blocks on those, analysts learn to click
   through warnings, and the gate becomes decorative — worse than no gate, since
   it manufactures a false record of review.

So: report what was found, in the analyst's words, above the checkbox they have
to tick themselves.

Examples are masked before they leave this module. A panel that helpfully prints
the PII it found — into a screenshot, a support ticket, a log — has leaked the
thing it was asked to protect.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence

import pandas as pd

EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.\w{2,}\b")
# US-centric by design: this tool's users are US institutions. International
# numbers will be missed — another reason this is advisory.
# The bracketed area code is its own alternative: `\b` cannot match before "(",
# so the old pattern began at the digits and masking left a stray "(" behind.
PHONE = re.compile(r"(?:\+?1[-.\s]?)?(?:\(\d{3}\)|\b\d{3})[-.\s]?\d{3}[-.\s]?\d{4}\b")
LONG_ID = re.compile(r"\b\d{7,10}\b")
SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
FULL_NAME = re.compile(r"^[A-Z][a-z]{1,20} [A-Z][a-z]{1,20}$")

# ── identifiers inside prose (review finding F6) ───────────────────────────
# Open-ended answers name people ("my advisor Dr. Chen"), streets and rooms,
# and the patterns above caught none of them. A capitalised word is not a name
# ("the Green Line", "Financial Aid"), and a scanner that cries wolf teaches
# analysts to click past it, so a name is reported only where the sentence
# itself says a person follows: a title, a relationship ("my roommate"), or a
# thank-you ("shout out to"). Measured on synthetic data: every
# planted name, address and room found, and no alarm on 600 name-free
# responses -- but those names were planted in these same frames, so the
# recall is optimistic; a name with no anchor ("Jenna helped me") is missed.
_NAME = r"[A-Z][a-z]+(?:[-'][A-Z]?[a-z]+)?"
_NAME_RUN = rf"{_NAME}(?:\s+{_NAME})?"
_TITLE = r"(?:Dr|Prof|Professor|Mr|Mrs|Ms|Mx|Dean|Coach)"
_RELATION = (r"(?:advisor|adviser|roommate|suitemate|professor|instructor|teacher|TA|RA|mentor|"
             r"tutor|friend|boss|manager|coach|counselor|counsellor|supervisor|partner|"
             r"girlfriend|boyfriend|sister|brother|cousin|aunt|uncle)")
_THANKS = r"(?:shout[- ]?out to|thanks to|thank you,?|kudos to|grateful to)"
#: Each has an `anchor` group that stays in the text and a `name` group that is masked.
NAME_ANCHORS = (
    re.compile(rf"\b(?P<anchor>{_TITLE}\.?\s+)(?P<name>{_NAME_RUN})"),
    re.compile(rf"\b(?P<anchor>(?i:my|our)\s+(?i:{_RELATION})\s+)(?P<name>{_NAME_RUN})"),
    re.compile(rf"\b(?P<anchor>(?i:{_THANKS})\s+)(?P<name>{_NAME_RUN})"),
)
#: Capitalised words that follow an anchor without being a name ("My advisor Was ...").
_NOT_A_NAME = {"Was", "Is", "Has", "Had", "And", "But", "The", "Said", "Says", "Never",
               "Always", "I", "It", "This", "That", "Everyone", "All"}
_STREET = (r"(?:St|Street|Ave|Avenue|Rd|Road|Blvd|Boulevard|Way|Ln|Lane|Dr|Drive|Pl|Place|"
           r"Ct|Court|Sq|Square|Ter|Terrace|Pkwy|Parkway)")
STREET_ADDRESS = re.compile(rf"\b\d{{1,5}}\s+(?:[A-Z][a-z]+\s+){{1,3}}{_STREET}\b")
ROOM_NUMBER = re.compile(r"\b(?i:room|rm|apt|apartment|suite|unit)\.?\s*#?\s*\d{1,4}[A-Za-z]?\b")

#: What the scanner cannot see. Shown with every summary, so a clean scan is
#: never read as "this file has no personal information".
SCANNER_LIMITS = (
    "The scan looks for emails, phone numbers, SSN-like and long ID numbers, "
    "street addresses, room numbers, and names that follow a title or a "
    "relationship (\"Dr. Chen\", \"my roommate Jenna\"). It cannot find a name "
    "with nothing around it (\"Jenna helped me\"), nicknames, or details that "
    "identify someone only in combination (a rare major plus a hometown). "
    "Read a sample of responses yourself.")


def find_prose_names(text: str) -> List[re.Match]:
    """Anchored name matches in `text` (see NAME_ANCHORS)."""
    out = []
    for pattern in NAME_ANCHORS:
        for match in pattern.finditer(text):
            if match.group("name").split()[0] not in _NOT_A_NAME:
                out.append(match)
    return out

# Substrings that make a column name suspicious. Matched against a normalized
# (lowercase, non-alphanumeric stripped) form so "Student ID" / "student_id" /
# "studentID" all hit.
SUSPICIOUS_COLUMN_TERMS = (
    "name",
    "email",
    "mail",
    "phone",
    "mobile",
    "address",
    "dob",
    "birth",
    "ssn",
    "student id",
    "studentid",
    "employeeid",
    "userid",
)

PATTERN_SIGNALS = (
    ("email address", EMAIL),
    ("SSN-like number", SSN),
    ("phone-like number", PHONE),
    ("long numeric ID", LONG_ID),
)


def _normalize_column(name: str) -> str:
    return re.sub(r"[^a-z0-9 ]", " ", str(name).lower())


def mask_example(value: str, kind: str) -> str:
    """Return a redacted preview of a hit — enough to recognize, not to identify."""
    text = str(value)
    if kind == "email address":
        match = EMAIL.search(text)
        if match:
            local, _, domain = match.group(0).partition("@")
            return f"{local[0]}***@***{domain[domain.rfind('.'):]}"
    for _, pattern in PATTERN_SIGNALS:
        match = pattern.search(text)
        if match and kind != "email address":
            hit = match.group(0)
            return text.replace(hit, f"{hit[:2]}{'*' * max(len(hit) - 2, 3)}")[:80]
    return (text[:40] + "…") if len(text) > 40 else text


def _text_like_columns(df: pd.DataFrame) -> List[str]:
    """Columns that can hold strings — dtype-agnostic (see sanitize_frame_for_csv)."""
    from pandas.api.types import is_bool_dtype, is_datetime64_any_dtype, is_numeric_dtype

    cols = []
    for col in df.columns:
        dtype = df[col].dtype
        if is_numeric_dtype(dtype) or is_bool_dtype(dtype) or is_datetime64_any_dtype(dtype):
            continue
        cols.append(col)
    return cols


def scan_frame(
    df: pd.DataFrame,
    text_cols: Optional[Sequence[str]] = None,
    sample_rows: int = 2000,
) -> List[Dict[str, Any]]:
    """Look for PII signals in `df`.

    Returns a list of ``{column, signal, n_hits, example_masked}`` dicts — one per
    (column, signal) pair that fired. An empty list means "nothing obvious was
    found", which is NOT the same as "there is no PII here".

    Only the first `sample_rows` rows are examined, so `n_hits` is a floor on a
    large file, not a total.
    """
    if df is None or df.empty:
        return []

    findings: List[Dict[str, Any]] = []
    sample = df.head(sample_rows)
    scan_cols = list(text_cols) if text_cols else _text_like_columns(sample)

    # 1. Column-name heuristics — fires on the column regardless of content, and
    #    covers structured PII the content regexes would miss (a "Last Name"
    #    column of ordinary words).
    for col in df.columns:
        normalized = _normalize_column(col)
        for term in SUSPICIOUS_COLUMN_TERMS:
            if term in normalized:
                findings.append(
                    {
                        "column": str(col),
                        "signal": f"column name suggests PII ('{term}')",
                        "n_hits": int(df[col].notna().sum()),
                        "example_masked": "—",
                    }
                )
                break

    # 2. Content patterns in text columns.
    for col in scan_cols:
        values = sample[col].dropna()
        if values.empty:
            continue
        as_text = values.astype(str)
        for kind, pattern in PATTERN_SIGNALS:
            hits = as_text[as_text.str.contains(pattern, regex=True, na=False)]
            if hits.empty:
                continue
            findings.append(
                {
                    "column": str(col),
                    "signal": kind,
                    "n_hits": int(len(hits)),
                    "example_masked": mask_example(hits.iloc[0], kind),
                }
            )

    # 2b. Identifiers inside prose: anchored names, street addresses, rooms.
    for col in scan_cols:
        as_text = sample[col].dropna().astype(str)
        if as_text.empty:
            continue
        for kind, finder in (
            ("name in text (after a title or relationship)", lambda t: bool(find_prose_names(t))),
            ("street address in text", lambda t: bool(STREET_ADDRESS.search(t))),
            ("room number in text", lambda t: bool(ROOM_NUMBER.search(t))),
        ):
            hits = as_text[as_text.map(finder)]
            if hits.empty:
                continue
            findings.append({
                "column": str(col), "signal": kind, "n_hits": int(len(hits)),
                "example_masked": mask_text_series(pd.Series([hits.iloc[0]])).iloc[0][:120],
            })

    # 3. Columns that look like a roster: mostly distinct "Firstname Lastname".
    for col in scan_cols:
        values = sample[col].dropna().astype(str)
        if len(values) < 5:
            continue
        name_like = values.str.match(FULL_NAME).mean()
        distinct_ratio = values.nunique() / len(values)
        if name_like >= 0.6 and distinct_ratio >= 0.5:
            findings.append(
                {
                    "column": str(col),
                    "signal": "values look like personal names",
                    "n_hits": int(values.str.match(FULL_NAME).sum()),
                    "example_masked": "e.g. 'J*** D***'",
                }
            )

    return findings


def summarize_findings(findings: List[Dict[str, Any]]) -> str:
    """One-line plain-language summary for the UI."""
    if not findings:
        return "No obvious personal details found. This is not a guarantee. " + SCANNER_LIMITS
    return findings_headline(findings) + " " + SCANNER_LIMITS


def findings_headline(findings: List[Dict[str, Any]]) -> str:
    """The result of the scan in a sentence, without the long list of what it cannot see.

    For a screen that shows `SCANNER_LIMITS` itself, one click away beside this."""
    if not findings:
        return "No obvious personal details found. This is not a guarantee."
    columns = sorted({f["column"] for f in findings})
    return (f"{len(findings)} possible personal detail(s) across {len(columns)} column(s): "
            f"{', '.join(columns[:5])}{'…' if len(columns) > 5 else ''}. Review before confirming.")


def mask_text_series(series: pd.Series) -> pd.Series:
    """Replace emails, phones, SSNs, long ids, street addresses, room numbers
    and anchored names in free text with placeholder tokens.

    Applied to the working frame when the analyst opts in. Kept coarse and
    obvious: the placeholders should be visible in outputs so a reader can tell
    masking happened, rather than silently altering quotes.
    """

    def _mask(value: Any) -> Any:
        if not isinstance(value, str):
            return value
        out = EMAIL.sub("[EMAIL]", value)
        out = SSN.sub("[SSN]", out)
        out = PHONE.sub("[PHONE]", out)
        out = LONG_ID.sub("[ID]", out)
        out = STREET_ADDRESS.sub("[ADDRESS]", out)
        out = ROOM_NUMBER.sub("[ROOM]", out)
        # Names last, keeping the anchor so the sentence still reads:
        # "My advisor [NAME] has been great."
        for match in sorted(find_prose_names(out), key=lambda m: m.start("name"), reverse=True):
            out = out[:match.start("name")] + "[NAME]" + out[match.end("name"):]
        return out

    return series.map(_mask)


def mask_frame(df: pd.DataFrame, columns: Sequence[str]) -> pd.DataFrame:
    """Return a copy of `df` with the given columns masked (see mask_text_series)."""
    out = df.copy()
    for col in columns:
        if col in out.columns:
            out[col] = mask_text_series(out[col])
    return out


# ── consistent pseudonyms (V7 Update 2, U5) ──────────────────────────────────
def _name_key(name: str) -> str:
    return " ".join(name.split()).casefold()


def pseudonymise_series(series: pd.Series,
                        mapping: Optional[Dict[str, str]] = None) -> tuple:
    """Mask a text column, giving each anchored name a consistent pseudonym.

    "My advisor Jenna Morales" and, three answers later, "thanks to Jenna
    Morales" both become [PERSON_1], so an analysis of who is mentioned where
    still works. Everything else is masked as `mask_text_series` does.

    Returns ``(masked_series, mapping)``, where mapping is ``{pseudonym: name}``.
    **The mapping re-identifies people**: it is returned to the caller to hand
    to the analyst, and must never be written into a project, an export or a
    log. Matching is on the exact name (spacing and case aside): "Okafor" and
    "Chinedu Okafor" get different pseudonyms, because deciding they are one
    person is a judgement this function will not make.
    """
    by_key: Dict[str, str] = {}
    out_map: Dict[str, str] = dict(mapping or {})
    for pseudonym, name in out_map.items():
        by_key[_name_key(name)] = pseudonym

    def _one(value: Any) -> Any:
        if not isinstance(value, str):
            return value
        text = value
        for match in sorted(find_prose_names(text), key=lambda m: m.start("name"), reverse=True):
            name = match.group("name")
            key = _name_key(name)
            if key not in by_key:
                pseudonym = f"[PERSON_{len(by_key) + 1}]"
                by_key[key] = pseudonym
                out_map[pseudonym] = name
            text = text[:match.start("name")] + by_key[key] + text[match.end("name"):]
        return mask_text_series(pd.Series([text])).iloc[0]

    return series.map(_one), out_map


def pseudonymise_frame(df: pd.DataFrame, columns: Sequence[str]) -> tuple:
    """`pseudonymise_series` over several columns with ONE mapping, so a person
    named in two columns gets one pseudonym. Returns ``(frame, mapping)``."""
    out = df.copy()
    mapping: Dict[str, str] = {}
    for col in columns:
        if col in out.columns:
            out[col], mapping = pseudonymise_series(out[col], mapping)
    return out, mapping

