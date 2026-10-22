"""
Erasure leaves no readable remnant (upstream fix, PORTED_BACK.md §11).

`erase_respondent` was correct about every *query*: the respondent was gone from
the store, the CSVs, the report, and the caches. It was wrong about the *file*.
SQLite marks a deleted row's page free and reuses it later, if ever, so the
response stayed legible in the `.qnw` bytes — and the pre-erase backup held a
whole un-erased copy beside it.

That matters more than the usual "deletion is not shredding" caveat. This is the
live project file the researcher goes on using, copies to a colleague, and
attaches to an archive.

**Every assertion here reads bytes, not rows.** Querying the store passed the
whole time this defect existed and proved nothing.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.backups import BACKUP_DIR_NAME, list_backups
from core.erasure import erase_respondent
from core.model import Source
from core.project import Project, new_id

# Distinctive enough that finding it in the file cannot be a coincidence.
WITHDRAWN_TEXT = "Zephyrine Quackenbush withdrew consent on the fourteenth"
RETAINED_TEXT = "an ordinary response that must survive the erasure"


def _seed(store: Path) -> None:
    with Project.create(store) as p:
        for rid, text in (("r1", WITHDRAWN_TEXT), ("r2", RETAINED_TEXT)):
            src = Source(source_id=new_id("src"), type="survey_response", raw_text=text,
                         label="Q1", metadata={"response_id": rid, "question_text": "Q1"})
            p.add_source(src)
            p.add_whole_response_excerpt(src)


def _appears_in(path: Path, text: str) -> bool:
    """Is this text recoverable from the file's raw bytes? UTF-8, as SQLite stores it."""
    return text.encode("utf-8") in path.read_bytes()


@pytest.fixture()
def project(tmp_path):
    project_dir = tmp_path / "run_1"
    project_dir.mkdir()
    store = project_dir / "project.qnw"
    _seed(store)
    assert _appears_in(store, WITHDRAWN_TEXT), "seed did not write the text we are testing for"
    return project_dir, store


class TestTheStoreFile:

    def test_the_erased_response_is_not_in_the_file_bytes(self, project):
        project_dir, store = project

        report = erase_respondent(project_dir, "r1", purge_backups=True)

        assert report["vacuumed"] is True
        assert not _appears_in(store, WITHDRAWN_TEXT)

    def test_the_other_respondent_survives_intact(self, project):
        project_dir, store = project

        erase_respondent(project_dir, "r1", purge_backups=True)

        assert _appears_in(store, RETAINED_TEXT)
        with Project.open(store) as p:
            assert len(p.list_sources()) == 1

    def test_the_report_says_whether_the_rebuild_happened(self, project):
        """A caller has to be able to tell an erasure from a half-erasure."""
        project_dir, _ = project

        report = erase_respondent(project_dir, "r1")

        assert "vacuumed" in report

    def test_a_missing_store_does_not_claim_a_rebuild(self, tmp_path):
        project_dir = tmp_path / "empty"
        project_dir.mkdir()

        report = erase_respondent(project_dir, "r1")

        assert report["vacuumed"] is False


class TestTheBackups:

    def test_the_pre_erase_backup_is_reported_as_still_holding_the_data(self, project):
        project_dir, store = project

        report = erase_respondent(project_dir, "r1")

        remaining = report["backups_retaining_data"]
        assert remaining, "the safety backup was kept but not reported"
        assert report["backups_purged"] is False
        assert any(_appears_in(Path(p), WITHDRAWN_TEXT) for p in remaining)

    def test_purging_removes_the_backup_that_holds_the_erased_text(self, project):
        project_dir, store = project

        report = erase_respondent(project_dir, "r1", purge_backups=True)

        assert report["backups_purged"] is True
        assert report["backups_retaining_data"] == []
        assert not (store.parent / BACKUP_DIR_NAME).exists()
        assert list_backups(store) == []

    def test_the_default_keeps_the_safety_net(self, project):
        """Erasing the wrong id must still be recoverable unless the caller opts out."""
        project_dir, store = project

        erase_respondent(project_dir, "r1")

        assert list_backups(store), "the default must not destroy the way back"


class TestTheAuditEvent:

    def test_the_audit_records_both_outcomes_without_naming_anyone(self, project):
        import json

        project_dir, _ = project

        erase_respondent(project_dir, "r1", purge_backups=True)

        events = [json.loads(line) for line
                  in (project_dir / "audit_log.jsonl").read_text(encoding="utf-8").splitlines()]
        event = events[-1]
        assert event["vacuumed"] is True
        assert event["backups_purged"] is True
        assert "r1" not in json.dumps(event)
        assert WITHDRAWN_TEXT not in json.dumps(event)
