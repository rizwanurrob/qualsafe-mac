"""
Tests for local-mode enforcement (v3.1.1, Phase 0.1).

The privacy claim in the README and the run manifest rests on two things being
true: the offline env vars get set before any model loads, and the only code path
that lifts them is the dedicated setup tool. These tests pin both, plus the lazy
imports (Phase 0.0) that make the ordering achievable in the first place.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.offline import (
    ALWAYS_VARS,
    OFFLINE_VARS,
    enforce_local_mode,
    human_size,
    is_offline_enforced,
    local_mode_status,
    model_cache_status,
)

ALL_VARS = (*ALWAYS_VARS, *OFFLINE_VARS)


@pytest.fixture
def clean_env(monkeypatch):
    """Remove every managed var so each test starts from a known state."""
    for var in ALL_VARS:
        monkeypatch.delenv(var, raising=False)
    return monkeypatch


class TestEnforceLocalMode:
    def test_sets_all_four_vars_by_default(self, clean_env):
        enforce_local_mode()
        for var in ALL_VARS:
            assert os.environ[var] == "1", f"{var} not set"

    def test_allow_downloads_lifts_offline_but_keeps_telemetry_off(self, clean_env):
        """The setup tool must be able to reach the hub — without turning telemetry on."""
        enforce_local_mode(allow_downloads=True)
        for var in ALWAYS_VARS:
            assert os.environ[var] == "1"
        for var in OFFLINE_VARS:
            assert var not in os.environ

    def test_respects_user_override(self, clean_env):
        """setdefault, not assignment: a user on a proxy can opt out deliberately."""
        clean_env.setenv("HF_HUB_OFFLINE", "0")
        enforce_local_mode()
        assert os.environ["HF_HUB_OFFLINE"] == "0"
        # ...but the vars they didn't set still get our defaults.
        assert os.environ["TRANSFORMERS_OFFLINE"] == "1"

    def test_is_idempotent(self, clean_env):
        enforce_local_mode()
        enforce_local_mode()
        for var in ALL_VARS:
            assert os.environ[var] == "1"

    def test_is_offline_enforced_reflects_state(self, clean_env):
        assert is_offline_enforced() is False
        enforce_local_mode()
        assert is_offline_enforced() is True

    def test_status_reports_every_managed_var(self, clean_env):
        enforce_local_mode()
        status = local_mode_status()
        assert set(status) == set(ALL_VARS)
        assert all(v == "1" for v in status.values())


class TestSetupToolIsTheOnlyDownloadPath:
    def test_download_models_passes_allow_downloads(self):
        """tools/download_models.py is the single place the offline flags come off."""
        from tools import download_models

        with patch("tools.download_models.enforce_local_mode") as mock_enforce:
            # Fail fast inside download() right after the enforce call; we only
            # care which flag it was given.
            with patch.dict(sys.modules, {"sentence_transformers": None, "transformers": None}):
                try:
                    download_models.download(
                        {
                            "embedding_model": "m1",
                            "sentiment_model": "m2",
                            "zero_shot_model": "m3",
                        }
                    )
                except Exception:  # noqa: BLE001 - import failure is expected here
                    pass

        mock_enforce.assert_called_once_with(allow_downloads=True)

    def test_entry_points_call_enforce_without_downloads(self):
        """Grep-level guard: no analysis entry point may allow downloads.

        The Streamlit entry point arms offline mode in `app/__init__.py` rather
        than in the shell (v4 Phase 0.1): every page module import goes through
        the package, so arming it there makes the guarantee independent of the
        order in which the shell imports pages.
        """
        root = Path(__file__).resolve().parents[1]
        for name in ("app/__init__.py", "analyze_survey.py", "iterative_supervised_thematic.py"):
            text = (root / name).read_text(encoding="utf-8")
            assert "enforce_local_mode()" in text, f"{name} does not enforce local mode"

        # No UI module may lift the offline flags; only the download subprocess may.
        ui_files = [root / "streamlit_app.py"] + sorted(root.glob("app/**/*.py"))
        for path in ui_files:
            text = path.read_text(encoding="utf-8")
            assert "allow_downloads=True" not in text, f"{path.name} must not allow downloads"

    def test_importing_the_app_package_arms_offline_mode(self):
        """Behavioural counterpart to the grep above."""
        import os

        import app  # noqa: F401 - the import is the assertion

        assert os.environ.get("HF_HUB_OFFLINE") == "1"
        assert os.environ.get("TRANSFORMERS_OFFLINE") == "1"


class TestLazyImports:
    """Phase 0.0 — the heavy imports must not fire at module import time."""

    def test_analyze_survey_does_not_import_torch_stack_at_module_scope(self):
        root = Path(__file__).resolve().parents[1]
        text = (root / "analyze_survey.py").read_text(encoding="utf-8")
        # Module-scope (column 0) imports of the heavy stack are what we forbid;
        # the deferred ones inside functions are indented.
        assert "\nfrom sentence_transformers import" not in text
        assert "\nfrom transformers import" not in text

    def test_mock_points_survive(self):
        """Tests patch these names; they must exist as module attributes."""
        import analyze_survey

        assert hasattr(analyze_survey, "pipeline")
        assert hasattr(analyze_survey, "SentenceTransformer")

    def test_get_pipeline_returns_patched_value_without_importing(self):
        import analyze_survey

        sentinel = object()
        with patch("analyze_survey.pipeline", sentinel):
            assert analyze_survey._get_pipeline() is sentinel

    def test_get_sentence_transformer_returns_patched_value(self):
        import analyze_survey

        sentinel = object()
        with patch("analyze_survey.SentenceTransformer", sentinel):
            assert analyze_survey._get_sentence_transformer() is sentinel


class TestMissingModelError:
    def test_missing_cache_error_is_translated(self):
        import analyze_survey

        def boom():
            raise OSError("Cannot find the requested files in the cached path.")

        with pytest.raises(analyze_survey.ModelNotDownloadedError) as exc:
            analyze_survey._load_model("facebook/bart-large-mnli", boom)

        msg = str(exc.value)
        assert "facebook/bart-large-mnli" in msg
        assert "download_models.py" in msg

    def test_unrelated_errors_pass_through_untouched(self):
        """Don't swallow real bugs behind a friendly download message."""
        import analyze_survey

        def boom():
            raise OSError("disk on fire")

        with pytest.raises(OSError, match="disk on fire"):
            analyze_survey._load_model("m", boom)

    def test_successful_load_returns_value(self):
        import analyze_survey

        assert analyze_survey._load_model("m", lambda: "model") == "model"


