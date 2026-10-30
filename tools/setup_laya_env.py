#!/usr/bin/env python
"""
Install Laya, the optional coding engine for written-codebook coding (Alt Survey Flow).

    python tools/setup_laya_env.py                  # install the package, then the model
    python tools/setup_laya_env.py --check          # report status, install nothing
    python tools/setup_laya_env.py --download-model # the model only
    python tools/setup_laya_env.py --remove         # delete what this installed

What "installed" means (changed 2026-10-06; the earlier design made a second Python
environment):

* The **Laya package** (about 360 KB, pinned to the version tested, `LAYA_REQUIREMENT`)
  goes into its own small folder, `PKG_DIR`, with `pip install --no-deps --target`.
  Nothing is installed into this app's own Python, and none of the app's libraries
  (transformers, torch, numpy) is touched or upgraded. The worker finds the folder
  through `PYTHONPATH`.
* The **model file** (English only, about 0.8 GB) is downloaded here, once, on purpose,
  into the Hugging Face cache. The worker starts offline (`HF_HUB_OFFLINE=1`), so coding
  never reaches the network.
* Laya runs in a worker **process** (`engines/laya_worker.py`) using this app's own
  Python and libraries. It needs the analysis engine (torch and transformers) to be
  installed already; if it is not, the status is `needs_engine`.

Why no separate environment: Laya's published requirements are torch 2.0 or newer,
transformers 4.48 or newer and numpy 1.20 or newer, and this app's own pins satisfy all
three. Checked on a real install (2026-10-06): the same 12 answers scored identically to
two decimals on transformers 5.18 / torch 2.14 / numpy 2.5 in a separate environment and on
this app's own transformers 4.57 / torch 2.13 / numpy 1.26.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
#: Per-user, non-project state, like the other `~/.qualsafe/` folders.
def default_pkg_dir() -> Path:
    """Looked up when needed, not when this file is imported, so a test that moves the home folder
    moves this too (tests/conftest.py)."""
    return Path.home() / ".qualsafe" / "laya_pkg"


PKG_DIR = default_pkg_dir()      # for reading in docs and messages; the functions below use the call-time value

#: Pinned to the version this was tested with. Laya is new and changes; a new version is
#: tried on purpose (the calibration check in the app is what says whether it still agrees).
LAYA_REQUIREMENT = "laya==0.3.28"

#: The model file Laya loads. Only the English one (about 0.8 GB). The repo also holds a
#: multilingual and a typed-decisions model this tool does not use.
CHECKPOINT_REPO = "convaiinnovations/laya"
_FETCH = ("from huggingface_hub import snapshot_download; "
          "snapshot_download({repo!r}, local_files_only={offline}, "
          "ignore_patterns=['multilingual/*', 'typed-decisions/*'])")


def app_python() -> str:
    """The Python to run Laya's worker and these steps with: this app's own, with a console.

    The installed app runs under `pythonw.exe`, which has no console and no usable standard
    streams, so a worker started with it could not talk back. Use `python.exe` beside it."""
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe":
        console = exe.with_name("python.exe")
        if console.is_file():
            return str(console)
    return str(exe)


def worker_env(pkg_dir: Optional[Path] = None) -> Dict[str, str]:
    """The environment for a process that should see the Laya package."""
    pkg_dir = pkg_dir or default_pkg_dir()
    env = dict(os.environ)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(pkg_dir) + (os.pathsep + existing if existing else "")
    return env


def _no_window() -> int:
    """Keep a console window from flashing up when this runs from the windowed app."""
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0


def _run(args, *, pkg_dir: Optional[Path] = None, timeout: float = 60, online: bool = False):
    """Run the app's Python with the Laya package visible. `online` is for the one step that must reach the
    model hub: the program arms offline mode in its own environment and a child inherits it, so a download
    started with those flags is refused. Everything else keeps them."""
    pkg_dir = pkg_dir or default_pkg_dir()
    env = worker_env(pkg_dir)
    if online:
        for var in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE"):
            env.pop(var, None)
    return subprocess.run([app_python(), *args], capture_output=True, text=True, timeout=timeout,
                          env=env, creationflags=_no_window())


def _log(message: str, as_json: bool) -> None:
    if not as_json:
        print(f"[laya-setup] {message}", flush=True)


#: The checks below must be quick: the web page runs them on every rerun and the desktop on
#: entering the engine step. So they start no process and import nothing heavy: the package's
#: version is read from its folder, torch and transformers are looked for (not imported; the worker
#: runs on this same Python), and the model file is looked for on disk. A package that is there but
#: will not load shows up when the worker starts, and the run then says so and uses the labelled
#: demo engine.

def _version_in(pkg_dir: Path) -> str:
    """The Laya version, from the `laya-X.Y.Z.dist-info` folder pip leaves beside the package."""
    for info in sorted(pkg_dir.glob("laya-*.dist-info")):
        return info.name[len("laya-"):-len(".dist-info")]
    return ""


def has_engine() -> bool:
    """Are torch and transformers installed in this Python (the one the worker uses)?"""
    import importlib.util

    try:
        return all(importlib.util.find_spec(name) is not None for name in ("torch", "transformers"))
    except (ImportError, ValueError):
        return False


def check(pkg_dir: Optional[Path] = None) -> dict:
    """Report status without installing anything, starting a process or importing Laya or torch.

    States: `not_installed` (no package), `needs_engine` (the package is there but torch or
    transformers is not), `broken` (the folder is there without its version record), `ready`."""
    pkg_dir = pkg_dir or default_pkg_dir()
    base = {"pkg_dir": str(pkg_dir), "python": app_python(), "laya_version": None}
    if not (pkg_dir / "laya").is_dir():
        return {"state": "not_installed", **base}
    version = _version_in(pkg_dir)
    if not version:
        return {"state": "broken", **base}
    if not has_engine():
        return {"state": "needs_engine", **{**base, "laya_version": version}}
    return {"state": "ready", **{**base, "laya_version": version}}


def hub_cache() -> Path:
    """Where Hugging Face keeps downloaded models, by the same rules it uses."""
    for key in ("HF_HUB_CACHE", "HUGGINGFACE_HUB_CACHE"):
        if os.environ.get(key):
            return Path(os.environ[key])
    home = os.environ.get("HF_HOME")
    return (Path(home) if home else Path.home() / ".cache" / "huggingface") / "hub"


def checkpoint_present(pkg_dir: Optional[Path] = None) -> bool:
    """Is the English model file on this computer? Looked for on disk: no network, no import."""
    folder = hub_cache() / ("models--" + CHECKPOINT_REPO.replace("/", "--")) / "snapshots"
    return folder.is_dir() and any((rev / "model.safetensors").is_file() for rev in folder.iterdir())


def download_checkpoint(pkg_dir: Optional[Path] = None, *, as_json: bool = False) -> dict:
    pkg_dir = pkg_dir or default_pkg_dir()
    """Download the model into the Hugging Face cache. The caller has already got consent."""
    _log(f"downloading the model {CHECKPOINT_REPO} (this is the large download)", as_json)
    try:
        result = _run(["-c", _FETCH.format(repo=CHECKPOINT_REPO, offline=False)],
                      pkg_dir=pkg_dir, timeout=3600, online=True)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "error": f"The model download did not finish: {exc}"}
    if result.returncode != 0:
        tail = (result.stderr or result.stdout or "").strip()[-1500:]
        return {"ok": False, "error": f"The model download failed: {tail}"}
    return {"ok": True}


def install(pkg_dir: Optional[Path] = None, *, as_json: bool = False) -> dict:
    """Install the package, then the model. Idempotent: whatever is already there is kept."""
    pkg_dir = pkg_dir or default_pkg_dir()
    status = check(pkg_dir)
    if status["state"] == "not_installed":
        pkg_dir.parent.mkdir(parents=True, exist_ok=True)
        _log(f"installing {LAYA_REQUIREMENT} into {pkg_dir} (the package only; nothing else changes)",
             as_json)
        try:
            result = subprocess.run(
                [app_python(), "-m", "pip", "install", "--no-deps", "--no-cache-dir",
                 "--target", str(pkg_dir), LAYA_REQUIREMENT],
                capture_output=True, text=True, timeout=900, creationflags=_no_window())
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {"ok": False, "error": f"The install did not finish: {exc}", **status}
        if result.returncode != 0:
            tail = (result.stderr or result.stdout or "").strip()[-2000:]
            return {"ok": False, "error": f"pip install failed: {tail}", **status}
        status = check(pkg_dir)
    else:
        _log(f"already installed in {pkg_dir}", as_json)
    if status["state"] == "needs_engine":
        return {"ok": False, "error": "The analysis engine (the language-model software) has to "
                                      "be installed first.", **status}
    if status["state"] != "ready":
        return {"ok": False, **status}
    if not checkpoint_present(pkg_dir):
        downloaded = download_checkpoint(pkg_dir, as_json=as_json)
        if not downloaded["ok"]:
            return {**status, "ok": False, "error": downloaded["error"]}
    return {"ok": True, **status}


def remove(pkg_dir: Optional[Path] = None) -> bool:
    """Delete the package folder. The model in the Hugging Face cache is left alone."""
    pkg_dir = pkg_dir or default_pkg_dir()
    if not pkg_dir.exists():
        return False
    shutil.rmtree(pkg_dir, ignore_errors=True)
    return True


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pkg-dir", default=str(default_pkg_dir()))
    parser.add_argument("--check", action="store_true", help="report status, install nothing")
    parser.add_argument("--remove", action="store_true", help="delete the package folder")
    parser.add_argument("--download-model", action="store_true",
                        help="download the model into an installed package")
    parser.add_argument("--json", action="store_true", help="machine-readable single-line output")
    args = parser.parse_args(argv)
    pkg_dir = Path(args.pkg_dir)

    if args.remove:
        removed = remove(pkg_dir)
        print(json.dumps({"ok": True, "removed": removed}) if args.json
              else (f"Removed {pkg_dir}" if removed else f"Nothing at {pkg_dir}"))
        return 0

    if args.check:
        status = check(pkg_dir)
        if args.json:
            print(json.dumps(status))
        else:
            print(f"State: {status['state']}  Folder: {status['pkg_dir']}  "
                  f"Laya: {status['laya_version'] or 'n/a'}")
        return 0 if status["state"] == "ready" else 1

    if args.download_model:
        result = download_checkpoint(pkg_dir, as_json=args.json)
        print(json.dumps(result) if args.json
              else ("Model downloaded." if result["ok"] else result["error"]))
        return 0 if result["ok"] else 1

    result = install(pkg_dir, as_json=args.json)
    if args.json:
        print(json.dumps(result))
    elif not result.get("ok"):
        print(result.get("error", "The install did not finish."))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
