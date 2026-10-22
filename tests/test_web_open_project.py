"""Opening a project file on the web (dry-run finding F8): a file someone gives you can be opened from Settings."""

from __future__ import annotations

import pytest

from app.data_management import open_project_bytes
from core.model import Code
from core.project import Project


def test_a_project_file_is_kept_in_its_own_folder_and_opens(tmp_path):
    source = tmp_path / "given.qnw"
    with Project.create(source) as proj:
        proj.add_code(Code(code_id="", name="Cost", definition="Money."))
    target = open_project_bytes("given.qnw", source.read_bytes(), output_dir=tmp_path / "out")
    assert target.name == "project.qnw" and target.parent.name.startswith("opened_given_")
    with Project.open(target) as proj:
        assert [c.name for c in proj.get_codebook()] == ["Cost"]


def test_something_that_is_not_a_project_is_refused_and_leaves_nothing(tmp_path):
    out = tmp_path / "out"
    with pytest.raises(ValueError, match="could not be opened as a project"):
        open_project_bytes("notes.qnw", b"just some words", output_dir=out)
    assert not out.exists() or list(out.iterdir()) == []


def test_without_a_project_the_explore_step_offers_to_open_one():
    from tests import webkit

    at = webkit.start("survey")
    at.session_state["step_surveys"] = "explore"
    at = webkit.go(at, "Analysis")
    assert not at.exception, at.exception
    assert any(b.key == "an_open_project" for b in at.button)
