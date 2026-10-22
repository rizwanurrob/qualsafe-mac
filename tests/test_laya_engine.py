"""Structured-coding logic (engines/laya_engine.py) -- fully offline via
MockLayaEngine, no subprocess, no real Laya install anywhere in this suite."""

from __future__ import annotations

from core.model import Code, Source
from core.project import Project
from engines.laya_engine import (
    CodingRunSpec,
    MockLayaEngine,
    build_questions_for_codes,
    code_excerpt,
    code_excerpt_hierarchical,
    draft_coding_decisions,
    route_by_confidence,
    run_coding_pass,
)


# ── route_by_confidence ───────────────────────────────────────────────────────

def test_route_by_confidence_bands():
    assert route_by_confidence(0.1, low=0.35, high=0.65) == "confident_no"
    assert route_by_confidence(0.5, low=0.35, high=0.65) == "ambiguous"
    assert route_by_confidence(0.9, low=0.35, high=0.65) == "confident_yes"


def test_route_by_confidence_boundaries_are_half_open():
    assert route_by_confidence(0.35, low=0.35, high=0.65) == "ambiguous"     # low is IN the band
    assert route_by_confidence(0.65, low=0.35, high=0.65) == "confident_yes"  # high is OUT


def test_route_by_confidence_treats_no_model_opinion_as_ambiguous():
    assert route_by_confidence(None, low=0.35, high=0.65) == "ambiguous"


# ── build_questions_for_codes ─────────────────────────────────────────────────

def test_multi_label_mode_asks_one_noul_per_code():
    codes = [Code(code_id="c1", name="A"), Code(code_id="c2", name="B")]
    questions = build_questions_for_codes(codes, "multi_label_noul")
    assert questions["c1"]["type"] == "noul"
    assert questions["c2"]["type"] == "noul"
    assert "__choice__" not in questions


def test_single_label_mode_asks_one_combined_choice():
    codes = [Code(code_id="c1", name="A"), Code(code_id="c2", name="B")]
    questions = build_questions_for_codes(codes, "single_label_choice")
    assert "c1" not in questions and "c2" not in questions
    assert questions["__choice__"]["type"] == "choice"
    assert set(questions["__choice__"]["criteria"]) == {"c1", "c2"}


def test_score_type_code_is_always_its_own_score_question_regardless_of_mode():
    rubric_code = Code(code_id="c3", name="Severity", decision_type="score",
                       rubric_levels=["low", "medium", "high"])
    plain_code = Code(code_id="c1", name="A")
    for mode in ("multi_label_noul", "single_label_choice"):
        questions = build_questions_for_codes([plain_code, rubric_code], mode)
        assert questions["c3"]["type"] == "score"
        assert questions["c3"]["criteria"] == ["low", "medium", "high"]


# ── code_excerpt with the mock ────────────────────────────────────────────────

def test_code_excerpt_returns_a_score_per_code():
    codes = [Code(code_id="c1", name="Financial stress"), Code(code_id="c2", name="Housing")]
    results = code_excerpt("I could not afford rent this semester.", codes,
                           MockLayaEngine().predict, "multi_label_noul")
    assert set(results) == {"c1", "c2"}
    for r in results.values():
        assert 0.0 <= r["score"] <= 1.0


def test_mock_engine_is_deterministic_across_calls():
    codes = [Code(code_id="c1", name="Financial stress")]
    text = "I could not afford rent this semester."
    first = code_excerpt(text, codes, MockLayaEngine().predict, "multi_label_noul")
    second = code_excerpt(text, codes, MockLayaEngine().predict, "multi_label_noul")
    assert first["c1"]["score"] == second["c1"]["score"]


def test_mock_engine_scores_differ_for_different_text():
    codes = [Code(code_id="c1", name="Financial stress")]
    a = code_excerpt("I could not afford rent.", codes, MockLayaEngine().predict, "multi_label_noul")
    b = code_excerpt("The campus is beautiful in autumn.", codes, MockLayaEngine().predict, "multi_label_noul")
    assert a["c1"]["score"] != b["c1"]["score"]


def test_single_label_choice_picks_exactly_one_winner():
    codes = [Code(code_id="c1", name="Financial"), Code(code_id="c2", name="Academic"),
             Code(code_id="c3", name="Social")]
    results = code_excerpt("I could not afford tuition this term.", codes,
                           MockLayaEngine().predict, "single_label_choice")
    assigned = [cid for cid, r in results.items() if r["assigned"]]
    assert len(assigned) == 1


def test_score_type_result_is_not_marked_assigned_true_or_false():
    codes = [Code(code_id="c1", name="Severity", decision_type="score",
                  rubric_levels=["low", "medium", "high"])]
    results = code_excerpt("It was somewhat difficult.", codes, MockLayaEngine().predict,
                           "multi_label_noul")
    assert results["c1"]["assigned"] is None   # a rating, not a yes/no


