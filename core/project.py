#!/usr/bin/env python
"""
SQLite-backed project store (`.qnw`) for QualSafe (v3).

This is the persistence layer for the shared project model (core/model.py). It
is the single place that touches SQL; every other module goes through the typed
`Project` API (add_source, add_excerpt, apply_code, get_codebook, ...). See
V3_PLAN.md §2.3 for the rationale (the analyses we want are relational joins; a
`.qnw` file is one portable, FERPA-friendly, transactional file).

Design decisions:
- One SQLite file == one project. `sqlite3` is stdlib — no new dependency.
- Embeddings are NOT stored here (they bloat the file and aren't needed for
  analytical queries); they stay in the existing .npy hash cache.
- IDs are minted as UUID-based strings when a dataclass is added without one, so
  merging/moving projects never collides (schema refinement #1 from the review).
- JSON export/import provides a portable, inspectable interchange format while
  SQLite remains the working store.
- Structural foreign keys (excerpt→source, application→excerpt/code,
  descriptor→source, code.parent→code) are enforced; provenance columns
  (rater_id, run_id) are plain columns so a coding can record provenance even if
  those rows are written later.

Nothing here is wired into the survey pipeline yet — that (populating the store
from a run, alongside the existing CSV outputs) is the next increment.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union

import pandas as pd

from core.model import (
    Code,
    CodeApplication,
    CodeDecisionType,
    CodingDecision,
    CodingReviewStatus,
    CodingRunConfig,
    Descriptor,
    DescriptorField,
    Excerpt,
    Memo,
    Rater,
    RunManifest,
    SavedChart,
    Source,
    WeightScale,
)

# v2 (3.1.1): adds an expression index on sources.metadata_json -> response_id.
# v3 (3.5/v4): adds the codebook_versions table (codebook snapshots).
# v4 (4.0): the corpus model -- cases, annotations, excerpt links.
# v5 (4.6): saved_charts -- a figure's definition, so it can be re-run later.
# v6 (4.11): sources stop carrying the author's filesystem.
# v7 (Alt Survey Flow): structured-coding fields on `codes`, plus
#     coding_decisions (the per-code audit trail) and coding_run_configs.
# v8 (4.12): rater_coverage -- which responses each rater reviewed, so "no
#     code applies" is recorded, not inferred; document_coverage -- which
#     documents a coder has finished, for agreement on span coding.
# v9 (4.13): project_events -- a dated record of every analytic decision
#     (codebook edits, memos, adjudication, imports, erasure); memos gain
#     created_at / updated_at. The audit trail export reads both.
# Bumping this requires an entry in core/migrations.py MIGRATIONS.
SCHEMA_VERSION = 9


def _default_actor() -> str:
    try:
        from core.app_settings import load_app_settings

        return str(load_app_settings().get("analyst_name", "") or "")
    except Exception:  # noqa: BLE001 - a settings problem must never block opening a project
        return ""


@dataclass
class RaterItemSet:
    """What `Project.rater_item_set` returns."""

    labels: Dict[str, set]
    #: True when the items come from the v8 review record; False when they
    #: were inferred from applications (agreement likely overstated).
    recorded: bool
    #: Survey excerpts this rater coded that are not in the review record.
    uncovered_applied: int = 0


def new_id(prefix: str) -> str:
    """Mint a collision-resistant id like 'exc_9f3a1c2b4d5e'."""
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS sources (
    source_id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    raw_text TEXT NOT NULL,
    label TEXT DEFAULT '',
    metadata_json TEXT DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS excerpts (
    excerpt_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES sources(source_id) ON DELETE CASCADE,
    text TEXT NOT NULL,
    char_start INTEGER NOT NULL,
    char_end INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS codes (
    code_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    definition TEXT DEFAULT '',
    parent_id TEXT REFERENCES codes(code_id) ON DELETE SET NULL,
    origin TEXT DEFAULT 'a_priori',
    created_by TEXT DEFAULT 'human',
    weight_kind TEXT,
    weight_min REAL,
    weight_max REAL,
    -- Structured coding (Alt Survey Flow, schema v7). Defaults are chosen so an
    -- existing code, opened by old code, behaves exactly as it always did.
    inclusion_criteria TEXT DEFAULT '',
    exclusion_criteria TEXT DEFAULT '',
    examples_json TEXT DEFAULT '[]',
    decision_type TEXT DEFAULT 'noul',
    rubric_levels_json TEXT
);
CREATE TABLE IF NOT EXISTS code_applications (
    application_id TEXT PRIMARY KEY,
    excerpt_id TEXT NOT NULL REFERENCES excerpts(excerpt_id) ON DELETE CASCADE,
    code_id TEXT NOT NULL REFERENCES codes(code_id) ON DELETE CASCADE,
    coder TEXT DEFAULT 'transformer',
    rater_id TEXT,
    run_id TEXT,
    weight REAL,
    confidence REAL,
    margin REAL,
    rationale TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS descriptors (
    source_id TEXT NOT NULL REFERENCES sources(source_id) ON DELETE CASCADE,
    key TEXT NOT NULL,
    value TEXT,
    PRIMARY KEY (source_id, key)
);
CREATE TABLE IF NOT EXISTS descriptor_fields (
    key TEXT PRIMARY KEY,
    dtype TEXT NOT NULL,
    ordered_levels_json TEXT,
    description TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS memos (
    memo_id TEXT PRIMARY KEY,
    target_type TEXT NOT NULL,
    target_id TEXT,
    text TEXT NOT NULL,
    author TEXT DEFAULT 'human',
    created_at TEXT DEFAULT '',
    updated_at TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS saved_charts (
    chart_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    spec_json TEXT NOT NULL,
    source TEXT DEFAULT 'codings',
    created_by TEXT DEFAULT 'human',
    created_at TEXT DEFAULT ''
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_saved_charts_name ON saved_charts(name);
CREATE TABLE IF NOT EXISTS raters (
    rater_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    name TEXT DEFAULT '',
    model_id TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    package_version TEXT,
    mode TEXT,
    engine TEXT,
    model TEXT,
    timestamp TEXT,
    thresholds_json TEXT DEFAULT '{}',
    counts_json TEXT DEFAULT '{}',
    template_version TEXT,
    exported_raw_text INTEGER DEFAULT 0,
    exported_embeddings INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS codebook_versions (
    version_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    note TEXT DEFAULT '',
    trigger TEXT DEFAULT '',
    codebook_hash TEXT NOT NULL,
    snapshot_json TEXT NOT NULL
);
-- ── Corpus model (schema v4) ────────────────────────────────────────────────
-- A "document" is just a Source with type='document' (its title/path/word_count
-- live in metadata_json), so no separate table is needed. What the corpus DOES
-- need is a unit that spans several sources — a person, site, or focus group —
-- which is what `cases` provides. Annotations and links hang off excerpts.
CREATE TABLE IF NOT EXISTS cases (
    case_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    kind TEXT DEFAULT 'person',
    description TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS case_membership (
    case_id TEXT NOT NULL REFERENCES cases(case_id) ON DELETE CASCADE,
    source_id TEXT NOT NULL REFERENCES sources(source_id) ON DELETE CASCADE,
    PRIMARY KEY (case_id, source_id)
);
CREATE TABLE IF NOT EXISTS annotations (
    annotation_id TEXT PRIMARY KEY,
    excerpt_id TEXT NOT NULL REFERENCES excerpts(excerpt_id) ON DELETE CASCADE,
    text TEXT NOT NULL,
    author TEXT DEFAULT 'human',
    created_at TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS excerpt_links (
    link_id TEXT PRIMARY KEY,
    from_excerpt TEXT NOT NULL REFERENCES excerpts(excerpt_id) ON DELETE CASCADE,
    to_excerpt TEXT NOT NULL REFERENCES excerpts(excerpt_id) ON DELETE CASCADE,
    kind TEXT DEFAULT 'see_also',
    note TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_case_membership_source ON case_membership(source_id);
CREATE INDEX IF NOT EXISTS idx_annotations_excerpt ON annotations(excerpt_id);
CREATE INDEX IF NOT EXISTS idx_links_from ON excerpt_links(from_excerpt);
CREATE INDEX IF NOT EXISTS idx_sources_type ON sources(type);
-- ── Structured coding / human review (schema v7, Alt Survey Flow) ───────────
-- Sits ABOVE code_applications rather than replacing it: every candidate code a
-- structured engine was asked about is recorded here, whether or not it was
-- assigned, whether or not a human has looked at it yet. code_applications
-- stays the canonical "this code IS on this excerpt" layer every existing
-- analysis function reads. See core/model.py::CodingDecision.
CREATE TABLE IF NOT EXISTS coding_decisions (
    decision_id TEXT PRIMARY KEY,
    excerpt_id TEXT NOT NULL REFERENCES excerpts(excerpt_id) ON DELETE CASCADE,
    code_id TEXT NOT NULL REFERENCES codes(code_id) ON DELETE CASCADE,
    run_id TEXT NOT NULL,
    model_score REAL,
    model_assigned INTEGER DEFAULT 0,
    review_status TEXT DEFAULT 'unreviewed',
    human_assigned INTEGER,
    reviewer TEXT DEFAULT '',
    reviewed_at TEXT DEFAULT '',
    note TEXT DEFAULT '',
    UNIQUE(excerpt_id, code_id, run_id)
);
CREATE INDEX IF NOT EXISTS idx_decisions_excerpt ON coding_decisions(excerpt_id);
CREATE INDEX IF NOT EXISTS idx_decisions_run ON coding_decisions(run_id);
CREATE INDEX IF NOT EXISTS idx_decisions_status ON coding_decisions(review_status);
CREATE TABLE IF NOT EXISTS coding_run_configs (
    config_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    spec_json TEXT NOT NULL,
    created_by TEXT DEFAULT 'human',
    created_at TEXT DEFAULT ''
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_coding_run_configs_name ON coding_run_configs(name);
-- v8: which excerpts each rater reviewed. A row means "this rater gave a
-- complete coding of this excerpt", including "no code applies" -- which a
-- code_applications row cannot say. Kappa is computed over these items; before
-- v8 it was inferred from applications and silently dropped every response a
-- coder left uncoded (review finding F1). Cascades with the excerpt, so
-- erasure removes it with no extra code.
CREATE TABLE IF NOT EXISTS rater_coverage (
    rater_id TEXT NOT NULL,
    excerpt_id TEXT NOT NULL REFERENCES excerpts(excerpt_id) ON DELETE CASCADE,
    run_id TEXT,
    reviewed_at TEXT DEFAULT '',
    PRIMARY KEY (rater_id, excerpt_id)
);
CREATE INDEX IF NOT EXISTS idx_coverage_excerpt ON rater_coverage(excerpt_id);
-- v8: documents a coder has marked as fully coded. Span-coding agreement is
-- computed only over these, because an unfinished document's uncoded
-- sentences would otherwise read as "no code applies" (review finding F4).
CREATE TABLE IF NOT EXISTS document_coverage (
    rater_id TEXT NOT NULL,
    source_id TEXT NOT NULL REFERENCES sources(source_id) ON DELETE CASCADE,
    marked_at TEXT DEFAULT '',
    PRIMARY KEY (rater_id, source_id)
);
-- v9: the project event log. One row per analytic decision, append-only,
-- in the analyst's words. No foreign keys: an event outlives the code or memo
-- it describes (a deleted code's deletion is exactly what an auditor asks
-- about). Never holds response text or response ids.
CREATE TABLE IF NOT EXISTS project_events (
    event_id TEXT PRIMARY KEY,
    at TEXT NOT NULL,
    actor TEXT DEFAULT '',
    kind TEXT NOT NULL,
    target_type TEXT DEFAULT '',
    target_id TEXT DEFAULT '',
    summary TEXT DEFAULT '',
    detail_json TEXT DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_events_at ON project_events(at);
CREATE INDEX IF NOT EXISTS idx_excerpts_source ON excerpts(source_id);
CREATE INDEX IF NOT EXISTS idx_apps_excerpt ON code_applications(excerpt_id);
CREATE INDEX IF NOT EXISTS idx_apps_code ON code_applications(code_id);
CREATE INDEX IF NOT EXISTS idx_descriptors_source ON descriptors(source_id);
CREATE INDEX IF NOT EXISTS idx_apps_rater ON code_applications(rater_id);
CREATE INDEX IF NOT EXISTS idx_apps_run ON code_applications(run_id);
-- Sources are looked up by response_id on every populate (to reuse rather than
-- duplicate) and every Lab save (to attach human codes). Mirrored in
-- core/migrations.py::_migrate_1_to_2 for stores created before v2.
CREATE INDEX IF NOT EXISTS idx_sources_response_id
    ON sources(json_extract(metadata_json, '$.response_id'));
"""

