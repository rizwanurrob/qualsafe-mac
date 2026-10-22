"""A run from the demo engine is labelled as one, everywhere (finding F2).

When Laya is not installed the Alt Survey Flow page runs `MockLayaEngine`,
whose scores are a hash of the text -- meaningless by design. Its codings were
stored under a rater whose model_id named the real Laya checkpoint, so nothing
downstream could tell them from real coding; and because demo and real runs
shared a run id, a real run started later under the same name *skipped* every
response the demo had already "coded".
"""

from __future__ import annotations

import pytest

from core.model import Code, Excerpt, Source
from core.project import Project
from engines.laya_engine import (CodingRunSpec, MockLayaEngine, demo_rater_ids, remove_demo_codings,
                                 run_coding_pass, run_id_for)

TEXTS = {"e1": "Books cost a lot.", "e2": "I miss home.", "e3": "Tuition went up again."}


def _project(tmp_path):
    path = tmp_path / "p.qnw"
    proj = Project.create(path)
    proj.add_code(Code(code_id="", name="Cost", definition="Money worries"))
    for i, (eid, text) in enumerate(TEXTS.items()):
        proj.add_source(Source(source_id=f"s{i}", type="survey_response", raw_text=text))
        proj.add_excerpt(Excerpt(excerpt_id=eid, source_id=f"s{i}", text=text,
                                 char_start=0, char_end=len(text)))
    return proj


def _run(proj, predict_fn, run_id):
    codes = proj.get_codebook()
    return run_coding_pass(proj, list(TEXTS.items()), codes, {}, predict_fn, run_id,
                           CodingRunSpec.from_dict({"low_threshold": 0.0, "high_threshold": 0.0001}))


def test_the_mock_says_it_is_a_mock():
    assert MockLayaEngine.is_mock is True


def test_a_demo_run_registers_a_demo_rater(tmp_path):
    proj = _project(tmp_path)
    _run(proj, MockLayaEngine().predict, run_id_for("run", "p", demo=True))
    raters = {r.rater_id: r for r in proj.list_raters()}
    demo = [r for rid, r in raters.items() if rid.startswith("laya")]
    assert len(demo) == 1
    rater = demo[0]
    assert rater.rater_id in demo_rater_ids(proj)
    assert rater.model_id == "mock:laya"
    assert "DEMO" in rater.name
    proj.close()


def test_demo_and_real_runs_never_share_an_id():
    assert run_id_for("run", "p", demo=True) != run_id_for("run", "p", demo=False)


def test_a_real_run_after_a_demo_run_codes_everything(tmp_path):
    proj = _project(tmp_path)
    _run(proj, MockLayaEngine().predict, run_id_for("run", "p", demo=True))

    calls = []

    def real_predict(state, questions):
        calls.append(state["text"])
        return {name: {"noul": 0.9, "confidence": 0.9} for name in questions}

    result = _run(proj, real_predict, run_id_for("run", "p", demo=False))
    assert result["skipped"] == 0
    assert sorted(calls) == sorted(TEXTS.values())
    proj.close()


def test_demo_codings_can_be_removed_without_touching_anything_else(tmp_path):
    proj = _project(tmp_path)
    _run(proj, MockLayaEngine().predict, run_id_for("run", "p", demo=True))

    def real_predict(state, questions):
        return {name: {"noul": 0.9, "confidence": 0.9} for name in questions}

    _run(proj, real_predict, run_id_for("run", "p", demo=False))
    before_real = len([a for a in proj.list_applications() if "demo" not in (a.rater_id or "")])

    report = remove_demo_codings(proj)
    assert report["applications"] >= 1
    assert not demo_rater_ids(proj)
    assert not proj.list_coding_decisions(run_id=run_id_for("run", "p", demo=True))
    assert len(proj.list_applications()) == before_real
    proj.close()


def test_the_methods_appendix_discloses_demo_codings(tmp_path):
    from exports.methods_appendix import methods_facts

    proj = _project(tmp_path)
    _run(proj, MockLayaEngine().predict, run_id_for("run", "p", demo=True))
    facts = methods_facts(proj)
    assert facts["demo_codings"] >= 1
    proj.close()
