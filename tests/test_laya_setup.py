"""engines/laya_setup.py -- the thin in-process wrapper over
tools/setup_laya_env.py. Mocks that script's functions directly rather than
subprocess, since laya_setup.install() itself shells out to it (one more layer
out); tools/test_setup_laya_env.py covers that script's own subprocess logic."""

from __future__ import annotations

import engines.laya_setup as ls


def test_install_instructions_names_what_it_does_and_does_not_do():
    info = ls.install_instructions()
    said = " ".join(info["what_it_does"]).lower()
    assert "own folder" in said and "uploaded" in said
    assert info["checkpoints"]
    assert all("model" in c for c in info["checkpoints"])


def test_checkpoints_include_the_documented_three():
    labels = {c["label"] for c in ls.CHECKPOINTS}
    assert labels == {"English", "Multilingual", "Typed decisions"}


def test_isolated_python_path_is_none_when_not_ready(tmp_path, monkeypatch):
    monkeypatch.setattr(ls, "installation_status",
                        lambda env_dir=None: {"state": "not_installed", "python": None})
    assert ls.isolated_python_path() is None


def test_isolated_python_path_returns_the_interpreter_when_ready(monkeypatch):
    monkeypatch.setattr(ls, "installation_status",
                        lambda env_dir=None: {"state": "ready", "python": "/some/python"})
    assert ls.isolated_python_path() == "/some/python"


def test_install_parses_the_last_json_line_from_the_subprocess(monkeypatch):
    class _FakeProc:
        stdout = 'some log noise\n{"ok": true, "laya_version": "0.3.3"}\n'
        stderr = ""
        returncode = 0

    monkeypatch.setattr(ls.subprocess, "run", lambda *a, **k: _FakeProc())
    result = ls.install()
    assert result["ok"] is True
    assert result["laya_version"] == "0.3.3"


def test_install_reports_stderr_when_no_json_is_found(monkeypatch):
    class _FakeProc:
        stdout = "no json here"
        stderr = "OSError: disk full"
        returncode = 1

    monkeypatch.setattr(ls.subprocess, "run", lambda *a, **k: _FakeProc())
    result = ls.install()
    assert result["ok"] is False
    assert "disk full" in result["error"]


def test_install_handles_a_timeout(monkeypatch):
    import subprocess as sp

    def raise_timeout(*a, **k):
        raise sp.TimeoutExpired(cmd="x", timeout=1)

    monkeypatch.setattr(ls.subprocess, "run", raise_timeout)
    result = ls.install(timeout=1)
    assert result["ok"] is False
    assert "timed out" in result["error"].lower()


def test_uninstall_delegates_to_the_setup_script(monkeypatch):
    calls = {}

    def fake_remove(env_dir):
        calls["called_with"] = env_dir
        return True

    import tools.setup_laya_env as sle
    monkeypatch.setattr(sle, "remove", fake_remove)
    assert ls.uninstall() is True
    assert calls["called_with"] is not None


def test_the_model_download_step_starts_without_the_offline_flags(monkeypatch):
    """The program arms offline mode and a child inherits it; the one step that must reach the hub clears it."""
    from tools import setup_laya_env as sle

    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "1")
    seen = []

    class _Done:
        returncode = 0
        stdout = stderr = ""

    monkeypatch.setattr(sle.subprocess, "run", lambda cmd, **kw: seen.append(kw["env"]) or _Done())
    monkeypatch.setattr(sle, "app_python", lambda: "python")
    sle._run(["-c", "pass"])                                  # an ordinary step keeps the flags
    sle._run(["-c", "pass"], online=True)                     # the download step does not
    assert seen[0].get("HF_HUB_OFFLINE") == "1"
    assert "HF_HUB_OFFLINE" not in seen[1] and "TRANSFORMERS_OFFLINE" not in seen[1]
