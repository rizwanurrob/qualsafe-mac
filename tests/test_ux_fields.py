"""Plain names for chartable fields."""

import pytest

from core.chart_spec import suggested_charts
from core.ux import words
from core.ux.fields import FRIENDLY_NAMES, friendly, is_technical, type_word

PROJECT_COLUMNS = ["application_id", "excerpt_id", "source_id", "code_id", "code_name",
                   "weight", "confidence", "coder", "rater_id", "run_id", "respondent_id"]


def test_every_internal_column_has_a_plain_name():
    for column in PROJECT_COLUMNS:
        assert column in FRIENDLY_NAMES, column


def test_no_internal_name_or_banned_word_reaches_the_screen():
    for column in PROJECT_COLUMNS:
        shown = friendly(column)
        assert "_" not in shown, shown
        assert words.find_never(shown) == [], shown
        assert words.find_replace(shown) == [], shown


@pytest.mark.parametrize("name,shown", [
    ("code_name", "Theme"), ("coder", "Coder"), ("confidence", "Confidence"),
    ("class_year", "Class year"), ("first_generation", "First generation"),
    ("First_Generation", "First Generation"), ("Program", "Program"), ("GPA", "GPA"),
])
def test_friendly_names(name, shown):
    assert friendly(name) == shown


@pytest.mark.parametrize("name,technical", [
    ("application_id", True), ("rater_id", True), ("run_id", True), ("respondent_id", True),
    ("id", True), ("UUID", True), ("code_name", False), ("coder", False),
    ("weight", False), ("class_year", False), ("candidate", False), ("identity", False),
])
def test_which_fields_are_technical(name, technical):
    assert is_technical(name) is technical


def test_type_words_are_plain():
    assert [type_word(t) for t in ("nominal", "ordinal", "quantitative", "temporal")] == [
        "category", "ordered category", "number", "date"]
    assert type_word("something") == "something"


def test_suggested_chart_titles_use_the_label_function_when_given_one():
    types = {"code_name": "nominal", "coder": "nominal", "weight": "quantitative"}
    plain = [r.title for r in suggested_charts(types)]
    assert any("code_name" in t for t in plain)                     # unchanged by default
    named = [r.title for r in suggested_charts(types, label=friendly)]
    assert named and all("code_name" not in t and "_" not in t for t in named)
    assert any("How often each Theme occurs" == t for t in named)


def test_a_codes_origin_is_shown_in_plain_words():
    from core.ux.fields import origin_label

    assert origin_label("a_priori") == "Decided before coding"
    assert origin_label("emergent") == "Found while coding"
    assert origin_label("from_pack") == "From pack"            # unknown values are tidied, not hidden
    assert origin_label("") == ""


def test_the_web_codebook_table_uses_plain_headings_and_origins():
    from pathlib import Path

    from core import sample_project
    from tests import webkit

    root = Path(__file__).resolve().parents[1]
    from app.shared import constants

    out = constants.STREAMLIT_OUTPUT_DIR / "SAMPLE_cb" / "project.qnw"
    out.parent.mkdir(parents=True)
    sample_project.build_sample_project(root / "data" / "sample_survey_education.csv", out)
    at = webkit.start("")
    at.session_state["active_project_path"] = str(out)
    webkit.go(at, "Codebook")
    assert not at.exception, at.exception
    frame = at.dataframe[0].value
    assert list(frame.columns) == ["Code", "Definition", "Part of", "Where it came from", "Times used"]
    assert set(frame["Where it came from"]) <= {"Decided before coding", "Found while coding"}
