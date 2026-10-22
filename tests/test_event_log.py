"""The project event log (store format v9) and dated memos (V7 Update 2, U2).

An audit trail is only as good as its record. Before v9, changing a code's
definition or writing a memo left no dated trace at all; this log is what the
audit trail export (U3) reads. It must never hold response text or ids.
"""

from __future__ import annotations

import json
import sqlite3

import pandas as pd
import pytest

from core.model import Code, Excerpt, Memo, Source
from core.project import SCHEMA_VERSION, Project

SECRET = "My advisor never answered my emails about the scholarship."


def _project(tmp_path):
    path = tmp_path / "p.qnw"
    proj = Project.create(path)
    proj.add_source(Source(source_id="s1", type="survey_response", raw_text=SECRET,
                           metadata={"response_id": "R-000123", "question_text": "Q"}))
    proj.add_excerpt(Excerpt(excerpt_id="e1", source_id="s1", text=SECRET,
                             char_start=0, char_end=len(SECRET)))
    return proj, path


def _kinds(proj):
    return [e["kind"] for e in proj.list_events()]


def test_every_codebook_decision_is_dated_and_described(tmp_path):
    proj, _ = _project(tmp_path)
    a = proj.add_code(Code(code_id="", name="Money", definition="Cost worries"))
    b = proj.add_code(Code(code_id="", name="Finances"))
    proj.rename_code(a, "Financial stress")
    proj.set_code_definition(a, "Worry about paying for college")
    proj.set_code_parent(b, a)
    proj.set_code_structured_fields(a, inclusion_criteria="tuition, rent, books")
    proj.tag_codebook_version("before merge")
    proj.merge_codes(b, a)
    c = proj.add_code(Code(code_id="", name="Temp"))
    proj.delete_code(c)
    assert _kinds(proj) == ["code_created", "code_created", "code_renamed", "code_redefined",
                            "code_moved", "code_criteria_changed", "codebook_tagged",
                            "codes_merged", "code_created", "code_deleted"]
    redefined = next(e for e in proj.list_events() if e["kind"] == "code_redefined")
    assert redefined["detail"] == {"from": "Cost worries", "to": "Worry about paying for college"}
    assert all(e["at"] for e in proj.list_events())
    proj.close()


def test_an_unchanged_name_or_definition_is_not_an_event(tmp_path):
    proj, _ = _project(tmp_path)
    a = proj.add_code(Code(code_id="", name="Cost", definition="d"))
    proj.rename_code(a, "Cost")
    proj.set_code_definition(a, "d")
    assert _kinds(proj) == ["code_created"]
    proj.close()


def test_restoring_a_codebook_version_is_recorded(tmp_path):
    proj, _ = _project(tmp_path)
    proj.add_code(Code(code_id="", name="Cost"))
    proj.tag_codebook_version("v1")
    version = proj.list_codebook_versions()[0]["version_id"]
    proj.restore_codebook_version(version)
    assert "codebook_restored" in _kinds(proj)
    proj.close()


def test_memos_are_dated_and_logged_without_their_text(tmp_path):
    proj, _ = _project(tmp_path)
    mid = proj.add_memo(Memo(memo_id="", target_type="project", target_id=None,
                             text="Private reasoning about R-000123"))
    memo = proj.list_memos()[0]
    assert memo.created_at and memo.created_at == memo.updated_at
    proj.update_memo(mid, "revised")
    proj.delete_memo(mid)
    assert _kinds(proj) == ["memo_added", "memo_edited", "memo_deleted"]
    assert "Private reasoning" not in json.dumps(proj.list_events())
    proj.close()


def test_the_actor_is_the_analyst_the_app_stores(tmp_path):
    from core.app_settings import save_app_settings

    save_app_settings({"analyst_name": "Dana Analyst"})
    proj, _ = _project(tmp_path)
    proj.add_code(Code(code_id="", name="Cost"))
    assert proj.list_events()[0]["actor"] == "Dana Analyst"
    proj.close()


