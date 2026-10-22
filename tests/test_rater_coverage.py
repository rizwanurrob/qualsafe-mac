"""Schema v8: which responses each rater actually reviewed (review finding F1).

Before v8 the store recorded only the codes a rater *applied*, so "I read this
and no code applies" was indistinguishable from "I never saw it". Kappa over the
intersection of two raters' items then dropped exactly the responses where one
coder said yes and the other said nothing applies -- the disagreements -- and
reported kappa = 1.00 for data whose true kappa is 0.62.
"""

from __future__ import annotations

import sqlite3

import pandas as pd
import pytest

from analysis.agreement import per_code_kappa
from core.model import Code, CodeApplication, Excerpt, Rater, Source
from core.populate import populate_project_store, record_human_codings
from core.project import SCHEMA_VERSION, Project

QUESTION = "What has been hardest?"


def _store(tmp_path, n=10):
    path = tmp_path / "p.qnw"
    with Project.create(path) as proj:
        proj.add_code(Code(code_id="", name="Cost"))
        for i in range(1, n + 1):
            text = f"response {i}"
            proj.add_source(Source(source_id=f"s{i}", type="survey_response", raw_text=text,
                                   metadata={"response_id": str(i), "question_text": QUESTION}))
            proj.add_excerpt(Excerpt(excerpt_id=f"e{i}", source_id=f"s{i}", text=text,
                                     char_start=0, char_end=len(text)))
    return path


def _cost_id(proj):
    return next(c.code_id for c in proj.get_codebook() if c.name == "Cost")


# ── the headline ─────────────────────────────────────────────────────────────
def test_kappa_counts_the_responses_a_coder_left_uncoded(tmp_path):
    path = _store(tmp_path)
    ids = [str(i) for i in range(1, 11)]
    record_human_codings(path, {i: (["Cost"] if int(i) <= 6 else []) for i in ids},
                         question_text=QUESTION, rater_id="human_primary")
    record_human_codings(path, {i: (["Cost"] if int(i) <= 4 else []) for i in ids},
                         question_text=QUESTION, rater_id="human_B")
    with Project.open(path) as proj:
        a, b = proj.rater_labels("human_primary"), proj.rater_labels("human_B")
    row = per_code_kappa(a, b, min_support=1).iloc[0]
    assert row["n_items"] == 10
    assert row["kappa"] == pytest.approx(0.6154, abs=1e-3)


def test_resaving_a_sample_is_idempotent(tmp_path):
    path = _store(tmp_path, n=3)
    for _ in range(2):
        record_human_codings(path, {"1": ["Cost"], "2": [], "3": []},
                             question_text=QUESTION, rater_id="human_primary")
    with Project.open(path) as proj:
        assert proj.coverage_excerpt_ids("human_primary") == {"e1", "e2", "e3"}
        assert proj.rater_labels("human_primary") == {"e1": {"Cost"}, "e2": set(), "e3": set()}


# ── old projects: say so, never guess ────────────────────────────────────────
def test_a_rater_with_no_review_record_falls_back_and_says_so(tmp_path):
    path = _store(tmp_path, n=3)
    with Project.open(path) as proj:
        proj.add_rater(Rater(rater_id="human_old", kind="human"))
        proj.apply_code(CodeApplication(application_id="", excerpt_id="e1",
                                        code_id=_cost_id(proj), coder="human",
                                        rater_id="human_old"))
        item_set = proj.rater_item_set("human_old")
    assert item_set.labels == {"e1": {"Cost"}}
    assert item_set.recorded is False


def test_codes_that_predate_the_record_are_counted_not_mixed_in(tmp_path):
    """A rater coded e1 before v8 and e2-e3 after. Treating e1 as a complete
    review would re-create F1 for it; silently dropping it would hide work. It
    is left out of the item set and counted, so the caveat can say how many."""
    path = _store(tmp_path, n=3)
    with Project.open(path) as proj:
        proj.add_rater(Rater(rater_id="human_primary", kind="human"))
        proj.apply_code(CodeApplication(application_id="", excerpt_id="e1",
                                        code_id=_cost_id(proj), coder="human",
                                        rater_id="human_primary"))
    record_human_codings(path, {"2": ["Cost"], "3": []}, question_text=QUESTION,
                         rater_id="human_primary")
    with Project.open(path) as proj:
        item_set = proj.rater_item_set("human_primary")
    assert item_set.recorded is True
    assert set(item_set.labels) == {"e2", "e3"}
    assert item_set.uncovered_applied == 1


