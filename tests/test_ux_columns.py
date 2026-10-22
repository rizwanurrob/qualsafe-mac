"""Suggesting which columns hold the answers: it suggests, it never decides."""

from pathlib import Path

import pandas as pd
import pytest

from core.ux.columns import Suggestion, sample_of, suggest_columns

DATA = Path(__file__).resolve().parents[1] / "data"


def _long(n=12):
    return pd.DataFrame({
        "response_id": range(1, n + 1),
        "question_text": ["What has been the hardest part of your first year?"] * n,
        "response_text": [f"Answer number {i}: something quite different about money and time." for i in range(n)],
    })


def test_a_long_file_suggests_the_answers_the_question_and_the_respondent():
    s = suggest_columns(_long())
    assert s == Suggestion("long", ("response_text",), question="question_text", respondent="response_id")


def test_the_repeated_prompt_is_never_suggested_as_the_answers():
    """The failure this guards: analysing the questions and having the run succeed."""
    s = suggest_columns(_long())
    assert "question_text" not in s.answers


def test_a_wide_file_suggests_every_answer_column():
    n = 15
    frame = pd.DataFrame({
        "student_id": [f"s{i}" for i in range(n)],
        "Class_Year": ["First-year", "Second-year"] * 7 + ["First-year"],
        "Q1_success": [f"Success to me is a long reply number {i} about my plans." for i in range(n)],
        "Q2_barrier": [f"The main barrier I face is reply {i}, which has many words in it." for i in range(n)],
    })
    s = suggest_columns(frame)
    assert s.shape == "wide" and s.answers == ("Q1_success", "Q2_barrier")
    assert s.respondent == "student_id" and s.question == ""


def test_short_labels_and_categories_are_not_answers():
    frame = pd.DataFrame({"year": ["First", "Second"] * 6, "program": ["Nursing", "Law", "Arts"] * 4})
    assert suggest_columns(frame) is None


def test_a_numeric_only_file_suggests_nothing():
    assert suggest_columns(pd.DataFrame({"a": range(10), "b": range(10)})) is None
    assert suggest_columns(pd.DataFrame()) is None
    assert suggest_columns(None) is None


def test_an_id_must_be_unique_to_count_as_a_respondent():
    frame = _long()
    frame["response_id"] = 1
    assert suggest_columns(frame).respondent == ""


def test_describe_gives_plain_lines():
    assert suggest_columns(_long()).describe() == [
        "Answers: response_text", "Question: question_text", "Respondent: response_id"]


@pytest.mark.parametrize("name,shape,answers", [
    ("sample_survey_education.csv", "long", ("response_text",)),
    ("synthetic_customer_experience_feedback.csv", None, None),     # checked below
])
def test_the_files_that_ship(name, shape, answers):
    frame = pd.read_csv(DATA / name)
    s = suggest_columns(frame)
    if shape:
        assert s.shape == shape and s.answers == answers
    else:
        assert s is None or s.answers          # whatever it says, it names real columns
        assert all(a in frame.columns for a in (s.answers if s else ()))


def test_the_shipped_wide_file_is_recognised_as_wide():
    frame = pd.read_csv(DATA / "synthetic_entering_student_survey_wide.csv")
    s = suggest_columns(frame)
    assert s.shape == "wide" and len(s.answers) >= 2
    assert all(a in frame.columns for a in s.answers)


def test_sample_of_shows_the_start_of_a_value_and_never_a_whole_long_one():
    frame = _long()
    text = sample_of(frame, "response_text", limit=30)
    assert text.startswith("Answer number 0") and text.endswith("…") and len(text) <= 31
    assert sample_of(frame, "nope") == ""
    assert sample_of(pd.DataFrame({"a": [None, None]}), "a") == ""