class TestCacheStatus:
    def test_unreadable_cache_reports_unknown_rather_than_raising(self):
        with patch.dict(sys.modules, {"huggingface_hub": None}):
            rows = model_cache_status(["a", "b"])
        assert len(rows) == 2
        assert all(r["cached"] is None for r in rows)

    def test_human_size_formats(self):
        assert human_size(512) == "512.0 B"
        assert human_size(2048) == "2.0 KB"
        assert "GB" in human_size(3 * 1024**3)


def test_a_missing_cache_folder_means_not_downloaded_not_unreadable(monkeypatch, tmp_path):
    """A fresh machine has no Hugging Face cache folder; the panel must say so plainly."""
    import huggingface_hub
    from huggingface_hub.errors import CacheNotFound
    from core import offline

    def _missing(*args, **kwargs):
        raise CacheNotFound("Cache directory not found", cache_dir=str(tmp_path / "nope"))

    monkeypatch.setattr(huggingface_hub, "scan_cache_dir", _missing)
    result = offline.model_cache_status(["some/model"])
    assert result[0]["cached"] is False and result[0]["detail"] == "not downloaded"


def test_a_download_clears_the_offline_flags_it_inherited(monkeypatch):
    """The program arms offline mode in its own environment; a download is a child process that inherits it.
    Not setting the flags is not enough, or the hub refuses ("We couldn't connect to huggingface.co")."""
    from core import offline

    for var in offline.OFFLINE_VARS:
        monkeypatch.setenv(var, "1")
    offline.enforce_local_mode(allow_downloads=True)
    assert not any(v in os.environ for v in offline.OFFLINE_VARS)
    assert os.environ.get("HF_HUB_DISABLE_TELEMETRY") == "1"          # telemetry stays off


def test_analysis_stays_offline_when_downloads_are_not_allowed(monkeypatch):
    from core import offline

    for var in offline.OFFLINE_VARS:
        monkeypatch.delenv(var, raising=False)
    offline.enforce_local_mode()
    assert offline.is_offline_enforced()


def test_the_download_child_process_is_started_without_the_offline_flags(monkeypatch):
    from core import model_manager, offline

    for var in offline.OFFLINE_VARS:
        monkeypatch.setenv(var, "1")
    seen = {}

    class _Done:
        stdout = '{"ok": true, "model": "m", "role": "embedding", "error": ""}'
        stderr = ""
        returncode = 0

    def fake_run(cmd, **kwargs):
        seen["env"] = kwargs.get("env")
        return _Done()

    monkeypatch.setattr(model_manager.subprocess, "run", fake_run)
    result = model_manager.download_model("sentence-transformers/all-MiniLM-L6-v2", "embedding")
    assert result["ok"]
    assert seen["env"] is not None
    assert not any(v in seen["env"] for v in offline.OFFLINE_VARS)
    assert os.environ["HF_HUB_OFFLINE"] == "1"                          # this process stays offline
