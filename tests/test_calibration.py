"""Calibrating a structured-coding run against a human-coded sample (U4).

Scores are constructed so the right answer is known: for "Cost", every item at
or above 0.60 is a real instance and nothing below 0.45 is (0.45 itself is real,
0.55 is not), so the band that reaches 100% precision and 100% negative
predictive value is exactly [0.45, 0.60). Seven real instances in all.
"""

from __future__ import annotations

import pandas as pd
import pytest

from analysis.calibration import (BAND_STEP, CAVEATS, draw_sample, highest_threshold_for_npv,
                                  lowest_threshold_for_precision, per_code_calibration,
                                  recommend_band, reliability_table, score_pairs)


def _decisions():
    rows = []
    scores = [0.10, 0.20, 0.30, 0.35, 0.45, 0.55, 0.60, 0.70, 0.80, 0.85, 0.90, 0.95]
    truth = [False, False, False, False, True, False, True, True, True, True, True, True]
    for i, (s, t) in enumerate(zip(scores, truth)):
        rows.append({"decision_id": f"d{i}", "excerpt_id": f"e{i}", "code_name": "Cost",
                     "model_score": s, "model_assigned": s >= 0.65})
    human = {f"e{i}": ({"Cost"} if t else set()) for i, t in enumerate(truth)}
    return pd.DataFrame(rows), human


def test_the_sample_is_random_seeded_and_bounded():
    ids = [f"e{i}" for i in range(100)]
    a, b = draw_sample(ids, 20, seed=7), draw_sample(ids, 20, seed=7)
    assert a == b and len(a) == 20 and len(set(a)) == 20
    assert draw_sample(ids[:5], 20) == sorted(ids[:5])
    assert draw_sample(ids, 20, seed=8) != a


def test_only_human_coded_excerpts_are_paired():
    decisions, human = _decisions()
    del human["e0"]
    pairs = score_pairs(decisions, human)
    assert len(pairs) == 11 and "e0" not in set(pairs["excerpt_id"])


def test_threshold_for_precision_is_the_lowest_that_reaches_it():
    decisions, human = _decisions()
    pairs = score_pairs(decisions, human)
    t, precision, recall = lowest_threshold_for_precision(
        pairs["score"], pairs["human"], 1.0, min_count=3)
    assert t == 0.60 and precision == 1.0 and recall == pytest.approx(6 / 7)
    t90, p90, _ = lowest_threshold_for_precision(pairs["score"], pairs["human"], 0.85, min_count=3)
    assert t90 == 0.45 and p90 == pytest.approx(7 / 8)


def test_threshold_for_negative_predictive_value():
    decisions, human = _decisions()
    pairs = score_pairs(decisions, human)
    t, npv = highest_threshold_for_npv(pairs["score"], pairs["human"], 1.0, min_count=3)
    assert t == 0.45 and npv == 1.0


def test_an_unreachable_target_says_so_rather_than_guessing():
    t, p, r = lowest_threshold_for_precision([0.9, 0.8, 0.7], [False, False, True], 0.95,
                                             min_count=1)
    assert t is None


def test_the_recommended_band_is_snapped_in_the_safe_direction():
    decisions, human = _decisions()
    band = recommend_band(score_pairs(decisions, human), target=1.0, min_count=3)
    assert band["high"] == 0.60 and band["low"] == 0.45
    assert band["note"] == ""


def test_off_grid_thresholds_snap_high_up_and_low_down():
    """Raw thresholds 0.66 (high) and 0.47 (low): rounding high down to 0.65
    would auto-assign below the measured threshold; rounding low up to 0.50
    would treat measured-unsafe scores as confident no."""
    scores = [0.10, 0.20, 0.30, 0.47, 0.50, 0.55, 0.66, 0.75, 0.85, 0.95]
    truth = [False, False, False, True, False, False, True, True, True, True]
    pairs = pd.DataFrame({"excerpt_id": [f"e{i}" for i in range(10)], "code_name": "Cost",
                          "score": scores, "model_assigned": False, "human": truth})
    band = recommend_band(pairs, target=1.0, min_count=3)
    assert band["high"] == 0.70 and band["low"] == 0.45


def test_per_code_figures_join_validation_and_the_threshold():
    decisions, human = _decisions()
    table = per_code_calibration(score_pairs(decisions, human), target=1.0, min_support=3)
    row = table.set_index("code").loc["Cost"]
    # current band assigns >= 0.65: 5 assigned, all right; 7 real instances
    assert row["n_model"] == 5 and row["precision"] == 1.0
    assert row["recall"] == pytest.approx(5 / 7, abs=1e-4)
    assert row["recommended_high"] == 0.60