def test_decisions_made_elsewhere_are_logged(tmp_path):
    from core.adjudication import record_adjudications
    from core.autocode import autocode_hits
    from core.codebook_io import import_codebook_yaml
    from core.populate import import_second_coder_sample
    from core.search import search

    proj, path = _project(tmp_path)
    import_codebook_yaml(proj, "codebook:\n  - name: Advising\n")
    hits = search(proj, "advisor")
    autocode_hits(proj, hits, "Advising", query="advisor")
    proj.close()

    record_adjudications(path, {"e1": ["Advising"]})
    csv = tmp_path / "coder2.csv"
    pd.DataFrame({"response_id": ["R-000123"], "human_labels": ["Advising"]}).to_csv(csv, index=False)
    import_second_coder_sample(path, csv, rater_id="human_b", question_text="Q")

    with Project.open(path) as proj:
        kinds = _kinds(proj)
    for kind in ("codebook_imported", "auto_coded", "adjudication", "coder_imported"):
        assert kind in kinds, kinds


def test_erasure_is_logged_by_hash_and_the_log_names_no_one(tmp_path):
    from core.erasure import erase_respondent

    proj, path = _project(tmp_path)
    proj.add_code(Code(code_id="", name="Advising"))
    proj.close()
    erase_respondent(tmp_path, "R-000123", store_path=path)
    with Project.open(path) as proj:
        events = proj.list_events()
    erased = next(e for e in events if e["kind"] == "respondent_erased")
    assert erased["target_id"] and "R-000123" not in erased["target_id"]
    dump = json.dumps(events)
    assert "R-000123" not in dump and SECRET not in dump


def test_no_event_ever_carries_response_text(tmp_path):
    """Walk a whole session's log for the one sentence that must never be in it."""
    proj, path = _project(tmp_path)
    a = proj.add_code(Code(code_id="", name="Advising"))
    proj.set_code_definition(a, "Trouble reaching an advisor")
    proj.add_memo(Memo(memo_id="", target_type="code", target_id=a, text=SECRET))
    proj.close()
    with Project.open(path) as proj:
        dump = json.dumps(proj.list_events())
    assert SECRET not in dump
    assert "R-000123" not in dump


def test_a_v8_store_migrates_to_v9(tmp_path):
    proj, path = _project(tmp_path)
    proj.add_memo(Memo(memo_id="m_old", target_type="project", target_id=None, text="old"))
    proj.close()
    con = sqlite3.connect(path)
    con.executescript("""
        DROP TABLE project_events;
        CREATE TABLE memos_v8 (memo_id TEXT PRIMARY KEY, target_type TEXT NOT NULL,
            target_id TEXT, text TEXT NOT NULL, author TEXT DEFAULT 'human');
        INSERT INTO memos_v8 SELECT memo_id, target_type, target_id, text, author FROM memos;
        DROP TABLE memos;
        ALTER TABLE memos_v8 RENAME TO memos;
        UPDATE meta SET value='8' WHERE key='schema_version';
    """)
    con.commit()
    con.close()
    with Project.open(path) as proj:
        memo = proj.list_memos()[0]
        assert memo.text == "old" and memo.created_at == ""   # never invented
        assert proj.list_events() == []
        proj.add_code(Code(code_id="", name="Cost"))
        assert _kinds(proj) == ["code_created"]
    con = sqlite3.connect(path)
    version = int(con.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0])
    con.close()
    assert version == SCHEMA_VERSION >= 9


def test_json_export_import_keeps_the_log(tmp_path):
    proj, _ = _project(tmp_path)
    proj.add_code(Code(code_id="", name="Cost"))
    proj.export_json(tmp_path / "p.json")
    proj.close()
    with Project.import_json(tmp_path / "p.json", tmp_path / "copy.qnw") as copy:
        assert "code_created" in _kinds(copy)


def test_the_desktop_app_names_its_analyst(tmp_path):
    pytest.importorskip("PySide6")
    from qualsafe_qt.services.project_service import ProjectService

    proj, path = _project(tmp_path)
    proj.close()
    service = ProjectService()
    service.set_analyst_name("Robin Coder")
    service.open(path)
    try:
        service.project.add_code(Code(code_id="", name="Cost"))
        assert service.project.list_events()[-1]["actor"] == "Robin Coder"
    finally:
        service.close()


def test_structured_code_examples_are_counted_not_copied(tmp_path):
    """Examples are often real responses pasted in; the log keeps the count."""
    proj, _ = _project(tmp_path)
    code = proj.add_code(Code(code_id="", name="Advising"))
    proj.set_code_structured_fields(code, examples=[SECRET, "another answer"])
    event = proj.list_events()[-1]
    assert event["detail"]["examples"] == "2 example(s)"
    assert SECRET not in json.dumps(proj.list_events())
    proj.close()
