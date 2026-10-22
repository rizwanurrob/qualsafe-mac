"""Plain names for the fields a person can chart.

The coded results carry internal columns (`application_id`, `code_name`, `rater_id`,
`run_id`). They are right for the project file and wrong on screen: Update 3's rule
is no internal names where a person reads. This module is the one place that says
what each field is called on screen, which fields are technical (identifiers, shown
only when asked for), and what to call a field type.

Fields from the person's own data (their respondent details, such as `class_year`)
keep their own names, tidied for display: underscores become spaces.
"""

from __future__ import annotations

from typing import Dict

#: What the project's own columns are called on screen.
FRIENDLY_NAMES: Dict[str, str] = {
    "code_name": "Theme",
    "coder": "Coder",
    "confidence": "Confidence",
    "weight": "Weight",
    "respondent_id": "Respondent (ID)",
    "source_id": "Answer (ID)",
    "code_id": "Theme (ID)",
    "excerpt_id": "Passage (ID)",
    "application_id": "Coding (ID)",
    "rater_id": "Coder (ID)",
    "run_id": "Analysis run (ID)",
}

#: Vega-Lite types (core.chart_spec) in the words a person would use.
TYPE_WORDS: Dict[str, str] = {
    "nominal": "category",
    "ordinal": "ordered category",
    "quantitative": "number",
    "temporal": "date",
}


def is_technical(name: str) -> bool:
    """An identifier: useful to a program, not something to chart. Hidden by default."""
    lowered = str(name).lower()
    return lowered in {"id", "uuid"} or lowered.endswith("_id")


def friendly(name: str) -> str:
    """What to call a field on screen."""
    name = str(name)
    if name in FRIENDLY_NAMES:
        return FRIENDLY_NAMES[name]
    text = name.replace("_", " ").strip() or name
    return text[:1].upper() + text[1:] if text.islower() else text


#: Where a code came from, in words a person would use (stored as `a_priori` / `emergent`).
ORIGIN_WORDS = {"a_priori": "Decided before coding", "emergent": "Found while coding"}


def origin_label(origin: str) -> str:
    """What to show for a code's origin; an unknown value is tidied rather than hidden."""
    origin = str(origin or "")
    return ORIGIN_WORDS.get(origin) or (origin.replace("_", " ").capitalize() if origin else "")


#: What the model screen's three kinds of column are called on screen.
MODEL_KIND_WORDS = {"code": "theme", "descriptor": "respondent detail", "derived": "count"}


def model_field_label(name: str) -> str:
    """A model column by its plain name: `code::Cost` is the theme "Cost", `desc::gpa` is the
    respondent detail "Gpa", and a descriptor level such as `desc::Program=Nursing` reads
    "Program: Nursing"."""
    name = str(name)
    if name.startswith("code::"):
        return name[len("code::"):]
    if name.startswith("desc::"):
        rest = name[len("desc::"):]
        if "=" in rest:
            key, level = rest.split("=", 1)
            return f"{friendly(key)}: {level}"
        return friendly(rest)
    return friendly(name)


def type_word(vega_type: str) -> str:
    """`quantitative` -> `number`."""
    return TYPE_WORDS.get(vega_type, vega_type)
