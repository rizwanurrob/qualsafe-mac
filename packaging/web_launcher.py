"""Start and stop the QualSafe web app on this computer.

Shipped in the web installer as `launch_web.py` and run by the interpreter that comes with it
(`pythonw.exe`, so there is no console window). Two actions:

    launch_web.py start     start the app if it is not running, then open it in the browser (default)
    launch_web.py stop      stop the app (add --quiet for no message box, as the uninstaller does)

The app is a Streamlit server. It listens on this computer only (127.0.0.1), on the first free port
from 8501 to 8510. Where it is running is remembered in `%LOCALAPPDATA%\\QualSafe Web\\server.json`,
so a second click on the shortcut opens the page that is already running instead of starting a
second server. What went wrong, if anything, is written to `server.log` beside it.

Nothing here imports Streamlit or the app: it only starts them, so it stays quick and is testable.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path
from typing import Optional

FIRST_PORT, LAST_PORT = 8501, 8510
#: A cold start imports pandas, Altair and Streamlit before the first page can draw.
START_TIMEOUT_SECONDS = 240


def state_dir() -> Path:
    override = os.environ.get("QUALSAFE_WEB_STATE")           # tests and unusual set-ups
    if override:
        return Path(override)
    return Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "QualSafe Web"


def state_path() -> Path:
    return state_dir() / "server.json"


def log_path() -> Path:
    return state_dir() / "server.log"


def read_state() -> Optional[dict]:
    try:
        data = json.loads(state_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) and "pid" in data and "port" in data else None
    except (OSError, ValueError):
        return None


def write_state(pid: int, port: int) -> None:
    state_dir().mkdir(parents=True, exist_ok=True)
    state_path().write_text(json.dumps({"pid": pid, "port": port}), encoding="utf-8")


def clear_state() -> None:
    try:
        state_path().unlink()
    except OSError:
        pass


def address(port: int) -> str:
    return f"http://localhost:{port}"


def server_up(port: int, timeout: float = 1.0) -> bool:
    """True when a Streamlit server answers its health check on this port."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/_stcore/health", timeout=timeout) as reply:
            return reply.status == 200
    except (OSError, ValueError):
        return False


def port_is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def free_port() -> Optional[int]:
    return next((p for p in range(FIRST_PORT, LAST_PORT + 1) if port_is_free(p)), None)


def command(root: Path, port: int) -> list:
    """The command that runs the app (the same interpreter that is running this)."""
    return [sys.executable, "-m", "streamlit", "run", str(Path(root) / "streamlit_app.py"),
            "--server.port", str(port), "--server.address", "127.0.0.1",
            "--server.headless", "true", "--browser.gatherUsageStats", "false"]


_QUIET = {"on": False}


def _tell(message: str) -> None:
    """Say something to a person when there is no console (pythonw): a message box on Windows.

    Silent with `--quiet`: the uninstaller stops the app this way, and a message box nobody can see would
    hold an unattended uninstall (found by running one)."""
    if _QUIET["on"]:
        return
    try:
        if sys.platform == "win32":
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, message, "QualSafe Web", 0x40)
            return
    except Exception:  # noqa: BLE001
        pass
    print(message)


def start(root: Path, open_browser: bool = True, wait: float = START_TIMEOUT_SECONDS) -> Optional[int]:
    """Start the app unless it is already running; return its port, or None if it would not start."""
    running = read_state()
    if running and server_up(int(running["port"])):
        if open_browser:
            webbrowser.open(address(int(running["port"])))
        return int(running["port"])
    clear_state()

    port = free_port()
    if port is None:
        _tell(f"QualSafe Web could not start: ports {FIRST_PORT} to {LAST_PORT} are all in use.")
        return None
    state_dir().mkdir(parents=True, exist_ok=True)
    flags = 0
    if sys.platform == "win32":
        flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
    with open(log_path(), "ab") as log:
        # Settings and saved progress go to the per-user folder, so they survive an upgrade or an uninstall
        # of the program folder (the app reads QNW_SETTINGS_DIR for both).
        env = {**os.environ, "QNW_SETTINGS_DIR": str(state_dir())}
        process = subprocess.Popen(command(root, port), cwd=str(root), stdout=log, stderr=log,
                                   stdin=subprocess.DEVNULL, creationflags=flags, env=env)
    write_state(process.pid, port)

    deadline = time.time() + wait
    while time.time() < deadline:
        if process.poll() is not None:
            clear_state()
            _tell("QualSafe Web stopped while starting. The reason is written in:\n" + str(log_path()))
            return None
        if server_up(port):
            if open_browser:
                webbrowser.open(address(port))
            return port
        time.sleep(1.0)
    _tell("QualSafe Web is taking a long time to start. Try the shortcut again in a minute; "
          "if it still does not open, see:\n" + str(log_path()))
    return port


def stop() -> bool:
    """Stop the app this launcher started. True if something was stopped."""
    running = read_state()
    clear_state()
    if not running:
        return False
    pid = int(running["pid"])
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True,
                           creationflags=subprocess.CREATE_NO_WINDOW)
        else:
            os.kill(pid, 15)
    except OSError:
        return False
    return True


def main(argv: Optional[list] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    _QUIET["on"] = "--quiet" in args
    args = [a for a in args if a != "--quiet"]
    action = args[0] if args else "start"
    root = Path(__file__).resolve().parent
    if action == "stop":
        stopped = stop()
        _tell("QualSafe Web has been stopped." if stopped else "QualSafe Web was not running.")
        return 0
    if action == "start":
        return 0 if start(root) is not None else 1
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
