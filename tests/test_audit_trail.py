"""The audit trail export (V7 Update 2, U3).

The record a confirmability audit needs: every dated decision, in order,
with no response text and no response ids -- checked the way the bundle's
redaction is checked, by opening the files and reading every part.
"""

from __future__ import annotations

import json
import zipfile

import pandas as pd
import pytest

from core.model import Code, Memo, Source
from core.populate import populate_project_store, record_human_codings
from core.project import Project
from exports.audit_trail import (audit_trail_frame, build_audit_trail_docx,
                                 build_audit_trail_xlsx)

SECRET = "I sleep in my car two nights a week because rent went up."
DOC_TITLE = "P07_Maria_Gonzalez_transcript"


def _session(tmp_path):
    """A realistic project: a run, Lab coding, a memo quoting a response, an
    adjudication, a finished document, a codebook edit, and an erasure."""
    from core.adjudication import record_adjudications

    work = pd.DataFrame({
        "response_id": ["R-9001", "R-9002", "R-9003"], "question_text": ["Q"] * 3,
        "response_text": [SECRET, "Advising was hard to reach.", "No complaints."],
        "zshot_top_label": ["Cost", "Advising", "Cost"], "zshot_top_score": [0.9, 0.8, 0.3],
        "zshot_strict_label": ["Cost", "Advising", "UNCERTAIN_REVIEW"],
        "zshot_strict_confident": [True, True, False], "zshot_strict_margin": [0.5, 0.4, 0.0]})
    config = {"input": {}, "output": {}, "models": {"zero_shot_model": "facebook/bart-large-mnli"},
              "zero_shot": {"labels": ["Cost", "Advising"],
                            "strict_coding": {"enabled": True, "uncertain_label": "UNCERTAIN_REVIEW"}}}
    store = populate_project_store(work, config, tmp_path / "project.qnw")
    record_human_codings(store, {"R-9001": ["Cost"], "R-9002": [], "R-9003": []}, question_text="Q")
    with Project.open(store) as proj:
        code = next(c.code_id for c in proj.get_codebook() if c.name == "Cost")
        proj.set_code_definition(code, "Worry about paying for college or rent")
        proj.add_memo(Memo(memo_id="", target_type="code", target_id=code,
                           text=f'Strong example: "{SECRET}"'))
        proj.add_source(Source(source_id="doc1", type="document", raw_text="Interview text.",
                               label=DOC_TITLE, metadata={"title": DOC_TITLE}))
        proj.mark_document_coded("human_primary", "doc1")
        excerpt = proj.list_excerpts()[0].excerpt_id
    record_adjudications(store, {excerpt: ["Cost"]})
    return store


def test_the_trail_is_chronological_and_draws_on_every_record(tmp_path):
    store = _session(tmp_path)
    with Project.open(store) as proj:
        frame = audit_trail_frame(proj)
    sources = set(frame["source"])
    assert {"event log", "runs", "review record"} <= sources
    whats = " | ".join(frame["what"])
    assert "Definition changed: Cost" in whats
    assert "Analysis run" in whats
    assert "response(s) reviewed" in whats
    assert "document(s) marked as fully coded" in whats
    dated = frame[frame["at"] != ""]["at"].tolist()
    assert dated == sorted(dated)


def test_nothing_in_either_file_names_a_respondent_or_quotes_them(tmp_path):
    from core.erasure import erase_respondent

    store = _session(tmp_path)
    erase_respondent(tmp_path, "R-9002", store_path=store)
    docx = build_audit_trail_docx(store, tmp_path / "audit.docx")
    xlsx = build_audit_trail_xlsx(store, tmp_path / "audit.xlsx")
    for path in (docx, xlsx):
        with zipfile.ZipFile(path) as zf:
            for name in zf.namelist():
                text = zf.read(name).decode("utf-8", errors="ignore")
                for forbidden in (SECRET, "R-9001", "R-9002", "R-9003", DOC_TITLE,
                                  "Advising was hard to reach"):
                    assert forbidden not in text, f"{forbidden!r} leaked into {path.name}:{name}"
    with Project.open(store) as proj:
        assert "A respondent's data was erased" in " ".join(audit_trail_frame(proj)["what"])


def test_memo_text_only_when_asked(tmp_path):
    store = _session(tmp_path)
    with Project.open(store) as proj:
        without = audit_trail_frame(proj)
        with_text = audit_trail_frame(proj, include_memo_text=True)
    assert SECRET not in " ".join(without["detail"])
    assert SECRET in " ".join(with_text["detail"])


def test_undated_history_is_admitted_not_invented(tmp_path):
    import sqlite3
    store = _session(tmp_path)
    con = sqlite3.connect(store)
    con.execute("UPDATE memos SET created_at = '', updated_at = ''")   # as if written pre-v9
    con.commit()
    con.close()
    with Project.open(store) as proj:
        frame = audit_trail_frame(proj)
    first = frame.iloc[0]
    assert first["at"] == "" and "before memos were dated" in first["what"]


def test_an_erasure_from_before_the_event_log_comes_from_the_log_file(tmp_path):
    store = _session(tmp_path)
    (tmp_path / "audit_log.jsonl").write_text(json.dumps({
        "timestamp": "2026-08-01T10:00:00", "event": "erase_respondent",
        "erased_response_id_hash": "abc123", "backups_purged": True}) + "\n", encoding="utf-8")
    with Project.open(store) as proj:
        frame = audit_trail_frame(proj)
    row = frame[frame["source"] == "erasure log"].iloc[0]
    assert row["at"] == "2026-08-01T10:00:00" and "abc123" in row["detail"]


def test_backups_appear_with_their_reason(tmp_path):
    from core.backups import backup_store
    store = _session(tmp_path)
    backup_store(store, reason="pre_store_merge")
    with Project.open(store) as proj:
        frame = audit_trail_frame(proj)
    assert "Backup taken before pre store merge" in " ".join(frame["what"])


def test_both_files_open_and_say_what_they_are(tmp_path):
    from docx import Document
    store = _session(tmp_path)
    doc = Document(build_audit_trail_docx(store, tmp_path / "a.docx"))
    text = "\n".join(p.text for p in doc.paragraphs)
    assert "What this record is" in text and "No response text" in text
    sheets = pd.read_excel(build_audit_trail_xlsx(store, tmp_path / "a.xlsx"), sheet_name=None)
    assert set(sheets) == {"Audit trail", "About"}
    assert list(sheets["Audit trail"].columns) == ["at", "who", "what", "detail", "source"]
