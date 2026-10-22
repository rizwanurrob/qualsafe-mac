"""
Tests for Phase 4 — LLM concurrency, outlier flag, codebook snapshots, sentence
units (v4).
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analyze_survey import flag_outliers
from core.model import Code, CodeApplication, Source
from core.project import Project, new_id
from core.text_units import split_sentences


# ── 4.1 LLM concurrency ──────────────────────────────────────────────────────

class TestLlmConcurrency:
    def _engine(self, delay=0.0):
        from engines.llm_engine import LlmEngine

        client = MagicMock()

        def gen(model, prompt, **kw):
            if delay:
                time.sleep(delay)
            # Echo the whole prompt (which embeds the response text) so we can
            # verify each output position got its matching input.
            return {"theme_scores": {}, "sentiment": "neutral", "rationale": prompt}

        client.generate_json.side_effect = gen
        return LlmEngine(model="m", client=client)

    def test_concurrent_preserves_input_order(self):
        eng = self._engine()
        # Distinct, non-prefix tokens (…END so token 1 ⊄ token 10).
        texts = [f"TOKEN{i}END" for i in range(20)]
        out = eng.code_responses(texts, ["A"], {"max_workers": 4})
        # out[i] must correspond to texts[i] despite concurrent completion order.
        assert all(texts[i] in out[i].rationale for i in range(len(texts)))

    def test_concurrency_actually_overlaps(self):
        """With workers>1 and per-call delay, wall time < sequential sum."""
        eng = self._engine(delay=0.1)
        texts = [f"r{i}" for i in range(8)]
        start = time.time()
        eng.code_responses(texts, ["A"], {"max_workers": 4})
        elapsed = time.time() - start
        # 8 * 0.1 = 0.8s sequential, about 0.2s with 4 workers. The bound sits between the two with room for a
        # busy machine: at 0.05 s a call it was 0.3 against 0.4 sequential, and an Intel Mac CI runner took 0.303.
        assert elapsed < 0.6

    def test_progress_is_monotonic_under_concurrency(self):
        eng = self._engine()
        seen = []
        lock = threading.Lock()

        def cb(done, total):
            with lock:
                seen.append(done)

        eng.code_responses([f"r{i}" for i in range(10)], ["A"],
                           {"max_workers": 4, "progress_callback": cb})
        assert seen[-1] == 10
        assert seen == sorted(seen)  # done only ever increases

    def test_single_worker_uses_sequential_path(self):
        eng = self._engine()
        out = eng.code_responses(["a", "b"], ["A"], {"max_workers": 1})
        assert len(out) == 2


# ── 4.2 outlier flag ─────────────────────────────────────────────────────────

class TestOutlierFlag:
    def test_far_point_flagged(self):
        # Cluster 0: tight around origin, with one far outlier.
        pts = np.array([[0, 0], [0.1, 0], [0, 0.1], [-0.1, 0], [0.05, 0.05], [10, 10]], dtype=float)
        labels = [0, 0, 0, 0, 0, 0]
        centers = np.array([[2, 2]])  # centroid pulled by the outlier, still far from [10,10]
        dist, flag = flag_outliers(pts, labels, centers, percentile=80)
        assert flag[-1]  # the [10,10] point is flagged
        assert not flag[0]  # a central point is not

    def test_small_cluster_not_flagged(self):
        pts = np.array([[0, 0], [9, 9]], dtype=float)
        dist, flag = flag_outliers(pts, [0, 0], np.array([[0, 0]]), percentile=50)
        assert not flag.any()  # <5 points: no flag (a threshold there is meaningless)

    def test_distances_returned_aligned(self):
        pts = np.array([[0, 0], [3, 4]], dtype=float)
        dist, flag = flag_outliers(pts, [0, 0], np.array([[0, 0]]))
        assert dist[0] == pytest.approx(0.0)
        assert dist[1] == pytest.approx(5.0)


# ── 4.3 codebook snapshots ───────────────────────────────────────────────────

class TestCodebookSnapshots:
    def test_merge_auto_snapshots_before_mutation(self, tmp_path):
        with Project.create(tmp_path / "s.qnw") as p:
            a = p.add_code(Code(code_id="", name="A"))
            b = p.add_code(Code(code_id="", name="B"))
            assert p.list_codebook_versions() == []
            p.merge_codes(a, b)
            versions = p.list_codebook_versions()
            assert len(versions) == 1
            assert versions[0]["trigger"] == "merge"

    def test_delete_and_reparent_snapshot(self, tmp_path):
        with Project.create(tmp_path / "s2.qnw") as p:
            a = p.add_code(Code(code_id="", name="A"))
            b = p.add_code(Code(code_id="", name="B"))
            p.set_code_parent(b, a)
            p.delete_code(b)
            triggers = {v["trigger"] for v in p.list_codebook_versions()}
            assert {"reparent", "delete"} <= triggers

    def test_manual_tag(self, tmp_path):
        with Project.create(tmp_path / "s3.qnw") as p:
            p.add_code(Code(code_id="", name="A"))
            p.tag_codebook_version("before big reorg")
            v = p.list_codebook_versions()
            assert v[0]["note"] == "before big reorg" and v[0]["trigger"] == "manual"

    def test_restore_preserves_applications_for_surviving_codes(self, tmp_path):
        """The load-bearing one: restore must NOT cascade-wipe codings."""
        with Project.create(tmp_path / "s4.qnw") as p:
            keep = p.add_code(Code(code_id="", name="Keep"))
            src = Source(source_id=new_id("src"), type="survey_response", raw_text="t",
                         label="Q", metadata={"response_id": "1"})
            p.add_source(src)
            exc = p.add_whole_response_excerpt(src)
            p.apply_code(CodeApplication(application_id="", excerpt_id=exc, code_id=keep))
            tag = p.tag_codebook_version("checkpoint")
            version_id = p.list_codebook_versions()[0]["version_id"]

            # Add a new code after the snapshot, then restore.
            p.add_code(Code(code_id="", name="Later"))
            p.restore_codebook_version(version_id)

            names = [c.name for c in p.get_codebook()]
            assert "Keep" in names and "Later" not in names
            # The application on the surviving 'Keep' code is intact.
            assert len(p.list_applications()) == 1

    def test_codebook_hash_changes_with_edits(self, tmp_path):
        with Project.create(tmp_path / "s5.qnw") as p:
            h0 = p.codebook_hash()
            p.add_code(Code(code_id="", name="A"))
            assert p.codebook_hash() != h0


# ── 4.4 sentence splitter + unitization ──────────────────────────────────────

class TestSentenceSplitter:
    def test_basic_split_with_offsets(self):
        text = "I love it. The support was slow. Fix that!"
        spans = split_sentences(text)
        assert [s for s, _, _ in spans] == ["I love it.", "The support was slow.", "Fix that!"]
        # Offset guarantee: every span is the exact source slice.
        for sentence, start, end in spans:
            assert text[start:end] == sentence

    def test_abbreviation_not_split(self):
        text = "I met Dr. Chen today. It went well."
        spans = split_sentences(text)
        assert spans[0][0] == "I met Dr. Chen today."

    def test_no_terminator_is_one_span(self):
        spans = split_sentences("just one line no period")
        assert len(spans) == 1 and spans[0][0] == "just one line no period"

    def test_empty_returns_none(self):
        assert split_sentences("") == []
        assert split_sentences("   ") == []

    def test_populate_sentence_unit_creates_sentence_excerpts(self, tmp_path):
        from core.populate import populate_project_store
        import pandas as pd

        df = pd.DataFrame({
            "response_id": ["1"], "response_text": ["First point. Second point."],
            "question_text": ["Q1"],
        })
        cfg = {"input": {}, "output": {}, "models": {}, "zero_shot": {"labels": []},
               "unit": "sentence"}
        store = populate_project_store(df, cfg, tmp_path / "u.qnw")
        with Project.open(store) as p:
            src = p.list_sources()[0]
            excerpts = p.list_excerpts(src.source_id)
            texts = [e.text for e in excerpts]
            # Whole-response excerpt + two sentence excerpts.
            assert "First point. Second point." in texts
            assert "First point." in texts and "Second point." in texts


class TestCrossUnitGuard:
    def test_refuses_cross_unit(self):
        from analysis.agreement import CrossUnitComparisonError, assert_comparable_units

        assert_comparable_units("response", "response")  # ok
        with pytest.raises(CrossUnitComparisonError):
            assert_comparable_units("response", "sentence")
