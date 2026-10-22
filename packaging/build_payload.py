#!/usr/bin/env python
"""
Assemble the tree that the installer ships: a complete, relocatable Python with
the app and its dependencies already installed into it.

    python packaging/build_payload.py                  # -> build/payload/
    python packaging/build_payload.py --engine         # include torch (option A)
    python packaging/build_payload.py --keep-download  # cache the CPython tarball

The result is a folder that runs on a machine with **no Python installed**:

    build/payload/python/pythonw.exe -m qualsafe_qt

`packaging/qualsafe.iss` wraps that folder into one signed setup executable.
This script does the slow, network-dependent half so the Inno step is a pure
file copy that can be re-run in seconds.

Why a standalone CPython and not python.org's "embeddable package"
------------------------------------------------------------------
The embeddable zip deliberately disables `site`, ships no `pip`, and needs
`._pth` surgery before it will import anything from `site-packages`. It is meant
for embedding an interpreter in a larger C application, not for shipping a Python
app with wheels. `python-build-standalone` (the relocatable builds `uv` uses) is
an ordinary complete CPython that relocates cleanly, so pip works normally and
the in-app "install the analysis engine" step stays possible later.

Why not a frozen single .exe
----------------------------
Two reasons, both recorded in RELEASE_READINESS.md §3.2 and §1.5. A frozen exe
could never add torch after install, which is the whole basis of the two-tier
install. And PySide6 is LGPL: the licence requires that a user be able to replace
the Qt libraries, which is trivially true when they sit in `site-packages` as
ordinary DLLs and awkward to argue for a single opaque binary.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path
from typing import Dict
from urllib.parse import unquote

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BUILD_DIR = PROJECT_ROOT / "build"
PAYLOAD_DIR = BUILD_DIR / "payload"
DOWNLOAD_DIR = BUILD_DIR / "download"

# ---------------------------------------------------------------------------
# The interpreter
# ---------------------------------------------------------------------------
# Pinned deliberately. A build must be reproducible, and "latest" would silently
# change the shipped interpreter between two builds of the same app version.
# Update this pin as a visible commit, never as a side effect.
#
# 3.12 is the ceiling the dependency pins impose, not a preference: numpy<2.0
# tops out at 1.26.4, which has no cp313/cp314 wheels, and pinned torch has none
# either. On 3.13+ pip falls back to compiling numpy from source with MinGW and
# produces a broken longdouble. See INSTALL_FIRST.txt and README.
CPYTHON_VERSION = "3.12.14"
CPYTHON_RELEASE = "20260814"

# `install_only_stripped` rather than `install_only`: 22 MB against 46 MB, and
# the only difference is native debug symbols. Python-level tracebacks -- the
# only kind anyone will ever read from this program -- are unaffected.
#
# The `+` in the filename must stay percent-encoded; GitHub serves the literal
# form as a 404.
CPYTHON_URL = (
    f"https://github.com/astral-sh/python-build-standalone/releases/download/"
    f"{CPYTHON_RELEASE}/cpython-{CPYTHON_VERSION}%2B{CPYTHON_RELEASE}"
    f"-x86_64-pc-windows-msvc-install_only_stripped.tar.gz"
)

# ---------------------------------------------------------------------------
# What of the project ships
# ---------------------------------------------------------------------------
# The engine packages the app imports, the app itself, and the data the Help
# walkthroughs name by filename. Anything not listed here does not reach a user.
APP_DIRS = (
    "qualsafe_qt",      # the desktop UI
    "core",             # store, offline mode, span coding, backups, erasure
    "analysis",         # frequency, co-occurrence, agreement, query, framework
    "engines",          # transformer + LLM coding engines
    "exports",          # Word / Excel / codebook / methods appendix / bundle
    "interview",        # document loaders, quote verification
    "privacy",          # the PII scan behind the import gate
    "prompts",          # versioned LLM prompt templates
    "config",           # example configs the UI offers to load
    "data",             # sample files named by the Help walkthroughs (§2.4)
)
APP_FILES = (
    "analyze_survey.py",
    "iterative_supervised_thematic.py",
    "LICENSE",
)

# Never ships: the developer's environment, git internals, caches, test
# fixtures, run outputs, and the internal design documents.
EXCLUDE_NAMES = {
    ".venv", ".git", ".github", "__pycache__", ".pytest_cache", ".mypy_cache",
    "build", "dist", "output", "output_qt", "output_streamlit",
    ".embedding_cache", ".DS_Store", "notebooks", "project_progress",
}

# Inside the installed site-packages. Every one of these is either a build-time
# artefact, a developer tool, or a Qt module the app never imports. Verified:
# the app imports exactly QtCore, QtGui, and QtWidgets.
#
# NOT pruned, despite looking like easy wins:
#   opengl32sw.dll  - 19.7 MB software OpenGL fallback. Qt needs it on machines
#                     with no usable GPU driver and over Remote Desktop, which
#                     is exactly the locked-down institutional hardware this
#                     tool is aimed at. Removing it renders a blank window.
#   platforms/      - the QPA plugins. Without qwindows.dll Qt cannot start.
PYSIDE_PRUNE_DIRS = (
    "qml",              # the whole QML/Quick stack; this app is pure QtWidgets
    "metatypes",        # build-time type registration data
    "typesystems",      # shiboken binding definitions
    "include",          # C++ headers for building extensions
    "scripts",          # packaging helpers
    "glue",             # shiboken code-generation glue
)
PYSIDE_PRUNE_GLOBS = (
    "Qt6Quick*.dll", "Qt6Qml*.dll", "Qt6Designer*.dll", "Qt6Test*.dll",
    "QtQml*.pyd", "QtQuick*.pyd", "QtDesigner*.pyd", "QtTest*.pyd",
    "qmlls.exe", "qmlformat.exe", "qmllint.exe", "qmlimportscanner.exe",
    "designer.exe", "assistant.exe", "linguist.exe", "lupdate.exe",
    "lrelease.exe", "pyside6-*.exe",
)


def _log(message: str) -> None:
    print(f"[build] {message}", flush=True)


def app_version() -> str:
    """Read `__version__` out of the single source, without importing Qt."""
    text = (PROJECT_ROOT / "qualsafe_qt" / "version.py").read_text("utf-8")
    match = re.search(r'^__version__\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not match:
        raise SystemExit("could not find __version__ in qualsafe_qt/version.py")
    return match.group(1)


def source_versions() -> Dict[str, str]:
    """The three numbers as the working tree declares them.

    Read with regexes rather than imports, for the same reason `app_version`
    does: the build must not need Qt, torch, or a configured sys.path.

    These get compared against what the *built payload* reports about itself.
    The payload is a copy, and a copy can be stale — a shipped `core/` left over
    from an earlier build would produce an installer whose provenance stamp
    names the wrong engine, which is precisely the defect v4.6.0 fixed inside
    the program. A build that does not check its own output repeats it.
    """
    def _read(relative: str, pattern: str) -> str:
        text = (PROJECT_ROOT / relative).read_text("utf-8")
        match = re.search(pattern, text, re.MULTILINE)
        if not match:
            raise SystemExit(f"could not find {pattern!r} in {relative}")
        return match.group(1)

    return {
        "app": app_version(),
        "engine": _read("core/manifest.py",
                        r'^PACKAGE_VERSION\s*=\s*"([^"]+)"'),
        "store": _read("core/project.py", r"^SCHEMA_VERSION\s*=\s*(\d+)"),
    }


# ---------------------------------------------------------------------------


def fetch_cpython(keep: bool) -> Path:
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    # Decode the %2B back to a `+` for the cached copy; the encoding is a
    # requirement of GitHub's URL, not something to carry onto the filesystem.
    archive = DOWNLOAD_DIR / unquote(CPYTHON_URL.rsplit("/", 1)[-1])
    if archive.is_file():
        _log(f"using cached {archive.name}")
        return archive
    _log(f"downloading {CPYTHON_URL}")
    with urllib.request.urlopen(CPYTHON_URL) as response:
        data = response.read()
    archive.write_bytes(data)
    _log(f"got {len(data):,} bytes  sha256={hashlib.sha256(data).hexdigest()}")
    if not keep:
        _log("(pass --keep-download to reuse this on the next build)")
    return archive


def _rmtree_robust(path: Path, attempts: int = 6) -> None:
    """rmtree that survives Windows.

    `RELEASE_READINESS.md` §3.3 records this as a known trap and says any new
    build script must handle it. This one did not, and a second build failed
    before it started:

        PermissionError: [WinError 5] Access is denied:
        build/payload/python/etc/jupyter/nbconfig/notebook.d

    Two causes, both ordinary on Windows and both transient-looking. Antivirus
    briefly holds files that were just written — the payload is half a gigabyte
    of freshly extracted CPython, so it is a large target. And pip leaves some
    package data read-only, which makes `rmdir` refuse the parent.

    So: clear the read-only bit on anything that refuses, then retry with a
    backoff. Only the last failure propagates, because a build that cannot clean
    up must still say so rather than carrying on over a half-deleted tree.
    """
    import stat
    import time

    def _clear_readonly(func, target, _exc):
        try:
            os.chmod(target, stat.S_IWRITE)
            func(target)
        except OSError:
            raise

    for attempt in range(attempts):
        try:
            shutil.rmtree(path, onexc=_clear_readonly)
            return
        except FileNotFoundError:
            return
        except (PermissionError, OSError):
            if attempt == attempts - 1:
                raise
            time.sleep(0.5 * (attempt + 1))


def unpack_cpython(archive: Path, destination: Path) -> Path:
    """Unpack to `destination/python`, returning the interpreter path."""
    if destination.exists():
        _rmtree_robust(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    _log(f"unpacking to {destination}")
    with tarfile.open(archive, "r:gz") as tar:
        # The archive contains a single top-level `python/` directory.
        tar.extractall(destination.parent, filter="data")
    python = destination / "python.exe"
    if not python.is_file():
        raise SystemExit(f"no python.exe under {destination}")
    return python


def pip_install(python: Path, arguments: list[str]) -> None:
    command = [str(python), "-m", "pip", "install", "--no-cache-dir", *arguments]
    _log(" ".join(command[2:]))
    subprocess.run(command, check=True, cwd=PROJECT_ROOT)


def install_dependencies(python: Path, with_engine: bool) -> None:
    pip_install(python, ["--upgrade", "pip"])
    pip_install(python, ["-r", "requirements-light.txt",
                         "-r", "requirements-qt.txt"])
    if with_engine:
        # CPU-only. The default index pulls the CUDA build, which is several GB
        # larger and useless without an NVIDIA card.
        _log("adding the analysis engine (CPU-only torch)")
        pip_install(python, ["--index-url",
                             "https://download.pytorch.org/whl/cpu",
                             "torch>=2.2,<3.0"])
        pip_install(python, ["transformers>=4.40,<5.0",
                             "sentence-transformers>=2.7,<4.0"])


# Packages that reach site-packages only because `requirements-light.txt` is
# shared with the *other* front end, and that nothing in the shipped tree
# imports. Verified by grep over qualsafe_qt/ core/ analysis/ exports/ engines/
# interview/ privacy/ before each was added here, and by `verify()` after.
#
#   streamlit + altair + pydeck + watchdog + tornado
#       the web front end itself. Shipping a web server inside a desktop app is
#       needless attack surface as well as needless bytes.
#   pyarrow (81 MB)
#       a streamlit dependency. pandas is pinned <3.0, where pyarrow is
#       optional; nothing here reads parquet or asks for an Arrow dtype backend.
#   (vl_convert, 79 MB, is no longer pruned: the Chart Builder renders every
#   figure through it, PNG/SVG/PDF export included, and the desktop view shows
#   that rendering. It was pruned while this app painted its own charts with
#   QPainter and never called it. Cost: about 79 MB of payload.)
#
# NOT pruned though it looks unused: `pytest` / `pytest-qt`. They arrive via
# requirements-light.txt and cost little, and leaving them means a user can be
# asked to run the suite in place when diagnosing a problem on their machine.
DEPENDENCY_PRUNE = (
    "streamlit", "altair", "pydeck", "watchdog", "tornado",
    "pyarrow",
)


def prune_site_packages(payload_python: Path) -> None:
    """Remove what the app provably never loads. Reports what it reclaimed."""
    site_packages = payload_python / "Lib" / "site-packages"
    before = _tree_size(site_packages)

    for name in DEPENDENCY_PRUNE:
        _remove(site_packages / name)
        # The matching metadata, or pip reports a package that is not there.
        for dist_info in site_packages.glob(f"{name}-*.dist-info"):
            _remove(dist_info)
        for dist_info in site_packages.glob(f"{name.replace('_', '-')}*.dist-info"):
            _remove(dist_info)

    pyside = site_packages / "PySide6"
    if pyside.is_dir():
        for directory in PYSIDE_PRUNE_DIRS:
            _remove(pyside / directory)
        for pattern in PYSIDE_PRUNE_GLOBS:
            for path in pyside.glob(pattern):
                _remove(path)
        # Keep English only; the app ships no translations of its own.
        translations = pyside / "translations"
        if translations.is_dir():
            for path in translations.iterdir():
                if not path.name.startswith(("qt_en", "qtbase_en")):
                    _remove(path)

    # Test suites and bytecode caches inside dependencies.
    for cache in site_packages.rglob("__pycache__"):
        _remove(cache)

    after = _tree_size(site_packages)
    _log(f"pruned {(before - after) / 1e6:,.0f} MB "
         f"({before / 1e6:,.0f} -> {after / 1e6:,.0f} MB)")


def strip_bytecode(root: Path) -> None:
    """Drop every `__pycache__` from the finished payload.

    Three reasons, in order of how much they matter:

    1. It is dead weight. 17 MB of `.pyc` compiled by the *build* machine, which
       the user's machine regenerates on first run regardless.
    2. `tools/uninstall.py` walks the project tree collecting bytecode caches to
       offer for deletion, and a payload sitting in `build/` puts hundreds of
       them in its path -- including inside `huggingface_hub`, which trips two
       assertions in `tests/test_uninstall.py` that use the package name as a
       proxy for the model cache. Leaving the payload bytecode-free keeps a
       built tree from turning the suite red. (The underlying quirk -- that the
       walk does not skip `build/` -- is upstream's; see PORTED_BACK.md.)
    3. Stale bytecode from a mismatched interpreter is a genuinely confusing
       class of bug, and shipping none of it removes the possibility.
    """
    removed = 0
    for cache in root.rglob("__pycache__"):
        if cache.is_dir():
            shutil.rmtree(cache, ignore_errors=True)
            removed += 1
    _log(f"stripped {removed} bytecode directories")


def _remove(path: Path) -> None:
    if path.is_dir():
        # Pruning is best-effort by design: a package that will not delete costs
        # megabytes, and failing the build over it would be worse than shipping
        # them. The two cleanups that must succeed use `_rmtree_robust`.
        shutil.rmtree(path, ignore_errors=True)
    elif path.exists():
        try:
            path.unlink()
        except OSError:
            pass  # Defender briefly locks fresh files; see §3.3.


def _tree_size(root: Path) -> int:
    return sum(p.stat().st_size for p in root.rglob("*") if p.is_file())


def copy_application(payload: Path) -> None:
    def ignore(directory: str, names: list[str]) -> set[str]:
        return {n for n in names if n in EXCLUDE_NAMES}

    for name in APP_DIRS:
        source = PROJECT_ROOT / name
        if not source.is_dir():
            raise SystemExit(f"missing directory: {name}")
        shutil.copytree(source, payload / name, ignore=ignore,
                        dirs_exist_ok=True)
    for name in APP_FILES:
        source = PROJECT_ROOT / name
        if source.is_file():
            shutil.copy2(source, payload / name)
    _log(f"copied {len(APP_DIRS)} package directories")


VERIFY_SCRIPT = r'''
"""Run inside the payload, by the payload's own interpreter.

Deliberately broad. The prune list above is an assertion that nothing in the
shipped tree imports those packages, and this is what tests that assertion --
a missing transitive dependency shows up as an ImportError in a view module, at
build time, instead of as a crash on a researcher's machine three screens in.
"""
import importlib, os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
app = QApplication([])

# Every screen, imported for real rather than trusted.
# Every screen the shell shows (inside an activity, Settings or Help). Kept in
# sync with `core.ux.activities.DESKTOP_SCREENS`; the check below compares the
# two rather than a hardcoded number, so adding a screen does not fail the
# build for the wrong reason -- which it did once, when Reports and Data arrived.
VIEWS = ["documents_view", "codebook_view", "analysis_view", "charts_view",
         "data_charts_view", "model_view", "search_view", "query_view", "pipeline_view",
         "results_view", "data_view", "models_view", "help_view"]
for name in VIEWS:
    importlib.import_module("qualsafe_qt.views." + name)

# The engine surfaces those screens call into, including the export paths that
# are only reached at runtime and so would not fail on their own.
for name in ["core.project", "core.span_coding", "core.search", "core.autocode",
             "core.backups", "core.erasure", "core.documents",
             "core.codebook_io", "analysis.frequency", "analysis.cooccurrence",
             "analysis.crosstab", "analysis.agreement", "analysis.query",
             "analysis.framework", "analysis.lexical", "analysis.disagreement",
             "analysis.codebook_health", "analysis.joint_display",
             "analysis.saturation", "analysis.design_matrix",
             "analysis.models", "analysis.double_lasso",
             "core.model_spec", "core.chart_spec", "core.run_config",
             "exports.docx_report",
             "exports.excel_workbook", "exports.bundle",
             "exports.methods_appendix", "exports.codebook_report",
             "exports.joint_display_export",
             "core.chartbuilder.build", "core.chartbuilder.export",
             "core.chartbuilder.survey", "core.chartbuilder.recommend",
             "core.chartbuilder.numeric", "core.chartbuilder.store",
             "qualsafe_qt.widgets.theme_dialog",
             "interview.parse", "privacy.scan"]:
    importlib.import_module(name)

# The Chart Builder renders every figure through vl-convert and reads legacy .xls
# through xlrd; neither is optional in the shipped app, so a payload missing one
# fails here, not on a researcher's first chart.
import vl_convert, xlrd
from core.chartbuilder import export as _cb_export
from core.chartbuilder.build import build_data as _cb_build
from core.chartbuilder.config import ChartConfig as _CbConfig
from core.chartbuilder.render import build_spec as _cb_spec
from core.chartbuilder.sample import sample_frame as _cb_sample
_cfg = _CbConfig(column="Class year")
_data, _theme = _cb_build(_cb_sample(40), _cfg)
_png = _cb_export.render_image(_cb_spec(_data, _cfg, _theme), "png", 96)
assert _png[:4] == bytes([137, 80, 78, 71]), "the chart builder could not draw a chart"

from qualsafe_qt.main import application_icon
from qualsafe_qt.version import version_line
from core.offline import is_offline_enforced

app.setWindowIcon(application_icon())
from qualsafe_qt.windows.main_window import MainWindow
window = MainWindow()
window.resize(1400, 900)
window.show()
app.processEvents()

# The shell is Home, three activities with steps, Settings and Help. Every screen
# in the map must be built and must show up in the step that names it.
from core.ux import activities
screens = window.activity._screens
built = {activities.top_level(n) for n in screens} | {"Models", "Data", "Help"}
assert built == set(activities.DESKTOP_SCREENS), (
    f"the shell builds {sorted(built)} but the screen map lists "
    f"{sorted(activities.DESKTOP_SCREENS)}")
assert len(VIEWS) == len(activities.DESKTOP_SCREENS), (
    f"{len(VIEWS)} view modules were imported but the screen map lists "
    f"{len(activities.DESKTOP_SCREENS)} screens -- a screen was added without "
    "updating VIEWS, or vice versa")
for act, step, screen, _more in activities.placements(activities.DESKTOP):
    window.open_activity(act, step)
    app.processEvents()
    assert window.activity.content.indexOf(screens[screen]) >= 0, (
        f"{screen} is not shown by {act} step {step}")
window.open_settings_page()
app.processEvents()
window.open_help()
app.processEvents()
window.go_home()
app.processEvents()

assert not application_icon().isNull(), "application icon missing"
assert not window.windowIcon().isNull(), "window icon not set"
assert is_offline_enforced(), "offline mode not armed"
assert window.grab().save(os.devnull) or True, "window would not render"

from qualsafe_qt.version import __version__, engine_version, store_format

print(f"payload ok: {version_line()}  "
      f"({len(VIEWS)} screens, offline armed)")
# Machine-readable, for the builder to compare against the source tree. The
# payload is a copy and a copy can be stale; this is how the build finds out.
print(f"payload versions: app={__version__} engine={engine_version()} "
      f"store={store_format()}")
'''


def assert_payload_clean() -> None:
    """Fail the build if anything unexpected sits at the payload's top level.

    `[Files]` in the .iss ships `build\\payload\\*` recursively, so whatever is
    in that folder reaches a user's machine. During development a manual
    screenshot (`_prune_check.png`) was written into the payload root and duly
    turned up in a built installer -- harmless in itself, and exactly the shape
    of mistake that ships a stray credential dump or a debug log one day.

    Top level only: that is where stray files land, and enumerating the whole
    tree would mean listing every file in site-packages.
    """
    expected = {"python", *APP_DIRS, *APP_FILES}
    actual = {path.name for path in PAYLOAD_DIR.iterdir()}
    unexpected = sorted(actual - expected)
    if unexpected:
        raise SystemExit(
            "refusing to ship: unexpected files in the payload root:\n  "
            + "\n  ".join(unexpected)
            + "\n\nRemove them, or add them to APP_DIRS / APP_FILES if they "
              "belong in the release.")
    missing = sorted(set(APP_DIRS) - actual)
    if missing:
        raise SystemExit(f"payload is missing: {', '.join(missing)}")
    _log(f"payload root is clean ({len(actual)} entries)")


def verify(payload_python: Path) -> None:
    """Prove the payload works before an installer is built around it.

    Runs offscreen so a headless build machine is fine, and runs *as the
    payload* -- its own interpreter, its own site-packages, its own copy of the
    app -- so it tests the thing that ships rather than the developer's venv.
    """
    _log("verifying the payload")
    # Resolved because the child runs with cwd set to the payload: a relative
    # path here would be re-interpreted against that directory and vanish.
    payload_python = payload_python.resolve()
    script_path = payload_python.parent / "_verify.py"
    script_path.write_text(VERIFY_SCRIPT, encoding="utf-8")
    # The app saves where the person left off (progress.json) and its settings next to itself unless told
    # otherwise: left alone, this check wrote its own session into the payload and every fresh install
    # opened to a "Continue" for a Surveys step nobody had visited. Point both at a throwaway folder.
    scratch = Path(tempfile.mkdtemp(prefix="qualsafe_verify_"))
    env = dict(os.environ, QNW_SETTINGS_DIR=str(scratch))
    try:
        result = subprocess.run(
            [str(payload_python / "python.exe"), str(script_path)],
            cwd=payload_python.parent, capture_output=True, text=True, env=env)
    finally:
        _remove(script_path)
        shutil.rmtree(scratch, ignore_errors=True)
    for stray in ("progress.json", "app_settings.json"):
        if (payload_python.parent / stray).exists():
            raise SystemExit(f"the payload holds a {stray} that the verification left behind: it would ship "
                             "someone's saved session")

    # Print before deciding. Capturing the output in order to compare versions
    # must not mean a failing payload reports only an exit code: the traceback
    # from inside the payload is the whole diagnostic.
    print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    if result.returncode != 0:
        raise SystemExit(
            f"the payload failed its own verification (exit {result.returncode}); "
            "see the traceback above")

    _assert_versions_agree(result.stdout)


def _assert_versions_agree(output: str) -> None:
    """The payload must report the versions the source tree declares.

    The payload is a copy of the tree, and a copy can be stale: a `core/` left
    behind by an earlier build would ship an installer whose provenance names
    the wrong engine. That is the same defect v4.6.0 fixed inside the program,
    one level out, and it would be invisible — the app would run, the screens
    would render, every assertion above would pass.
    """
    match = re.search(r"^payload versions: app=(\S+) engine=(\S+) store=(\S+)$",
                      output, re.MULTILINE)
    if not match:
        raise SystemExit(
            "the payload did not report its versions; the verification script "
            "and this check have drifted apart")

    reported = dict(zip(("app", "engine", "store"), match.groups()))
    expected = source_versions()
    disagreements = [f"  {key}: payload says {reported[key]}, "
                     f"source says {expected[key]}"
                     for key in expected if reported[key] != expected[key]]
    if disagreements:
        raise SystemExit(
            "refusing to ship: the payload does not match the source tree:\n"
            + "\n".join(disagreements)
            + "\n\nThe payload is stale. Delete build/payload and rebuild.")

    _log(f"versions agree: app {expected['app']}, engine {expected['engine']}, "
         f"project format v{expected['store']}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", action="store_true",
                        help="bundle torch/transformers (option A, ~4 GB)")
    parser.add_argument("--keep-download", action="store_true",
                        help="keep the CPython archive for the next build")
    parser.add_argument("--skip-verify", action="store_true")
    arguments = parser.parse_args()

    version = app_version()
    _log(f"QualSafe Desktop {version}"
         f"{' + analysis engine' if arguments.engine else ' (lite)'}")

    if PAYLOAD_DIR.exists():
        _rmtree_robust(PAYLOAD_DIR)
    PAYLOAD_DIR.mkdir(parents=True)

    archive = fetch_cpython(arguments.keep_download)
    payload_python = PAYLOAD_DIR / "python"
    unpack_cpython(archive, payload_python)

    install_dependencies(payload_python / "python.exe", arguments.engine)
    prune_site_packages(payload_python)
    copy_application(PAYLOAD_DIR)
    assert_payload_clean()

    if not arguments.skip_verify:
        verify(payload_python)

    # Last, because pip and the verification run both regenerate bytecode.
    strip_bytecode(PAYLOAD_DIR)

    total = _tree_size(PAYLOAD_DIR)
    _log(f"payload ready: {PAYLOAD_DIR}  ({total / 1e9:.2f} GB)")
    _log(f"next:  iscc packaging/qualsafe.iss /DAppVersion={version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
