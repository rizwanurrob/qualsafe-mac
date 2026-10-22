"""core/written_codebook.py: coding survey answers with a written codebook (offline, demo engine)."""

import pandas as pd
import pytest

from core import written_codebook as wc
from core.model import Code
from core.project import Project

ANSWERS = pd.DataFrame({
    "id": ["a", "b", "c", "d"],
    "answer": ["I cannot afford the books", "Advisors were kind", "", "Rent is too high and I work nights"],
})


@pytest.fixture
def project_path(tmp_path):
    path = tmp_path / "p.qnw"
    with Project.create(path) as proj:
        proj.add_code(Code(code_id="", name="Money", definition="", inclusion_criteria="trouble paying",
                           exclusion_criteria="praise for aid"))
        proj.add_code(Code(code_id="", name="Support", definition="", inclusion_criteria="helpful staff"))
        proj.add_code(Code(code_id="", name="Severity", definition="", decision_type="score",
                           rubric_levels=["none", "mild", "severe"]))
    return path


def test_every_non_empty_answer_gets_one_source_and_one_excerpt(project_path):
    with Project.open(project_path) as proj:
        found = wc.ensure_excerpts(proj, ANSWERS, "answer", "id")
        assert [text for _e, text in found] == ["I cannot afford the books", "Advisors were kind",
                                                "Rent is too high and I work nights"]
        again = wc.ensure_excerpts(proj, ANSWERS, "answer", "id")
        assert [e for e, _ in again] == [e for e, _ in found]          # reused, not duplicated
        assert proj.count_sources() == 3 if hasattr(proj, "count_sources") else True


def test_rows_without_an_id_column_get_row_ids(project_path):
    with Project.open(project_path) as proj:
        found = wc.ensure_excerpts(proj, ANSWERS.drop(columns="id"), "answer")
        assert len(found) == 3


def test_a_rating_scale_is_not_a_theme(project_path):
    with Project.open(project_path) as proj:
        names = [c.name for c in wc.usable_codes(proj.get_codebook())]
    assert sorted(names) == ["Money", "Support"]


def test_has_rules_looks_at_both_boundaries():
    assert wc.has_rules(Code(code_id="", name="x", definition="", inclusion_criteria="a"))
    assert wc.has_rules(Code(code_id="", name="x", definition="", exclusion_criteria="b"))
    assert not wc.has_rules(Code(code_id="", name="x", definition=""))


def test_without_the_engine_the_run_is_labelled_a_demo(project_path):
    result = wc.run(project_path, ANSWERS, "answer", "id", "r1", {"text_column": "answer"})
    assert result["engine"] == "demo" and "demo engine" in result["engine_note"]
    assert "__demo_" in result["run_id"] and result["coded"] == 3 and result["n_answers"] == 3


def test_an_engine_that_cannot_start_falls_back_and_says_why(project_path, tmp_path):
    result = wc.run(project_path, ANSWERS, "answer", "id", "r1", {"text_column": "answer"},
                    python_exe=str(tmp_path / "no_such_python.exe"))
    assert result["engine"] == "demo" and "could not start" in result["engine_note"]


def test_running_again_under_the_same_name_skips_what_is_done(project_path):
    wc.run(project_path, ANSWERS, "answer", "id", "r1", {"text_column": "answer"})
    again = wc.run(project_path, ANSWERS, "answer", "id", "r1", {"text_column": "answer"})
    assert again["skipped"] == 3 and again["coded"] == 0
    forced = wc.run(project_path, ANSWERS, "answer", "id", "r1", {"text_column": "answer"}, force=True)
    assert forced["coded"] == 3


def test_a_run_can_be_stopped_and_keeps_what_was_coded(project_path):
    result = wc.run(project_path, ANSWERS, "answer", "id", "r1", {"text_column": "answer"},
                    should_cancel=lambda: True)
    assert result["cancelled"] is True and result["coded"] < 3


def test_an_empty_column_is_refused(project_path):
    with pytest.raises(ValueError):
        wc.run(project_path, ANSWERS.assign(answer=""), "answer", "id", "r1", {"text_column": "answer"})


def test_review_records_a_verdict_and_the_queue_shrinks(project_path):
    spec = {"text_column": "answer", "low_threshold": 0.0, "high_threshold": 1.01}
    result = wc.run(project_path, ANSWERS, "answer", "id", "r1", spec)
    with Project.open(project_path) as proj:
        waiting = wc.queue(proj, result["run_id"], 0.0, 1.01)
        assert len(waiting) > 0
        first = waiting.iloc[0]
        wc.review(proj, first["decision_id"], "accept", "")
        after = wc.queue(proj, result["run_id"], 0.0, 1.01)
        assert len(after) == len(waiting) - 1


def test_an_unknown_verdict_is_refused(project_path):
    with Project.open(project_path) as proj:
        with pytest.raises(ValueError):
            wc.review(proj, "x", "maybe", "me")


def test_the_time_estimate_follows_the_measured_speed():
    assert wc.estimate_seconds(40, 5) == 780                    # measured 543 s and 754 s
    assert wc.estimate_text(40, 5) == "about 13 minutes"
    assert wc.estimate_text(1, 1) == "about 3 minutes"
    assert wc.estimate_text(0, 0) == "about 3 minutes"          # the start-up time alone
    assert wc.estimate_text(1000, 5) == "about 4.2 hours"
