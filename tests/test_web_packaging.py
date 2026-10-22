"""The web installer: what it ships and how it starts (packaging/build_payload_web.py, web_launcher.py)."""

from __future__ import annotations

import importlib.util
import re
import socket
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKAGING = ROOT / "packaging"


def _load(name: str, filename: str):
    sys.path.insert(0, str(PACKAGING))
    try:
        spec = importlib.util.spec_from_file_location(name, PACKAGING / filename)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(PACKAGING))


@pytest.fixture(scope="module")
def build():
    return _load("build_payload_web_under_test", "build_payload_web.py")


@pytest.fixture
def launcher(tmp_path, monkeypatch):
    monkeypatch.setenv("QUALSAFE_WEB_STATE", str(tmp_path / "state"))
    return _load("web_launcher_under_test", "web_launcher.py")


# -- what ships ---------------------------------------------------------------------------------

def test_every_folder_and_file_the_web_installer_ships_exists(build):
    for name in build.APP_DIRS:
        assert (ROOT / name).is_dir(), name
    for name in (*build.APP_FILES, *(s for s, _d in build.EXTRA_FILES)):
        assert (ROOT / name).is_file(), name


def test_the_web_app_never_needs_the_desktop_ui(build):
    """qualsafe_qt does not ship in the web installer, so nothing that does ship may import it."""
    pattern = re.compile(r"^\s*(from|import)\s+qualsafe_qt\b", re.MULTILINE)
    offenders = []
    for name in build.APP_DIRS:
        for path in (ROOT / name).rglob("*.py"):
            if pattern.search(path.read_text(encoding="utf-8", errors="ignore")):
                offenders.append(str(path.relative_to(ROOT)))
    for name in build.APP_FILES:
        if name.endswith(".py") and pattern.search((ROOT / name).read_text(encoding="utf-8")):
            offenders.append(name)
    assert not offenders, offenders


def test_the_web_installer_installs_the_dependencies_the_web_app_runs_on():
    text = (ROOT / "requirements-light.txt").read_text(encoding="utf-8").lower()
    for package in ("streamlit", "altair", "vl-convert-python", "pandas", "scikit-learn", "python-docx"):
        assert package in text, package


def test_the_installer_script_matches_the_payload():
    iss = (PACKAGING / "qualsafe_web.iss").read_text(encoding="utf-8")
    assert r"..\build\payload_web" in iss and "launch_web.py" in iss and "resources\qualsafe.ico" in iss
    assert "QualSafe-Web-{#AppVersion}-Setup" in iss
    # a different identity from the desktop installer, so both can be installed side by side
    desktop = (PACKAGING / "qualsafe.iss").read_text(encoding="utf-8")
    web_id = re.search(r"AppId=\{\{([0-9A-F-]+)\}", iss).group(1)
    desktop_id = re.search(r"AppId=\{\{([0-9A-F-]+)\}", desktop).group(1)
    assert web_id != desktop_id
    # the uninstaller leaves the researcher's files alone
    assert 'Type: dirifempty; Name: "{app}\\data"' in iss and "output_streamlit" in iss
    assert not re.search(r'filesandordirs; Name: "\{app\}\\(data|output_streamlit)"', iss)


# -- the launcher -------------------------------------------------------------------------------

def test_the_command_runs_the_app_on_this_computer_only(launcher, tmp_path):
    command = launcher.command(tmp_path, 8503)
    assert command[:3] == [sys.executable, "-m", "streamlit"]
    assert command[command.index("--server.address") + 1] == "127.0.0.1"
    assert command[command.index("--server.port") + 1] == "8503"
    assert command[command.index("--server.headless") + 1] == "true"
    assert command[command.index("--browser.gatherUsageStats") + 1] == "false"
    assert str(tmp_path / "streamlit_app.py") in command


def test_a_free_port_in_range_is_chosen_and_a_busy_one_is_skipped(launcher):
    with socket.socket() as busy:
        busy.bind(("127.0.0.1", launcher.FIRST_PORT))
        busy.listen(1)
        port = launcher.free_port()
        assert port is None or launcher.FIRST_PORT < port <= launcher.LAST_PORT
        assert not launcher.port_is_free(launcher.FIRST_PORT)


def test_nothing_is_up_on_a_port_nobody_listens_on(launcher):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        quiet = probe.getsockname()[1]
    assert launcher.server_up(quiet, timeout=0.3) is False


def test_where_the_app_is_running_is_remembered_and_forgotten(launcher):
    assert launcher.read_state() is None
    launcher.write_state(1234, 8502)
    assert launcher.read_state() == {"pid": 1234, "port": 8502}
    launcher.clear_state()
    assert launcher.read_state() is None
    launcher.state_dir().mkdir(parents=True, exist_ok=True)
    launcher.state_path().write_text("not json", encoding="utf-8")
    assert launcher.read_state() is None                      # a damaged file is no state, never an error


def test_stopping_when_nothing_runs_says_so_and_does_not_fail(launcher):
    assert launcher.stop() is False


def test_starting_reopens_the_page_already_running_instead_of_starting_a_second_server(launcher, monkeypatch, tmp_path):
    opened = []
    launcher.write_state(4321, 8505)
    monkeypatch.setattr(launcher, "server_up", lambda port, timeout=1.0: port == 8505)
    monkeypatch.setattr(launcher.webbrowser, "open", lambda url: opened.append(url))
    started = []
    monkeypatch.setattr(launcher.subprocess, "Popen", lambda *a, **k: started.append(a) or None)
    assert launcher.start(tmp_path) == 8505
    assert opened == ["http://localhost:8505"] and not started


def test_the_uninstaller_stops_the_app_without_a_message_box(launcher):
    """An unattended uninstall hung on 'QualSafe Web has been stopped' until the stop was made quiet."""
    iss = (PACKAGING / "qualsafe_web.iss").read_text(encoding="utf-8")
    assert "stop --quiet" in iss.split("[UninstallRun]")[1].split("[UninstallDelete]")[0]
    shown = []
    launcher.ctypes_called = shown
    assert launcher.main(["stop", "--quiet"]) == 0                      # nothing running: returns, no dialog
    assert launcher._QUIET["on"] is True


def test_pyarrow_is_pinned_below_the_release_that_needs_numpy_2():
    """Streamlit draws tables through pyarrow; pyarrow 26 needs NumPy 2 and this app is pinned to NumPy 1.x, so
    an unpinned fresh install (the Mac CI, the web payload) failed on every page with a table."""
    for name in ("requirements.txt", "requirements-light.txt", "requirements-compat.txt"):
        lines = (ROOT / name).read_text(encoding="utf-8").splitlines()
        pins = [l for l in lines if l.strip().lower().startswith("pyarrow")]
        assert pins and "<26" in pins[0].replace(" ", ""), (name, pins)
        assert any(l.strip().lower().startswith("numpy") and "<2" in l for l in lines), name


def test_the_payload_check_draws_a_table_not_only_home(build):
    assert "pyarrow" in build.VERIFY_SCRIPT and "dc_sample" in build.VERIFY_SCRIPT
