#!/usr/bin/env python
"""
Schema migrations for the `.qnw` project store (v3.1.1, Phase 1.2).

Until now `SCHEMA_VERSION` was decoration: every run deleted and rebuilt the
store, so no file ever outlived the code that wrote it. Phase 1.2 makes stores
persist and accumulate across runs — and therefore across versions — which is the
moment the version number has to start doing real work.

This harness exists now, while stores are young and the only migration is
trivial, because retrofitting migrations onto files that already hold months of
someone's coding is miserable. The cost of building it early is one dict.

Adding a migration
------------------
1. Bump `SCHEMA_VERSION` in `core/project.py`.
2. Add `{new_version: _migrate_N_to_N_plus_1}` to `MIGRATIONS` below.
3. Write the function: take a connection, make the change, don't commit (the
   caller wraps everything in one transaction so a crash mid-migration rolls
   back rather than leaving a half-migrated file).
4. Add a fixture of the *old* format under `tests/fixtures/` and a test that
   opens it.

Migrations must be forward-only and idempotent where possible (`IF NOT EXISTS`).
There is no downgrade path: opening a store written by a *newer* version raises
rather than guessing, because silently reading a file you don't understand is how
data gets corrupted.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Callable, Dict, List


class SchemaTooNewError(RuntimeError):
    """The store was written by a newer version of the tool than this one."""

    def __init__(self, found: int, supported: int):
        super().__init__(
            f"This project file uses schema version {found}, but this version of the "
            f"QualSafe only understands up to version {supported}. "
            f"Update the tool to open this project. (Older versions are not able to "
            f"safely read newer project files, so it will not guess.)"
        )
        self.found = found
        self.supported = supported


def assert_json1_available(conn: sqlite3.Connection) -> None:
    """Fail early and clearly if SQLite lacks the JSON1 extension.

    `find_source_by_response_id` relies on `json_extract`. JSON1 is compiled into
    every CPython >= 3.9 build we expect to meet, but "expect" isn't "checked",
    and discovering it on a user's ancient Linux distro halfway through a run is a
    much worse way to find out.
    """
    try:
        conn.execute("SELECT json_extract('{\"a\":1}', '$.a')").fetchone()
    except sqlite3.OperationalError as exc:  # pragma: no cover - platform-specific
        raise RuntimeError(
            "This Python's SQLite was built without the JSON1 extension, which the "
            "project store requires. Install a Python built with JSON1 support "
            "(any python.org build works), or upgrade your system SQLite."
        ) from exc


def _migrate_1_to_2(conn: sqlite3.Connection) -> None:
    """v1 -> v2: index sources by their response_id metadata.

    Phase 1.1/1.2 look sources up by `response_id` on every populate (to reuse
    rather than duplicate) and on every Lab save (to attach human codes). Without
    an index that is a full scan plus a JSON parse per row, per lookup — fine for
    20 responses, not for 20,000.

    Nothing in the stored data changes, so v1 files need no rewrite.
    """
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_sources_response_id "
        "ON sources(json_extract(metadata_json, '$.response_id'))"
    )


def _migrate_2_to_3(conn: sqlite3.Connection) -> None:
    """v2 -> v3: add the codebook_versions table (codebook snapshots).

    Purely additive — existing rows are untouched; the table starts empty and the
    first mutation auto-snapshots into it.
    """
    conn.execute(
        "CREATE TABLE IF NOT EXISTS codebook_versions ("
        " version_id TEXT PRIMARY KEY,"
        " created_at TEXT NOT NULL,"
        " note TEXT DEFAULT '',"
        " trigger TEXT DEFAULT '',"
        " codebook_hash TEXT NOT NULL,"
        " snapshot_json TEXT NOT NULL)"
    )


def _migrate_3_to_4(conn: sqlite3.Connection) -> None:
    """v3 -> v4: the corpus model — cases, annotations, and excerpt links.

    Purely additive: four empty tables plus indexes. Existing sources, excerpts,
    codes, and codings are untouched, so a v3 project opens as a v4 project with
    the same contents and simply gains the new capabilities.

    Two things deliberately NOT here:

    - **Documents.** A document is a Source with ``type='document'`` (title, path,
      and word count live in its ``metadata_json``), so the corpus needs no new
      table for them — only `cases`, which is the unit a document *belongs to*.
    - **The FTS5 index.** Creating it can fail on a SQLite built without FTS5, and
      a migration that can fail is a store that won't open. `Project._init_fts`
      creates it opportunistically after migration and backfills the existing
      text, so an upgraded project becomes searchable on first open.
    """
    conn.executescript(
        """
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
        """
    )


def _migrate_4_to_5(conn: sqlite3.Connection) -> None:
    """v4 -> v5: saved charts.

    Additive: one table. A saved chart is a *definition*, not a picture — the
    mark, the shelf assignments and the data source, stored as the JSON of a
    `core.chart_spec.ChartRequest`. Re-running it against the project as it
    stands now is the whole point: a figure built after twenty interviews should
    redraw itself after forty without anyone remembering how it was made.

    The spec is stored as JSON rather than as columns because `ChartRequest` will
    grow fields, and a schema that has to migrate every time a chart gains an
    option is a schema that discourages the option. The trade is that the store
    cannot query inside a spec, which nothing wants to do.
    """
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS saved_charts (
            chart_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            spec_json TEXT NOT NULL,
            source TEXT DEFAULT 'codings',
            created_by TEXT DEFAULT 'human',
            created_at TEXT DEFAULT ''
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_saved_charts_name ON saved_charts(name);
        """
    )


