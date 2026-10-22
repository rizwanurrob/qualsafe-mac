"""The person against the engine, code by code (analysis/calibration.py), with the demo engine."""

import math

import pandas as pd
import pytest

from analysis import calibration as cal
from analysis.agreement import DEFAULT_MIN_SUPPORT
from core import hand_coding as hc
from core import written_codebook as wc
from core.agreement_pairs import engine_raters, human_raters, selectable_raters
from core.model import Code
from core.project import Project
from core.span_coding import HUMAN_RATER

N = 24
FRAME = pd.DataFrame({"id": [f"r{n}" for n in range(N)],
                      "answer": [f"answer number {n} about things" for n in range(N)]})


@pytest.fixture
def run(tmp_path):
    path = tmp_path / "p.qnw"
    with Project.create(path) as proj:
        proj.add_code(Code(code_id="", name="Money", inclusion_criteria="trouble paying"))
        proj.add_code(Code(code_id="", name="Belonging", inclusion_criteria="fitting in"))
    result = wc.run(path, FRAME, "answer", "id", "r1",
                    {"text_column": "answer", "low_threshold": 0.35, "high_threshold": 0.65})
    return path, result["run_id"]


def code_the_sample(proj, run_id, size=N, seed=1):
    ids = cal.draw_sample(cal.run_excerpt_ids(proj, run_id), size, seed=seed)
    cal.save_sample(proj, run_id, ids, seed=seed)
    sources = hc.source_ids_for_excerpts(proj, ids)
    answers, _ = hc.page(proj, only_ids=sources, limit=1000)
    for i, answer in enumerate(answers):                       # a stand-in person: ticks by position
        hc.save(proj, answer.source_id, ["Money"] if i % 3 == 0 else (["Belonging"] if i % 3 == 1 else []))
    return ids


def test_runs_with_decisions_are_listed_real_before_demo(run):
    path, run_id = run
    with Project.open(path) as proj:
        assert cal.decision_run_ids(proj) == [run_id]
        assert "__demo_" in run_id


def test_the_sample_is_drawn_from_the_answers_the_run_scored(run):
    path, run_id = run
    with Project.open(path) as proj:
        assert len(cal.run_excerpt_ids(proj, run_id)) == N


def test_sample_status_counts_what_the_person_has_judged(run):
    path, run_id = run
    with Project.open(path) as proj:
        ids = cal.draw_sample(cal.run_excerpt_ids(proj, run_id), 10, seed=1)
        cal.save_sample(proj, run_id, ids, seed=1)
        assert cal.sample_status(proj, run_id) == (10, 0)
        sources = sorted(hc.source_ids_for_excerpts(proj, ids))
        hc.save(proj, sources[0], [])
        hc.save(proj, sources[1], ["Money"])
        assert cal.sample_status(proj, run_id) == (10, 2)


def test_only_the_sampled_answers_are_offered_for_hand_coding(run):
    path, run_id = run
    with Project.open(path) as proj:
        ids = cal.draw_sample(cal.run_excerpt_ids(proj, run_id), 6, seed=2)
        sources = hc.source_ids_for_excerpts(proj, ids)
        answers, total = hc.page(proj, only_ids=sources, limit=100)
        assert total == 6 and {a.source_id for a in answers} == sources
        assert hc.progress(proj, only_ids=sources) == (0, 6)
        assert hc.next_unjudged(proj, only_ids=sources) in sources


def test_the_table_has_kappa_percent_agreement_prevalence_and_the_support_flag(run):
    path, run_id = run
    with Project.open(path) as proj:
        code_the_sample(proj, run_id)
        table = cal.agreement_by_code(cal.calibration_pairs(proj, run_id))
    assert list(table["code"]) == ["Belonging", "Money"]
    for column in ("kappa", "percent_agreement", "prevalence_human", "prevalence_model", "n_items",
                   "reliable", "precision", "recall", "f1"):
        assert column in table.columns
    assert (table["n_items"] == N).all() and table["reliable"].all()
    assert table["kappa"].between(-1, 1).all() and table["percent_agreement"].between(0, 1).all()


def test_a_small_sample_is_flagged_as_not_enough_not_given_a_kappa(run):
    path, run_id = run
    with Project.open(path) as proj:
        code_the_sample(proj, run_id, size=DEFAULT_MIN_SUPPORT - 1)
        table = cal.agreement_by_code(cal.calibration_pairs(proj, run_id))
    assert not table["reliable"].any()
    assert table["kappa"].isna().all() or all(math.isnan(k) for k in table["kappa"])


def test_no_pairs_gives_an_empty_table(run):
    assert cal.agreement_by_code(pd.DataFrame(columns=["excerpt_id", "code_name", "score",
                                                       "model_assigned", "human"])).empty


def test_the_engine_is_never_listed_among_the_coders(run):
    path, run_id = run
    with Project.open(path) as proj:
        code_the_sample(proj, run_id)
        humans = human_raters(proj)
        assert HUMAN_RATER in humans
        engine_ids = {r.rater_id for r in proj.list_raters() if r.rater_id != HUMAN_RATER}
        assert engine_ids                                     # the run's own (demo) coder exists…
        assert not engine_ids & set(humans)                   # …but is not a human coder
        assert not engine_ids & set(selectable_raters(proj))  # and cannot be picked as one
        assert not engine_ids & set(engine_raters(proj))      # a written-codebook run is not a pipeline engine run
