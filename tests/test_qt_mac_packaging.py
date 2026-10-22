"""
The macOS build, tested from wherever the suite runs.

The Mac build itself needs a Mac: it runs `codesign`, `otool` and a macOS Python.
None of that is reachable from the Windows machine the app is developed on, so
this file tests what *can* be tested there -- everything `packaging/mac_bundle.py`
computes -- and is honest about the rest. Passing here means the plans are right,
not that a Mac has built and launched the app. That is `.github/workflows/mac.yml`.

Two kinds of test:

* **Plan tests** check the output of a pure function (the plist, the signing
  command lines, the launcher text).
* **Behavioural tests** run the generated launcher against a stub interpreter in
  a temp directory, so the paths and environment it sets are checked by
  executing it rather than by reading it.
"""

from __future__ import annotations

import fnmatch
import importlib.util
import os
import plistlib
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PACKAGING = PROJECT_ROOT / "packaging"

requires_qt = pytest.mark.skipif(
    importlib.util.find_spec("PySide6") is None,
    reason="Qt front end not installed")


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, PACKAGING / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


mb = _load("mac_bundle", "mac_bundle.py")

MACHO64 = b"\xcf\xfa\xed\xfe" + b"\x07\x00\x00\x01" + b"\x00" * 24
FAT = b"\xca\xfe\xba\xbe" + (2).to_bytes(4, "big") + b"\x00" * 24
JAVA_CLASS = b"\xca\xfe\xba\xbe" + (52).to_bytes(4, "big") + b"\x00" * 24


# -- Info.plist --------------------------------------------------------------


def test_the_plist_names_the_executable_the_bundle_actually_contains(tmp_path) -> None:
    app = tmp_path / "QualSafe.app"
    mb.write_bundle_shell(app, "0.99.7")
    info = plistlib.loads((app / "Contents" / "Info.plist").read_bytes())
    assert (app / "Contents" / "MacOS" / info["CFBundleExecutable"]).is_file()


def test_the_plist_carries_the_app_version() -> None:
    info = plistlib.loads(mb.info_plist("1.2.3"))
    assert info["CFBundleShortVersionString"] == "1.2.3"
    assert info["CFBundleVersion"] == "1.2.3"


def test_the_plist_refuses_macs_the_qt_wheel_cannot_load() -> None:
    """PySide6 6.11 ships one macOS wheel, tagged macosx_13_0_universal2. Below
    that the app dies in dlopen with an unreadable message; LSMinimumSystemVersion
    makes the system explain it instead."""
    info = plistlib.loads(mb.info_plist("1.0.0"))
    major = int(info["LSMinimumSystemVersion"].split(".")[0])
    assert major >= 13


def test_the_bundle_id_is_reverse_dns_and_stable() -> None:
    # Privacy grants and Gatekeeper history key on this; it must not drift.
    assert mb.BUNDLE_ID == "org.qualsafe.desktop"
    assert mb.BUNDLE_ID.count(".") >= 2


def test_the_plist_is_retina_capable() -> None:
    assert plistlib.loads(mb.info_plist("1.0.0"))["NSHighResolutionCapable"] is True


def test_the_icon_the_plist_names_exists_in_the_source_tree() -> None:
    icon = PROJECT_ROOT / "qualsafe_qt" / "resources" / mb.ICON_FILE
    assert icon.is_file(), "run: python packaging/make_icon.py --icns-only"
    assert icon.read_bytes()[:4] == b"icns"


def test_the_icns_holds_the_retina_sizes() -> None:
    PIL = pytest.importorskip("PIL")
    from PIL import Image

    icon = PROJECT_ROOT / "qualsafe_qt" / "resources" / mb.ICON_FILE
    with Image.open(icon) as image:
        sizes = {(w, h) for (w, h, _scale) in image.info["sizes"]}
    assert (512, 512) in sizes and (256, 256) in sizes and (128, 128) in sizes