# Full-text index over source text (schema v4). Kept OUT of `_SCHEMA` and created
# behind a try/except because FTS5 is a compile-time SQLite option: it is present
# in every build we expect (verified on the python.org Windows build), but a store
# must still *open* on a SQLite without it. When it is missing, `fts_available()`
# returns False and search falls back to a slower scan — a degraded feature, never
# a store that won't open.
#
# External-content table (`content='sources'`): the text is not duplicated, and
# the triggers keep the index in step with inserts, updates, and deletes —
# including the cascade from respondent erasure, which must not leave searchable
# ghosts of erased text.
_FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS sources_fts USING fts5(
    raw_text, content='sources', content_rowid='rowid'
);
CREATE TRIGGER IF NOT EXISTS sources_fts_ai AFTER INSERT ON sources BEGIN
    INSERT INTO sources_fts(rowid, raw_text) VALUES (new.rowid, new.raw_text);
END;
CREATE TRIGGER IF NOT EXISTS sources_fts_ad AFTER DELETE ON sources BEGIN
    INSERT INTO sources_fts(sources_fts, rowid, raw_text)
        VALUES ('delete', old.rowid, old.raw_text);
END;
CREATE TRIGGER IF NOT EXISTS sources_fts_au AFTER UPDATE ON sources BEGIN
    INSERT INTO sources_fts(sources_fts, rowid, raw_text)
        VALUES ('delete', old.rowid, old.raw_text);
    INSERT INTO sources_fts(rowid, raw_text) VALUES (new.rowid, new.raw_text);
