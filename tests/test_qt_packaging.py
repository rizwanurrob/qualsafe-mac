"""
What the installer depends on, pinned.

These are cheap assertions about facts the build script trusts. Each one failed
for real, or would have shipped something wrong, during the packaging work:

* the desktop version quietly reverting to the engine's, so the installer
  claims to be the same artefact as a program it shares no interface with;
* the icon vanishing, which is invisible until Windows shows a blank window;
* the prune list growing to include something the app actually imports, which
  surfaces as an ImportError three screens into a researcher's session.

Nothing here needs Qt to be installed except where marked, and nothing needs a
network, a model, or a built payload.
"""

from __future__ import annotations

import ast
import importlib.util
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PACKAGING = PROJECT_ROOT / "packaging"

# Most of this file reads the .iss, the icon and the build script as text, so it
# runs anywhere and deliberately has no module-level importorskip("PySide6"):
# checking that the installer is sane should not require the GUI toolkit.
#
# Three tests do need a live QApplication. Without this marker they requested a
# `qapp` fixture that does not exist in a Streamlit-only environment and errored
# at setup rather than skipping — a red suite for something that is not a
# defect. Surfaced by merging the desktop fork into the mainline, which is the
# first time one install collected a file written for the other.
requires_qt = pytest.mark.skipif(
    importlib.util.find_spec("PySide6") is None,
    reason="Qt front end not installed")

# The tree that ships. `data/` is included because the Help walkthroughs name
# files inside it, and `tests/` is not because a user never runs it.
SHIPPED_SOURCE_DIRS = ("qualsafe_qt", "core", "analysis", "exports", "engines",
                       "interview", "privacy")


def _build_script_namespace() -> dict:
    """Read `build_payload.py`'s constants without importing it.

    Importing would run its argparse-free module body, which is harmless, but
    parsing keeps this test independent of anything the script imports.
    """
    source = (PACKAGING / "build_payload.py").read_text("utf-8")
    tree = ast.parse(source)
    namespace: dict = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name):
                try:
                    namespace[target.id] = ast.literal_eval(node.value)
                except ValueError:
                    continue  # f-strings and the like; not needed here
    return namespace


# -- identity ---------------------------------------------------------------


def test_the_desktop_version_is_its_own_number() -> None:
    """It must not silently report the engine's version.

    The engine is shared byte for byte with another program on its own release
    cadence. Reporting its number here would claim the two ship together.
    """
    from core.manifest import PACKAGE_VERSION
    from qualsafe_qt.version import __version__

    assert __version__ != PACKAGE_VERSION, (
        "the desktop app is reporting the engine's version as its own")
    assert re.fullmatch(r"\d+\.\d+\.\d+(-ux\d+)?", __version__), __version__


def test_the_version_line_names_both_versions() -> None:
    """A methods appendix needs the engine version; a bug report needs the
    app's. Showing one without the other loses information a reader needs."""
    from core.manifest import PACKAGE_VERSION
    from qualsafe_qt.version import __version__, version_line

    line = version_line()
    assert __version__ in line
    assert str(PACKAGE_VERSION) in line


def test_the_store_format_is_reported_too() -> None:
    """The third number, and the one usually left out.

    Neither the app version nor the engine version tells someone handed a `.qnw`
    by a colleague whether their install can open it. A store from a newer
    schema raises rather than degrading, so the schema is the number that
    answers the question — and it is the one that had gone missing from the run
    manifest and the methods appendix as well.
    """
    from core.project import SCHEMA_VERSION
    from qualsafe_qt.version import store_format

    assert store_format() == str(SCHEMA_VERSION)


@requires_qt
def test_the_about_box_shows_all_three_numbers(qapp) -> None:
    """Checked on the assembled text rather than on the helpers, because the
    About box is where a user actually reads them."""
    from unittest.mock import patch

    from core.manifest import PACKAGE_VERSION
    from core.project import SCHEMA_VERSION
    from qualsafe_qt.version import __version__
    from qualsafe_qt.windows.main_window import MainWindow

    window = MainWindow()
    try:
        with patch("qualsafe_qt.windows.main_window.QMessageBox.about") as about:
            window._show_about()
        body = about.call_args[0][2]
    finally:
        window.close()

    assert __version__ in body, "the About box does not name the app version"
    assert str(PACKAGE_VERSION) in body, "no engine version"
    assert f"v{SCHEMA_VERSION}" in body, "no project format version"


