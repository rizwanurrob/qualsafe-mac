"""Tests for in-app model management (v3.9.7, F4)."""

from __future__ import annotations

import os

import pytest

from core import model_manager as mm


class _FakeProc:
    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout, self.stderr, self.returncode = stdout, stderr, returncode


def test_download_model_success(monkeypatch):
    monkeypatch.setattr(mm.subprocess, "run",
                        lambda *a, **k: _FakeProc(stdout='{"ok": true, "model": "X", "role": "embedding", "error": ""}'))
    res = mm.download_model("X", "embedding")
    assert res["ok"] is True and res["model"] == "X" and res["role"] == "embedding"


def test_download_model_reports_failure_tail(monkeypatch):
    monkeypatch.setattr(mm.subprocess, "run",
                        lambda *a, **k: _FakeProc(stdout="noise", stderr="OSError: boom", returncode=1))
    res = mm.download_model("X", "embedding")
    assert res["ok"] is False and "boom" in res["message"]


def test_download_model_bad_role_raises():
    with pytest.raises(ValueError):
        mm.download_model("X", "not-a-role")


def test_download_model_empty_id_short_circuits(monkeypatch):
    called = {"ran": False}
    monkeypatch.setattr(mm.subprocess, "run",
                        lambda *a, **k: called.update(ran=True) or _FakeProc())
    res = mm.download_model("   ", "embedding")
    assert res["ok"] is False
    assert called["ran"] is False  # never spawns a process for an empty id


def test_download_does_not_touch_offline_env(monkeypatch):
    """The offline guarantee: downloading must not un-pin this process."""
    monkeypatch.setattr(mm.subprocess, "run", lambda *a, **k: _FakeProc(stdout='{"ok": true}'))
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "1")
    mm.download_model("X", "embedding")
    assert os.environ.get("HF_HUB_OFFLINE") == "1"
    assert os.environ.get("TRANSFORMERS_OFFLINE") == "1"


def test_download_builds_role_explicit_command(monkeypatch):
    captured = {}
    monkeypatch.setattr(mm.subprocess, "run",
                        lambda cmd, **k: captured.update(cmd=cmd) or _FakeProc(stdout='{"ok": true}'))
    mm.download_model("my/model", "zero-shot")
    cmd = captured["cmd"]
    assert "--model" in cmd and "my/model" in cmd
    assert "--role" in cmd and "zero-shot" in cmd
    assert "--json" in cmd


def test_configured_role_models_uses_defaults_when_unset():
    store = {"adv_embedding_model": "custom/emb"}
    got = mm.configured_role_models(lambda k, d: store.get(k, d))
    assert got["embedding"] == "custom/emb"
    assert got["sentiment"] == mm.DEFAULT_MODELS["sentiment"]
    assert got["zero-shot"] == mm.DEFAULT_MODELS["zero-shot"]


def test_remove_from_cache(monkeypatch):
    class _Rev:
        def __init__(self, h):
            self.commit_hash = h

    class _Repo:
        def __init__(self, rid, size, revs):
            self.repo_id, self.size_on_disk = rid, size
            self.revisions = [_Rev(h) for h in revs]

    class _Strategy:
        def execute(self):
            _Strategy.executed = True

    deleted = {}

    class _Cache:
        repos = [_Repo("keep/me", 100, ["a"]), _Repo("drop/me", 500, ["b", "c"])]

        def delete_revisions(self, *hashes):
            deleted["hashes"] = set(hashes)
            return _Strategy()

    import huggingface_hub
    monkeypatch.setattr(huggingface_hub, "scan_cache_dir", lambda: _Cache())
    freed = mm.remove_from_cache("drop/me")
    assert freed == 500
    assert deleted["hashes"] == {"b", "c"}


def test_remove_unknown_repo_frees_nothing(monkeypatch):
    class _Cache:
        repos = []

    import huggingface_hub
    monkeypatch.setattr(huggingface_hub, "scan_cache_dir", lambda: _Cache())
    assert mm.remove_from_cache("ghost/model") == 0
