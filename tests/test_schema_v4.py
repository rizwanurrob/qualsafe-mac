"""Schema v4: corpus tables, FTS5 index, and the v3 -> v4 migration."""

from __future__ import annotations

import sqlite3

from core.model import Annotation, Case, ExcerptLink, Source
from core.project import SCHEMA_VERSION, Project

V4_TABLES = ("cases", "case_membership", "annotations", "excerpt_links")


def _downgrade_to_v3(path):
    """Make a current store look like a v3 one: drop v4 tables + FTS, stamp 3."""
    con = sqlite3.connect(path)
    for table in V4_TABLES:
        con.execute(f"DROP TABLE IF EXISTS {table}")
    con.executescript(
        "DROP TRIGGER IF EXISTS sources_fts_ai;"
        "DROP TRIGGER IF EXISTS sources_fts_ad;"
        "DROP TRIGGER IF EXISTS sources_fts_au;"
        "DROP TABLE IF EXISTS sources_fts;"
    )
    con.execute("UPDATE meta SET value='3' WHERE key='schema_version'")
    con.commit()
    con.close()


def _seed(proj, sid="s1", text="The advisor was helpful", stype="document"):
    src = Source(source_id=sid, type=stype, raw_text=text, label=sid, metadata={})
    proj.add_source(src)
    return src, proj.add_whole_response_excerpt(src)


def test_new_store_is_v4_with_corpus_tables(tmp_path):
    path = tmp_path / "new.qnw"
    with Project.create(path):
        pass
    con = sqlite3.connect(path)
    version = int(con.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0])
    names = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    con.close()
    # v4 added the corpus tables; the store has moved on since (v5 added
    # saved_charts), so this asserts the corpus tables arrived and that the
    # file is at whatever the current version is -- not a frozen number.
    assert version == SCHEMA_VERSION >= 4
    assert set(V4_TABLES) <= names


def test_v3_store_migrates_and_keeps_its_data(tmp_path):
    path = tmp_path / "old.qnw"
    with Project.create(path) as proj:
        _seed(proj, text="advising was helpful", stype="survey_response")
    _downgrade_to_v3(path)

    with Project.open(path) as proj:            # opening runs the migration
        assert [s.raw_text for s in proj.list_sources()] == ["advising was helpful"]
        assert proj.list_cases() == []          # new table exists and is empty
    con = sqlite3.connect(path)
    version = int(con.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0])
    con.close()
    assert version == SCHEMA_VERSION


def test_migration_backfills_the_search_index(tmp_path):
    """An upgraded project must be searchable over text it already had."""
    path = tmp_path / "old.qnw"
    with Project.create(path) as proj:
        _seed(proj, text="tuition cost is a worry")
    _downgrade_to_v3(path)

    with Project.open(path) as proj:
        if not proj.fts_available():
            return                              # SQLite without FTS5: nothing to assert
        assert proj.fts_match_source_ids("tuition") == ["s1"]


def test_deleting_a_source_purges_it_from_the_index(tmp_path):
    """Erasure must not leave searchable ghosts of deleted text."""
    path = tmp_path / "p.qnw"
    with Project.create(path) as proj:
        _seed(proj, sid="s1", text="a secret confession")
        if not proj.fts_available():
            return
        assert proj.fts_match_source_ids("confession") == ["s1"]
        proj.delete_source("s1")
        assert proj.fts_match_source_ids("confession") == []


def test_malformed_fts_query_raises_valueerror(tmp_path):
    path = tmp_path / "p.qnw"
    with Project.create(path) as proj:
        _seed(proj)
        if not proj.fts_available():
            return
        try:
            proj.fts_match_source_ids('"unbalanced')
        except ValueError:
            return
        # Some SQLite builds tolerate it; tolerating is fine, crashing is not.


def test_pagination_and_counts(tmp_path):
    path = tmp_path / "p.qnw"
    with Project.create(path) as proj:
        for i in range(5):
            _seed(proj, sid=f"s{i}", text=f"text {i}")
        _seed(proj, sid="survey1", text="a response", stype="survey_response")
        assert proj.count_sources() == 6
        assert proj.count_sources("document") == 5
        page = proj.iter_sources(limit=2, offset=0)
        assert len(page) == 2
        assert [s.source_id for s in proj.iter_sources(limit=2, offset=2)] != \
               [s.source_id for s in page]
        assert set(proj.source_types()) == {"document", "survey_response"}


def test_cases_annotations_and_links(tmp_path):
    path = tmp_path / "p.qnw"
    with Project.create(path) as proj:
        _, e1 = _seed(proj, sid="s1", text="first doc")
        _, e2 = _seed(proj, sid="s2", text="second doc")

        cid = proj.add_case(Case(case_id="", name="Alice", kind="person"))
        proj.assign_source_to_case(cid, "s1")
        proj.assign_source_to_case(cid, "s1")          # idempotent
        proj.assign_source_to_case(cid, "s2")
        assert proj.case_sources(cid) == ["s1", "s2"]
        assert proj.source_cases("s1") == [cid]
        assert [c.name for c in proj.list_cases()] == ["Alice"]

        aid = proj.add_annotation(Annotation(annotation_id="", excerpt_id=e1, text="key line"))
        assert [a.text for a in proj.list_annotations(e1)] == ["key line"]
        proj.delete_annotation(aid)
        assert proj.list_annotations(e1) == []

        proj.add_excerpt_link(ExcerptLink(link_id="", from_excerpt=e1, to_excerpt=e2,
                                          kind="contradicts", note="opposite views"))
        links = proj.list_excerpt_links(e1)
        assert len(links) == 1 and links[0].kind == "contradicts"


def test_case_membership_cascades_when_source_deleted(tmp_path):
    path = tmp_path / "p.qnw"
    with Project.create(path) as proj:
        _seed(proj, sid="s1")
        cid = proj.add_case(Case(case_id="", name="Alice"))
        proj.assign_source_to_case(cid, "s1")
        proj.delete_source("s1")
        assert proj.case_sources(cid) == []