# ── machine raters: every response the engine scored is reviewed ────────────
def _config():
    return {"input": {}, "output": {},
            "models": {"zero_shot_model": "facebook/bart-large-mnli"},
            "zero_shot": {"labels": ["Belonging", "Cost"],
                          "strict_coding": {"enabled": True, "uncertain_label": "UNCERTAIN_REVIEW"}}}


def _scored():
    return pd.DataFrame({
        "response_id": ["r1", "r2", "r3"], "question_text": ["Q1"] * 3,
        "response_text": ["I belong", "tuition is a lot", "n/a"],
        "zshot_top_label": ["Belonging", "Cost", "Belonging"],
        "zshot_top_score": [0.8, 0.8, 0.4],
        "zshot_strict_label": ["Belonging", "Cost", "UNCERTAIN_REVIEW"],
        "zshot_strict_confident": [True, True, False],
        "zshot_strict_margin": [0.5, 0.5, 0.05]})


def test_an_uncertain_response_counts_as_the_engine_applying_no_code(tmp_path):
    store = populate_project_store(_scored(), _config(), tmp_path / "p.qnw")
    with Project.open(store) as proj:
        engine = next(r.rater_id for r in proj.list_raters() if r.kind == "transformer")
        labels = proj.rater_labels(engine)
    assert len(labels) == 3
    assert sorted(len(v) for v in labels.values()) == [0, 1, 1]


# ── every path that moves a project carries the record ──────────────────────
def test_adjudication_records_what_it_resolved(tmp_path):
    from core.adjudication import ADJUDICATED_RATER, record_adjudications

    path = _store(tmp_path, n=2)
    record_adjudications(path, {"e1": ["Cost"], "e2": []})
    with Project.open(path) as proj:
        assert proj.rater_labels(ADJUDICATED_RATER) == {"e1": {"Cost"}, "e2": set()}


def test_json_export_import_keeps_the_record(tmp_path):
    path = _store(tmp_path, n=2)
    record_human_codings(path, {"1": [], "2": ["Cost"]}, question_text=QUESTION)
    with Project.open(path) as proj:
        proj.export_json(tmp_path / "p.json")
    with Project.import_json(tmp_path / "p.json", tmp_path / "copy.qnw") as copy:
        assert copy.rater_labels("human_primary") == {"e1": set(), "e2": {"Cost"}}


def test_merging_another_project_carries_its_uncoded_reviews(tmp_path):
    from core.store_merge import merge_project_stores

    (tmp_path / "t").mkdir()
    (tmp_path / "i").mkdir()
    target, incoming = _store(tmp_path / "t", n=3), _store(tmp_path / "i", n=3)
    record_human_codings(incoming, {"1": ["Cost"], "2": [], "3": []},
                         question_text=QUESTION, rater_id="human_colleague")
    merge_project_stores(target, incoming)
    with Project.open(target) as proj:
        assert proj.rater_labels("human_colleague") == {"e1": {"Cost"}, "e2": set(), "e3": set()}


def test_erasing_a_respondent_removes_their_review_record(tmp_path):
    path = _store(tmp_path, n=2)
    record_human_codings(path, {"1": [], "2": []}, question_text=QUESTION)
    with Project.open(path) as proj:
        proj.delete_source("s1")
        assert proj.coverage_excerpt_ids("human_primary") == {"e2"}


# ── the migration ────────────────────────────────────────────────────────────
def test_a_v7_store_migrates_to_v8_and_keeps_its_codes(tmp_path):
    path = _store(tmp_path, n=2)
    with Project.open(path) as proj:
        proj.add_rater(Rater(rater_id="human_primary", kind="human"))
        proj.apply_code(CodeApplication(application_id="a1", excerpt_id="e1",
                                        code_id=_cost_id(proj), coder="human",
                                        rater_id="human_primary"))
    con = sqlite3.connect(path)
    con.execute("DROP TABLE rater_coverage")
    con.execute("UPDATE meta SET value='7' WHERE key='schema_version'")
    con.commit()
    con.close()

    with Project.open(path) as proj:
        assert proj.rater_item_set("human_primary").recorded is False
        assert proj.rater_labels("human_primary") == {"e1": {"Cost"}}
    con = sqlite3.connect(path)
    version = int(con.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0])
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    con.close()
    assert version == SCHEMA_VERSION >= 8
    assert "rater_coverage" in tables
