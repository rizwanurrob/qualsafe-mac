"""The in-app analysis-engine installer (core/engine_install.py): where it goes, what it asks pip for, and that a
failure comes back as a message. No test downloads anything: pip runs are replaced by a fake stream."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from core import engine_install as ei


@pytest.fixture(autouse=True)
def _no_override(monkeypatch):
    monkeypatch.delenv("QUALSAFE_ENGINE_DIR", raising=False)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)


def test_engine_dir_per_platform(monkeypatch):
    home = Path("/home/u")
    monkeypatch.setenv("LOCALAPPDATA", str(home / "AppData" / "Local"))
    tag = f"py{sys.version_info[0]}{sys.version_info[1]}"
    assert ei.engine_dir("darwin", home) == home / "Library" / "Application Support" / "QualSafe" / "engine" / tag
    assert ei.engine_dir("linux", home) == home / ".local" / "share" / "qualsafe" / "engine" / tag
    assert ei.engine_dir("win32", home) == home / "AppData" / "Local" / "QualSafe" / "engine" / tag


def test_override(monkeypatch, tmp_path):
    monkeypatch.setenv("QUALSAFE_ENGINE_DIR", str(tmp_path))
    assert ei.engine_dir() == tmp_path


def test_intel_mac_is_held_to_the_last_torch_it_can_have():
    assert "torch==2.2.2" in ei.platform_constraints("darwin", "x86_64")
    assert "torch==2.2.2" not in ei.platform_constraints("darwin", "arm64")
    assert "numpy>=1.24,<2.0" in ei.platform_constraints("win32", "AMD64")


def test_steps_per_system():
    win = ei.steps("win32", "AMD64", pins=[])
    assert len(win) == 2 and ei.CPU_TORCH_INDEX in win[0]["args"]
    mac = ei.steps("darwin", "arm64", pins=[])
    assert len(mac) == 1 and ei.CPU_TORCH_INDEX not in mac[0]["args"]
    intel = ei.steps("darwin", "x86_64", pins=[])
    assert "torch==2.2.2" in intel[0]["packages"]


def test_install_command_targets_the_folder(tmp_path):
    step = ei.steps("darwin", "arm64", pins=[])[0]
    command = ei.install_command(step, tmp_path, "py")
    assert command[:4] == ["py", "-m", "pip", "install"] and str(tmp_path) in command


def test_activate_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.setenv("PYTHONPATH", "")
    assert ei.activate(tmp_path) is True
    assert ei.activate(tmp_path) is False
    assert sys.path.count(str(tmp_path)) == 1
    assert ei.activate(tmp_path / "missing") is False


def test_install_runs_every_step_and_reports(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "path", list(sys.path))
    seen, lines = [], []
    def fake(command, progress):
        seen.append(command)
        progress("fake line")
        return []
    result = ei.install(progress=lines.append, target=tmp_path / "e", python="py", stream=fake, check=False)
    assert result["ok"] and len(seen) == len(ei.steps())
    assert "fake line" in lines and lines[0].startswith("Step 1")


def test_install_failure_is_an_error_with_the_log(tmp_path):
    def broken(command, progress):
        raise ei.EngineInstallError("pip stopped with exit code 1", "no network")
    with pytest.raises(ei.EngineInstallError) as caught:
        ei.install(target=tmp_path / "e", python="py", stream=broken, check=False)
    assert caught.value.log == "no network"


def test_pip_is_told_not_to_compile_bytecode():
    """Compiling a .pyc for every file made the real engine install take 50 minutes; Python does it on import."""
    assert all("--no-compile" in step["args"] for step in ei.steps("win32", "AMD64", pins=[]))
    assert "--no-compile" in ei.steps("darwin", "arm64", pins=[])[0]["args"]


def test_copies_of_packages_the_program_has_are_pruned_and_the_rest_is_kept(tmp_path):
    import importlib.metadata as md

    numpy_version = md.version("numpy")
    for name in ("numpy", "numpy.libs", f"numpy-{numpy_version}.dist-info", "torch", "torch-2.0.dist-info"):
        (tmp_path / name).mkdir()
    removed = ei.prune_duplicates(tmp_path)
    assert sorted(removed) == sorted(["numpy", "numpy.libs", f"numpy-{numpy_version}.dist-info"])
    assert (tmp_path / "torch").is_dir() and (tmp_path / "torch-2.0.dist-info").is_dir()


def test_a_package_the_program_lacks_is_never_pruned(tmp_path, monkeypatch):
    import importlib.metadata as md

    real = md.version

    def fake(name):
        if name == "scipy":
            raise md.PackageNotFoundError(name)
        return real(name)

    monkeypatch.setattr(md, "version", fake)
    (tmp_path / "scipy").mkdir()
    ei.prune_duplicates(tmp_path)
    assert (tmp_path / "scipy").is_dir()
