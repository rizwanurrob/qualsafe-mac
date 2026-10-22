"""
Tests for populating a .qnw project store from a survey run frame (Phase 0b wiring).

Offline, no models — builds a synthetic response DataFrame with the columns the
pipeline produces and asserts the resulting store contents.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.populate import populate_project_store
from core.project import Project


def _config():
    return {
        "input": {"descriptor_columns": ["program", "first_gen"]},
        "output": {},
        "models": {"zero_shot_model": "facebook/bart-large-mnli"},
        "zero_shot": {
            "labels": ["Belonging", "Financial concern", "Academic success"],
            "strict_coding": {"enabled": True, "uncertain_label": "UNCERTAIN_REVIEW"},
        },
    }


def _work_df():
    return pd.DataFrame({
        "response_id": ["r1", "r2", "r3"],
        "response_text": ["I feel like I belong here", "worried about paying tuition", "n/a"],
        "question_text": ["Q1", "Q1", "Q1"],
        "program": ["Nursing", "Finance", "Undeclared"],
        "first_gen": ["Yes", "No", "Yes"],
        "cluster_id": [0, 1, 0],
        "sentiment_label": ["POSITIVE", "NEGATIVE", "NEUTRAL"],
        "sentiment_score": [0.91, 0.88, 0.5],
        "zshot_top_label": ["Belonging", "Financial concern", "Belonging"],
        "zshot_top_score": [0.82, 0.77, 0.40],
        "zshot_strict_label": ["Belonging", "Financial concern", "UNCERTAIN_REVIEW"],
        "zshot_strict_confident": [True, True, False],
        "zshot_strict_margin": [0.5, 0.4, 0.05],
    })


class TestPopulate:
    def test_sources_excerpts_and_descriptors(self, tmp_path):
        store = populate_project_store(_work_df(), _config(), tmp_path / "p.qnw")
        with Project.open(store) as p:
            sources = p.list_sources()
            assert len(sources) == 3
            # whole-response excerpt verifies against its source
            for s in sources:
                exc = p.list_excerpts(s.source_id)[0]
                assert exc.verify_offsets(s.raw_text)
            # descriptors carried
            s1 = next(s for s in sources if s.metadata.get("response_id") == "r1")
            assert p.get_descriptors(s1.source_id) == {"program": "Nursing", "first_gen": "Yes"}
            # sentiment recorded on metadata, not as a code
            assert s1.metadata["sentiment_label"] == "POSITIVE"

    def test_only_confident_assignments_become_applications(self, tmp_path):
        store = populate_project_store(_work_df(), _config(), tmp_path / "p2.qnw")
        with Project.open(store) as p:
            freq = p.code_frequency()
            # r1 -> Belonging, r2 -> Financial concern; r3 uncertain -> no application
            code_by_id = {c.code_id: c.name for c in p.get_codebook()}
            named = {code_by_id[cid]: n for cid, n in freq.items()}
            assert named == {"Belonging": 1, "Financial concern": 1}
            # all three a-priori labels exist as codes even if unused
            assert set(code_by_id.values()) == {"Belonging", "Financial concern", "Academic success"}

    def test_applications_carry_rater_and_run(self, tmp_path):
        store = populate_project_store(_work_df(), _config(), tmp_path / "p3.qnw")
        with Project.open(store) as p:
            apps = p.list_applications()
            assert apps and all(a.rater_id and a.run_id for a in apps)
            raters = p.list_raters()
            assert raters[0].kind == "transformer"
            assert raters[0].model_id == "facebook/bart-large-mnli"
            assert p.list_runs()[0].counts == {"responses": 3}

    def test_populate_is_additive_not_destructive(self, tmp_path):
        """v3.1.1: re-running must not wipe the store (it now holds human codes)."""
        path = tmp_path / "p4.qnw"
        populate_project_store(_work_df(), _config(), path)
        # Re-run the same frame: sources are reused, not duplicated; a second run
        # is recorded.
        populate_project_store(_work_df(), _config(), path)
        with Project.open(path) as p:
            assert len(p.list_sources()) == 3
            assert len(p.list_runs()) == 2
            # Codes matched by name, not created twice.
            names = [c.name for c in p.get_codebook()]
            assert names.count("Belonging") == 1

    def test_populate_adds_only_new_rows_on_rerun(self, tmp_path):
        path = tmp_path / "p5.qnw"
        populate_project_store(_work_df().head(2), _config(), path)
        populate_project_store(_work_df(), _config(), path)  # adds r3
        with Project.open(path) as p:
            assert len(p.list_sources()) == 3

    def test_response_id_and_question_recorded_for_join(self, tmp_path):
        store = populate_project_store(_work_df(), _config(), tmp_path / "p6.qnw")
        with Project.open(store) as p:
            src = p.find_source_by_response_id("r1", question="Q1")
            assert src is not None
            assert src.metadata["response_id"] == "r1"
            assert src.metadata["question_text"] == "Q1"
