"""
Tests for the session-inputs lifecycle (v3.1.1, Phase 0.2).

Versions <= 3.1 wrote a timestamped copy of every analyzed dataset into a global
`data/session_inputs/` folder that nothing cleaned up and no UI surface mentioned.
These tests pin the replacement: snapshots live inside the run directory that
consumes them, and the leftovers stay visible and deletable.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import streamlit_app
# The path constants and the functions that read them live in app.shared.io since
# the v4 Phase 0.1 split, so that is where they must be patched — patching the
# shell's re-exported name would rebind a different module global.
import app.shared.io as shared_io
from streamlit_app import delete_paths, save_df_for_pipeline


@pytest.fixture
def frame():
    return pd.DataFrame({"response_text": ["a", "b"], "question_text": ["q", "q"]})


class TestSaveDfForPipeline:
    def test_writes_into_the_given_dir(self, tmp_path, frame):
        run_dir = tmp_path / "run_20260715_120000"
        out = save_df_for_pipeline(frame, "input_snapshot", run_dir)
        assert out.parent == run_dir
        assert out.name == "input_snapshot.csv"
        assert out.exists()

    def test_creates_target_dir_if_absent(self, tmp_path, frame):
        target = tmp_path / "not_yet" / "nested"
        out = save_df_for_pipeline(frame, "input_snapshot", target)
        assert out.exists()

    def test_roundtrips_the_frame(self, tmp_path, frame):
        out = save_df_for_pipeline(frame, "input_snapshot", tmp_path)
        assert pd.read_csv(out)["response_text"].tolist() == ["a", "b"]

    def test_does_not_touch_the_global_session_input_dir(self, tmp_path, frame, monkeypatch):
        """The regression this phase exists to prevent."""
        fake_global = tmp_path / "session_inputs"
        monkeypatch.setattr(shared_io, "SESSION_INPUT_DIR", fake_global)

        save_df_for_pipeline(frame, "input_snapshot", tmp_path / "run_1")

        assert not fake_global.exists(), "snapshot leaked into the global session-inputs dir"

    def test_filename_is_stable_so_reruns_overwrite(self, tmp_path, frame):
        """A timestamped name would pile up one copy of the data per click."""
        target = tmp_path / "output_iterative"
        first = save_df_for_pipeline(frame, "iterative_input", target)
        second = save_df_for_pipeline(frame, "iterative_input", target)
        assert first == second
        assert len(list(target.glob("*.csv"))) == 1


class TestLegacyDiscoveryAndPurge:
    def test_finds_legacy_snapshots(self, tmp_path, monkeypatch, frame):
        legacy_dir = tmp_path / "session_inputs"
        legacy_dir.mkdir()
        (legacy_dir / "streamlit_input_20260101_101010.csv").write_text("a,b\n1,2\n")
        (legacy_dir / "iterative_input_20260102_101010.csv").write_text("a,b\n1,2\n")
        monkeypatch.setattr(shared_io, "SESSION_INPUT_DIR", legacy_dir)

        found = shared_io.legacy_session_input_files()
        assert len(found) == 2

    def test_missing_legacy_dir_is_not_an_error(self, tmp_path, monkeypatch):
        monkeypatch.setattr(shared_io, "SESSION_INPUT_DIR", tmp_path / "nope")
        assert shared_io.legacy_session_input_files() == []

    def test_purge_removes_files(self, tmp_path):
        a = tmp_path / "a.csv"
        b = tmp_path / "b.csv"
        a.write_text("x")
        b.write_text("y")

        result = delete_paths([a, b])

        assert sorted(result["deleted"]) == ["a.csv", "b.csv"]
        assert result["failed"] == []
        assert not a.exists() and not b.exists()

    def test_purge_reports_failures_instead_of_raising(self, tmp_path):
        """Windows file locks must not turn a purge into a stack trace."""
        missing = tmp_path / "gone.csv"
        present = tmp_path / "here.csv"
        present.write_text("x")

        result = delete_paths([missing, present])

        assert result["deleted"] == ["here.csv"]
        assert len(result["failed"]) == 1
        assert "gone.csv" in result["failed"][0]


class TestWorkingDataInventory:
    def test_lists_legacy_and_run_files(self, tmp_path, monkeypatch):
        legacy_dir = tmp_path / "session_inputs"
        legacy_dir.mkdir()
        (legacy_dir / "old_input_20260101_101010.csv").write_text("a\n1\n")

        out_dir = tmp_path / "output_streamlit"
        (out_dir / "run_20260715_120000").mkdir(parents=True)
        (out_dir / "run_20260715_120000" / "input_snapshot.csv").write_text("a\n1\n")

        monkeypatch.setattr(shared_io, "SESSION_INPUT_DIR", legacy_dir)
        monkeypatch.setattr(shared_io, "STREAMLIT_OUTPUT_DIR", out_dir)

        table = shared_io.describe_working_files()

        assert len(table) == 2
        locations = set(table["location"])
        assert "data/session_inputs (legacy)" in locations
        assert "output_streamlit/run_20260715_120000" in locations

    def test_empty_when_nothing_written(self, tmp_path, monkeypatch):
        monkeypatch.setattr(shared_io, "SESSION_INPUT_DIR", tmp_path / "a")
        monkeypatch.setattr(shared_io, "STREAMLIT_OUTPUT_DIR", tmp_path / "b")
        assert shared_io.describe_working_files().empty
