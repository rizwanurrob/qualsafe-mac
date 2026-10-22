"""The short tips behind the small (i) buttons (V8_PLAN.md section 6, point 2).

One or two plain sentences per control that is not obvious, each pointing to the step
article that says more. Shared by both apps. Nothing here imports Qt or Streamlit.

`LABEL_TIPS` lets a screen attach a tip just by naming the row's label; a label that
means different things on two screens (for example "Method") is passed a tip id instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional


@dataclass(frozen=True)
class Tip:
    text: str
    article: str            # `<activity>-<step>`: the article the "More" link opens


TIPS: Dict[str, Tip] = {
    # Surveys, step 1: Load
    "survey.layout": Tip(
        "Choose one column per question if each row is one person who answered several "
        "questions. Choose one answer per row if each row is a single answer.",
        "surveys-load"),
    "survey.question_column": Tip(
        "Use this if one column says which question each answer replies to. Leave it as "
        "(none) if every row answers the same question.", "surveys-load"),
    "survey.question_label": Tip(
        "Used when there is no question column: the label these answers are reported under.",
        "surveys-load"),
    "survey.respondent_id": Tip(
        "A column that identifies each person, so several answers from one person stay "
        "linked to them.", "surveys-load"),
    "survey.details": Tip(
        "Columns such as class year that you may want to compare themes across. Keep the "
        "ones you need.", "surveys-load"),
    # Surveys, step 2: Themes
    "themes.per_question": Tip(
        "Optional. Give one question its own themes, one line each, written as "
        "Question :: Theme A | Theme B.", "surveys-themes"),
    # Surveys, step 3: Code
    "code.method": Tip(
        "The way QualSafe works out its suggestions. The first choice is fine for most "
        "files.", "surveys-code"),
    "code.review_limits": Tip(
        "Answers where QualSafe is not confident enough are marked Needs your review. "
        "Raise the limits to check more answers, or lower them to check fewer.",
        "surveys-code"),
    "written.description": Tip(
        "Say in a sentence or two what counts as this code. It is what QualSafe asks about "
        "each answer, so be specific.", "surveys-code"),
    "written.kind": Tip(
        "Most codes are yes or no: does the answer touch this theme? Choose a rating scale "
        "only if you want a level, such as none, mild or severe.", "surveys-code"),
    "written.mode": Tip(
        "Each code on its own lets one answer have several codes. One code per answer picks "
        "the best fit for each answer.", "surveys-code"),
    "written.limits": Tip(
        "Scores between these two numbers are marked for you to check. Scores outside them "
        "are treated as a clear yes or a clear no.", "surveys-code"),
    "written.piece": Tip(
        "Long answers are split into overlapping pieces so that none is cut off. This sets "
        "the longest piece.", "surveys-code"),
    # Charts
    "chart.kind": Tip(
        "QualSafe guesses what kind of question this is from the answers. Change it if the "
        "guess is wrong, for example when a number is really a choice.", "charts-question"),
    "chart.split": Tip(
        "Pick a column, such as class year, to see the chart separately for each group.",
        "charts-question"),
    "chart.sharpness": Tip(
        "300 is sharp enough to print. 150 is fine for a slide and makes a smaller file.",
        "charts-save"),
    # Surveys and Interviews, step 4: Explore (Modelling)
    "model.method": Tip(
        "The goal you chose picks a sensible method. Change it only if you or a reviewer "
        "need a particular one.", "surveys-explore"),
    "model.folds": Tip(
        "The data is split into this many parts, and each part takes a turn at being left "
        "out to test the result. More parts take longer.", "surveys-explore"),
    "model.seed": Tip(
        "A number that makes the chance parts of the analysis repeatable. Use the same "
        "number to get the same result again.", "surveys-explore"),
}

#: Row label -> tip id, for labels that mean one thing everywhere they appear.
LABEL_TIPS: Dict[str, str] = {
    "Layout": "survey.layout",
    "Question column": "survey.question_column",
    "Question label": "survey.question_label",
    "Respondent ID column": "survey.respondent_id",
    "Respondent details to keep": "survey.details",
    "Different themes for one question": "themes.per_question",
    "Method": "code.method",
    "Check suggestions": "code.review_limits",
    "Description": "written.description",
    "Kind of code": "written.kind",
    "How to code": "written.mode",
    "Ask me to check scores from": "written.limits",
    "up to": "written.limits",
    "Longest piece of an answer": "written.piece",
    "Kind of question": "chart.kind",
    "Split by (optional)": "chart.split",
    "Sharpness": "chart.sharpness",
    "Folds": "model.folds",
    "Seed": "model.seed",
}


def get(tip_id: str) -> Optional[Tip]:
    return TIPS.get(tip_id)


def for_label(label: str) -> Optional[str]:
    """The tip id for a row label, or None."""
    return LABEL_TIPS.get(label)
