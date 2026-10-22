"""Tests for whole-project archive export/import (v3.9.1)."""

from __future__ import annotations

import io
import zipfile

import pytest

from core.model import Source
from core.project import Project
from core.project_archive import export_project_archive, import_project_archive
from core.reconstruct import dataframe_from_store


def _make_project(dir_path):
    """A realistic project folder: store + run output + a backup + a cache."""
    dir_path.mkdir(parents=True, exist_ok=True)
    store = dir_path / "project.qnw"
    with Project.create(store) as proj:
        src = Source(source_id="s1", type="survey_response", raw_text="hello world",
                     label="Q1", metadata={"response_id": "1", "question_text": "Q1"})
        proj.add_source(src)
        proj.add_whole_response_excerpt(src)
    (dir_path / "responses_scored.csv").write_text("response_id,x\n1,2\n", encoding="utf-8")
    (dir_path / "run_report.md").write_text("# report", encoding="utf-8")
    backups = dir_path / "project_backups"
    backups.mkdir()
    (backups / "qnw_20260101_000000.qnw").write_text("SENSITIVE PRE-ERASURE COPY", encoding="utf-8")
    (dir_path / "embeddings.npy").write_bytes(b"\x00\x01\x02")
    return store


def _names(data: bytes):
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        return [n.replace("\\", "/") for n in zf.namelist()]


def test_archive_includes_store_and_outputs(tmp_path):
    store = _make_project(tmp_path / "run_x")
    names = _names(export_project_archive(store))
    assert any(n.endswith("run_x/project.qnw") for n in names)
    assert any(n.endswith("run_x/responses_scored.csv") for n in names)
    assert any(n.endswith("run_x/run_report.md") for n in names)


def test_archive_excludes_backups_and_caches(tmp_path):
    store = _make_project(tmp_path / "run_x")
    names = _names(export_project_archive(store))
    assert not any("project_backups" in n for n in names), "backups must not ship"
    assert not any(n.endswith(".npy") for n in names), "embedding caches must not ship"


def test_roundtrip_import_finds_store_and_data(tmp_path):
    store = _make_project(tmp_path / "run_x")
    data = export_project_archive(store)

    dest = tmp_path / "other_install"
    imported = import_project_archive(data, dest, name_hint="run_x")
    assert imported.exists() and imported.suffix == ".qnw"
    assert dest in imported.parents
    # The store opens and its response text survived the round trip.
    df = dataframe_from_store(imported)
    assert df["response_text"].iloc[0] == "hello world"


def test_import_rejects_zip_slip(tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../escape.qnw", "x")
    with pytest.raises(ValueError):
        import_project_archive(buf.getvalue(), tmp_path / "dest")


def test_import_without_store_raises(tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("proj/readme.txt", "no store here")
    with pytest.raises(ValueError):
        import_project_archive(buf.getvalue(), tmp_path / "dest")


def test_export_missing_store_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        export_project_archive(tmp_path / "nope.qnw")
