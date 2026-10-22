"""The three plain goals of the Modelling screen (V8_PLAN.md section 3.10a), shared by both apps.

A person says what they want to know; QualSafe picks the method. The method can still be changed
under More options. Nothing here imports Qt or Streamlit.
"""

from __future__ import annotations

from typing import Iterable, List

from core.ux.fields import model_field_label

#: (key, method, what the person wants). The method is a key of `core.model_spec.METHODS`.
GOALS = (
    ("tree", "decision_tree", "See which themes go with the outcome, as rules I can read"),
    ("forest", "random_forest", "See which themes matter most for the outcome"),
    ("effect", "double_lasso", "Estimate the effect of one thing, allowing for the others"),
)
GOAL_KEYS = tuple(g[0] for g in GOALS)
METHOD_FOR_GOAL = {key: method for key, method, _text in GOALS}


def goal_for_method(method: str) -> str:
    """The goal a method belongs to, or '' when it is not one of the three (chosen by hand)."""
    return next((key for key, m, _t in GOALS if m == method), "")


def plain(text: str, columns: Iterable[str]) -> str:
    """A sentence from the shared model grammar, its internal column names in plain words."""
    text = text.replace("Drop a field on Outcome", "Choose what you want to explain")
    for name in sorted((c for c in columns if c != "case_id"), key=len, reverse=True):
        if name in text:
            text = text.replace(name, model_field_label(name))
    return text


def without(names: Iterable[str], *left_out: str) -> List[str]:
    """Predictors with the outcome (and the treatment) taken out: what you want to explain, or the
    effect of, cannot also be something that explains it."""
    gone = {n for n in left_out if n}
    return [n for n in names if n not in gone]
