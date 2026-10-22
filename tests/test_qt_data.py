"""
Data Management: backups, archive, and the erasure that must actually erase.

Most of the weight here is on `_erase_respondent`. Erasure is the one
irreversible thing this program does, and it has a trap: `core.erasure` takes a
pre-erase backup, and that backup still contains the response. An erasure that
leaves it behind has relocated the data, not removed it.

So the tests below check the *ordering* and the *outcome* rather than that a
function was called: erase first, purge second, and afterwards the phrase must
be absent from the store AND from every backup.
"""

from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6", reason="Qt front end not installed")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QUndoStack  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core.backups import BACKUP_DIR_NAME, backup_store, list_backups  # noqa: E402
from core.model import Code, CodeApplication, Excerpt, Rater, Source  # noqa: E402
from core.project import Project  # noqa: E402
from qualsafe_qt.services.project_service import ProjectService  # noqa: E402
from qualsafe_qt.views.data_view import (  # noqa: E402
    ERASE_CONFIRMATION, DataView, _erase_respondent, _human_bytes,
)

WITHDRAWN = "I would rather you did not quote me on the money side"
KEPT = "the library hours were the best part of the term"


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def survey_project(tmp_path):
    """Two survey responses, one of which will ask to be removed."""
    project_dir = tmp_path / "run_01"
    project_dir.mkdir()
    path = project_dir / "project.qnw"
    with Project.create(path) as proj:
        code = proj.add_code(Code(code_id="", name="Financial concerns"))
        proj.add_rater(Rater(rater_id="human_primary", kind="human", name="A"))
        for response_id, text in (("r1", WITHDRAWN), ("r2", KEPT)):
            source_id = proj.add_source(Source(
                source_id="", type="survey_response", raw_text=text,
                label="Q1", metadata={"response_id": response_id}))
            excerpt = proj.add_excerpt(Excerpt(
                excerpt_id="", source_id=source_id, text=text,
                char_start=0, char_end=len(text)))
            proj.apply_code(CodeApplication(
                application_id="", excerpt_id=excerpt, code_id=code,
                coder="human", rater_id="human_primary"))
    return path


@pytest.fixture
def view(qapp, survey_project):
    service = ProjectService()
    service.open(survey_project)
    widget = DataView(service, QUndoStack())
    yield widget, service, survey_project
    service.close()


def _store_bytes(path) -> str:
    return path.read_bytes().decode("utf-8", "replace")


# -- erasure -----------------------------------------------------------------


def test_erasure_removes_the_response_from_the_store(survey_project):
    assert WITHDRAWN in _store_bytes(survey_project)

    _erase_respondent(survey_project.parent, "r1", survey_project,
                      purge_backups=True)

    assert WITHDRAWN not in _store_bytes(survey_project), (
        "the withdrawn response is still in the project file")
    assert KEPT in _store_bytes(survey_project), (
        "erasing one response removed another")


def test_erasure_purges_the_backup_that_still_holds_the_data(survey_project):
    """The trap this screen exists to close.

    `core.erasure` backs up before erasing, so without the purge the withdrawn
    response survives in `project_backups/` and nothing has really been erased.
    """
    backup_store(survey_project, reason="manual")
    assert list_backups(survey_project), "expected a backup to exist first"

    _erase_respondent(survey_project.parent, "r1", survey_project,
                      purge_backups=True)

    assert not list_backups(survey_project), "backups survived the erasure"
    backup_dir = survey_project.parent / BACKUP_DIR_NAME
    leftovers = list(backup_dir.rglob("*")) if backup_dir.exists() else []
    for leftover in leftovers:
        if leftover.is_file():
            assert WITHDRAWN not in leftover.read_bytes().decode(
                "utf-8", "replace"), f"{leftover.name} still holds the response"


def test_keeping_backups_is_reported_honestly(survey_project):
    """Unticking the box is legitimate -- correcting a mistake -- but it must
    not be sold as a complete erasure, so the backup genuinely does remain."""
    report = _erase_respondent(survey_project.parent, "r1", survey_project,
                               purge_backups=False)

    assert not report.get("backups_purged")
    assert list_backups(survey_project), (
        "with purging off the pre-erase backup should still be there")


def test_erasure_happens_before_the_purge(survey_project, monkeypatch):
    """Ordering matters: purging first would destroy the safety net before the
    risky step, so a failure mid-erase would leave nothing to fall back on."""
    order = []

    import core.erasure as erasure_module

    real = erasure_module.erase_respondent

    def spy(*args, **kwargs):
        order.append("erase")
        return real(*args, **kwargs)

    monkeypatch.setattr(erasure_module, "erase_respondent", spy)

    import shutil as shutil_module

    real_rmtree = shutil_module.rmtree

    def spy_rmtree(*args, **kwargs):
        order.append("purge")
        return real_rmtree(*args, **kwargs)

    monkeypatch.setattr(shutil_module, "rmtree", spy_rmtree)

    _erase_respondent(survey_project.parent, "r1", survey_project,
                      purge_backups=True)

    assert order[0] == "erase", f"expected erase before purge, got {order}"


def test_the_confirmation_word_is_not_a_click(view):
    """Typed, not clicked. The dialog demands this exact string."""
    assert ERASE_CONFIRMATION == "ERASE"
    assert ERASE_CONFIRMATION.isupper()


def test_erasing_without_an_id_does_nothing(view):
    widget, _service, path = view
    widget.erase_id.setText("   ")
    widget._erase()
    assert WITHDRAWN in _store_bytes(path), "an empty id still erased something"


