"""
Tests for tools/uninstall.py — the clean-slate planner (v3.6).

Only the planning/scope logic is tested (no actual deletion of the real tree).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from tools import uninstall

_HF_VARS = ("HF_HOME", "XDG_CACHE_HOME", "HF_HUB_CACHE", "HUGGINGFACE_HUB_CACHE")


@pytest.fixture(autouse=True)
def _default_hf_location(monkeypatch):
    """tests/conftest.py pins HF_HOME to the REAL model cache (so model tests
    find it). Planning here must never resolve to that, so every variable the
    uninstaller reads is cleared, and the default (under the per-test temp home)
    applies unless a test sets one to a temp path."""
    for var in _HF_VARS:
        monkeypatch.delenv(var, raising=False)


def _model_cache() -> str:
    """Where the uninstaller looks, resolved when the test runs: the home
    folder is a temp folder per test (tests/conftest.py), so a module-level
    constant would name the real one."""
    return str(Path.home() / ".cache" / "huggingface")


@pytest.fixture()
def packaged_build_tree():
    """A build tree shaped like the desktop installer's payload, then removed.

    The payload is a whole relocatable CPython, so it contains third-party
    packages carrying their own `__pycache__`. The planner used to walk into it
    and offer every one of them for deletion. `build/` is gitignored, so creating
    one here is invisible to the repository.
    """
    root = uninstall.PROJECT_ROOT / "build"
    pre_existing = root.exists()
    cache = root / "payload" / "python" / "Lib" / "site-packages" / "huggingface_hub" / "__pycache__"
    cache.mkdir(parents=True, exist_ok=True)
    try:
        yield cache
    finally:
        if not pre_existing:
            import shutil
            shutil.rmtree(root, ignore_errors=True)


class TestForeignTrees:
    """"Clear caches" means the analyst's caches — not bytecode belonging to a
    packaged application that happens to sit inside the project tree."""

    def test_a_packaged_build_tree_is_not_offered_for_deletion(self, packaged_build_tree):
        paths = [str(p) for p, _ in uninstall.plan_targets("caches")]
        assert str(packaged_build_tree) not in paths

    def test_no_planned_target_lives_under_build_or_dist(self, packaged_build_tree):
        for scope in ("caches", "env", "all"):
            for path, _ in uninstall.plan_targets(scope):
                names = {p.name for p in Path(path).parents}
                assert not (names & {"build", "dist"}), f"{path} is inside packaged output"


class TestScopePlanning:
    def test_caches_scope_excludes_venv_and_models(self):
        targets = uninstall.plan_targets("caches")
        paths = [str(p) for p, _ in targets]
        assert not any(p.endswith(".venv") for p in paths)
        # The model cache is identified by its path, not by the substring
        # "huggingface" — a *package* named huggingface_hub is not a model cache,
        # and the looser check turned this test red on any machine that had built
        # the desktop payload.
        assert not any(p.startswith(_model_cache()) for p in paths)

    def test_env_scope_includes_venv_not_models(self):
        targets = uninstall.plan_targets("env")
        paths = [str(p) for p, _ in targets]
        assert any(p.endswith(".venv") for p in paths)
        assert not any(p.startswith(_model_cache()) for p in paths)

    def test_all_scope_includes_venv_and_models(self):
        targets = uninstall.plan_targets("all")
        paths = [str(p) for p, _ in targets]
        assert any(p.endswith(".venv") for p in paths)
        assert any(p.startswith(_model_cache()) for p in paths)

    def test_output_dirs_in_every_scope(self):
        for scope in ("caches", "env", "all"):
            descs = [d for _, d in uninstall.plan_targets(scope)]
            assert any("GUI run outputs" in d for d in descs)

    def test_dry_run_removes_nothing(self, tmp_path):
        target = tmp_path / "junk"
        target.mkdir()
        assert uninstall._remove(target, dry_run=True) is True
        assert target.exists()  # dry run: still there

    def test_remove_deletes(self, tmp_path):
        target = tmp_path / "junk"
        target.mkdir()
        assert uninstall._remove(target, dry_run=False) is True
        assert not target.exists()


class TestModelCacheLocation:
    """The app finds its models through huggingface_hub, which honours HF_HOME,
    XDG_CACHE_HOME and HF_HUB_CACHE. The uninstaller hard-coded
    ~/.cache/huggingface, so with the cache moved it missed the real one and
    said "already clean"."""

    def _paths(self):
        return [p for p, _ in uninstall.plan_targets("models")]

    def test_default_is_the_home_cache(self):
        assert self._paths()[-1] == Path.home() / ".cache" / "huggingface"

    def test_hf_home_moves_it(self, monkeypatch, tmp_path):
        monkeypatch.setenv("HF_HOME", str(tmp_path / "hf"))
        paths = self._paths()
        assert tmp_path / "hf" in paths
        assert Path.home() / ".cache" / "huggingface" not in paths

    def test_xdg_cache_home_moves_it(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
        assert tmp_path / "xdg" / "huggingface" in self._paths()

    def test_hf_home_beats_xdg(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
        monkeypatch.setenv("HF_HOME", str(tmp_path / "hf"))
        paths = self._paths()
        assert tmp_path / "hf" in paths and tmp_path / "xdg" / "huggingface" not in paths

    @pytest.mark.parametrize("var", ["HF_HUB_CACHE", "HUGGINGFACE_HUB_CACHE"])
    def test_a_hub_cache_elsewhere_is_added(self, monkeypatch, tmp_path, var):
        monkeypatch.setenv("HF_HOME", str(tmp_path / "hf"))
        monkeypatch.setenv(var, str(tmp_path / "models"))
        paths = self._paths()
        assert tmp_path / "hf" in paths and tmp_path / "models" in paths

    def test_a_hub_cache_inside_hf_home_is_not_listed_twice(self, monkeypatch, tmp_path):
        monkeypatch.setenv("HF_HOME", str(tmp_path / "hf"))
        monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path / "hf" / "hub"))
        assert self._paths().count(tmp_path / "hf") == 1
        assert tmp_path / "hf" / "hub" not in self._paths()

    def test_agrees_with_huggingface_hub(self, monkeypatch, tmp_path):
        """The same answer the library the app uses gives, for a moved cache."""
        import importlib
        constants = pytest.importorskip("huggingface_hub.constants")
        monkeypatch.setenv("HF_HOME", str(tmp_path / "hf"))
        monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path / "elsewhere"))
        try:
            constants = importlib.reload(constants)
            paths = self._paths()
            assert Path(constants.HF_HOME) in paths
            assert Path(constants.HF_HUB_CACHE) in paths
        finally:
            monkeypatch.undo()
            importlib.reload(constants)


class TestModelCacheSafety:
    """With the location read from the environment, a mistaken value must not
    turn "remove downloaded models" into "remove everything"."""

    @pytest.mark.parametrize("where", ["home", "home_parent", "project", "root"])
    def test_refuses_dangerous_locations(self, monkeypatch, capsys, where):
        target = {"home": Path.home(), "home_parent": Path.home().parent,
                  "project": uninstall.PROJECT_ROOT,
                  "root": Path(Path.home().anchor)}[where]
        monkeypatch.setenv("HF_HOME", str(target))
        paths = [p for p, _ in uninstall.plan_targets("all")]
        assert target not in paths
        assert "not removing the model cache" in capsys.readouterr().out

    def test_a_dangerous_hub_cache_is_refused_but_hf_home_kept(self, monkeypatch, tmp_path):
        monkeypatch.setenv("HF_HOME", str(tmp_path / "hf"))
        monkeypatch.setenv("HF_HUB_CACHE", str(Path.home()))
        paths = [p for p, _ in uninstall.plan_targets("models")]
        assert tmp_path / "hf" in paths and Path.home() not in paths

    def test_a_folder_inside_home_is_allowed(self, tmp_path):
        assert uninstall.unsafe_to_remove(Path.home() / ".cache" / "huggingface") == ""
        assert uninstall.unsafe_to_remove(tmp_path / "hf") == ""

    def test_the_label_says_where_the_location_came_from(self, monkeypatch, tmp_path):
        monkeypatch.setenv("HF_HOME", str(tmp_path / "hf"))
        descs = dict(uninstall.plan_targets("models"))
        assert "HF_HOME" in descs[tmp_path / "hf"]
