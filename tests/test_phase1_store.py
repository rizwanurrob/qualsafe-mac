"""
Tests for Phase 1 — the .qnw store as the project of record (v3.1.1).

Covers: schema migration, human codings entering the store (the response_id join,
emergent codes, replace-not-append), respondent erasure across derived artifacts,
and the shared embedding cache.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.migrations import SchemaTooNewError, migrate
from core.model import Code, CodeApplication, Source
from core.populate import populate_project_store, record_human_codings
from core.project import SCHEMA_VERSION, Project, new_id


def _seed_store(path, response_ids=("r1", "r2", "r3"), question="Q1"):
    """A store with a few survey sources + whole-response excerpts."""
    with Project.create(path) as p:
        for rid in response_ids:
            src = Source(source_id=new_id("src"), type="survey_response", raw_text=f"text for {rid}",
                         label=question, metadata={"response_id": rid, "question_text": question})
            p.add_source(src)
            p.add_whole_response_excerpt(src)
    return path


# ── migrations ───────────────────────────────────────────────────────────────

class TestMigrations:
    def test_new_store_is_at_current_version(self, tmp_path):
        path = tmp_path / "new.qnw"
        with Project.create(path):
            pass
        con = sqlite3.connect(path)
        version = con.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]
        con.close()
        assert int(version) == SCHEMA_VERSION

    def test_v1_store_is_migrated_on_open(self, tmp_path):
        """Simulate a v1 file (no response_id index, version stamped 1)."""
        path = tmp_path / "old.qnw"
        with Project.create(path):
            pass
        con = sqlite3.connect(path)
        con.execute("DROP INDEX IF EXISTS idx_sources_response_id")
        con.execute("UPDATE meta SET value='1' WHERE key='schema_version'")
        con.commit()
        con.close()

        with Project.open(path):  # opening runs the migration
            pass

        con = sqlite3.connect(path)
        version = con.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]
        idx = con.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_sources_response_id'"
        ).fetchone()
        con.close()
        assert int(version) == SCHEMA_VERSION
        assert idx is not None

    def test_future_schema_is_refused(self, tmp_path):
        path = tmp_path / "future.qnw"
        with Project.create(path):
            pass
        con = sqlite3.connect(path)
        con.execute("UPDATE meta SET value='999' WHERE key='schema_version'")
        con.commit()
        con.close()
        with pytest.raises(SchemaTooNewError):
            Project.open(path)

    def test_migrate_returns_applied_versions(self):
        con = sqlite3.connect(":memory:")
        con.executescript("CREATE TABLE sources(source_id TEXT, metadata_json TEXT)")
        applied = migrate(con, from_version=1, to_version=2)
        con.close()
        assert applied == [2]


# ── human codings ────────────────────────────────────────────────────────────

class TestHumanCodings:
    def test_codings_land_as_human_applications(self, tmp_path):
        path = _seed_store(tmp_path / "h.qnw")
        result = record_human_codings(
            path, {"r1": ["Belonging"], "r2": ["Financial concern"]}, question_text="Q1"
        )
        assert result["applications"] == 2
        with Project.open(path) as p:
            apps = p.list_applications()
            assert all(a.coder == "human" and a.rater_id == "human_primary" for a in apps)

    def test_new_label_becomes_emergent_code(self, tmp_path):
        path = _seed_store(tmp_path / "h2.qnw")
        record_human_codings(path, {"r1": ["A brand new theme"]}, question_text="Q1")
        with Project.open(path) as p:
            code = p.find_code_by_name("A brand new theme")
            assert code is not None
            assert code.origin == "emergent"
            assert code.created_by == "human"

    def test_resave_replaces_not_appends(self, tmp_path):
        path = _seed_store(tmp_path / "h3.qnw")
        record_human_codings(path, {"r1": ["Belonging"]}, question_text="Q1")
        # Analyst changes their mind: r1 is now Financial concern, not Belonging.
        record_human_codings(path, {"r1": ["Financial concern"]}, question_text="Q1")
        with Project.open(path) as p:
            apps = p.list_applications()
            code_by_id = {c.code_id: c.name for c in p.get_codebook()}
            applied = [code_by_id[a.code_id] for a in apps]
            assert applied == ["Financial concern"]  # exactly one, not both

    def test_unmatched_response_id_is_reported_not_dropped_silently(self, tmp_path):
        path = _seed_store(tmp_path / "h4.qnw")
        result = record_human_codings(path, {"nonexistent": ["X"]}, question_text="Q1")
        assert result["unmatched"] == 1
        assert result["applications"] == 0

    def test_question_scoping_resolves_the_right_source(self, tmp_path):
        """Same response_id under two questions must not collide."""
        path = tmp_path / "h5.qnw"
        with Project.create(path) as p:
            for q in ("Q1", "Q2"):
                src = Source(source_id=new_id("src"), type="survey_response", raw_text=f"{q} answer",
                             label=q, metadata={"response_id": "r1", "question_text": q})
                p.add_source(src)
                p.add_whole_response_excerpt(src)
        record_human_codings(path, {"r1": ["ThemeForQ2"]}, question_text="Q2")
        with Project.open(path) as p:
            q2 = p.find_source_by_response_id("r1", question="Q2")
            q1 = p.find_source_by_response_id("r1", question="Q1")
            q2_excerpt = p.list_excerpts(q2.source_id)[0]
            applied_excerpts = {a.excerpt_id for a in p.list_applications()}
            assert q2_excerpt.excerpt_id in applied_excerpts
            q1_excerpt = p.list_excerpts(q1.source_id)[0]
            assert q1_excerpt.excerpt_id not in applied_excerpts


# ── erasure ──────────────────────────────────────────────────────────────────

class TestErasure:
    def test_delete_source_leaves_codebook_intact(self, tmp_path):
        """Deleting a respondent must never touch the shared codebook."""
        path = _seed_store(tmp_path / "e.qnw")
        with Project.open(path) as p:
            code_id = p.add_code(Code(code_id="", name="Belonging"))
            src = p.find_source_by_response_id("r1", question="Q1")
            exc = p.list_excerpts(src.source_id)[0]
            p.apply_code(CodeApplication(application_id="", excerpt_id=exc.excerpt_id, code_id=code_id))
            p.delete_source(src.source_id)

            assert p.find_source_by_response_id("r1", question="Q1") is None
            assert p.find_code_by_name("Belonging") is not None  # codebook survives
            assert len(p.list_sources()) == 2

    def test_erase_respondent_across_artifacts(self, tmp_path):
        from core.erasure import erase_respondent

        project_dir = tmp_path / "run_1"
        project_dir.mkdir()
        store = project_dir / "project.qnw"
        _seed_store(store)

        # Scored CSV with a response_id column + a summary CSV with a quote column.
        pd.DataFrame({
            "response_id": ["r1", "r2", "r3"],
            "response_text": ["text for r1", "text for r2", "text for r3"],
        }).to_csv(project_dir / "responses_scored.csv", index=False)
        pd.DataFrame({
            "cluster_id": [0],
            "example_quotes": ["text for r1 || text for r2"],
        }).to_csv(project_dir / "cluster_summary.csv", index=False)
        (project_dir / "run_report.md").write_text(
            "Quote: text for r1 was notable.", encoding="utf-8"
        )
        np.save(project_dir / "embeddings.npy", np.zeros((3, 4)))

        report = erase_respondent(project_dir, "r1")

        # Store: r1 gone, others intact.
        with Project.open(store) as p:
            assert p.find_source_by_response_id("r1", question="Q1") is None
            assert len(p.list_sources()) == 2

        # Scored CSV: r1 row dropped.
        scored = pd.read_csv(project_dir / "responses_scored.csv")
        assert "r1" not in scored["response_id"].astype(str).tolist()
        assert len(scored) == 2

        # Summary quote column: r1's text scrubbed, r2's kept.
        summary = pd.read_csv(project_dir / "cluster_summary.csv")
        cell = summary["example_quotes"].iloc[0]
        assert "text for r1" not in cell
        assert "text for r2" in cell

        # Markdown scrubbed; embeddings invalidated; audit written w/o the id.
        assert "text for r1" not in (project_dir / "run_report.md").read_text(encoding="utf-8")
        assert not (project_dir / "embeddings.npy").exists()
        audit = (project_dir / "audit_log.jsonl").read_text(encoding="utf-8")
        assert "r1" not in audit  # only the hash is stored
        assert report["response_id_hash"] in audit

    def test_purge_project_removes_directory(self, tmp_path):
        from core.erasure import purge_project

        project_dir = tmp_path / "run_2"
        project_dir.mkdir()
        _seed_store(project_dir / "project.qnw")
        result = purge_project(project_dir)
        assert result["status"] == "purged"
        assert not project_dir.exists()


# ── embedding cache ──────────────────────────────────────────────────────────

class TestEmbeddingCache:
    def _counting_encoder(self):
        calls = {"n": 0}

        def build(texts, model_name, batch_size, normalize_embeddings, dedupe=False):
            calls["n"] += 1
            return np.arange(len(texts) * 3, dtype=np.float32).reshape(len(texts), 3)

        return build, calls

    def test_second_call_hits_cache(self, tmp_path, monkeypatch):
        import core.embedding_cache as ec

        build, calls = self._counting_encoder()
        monkeypatch.setattr(ec, "build_embeddings", build)

        texts = ["a", "b", "c"]
        first = ec.load_or_build_embeddings(texts, "m", 32, tmp_path)
        second = ec.load_or_build_embeddings(texts, "m", 32, tmp_path)
        assert calls["n"] == 1  # second served from disk
        np.testing.assert_array_equal(first, second)

    def test_changed_text_reencodes(self, tmp_path, monkeypatch):
        import core.embedding_cache as ec

        build, calls = self._counting_encoder()
        monkeypatch.setattr(ec, "build_embeddings", build)

        ec.load_or_build_embeddings(["a", "b"], "m", 32, tmp_path)
        ec.load_or_build_embeddings(["a", "c"], "m", 32, tmp_path)  # different texts
        assert calls["n"] == 2

    def test_normalize_flag_is_part_of_the_key(self, tmp_path, monkeypatch):
        """A run that flips normalize must not be served the other version."""
        import core.embedding_cache as ec

        build, calls = self._counting_encoder()
        monkeypatch.setattr(ec, "build_embeddings", build)

        ec.load_or_build_embeddings(["a"], "m", 32, tmp_path, normalize_embeddings=True)
        ec.load_or_build_embeddings(["a"], "m", 32, tmp_path, normalize_embeddings=False)
        assert calls["n"] == 2

    def test_clear_cache(self, tmp_path, monkeypatch):
        import core.embedding_cache as ec

        build, _ = self._counting_encoder()
        monkeypatch.setattr(ec, "build_embeddings", build)
        ec.load_or_build_embeddings(["a"], "m", 32, tmp_path)
        removed = ec.clear_cache(tmp_path)
        assert removed == 1
        assert not list(tmp_path.glob("embeddings_*.npy"))