def test_code_excerpt_with_no_codes_returns_nothing():
    assert code_excerpt("some text", [], MockLayaEngine().predict, "multi_label_noul") == {}


# ── hierarchical coarse-to-fine ───────────────────────────────────────────────

def test_hierarchical_walk_descends_only_past_the_top_level():
    parent = Code(code_id="p1", name="Financial")
    child_a = Code(code_id="c1a", name="Tuition", parent_id="p1")
    child_b = Code(code_id="c1b", name="Housing", parent_id="p1")
    other_parent = Code(code_id="p2", name="Unrelated topic entirely")
    other_child = Code(code_id="c2a", name="Some other unrelated child", parent_id="p2")

    children_by_parent = {"p1": [child_a, child_b], "p2": [other_child]}
    results = code_excerpt_hierarchical(
        "text", [parent, other_parent], children_by_parent, MockLayaEngine().predict,
        "multi_label_noul", low=0.0, high=2.0,   # high=2.0: nothing is ever confident_yes,
    )                                             # but nothing is confident_no either (low=0.0)
    # low=0.0 means route_by_confidence never returns confident_no (score>=0 always),
    # so every parent's children should have been visited too.
    assert {"p1", "p2", "c1a", "c1b", "c2a"} <= set(results)


def test_hierarchical_walk_prunes_confident_no_parents():
    parent = Code(code_id="p1", name="Financial")
    child = Code(code_id="c1a", name="Tuition", parent_id="p1")
    children_by_parent = {"p1": [child]}
    # low=high=1.0 forces every mock score (which is < 1.0) to be confident_no.
    results = code_excerpt_hierarchical(
        "text", [parent], children_by_parent, MockLayaEngine().predict,
        "multi_label_noul", low=1.0, high=1.0,
    )
    assert "p1" in results
    assert "c1a" not in results   # pruned: parent was confident_no


# ── draft_coding_decisions (segmentation + de-dup) ────────────────────────────

def test_draft_coding_decisions_short_text_produces_one_decision_per_code():
    codes = [Code(code_id="c1", name="Financial stress")]
    spec = CodingRunSpec(text_column="response_text")
    decisions = draft_coding_decisions(
        "exc1", "I could not afford rent this semester.", codes, {},
        MockLayaEngine().predict, "run1", spec,
    )
    assert len(decisions) == 1
    assert decisions[0].excerpt_id == "exc1"
    assert decisions[0].code_id == "c1"
    assert decisions[0].run_id == "run1"
    assert decisions[0].review_status == "unreviewed"
    assert decisions[0].human_assigned is None


def test_draft_coding_decisions_assigned_matches_the_threshold_band():
    codes = [Code(code_id="c1", name="Financial stress")]
    spec = CodingRunSpec(text_column="response_text", low_threshold=0.0, high_threshold=0.0)
    decisions = draft_coding_decisions(
        "exc1", "anything", codes, {}, MockLayaEngine().predict, "run1", spec,
    )
    # high=0.0 means route_by_confidence(any score >= 0) => confident_yes always.
    assert decisions[0].model_assigned is True


def test_draft_coding_decisions_deduplicates_across_segments_by_max_score():
    """A long text gets segmented; the same code appearing in two segments must
    produce ONE decision, keeping the stronger of the two scores."""
    codes = [Code(code_id="c1", name="Financial stress")]
    long_text = (
        "Financial stress was overwhelming this semester. " * 2
        + "I almost dropped out because I could not afford rent. "
        + "Unrelated filler about campus dining options follows here for length. " * 10
    )
    spec = CodingRunSpec(text_column="response_text", segmentation_token_budget=15)
    decisions = draft_coding_decisions(
        "exc1", long_text, codes, {}, MockLayaEngine().predict, "run1", spec,
    )
    ids = [d.code_id for d in decisions]
    assert ids.count("c1") == 1   # not one row per segment


# ── run_coding_pass (end to end, against a real Project) ──────────────────────

def _project_with_excerpts(tmp_path, texts):
    proj = Project.create(tmp_path / "p.qnw")
    excerpts = []
    for i, text in enumerate(texts):
        src = Source(source_id="", type="survey_response", raw_text=text, label=f"s{i}")
        sid = proj.add_source(src)
        src.source_id = sid   # add_source mints the id; add_whole_response_excerpt reads it back
        eid = proj.add_whole_response_excerpt(src)
        excerpts.append((eid, text))
    return proj, excerpts


def test_run_coding_pass_codes_every_excerpt_and_reports_counts(tmp_path):
    proj, excerpts = _project_with_excerpts(tmp_path, [
        "I could not afford rent this semester.",
        "Advising was hard to reach when I needed help.",
    ])
    codes = [proj.add_code(Code(code_id="", name="Financial stress"))]
    root_codes = proj.get_codebook()
    spec = CodingRunSpec(text_column="response_text")

    result = run_coding_pass(proj, excerpts, root_codes, {}, MockLayaEngine().predict,
                             "run1", spec)
    assert result["coded"] == 2
    assert result["skipped"] == 0
    assert result["cancelled"] is False
    assert result["total"] == 2
    assert len(proj.list_coding_decisions(run_id="run1")) == 2   # one per excerpt/code pair
    proj.close()


