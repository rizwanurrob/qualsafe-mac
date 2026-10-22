"""tools/setup_laya_env.py -- against a fake subprocess, never a real install. This is the one
script that runs `pip install laya`; these tests verify its logic without running that command."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import tools.setup_laya_env as sle


class _Proc:
    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout, self.stderr, self.returncode = stdout, stderr, returncode


def _laya_folder(tmp_path, version="0.3.28"):
    pkg = tmp_path / "laya_pkg"
    (pkg / "laya").mkdir(parents=True)
    if version:
        (pkg / f"laya-{version}.dist-info").mkdir()
    return pkg


def _put_model(cache: Path) -> None:
    snap = cache / "models--convaiinnovations--laya" / "snapshots" / "abc"
    snap.mkdir(parents=True, exist_ok=True)
    (snap / "model.safetensors").write_text("x")


def _fake(monkeypatch, tmp_path, *, engine=True, model=True, pip_ok=True, download_ok=True, log=None):
    """A subprocess.run that answers like pip and the model download would; an engine that is or
    is not installed; and a Hugging Face cache that does or does not hold the model."""
    cache = tmp_path / "hub"
    monkeypatch.setenv("HF_HUB_CACHE", str(cache))
    monkeypatch.setattr(sle, "has_engine", lambda: engine)
    if model:
        _put_model(cache)

    def run(cmd, **kwargs):
        text = " ".join(map(str, cmd))
        if log is not None:
            log.append((text, kwargs))
        if "pip" in cmd:
            if pip_ok:
                folder = Path(cmd[cmd.index("--target") + 1])
                (folder / "laya").mkdir(parents=True, exist_ok=True)
                (folder / "laya-0.3.28.dist-info").mkdir(exist_ok=True)
            return _Proc(returncode=0 if pip_ok else 1, stderr="" if pip_ok else "network unreachable")
        if "snapshot_download" in text:
            if download_ok:
                _put_model(cache)
            return _Proc(returncode=0 if download_ok else 1, stderr="" if download_ok else "offline")
        return _Proc()
    monkeypatch.setattr(sle.subprocess, "run", run)


# ── what is pinned and where it goes ────────────────────────────────────────

def test_the_version_is_pinned_to_the_one_that_was_tested():
    assert sle.LAYA_REQUIREMENT == "laya==0.3.28"


def test_the_package_goes_in_its_own_folder_in_the_users_home():
    assert sle.PKG_DIR.name == "laya_pkg" and ".qualsafe" in sle.PKG_DIR.parts


def test_the_worker_python_has_a_console(tmp_path, monkeypatch):
    (tmp_path / "pythonw.exe").write_text("")
    (tmp_path / "python.exe").write_text("")
    monkeypatch.setattr(sle.sys, "executable", str(tmp_path / "pythonw.exe"))
    assert sle.app_python().endswith("python.exe") and not sle.app_python().endswith("pythonw.exe")
    monkeypatch.setattr(sle.sys, "executable", str(tmp_path / "python.exe"))
    assert sle.app_python() == str(tmp_path / "python.exe")


def test_the_worker_environment_puts_the_package_first_and_keeps_the_rest(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHONPATH", "already_here")
    env = sle.worker_env(tmp_path)
    assert env["PYTHONPATH"].split(os.pathsep) == [str(tmp_path), "already_here"]


# ── check: quick, and starts nothing ────────────────────────────────────────

def test_not_installed_when_there_is_no_package(tmp_path):
    status = sle.check(tmp_path / "nowhere")
    assert status["state"] == "not_installed" and status["laya_version"] is None


def test_needs_the_analysis_engine_when_torch_is_missing(tmp_path, monkeypatch):
    _fake(monkeypatch, tmp_path, engine=False)
    status = sle.check(_laya_folder(tmp_path))
    assert status["state"] == "needs_engine" and status["laya_version"] == "0.3.28"


def test_ready_reads_the_version_from_the_package_folder(tmp_path, monkeypatch):
    _fake(monkeypatch, tmp_path)
    status = sle.check(_laya_folder(tmp_path, version="0.3.28"))
    assert status["state"] == "ready" and status["laya_version"] == "0.3.28"
    assert status["python"] == sle.app_python()


def test_broken_when_the_folder_has_no_version_record(tmp_path, monkeypatch):
    _fake(monkeypatch, tmp_path)
    assert sle.check(_laya_folder(tmp_path, version=""))["state"] == "broken"


def test_the_check_starts_no_process_and_imports_nothing_heavy(tmp_path, monkeypatch):
    """It runs on every page rerun and on entering the engine step: it must not take seconds."""
    log = []
    _fake(monkeypatch, tmp_path, log=log)
    sle.check(_laya_folder(tmp_path))
    assert log == []                                   # no subprocess at all
    started = time.time()
    sle.check(tmp_path / "nowhere")
    assert time.time() - started < 0.5


def test_has_engine_looks_for_torch_and_transformers_without_importing_them():
    before = "torch" in sys.modules
    sle.has_engine()
    assert ("torch" in sys.modules) == before


# ── the model file ──────────────────────────────────────────────────────────

def test_the_model_is_looked_for_on_disk_with_no_subprocess(tmp_path, monkeypatch):
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path / "hub"))
    assert sle.checkpoint_present() is False
    snap = tmp_path / "hub" / "models--convaiinnovations--laya" / "snapshots" / "abc"
    snap.mkdir(parents=True)
    assert sle.checkpoint_present() is False                      # a snapshot without the model file
    (snap / "model.safetensors").write_text("x")
    assert sle.checkpoint_present() is True


def test_the_hub_cache_follows_the_same_rules_as_the_hub(tmp_path, monkeypatch):
    for key in ("HF_HUB_CACHE", "HUGGINGFACE_HUB_CACHE", "HF_HOME"):
        monkeypatch.delenv(key, raising=False)
    assert sle.hub_cache().parts[-3:] == (".cache", "huggingface", "hub")
    monkeypatch.setenv("HF_HOME", str(tmp_path))
    assert sle.hub_cache() == tmp_path / "hub"
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path / "elsewhere"))
    assert sle.hub_cache() == tmp_path / "elsewhere"


# ── install ─────────────────────────────────────────────────────────────────

def test_install_adds_only_the_pinned_package_into_its_folder_and_touches_nothing_else(tmp_path, monkeypatch):
    log = []
    _fake(monkeypatch, tmp_path, log=log)
    pkg = tmp_path / "laya_pkg"
    result = sle.install(pkg)
    pip = next(text for text, _k in log if " pip " in f" {text} ")
    assert result["ok"] is True
    assert "--no-deps" in pip and "--target" in pip and str(pkg) in pip and sle.LAYA_REQUIREMENT in pip


def test_install_is_idempotent_when_everything_is_there(tmp_path, monkeypatch):
    log = []
    _fake(monkeypatch, tmp_path, log=log)
    result = sle.install(_laya_folder(tmp_path))
    assert result["ok"] is True and log == []                    # nothing run: nothing to do


def test_install_downloads_only_the_english_model_when_it_is_missing(tmp_path, monkeypatch):
    log = []
    _fake(monkeypatch, tmp_path, model=False, log=log)
    result = sle.install(_laya_folder(tmp_path))
    downloads = [t for t, _k in log if "snapshot_download" in t]
    assert result["ok"] is True and len(downloads) == 1
    assert "multilingual/*" in downloads[0] and "typed-decisions/*" in downloads[0]


def test_install_says_when_the_model_did_not_download(tmp_path, monkeypatch):
    _fake(monkeypatch, tmp_path, model=False, download_ok=False)
    result = sle.install(_laya_folder(tmp_path))
    assert result["ok"] is False and "model download failed" in result["error"]


def test_install_reports_a_pip_failure(tmp_path, monkeypatch):
    _fake(monkeypatch, tmp_path, pip_ok=False)
    result = sle.install(tmp_path / "laya_pkg")
    assert result["ok"] is False and "network unreachable" in result["error"]


def test_install_says_the_analysis_engine_comes_first(tmp_path, monkeypatch):
    _fake(monkeypatch, tmp_path, engine=False)
    result = sle.install(_laya_folder(tmp_path))
    assert result["ok"] is False and "analysis engine" in result["error"] and result["state"] == "needs_engine"


# ── remove and the command line ─────────────────────────────────────────────

def test_remove_deletes_the_package_folder(tmp_path):
    pkg = _laya_folder(tmp_path)
    assert sle.remove(pkg) is True and not pkg.exists()


def test_remove_on_a_missing_folder_returns_false(tmp_path):
    assert sle.remove(tmp_path / "nothing") is False


def test_main_check_exits_nonzero_when_not_installed(tmp_path, capsys):
    assert sle.main(["--check", "--pkg-dir", str(tmp_path / "nothing")]) == 1
    assert "not_installed" in capsys.readouterr().out


def test_the_worker_stays_offline_unless_told_otherwise(monkeypatch):
    from engines import laya_worker
    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
    monkeypatch.setitem(sys.modules, "laya", None)            # "not installed": it stops early
    laya_worker.main([])
    assert os.environ["HF_HUB_OFFLINE"] == "1"
    monkeypatch.setenv("HF_HUB_OFFLINE", "0")
    laya_worker.main([])
    assert os.environ["HF_HUB_OFFLINE"] == "0"


def test_the_default_folder_follows_the_home_folder_at_call_time(tmp_path, monkeypatch):
    """So a test that moves the home folder cannot see a Laya installed on the developer's machine."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    assert sle.default_pkg_dir() == tmp_path / ".qualsafe" / "laya_pkg"
    assert sle.check()["state"] == "not_installed"