def _migrate_5_to_6(conn: sqlite3.Connection) -> None:
    """v5 -> v6: stop carrying the author's filesystem in a shareable file.

    Every imported document recorded the absolute path it came from. A real one
    looks like

        C:/Users/jsmith/OneDrive - State University/IRB-2026-0142/
        Participant Interviews/P07_Maria_Gonzalez_transcript.docx

    so a `.qnw` -- the artifact the program itself describes as portable and
    shareable -- handed its recipient the author's username, their institution's
    tenant, the protocol number and a participant's name. Verified by searching
    a store's bytes: all four strings were there.

    The privacy gate could not have caught it. `privacy.scan.scan_frame` takes a
    DataFrame: it scans what goes *in*, and never sees the store's metadata.

    Nothing read the value back, so nothing breaks by shortening it. The file's
    name is kept -- provenance is a fair question and the name is already the
    document's title -- and the directories, which nobody chose to publish, go.

    This is a data migration, not a schema one: no table changes. It is a
    version step anyway, because a store that has been through it makes a
    promise the previous one did not, and a reader needs to be able to tell.
    """
    rows = conn.execute(
        "SELECT source_id, metadata_json FROM sources "
        "WHERE metadata_json LIKE '%source_path%'"
    ).fetchall()

    for source_id, metadata_json in rows:
        try:
            metadata = json.loads(metadata_json or "{}")
        except (TypeError, ValueError):
            continue
        original = metadata.get("source_path")
        if not isinstance(original, str) or not original:
            continue
        shortened = original.replace("\\", "/").rsplit("/", 1)[-1].strip()
        if shortened != original:
            metadata["source_path"] = shortened
            conn.execute(
                "UPDATE sources SET metadata_json = ? WHERE source_id = ?",
                (json.dumps(metadata), source_id),
            )