END;
"""


class Project:
    """A `.qnw` project: a single SQLite file holding the shared model.

    Use as a context manager (``with Project.create(path) as p: ...``) or call
    ``close()`` explicitly. All writes commit immediately (autocommit via
    per-method commit) so an interrupted session never corrupts the file.
    """

    def __init__(self, path: Union[str, Path]):
        self.path = Path(path)
        self._conn = sqlite3.connect(str(self.path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._in_bulk = False
        self._init_schema()
        #: Who the event log names. Defaults to the analyst name the web app
        #: stores; the desktop app sets it from its own preference.
        self.actor = _default_actor()

    # ── lifecycle ────────────────────────────────────────────────────────────
    @classmethod
    def create(cls, path: Union[str, Path]) -> "Project":
        """Create (or open) a project file."""
        return cls(path)

    @classmethod
    def open(cls, path: Union[str, Path]) -> "Project":
        """Open an existing project file."""
        if not Path(path).exists():
            raise FileNotFoundError(f"Project file not found: {path}")
        return cls(path)

    def _init_schema(self) -> None:
        from core.migrations import assert_json1_available, migrate

        assert_json1_available(self._conn)
        self._conn.executescript(_SCHEMA)

        cur = self._conn.execute("SELECT value FROM meta WHERE key = 'schema_version'")
        row = cur.fetchone()
        if row is None:
            # Brand-new store: it is current by construction.
            self._conn.execute(
                "INSERT INTO meta(key, value) VALUES ('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
        else:
            found = int(row["value"])
            if found != SCHEMA_VERSION:
                # One transaction for the whole upgrade: a crash mid-migration
                # must roll back rather than leave a half-migrated file.
                with self._conn:
                    applied = migrate(self._conn, from_version=found,
                                      to_version=SCHEMA_VERSION)
                    self._conn.execute(
                        "UPDATE meta SET value = ? WHERE key = 'schema_version'",
                        (str(SCHEMA_VERSION),),
                    )
                self._vacuum_after(applied)
        self._init_fts()
        self._commit()

    #: Migrations that shorten or remove stored text rather than adding to it.
    #: SQLite marks a rewritten row's old page free and leaves it legible until
    #: something reuses it, so for these the file has to be rebuilt or the value
    #: the migration removed is still sitting in the bytes. `core/erasure.py`
    #: learned this the same way, and measured it.
    _REDACTING_MIGRATIONS = frozenset({6})

    def _vacuum_after(self, applied: Sequence[int]) -> bool:
        """Rebuild the file if a migration removed something.

        Outside the migration transaction, because SQLite refuses to VACUUM
        inside one. Best-effort: a store that cannot be compacted has still been
        migrated correctly, and failing the open would be a worse outcome than a
        larger file.
        """
        if not set(applied) & self._REDACTING_MIGRATIONS:
            return False
        try:
            self._conn.execute("VACUUM")
            return True
        except Exception:  # noqa: BLE001 - a locked file must not fail the open
            return False

    def _init_fts(self) -> None:
        """Create the full-text index if this SQLite supports FTS5.

        Backfills only when the table is created for the first time over a store
        that already holds sources (an existing project gaining search, or one
        first opened on a SQLite without FTS5). Never re-indexes on a normal open
        — the triggers keep it current — so opening a large corpus stays fast.
        """
        existed = self._conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='sources_fts'"
        ).fetchone() is not None
        try:
            self._conn.executescript(_FTS_SCHEMA)
            self._fts_available = True
        except sqlite3.OperationalError:
            # No FTS5 in this SQLite build: search degrades to a scan.
            self._fts_available = False
            return
        if not existed:
            has_rows = self._conn.execute("SELECT 1 FROM sources LIMIT 1").fetchone()
            if has_rows:
                self.rebuild_fts()

    def fts_available(self) -> bool:
        """True when the full-text index is usable (FTS5 present in SQLite)."""
        return bool(getattr(self, "_fts_available", False))

    def rebuild_fts(self) -> None:
        """Re-index all source text. Only needed after a bulk out-of-band change."""
        if not self.fts_available():
            return
        self._conn.execute("INSERT INTO sources_fts(sources_fts) VALUES ('rebuild')")
        self._commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "Project":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    @contextmanager
    def bulk(self):
        """Defer commits so a batch of writes lands as one transaction.

        Every write method commits on its own, which is right for interactive
        edits and wrong for populate: thousands of per-row commits is slow, and an
        interrupted run leaves a half-populated store that looks complete. Inside
        this block the per-method commits become no-ops and a single commit (or
        rollback) happens on exit.

            with proj.bulk():
                for row in rows:
                    proj.add_source(...)

        Not reentrant and not thread-safe — populate is a single loop on one
        thread, and anything fancier should use its own connection.
        """
        if self._in_bulk:
            raise RuntimeError("Project.bulk() is not reentrant")
        self._in_bulk = True
        try:
            with self._conn:  # commits on success, rolls back on exception
                yield self
        finally:
            self._in_bulk = False

    def _commit(self) -> None:
        """Commit unless we're inside a bulk() block (which owns the transaction)."""
        if not self._in_bulk:
            self._conn.commit()

    # ── sources ──────────────────────────────────────────────────────────────
    def add_source(self, source: Source) -> str:
        sid = source.source_id or new_id("src")
        self._conn.execute(
            "INSERT INTO sources(source_id, type, raw_text, label, metadata_json) "
            "VALUES (?, ?, ?, ?, ?)",
            (sid, source.type, source.raw_text, source.label, json.dumps(source.metadata)),
        )
        self._commit()
        return sid

    def source_ids_in_ingestion_order(self) -> List[str]:
        """Source ids in the order the sources were added.

        `list_sources()` sorts by id, and ids minted for new sources are random, so that order is arbitrary:
        anything that means 'the order they were ingested' (the saturation curve) must use this instead."""
        return [r["source_id"] for r in self._conn.execute("SELECT source_id FROM sources ORDER BY rowid")]

    def get_meta(self, key: str, default: str = "") -> str:
        """A small project-level value (the interview guide, for one). Text in, text out."""
        row = self._conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return default if row is None or row["value"] is None else str(row["value"])

    def set_meta(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT INTO meta(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))
        self._commit()

    def update_run_counts(self, run_id: str, counts: Dict[str, Any]) -> None:
        """Replace a run's `counts` once its outcome is known."""
        self._conn.execute("UPDATE runs SET counts_json = ? WHERE run_id = ?",
                           (json.dumps(counts), run_id))
        self._commit()

    def delete_excerpt_if_unused(self, excerpt_id: str) -> bool:
        """Remove a passage that carries no code, note, memo or link. True if it was removed.

        For a tool that made a passage only to hang a suggestion on and has taken the
        suggestion away again; anything a person added to it keeps it."""
        q = self._conn.execute
        busy = (
            q("SELECT 1 FROM code_applications WHERE excerpt_id = ? LIMIT 1", (excerpt_id,)).fetchone()
            or q("SELECT 1 FROM annotations WHERE excerpt_id = ? LIMIT 1", (excerpt_id,)).fetchone()
            or q("SELECT 1 FROM excerpt_links WHERE from_excerpt = ? OR to_excerpt = ? LIMIT 1",
                 (excerpt_id, excerpt_id)).fetchone()
            or q("SELECT 1 FROM memos WHERE target_type = 'excerpt' AND target_id = ? LIMIT 1",
                 (excerpt_id,)).fetchone())
        if busy:
            return False
        q("DELETE FROM excerpts WHERE excerpt_id = ?", (excerpt_id,))
        self._commit()
        return True

    def update_source_metadata(self, source_id: str, patch: Dict[str, Any]) -> bool:
        """Merge `patch` into a source's metadata (top-level keys; a None value removes one).

        For small facts kept with a document, such as who the speakers are. No schema
        change: `metadata_json` already exists. Returns False if there is no such source.
        """
        row = self._conn.execute(
            "SELECT metadata_json FROM sources WHERE source_id = ?", (source_id,)).fetchone()
        if row is None:
            return False
        meta = json.loads(row["metadata_json"] or "{}")
        for key, value in patch.items():
            if value is None:
                meta.pop(key, None)
            else:
                meta[key] = value
        self._conn.execute("UPDATE sources SET metadata_json = ? WHERE source_id = ?",
                           (json.dumps(meta), source_id))
        self._commit()
        return True

    def get_source(self, source_id: str) -> Optional[Source]:
        row = self._conn.execute(
            "SELECT * FROM sources WHERE source_id = ?", (source_id,)
        ).fetchone()
        if row is None:
            return None
        return Source(
            source_id=row["source_id"], type=row["type"], raw_text=row["raw_text"],
            label=row["label"], metadata=json.loads(row["metadata_json"] or "{}"),
        )

    def list_sources(self) -> List[Source]:
        return [
            Source(source_id=r["source_id"], type=r["type"], raw_text=r["raw_text"],
                   label=r["label"], metadata=json.loads(r["metadata_json"] or "{}"))
            for r in self._conn.execute("SELECT * FROM sources ORDER BY source_id")
        ]

    def find_source_by_response_id(
        self, response_id: str, question: Optional[str] = None
    ) -> Optional[Source]:
        """Find the Source minted for a given survey response_id.

        This is the join that makes the store additive and lets human codes
        attach to the right row: the Labeling Lab and the pipeline both key on the
        CSV's `response_id`, but the store keys on `source_id`, so populate records
        `response_id` (and `question_text`) in the Source metadata for this lookup.

        `question` disambiguates: one respondent answers several questions, so the
        same `response_id` can map to multiple Sources. When the caller is
        question-scoped (the Lab always is), pass it — otherwise the first match by
        source_id order is returned, which is only safe when response_id is unique.
        """
        rows = self._conn.execute(
            "SELECT * FROM sources "
            "WHERE json_extract(metadata_json, '$.response_id') = ? "
            "ORDER BY source_id",
            (str(response_id),),
        ).fetchall()
        if not rows:
            return None
        if question is not None:
            for r in rows:
                meta = json.loads(r["metadata_json"] or "{}")
                if str(meta.get("question_text", "")) == str(question):
                    return self._row_to_source(r)
            return None
        return self._row_to_source(rows[0])

    def _row_to_source(self, r: sqlite3.Row) -> Source:
        return Source(
            source_id=r["source_id"], type=r["type"], raw_text=r["raw_text"],
            label=r["label"], metadata=json.loads(r["metadata_json"] or "{}"),
        )

    def delete_source(self, source_id: str) -> Dict[str, int]:
        """Delete a source and everything hanging off it. Returns removed counts.

        Foreign keys cascade excerpts -> applications, so the store side is nearly
        free. Deleting a Source must NEVER touch Codes: the codebook is shared
        analytical vocabulary that outlives any one respondent. (The FKs are set
        up correctly for this — a test asserts it, because someone will 'simplify'
        them someday.)
        """
        counts = self._erasure_counts(where_source_ids=[source_id])
        self._conn.execute("DELETE FROM sources WHERE source_id = ?", (source_id,))
        self._commit()
        return counts

    def delete_by_response_id(self, response_id: str) -> Dict[str, int]:
        """Delete every Source for a response_id (across all questions). Returns counts."""
        rows = self._conn.execute(
            "SELECT source_id FROM sources "
            "WHERE json_extract(metadata_json, '$.response_id') = ?",
            (str(response_id),),
        ).fetchall()
        source_ids = [r["source_id"] for r in rows]
        if not source_ids:
            return {"sources": 0, "excerpts": 0, "applications": 0, "descriptors": 0}
        counts = self._erasure_counts(where_source_ids=source_ids)
        placeholders = ",".join("?" for _ in source_ids)
        self._conn.execute(
            f"DELETE FROM sources WHERE source_id IN ({placeholders})", source_ids
        )
        self._commit()
        return counts

    def _erasure_counts(self, where_source_ids: List[str]) -> Dict[str, int]:
        """Count rows that a source deletion will cascade away, for the audit note."""
        if not where_source_ids:
            return {"sources": 0, "excerpts": 0, "applications": 0, "descriptors": 0}
        placeholders = ",".join("?" for _ in where_source_ids)
        exc = self._conn.execute(
            f"SELECT excerpt_id FROM excerpts WHERE source_id IN ({placeholders})",
            where_source_ids,
        ).fetchall()
        excerpt_ids = [r["excerpt_id"] for r in exc]
        app_count = 0
        if excerpt_ids:
            eph = ",".join("?" for _ in excerpt_ids)
            app_count = self._conn.execute(
                f"SELECT COUNT(*) AS n FROM code_applications WHERE excerpt_id IN ({eph})",
                excerpt_ids,
            ).fetchone()["n"]
        desc_count = self._conn.execute(
            f"SELECT COUNT(*) AS n FROM descriptors WHERE source_id IN ({placeholders})",
            where_source_ids,
        ).fetchone()["n"]
        return {
            "sources": len(where_source_ids),
            "excerpts": len(excerpt_ids),
            "applications": int(app_count),
            "descriptors": int(desc_count),
        }

    # ── excerpts ─────────────────────────────────────────────────────────────
    def add_excerpt(self, excerpt: Excerpt) -> str:
        eid = excerpt.excerpt_id or new_id("exc")
        self._conn.execute(
            "INSERT INTO excerpts(excerpt_id, source_id, text, char_start, char_end) "
            "VALUES (?, ?, ?, ?, ?)",
            (eid, excerpt.source_id, excerpt.text, excerpt.char_start, excerpt.char_end),
        )
        self._commit()
        return eid

    def add_whole_response_excerpt(self, source: Source, excerpt_id: str = "") -> str:
        """Convenience: create the default whole-response excerpt for a source."""
        exc = Excerpt(
            excerpt_id=excerpt_id or new_id("exc"), source_id=source.source_id,
            text=source.raw_text, char_start=0, char_end=len(source.raw_text),
        )
        return self.add_excerpt(exc)

    def add_sentence_excerpts(self, source: Source) -> List[str]:
        """Create one excerpt per sentence in the source (v4 sentence unitization).

        Returns the new excerpt ids in document order. Offsets come from the
        offline splitter, so each excerpt's text equals the exact source span.
        Falls back to a single whole-response excerpt when the text has no
        detectable sentence boundary (so a source always has at least one excerpt).
        """
        from core.text_units import split_sentences

        spans = split_sentences(source.raw_text)
        if not spans:
            return [self.add_whole_response_excerpt(source)]
        ids: List[str] = []
        for sentence, start, end in spans:
            ids.append(self.add_excerpt(Excerpt(
                excerpt_id=new_id("exc"), source_id=source.source_id,
                text=sentence, char_start=start, char_end=end)))
        return ids

    def list_excerpts(self, source_id: Optional[str] = None) -> List[Excerpt]:
        if source_id is None:
            rows = self._conn.execute("SELECT * FROM excerpts ORDER BY excerpt_id")
        else:
            rows = self._conn.execute(
                "SELECT * FROM excerpts WHERE source_id = ? ORDER BY excerpt_id", (source_id,)
            )
        return [
            Excerpt(excerpt_id=r["excerpt_id"], source_id=r["source_id"], text=r["text"],
                    char_start=r["char_start"], char_end=r["char_end"])
            for r in rows
        ]

    # ── codebook ─────────────────────────────────────────────────────────────
    def add_code(self, code: Code) -> str:
        cid = code.code_id or new_id("code")
        ws = code.weight_scale
        self._conn.execute(
            "INSERT INTO codes(code_id, name, definition, parent_id, origin, created_by, "
            "weight_kind, weight_min, weight_max, inclusion_criteria, exclusion_criteria, "
            "examples_json, decision_type, rubric_levels_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (cid, code.name, code.definition, code.parent_id, code.origin, code.created_by,
             ws.kind if ws else None, ws.min_value if ws else None, ws.max_value if ws else None,
             code.inclusion_criteria, code.exclusion_criteria, json.dumps(code.examples),
             code.decision_type,
             json.dumps(code.rubric_levels) if code.rubric_levels is not None else None),
        )
        self._event("code_created", f"Code created: {code.name}", target_type="code",
                    target_id=cid, detail={"origin": code.origin, "created_by": code.created_by,
                                           "definition": code.definition,
                                           "parent": self._code_name(code.parent_id)})
        self._commit()
        return cid

    def _row_to_code(self, r: sqlite3.Row) -> Code:
        ws = None
        if r["weight_kind"] is not None:
            ws = WeightScale(kind=r["weight_kind"], min_value=r["weight_min"], max_value=r["weight_max"])
        keys = r.keys()  # sqlite3.Row: absent on a pre-v7 SELECT * only if a caller bypasses _SCHEMA
        rubric_json = r["rubric_levels_json"] if "rubric_levels_json" in keys else None
        return Code(
            code_id=r["code_id"], name=r["name"], definition=r["definition"],
            parent_id=r["parent_id"], origin=r["origin"], created_by=r["created_by"],
            weight_scale=ws,
            inclusion_criteria=(r["inclusion_criteria"] if "inclusion_criteria" in keys else "") or "",
            exclusion_criteria=(r["exclusion_criteria"] if "exclusion_criteria" in keys else "") or "",
            examples=json.loads(r["examples_json"]) if ("examples_json" in keys and r["examples_json"]) else [],
            decision_type=(r["decision_type"] if "decision_type" in keys else "noul") or "noul",
            rubric_levels=json.loads(rubric_json) if rubric_json else None,
        )

    def set_code_structured_fields(
        self, code_id: str, *, inclusion_criteria: Optional[str] = None,
        exclusion_criteria: Optional[str] = None, examples: Optional[List[str]] = None,
        decision_type: Optional[CodeDecisionType] = None,
        rubric_levels: Optional[List[str]] = None,
    ) -> None:
        """Update a code's structured-coding fields. Only given fields change.

        Mirrors `set_code_definition` / `set_code_parent`: one narrow setter per
        concern rather than a single wide "update_code" that invites callers to
        pass a half-built Code and silently blank fields they didn't mean to.
        """
        sets, params = [], []
        if inclusion_criteria is not None:
            sets.append("inclusion_criteria = ?"); params.append(inclusion_criteria)
        if exclusion_criteria is not None:
            sets.append("exclusion_criteria = ?"); params.append(exclusion_criteria)
        if examples is not None:
            sets.append("examples_json = ?"); params.append(json.dumps(examples))
        if decision_type is not None:
            if decision_type not in ("noul", "score"):
                raise ValueError(f"decision_type must be 'noul' or 'score', got {decision_type!r}")
            sets.append("decision_type = ?"); params.append(decision_type)
        if rubric_levels is not None:
            sets.append("rubric_levels_json = ?"); params.append(json.dumps(rubric_levels))
        if not sets:
            return
        params.append(code_id)
        self._conn.execute(f"UPDATE codes SET {', '.join(sets)} WHERE code_id = ?", params)
        # Examples are often responses pasted in verbatim, so the log records
        # how many, never the text (the event log carries no response text).
        changed = {k: v for k, v in (("inclusion_criteria", inclusion_criteria),
                                     ("exclusion_criteria", exclusion_criteria),
                                     ("examples", None if examples is None
                                      else f"{len(examples)} example(s)"),
                                     ("decision_type", decision_type),
                                     ("rubric_levels", rubric_levels)) if v is not None}
        self._event("code_criteria_changed",
                    f"Coding rules changed for {self._code_name(code_id)}: {', '.join(changed)}",
                    target_type="code", target_id=code_id, detail=changed)
        self._commit()

    def get_codebook(self) -> List[Code]:
        return [self._row_to_code(r) for r in self._conn.execute("SELECT * FROM codes ORDER BY code_id")]

    def get_excerpt(self, excerpt_id: str) -> Optional[Excerpt]:
        row = self._conn.execute("SELECT * FROM excerpts WHERE excerpt_id = ?", (excerpt_id,)).fetchone()
        if row is None:
            return None
        return Excerpt(excerpt_id=row["excerpt_id"], source_id=row["source_id"], text=row["text"],
                       char_start=row["char_start"], char_end=row["char_end"])

    # ── the event log (store format v9) ──────────────────────────────────────
    def _event(self, kind: str, summary: str, *, target_type: str = "", target_id: str = "",
               detail: Optional[Dict[str, Any]] = None, actor: Optional[str] = None) -> str:
        """Insert one event without committing (the caller owns the transaction)."""
        eid = new_id("evt")
        self._conn.execute(
            "INSERT INTO project_events(event_id, at, actor, kind, target_type, target_id, "
            "summary, detail_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (eid, datetime.now().isoformat(timespec="seconds"),
             self.actor if actor is None else actor, kind, target_type, target_id or "",
             summary, json.dumps(detail or {}, sort_keys=True)))
        return eid

    def log_event(self, kind: str, summary: str, **kwargs: Any) -> str:
        """Record an analytic decision made outside this class (an import, a
        merge, an adjudication, an erasure). Never pass response text or ids."""
        eid = self._event(kind, summary, **kwargs)
        self._commit()
        return eid

    def list_events(self) -> List[Dict[str, Any]]:
        """Every event, oldest first."""
        return [{**dict(r), "detail": json.loads(r["detail_json"] or "{}")}
                for r in self._conn.execute(
                    "SELECT * FROM project_events ORDER BY at, rowid")]

    def _code_name(self, code_id: Optional[str]) -> str:
        if not code_id:
            return ""
        row = self._conn.execute("SELECT name FROM codes WHERE code_id = ?", (code_id,)).fetchone()
        return row["name"] if row else code_id

    # ── codebook editing (human owns the codebook) ──────────────────────────
    def rename_code(self, code_id: str, name: str) -> None:
        old = self._code_name(code_id)
        self._conn.execute("UPDATE codes SET name = ? WHERE code_id = ?", (name, code_id))
        if old != name:
            self._event("code_renamed", f"Code renamed: {old} -> {name}", target_type="code",
                        target_id=code_id, detail={"from": old, "to": name})
        self._commit()

    def set_code_definition(self, code_id: str, definition: str) -> None:
        row = self._conn.execute("SELECT definition FROM codes WHERE code_id = ?",
                                 (code_id,)).fetchone()
        old = (row["definition"] if row else "") or ""
        self._conn.execute("UPDATE codes SET definition = ? WHERE code_id = ?", (definition, code_id))
        if old != definition:
            # A changed decision rule is what an auditor most wants to see, and
            # before v9 it left no dated trace at all.
            self._event("code_redefined", f"Definition changed: {self._code_name(code_id)}",
                        target_type="code", target_id=code_id,
                        detail={"from": old, "to": definition})
        self._commit()

    def set_code_parent(self, code_id: str, parent_id: Optional[str]) -> None:
        """Reparent a code, rejecting moves that would create a cycle."""
        if parent_id == code_id:
            raise ValueError("A code cannot be its own parent.")
        if parent_id is not None:
            from core.model import ancestors
            codes = {c.code_id: c for c in self.get_codebook()}
            if code_id in ancestors(parent_id, codes):
                raise ValueError("That move would create a cycle in the codebook.")
        with self._conn:  # snapshot + mutation atomic: a crash can't lose the undo state
            self._snapshot_codebook(trigger="reparent")
            self._event("code_moved",
                        f"Code moved: {self._code_name(code_id)} under "
                        f"{self._code_name(parent_id) or '(top level)'}",
                        target_type="code", target_id=code_id,
                        detail={"parent": self._code_name(parent_id)})
            self._conn.execute("UPDATE codes SET parent_id = ? WHERE code_id = ?", (parent_id, code_id))

    def merge_codes(self, from_id: str, into_id: str) -> None:
        """Merge `from_id` into `into_id`: reassign its applications, reparent its
        children, re-target its memos, then delete it. The analyst's split/merge
        decision.

        Re-targeting memos matters: a memo attached to the merged-away code would
        otherwise dangle (its target_id points at a deleted code), losing the
        analyst's note about that theme. It moves to the surviving code.

        A codebook snapshot is taken first (same transaction) so the merge is
        undoable.
        """
        if from_id == into_id:
            raise ValueError("Cannot merge a code into itself.")
        with self._conn:  # snapshot BEFORE the mutation, in one transaction
            self._snapshot_codebook(trigger="merge")
            moved = self._conn.execute(
                "SELECT COUNT(*) FROM code_applications WHERE code_id = ?", (from_id,)).fetchone()[0]
            self._event("codes_merged",
                        f"Codes merged: {self._code_name(from_id)} into {self._code_name(into_id)}",
                        target_type="code", target_id=into_id,
                        detail={"from": self._code_name(from_id), "into": self._code_name(into_id),
                                "codings_moved": int(moved)})
            self._conn.execute("UPDATE code_applications SET code_id = ? WHERE code_id = ?", (into_id, from_id))
            self._conn.execute("UPDATE codes SET parent_id = ? WHERE parent_id = ?", (into_id, from_id))
            self._conn.execute(
                "UPDATE memos SET target_id = ? WHERE target_type = 'code' AND target_id = ?",
                (into_id, from_id))
            self._conn.execute("DELETE FROM codes WHERE code_id = ?", (from_id,))

    def delete_code(self, code_id: str) -> None:
        """Delete a code (its applications cascade; children's parent is nulled)."""
        with self._conn:
            self._snapshot_codebook(trigger="delete")
            lost = self._conn.execute(
                "SELECT COUNT(*) FROM code_applications WHERE code_id = ?", (code_id,)).fetchone()[0]
            self._event("code_deleted", f"Code deleted: {self._code_name(code_id)}",
                        target_type="code", target_id=code_id,
                        detail={"codings_removed": int(lost)})
            self._conn.execute("DELETE FROM codes WHERE code_id = ?", (code_id,))

    # ── codebook snapshots (v4) ──────────────────────────────────────────────
    def _snapshot_codebook(self, *, note: str = "", trigger: str = "") -> str:
        """Write the current codebook to codebook_versions. Returns version_id.

        Called inside a mutation's transaction so the snapshot and the change that
        follows commit together — a crash between them can't leave the store
        without the pre-change state to roll back to. Must NOT commit (the caller's
        `with self._conn:` owns the transaction).
        """
        codes = [dict(r) for r in self._conn.execute("SELECT * FROM codes ORDER BY code_id")]
        snapshot = json.dumps(codes, sort_keys=True)
        codebook_hash = hashlib.sha256(snapshot.encode("utf-8")).hexdigest()[:16]
        self._conn.execute(
            "INSERT INTO codebook_versions(version_id, created_at, note, trigger, "
            "codebook_hash, snapshot_json) VALUES (?, ?, ?, ?, ?, ?)",
            (new_id("cbv"), datetime.now().isoformat(timespec="seconds"), note, trigger,
             codebook_hash, snapshot),
        )
        return codebook_hash

    def tag_codebook_version(self, note: str) -> str:
        """Manually snapshot the codebook with a note. Returns the codebook hash."""
        with self._conn:
            self._event("codebook_tagged", f"Codebook version tagged: {note}",
                        target_type="codebook", detail={"note": note})
            return self._snapshot_codebook(note=note, trigger="manual")

    def codebook_hash(self) -> str:
        """Deterministic hash of the current codebook (recorded in run manifests)."""
        codes = [dict(r) for r in self._conn.execute("SELECT * FROM codes ORDER BY code_id")]
        return hashlib.sha256(json.dumps(codes, sort_keys=True).encode("utf-8")).hexdigest()[:16]

    def list_codebook_versions(self) -> List[Dict[str, Any]]:
        """Snapshot history, newest first (metadata only, not the full snapshot)."""
        return [
            {"version_id": r["version_id"], "created_at": r["created_at"],
             "note": r["note"], "trigger": r["trigger"], "codebook_hash": r["codebook_hash"]}
            for r in self._conn.execute(
                "SELECT * FROM codebook_versions ORDER BY created_at DESC, version_id DESC")
        ]

    def restore_codebook_version(self, version_id: str) -> None:
        """Restore the codebook to a snapshot, preserving applications where possible.

        Diff-based, NOT delete-all: a blanket `DELETE FROM codes` would cascade
        away every code application (FK ON DELETE CASCADE), wiping the coding for
        codes that the snapshot actually keeps. Instead:
          - codes in the snapshot but now missing → re-inserted;
          - codes present now but not in the snapshot → deleted (their apps cascade,
            which is correct — the snapshot predates them);
          - codes in both → fields updated to the snapshot's, applications intact.
        Snapshots the current state first, so a restore is itself undoable.
        """
        row = self._conn.execute(
            "SELECT snapshot_json FROM codebook_versions WHERE version_id = ?", (version_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"No codebook version {version_id}")
        snapshot = json.loads(row["snapshot_json"])
        snap_by_id = {c["code_id"]: c for c in snapshot}

        with self._conn:
            self._snapshot_codebook(trigger="pre_restore")
            self._event("codebook_restored", f"Codebook restored to version {version_id}",
                        target_type="codebook_version", target_id=version_id)
            current_ids = {r["code_id"] for r in self._conn.execute("SELECT code_id FROM codes")}
            # Remove codes not in the snapshot (their applications cascade away).
            for code_id in current_ids - set(snap_by_id):
                self._conn.execute("DELETE FROM codes WHERE code_id = ?", (code_id,))
            # Upsert every snapshot code (insert missing, update existing in place).
            for code in snapshot:
                cols = list(code.keys())
                placeholders = ", ".join("?" for _ in cols)
                updates = ", ".join(f"{c}=excluded.{c}" for c in cols if c != "code_id")
                self._conn.execute(
                    f"INSERT INTO codes({', '.join(cols)}) VALUES ({placeholders}) "
                    f"ON CONFLICT(code_id) DO UPDATE SET {updates}",
                    tuple(code[c] for c in cols))

    # ── code applications ────────────────────────────────────────────────────
    def apply_code(self, app: CodeApplication) -> str:
        aid = app.application_id or new_id("app")
        self._conn.execute(
            "INSERT INTO code_applications(application_id, excerpt_id, code_id, coder, "
            "rater_id, run_id, weight, confidence, margin, rationale) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (aid, app.excerpt_id, app.code_id, app.coder, app.rater_id, app.run_id,
             app.weight, app.confidence, app.margin, app.rationale),
        )
        self._commit()
        return aid

    def delete_application(self, application_id: str) -> None:
        """Remove one code application. Used to undo auto-coding (v4, Phase 1.4).

        Deliberately narrow: it removes the *application*, never the excerpt or
        the code — another rater may have coded the same span, and the codebook
        outlives any one coding decision.
        """
        self._conn.execute(
            "DELETE FROM code_applications WHERE application_id = ?", (application_id,))
        self._commit()

    def list_applications(self) -> List[CodeApplication]:
        return [
            CodeApplication(
                application_id=r["application_id"], excerpt_id=r["excerpt_id"], code_id=r["code_id"],
                coder=r["coder"], rater_id=r["rater_id"], run_id=r["run_id"], weight=r["weight"],
                confidence=r["confidence"], margin=r["margin"], rationale=r["rationale"])
            for r in self._conn.execute("SELECT * FROM code_applications ORDER BY application_id")
        ]

    def replace_applications_for_rater(
        self, rater_id: str, excerpt_ids: List[str], applications: List[CodeApplication],
        *, run_id: Optional[str] = None, record_review: bool = True,
    ) -> Dict[str, int]:
        """Replace one rater's applications on a set of excerpts, atomically.

        Re-saving a coding sample must overwrite that rater's prior codes on those
        excerpts, not pile new ones on top — otherwise recoding a response from
        [A] to [B] leaves both, and every downstream count double-reports. So:
        delete this rater's applications on these excerpts, then insert the new
        set, in one transaction. Other raters' codes on the same excerpts (the
        model's, a second human's) are untouched.

        Every excerpt in `excerpt_ids` is also recorded as *reviewed* by this
        rater (store format v8), including those with no applications: that is
        how "no code applies" reaches the agreement tables. Pass
        `record_review=False` only when copying codings whose review record is
        unknown (a pre-v8 project being merged): recording one there would
        claim reviews nobody made.

        Returns ``{"deleted", "inserted"}``.
        """
        if not excerpt_ids:
            excerpt_ids = []
        with self._conn:  # one transaction: never leave a half-replaced rater
            deleted = 0
            if excerpt_ids:
                placeholders = ",".join("?" for _ in excerpt_ids)
                cur = self._conn.execute(
                    f"DELETE FROM code_applications "
                    f"WHERE rater_id = ? AND excerpt_id IN ({placeholders})",
                    [rater_id, *excerpt_ids],
                )
                deleted = cur.rowcount if cur.rowcount is not None else 0
            for app in applications:
                self._conn.execute(
                    "INSERT INTO code_applications(application_id, excerpt_id, code_id, coder, "
                    "rater_id, run_id, weight, confidence, margin, rationale) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (app.application_id or new_id("app"), app.excerpt_id, app.code_id, app.coder,
                     app.rater_id, app.run_id, app.weight, app.confidence, app.margin, app.rationale),
                )
            if record_review:
                self._record_coverage_rows(rater_id, excerpt_ids, run_id)
        return {"deleted": int(deleted), "inserted": len(applications)}

    def find_code_by_name(self, name: str) -> Optional[Code]:
        """Return the first code with this exact name, or None.

        Additive populate and human coding both match codes by name so a label
        that already exists ("Barriers") is applied to rather than duplicated.
        """
        row = self._conn.execute(
            "SELECT * FROM codes WHERE name = ? ORDER BY code_id LIMIT 1", (name,)
        ).fetchone()
        return self._row_to_code(row) if row is not None else None

    def rater_labels(self, rater_id: str) -> Dict[str, set]:
        """Return {excerpt_id: set(code_name)} over the excerpts this rater reviewed.

        The shape `analysis.agreement.per_code_kappa` consumes directly. An
        excerpt the rater reviewed and left uncoded is present with an empty
        set -- "no code applies" is an answer, and dropping it removes exactly
        the items where two coders disagree (review finding F1). See
        `rater_item_set` for how a rater with no review record is handled.
        """
        return self.rater_item_set(rater_id).labels

    def rater_item_set(self, rater_id: str) -> "RaterItemSet":
        """The items a rater judged, and whether that set was recorded or inferred.

        * **Recorded** (store format v8+): the excerpts in `rater_coverage` for
          this rater, each with the codes applied -- empty where none were.
          Survey excerpts this rater coded *before* reviews were recorded are
          left out and counted in `uncovered_applied`, because treating them as
          complete reviews would recreate the defect the record exists to fix.
        * **Inferred** (no review record for this rater -- a project coded
          before v8): the excerpts with at least one application. Responses the
          rater left uncoded are missing, so agreement computed from it is
          likely overstated; callers must say so (`core.agreement_pairs`).
        """
        applied: Dict[str, set] = {}
        for r in self._conn.execute(
            "SELECT a.excerpt_id, c.name AS code_name "
            "FROM code_applications a JOIN codes c ON a.code_id = c.code_id "
            "WHERE a.rater_id = ?",
            (rater_id,),
        ):
            applied.setdefault(r["excerpt_id"], set()).add(r["code_name"])
        covered = self.coverage_excerpt_ids(rater_id)
        if not covered:
            return RaterItemSet(labels=applied, recorded=False, uncovered_applied=0)
        labels = {e: set(applied.get(e, set())) for e in covered}
        uncovered = set(applied) - covered
        if uncovered:
            placeholders = ",".join("?" for _ in uncovered)
            # Span codings on documents are compared by unit (span_comparison),
            # not per excerpt, so they are not "missing reviews" here.
            uncovered = {r["excerpt_id"] for r in self._conn.execute(
                f"SELECT e.excerpt_id FROM excerpts e JOIN sources s ON e.source_id = s.source_id "
                f"WHERE e.excerpt_id IN ({placeholders}) AND s.type != 'document'",
                list(uncovered))}
        return RaterItemSet(labels=labels, recorded=True, uncovered_applied=len(uncovered))

    # ── review record (store format v8) ──────────────────────────────────────
    def _record_coverage_rows(self, rater_id: str, excerpt_ids: Sequence[str],
                              run_id: Optional[str] = None) -> None:
        stamp = datetime.now().isoformat(timespec="seconds")
        self._conn.executemany(
            "INSERT INTO rater_coverage(rater_id, excerpt_id, run_id, reviewed_at) "
            "VALUES (?, ?, ?, ?) ON CONFLICT(rater_id, excerpt_id) DO UPDATE SET "
            "run_id = excluded.run_id, reviewed_at = excluded.reviewed_at",
            [(rater_id, e, run_id, stamp) for e in dict.fromkeys(excerpt_ids)])

    def record_coverage(self, rater_id: str, excerpt_ids: Sequence[str],
                        run_id: Optional[str] = None) -> None:
        """Record that `rater_id` gave a complete coding of each excerpt.

        Idempotent. Write it for every excerpt a rater judged, including the
        ones they applied no code to. Do not write it for a partial judgement
        (one code confirmed in a review queue): that would claim every other
        code was judged absent.
        """
        self._record_coverage_rows(rater_id, excerpt_ids, run_id)
        self._commit()

    def coverage_excerpt_ids(self, rater_id: str) -> set:
        return {r["excerpt_id"] for r in self._conn.execute(
            "SELECT excerpt_id FROM rater_coverage WHERE rater_id = ?", (rater_id,))}

    def mark_document_coded(self, rater_id: str, source_id: str, coded: bool = True) -> None:
        """Mark (or unmark) a document as fully coded by `rater_id`.

        Span-coding agreement compares only documents both coders marked: an
        unfinished document's uncoded sentences would otherwise count as "no
        code applies".
        """
        if coded:
            self._conn.execute(
                "INSERT INTO document_coverage(rater_id, source_id, marked_at) VALUES (?, ?, ?) "
                "ON CONFLICT(rater_id, source_id) DO UPDATE SET marked_at = excluded.marked_at",
                (rater_id, source_id, datetime.now().isoformat(timespec="seconds")))
        else:
            self._conn.execute(
                "DELETE FROM document_coverage WHERE rater_id = ? AND source_id = ?",
                (rater_id, source_id))
        self._commit()

    def documents_coded_by(self, rater_id: str) -> set:
        return {r["source_id"] for r in self._conn.execute(
            "SELECT source_id FROM document_coverage WHERE rater_id = ?", (rater_id,))}

    def rater_run_order(self) -> Dict[str, tuple]:
        """{rater_id: (latest run timestamp, latest run insertion order)}.

        Every pipeline run registers its own engine rater, so "the engine" means
        the most recent run's. Timestamps have one-second resolution; the run's
        insertion order breaks ties.
        """
        rows = self._conn.execute(
            "SELECT x.rater_id, MAX(COALESCE(r.timestamp, '')) AS ts, MAX(r.rowid) AS rn "
            "FROM (SELECT rater_id, run_id FROM code_applications "
            "      UNION SELECT rater_id, run_id FROM rater_coverage) x "
            "JOIN runs r ON r.run_id = x.run_id "
            "WHERE x.rater_id IS NOT NULL GROUP BY x.rater_id")
        return {r["rater_id"]: (r["ts"] or "", r["rn"] or -1) for r in rows}

    def run_ids_for_rater(self, rater_id: str) -> set:
        """Every run id this rater applied a code or recorded a review under."""
        return {r["run_id"] for r in self._conn.execute(
            "SELECT run_id FROM code_applications WHERE rater_id = ? "
            "UNION SELECT run_id FROM rater_coverage WHERE rater_id = ?",
            (rater_id, rater_id)) if r["run_id"]}

    def delete_coding_decisions(self, run_id: str) -> int:
        """Remove a structured-coding run's audit trail (Alt Survey Flow)."""
        cur = self._conn.execute("DELETE FROM coding_decisions WHERE run_id = ?", (run_id,))
        self._commit()
        return cur.rowcount or 0

    def delete_rater(self, rater_id: str) -> Dict[str, int]:
        """Remove every application and review record of one rater, and the rater.

        For discarding a whole coder's output (a demo engine run). Excerpts and
        codes stay: other raters may use them.
        """
        with self._conn:
            apps = self._conn.execute(
                "DELETE FROM code_applications WHERE rater_id = ?", (rater_id,)).rowcount
            cov = self._conn.execute(
                "DELETE FROM rater_coverage WHERE rater_id = ?", (rater_id,)).rowcount
            self._conn.execute("DELETE FROM document_coverage WHERE rater_id = ?", (rater_id,))
            self._conn.execute("DELETE FROM raters WHERE rater_id = ?", (rater_id,))
        return {"applications": apps or 0, "coverage": cov or 0}

    def rater_ids(self) -> List[str]:
        """Distinct rater_ids that have applied at least one code."""
        return [r["rater_id"] for r in self._conn.execute(
            "SELECT DISTINCT rater_id FROM code_applications "
            "WHERE rater_id IS NOT NULL ORDER BY rater_id")]

    def code_frequency(self) -> Dict[str, int]:
        """Count code applications per code_id (basis for Phase 3 frequency)."""
        rows = self._conn.execute(
            "SELECT code_id, COUNT(*) AS n FROM code_applications GROUP BY code_id"
        )
        return {r["code_id"]: r["n"] for r in rows}

    # ── analytical views (feed the pure functions in analysis/) ──────────────
    def coding_table(self) -> pd.DataFrame:
        """One row per code application, joined to its excerpt's source and code
        name — the input to analysis.frequency / cooccurrence / crosstab.

        Includes `respondent_id` (from the source metadata, wide-form ingestion) so
        co-occurrence can be grouped at the respondent level (Feature B).
        """
        cols = ["application_id", "excerpt_id", "source_id", "code_id", "code_name",
                "weight", "confidence", "coder", "rater_id", "run_id", "respondent_id"]
        rows = self._conn.execute(
            "SELECT a.application_id, a.excerpt_id, e.source_id, a.code_id, "
            "c.name AS code_name, a.weight, a.confidence, a.coder, a.rater_id, a.run_id, "
            "json_extract(s.metadata_json, '$.respondent_id') AS respondent_id "
            "FROM code_applications a "
            "JOIN excerpts e ON a.excerpt_id = e.excerpt_id "
            "JOIN codes c ON a.code_id = c.code_id "
            "JOIN sources s ON e.source_id = s.source_id"
        ).fetchall()
        return pd.DataFrame([dict(r) for r in rows], columns=cols)

    def coding_spans_table(self) -> pd.DataFrame:
        """`coding_table()` plus each excerpt's character span and its source's cases.

        A separate method rather than columns on `coding_table()`, which many
        callers already consume. Proximity queries ("Cost NEAR/50 dropout") need
        offsets, and case-level queries need the case membership, so both are
        joined here once.

        A source in two cases produces one row per case; a source in none keeps a
        single row with an empty `case_id`.
        """
        cols = ["application_id", "excerpt_id", "source_id", "code_id", "code_name",
                "char_start", "char_end", "coder", "rater_id", "run_id",
                "respondent_id", "case_id", "case_name"]
        rows = self._conn.execute(
            "SELECT a.application_id, a.excerpt_id, e.source_id, a.code_id, "
            "c.name AS code_name, e.char_start, e.char_end, a.coder, a.rater_id, "
            "a.run_id, json_extract(s.metadata_json, '$.respondent_id') AS respondent_id, "
            "cm.case_id AS case_id, k.name AS case_name "
            "FROM code_applications a "
            "JOIN excerpts e ON a.excerpt_id = e.excerpt_id "
            "JOIN codes c ON a.code_id = c.code_id "
            "JOIN sources s ON e.source_id = s.source_id "
            "LEFT JOIN case_membership cm ON cm.source_id = s.source_id "
            "LEFT JOIN cases k ON k.case_id = cm.case_id"
        ).fetchall()
        frame = pd.DataFrame([dict(r) for r in rows], columns=cols)
        for col in ("case_id", "case_name", "respondent_id"):
            frame[col] = frame[col].fillna("")
        return frame

    def sources_by_respondent(self) -> Dict[str, List[Source]]:
        """Group sources by respondent_id (wide-form). Sources without one are
        keyed by their own source_id, so long-format data degrades gracefully."""
        out: Dict[str, List[Source]] = {}
        for src in self.list_sources():
            rid = str(src.metadata.get("respondent_id") or src.source_id)
            out.setdefault(rid, []).append(src)
        return out

    def descriptor_table(self) -> pd.DataFrame:
        """Long descriptor table [source_id, key, value] for cross-tabs."""
        rows = self._conn.execute("SELECT source_id, key, value FROM descriptors").fetchall()
        return pd.DataFrame([dict(r) for r in rows], columns=["source_id", "key", "value"])

    # ── descriptors ──────────────────────────────────────────────────────────
    def set_descriptor(self, descriptor: Descriptor) -> None:
        self._conn.execute(
            "INSERT INTO descriptors(source_id, key, value) VALUES (?, ?, ?) "
            "ON CONFLICT(source_id, key) DO UPDATE SET value = excluded.value",
            (descriptor.source_id, descriptor.key, descriptor.value),
        )
        self._commit()

    def get_descriptors(self, source_id: str) -> Dict[str, str]:
        rows = self._conn.execute(
            "SELECT key, value FROM descriptors WHERE source_id = ?", (source_id,)
        )
        return {r["key"]: r["value"] for r in rows}

    def add_descriptor_field(self, field: DescriptorField) -> None:
        self._conn.execute(
            "INSERT INTO descriptor_fields(key, dtype, ordered_levels_json, description) "
            "VALUES (?, ?, ?, ?) ON CONFLICT(key) DO UPDATE SET "
            "dtype = excluded.dtype, ordered_levels_json = excluded.ordered_levels_json, "
            "description = excluded.description",
            (field.key, field.dtype,
             json.dumps(field.ordered_levels) if field.ordered_levels is not None else None,
             field.description),
        )
        self._commit()

    # ── corpus access (v4): paginated reads + cases / annotations / links ────
    def count_sources(self, source_type: Optional[str] = None) -> int:
        """How many sources (optionally of one type). Cheap; no text loaded."""
        if source_type is None:
            row = self._conn.execute("SELECT COUNT(*) AS n FROM sources").fetchone()
        else:
            row = self._conn.execute(
                "SELECT COUNT(*) AS n FROM sources WHERE type = ?", (source_type,)
            ).fetchone()
        return int(row["n"])

    def iter_sources(
        self, *, source_type: Optional[str] = None,
        limit: int = 100, offset: int = 0, order: str = "source_id",
    ) -> List[Source]:
        """A page of sources, ordered by source_id (or, with `order="entered"`, the order
        they were added, which for a survey is the order of the spreadsheet).

        `list_sources()` loads the whole corpus, which is fine for a survey run
        and wrong for hundreds of documents — every caller that renders a list
        should page instead (v4, Phase 0.3).
        """
        by = "rowid" if order == "entered" else "source_id"
        if source_type is None:
            rows = self._conn.execute(
                f"SELECT * FROM sources ORDER BY {by} LIMIT ? OFFSET ?",
                (int(limit), int(offset)),
            )
        else:
            rows = self._conn.execute(
                f"SELECT * FROM sources WHERE type = ? ORDER BY {by} LIMIT ? OFFSET ?",
                (source_type, int(limit), int(offset)),
            )
        return [self._row_to_source(r) for r in rows]

    def source_types(self) -> List[str]:
        """Distinct source types present (survey_response / interview / document)."""
        return [r["type"] for r in self._conn.execute(
            "SELECT DISTINCT type FROM sources ORDER BY type")]

    # cases ------------------------------------------------------------------
    def add_case(self, case: "Case") -> str:
        cid = case.case_id or new_id("case")
        self._conn.execute(
            "INSERT INTO cases(case_id, name, kind, description) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(case_id) DO UPDATE SET name = excluded.name, "
            "kind = excluded.kind, description = excluded.description",
            (cid, case.name, case.kind, case.description),
        )
        self._commit()
        return cid

    def list_cases(self) -> List["Case"]:
        from core.model import Case
        return [Case(case_id=r["case_id"], name=r["name"], kind=r["kind"],
                     description=r["description"])
                for r in self._conn.execute("SELECT * FROM cases ORDER BY name")]

    def assign_source_to_case(self, case_id: str, source_id: str) -> None:
        """Attach a source to a case. Idempotent."""
        self._conn.execute(
            "INSERT OR IGNORE INTO case_membership(case_id, source_id) VALUES (?, ?)",
            (case_id, source_id),
        )
        self._commit()

    def case_sources(self, case_id: str) -> List[str]:
        return [r["source_id"] for r in self._conn.execute(
            "SELECT source_id FROM case_membership WHERE case_id = ? ORDER BY source_id",
            (case_id,))]

    def source_cases(self, source_id: str) -> List[str]:
        return [r["case_id"] for r in self._conn.execute(
            "SELECT case_id FROM case_membership WHERE source_id = ? ORDER BY case_id",
            (source_id,))]

    # annotations & links ----------------------------------------------------
    def add_annotation(self, annotation: "Annotation") -> str:
        aid = annotation.annotation_id or new_id("ann")
        created = annotation.created_at or datetime.now().isoformat(timespec="seconds")
        self._conn.execute(
            "INSERT INTO annotations(annotation_id, excerpt_id, text, author, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (aid, annotation.excerpt_id, annotation.text, annotation.author, created),
        )
        self._commit()
        return aid

    def list_annotations(self, excerpt_id: Optional[str] = None) -> List["Annotation"]:
        from core.model import Annotation
        if excerpt_id is None:
            rows = self._conn.execute("SELECT * FROM annotations ORDER BY created_at")
        else:
            rows = self._conn.execute(
                "SELECT * FROM annotations WHERE excerpt_id = ? ORDER BY created_at",
                (excerpt_id,))
        return [Annotation(annotation_id=r["annotation_id"], excerpt_id=r["excerpt_id"],
                           text=r["text"], author=r["author"], created_at=r["created_at"])
                for r in rows]

    def delete_annotation(self, annotation_id: str) -> None:
        self._conn.execute("DELETE FROM annotations WHERE annotation_id = ?", (annotation_id,))
        self._commit()

    def add_excerpt_link(self, link: "ExcerptLink") -> str:
        lid = link.link_id or new_id("lnk")
        self._conn.execute(
            "INSERT INTO excerpt_links(link_id, from_excerpt, to_excerpt, kind, note) "
            "VALUES (?, ?, ?, ?, ?)",
            (lid, link.from_excerpt, link.to_excerpt, link.kind, link.note),
        )
        self._commit()
        return lid

    def list_excerpt_links(self, excerpt_id: Optional[str] = None) -> List["ExcerptLink"]:
        from core.model import ExcerptLink
        if excerpt_id is None:
            rows = self._conn.execute("SELECT * FROM excerpt_links ORDER BY link_id")
        else:
            rows = self._conn.execute(
                "SELECT * FROM excerpt_links WHERE from_excerpt = ? OR to_excerpt = ? "
                "ORDER BY link_id", (excerpt_id, excerpt_id))
        return [ExcerptLink(link_id=r["link_id"], from_excerpt=r["from_excerpt"],
                            to_excerpt=r["to_excerpt"], kind=r["kind"], note=r["note"])
                for r in rows]

    # full-text -------------------------------------------------------------
    def fts_match_source_ids(self, query: str, limit: int = 500) -> List[str]:
        """Source ids whose text matches an FTS5 query, best matches first.

        Raises ValueError on malformed FTS syntax (an unbalanced quote is a user
        typo, not a crash). Returns [] when FTS5 is unavailable — callers fall
        back to scanning, see `core/search.py`.
        """
        if not self.fts_available():
            return []
        try:
            rows = self._conn.execute(
                "SELECT s.source_id FROM sources_fts f "
                "JOIN sources s ON s.rowid = f.rowid "
                "WHERE sources_fts MATCH ? ORDER BY rank LIMIT ?",
                (query, int(limit)),
            ).fetchall()
        except sqlite3.OperationalError as exc:
            raise ValueError(f"Invalid search syntax: {exc}") from exc
        return [r["source_id"] for r in rows]

    def get_descriptor_fields(self) -> List[DescriptorField]:
        return [
            DescriptorField(
                key=r["key"], dtype=r["dtype"],
                ordered_levels=json.loads(r["ordered_levels_json"]) if r["ordered_levels_json"] else None,
                description=r["description"])
            for r in self._conn.execute("SELECT * FROM descriptor_fields ORDER BY key")
        ]

    # ── saved charts ─────────────────────────────────────────────────────────
    #
    # A chart is saved by name and replaced on re-save, deliberately. An analyst
    # who tweaks "Themes by class year" and saves it again means *that* chart,
    # not a second one an inch away from the first; a list of near-duplicates is
    # how a saved-view feature stops being used.

    def save_chart(self, chart: SavedChart) -> str:
        """Insert or replace a chart definition. Returns its id."""
        existing = self._conn.execute(
            "SELECT chart_id FROM saved_charts WHERE name = ?", (chart.name,)
        ).fetchone()
        chart_id = chart.chart_id or (existing["chart_id"] if existing else new_id("chart"))
        self._conn.execute(
            "INSERT INTO saved_charts(chart_id, name, spec_json, source, created_by, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(name) DO UPDATE SET spec_json = excluded.spec_json, "
            "source = excluded.source, created_by = excluded.created_by, "
            "created_at = excluded.created_at",
            (chart_id, chart.name, json.dumps(chart.spec), chart.source,
             chart.created_by, chart.created_at or datetime.now().isoformat(timespec="seconds")),
        )
        self._commit()
        return chart_id

    def list_charts(self) -> List[SavedChart]:
        """Every saved chart, by name."""
        return [
            SavedChart(chart_id=r["chart_id"], name=r["name"],
                       spec=json.loads(r["spec_json"] or "{}"), source=r["source"],
                       created_by=r["created_by"], created_at=r["created_at"])
            for r in self._conn.execute("SELECT * FROM saved_charts ORDER BY name")
        ]

    def get_chart(self, name: str) -> Optional[SavedChart]:
        row = self._conn.execute(
            "SELECT * FROM saved_charts WHERE name = ?", (name,)).fetchone()
        if row is None:
            return None
        return SavedChart(chart_id=row["chart_id"], name=row["name"],
                          spec=json.loads(row["spec_json"] or "{}"),
                          source=row["source"], created_by=row["created_by"],
                          created_at=row["created_at"])

    def delete_chart(self, name: str) -> bool:
        """Remove a saved chart. True if one was there."""
        cursor = self._conn.execute("DELETE FROM saved_charts WHERE name = ?", (name,))
        self._commit()
        return cursor.rowcount > 0

    # ── memos ────────────────────────────────────────────────────────────────
    def add_memo(self, memo: Memo) -> str:
        mid = memo.memo_id or new_id("memo")
        now = datetime.now().isoformat(timespec="seconds")
        self._conn.execute(
            "INSERT INTO memos(memo_id, target_type, target_id, text, author, created_at, "
            "updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (mid, memo.target_type, memo.target_id, memo.text, memo.author, now, now),
        )
        self._event("memo_added", f"Memo added ({self._memo_target(memo.target_type, memo.target_id)})",
                    target_type="memo", target_id=mid, detail={"author": memo.author})
        self._commit()
        return mid

    def _memo_target(self, target_type: str, target_id: Optional[str]) -> str:
        if target_type == "code":
            return f"code {self._code_name(target_id)}"
        return target_type if not target_id else f"{target_type} {target_id}"

    def list_memos(self, target_type: Optional[str] = None,
                   target_id: Optional[str] = None) -> List[Memo]:
        """List memos, optionally filtered to a target (code, view, project)."""
        query = "SELECT * FROM memos"
        params: List[Any] = []
        clauses = []
        if target_type is not None:
            clauses.append("target_type = ?")
            params.append(target_type)
        if target_id is not None:
            clauses.append("target_id = ?")
            params.append(target_id)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY memo_id"
        return [
            Memo(memo_id=r["memo_id"], target_type=r["target_type"], target_id=r["target_id"],
                 text=r["text"], author=r["author"],
                 created_at=r["created_at"] or "", updated_at=r["updated_at"] or "")
            for r in self._conn.execute(query, params)
        ]

    def update_memo(self, memo_id: str, text: str) -> None:
        self._conn.execute("UPDATE memos SET text = ?, updated_at = ? WHERE memo_id = ?",
                           (text, datetime.now().isoformat(timespec="seconds"), memo_id))
        self._event("memo_edited", "Memo edited", target_type="memo", target_id=memo_id)
        self._commit()

    def delete_memo(self, memo_id: str) -> None:
        self._conn.execute("DELETE FROM memos WHERE memo_id = ?", (memo_id,))
        self._event("memo_deleted", "Memo deleted", target_type="memo", target_id=memo_id)
        self._commit()

    # ── raters ───────────────────────────────────────────────────────────────
    def add_rater(self, rater: Rater) -> str:
        rid = rater.rater_id or new_id("rater")
        self._conn.execute(
            "INSERT INTO raters(rater_id, kind, name, model_id) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(rater_id) DO UPDATE SET kind = excluded.kind, name = excluded.name, "
            "model_id = excluded.model_id",
            (rid, rater.kind, rater.name, rater.model_id),
        )
        self._commit()
        return rid

    def list_raters(self) -> List[Rater]:
        return [
            Rater(rater_id=r["rater_id"], kind=r["kind"], name=r["name"], model_id=r["model_id"])
            for r in self._conn.execute("SELECT * FROM raters ORDER BY rater_id")
        ]

    # ── run manifests ────────────────────────────────────────────────────────
    def add_run(self, run: RunManifest) -> str:
        rid = run.run_id or new_id("run")
        self._conn.execute(
            "INSERT INTO runs(run_id, package_version, mode, engine, model, timestamp, "
            "thresholds_json, counts_json, template_version, exported_raw_text, exported_embeddings) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (rid, run.package_version, run.mode, run.engine, run.model, run.timestamp,
             json.dumps(run.thresholds), json.dumps(run.counts), run.template_version,
             int(run.exported_raw_text), int(run.exported_embeddings)),
        )
        self._commit()
        return rid

    def list_runs(self) -> List[RunManifest]:
        return [
            RunManifest(
                run_id=r["run_id"], package_version=r["package_version"], mode=r["mode"],
                engine=r["engine"], model=r["model"], timestamp=r["timestamp"],
                thresholds=json.loads(r["thresholds_json"] or "{}"),
                counts=json.loads(r["counts_json"] or "{}"),
                template_version=r["template_version"],
                exported_raw_text=bool(r["exported_raw_text"]),
                exported_embeddings=bool(r["exported_embeddings"]))
            for r in self._conn.execute("SELECT * FROM runs ORDER BY run_id")
        ]

    # ── structured coding: decisions + review (Alt Survey Flow, schema v7) ────
    def record_coding_decisions(self, decisions: List[CodingDecision]) -> List[str]:
        """Insert or replace this run's candidate-code verdicts, one call.

        `INSERT ... ON CONFLICT` on (excerpt_id, code_id, run_id): re-running the
        same coding run over the same excerpt replaces the prior verdict for that
        (excerpt, code) pair rather than duplicating it, so a cancelled-and-resumed
        run (the resumability the workflow promises) is idempotent. A REVIEWED
        decision is deliberately still overwritable this way -- re-running is a
        new model opinion, and the reviewer sees it as freshly unreviewed unless
        the caller explicitly preserves review_status, which record_coding_run
        (engines/laya_engine.py) does for items it is resuming rather than redoing.
        Returns the decision_ids in the order given.
        """
        ids: List[str] = []
        with self._conn:
            for d in decisions:
                did = d.decision_id or new_id("dec")
                ids.append(did)
                self._conn.execute(
                    "INSERT INTO coding_decisions(decision_id, excerpt_id, code_id, run_id, "
                    "model_score, model_assigned, review_status, human_assigned, reviewer, "
                    "reviewed_at, note) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(excerpt_id, code_id, run_id) DO UPDATE SET "
                    "decision_id = excluded.decision_id, model_score = excluded.model_score, "
                    "model_assigned = excluded.model_assigned, review_status = excluded.review_status, "
                    "human_assigned = excluded.human_assigned, reviewer = excluded.reviewer, "
                    "reviewed_at = excluded.reviewed_at, note = excluded.note",
                    (did, d.excerpt_id, d.code_id, d.run_id, d.model_score, int(d.model_assigned),
                     d.review_status,
                     None if d.human_assigned is None else int(d.human_assigned),
                     d.reviewer, d.reviewed_at, d.note),
                )
        return ids

    def sync_machine_application(
        self, *, excerpt_id: str, code_id: str, rater_id: str, run_id: str,
        confidence: Optional[float] = None,
    ) -> Optional[str]:
        """Idempotently ensure a machine CodeApplication exists for (excerpt,
        code, rater). Used by `engines.laya_engine.run_coding_pass` for every
        confident_yes decision -- a resumed or forced-redo coding pass must not
        insert a second application for the same call, the way a plain
        `apply_code` would. Returns the application_id (new or existing), or
        None only if the caller passes bad ids (never raises: this runs inside
        a coding loop that should not abort a whole pass over one row).
        """
        existing = self._conn.execute(
            "SELECT application_id FROM code_applications "
            "WHERE excerpt_id = ? AND code_id = ? AND rater_id = ?",
            (excerpt_id, code_id, rater_id)).fetchone()
        if existing is not None:
            return existing["application_id"]
        aid = new_id("app")
        self._conn.execute(
            "INSERT INTO code_applications(application_id, excerpt_id, code_id, coder, "
            "rater_id, run_id, confidence) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (aid, excerpt_id, code_id, "transformer", rater_id, run_id, confidence),
        )
        self._commit()
        return aid

    def review_coding_decision(
        self, decision_id: str, *, human_assigned: bool, reviewer: str,
        review_status: Optional[CodingReviewStatus] = None, note: str = "",
        rater_id: str = "human_primary",
    ) -> None:
        """Record a human's verdict on one candidate code (the Review Queue's
        accept/reject/flag action). `review_status` defaults to 'confirmed' when
        human_assigned agrees with the model's own call, else 'rejected' -- the
        analyst can override with 'flagged' for "still unsure, look again".

        Also keeps `code_applications` in step with the verdict, under
        `rater_id` (default `'human_primary'` -- the same identity
        `core.populate.record_human_codings` uses for Labeling Lab codes, so a
        code confirmed here and one hand-coded in the Lab are the same coder's
        work for kappa purposes, not two). `human_assigned=True` ensures an
        application exists; `False` removes one if the model had already
        created it. This is why CodingDecision and CodeApplication can stay two
        separate tables without every caller having to remember to sync them.
        """
        row = self._conn.execute(
            "SELECT excerpt_id, code_id, model_score, model_assigned "
            "FROM coding_decisions WHERE decision_id = ?", (decision_id,)).fetchone()
        if row is None:
            raise ValueError(f"No coding decision with id {decision_id!r}")
        if review_status is None:
            review_status = "confirmed" if bool(row["model_assigned"]) == human_assigned else "rejected"

        with self._conn:
            self._conn.execute(
                "UPDATE coding_decisions SET human_assigned = ?, review_status = ?, "
                "reviewer = ?, reviewed_at = ?, note = ? WHERE decision_id = ?",
                (int(human_assigned), review_status, reviewer,
                 datetime.now().isoformat(timespec="seconds"), note, decision_id),
            )
            existing = self._conn.execute(
                "SELECT application_id FROM code_applications "
                "WHERE excerpt_id = ? AND code_id = ? AND rater_id = ?",
                (row["excerpt_id"], row["code_id"], rater_id)).fetchall()
            if human_assigned and not existing:
                self._conn.execute(
                    "INSERT INTO code_applications(application_id, excerpt_id, code_id, coder, "
                    "rater_id, confidence) VALUES (?, ?, ?, ?, ?, ?)",
                    (new_id("app"), row["excerpt_id"], row["code_id"], "human", rater_id,
                     row["model_score"]),
                )
            elif not human_assigned and existing:
                self._conn.executemany(
                    "DELETE FROM code_applications WHERE application_id = ?",
                    [(r["application_id"],) for r in existing])

    def _row_to_coding_decision(self, r: sqlite3.Row) -> CodingDecision:
        return CodingDecision(
            decision_id=r["decision_id"], excerpt_id=r["excerpt_id"], code_id=r["code_id"],
            run_id=r["run_id"], model_score=r["model_score"], model_assigned=bool(r["model_assigned"]),
            review_status=r["review_status"],
            human_assigned=None if r["human_assigned"] is None else bool(r["human_assigned"]),
            reviewer=r["reviewer"], reviewed_at=r["reviewed_at"], note=r["note"],
        )

    def list_coding_decisions(
        self, *, run_id: Optional[str] = None, excerpt_id: Optional[str] = None,
        review_status: Optional[str] = None,
    ) -> List[CodingDecision]:
        query = "SELECT * FROM coding_decisions"
        clauses, params = [], []
        if run_id is not None:
            clauses.append("run_id = ?"); params.append(run_id)
        if excerpt_id is not None:
            clauses.append("excerpt_id = ?"); params.append(excerpt_id)
        if review_status is not None:
            clauses.append("review_status = ?"); params.append(review_status)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY decision_id"
        return [self._row_to_coding_decision(r) for r in self._conn.execute(query, params)]

    def coding_decisions_table(self, run_id: Optional[str] = None) -> pd.DataFrame:
        """One row per (excerpt, candidate code) decision, joined to the excerpt's
        text and source, and the code's name -- the Review Queue's and the
        export's source table. Includes rejected/unassigned candidates, unlike
        `coding_table()` which only ever sees accepted codes."""
        cols = ["decision_id", "excerpt_id", "source_id", "excerpt_text", "code_id",
                "code_name", "run_id", "model_score", "model_assigned", "review_status",
                "human_assigned", "reviewer", "reviewed_at", "note"]
        query = (
            "SELECT d.decision_id, d.excerpt_id, e.source_id, e.text AS excerpt_text, "
            "d.code_id, c.name AS code_name, d.run_id, d.model_score, d.model_assigned, "
            "d.review_status, d.human_assigned, d.reviewer, d.reviewed_at, d.note "
            "FROM coding_decisions d "
            "JOIN excerpts e ON d.excerpt_id = e.excerpt_id "
            "JOIN codes c ON d.code_id = c.code_id"
        )
        params: List[Any] = []
        if run_id is not None:
            query += " WHERE d.run_id = ?"
            params.append(run_id)
        rows = self._conn.execute(query, params).fetchall()
        return pd.DataFrame([dict(r) for r in rows], columns=cols)

    def review_queue(self, run_id: str, *, low: float, high: float) -> pd.DataFrame:
        """Decisions from `run_id` a human still needs to look at: unreviewed and
        scored in the ambiguous band [low, high) -- clearly-no and clearly-yes
        candidates outside that band are exactly what a confidence threshold is
        FOR (see engines/laya_engine.py::route_by_confidence for the shared
        definition of "ambiguous" this must not drift from)."""
        table = self.coding_decisions_table(run_id)
        if table.empty:
            return table
        in_band = table["model_score"].apply(
            lambda s: s is not None and low <= float(s) < high)
        return table[(table["review_status"] == "unreviewed") & in_band].reset_index(drop=True)

    # ── coding run configs (Alt Survey Flow) ─────────────────────────────────
    def save_coding_run_config(self, config: CodingRunConfig) -> str:
        """Insert or replace by name -- a saved run configuration is named and
        re-editable, same convention as `save_chart`."""
        existing = self._conn.execute(
            "SELECT config_id FROM coding_run_configs WHERE name = ?", (config.name,)
        ).fetchone()
        cid = config.config_id or (existing["config_id"] if existing else new_id("crc"))
        self._conn.execute(
            "INSERT INTO coding_run_configs(config_id, name, spec_json, created_by, created_at) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(name) DO UPDATE SET spec_json = excluded.spec_json, "
            "created_by = excluded.created_by, created_at = excluded.created_at",
            (cid, config.name, json.dumps(config.spec), config.created_by,
             config.created_at or datetime.now().isoformat(timespec="seconds")),
        )
        self._commit()
        return cid

    def get_coding_run_config(self, name: str) -> Optional[CodingRunConfig]:
        row = self._conn.execute(
            "SELECT * FROM coding_run_configs WHERE name = ?", (name,)).fetchone()
        if row is None:
            return None
        return CodingRunConfig(config_id=row["config_id"], name=row["name"],
                               spec=json.loads(row["spec_json"] or "{}"),
                               created_by=row["created_by"], created_at=row["created_at"])

    def list_coding_run_configs(self) -> List[CodingRunConfig]:
        return [
            CodingRunConfig(config_id=r["config_id"], name=r["name"],
                            spec=json.loads(r["spec_json"] or "{}"),
                            created_by=r["created_by"], created_at=r["created_at"])
            for r in self._conn.execute("SELECT * FROM coding_run_configs ORDER BY name")
        ]

    def delete_coding_run_config(self, name: str) -> bool:
        cursor = self._conn.execute("DELETE FROM coding_run_configs WHERE name = ?", (name,))
        self._commit()
        return cursor.rowcount > 0

    # ── JSON export / import (portability) ───────────────────────────────────
    _TABLES = ["sources", "excerpts", "codes", "code_applications", "descriptors",
               "descriptor_fields", "memos", "raters", "runs", "codebook_versions",
               "coding_decisions", "coding_run_configs", "rater_coverage",
               "document_coverage", "project_events"]

    def export_json(self, path: Union[str, Path]) -> Path:
        """Dump the whole project to a portable JSON bundle."""
        bundle: Dict[str, Any] = {"schema_version": SCHEMA_VERSION, "tables": {}}
        for table in self._TABLES:
            rows = self._conn.execute(f"SELECT * FROM {table}")
            bundle["tables"][table] = [dict(r) for r in rows]
        out = Path(path)
        out.write_text(json.dumps(bundle, indent=2), encoding="utf-8")
        return out

    @classmethod
    def import_json(cls, json_path: Union[str, Path], db_path: Union[str, Path]) -> "Project":
        """Build a new project file from a JSON bundle produced by export_json."""
        bundle = json.loads(Path(json_path).read_text(encoding="utf-8"))
        proj = cls.create(db_path)
        tables = bundle.get("tables", {})
        # Insert in dependency order so foreign keys resolve.
        for table in cls._TABLES:
            for row in tables.get(table, []):
                cols = list(row.keys())
                placeholders = ", ".join("?" for _ in cols)
                proj._conn.execute(
                    f"INSERT INTO {table}({', '.join(cols)}) VALUES ({placeholders})",
                    tuple(row[c] for c in cols),
                )
        proj._conn.commit()
        return proj
