"""
Tests for v3.8.0 (P0) — Lab autosave, workspace resume, store backups.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.backups import backup_store, list_backups, restore_backup
from core.model import Code, Source
from core.project import Project, new_id
from core.workspace import (
    WORKSPACE_KEYS,
    clear_workspace,
    derive_resume_path,
    load_workspace,
    save_workspace,
)


@pytest.fixture(autouse=True)
def _tmp_settings_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("QNW_SETTINGS_DIR", str(tmp_path))
    return tmp_path


# ── 8.1 autosave serialization ───────────────────────────────────────────────

class TestBuildSavedSample:
    def test_labels_and_notes_applied(self):
        from streamlit_app import build_saved_sample

        df = pd.DataFrame({"response_id": ["1", "2"], "question_text": ["Q", "Q"],
                           "response_text": ["a", "b"], "human_labels": ["", ""],
                           "coder_notes": ["", ""]})
        out = build_saved_sample(df, {"1": ["Cost", "Belonging"]}, {"2": "check later"})
        assert out.loc[out["response_id"] == "1", "human_labels"].iloc[0] == "Cost|Belonging"
        assert out.loc[out["response_id"] == "2", "coder_notes"].iloc[0] == "check later"
        assert out.loc[out["response_id"] == "2", "human_labels"].iloc[0] == ""

    def test_roundtrips_through_lab_reader(self, tmp_path):
        """Autosaved file must reload exactly (ids stable, labels intact)."""
        import streamlit_app as app

        df = pd.DataFrame({"response_id": ["101", "102"], "question_text": ["Q", "Q"],
                           "response_text": ["a", "b"], "human_labels": ["", ""],
                           "coder_notes": ["", ""]})
        out = app.build_saved_sample(df, {"101": ["X"]}, {})
        out.to_csv(tmp_path / "coding_sample.csv", index=False)
        back = app.load_coding_sample_df(tmp_path)
        assert back["response_id"].tolist() == ["101", "102"]
        assert back["human_labels"].tolist() == ["X", ""]


# ── 8.2 workspace resume ─────────────────────────────────────────────────────

class TestWorkspace:
    def _state(self, tmp_path):
        data = tmp_path / "input.csv"
        data.write_text("response_id,question_text,response_text\n1,Q,hello\n", encoding="utf-8")
        return {
            "input_source": f"folder:{data}",
            "input_file_path": "",
            "ingestion_mode": "long",
            "text_column": "response_text",
            "question_column": "question_text",
            "id_column": "response_id",
            "theme_labels_text": "Cost\nBelonging",
            "descriptor_columns": [],
        }

    def test_roundtrip(self, tmp_path):
        save_workspace(self._state(tmp_path))
        ws = load_workspace()
        assert ws["text_column"] == "response_text"
        assert ws["theme_labels_text"] == "Cost\nBelonging"
        assert Path(ws["resume_path"]).exists()

    def test_no_resume_path_means_no_save(self, tmp_path):
        state = self._state(tmp_path)
        state["input_source"] = "upload:mystery.csv"  # no reachable path
        assert save_workspace(state) is None
        assert load_workspace() == {}

    def test_stale_workspace_ignored(self, tmp_path):
        state = self._state(tmp_path)
        save_workspace(state)
        Path(state["input_source"][len("folder:"):]).unlink()  # data file gone
        assert load_workspace() == {}  # never offer a resume we can't honor

    def test_never_stores_response_data(self, tmp_path):
        save_workspace(self._state(tmp_path))
        raw = json.loads((Path(str(_load_ws_path())).read_text(encoding="utf-8")))
        assert "hello" not in json.dumps(raw)  # data content never persisted
        assert set(raw) <= set(WORKSPACE_KEYS)

    def test_clear(self, tmp_path):
        save_workspace(self._state(tmp_path))
        clear_workspace()
        assert load_workspace() == {}

    def test_derive_resume_path(self, tmp_path):
        data = tmp_path / "d.csv"
        data.write_text("a\n1\n", encoding="utf-8")
        assert derive_resume_path(f"folder:{data}") == str(data)
        assert derive_resume_path("upload:x.csv", str(data)) == str(data)
        assert derive_resume_path("upload:x.csv", "") == ""


def _load_ws_path():
    from core.workspace import _workspace_path

    return _workspace_path()


# ── 8.3 backups ──────────────────────────────────────────────────────────────

class TestBackups:
    def _store(self, tmp_path, name="p.qnw"):
        path = tmp_path / name
        with Project.create(path) as p:
            p.add_code(Code(code_id="", name="A"))
        return path

    def test_backup_and_list(self, tmp_path):
        store = self._store(tmp_path)
        result = backup_store(store, reason="manual")
        assert result is not None and result.exists()
        assert list_backups(store) == [result]
        assert "manual" in result.name

    def test_prune_keeps_newest(self, tmp_path):
        store = self._store(tmp_path)
        made = []
        for i in range(7):
            b = backup_store(store, reason=f"r{i}", keep=5)
            time.sleep(0.02)  # distinct mtimes for deterministic pruning order
            made.append(b)
        remaining = list_backups(store)
        assert len(remaining) == 5
        assert remaining[0] == made[-1]  # newest survived

    def test_restore_replaces_store_and_is_undoable(self, tmp_path):
        store = self._store(tmp_path)
        backup = backup_store(store, reason="checkpoint")
        # Mutate the store after the backup.
        with Project.open(store) as p:
            p.add_code(Code(code_id="", name="B"))
        restore_backup(store, backup)
        with Project.open(store) as p:
            names = [c.name for c in p.get_codebook()]
        assert names == ["A"]  # back to checkpoint state
        # The pre-restore state was itself backed up.
        assert any("pre_restore" in b.name for b in list_backups(store))

    def test_missing_store_returns_none(self, tmp_path):
        assert backup_store(tmp_path / "nope.qnw") is None

    def test_erasure_takes_a_backup_first(self, tmp_path):
        from core.erasure import erase_respondent

        project_dir = tmp_path / "run"
        project_dir.mkdir()
        store = project_dir / "project.qnw"
        with Project.create(store) as p:
            src = Source(source_id=new_id("src"), type="survey_response", raw_text="text",
                         label="Q", metadata={"response_id": "r1", "question_text": "Q"})
            p.add_source(src)
            p.add_whole_response_excerpt(src)
        report = erase_respondent(project_dir, "r1")
        assert report["backup"] is not None
        assert Path(report["backup"]).exists()

    def test_team_merge_takes_a_backup(self, tmp_path):
        from core.assignments import merge_coder_samples

        store = self._store(tmp_path, "team.qnw")
        csv = tmp_path / "coder.csv"
        pd.DataFrame({"response_id": ["1"], "human_labels": ["A"]}).to_csv(csv, index=False)
        merge_coder_samples(store, {"Alice": csv}, question_text="Q")
        assert any("pre_team_merge" in b.name for b in list_backups(store))
