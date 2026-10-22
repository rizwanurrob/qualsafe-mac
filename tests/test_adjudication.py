"""Tests for adjudicated-coding writes (v3.9.6, F2 store side)."""

from __future__ import annotations

from core.adjudication import ADJUDICATED_RATER, record_adjudications
from core.model import CodeApplication, Rater, Source
from core.project import Project


def _seed_simple(path):
    from core.model import Code
    with Project.create(path) as proj:
        proj.add_rater(Rater(rater_id="human_alice", kind="human"))
        proj.add_rater(Rater(rater_id="human_bob", kind="human"))
        cost_id = proj.add_code(Code(code_id="", name="Cost", origin="a_priori"))
        eids = []
        for i in range(2):
            src = Source(source_id=f"s{i}", type="survey_response", raw_text=f"text {i}",
                         label="Q", metadata={"response_id": str(i), "question_text": "Q"})
            proj.add_source(src)
            eid = proj.add_whole_response_excerpt(src)
            eids.append(eid)
            # Alice codes both as Cost; Bob leaves them uncoded (disagreement).
            proj.apply_code(CodeApplication(application_id="", excerpt_id=eid,
                                            code_id=cost_id, coder="human",
                                            rater_id="human_alice"))
        return eids


def test_records_adjudicated_rater_without_touching_others(tmp_path):
    store = tmp_path / "project.qnw"
    eids = _seed_simple(store)

    result = record_adjudications(store, {eids[0]: ["Cost"], eids[1]: []})
    assert result["applications"] == 1  # only the first excerpt got a code

    with Project.open(store) as proj:
        adj = proj.rater_labels(ADJUDICATED_RATER)
        assert adj[eids[0]] == {"Cost"}
        # A "no code" adjudication writes no application, but it IS a decision:
        # since store format v8 it is recorded as reviewed, with an empty set.
        # (Before, the excerpt vanished -- review finding F1 -- and the
        # reconcile panel showed a "no code" resolution as still unresolved.)
        assert adj[eids[1]] == set()
        # Alice's original codings are untouched.
        assert proj.rater_labels("human_alice")[eids[0]] == {"Cost"}
        assert proj.rater_labels("human_alice")[eids[1]] == {"Cost"}


def test_reresolving_is_idempotent(tmp_path):
    store = tmp_path / "project.qnw"
    eids = _seed_simple(store)
    record_adjudications(store, {eids[0]: ["Cost"]})
    record_adjudications(store, {eids[0]: ["Cost"]})  # again
    with Project.open(store) as proj:
        # Not doubled: still exactly one Cost application for the adjudicated rater.
        ct = proj.coding_table()
        adj = ct[(ct["rater_id"] == ADJUDICATED_RATER)]
        assert len(adj) == 1


def test_new_reconciling_label_is_created(tmp_path):
    store = tmp_path / "project.qnw"
    eids = _seed_simple(store)
    result = record_adjudications(store, {eids[0]: ["Brand new theme"]})
    assert result["new_codes"] == 1
    with Project.open(store) as proj:
        assert proj.rater_labels(ADJUDICATED_RATER)[eids[0]] == {"Brand new theme"}


def test_unknown_excerpt_reported_not_written(tmp_path):
    store = tmp_path / "project.qnw"
    _seed_simple(store)
    result = record_adjudications(store, {"does_not_exist": ["Cost"]})
    assert result["unmatched"] == 1
    assert result["applications"] == 0
