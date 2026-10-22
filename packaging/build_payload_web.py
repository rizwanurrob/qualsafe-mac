#!/usr/bin/env python
"""
Assemble the tree that the WEB installer ships: a complete, relocatable Python with the web app (Streamlit)
and its dependencies already installed into it, plus a small launcher.

    python packaging/build_payload_web.py                  # -> build/payload_web/
    python packaging/build_payload_web.py --keep-download  # cache the CPython tarball

`packaging/qualsafe_web.iss` wraps that folder into one setup executable, the way `qualsafe.iss` does for the
desktop app. The two are separate installers on purpose: the desktop build carries no web server.

What is the same as the desktop build: the standalone CPython and the helpers that fetch, unpack and clean
it (imported from `build_payload.py`, so a fix to one is a fix to both).
What differs: no Qt; Streamlit, Altair, Arrow and vl-convert stay in; the app folders are the web app's;
`launch_web.py` starts the app on this computer only and opens it in the browser.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_payload as base  # noqa: E402

PROJECT_ROOT = base.PROJECT_ROOT
PAYLOAD_DIR = base.BUILD_DIR / "payload_web"

#: The web app and the engine it runs on. Not shipped: the desktop UI (`qualsafe_qt`), tests, notebooks,
#: run outputs, and the internal design documents.
APP_DIRS = (
    "app",              # the web pages
    "core",             # store, offline mode, span coding, backups, erasure, shared interface data
    "analysis",         # frequency, co-occurrence, agreement, query, framework, models
    "engines",          # transformer + language-model coding engines
    "exports",          # Word / Excel / codebook / methods appendix / bundle
    "interview",        # document loaders, quote verification
    "privacy",          # the PII scan behind the import gate
    "prompts",          # versioned prompt templates
    "config",           # example configs the app offers to load
    "data",             # sample files named by the help articles
    "tools",            # public-dataset helper the Load step uses
)
APP_FILES = (
    "streamlit_app.py",
    "interview_ui.py",
    "analyze_survey.py",
    "iterative_supervised_thematic.py",
    "LICENSE",
)
#: (source, destination inside the payload)
EXTRA_FILES = (
    (".streamlit/config.toml", ".streamlit/config.toml"),
    ("packaging/web_launcher.py", "launch_web.py"),
    ("qualsafe_qt/resources/qualsafe.ico", "resources/qualsafe.ico"),
)

#: Run by the payload's own interpreter: starts the app as the launcher would and checks it draws Home.
VERIFY_SCRIPT = r'''
import os, sys, tempfile
root = sys.argv[1]
sys.path.insert(0, root)
os.chdir(root)
os.environ["QNW_SETTINGS_DIR"] = tempfile.mkdtemp()
os.environ["QUALSAFE_NO_TOUR"] = "1"

from streamlit.testing.v1 import AppTest
at = AppTest.from_file(os.path.join(root, "streamlit_app.py"), default_timeout=300)
at.run()
assert not at.exception, at.exception
headers = " ".join(h.value for h in at.header)
assert "What would you like to do?" in headers, headers

# A page with a table: Streamlit draws tables through pyarrow, which failed to import under NumPy 1.x in the
# first web payload (pyarrow 26), and drawing Home alone did not notice.
import pyarrow
at.session_state["view"], at.session_state["activity"], at.session_state["step_charts"] = "activity", "charts", "open"
at.run()
next(b for b in at.button if b.key == "dc_sample").click()
at.run()
assert not at.exception, at.exception
assert at.dataframe, "the sample's first rows are not drawn as a table"

from core.manifest import PACKAGE_VERSION
from core.project import SCHEMA_VERSION
heavy = [m for m in ("PySide6", "qualsafe_qt", "torch", "transformers", "sklearn", "scipy") if m in sys.modules]
assert not heavy, "loaded before it is needed: %s" % heavy
assert os.path.isfile(os.path.join(root, "launch_web.py")), "launcher missing"
print("web payload ok: engine %s, project format v%s; Home and a table draw (pyarrow %s); nothing heavy loaded" % (PACKAGE_VERSION, SCHEMA_VERSION, pyarrow.__version__))
'''


def copy_application(payload: Path) -> None:
    def ignore(directory: str, names: list) -> set:
        return {n for n in names if n in base.EXCLUDE_NAMES}

    for name in APP_DIRS:
        source = PROJECT_ROOT / name
        if not source.is_dir():
            raise SystemExit(f"missing directory: {name}")
        shutil.copytree(source, payload / name, ignore=ignore, dirs_exist_ok=True)
    for name in APP_FILES:
        source = PROJECT_ROOT / name
        if not source.is_file():
            raise SystemExit(f"missing file: {name}")
        shutil.copy2(source, payload / name)
    for source_name, destination_name in EXTRA_FILES:
        source = PROJECT_ROOT / source_name
        if not source.is_file():
            raise SystemExit(f"missing file: {source_name}")
        destination = payload / destination_name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    base._log(f"copied {len(APP_DIRS)} package directories and {len(APP_FILES) + len(EXTRA_FILES)} files")


def install_dependencies(python: Path) -> None:
    base.pip_install(python, ["--upgrade", "pip"])
    # The same set the tests run against: Streamlit, Altair, scikit-learn, XGBoost, vl-convert and the rest.
    base.pip_install(python, ["-r", "requirements-light.txt"])


def assert_payload_clean() -> None:
    """Nothing of the developer's machine reaches a user."""
    bad = [p for p in PAYLOAD_DIR.iterdir() if p.name in base.EXCLUDE_NAMES or p.name.startswith("test")]
    if bad:
        raise SystemExit(f"unexpected in the payload root: {[p.name for p in bad]}")
    if (PAYLOAD_DIR / "qualsafe_qt").exists():
        raise SystemExit("the desktop UI must not ship in the web installer")


def verify(python: Path) -> None:
    base._log("verifying the payload: the app draws Home from inside it")
    done = subprocess.run([str(python), "-c", VERIFY_SCRIPT, str(PAYLOAD_DIR)], capture_output=True,
                          text=True, cwd=str(PAYLOAD_DIR), env={**os.environ, "PYTHONNOUSERSITE": "1"})
    if done.returncode != 0:
        raise SystemExit("payload verification failed:\n" + (done.stderr or done.stdout)[-1500:])
    for line in done.stdout.splitlines():
        if line.startswith("web payload ok"):
            base._log(line)
            return
    raise SystemExit("payload verification printed nothing:\n" + done.stdout[-800:])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keep-download", action="store_true", help="keep the CPython archive for the next build")
    parser.add_argument("--skip-verify", action="store_true")
    arguments = parser.parse_args()

    base._log("QualSafe Web (the web app, Streamlit)")
    if PAYLOAD_DIR.exists():
        base._rmtree_robust(PAYLOAD_DIR)
    PAYLOAD_DIR.mkdir(parents=True)

    archive = base.fetch_cpython(arguments.keep_download)
    payload_python = PAYLOAD_DIR / "python"
    base.unpack_cpython(archive, payload_python)

    install_dependencies(payload_python / "python.exe")
    copy_application(PAYLOAD_DIR)
    assert_payload_clean()
    if not arguments.skip_verify:
        verify(payload_python / "python.exe")

    # Last, because pip and the verification run both regenerate bytecode.
    base.strip_bytecode(PAYLOAD_DIR)
    base._log(f"payload ready: {PAYLOAD_DIR}  ({base._tree_size(PAYLOAD_DIR) / 1e9:.2f} GB)")
    base._log("next:  iscc packaging/qualsafe_web.iss /DAppVersion=<label>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
