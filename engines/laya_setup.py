#!/usr/bin/env python
"""
Laya detection and guided installation (Alt Survey Flow).

Mirrors `engines/ollama_setup.py`: report exactly what's missing and give the
precise next step, never install anything silently. "Installed" means two things
`tools/setup_laya_env.py` puts in place: the small Laya package in its own folder
(`~/.qualsafe/laya_pkg`), and the English model file in the Hugging Face cache. Laya
then runs in a worker process using this app's own Python and libraries (see
`engines/laya_worker.py`), so it needs the analysis engine (torch, transformers)
installed first.

`install()` here is consent-gated the same way `core/model_manager.download_model`
is: the caller (the Alt Survey Flow UI) must get an explicit click before calling
it, because it downloads about 0.8 GB.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Dict, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SETUP_SCRIPT = PROJECT_ROOT / "tools" / "setup_laya_env.py"

#: The three checkpoints Laya publishes (docs/ALT_SURVEY_FLOW_PLAN.md has the
#: sourced comparison). Only the English one is downloaded or used: this is a
#: workflow for English survey text. The others are listed for the record.
CHECKPOINTS = [
    {"model": "convaiinnovations/laya", "subfolder": None, "label": "English",
     "context_tokens": 512, "note": "Default. English text only. The only one downloaded."},
    {"model": "convaiinnovations/laya", "subfolder": "multilingual", "label": "Multilingual",
     "context_tokens": 1024, "note": "100+ languages; lower per-language accuracy than the English checkpoint on English text."},
    {"model": "convaiinnovations/laya", "subfolder": "typed-decisions", "label": "Typed decisions",
     "context_tokens": 1024, "note": "Tuned for structured/agent-trace decisions rather than open text; not the default for survey coding."},
]


def installation_status(pkg_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Report what's present. States: `not_installed`, `needs_engine` (the package is
    there but torch or transformers is not), `needs_model` (the model file is not on this
    computer yet), `broken`, `ready`. The checks run in a subprocess, as the worker will."""
    from tools.setup_laya_env import check, checkpoint_present, default_pkg_dir

    status = check(pkg_dir or default_pkg_dir())
    status["checkpoint"] = False
    if status["state"] == "ready":
        status["checkpoint"] = checkpoint_present(pkg_dir or default_pkg_dir())
        if not status["checkpoint"]:
            status["state"] = "needs_model"
    return status


def install_instructions() -> Dict[str, Any]:
    """What installing Laya actually does, for the confirmation dialog before
    `install()` is called."""
    return {
        "headline": "Install the structured coding engine (optional)",
        "what_it_does": [
            "Adds the small Laya package (under 1 MB) in its own folder. Nothing in this "
            "app's own installation is changed.",
            "Downloads the model file it uses (about 0.8 GB, English only), once.",
            "After that it runs on this computer without the internet. Nothing about your "
            "survey or interview data is uploaded; this only downloads software.",
        ],
        "why_isolated": (
            "The package is kept in its own folder and pinned to the version this app was "
            "checked with, so it cannot change the libraries the rest of the app relies on."
        ),
        "disk_estimate_mb": 850,   # measured 2026-10-05/06: English model 804 MB; package under 1 MB
        "checkpoints": CHECKPOINTS,
    }


def install(*, pkg_dir: Optional[Path] = None, python_exe: Optional[str] = None,
            timeout: Optional[float] = 5400) -> Dict[str, Any]:
    """Run the installer in a subprocess. The CALLER is responsible for consent
    (a confirmation dialog showing install_instructions()) before calling this —
    same convention as OllamaClient.pull and core.model_manager.download_model.
    """
    from tools.setup_laya_env import app_python, default_pkg_dir, _no_window

    shown = str(pkg_dir or default_pkg_dir())
    cmd = [python_exe or app_python(), str(SETUP_SCRIPT), "--json"]
    if pkg_dir:
        cmd += ["--pkg-dir", str(pkg_dir)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                              creationflags=_no_window())
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"Install timed out after {timeout}s.", "pkg_dir": shown}
    except OSError as exc:
        return {"ok": False, "error": f"Could not start the installer: {exc}", "pkg_dir": shown}

    import json as _json
    for line in reversed((proc.stdout or "").splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                return _json.loads(line)
            except _json.JSONDecodeError:
                continue
    tail = (proc.stderr or proc.stdout or "").strip()[-1000:]
    return {"ok": False, "error": tail or f"exited with code {proc.returncode}", "pkg_dir": shown}


def uninstall(pkg_dir: Optional[Path] = None) -> bool:
    """Delete the package folder. Never touches a project, the main app's libraries, or
    the downloaded model."""
    from tools.setup_laya_env import default_pkg_dir, remove

    return remove(pkg_dir or default_pkg_dir())


def isolated_python_path(pkg_dir: Optional[Path] = None) -> Optional[str]:
    """The interpreter to hand to `engines.laya_client.LayaClient`, or None if Laya isn't
    ready. (The name is kept; it is now this app's own Python, with the package folder on its
    path: see `worker_env`.)"""
    status = installation_status(pkg_dir)
    return status["python"] if status["state"] == "ready" else None


def worker_env(pkg_dir: Optional[Path] = None) -> Dict[str, str]:
    """The environment the worker process needs to find the Laya package."""
    from tools.setup_laya_env import default_pkg_dir, worker_env as _env

    return _env(pkg_dir or default_pkg_dir())