def test_reliability_table_and_caveats():
    decisions, human = _decisions()
    table = reliability_table(score_pairs(decisions, human), n_bins=5)
    assert table["n"].sum() == 12
    assert any("not probabilities" in c for c in CAVEATS)
    assert any("parent" in c for c in CAVEATS)


def test_the_decision_export_leaves_response_text_out_unless_asked():
    from analysis.calibration import decisions_export
    decisions, _ = _decisions()
    decisions = decisions.assign(excerpt_text="a response", source_id="s", review_status="unreviewed",
                                 human_assigned=None, reviewer="", reviewed_at="", note="")
    assert "excerpt_text" not in decisions_export(decisions).columns
    assert decisions_export(decisions, include_text=True)["excerpt_text"].iloc[0] == "a response"


def test_a_sample_is_stored_with_the_project_and_only_judged_responses_count(tmp_path):
    from analysis.calibration import calibration_pairs, load_sample, save_sample
    from core.model import Code, CodeApplication, Excerpt, Source
    from core.project import Project
    from engines.laya_engine import CodingRunSpec, run_coding_pass

    with Project.create(tmp_path / "p.qnw") as proj:
        cost = proj.add_code(Code(code_id="", name="Cost"))
        texts = {f"e{i}": f"response {i}" for i in range(6)}
        for i, (eid, text) in enumerate(texts.items()):
            proj.add_source(Source(source_id=f"s{i}", type="survey_response", raw_text=text))
            proj.add_excerpt(Excerpt(excerpt_id=eid, source_id=f"s{i}", text=text,
                                     char_start=0, char_end=len(text)))

        def predict(state, questions):
            return {n: {"noul": 0.8, "confidence": 0.8} for n in questions}

        run_coding_pass(proj, list(texts.items()), proj.get_codebook(), {}, predict, "r1",
                        CodingRunSpec.from_dict({}))
        save_sample(proj, "r1", ["e0", "e1", "e2"])
        assert load_sample(proj, "r1") == ["e0", "e1", "e2"]
        assert calibration_pairs(proj, "r1").empty, "nothing judged yet"
        proj.replace_applications_for_rater(
            "human_primary", ["e0", "e1"],
            [CodeApplication(application_id="", excerpt_id="e0", code_id=cost, coder="human",
                             rater_id="human_primary")])
        pairs = calibration_pairs(proj, "r1")
    assert sorted(pairs["excerpt_id"]) == ["e0", "e1"]
    assert pairs.set_index("excerpt_id")["human"].to_dict() == {"e0": True, "e1": False}


def test_the_methods_appendix_reports_a_calibration_and_flags_a_demo_one(tmp_path):
    from docx import Document

    from analysis.calibration import save_sample
    from core.model import Code, CodeApplication, Excerpt, Source
    from core.project import Project
    from engines.laya_engine import CodingRunSpec, MockLayaEngine, run_coding_pass, run_id_for
    from exports.methods_appendix import build_methods_appendix

    path = tmp_path / "p.qnw"
    with Project.create(path) as proj:
        cost = proj.add_code(Code(code_id="", name="Cost"))
        items = [(f"e{i}", f"response {i}") for i in range(8)]
        for i, (eid, text) in enumerate(items):
            proj.add_source(Source(source_id=f"s{i}", type="survey_response", raw_text=text))
            proj.add_excerpt(Excerpt(excerpt_id=eid, source_id=f"s{i}", text=text,
                                     char_start=0, char_end=len(text)))
        run_id = run_id_for("r", "p", demo=True)
        run_coding_pass(proj, items, proj.get_codebook(), {}, MockLayaEngine().predict, run_id,
                        CodingRunSpec.from_dict({}))
        save_sample(proj, run_id, [e for e, _ in items])
        proj.replace_applications_for_rater(
            "human_primary", [e for e, _ in items],
            [CodeApplication(application_id="", excerpt_id=f"e{i}", code_id=cost, coder="human",
                             rater_id="human_primary") for i in range(4)])
    out = build_methods_appendix(str(path), tmp_path / "appendix.docx")
    text = "\n".join(p.text for p in Document(out).paragraphs)
    assert "Structured coding: calibration against a human sample" in text
    assert "DEMO engine" in text
    assert "8 response(s)" in text