def test_entitlements_grant_only_the_two_exceptions_python_needs() -> None:
    granted = plistlib.loads(mb.entitlements_plist())
    assert set(granted) == {
        "com.apple.security.cs.allow-unsigned-executable-memory",
        "com.apple.security.cs.disable-library-validation",
    }
    assert all(v is True for v in granted.values())
    # The sandbox would need a bookmark for every file the analyst opens.
    assert "com.apple.security.app-sandbox" not in granted


# -- the launcher ------------------------------------------------------------


def test_the_launcher_script_is_valid_bash() -> None:
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("no bash on this machine")
    result = subprocess.run([bash, "-n"], input=mb.launcher_script(),
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_the_launcher_states_what_keeps_the_signed_bundle_sealed() -> None:
    script = mb.launcher_script()
    assert script.startswith("#!/bin/bash\n")
    assert "PYTHONDONTWRITEBYTECODE=1" in script   # never mutate a signed bundle
    assert "PYTHONNOUSERSITE=1" in script          # user packages must not shadow ours
    assert "-m qualsafe_qt" in script
    assert '"$@"' in script                        # arguments pass through
    # The menu bar name comes from the interpreter's file name, so the launcher
    # must run the QualSafe-named link -- not python3, and not `exec -a`.
    assert f'exec "$RES/python/bin/{mb.INTERPRETER_LINK}"' in script
    assert "exec -a" not in script


def test_the_launcher_locates_python_relative_to_itself() -> None:
    script = mb.launcher_script()
    # An absolute path here would work on the build machine and nowhere else.
    assert "/Users/" not in script and "/Applications/" not in script
    assert '"$RES/python/bin/' in script


@pytest.mark.skipif(shutil.which("bash") is None, reason="no bash on this machine")
def test_running_the_launcher_starts_the_bundled_python_in_resources(tmp_path) -> None:
    """Execute the real generated launcher against a stub interpreter.

    The stub records where it was started, what it was told to run, and the two
    environment variables the launcher promises to set -- so the contract is
    checked by running it, not by reading the script.
    """
    app = tmp_path / "QualSafe.app"
    launcher = mb.write_bundle_shell(app, "0.99.7")
    python = app / "Contents" / "Resources" / "python" / "bin" / mb.INTERPRETER_LINK
    python.parent.mkdir(parents=True)
    record = tmp_path / "record.txt"
    python.write_text(
        "#!/bin/bash\n"
        f'{{ echo "cwd=$(pwd)"; echo "args=$*"; '
        'echo "bytecode=$PYTHONDONTWRITEBYTECODE"; echo "usersite=$PYTHONNOUSERSITE"; } '
        f'> "{record.as_posix()}"\n', encoding="utf-8", newline="\n")
    python.chmod(python.stat().st_mode | stat.S_IXUSR)

    result = subprocess.run([shutil.which("bash"), launcher.as_posix(), "--flag"],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    lines = dict(line.split("=", 1) for line in record.read_text().splitlines())
    assert Path(lines["cwd"]).name == "Resources"
    assert lines["args"] == "-m qualsafe_qt --flag"
    assert lines["bytecode"] == "1"
    assert lines["usersite"] == "1"


def test_the_interpreter_link_is_relative_and_named_for_the_app(tmp_path) -> None:
    python_dir = tmp_path / "python"
    (python_dir / "bin").mkdir(parents=True)
    (python_dir / "bin" / "python3").write_bytes(MACHO64)
    try:
        link = mb.link_interpreter(python_dir)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not permitted on this machine")
    assert link.name == mb.INTERPRETER_LINK == mb.BUNDLE_NAME
    # Relative: an absolute target would name the machine that built it, and the
    # app would break the moment it was dragged to Applications.
    assert os.readlink(link) == "python3"
    assert link.resolve() == (python_dir / "bin" / "python3").resolve()
    mb.link_interpreter(python_dir)            # idempotent: a rebuild must not fail


def test_the_bundle_shell_has_the_layout_macos_requires(tmp_path) -> None:
    icon = PROJECT_ROOT / "qualsafe_qt" / "resources" / mb.ICON_FILE
    app = tmp_path / "QualSafe.app"
    launcher = mb.write_bundle_shell(app, "0.99.7", icon)
    assert (app / "Contents" / "Info.plist").is_file()
    assert (app / "Contents" / "PkgInfo").read_bytes() == b"APPL????"
    assert (app / "Contents" / "Resources" / mb.ICON_FILE).is_file()
    assert launcher == app / "Contents" / "MacOS" / mb.EXECUTABLE
    if os.name == "posix":
        assert os.access(launcher, os.X_OK), "the launcher must be executable"


def test_the_launcher_uses_unix_line_endings(tmp_path) -> None:
    # A CRLF in the shebang makes macOS report "bad interpreter: bash^M" -- and a
    # build run from a Windows checkout is exactly how one would get there.
    launcher = mb.write_bundle_shell(tmp_path / "QualSafe.app", "1.0.0")
    assert b"\r" not in launcher.read_bytes()


# -- finding what to sign ----------------------------------------------------


@pytest.mark.parametrize("content, expected", [
    (MACHO64, True),
    (FAT, True),
    (JAVA_CLASS, False),          # same 0xCAFEBABE magic, version >= 45
    (b"#!/bin/bash\necho hi\n", False),
    (b"\xcf\xfa", False),         # shorter than a header
    (b"", False),
])
def test_macho_detection(tmp_path, content, expected) -> None:
    path = tmp_path / "f"
    path.write_bytes(content)
    assert mb.is_macho(path) is expected


def test_a_missing_file_is_not_macho(tmp_path) -> None:
    assert mb.is_macho(tmp_path / "nope") is False


def test_find_macho_files_returns_only_binaries_in_a_stable_order(tmp_path) -> None:
    (tmp_path / "b" / "deep").mkdir(parents=True)
    (tmp_path / "b" / "deep" / "lib.dylib").write_bytes(MACHO64)
    (tmp_path / "a.so").write_bytes(FAT)
    (tmp_path / "script.sh").write_bytes(b"#!/bin/sh\n")
    (tmp_path / "Foo.class").write_bytes(JAVA_CLASS)
    found = mb.find_macho_files(tmp_path)
    assert [p.name for p in found] == ["a.so", "lib.dylib"]
    assert found == sorted(found)


def test_find_macho_files_skips_symlinks(tmp_path) -> None:
    (tmp_path / "real.dylib").write_bytes(MACHO64)
    try:
        (tmp_path / "alias.dylib").symlink_to(tmp_path / "real.dylib")
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not permitted on this machine")
    # Signing the target twice under two names is wasted work, and a framework's
    # Versions/Current link would otherwise list one binary twice.
    assert [p.name for p in mb.find_macho_files(tmp_path)] == ["real.dylib"]


# -- signing and packaging plans --------------------------------------------


def test_ad_hoc_signing_does_not_ask_for_a_certificate_only_option() -> None:
    (command,) = mb.signing_commands([Path("a"), Path("b")])
    assert command[:4] == ["codesign", "--force", "--sign", "-"]
    # Hardened runtime and a secure timestamp need a real identity.
    assert "--options" not in command and "--timestamp" not in command


def test_a_developer_id_signature_is_hardened_and_timestamped() -> None:
    ent = Path("ent.plist")
    (command,) = mb.signing_commands([Path("a")], "Developer ID Application: X (ABC)", ent)
    assert command[command.index("--options") + 1] == "runtime"
    assert "--timestamp" in command
    assert command[command.index("--entitlements") + 1] == "ent.plist"


def test_signing_covers_every_file_exactly_once_and_in_order() -> None:
    files = [Path(f"f{i:04d}") for i in range(450)]
    commands = mb.signing_commands(files, chunk=200)
    assert [len(c) - 4 for c in commands] == [200, 200, 50]
    flattened = [arg for c in commands for arg in c[4:]]
    assert flattened == [str(f) for f in files]


def test_the_bundle_is_signed_without_deep() -> None:
    # Apple documents --deep as unsuitable for *signing*: it applies one set of
    # options to every nested item. Nested code is signed individually first.
    for identity in (mb.AD_HOC, "Developer ID Application: X (ABC)"):
        command = mb.bundle_signing_command(Path("QualSafe.app"), identity)
        assert "--deep" not in command
        assert command[-1] == "QualSafe.app"


def test_notarisation_uses_a_keychain_profile_never_a_password() -> None:
    submit, staple = mb.notarize_commands(Path("q.dmg"), "qualsafe-notary")
    assert submit[submit.index("--keychain-profile") + 1] == "qualsafe-notary"
    assert "--wait" in submit
    assert not any(flag in submit for flag in ("--password", "--apple-id"))
    assert staple[:3] == ["xcrun", "stapler", "staple"]


def test_the_disk_image_is_built_from_a_staging_folder() -> None:
    command = mb.dmg_command(Path("stage"), "QualSafe Desktop 1.0", Path("out.dmg"))
    assert command[:2] == ["hdiutil", "create"]
    assert command[command.index("-srcfolder") + 1] == "stage"
    assert command[command.index("-volname") + 1] == "QualSafe Desktop 1.0"
    assert command[-1] == "out.dmg"


# -- the interpreter download ------------------------------------------------


def test_the_interpreter_asset_names_match_the_real_release() -> None:
    """These two literals were copied from the release's own file listing
    (astral-sh/python-build-standalone, tag 20260814), not constructed."""
    assert mb.cpython_asset_name("arm64", "3.12.14", "20260814") == (
        "cpython-3.12.14+20260814-aarch64-apple-darwin-install_only_stripped.tar.gz")
    assert mb.cpython_asset_name("x86_64", "3.12.14", "20260814") == (
        "cpython-3.12.14+20260814-x86_64-apple-darwin-install_only_stripped.tar.gz")


def test_an_unknown_architecture_is_refused() -> None:
    with pytest.raises(ValueError):
        mb.cpython_asset_name("ppc", "3.12.14", "20260814")


def test_mac_and_windows_builds_pin_the_same_interpreter() -> None:
    """One pin, in build_payload.py; the Mac build reads it rather than copying.
    If they diverged the two platforms would ship different Pythons."""
    windows = _load("build_payload_for_mac_test", "build_payload.py")
    name = mb.cpython_asset_name("arm64", windows.CPYTHON_VERSION, windows.CPYTHON_RELEASE)
    assert windows.CPYTHON_VERSION in name and windows.CPYTHON_RELEASE in name
    # 3.12 is the dependency pins' ceiling; a Mac must not drift above it.
    assert windows.CPYTHON_VERSION.startswith("3.12.")


def test_a_checksum_is_found_by_file_name() -> None:
    listing = ("aaa111  cpython-a.tar.gz\n"
               "BBB222 *cpython-b.tar.gz\n"      # '*' marks binary mode
               "ccc333  cpython-c.tar.gz\n")
    assert mb.sha256_for(listing, "cpython-a.tar.gz") == "aaa111"
    assert mb.sha256_for(listing, "cpython-b.tar.gz") == "bbb222"
    assert mb.sha256_for(listing, "missing.tar.gz") is None


def test_the_intel_build_pins_the_last_torch_that_exists_for_it() -> None:
    text = (PACKAGING / "constraints-macos-x86_64.txt").read_text("utf-8")
    lines = [ln.strip() for ln in text.splitlines()
             if ln.strip() and not ln.startswith("#")]
    assert "torch==2.2.2" in lines
    # numpy 2 would break torch 2.2, which was built against numpy 1.
    assert any(ln.startswith("numpy") and "<2" in ln for ln in lines)


# -- relocation and the prune safety net ------------------------------------


def test_scripts_with_a_build_machine_shebang_are_found_and_real_binaries_are_not(tmp_path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "pip").write_bytes(b"#!/Users/runner/work/x/python3.12\nimport sys\n")
    (bin_dir / "pytest").write_bytes(b"#!/Users/builder/build/python\n")
    (bin_dir / "portable").write_bytes(b"#!/usr/bin/env python3\n")   # relocatable
    (bin_dir / "python3.12").write_bytes(MACHO64)                     # the interpreter
    (bin_dir / "notes.txt").write_bytes(b"not a script\n")
    assert [p.name for p in mb.scripts_with_absolute_shebang(bin_dir)] == ["pip", "pytest"]


def test_a_missing_bin_directory_is_not_an_error(tmp_path) -> None:
    assert mb.scripts_with_absolute_shebang(tmp_path / "absent") == []


OTOOL_SAMPLE = """\
/x/PySide6/Qt/plugins/platforms/libqcocoa.dylib:
\t@rpath/libqcocoa.dylib (compatibility version 0.0.0, current version 0.0.0)
\t@rpath/QtCore.framework/Versions/A/QtCore (compatibility version 6.0.0, current version 6.11.0)
\t@rpath/QtGui.framework/Versions/A/QtGui (compatibility version 6.0.0, current version 6.11.0)
\t@rpath/QtQuick3D.framework/Versions/A/QtQuick3D (compatibility version 6.0.0)
\t/System/Library/Frameworks/AppKit.framework/Versions/C/AppKit (compatibility version 45.0.0)
"""


def test_otool_output_yields_only_the_qt_frameworks_it_needs() -> None:
    assert mb.qt_frameworks_referenced(OTOOL_SAMPLE) == {"QtCore", "QtGui", "QtQuick3D"}


def test_a_pruned_framework_that_something_still_links_is_reported() -> None:
    needed = mb.qt_frameworks_referenced(OTOOL_SAMPLE)
    assert mb.missing_frameworks(needed, ["QtCore", "QtGui", "QtWidgets"]) == ["QtQuick3D"]
    assert mb.missing_frameworks(needed, ["QtCore", "QtGui", "QtQuick3D"]) == []


def test_no_prune_pattern_can_match_a_module_the_app_imports() -> None:
    """The app imports exactly QtCore, QtGui and QtWidgets. The prune globs are
    the one place a typo could delete one of them, so check them against those
    names directly, in every form they take on disk."""
    protected = []
    for module in ("QtCore", "QtGui", "QtWidgets"):
        protected += [f"{module}.abi3.so", f"{module}.framework", module]
    patterns = (list(mb.PYSIDE_PRUNE_GLOBS) + list(mb.PYSIDE_PRUNE_FRAMEWORK_GLOBS)
                + list(mb.PYSIDE_PRUNE_PATHS))
    for pattern in patterns:
        for name in protected:
            assert not fnmatch.fnmatch(name, pattern), f"{pattern!r} would remove {name}"


def test_the_prune_keeps_the_plugins_qt_cannot_start_without() -> None:
    # Windows' equivalent note: removing the platform plugin renders nothing.
    for name in ("Qt/plugins", "Qt/plugins/platforms", "Qt/lib",
                 "Qt/plugins/imageformats", "Qt/plugins/platforminputcontexts"):
        assert name not in mb.PYSIDE_PRUNE_PATHS


def test_the_prune_removes_qmltooling_alongside_qml() -> None:
    """The first real Mac build failed check_qt_links here: Qt/qml (the
    importable QML modules) was pruned, but Qt/plugins/qmltooling (QML
    debugger/profiler support -- a different directory) was not, and it still
    links QtQml/QtQuick. Both must go together for a QML-free app."""
    assert "Qt/plugins/qmltooling" in mb.PYSIDE_PRUNE_PATHS
    assert "Qt/qml" in mb.PYSIDE_PRUNE_PATHS


#: Every binary the second real build's check_qt_links reported (CI runs
#: 35920780382 and 35940165488, arm64 and x86_64 alike), relative to PySide6/.
#: The fix prunes each of them; un-pruning the frameworks they link would ship
#: the QML stack to a QtWidgets app, and QtPdf/QtVirtualKeyboard/QtWebEngine are
#: not in PySide6-Essentials at all, so there was nothing to un-prune.
CI_DANGLING_BINARIES = (
    "Qt/libexec/qmlcachegen",
    "Qt/libexec/qmlimportscanner",
    "Qt/plugins/designer/libqquickwidget.dylib",
    "Qt/plugins/designer/libqwebengineview.dylib",
    "Qt/plugins/imageformats/libqpdf.dylib",
    "Qt/plugins/platforminputcontexts/libqtvirtualkeyboardplugin.dylib",
    "Qt/plugins/qmllint/libqdslintplugin.dylib",
    "Qt/plugins/qmllint/libquicklintplugin.dylib",
    "Qt/plugins/vectorimageformats/libqlottievectorimage.dylib",
    "libpyside6qml.abi3.6.11.dylib",
    "svgtoqml",
)

#: What the app needs and a neighbour of each pruned file must not take with it.
KEPT_BINARIES = (
    "Qt/lib/QtCore.framework/Versions/A/QtCore",
    "Qt/lib/QtGui.framework/Versions/A/QtGui",
    "Qt/lib/QtWidgets.framework/Versions/A/QtWidgets",
    "Qt/plugins/platforms/libqcocoa.dylib",
    "Qt/plugins/imageformats/libqjpeg.dylib",
    "Qt/plugins/imageformats/libqsvg.dylib",
    "Qt/plugins/styles/libqmacstyle.dylib",
    "QtCore.abi3.so", "QtGui.abi3.so", "QtWidgets.abi3.so",
    "libpyside6.abi3.6.11.dylib",
)


def test_the_prune_removes_every_binary_the_link_check_found_dangling(tmp_path) -> None:
    """Runs the real `build_mac.prune` over a fake wheel laid out like the one CI
    installs. The link check itself needs otool, so it cannot run here; this
    pins the input it failed on instead."""
    build_mac = _load("build_mac_prune", "build_mac.py")
    resources = tmp_path / "Resources"
    pyside = build_mac.site_packages(resources) / "PySide6"
    for relative in CI_DANGLING_BINARIES + KEPT_BINARIES:
        (pyside / relative).parent.mkdir(parents=True, exist_ok=True)
        (pyside / relative).write_bytes(MACHO64)
    (resources / "python" / "bin").mkdir(parents=True)

    build_mac.prune(resources)

    survivors = [r for r in CI_DANGLING_BINARIES if (pyside / r).exists()]
    assert survivors == [], f"still present, still linking pruned frameworks: {survivors}"
    lost = [r for r in KEPT_BINARIES if not (pyside / r).exists()]
    assert lost == [], f"pruned something the app loads: {lost}"


def test_the_app_still_imports_only_the_qt_modules_the_prune_assumes() -> None:
    """The prune list asserts these three are all the app uses. If a view starts
    importing another Qt module, the assertion is stale -- so check it."""
    import re

    allowed = {"QtCore", "QtGui", "QtWidgets"}
    pruned_prefixes = ("QtQml", "QtQuick", "QtDesigner", "QtTest")
    used = set()
    for path in (PROJECT_ROOT / "qualsafe_qt").rglob("*.py"):
        for match in re.finditer(r"^\s*(?:from|import)\s+PySide6\.(Qt\w+)",
                                 path.read_text("utf-8"), re.MULTILINE):
            used.add(match.group(1))
    assert not [m for m in used if m.startswith(pruned_prefixes)], used
    assert used <= allowed | {"QtSvg", "QtSvgWidgets", "QtPrintSupport", "QtNetwork"}, used


# -- the build script itself --------------------------------------------------


def test_the_build_script_refuses_to_run_off_a_mac() -> None:
    if sys.platform == "darwin":
        pytest.skip("this is the off-Mac behaviour")
    build_mac = _load("build_mac_under_test", "build_mac.py")
    with pytest.raises(SystemExit) as raised:
        build_mac.require_mac_host("arm64")
    assert "macOS" in str(raised.value)


def test_the_build_script_reads_what_ships_from_the_windows_build() -> None:
    build_mac = _load("build_mac_shared", "build_mac.py")
    assert build_mac.bp.APP_DIRS and "qualsafe_qt" in build_mac.bp.APP_DIRS
    # The Mac build adds an icon to Resources and nothing else.
    assert mb.ICON_FILE not in build_mac.bp.APP_FILES


def test_the_windows_build_script_was_left_untouched() -> None:
    """test_qt_packaging.py parses build_payload.py as source. The Mac build
    imports it; it must not need to change it. This pins the seam."""
    source = (PACKAGING / "build_payload.py").read_text("utf-8")
    assert "darwin" not in source and "macos" not in source.lower()


# -- keyboard wording ---------------------------------------------------------


def test_shortcut_wording_is_rewritten_on_a_mac_and_only_there() -> None:
    from qualsafe_qt.keys import native

    text = "Undoable with Ctrl+Z. Ctrl+E grows the selection."
    assert native(text, platform="darwin") == "Undoable with ⌘Z. ⌘E grows the selection."
    for other in ("win32", "linux"):
        assert native(text, platform=other) == text


def test_redo_is_not_rewritten_to_a_different_command() -> None:
    """Command+Y is 'Show History' in most Mac apps. Redo there is Shift+Command+Z,
    which is what `StandardKey.Redo` binds; the wording must match the binding."""
    from qualsafe_qt.keys import native

    assert native("Ctrl+Y redo", platform="darwin") == "⇧⌘Z redo"
    assert "⌘Y" not in native("Ctrl+Y", platform="darwin")


@requires_qt
def test_the_menu_tells_macos_which_items_are_quit_and_about() -> None:
    """macOS moves these into the application menu only when told what they are.
    Matching on the text 'Exit' is a heuristic that a translation would break."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QAction
    from PySide6.QtWidgets import QApplication

    import qualsafe_qt.windows.main_window as module

    app = QApplication.instance() or QApplication([])
    module.ORGANIZATION = "QualSafeTest"
    window = module.MainWindow()
    try:
        roles = {}
        for menu_action in window.menuBar().actions():
            menu = menu_action.menu()
            for action in (menu.actions() if menu else []):
                roles[action.text().replace("&", "")] = action.menuRole()
        assert roles["Exit"] == QAction.MenuRole.QuitRole
        assert roles["About"] == QAction.MenuRole.AboutRole
    finally:
        window.close()
        app.processEvents()


def test_every_pruned_qt_framework_family_also_has_its_python_binding_pruned():
    """A binding left behind links a framework that is gone, and the link check fails the build (the third
    real build, PySide6 6.12: QtLabsStyleKit.abi3.so needs QtLabsStyleKit)."""
    from fnmatch import fnmatch

    import mac_bundle as mb

    families = [g.split(".framework")[0].rstrip("*") for g in mb.PYSIDE_PRUNE_FRAMEWORK_GLOBS]   # QtQml, QtQuick...
    assert {"QtQml", "QtQuick", "QtLabs", "QtLottie", "QtDesigner", "QtTest"} <= set(families)
    for family in families:
        sample = f"{family}StyleKit.abi3.so" if family == "QtLabs" else f"{family}Thing.abi3.so"
        assert any(fnmatch(sample, glob) for glob in mb.PYSIDE_PRUNE_GLOBS), family


def test_a_busy_disk_image_step_is_tried_again_and_a_real_failure_still_fails(monkeypatch):
    """hdiutil create reported 'Resource busy' once on a CI runner; the build now pauses and retries."""
    import subprocess

    spec = importlib.util.spec_from_file_location("build_mac_retry", PACKAGING / "build_mac.py")
    # build_mac checks the host at call time, not import time, so it loads anywhere.
    build_mac = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(PACKAGING))
    try:
        spec.loader.exec_module(build_mac)
    finally:
        sys.path.remove(str(PACKAGING))

    calls = []

    def flaky(command, check=True, **kwargs):
        calls.append(command)
        if len(calls) < 3:
            raise subprocess.CalledProcessError(1, command)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(build_mac.subprocess, "run", flaky)
    monkeypatch.setattr("time.sleep", lambda _s: None)
    build_mac._run_retrying(["hdiutil", "create"], attempts=4, delay=0)
    assert len(calls) == 3

    calls.clear()
    monkeypatch.setattr(build_mac.subprocess, "run",
                        lambda c, check=True, **k: (calls.append(c), (_ for _ in ()).throw(subprocess.CalledProcessError(1, c)))[1])
    with pytest.raises(subprocess.CalledProcessError):
        build_mac._run_retrying(["hdiutil", "create"], attempts=3, delay=0)
    assert len(calls) == 3