def _migrate_6_to_7(conn: sqlite3.Connection) -> None:
    """v6 -> v7: structured codebook coding (Alt Survey Flow).

    Purely additive. Five new columns on `codes` (inclusion/exclusion criteria,
    examples, decision type, rubric levels) all default to the value that means
    "this code behaves exactly as it did before" -- empty string, empty list,
    'noul' -- so every existing code in every existing project is a valid
    structured code the moment it opens, needing no data rewrite.

    Two new tables: `coding_decisions` is the per-code, per-excerpt audit trail
    (model score, assignment, review status, human correction) that sits above
    `code_applications` rather than replacing it -- see core/model.py::
    CodingDecision for why the two are deliberately separate. `coding_run_configs`
    holds a coding run's saved settings, the same "spec as JSON" pattern
    `saved_charts` already uses.
    """
    existing = {row[1] for row in conn.execute("PRAGMA table_info(codes)")}
    for column, ddl in (
        ("inclusion_criteria", "TEXT DEFAULT ''"),
        ("exclusion_criteria", "TEXT DEFAULT ''"),
        ("examples_json", "TEXT DEFAULT '[]'"),
        ("decision_type", "TEXT DEFAULT 'noul'"),
        ("rubric_levels_json", "TEXT"),
    ):
        if column not in existing:
            conn.execute(f"ALTER TABLE codes ADD COLUMN {column} {ddl}")

    conn.executescript(
        """
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
        """
    )


def _migrate_7_to_8(conn: sqlite3.Connection) -> None:
    """v7 -> v8: the review record (review findings F1, F4).

    Purely additive. `rater_coverage` records which excerpts each rater gave a
    complete coding of -- including "no code applies", which the store could
    not express before, so kappa silently dropped every response a coder left
    uncoded. `document_coverage` records which documents a coder has finished,
    for agreement on span coding.

    No backfill, deliberately: nothing in a v7 store says which uncoded
    responses a rater looked at, and guessing would recreate the defect. A
    rater without rows keeps the old behaviour and every table built from it
    says agreement is likely overstated (`core.agreement_pairs`); re-saving a
    coding sample records the reviews.
    """
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS rater_coverage (
            rater_id TEXT NOT NULL,
            excerpt_id TEXT NOT NULL REFERENCES excerpts(excerpt_id) ON DELETE CASCADE,
            run_id TEXT,
            reviewed_at TEXT DEFAULT '',
            PRIMARY KEY (rater_id, excerpt_id)
        );
        CREATE INDEX IF NOT EXISTS idx_coverage_excerpt ON rater_coverage(excerpt_id);
        CREATE TABLE IF NOT EXISTS document_coverage (
            rater_id TEXT NOT NULL,
            source_id TEXT NOT NULL REFERENCES sources(source_id) ON DELETE CASCADE,
            marked_at TEXT DEFAULT '',
            PRIMARY KEY (rater_id, source_id)
        );
        """
    )


def _migrate_8_to_9(conn: sqlite3.Connection) -> None:
    """v8 -> v9: the project event log, and dated memos (V7 Update 2, U2).

    Purely additive. `project_events` starts empty -- decisions made before
    4.13 were never recorded, and inventing a history would be worse than
    admitting none. The audit trail export fills that period from the records
    that were always dated (runs, codebook versions, reviews). Existing memos
    keep empty dates, shown as "before memos were dated".
    """
    existing = {row[1] for row in conn.execute("PRAGMA table_info(memos)")}
    for column in ("created_at", "updated_at"):
        if column not in existing:
            conn.execute(f"ALTER TABLE memos ADD COLUMN {column} TEXT DEFAULT ''")
    conn.executescript(
        """
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
        """
    )


# version -> function that migrates *into* that version.
MIGRATIONS: Dict[int, Callable[[sqlite3.Connection], None]] = {
    2: _migrate_1_to_2,
    3: _migrate_2_to_3,
    4: _migrate_3_to_4,
    5: _migrate_4_to_5,
    6: _migrate_5_to_6,
    7: _migrate_6_to_7,
    8: _migrate_7_to_8,
    9: _migrate_8_to_9,
}


def migrate(conn: sqlite3.Connection, from_version: int, to_version: int) -> List[int]:
    """Run every migration needed to bring `from_version` up to `to_version`.

    Returns the versions applied. Raises `SchemaTooNewError` if the store is
    ahead of this code. The caller owns the transaction.
    """
    if from_version > to_version:
        raise SchemaTooNewError(found=from_version, supported=to_version)

    applied: List[int] = []
    for version in range(from_version + 1, to_version + 1):
        step = MIGRATIONS.get(version)
        if step is not None:
            step(conn)
        applied.append(version)
    return applied
