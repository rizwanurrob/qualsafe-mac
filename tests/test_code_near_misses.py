"""Two more example lists on a code (book-audit F7, store format v10): "close, but no" and "unusual, but yes"."""

from __future__ import annotations

import json
import os
import sqlite3

import pytest

from core.codebook_io import export_codebook_yaml, import_codebook_yaml
from core.model import Code
from core.project import SCHEMA_VERSION, Project


def _project(tmp_path, name="p.qnw"):
    return Project.create(tmp_path / name)


def test_the_format_version_is_at_least_ten():
    assert SCHEMA_VERSION >= 10


def test_the_two_lists_are_kept_and_the_log_records_counts_not_text(tmp_path):
    secret = "my landlord raised the rent again"
    project = _project(tmp_path)
    cid = project.add_code(Code(code_id="", name="Cost"))
    project.set_code_structured_fields(cid, near_misses=[secret, "prices in general"],
                                       atypical_examples=["we ate rice for a week"])
    code = project.get_codebook()[0]
    assert code.near_misses == [secret, "prices in general"]
    assert code.atypical_examples == ["we ate rice for a week"]
    assert code.examples == []                      # the older list is untouched
    events = json.dumps(project.list_events())
    assert secret not in events and "2 close-but-no example(s)" in events
    project.close()


def test_a_v9_store_opens_with_empty_lists_and_is_upgraded(tmp_path):
    project = _project(tmp_path)
    project.add_code(Code(code_id="", name="Cost", definition="Money worries"))
    path = project.path if hasattr(project, "path") else tmp_path / "p.qnw"
    project.close()
    con = sqlite3.connect(path)
    con.execute("ALTER TABLE codes DROP COLUMN near_misses_json")
    con.execute("ALTER TABLE codes DROP COLUMN atypical_json")
    con.execute("UPDATE meta SET value='9' WHERE key='schema_version'")
    con.commit()
    con.close()
    with Project.open(path) as proj:
        code = proj.get_codebook()[0]
        assert code.name == "Cost" and code.near_misses == [] and code.atypical_examples == []
        proj.set_code_structured_fields(code.code_id, near_misses=["x"])
        assert proj.get_codebook()[0].near_misses == ["x"]
    con = sqlite3.connect(path)
    version = int(con.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0])
    con.close()
    assert version == SCHEMA_VERSION


def test_a_newer_file_is_refused_rather_than_guessed_at(tmp_path):
    project = _project(tmp_path)
    path = tmp_path / "p.qnw"
    project.close()
    con = sqlite3.connect(path)
    con.execute("UPDATE meta SET value=? WHERE key='schema_version'", (str(SCHEMA_VERSION + 1),))
    con.commit()
    con.close()
    with pytest.raises(Exception):
        Project.open(path).close()


def test_the_codebook_file_carries_the_new_lists_both_ways(tmp_path):
    project = _project(tmp_path)
    cid = project.add_code(Code(code_id="", name="Cost"))
    project.set_code_structured_fields(cid, near_misses=["prices in general"],
                                       atypical_examples=["we ate rice for a week"])
    text = export_codebook_yaml(project)
    assert "near_misses" in text and "atypical_examples" in text
    other = _project(tmp_path, "q.qnw")
    result = import_codebook_yaml(other, text)
    assert result["created"] == ["Cost"]
    code = other.get_codebook()[0]
    assert code.near_misses == ["prices in general"] and code.atypical_examples == ["we ate rice for a week"]
    project.close()
    other.close()


pytest.importorskip("PySide6", reason="Qt front end not installed")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QUndoStack  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from qualsafe_qt.services.project_service import ProjectService  # noqa: E402
from qualsafe_qt.views.codebook_view import CodebookView  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_the_desktop_code_editor_saves_and_reloads_both_lists(app, tmp_path):
    service = ProjectService()
    service.create(tmp_path / "d.qnw")
    cid = service.project.add_code(Code(code_id="", name="Cost"))
    view = CodebookView(service, QUndoStack())
    view.show()
    view._select_code(cid)
    app.processEvents()
    view.near_miss_edit.setPlainText("prices in general\n\nrent talk without hardship")
    view.atypical_edit.setPlainText("we ate rice for a week")
    view._save_code()
    app.processEvents()
    stored = service.get_code(cid)
    assert stored.near_misses == ["prices in general", "rent talk without hardship"]
    assert stored.atypical_examples == ["we ate rice for a week"]
    view._select_code(cid)
    app.processEvents()
    assert view.near_miss_edit.toPlainText().splitlines()[0] == "prices in general"
    view.close()
    service.close()