class TestTheBuildChecksItsOwnOutput:
    """A built payload is a copy of the tree, and a copy can be stale.

    A `core/` left behind by an earlier build ships an installer whose
    provenance names the wrong engine — the same defect v4.6.0 fixed inside the
    program, one level out, and invisible: the app runs, the screens render,
    every other assertion in `verify()` passes.
    """

    @staticmethod
    def _builder():
        import importlib.util

        path = PROJECT_ROOT / "packaging" / "build_payload.py"
        spec = importlib.util.spec_from_file_location("build_payload", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_the_source_versions_are_read_without_importing_anything(self):
        """Regexes, not imports: the build must not need Qt, torch, or a
        configured sys.path."""
        from core.manifest import PACKAGE_VERSION
        from core.project import SCHEMA_VERSION
        from qualsafe_qt.version import __version__

        found = self._builder().source_versions()

        assert found == {"app": __version__,
                         "engine": str(PACKAGE_VERSION),
                         "store": str(SCHEMA_VERSION)}

    def test_a_matching_payload_passes(self):
        versions = self._builder().source_versions()
        line = (f"payload versions: app={versions['app']} "
                f"engine={versions['engine']} store={versions['store']}\n")

        self._builder()._assert_versions_agree(line)   # must not raise

    def test_a_stale_engine_in_the_payload_stops_the_build(self):
        builder = self._builder()
        versions = builder.source_versions()
        line = (f"payload versions: app={versions['app']} "
                f"engine=4.4.0 store={versions['store']}\n")

        with pytest.raises(SystemExit, match="does not match the source tree"):
            builder._assert_versions_agree(line)

    def test_a_stale_store_format_in_the_payload_stops_the_build(self):
        builder = self._builder()
        versions = builder.source_versions()
        line = (f"payload versions: app={versions['app']} "
                f"engine={versions['engine']} store=4\n")

        with pytest.raises(SystemExit, match="does not match the source tree"):
            builder._assert_versions_agree(line)

    def test_a_silent_verification_script_is_a_failure_not_a_pass(self):
        """If the two halves drift apart, the check must fail loudly rather
        than quietly stop checking."""
        with pytest.raises(SystemExit, match="did not report its versions"):
            self._builder()._assert_versions_agree("payload ok: 0.99.0\n")

    def test_the_verification_script_prints_the_line_the_builder_parses(self):
        """The two live in the same file but run in different interpreters, so
        nothing else connects them."""
        builder = self._builder()

        assert "payload versions: app=" in builder.VERIFY_SCRIPT


def test_the_version_is_a_plain_literal_the_build_script_can_read() -> None:
    """`build_payload.app_version()` regexes this out rather than importing Qt.
    A computed or multi-line assignment would break the build, not a test."""
    source = (PROJECT_ROOT / "qualsafe_qt" / "version.py").read_text("utf-8")
    assert re.search(r'^__version__\s*=\s*"\d+\.\d+\.\d+(-ux\d+)?"$', source,
                     re.MULTILINE), "version.py must keep a one-line literal"



def test_the_citation_file_cites_this_version() -> None:
    """CITATION.cff is what GitHub's "Cite this repository" and Zenodo read.
    It said 0.99.0 through ten releases, so a paper citing it named a version
    that could not open the reader's projects."""
    from qualsafe_qt.version import __version__

    cff = (PROJECT_ROOT / "CITATION.cff").read_text("utf-8")
    found = re.search(r'^version:\s*"([^"]+)"', cff, re.MULTILINE)
    assert found, "CITATION.cff has no version line"
    assert found.group(1) == __version__

# -- the icon ---------------------------------------------------------------


def test_the_application_icon_ships_and_covers_the_sizes_windows_asks_for() -> None:
    icon = PROJECT_ROOT / "qualsafe_qt" / "resources" / "qualsafe.ico"
    assert icon.is_file(), "run: python packaging/make_icon.py"

    from PIL import Image
    with Image.open(icon) as image:
        sizes = {size for size in image.info.get("sizes", ())}
    # 16 title bar, 32 taskbar and alt-tab, 48 desktop, 256 shell and installer.
    for required in ((16, 16), (32, 32), (48, 48), (256, 256)):
        assert required in sizes, f"icon is missing {required}: {sorted(sizes)}"


@requires_qt
def test_a_missing_icon_does_not_stop_the_app_starting(qapp, monkeypatch) -> None:
    """A packaging mistake must not be the reason a researcher cannot work."""
    from qualsafe_qt import main as main_module

    monkeypatch.setattr(main_module, "ICON_PATH", Path("nowhere.ico"))
    assert main_module.application_icon().isNull()


# -- the prune list ---------------------------------------------------------


def test_the_app_still_works_with_every_pruned_package_absent() -> None:
    """The property that actually matters, tested the way it actually breaks.

    A first attempt at this grepped for imports of the pruned packages and
    failed on two false positives: `core/theme.py` imports altair inside a
    `try` and falls back, and `core/viz_export.py` imports vl_convert lazily
    but is never reached from this app at all. Neither is a defect, and a
    static rule that flags them would be pressure to delete real code.

    So block the packages at import time and load every screen. That is
    precisely what a user's machine does after the build prunes them, and it
    catches the case static analysis cannot: a *transitive* dependency landing
    on a pruned package.

    A subprocess, because these modules are already in `sys.modules` here.
    """
    pytest.importorskip("PySide6")
    pruned = list(_build_script_namespace()["DEPENDENCY_PRUNE"])
    assert pruned, "could not read DEPENDENCY_PRUNE from build_payload.py"

    program = _IMPORT_BLOCK_PROGRAM.format(pruned=pruned)
    result = subprocess.run([sys.executable, "-c", program],
                            cwd=PROJECT_ROOT, capture_output=True, text=True,
                            env={**os.environ, "QT_QPA_PLATFORM": "offscreen"})
    assert result.returncode == 0, (
        "the app cannot start once the payload's pruned packages are gone:\n"
        + result.stdout + result.stderr)


_IMPORT_BLOCK_PROGRAM = '''
import importlib, sys

BLOCKED = {pruned}


class _Blocker:
    """Make the pruned packages unimportable, as the built payload does."""

    def find_module(self, name, path=None):
        return self.find_spec(name, path)

    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in BLOCKED:
            raise ImportError(f"{{name}} is pruned from the installer payload")
        return None


sys.meta_path.insert(0, _Blocker())

for name in ["documents_view", "codebook_view", "analysis_view",
             "search_view", "query_view", "pipeline_view", "results_view",
             "data_view", "models_view", "help_view"]:
    importlib.import_module("qualsafe_qt.views." + name)

for name in ["core.project", "core.span_coding", "core.search",
             "core.autocode", "core.backups", "core.erasure",
             "core.documents", "core.codebook_io", "core.theme",
             "analysis.frequency", "analysis.cooccurrence",
             "analysis.crosstab", "analysis.agreement", "analysis.query",
             "analysis.framework", "analysis.lexical",
             "analysis.disagreement", "analysis.codebook_health",
             "exports.docx_report", "exports.excel_workbook",
             "exports.bundle", "exports.methods_appendix",
             "exports.codebook_report", "interview.parse", "privacy.scan"]:
    importlib.import_module(name)

from PySide6.QtWidgets import QApplication
app = QApplication([])
from qualsafe_qt.windows.main_window import MainWindow
window = MainWindow()
window.show()
app.processEvents()
print("ok")
'''


def test_every_directory_the_payload_ships_exists() -> None:
    namespace = _build_script_namespace()
    for name in namespace["APP_DIRS"]:
        assert (PROJECT_ROOT / name).is_dir(), f"build ships missing dir {name}"


# -- the installer script ---------------------------------------------------


def test_the_installer_installs_per_user_and_needs_no_admin() -> None:
    """A per-user install is what lets a researcher on a managed machine
    install this without calling IT (RELEASE_READINESS.md §5)."""
    script = (PACKAGING / "qualsafe.iss").read_text("utf-8")
    assert "PrivilegesRequired=lowest" in script
def test_the_shortcut_launches_without_a_console_window() -> None:
    """Started through python.exe a console sits behind the app for its whole
    life (RELEASE_READINESS.md §1.3)."""
    script = (PACKAGING / "qualsafe.iss").read_text("utf-8")
    assert re.search(r'#define\s+AppExeName\s+"pythonw\.exe"', script)

    # Check what is actually launched, not the prose around it: the interpreter
    # directory is literally named `python`, so a substring search over the
    # whole file matches comments and paths and proves nothing.
    launched = re.findall(r'Filename:\s*"([^"]+)"', script)
    assert launched, "expected [Icons] / [Run] entries"
    for target in launched:
        assert not target.endswith("\\python.exe"), (
            f"{target} would leave a console window open behind the app")


def test_the_appid_is_a_fixed_literal() -> None:
    """It is how Windows recognises an upgrade. If it ever moves, the old
    install is stranded in Add/Remove Programs with no way to remove it."""
    script = (PACKAGING / "qualsafe.iss").read_text("utf-8")
    match = re.search(r"^AppId=\{\{([0-9A-F-]{36})\}", script, re.MULTILINE)
    assert match, "AppId must be a literal GUID"


def test_the_uninstaller_can_run_unattended() -> None:
    """A plain `MsgBox` in [Code] ignores /SUPPRESSMSGBOXES and blocks forever
    with no visible window under /VERYSILENT -- an unattended uninstall hangs
    rather than fails. Found by running one. `SuppressibleMsgBox` takes the
    supplied default instead."""
    script = (PACKAGING / "qualsafe.iss").read_text("utf-8")

    code = script[script.index("[Code]"):]
    # Strip comments so the word inside an explanatory { ... } block does not
    # read as a call.
    code = re.sub(r"\{[^}]*\}", "", code)

    calls = re.findall(r"(?<![A-Za-z])(\w*MsgBox)\s*\(", code)
    assert calls, "expected the uninstall confirmation to still be there"
    for call in calls:
        assert call == "SuppressibleMsgBox", (
            f"{call} in [Code] blocks an unattended uninstall; "
            "use SuppressibleMsgBox with an explicit default")


def test_the_installer_rejects_a_path_too_long_for_windows() -> None:
    """The payload nests to 120 characters, so a long install directory makes
    some files unwritable and the install rolls back with an unexplained
    "MoveFile failed; code 3". The guard must live in `PrepareToInstall`,
    which -- unlike NextButtonClick -- also runs during a silent install."""
    script = (PACKAGING / "qualsafe.iss").read_text("utf-8")
    assert "function PrepareToInstall(" in script
    assert "MaxInstallDirLength" in script

    match = re.search(r"MaxInstallDirLength\s*=\s*(\d+)", script)
    assert match, "the limit must be a named constant"
    limit = int(match.group(1))

    # 259 is the usable MAX_PATH budget. The limit has to leave room for the
    # deepest path inside the payload, measured at 120 characters.
    assert 100 <= limit <= 259 - 120 - 1, (
        f"an install-directory limit of {limit} does not leave room for the "
        "payload's own nesting inside MAX_PATH")


def test_the_payload_guard_lists_everything_the_build_ships() -> None:
    """`[Files]` ships the payload root recursively, so a stray file left
    there reaches users -- one did. The guard compares against exactly the
    lists the build copies from."""
    namespace = _build_script_namespace()
    source = (PACKAGING / "build_payload.py").read_text("utf-8")
    assert "def assert_payload_clean(" in source
    assert "assert_payload_clean()" in source.split("def main(")[-1], (
        "the guard exists but main() never calls it")
    assert namespace["APP_DIRS"] and namespace["APP_FILES"]


def test_the_entry_point_module_exists() -> None:
    """The shortcut runs `pythonw.exe -m qualsafe_qt`, which needs __main__."""
    assert (PROJECT_ROOT / "qualsafe_qt" / "__main__.py").is_file()


def test_the_icon_uses_frames_windows_can_actually_render() -> None:
    """Windows accepts a PNG-compressed icon frame only at 256x256. At 16
    through 128 the shell expects an uncompressed BMP/DIB and renders *nothing*
    otherwise -- no error, no fallback, just a blank shortcut.

    Pillow's ICO writer defaults to PNG for every frame, so the first build of
    this icon shipped unrenderable. It was invisible to inspection because
    Pillow re-reads its own PNG frames perfectly; only Windows refuses them.
    """
    import struct

    icon = PROJECT_ROOT / "qualsafe_qt" / "resources" / "qualsafe.ico"
    raw = icon.read_bytes()
    count = struct.unpack("<HHH", raw[:6])[2]
    assert count, "icon has no frames"

    unrenderable = []
    for index in range(count):
        entry = 6 + index * 16
        width, _h, _c, _r, _p, _bpp, _size, offset = struct.unpack(
            "<BBBBHHII", raw[entry:entry + 16])
        width = width or 256
        is_png = raw[offset:offset + 8] == b"\x89PNG\r\n\x1a\n"
        if is_png and width < 256:
            unrenderable.append(width)

    assert not unrenderable, (
        f"frames at {unrenderable} are PNG-compressed; Windows will show no "
        "icon. Regenerate with bitmap_format='bmp' "
        "(python packaging/make_icon.py).")


def test_the_installer_and_the_app_agree_on_the_app_user_model_id() -> None:
    """They must be identical, and this is not cosmetic.

    Windows uses the AppUserModelID to decide that a running window and a
    shortcut are the same application. Set it on only one side, or set two
    different values, and the shell cannot resolve the pair:

    * neither side set -> the taskbar identifies the button by its executable
      and draws `pythonw.exe`'s icon, i.e. the Python logo;
    * process set, shortcut not -> the taskbar button resolves no icon at all
      and comes up blank;
    * both set and equal -> the app's own icon, correct grouping, working pin.

    All three states were observed while getting this right.
    """
    source = (PROJECT_ROOT / "qualsafe_qt" / "main.py").read_text("utf-8")
    match = re.search(r'^APP_USER_MODEL_ID\s*=\s*"([^"]+)"', source, re.MULTILINE)
    assert match, "main.py must define APP_USER_MODEL_ID as a plain literal"
    app_id = match.group(1)

    script = (PACKAGING / "qualsafe.iss").read_text("utf-8")
    defined = re.search(r'#define\s+AppUserId\s+"([^"]+)"', script)
    assert defined, "the installer script must define AppUserId"
    assert defined.group(1) == app_id, (
        f"installer says {defined.group(1)!r}, app says {app_id!r}; Windows "
        "will treat them as two different applications")

    # And every shortcut must actually carry it -- defining it is not enough.
    # Inno continues a directive with a trailing backslash, so join those into
    # one logical line first. A regex written to span the continuations was
    # tried and silently matched only the first physical line, which would have
    # let a shortcut with no AppUserModelID pass this check.
    icons_section = script.split("[Icons]", 1)[1].split("\n[", 1)[0]
    joined = re.sub(r"\\\s*\n\s*", " ", icons_section)
    entries = [line for line in joined.splitlines() if line.startswith("Name:")]

    assert entries, "expected [Icons] entries"
    for entry in entries:
        assert "AppUserModelID:" in entry, (
            "a shortcut without AppUserModelID gives a blank taskbar icon:\n  "
            + entry[:90])


@requires_qt
def test_the_build_verification_covers_every_screen_the_shell_shows(qapp) -> None:
    """`build_payload.VERIFY_SCRIPT` imports a list of view modules and asserts
    the tab count matches it. If a screen is added to the shell and not to that
    list, the build fails -- correctly, but for a confusing reason. This keeps
    the two in step, and names the mismatch plainly when they drift.

    Reports and Data both tripped this on the way in.
    """
    from core.ux import activities
    from qualsafe_qt.windows.main_window import MainWindow

    source = (PACKAGING / "build_payload.py").read_text("utf-8")
    block = re.search(r"VIEWS = \[(.*?)\]", source, re.DOTALL)
    assert block, "could not find VIEWS in the verification script"
    listed = set(re.findall(r'"(\w+_view)"', block.group(1)))

    window = MainWindow()
    try:
        shown = {activities.top_level(n) for n in window.activity._screens}
        shown |= {"Models", "Data", "Help"}      # Settings and Help
    finally:
        window.close()

    assert shown == set(activities.DESKTOP_SCREENS)
    assert len(listed) == len(shown), (
        f"the shell shows {len(shown)} screens but build_payload.VIEWS lists "
        f"{len(listed)} view modules: {sorted(listed)}")
    assert "QTabWidget" not in source.split("VERIFY_SCRIPT")[1].split("'''")[1], (
        "the build check must not count tabs: the shell no longer has a tab row")


def _uninstall_delete_section() -> str:
    """The [UninstallDelete] section, found at the start of a line.

    A plain `split("[UninstallDelete]")` matches the *comment* near the top of
    the script that explains the section, and then parses the comment block
    instead. Anchoring to a line start is the difference between checking the
    directives and checking prose about them.
    """
    script = (PACKAGING / "qualsafe.iss").read_text("utf-8")
    match = re.search(r"^\[UninstallDelete\]\s*$", script, re.MULTILINE)
    assert match, "no [UninstallDelete] section"
    rest = script[match.end():]
    following = re.search(r"^\[", rest, re.MULTILINE)
    return rest[:following.start()] if following else rest


def test_the_uninstaller_never_touches_anything_outside_the_program() -> None:
    """Projects, saved output, and the model cache live outside {app}. Deleting
    a researcher's coded work because they uninstalled would be unforgivable
    (RELEASE_READINESS.md 3.4)."""
    section = _uninstall_delete_section()

    targets = re.findall(r'Name:\s*"([^"]+)"', section)
    assert targets, "expected [UninstallDelete] entries"
    for target in targets:
        assert target == "{app}" or target.startswith("{app}\\"), (
            f"uninstall would delete {target}, which is outside the program")

    script = (PACKAGING / "qualsafe.iss").read_text("utf-8")
    for forbidden in ("{userdocs}", "{userprofile}", "{localappdata}\\Qual",
                      ".cache", "huggingface", "*.qnw"):
        assert forbidden not in script, (
            f"the installer script references {forbidden}")


def test_the_uninstaller_removes_the_directories_it_created() -> None:
    """Running the program writes bytecode through the whole tree, and Inno
    does not track files it did not install. An earlier version of this script
    listed individual __pycache__ paths; a measured uninstall then left 716
    .pyc files behind with the install folder still standing.

    So every directory the installer creates is removed wholesale.
    """
    section = _uninstall_delete_section()
    recursive = set(re.findall(
        r'Type:\s*filesandordirs;\s*Name:\s*"\{app\}\\([^"\\]+)"', section))

    shipped = set(_build_script_namespace()["APP_DIRS"]) | {"python"}

    # `data` is deliberately excluded: the Help walkthrough sends a new user to
    # that folder, so it may hold their own transcripts.
    missing = sorted((shipped - {"data"}) - recursive)
    assert not missing, (
        "these installed directories would survive an uninstall, holding "
        f"generated bytecode: {missing}")

    assert "data" not in recursive, (
        "{app}\\data must not be deleted recursively -- users are told to put "
        "their own files there")


def test_the_uninstaller_only_removes_the_app_folder_when_it_is_empty() -> None:
    """If a researcher kept anything inside the installation, the folder must
    survive with their file in it rather than being deleted around them."""
    section = _uninstall_delete_section()

    assert re.search(r'Type:\s*dirifempty;\s*Name:\s*"\{app\}"', section), (
        "the install folder should be removed with dirifempty, never "
        "filesandordirs")
    assert not re.search(r'Type:\s*filesandordirs;\s*Name:\s*"\{app\}"',
                         section), (
        "a recursive delete of {app} would take a user's files with it")


# -- the model download script ------------------------------------------------------------------------------


def test_the_payload_carries_the_model_download_script_and_nothing_else_from_tools(tmp_path) -> None:
    """The Models screen's "Download & use" runs `tools/download_models.py` in its own process. An installer
    without that file failed on a student's Mac with "can't open file ... download_models.py" (and the
    Windows installer had the same gap). Only that one script ships from `tools`; the rest is for developers."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("build_payload_under_test", PACKAGING / "build_payload.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert "tools" in module.APP_DIRS and module.TOOLS_SHIPPED == ("download_models.py",)
    module.copy_application(tmp_path)
    shipped = sorted(p.name for p in (tmp_path / "tools").iterdir())
    assert shipped == ["download_models.py"]
    # and the script the Models screen starts is exactly the one that shipped
    from core.model_manager import DOWNLOAD_SCRIPT

    assert DOWNLOAD_SCRIPT.name in shipped and DOWNLOAD_SCRIPT.parent.name == "tools"


def test_uninstalling_removes_the_tools_folder_too() -> None:
    script = (PACKAGING / "qualsafe.iss").read_text("utf-8")
    assert r'Name: "{app}\tools"' in script