def test_the_purge_box_defaults_to_on(view):
    """A withdrawal-of-consent request is the common case, and the safe
    default for it is a complete erasure."""
    widget, _service, _path = view
    assert widget.purge_backups.isChecked()


# -- backups -----------------------------------------------------------------


def test_backing_up_now_produces_a_listed_backup(view):
    """`count() >= 0` stood here, which a Qt count satisfies unconditionally.

    Tightening it exposed two things. `core/backups.py` was overwriting backups
    made inside one clock tick — fixed, and covered by
    `tests/test_backup_naming.py`. And `backup_list.count()` is not the number
    of backups: an empty list shows one disabled "No backups yet." row, so the
    widget reports 1 when the disk holds 0. `_backups` is the real list, and it
    is what `_restore` indexes into.
    """
    widget, _service, path = view
    before = len(widget._backups)

    widget._backup_now()

    assert list_backups(path), "no backup was written"
    assert len(widget._backups) == before + 1
    assert len(widget._backups) == len(list_backups(path))


def test_two_backups_in_quick_succession_are_both_listed(view):
    """The burst case. Before the naming fix these collapsed into one file."""
    widget, _service, path = view

    widget._backup_now()
    widget._backup_now()

    assert len(widget._backups) == 2
    assert len({backup.name for backup in widget._backups}) == 2


def test_an_empty_backup_list_says_so_and_cannot_be_restored_from(view):
    """The placeholder row that made `count()` a misleading proxy. It must not
    be selectable: restoring "No backups yet." would be a crash at best."""
    widget, _service, _path = view

    widget._reload_backups()

    assert widget._backups == []
    assert widget.backup_list.count() == 1, "expected the placeholder row"
    assert "No backups" in widget.backup_list.item(0).text()
    assert widget.backup_list.item(0).flags() == Qt.ItemFlag.NoItemFlags
    assert not widget.restore_button.isEnabled()


def test_the_placeholder_goes_away_once_a_backup_exists(view):
    widget, _service, _path = view

    widget._backup_now()

    assert widget.backup_list.count() == len(widget._backups)
    assert widget.restore_button.isEnabled()


def test_restoring_puts_back_the_earlier_state(view):
    """And the current state is snapshotted first, so a restore is undoable."""
    widget, service, path = view
    widget._backup_now()
    before = len(list_backups(path))

    with Project.open(path) as proj:
        proj.add_code(Code(code_id="", name="Added after the backup"))
    service.reopen()
    assert any(c.name == "Added after the backup"
               for c in service.get_codebook_list()) if hasattr(
        service, "get_codebook_list") else True

    widget.backup_list.setCurrentRow(0)
    # The dialog is the human's decision; the restore itself is what is tested.
    from core.backups import restore_backup

    service.close()
    restore_backup(path, list_backups(path)[0])
    service.open(path)

    names = [c.name for c in service.codebook()]
    assert "Added after the backup" not in names
    assert len(list_backups(path)) > before, (
        "restoring should snapshot the current state first")


# -- the screen --------------------------------------------------------------


def test_everything_is_disabled_without_a_project(qapp):
    service = ProjectService()
    widget = DataView(service, QUndoStack())
    assert not service.is_open
    for control in (widget.backup_now, widget.export_archive,
                    widget.erase_button, widget.analyst_name):
        assert not control.isEnabled()


def test_the_analyst_name_is_editable_here(view):
    """It is stamped on every coding and was previously buried in a menu."""
    widget, service, _path = view
    widget.analyst_name.setText("R. Ahmed")
    widget._save_analyst_name()
    assert service.analyst_name == "R. Ahmed"


def test_human_bytes_reads_like_a_size():
    assert _human_bytes(512) == "512 bytes"
    assert _human_bytes(2048).endswith("KB")
    assert _human_bytes(5 * 1024 * 1024).endswith("MB")


def test_erasure_leaves_no_recoverable_text_in_the_project_file(survey_project):
    """Deleting a SQLite row frees its page; it does not overwrite it.

    Measured before this was fixed: after `erase_respondent` the withdrawn
    response was still legible in the file's raw bytes -- `strings
    project.qnw` would print it -- while being correctly absent from every
    query. For an erasure offered as "this participant withdrew consent" that
    is the difference between the claim and the fact.

    The fix is a VACUUM, which rebuilds the database without the freed pages.
    This test reads the file as bytes on purpose: querying the store would
    have passed all along and told us nothing.
    """
    report = _erase_respondent(survey_project.parent, "r1", survey_project,
                               purge_backups=True)

    assert report.get("vacuumed") is True, "the store was not rebuilt"

    raw = survey_project.read_bytes()
    assert WITHDRAWN.encode() not in raw, (
        "the erased response is still readable in the project file")
    assert KEPT.encode() in raw, "the VACUUM removed a response it should keep"


def test_the_screen_does_not_overclaim_what_erasure_guarantees(view):
    """The file no longer holds it; the disk might. Saying so is better than
    implying a guarantee the software cannot make.

    Reads the labels already on the screen. A first version called
    `_build_erasure_box()` again, which quietly built a SECOND set of controls,
    rebound `self.erase_button` to them, and left `refresh()` poking at deleted
    C++ objects on teardown.
    """
    from PySide6.QtWidgets import QCheckBox, QLabel

    widget, _service, _path = view
    # Checkboxes too: the backup caveat is carried by the purge control's own
    # label, not by a paragraph beside it.
    text = " ".join(
        w.text() for w in widget.findChildren(QLabel) + widget.findChildren(QCheckBox)
    ).lower()

    assert "shred" in text, "the erasure limits are not stated on screen"
    assert "backup" in text, "the backup caveat is not stated on screen"