def test_run_coding_pass_registers_a_machine_rater(tmp_path):
    proj, excerpts = _project_with_excerpts(tmp_path, ["some response text here"])
    proj.add_code(Code(code_id="", name="A"))
    root_codes = proj.get_codebook()
    spec = CodingRunSpec(text_column="response_text")

    def real_predict(state, questions):   # stands in for LayaClient.predict
        return {name: {"noul": 0.5, "confidence": 0.5} for name in questions}

    run_coding_pass(proj, excerpts, root_codes, {}, real_predict, "run1", spec)
    raters = {r.rater_id: r for r in proj.list_raters()}
    assert raters["laya_run1"].kind == "structured"
    assert raters["laya_run1"].model_id == spec.model

    # The mock must never register under the real checkpoint's name (review F2).
    run_coding_pass(proj, excerpts, root_codes, {}, MockLayaEngine().predict, "run2", spec)
    demo = {r.rater_id: r for r in proj.list_raters()}["laya_demo_run2"]
    assert demo.model_id == "mock:laya" and "DEMO" in demo.name
    proj.close()


def test_run_coding_pass_creates_applications_only_for_confident_yes(tmp_path):
    proj, excerpts = _project_with_excerpts(tmp_path, ["anything at all"])
    proj.add_code(Code(code_id="", name="A"))
    root_codes = proj.get_codebook()
    # high=0.0 forces every score to confident_yes.
    spec = CodingRunSpec(text_column="response_text", low_threshold=0.0, high_threshold=0.0)

    result = run_coding_pass(proj, excerpts, root_codes, {}, MockLayaEngine().predict,
                             "run1", spec)
    assert result["assigned"] == 1
    assert len(proj.list_applications()) == 1
    proj.close()


def test_run_coding_pass_is_resumable_and_skips_already_coded_excerpts(tmp_path):
    proj, excerpts = _project_with_excerpts(tmp_path, ["a response", "another response"])
    proj.add_code(Code(code_id="", name="A"))
    root_codes = proj.get_codebook()
    spec = CodingRunSpec(text_column="response_text")

    run_coding_pass(proj, excerpts, root_codes, {}, MockLayaEngine().predict, "run1", spec)
    second = run_coding_pass(proj, excerpts, root_codes, {}, MockLayaEngine().predict,
                             "run1", spec)
    assert second["coded"] == 0
    assert second["skipped"] == 2
    proj.close()


def test_run_coding_pass_stops_at_cancellation_and_keeps_prior_work(tmp_path):
    proj, excerpts = _project_with_excerpts(
        tmp_path, ["first response", "second response", "third response"])
    proj.add_code(Code(code_id="", name="A"))
    root_codes = proj.get_codebook()
    spec = CodingRunSpec(text_column="response_text")

    seen = {"n": 0}

    def cancel_after_one():
        return seen["n"] >= 1

    def counting_predict(state, questions):
        seen["n"] += 1
        return MockLayaEngine().predict(state, questions)

    result = run_coding_pass(proj, excerpts, root_codes, {}, counting_predict, "run1", spec,
                             should_cancel=cancel_after_one)
    assert result["cancelled"] is True
    assert result["coded"] == 1                          # the one excerpt coded before cancelling
    assert len(proj.list_coding_decisions(run_id="run1")) == 1   # and it was actually saved
    proj.close()


def test_run_coding_pass_reports_progress(tmp_path):
    proj, excerpts = _project_with_excerpts(tmp_path, ["one", "two", "three"])
    proj.add_code(Code(code_id="", name="A"))
    root_codes = proj.get_codebook()
    spec = CodingRunSpec(text_column="response_text")

    calls = []
    run_coding_pass(proj, excerpts, root_codes, {}, MockLayaEngine().predict, "run1", spec,
                    progress_callback=lambda frac, msg: calls.append((frac, msg)))
    assert calls[-1][0] == 1.0
    proj.close()


def test_run_coding_pass_forced_redo_does_not_duplicate_applications(tmp_path):
    proj, excerpts = _project_with_excerpts(tmp_path, ["anything"])
    proj.add_code(Code(code_id="", name="A"))
    root_codes = proj.get_codebook()
    spec = CodingRunSpec(text_column="response_text", low_threshold=0.0, high_threshold=0.0)

    run_coding_pass(proj, excerpts, root_codes, {}, MockLayaEngine().predict, "run1", spec,
                    skip_existing=False)
    run_coding_pass(proj, excerpts, root_codes, {}, MockLayaEngine().predict, "run1", spec,
                    skip_existing=False)
    assert len(proj.list_applications()) == 1   # not two
    proj.close()
