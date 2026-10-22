"""A suggestion for which columns of a survey file mean what.

QualSafe never picks the answers column for you: the first text-like column of
a long-form survey is often the *question*, and analysing the prompts instead of
the answers still "succeeds". So this only *suggests*. The screen shows the
suggestion with a sample of what is in the column and waits for one explicit
click. Nothing here changes a setting.

Two telltales separate answers from prompts:

* answers vary: nearly every row's text is different (high share of distinct values);
* a prompt repeats: the same long sentence in every row, or nearly so.

The file layout follows from how many columns look like answers: one means long
(each row is one answer, perhaps with a question column); two or more means wide
(each answer column is its own question).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

import pandas as pd

#: A column is answer-like when most rows differ and the text is not a one-word label.
MIN_ANSWER_LENGTH = 20
MIN_DISTINCT_SHARE = 0.6
#: A column is prompt-like when it repeats: few distinct values, and sentences long.
MAX_PROMPT_DISTINCT_SHARE = 0.1
MIN_PROMPT_LENGTH = 15

_ID_NAME = re.compile(r"(^|[_\s-])(id|respondent|participant)$|^(id|respondent|participant)([_\s-]|$)",
                      re.IGNORECASE)


@dataclass(frozen=True)
class Suggestion:
    """What the file looks like. `answers` is one column when long, two or more when wide."""

    shape: str                              # "long" | "wide"
    answers: Tuple[str, ...]
    question: str = ""                      # long only: the column naming each question
    respondent: str = ""                    # a column that identifies a respondent

    def describe(self) -> List[str]:
        """Plain lines for the screen, one per thing suggested."""
        if self.shape == "wide":
            lines = ["Answers: " + ", ".join(self.answers) + " (one column per question)"]
        else:
            lines = [f"Answers: {self.answers[0]}"]
            if self.question:
                lines.append(f"Question: {self.question}")
        if self.respondent:
            lines.append(f"Respondent: {self.respondent}")
        return lines


def _strings(series: pd.Series) -> pd.Series:
    return series.dropna().astype(str).str.strip().loc[lambda s: s != ""]


def _is_text(series: pd.Series) -> bool:
    return series.dtype == object or str(series.dtype) == "string"


def suggest_columns(frame: pd.DataFrame) -> Optional[Suggestion]:
    """A suggestion, or None when nothing in the file looks like written answers."""
    if frame is None or frame.empty:
        return None
    answers, prompts = [], []
    for name in frame.columns:
        if not _is_text(frame[name]):
            continue
        text = _strings(frame[name])
        if len(text) < 2:
            continue
        distinct = text.nunique() / len(text)
        length = float(text.str.len().median())
        if distinct <= MAX_PROMPT_DISTINCT_SHARE and length >= MIN_PROMPT_LENGTH:
            prompts.append(str(name))
        elif distinct >= MIN_DISTINCT_SHARE and length >= MIN_ANSWER_LENGTH:
            answers.append((str(name), length))
    if not answers:
        return None
    respondent = _respondent_column(frame)
    if len(answers) >= 2:
        return Suggestion("wide", tuple(n for n, _ in answers), respondent=respondent)
    question = prompts[0] if prompts else ""
    return Suggestion("long", (answers[0][0],), question=question, respondent=respondent)


def _respondent_column(frame: pd.DataFrame) -> str:
    """A column named like an id whose values are all different."""
    for name in frame.columns:
        if _ID_NAME.search(str(name)) and frame[name].notna().all() and frame[name].is_unique:
            return str(name)
    return ""


def sample_of(frame: pd.DataFrame, column: str, limit: int = 80) -> str:
    """The start of the first non-empty value in a column, for the screen to show.

    Shown so a person can see at a glance that this is answers and not prompts.
    Never stored."""
    values = _strings(frame[column]) if column in frame.columns else []
    if len(values) == 0:
        return ""
    first = " ".join(str(values.iloc[0]).split())
    return first if len(first) <= limit else first[:limit].rstrip() + "…"
