"""
The host-independent half of the macOS build.

Everything in this module is a pure function of its arguments: it builds a
`plist`, a launcher script, a list of `codesign` command lines, a parse of
`otool` output. None of it runs a macOS tool, so all of it can be tested on the
Windows machine the desktop app is developed on. `packaging/build_mac.py` is the
half that can only run on a Mac -- it executes these plans.

That split is deliberate rather than tidy. The Mac build was written on a
machine that cannot run a Mach-O binary, let alone `codesign`. Anything left
inside the orchestrator is unverified until a Mac runs it, so the logic that *can*
be checked lives here, where `tests/test_qt_mac_packaging.py` checks it.

Design follows the Windows installer (`packaging/build_payload.py`), and for the
same reasons: a relocatable CPython plus ordinary `site-packages` inside the
bundle, not a frozen executable. PySide6 is LGPL, which requires that a user be
able to replace the Qt libraries; and a frozen binary could never gain the
analysis engine after install. Both arguments are platform-independent.
"""

from __future__ import annotations

import os
import plistlib
import re
import stat
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set

# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------
#: `QualSafe.app`. Short on purpose: it is what the Dock and Finder show.
BUNDLE_NAME = "QualSafe"
#: The window title and About box say "QualSafe Desktop" on both platforms.
DISPLAY_NAME = "QualSafe Desktop"
#: Reverse-DNS identity. macOS keys privacy grants, preferences and Gatekeeper
#: history on this string, so changing it after release makes the system treat
#: the next version as a different application. Chosen once; see INSTALL_MAC.md.
BUNDLE_ID = "org.qualsafe.desktop"
#: The file in Contents/MacOS that the system executes.
EXECUTABLE = "QualSafe"
ICON_FILE = "qualsafe.icns"
#: A symlink to the bundled interpreter, named for the app. See `launcher_script`.
INTERPRETER_LINK = "QualSafe"

#: PySide6 6.11 ships one macOS wheel, tagged macosx_13_0_universal2. Older Macs
#: cannot load it, so the bundle refuses to launch on them with a system message
#: instead of crashing in dlopen. Verified against PyPI, not assumed.
MIN_MACOS = "13.0"

ARCHITECTURES = ("arm64", "x86_64")

#: python-build-standalone's names for the same two architectures.
CPYTHON_TRIPLES: Dict[str, str] = {
    "arm64": "aarch64-apple-darwin",
    "x86_64": "x86_64-apple-darwin",
}


# ---------------------------------------------------------------------------
# Info.plist
# ---------------------------------------------------------------------------
def info_plist(version: str, min_macos: str = MIN_MACOS) -> bytes:
    """The bundle's `Info.plist`, as the bytes to write."""
    payload = {
        "CFBundleName": BUNDLE_NAME,
        "CFBundleDisplayName": DISPLAY_NAME,
        "CFBundleIdentifier": BUNDLE_ID,
        "CFBundleExecutable": EXECUTABLE,
        "CFBundleIconFile": ICON_FILE,
        "CFBundlePackageType": "APPL",
        "CFBundleSignature": "????",
        "CFBundleInfoDictionaryVersion": "6.0",
        "CFBundleShortVersionString": version,
        "CFBundleVersion": version,
        "LSMinimumSystemVersion": min_macos,
        "LSApplicationCategoryType": "public.app-category.education",
        "NSHighResolutionCapable": True,
        "NSPrincipalClass": "NSApplication",
        "NSHumanReadableCopyright": "MIT License. Runs entirely on this computer.",
        # A .qnw project is a file the app writes and reads, but the app is not
        # registered as an editor of it here: a document type declaration would
        # promise double-click-to-open, which needs QFileOpenEvent handling the
        # app does not have yet. Declared when it works, not before.
    }
    return plistlib.dumps(payload, fmt=plistlib.FMT_XML, sort_keys=True)


def entitlements_plist() -> bytes:
    """Entitlements for a hardened-runtime signature (Developer ID / notarised).

    The two exceptions are the ones every bundled-CPython app needs, and each is
    here for a stated reason -- hardened runtime denies both by default:

    * `allow-unsigned-executable-memory` -- ctypes/libffi closures and several
      numerical libraries allocate writable+executable pages.
    * `disable-library-validation` -- the runtime otherwise refuses to load a
      dylib not signed by the same Team ID. Every wheel in site-packages (numpy,
      scipy, torch, Qt) is signed by someone else, or ad-hoc.

    No sandbox entitlement: the app reads and writes files the user chooses
    anywhere on disk, and a sandbox would need a security-scoped bookmark for
    every one.
    """
    return plistlib.dumps({
        "com.apple.security.cs.allow-unsigned-executable-memory": True,
        "com.apple.security.cs.disable-library-validation": True,
    }, fmt=plistlib.FMT_XML, sort_keys=True)


# ---------------------------------------------------------------------------
# The launcher
# ---------------------------------------------------------------------------
def launcher_script() -> str:
    """The `Contents/MacOS/QualSafe` executable: a small bash script.

    Why bash and not `sh`: `/bin/bash` exists on every Mac, while `/bin/sh` has
    changed behaviour between releases.

    Each line is here for a reason:

    * **Paths are resolved from the script's own location**, so the .app can be
      dragged anywhere, including onto a different volume.
    * **`cd` into Resources** because `python -m qualsafe_qt` finds the app on
      `sys.path[0]`, exactly as the Windows shortcut's WorkingDir does.
    * **`PYTHONDONTWRITEBYTECODE=1`.** A signed bundle is sealed; Python writing
      `__pycache__` into it afterwards changes the sealed contents, which
      `codesign --verify` then reports as a modified app. Bytecode is compiled
      at build time instead (see `build_mac.precompile`), so nothing is lost --
      and a translocated, read-only copy (Gatekeeper runs a just-downloaded app
      from a read-only mount) starts as fast as an installed one.
    * **`PYTHONNOUSERSITE=1`.** A researcher's own `~/Library/Python` packages
      must not shadow the ones the app was tested with.
    * **It runs `python/bin/QualSafe`, a symlink to the interpreter**, not
      `python3`. macOS titles the application menu from the process name, which
      it takes from argv[0]'s file name; run as `python3` the menu bar would read
      "python3". The obvious fix, `exec -a QualSafe python3`, hands Python an
      argv[0] with no directory in it, and Python finds its standard library by
      locating its own executable -- a bare name sends it searching PATH, which is
      not something a launcher should bet the app on. A symlink gives argv[0] a
      real path *and* the right name, and `sys.executable` stays a working
      interpreter (the model downloader and pip both re-run it as a subprocess).
    """
    return (
        "#!/bin/bash\n"
        "# QualSafe Desktop launcher. Generated by packaging/mac_bundle.py.\n"
        'HERE="$(cd "$(dirname "$0")" && pwd)"\n'
        'RES="$HERE/../Resources"\n'
        'cd "$RES" || exit 1\n'
        "export PYTHONDONTWRITEBYTECODE=1\n"
        "export PYTHONNOUSERSITE=1\n"
        f'exec "$RES/python/bin/{INTERPRETER_LINK}" -m qualsafe_qt "$@"\n'
    )


def link_interpreter(python_dir: Path) -> Path:
    """Create `python/bin/QualSafe` -> `python3` (relative, so the app can move).

    Called by the build once the interpreter has been unpacked. A relative link is
    essential: an absolute one would name the build machine's directory.
    """
    link = python_dir / "bin" / INTERPRETER_LINK
    if link.is_symlink() or link.exists():
        link.unlink()
    link.symlink_to("python3")
    return link


# ---------------------------------------------------------------------------
# Writing the bundle shell
# ---------------------------------------------------------------------------
def write_bundle_shell(app: Path, version: str, icon: Optional[Path] = None) -> Path:
    """Write everything in the .app that is not the payload.

    The payload (interpreter, packages, application source) is built directly
    into `Contents/Resources` rather than built elsewhere and copied in: copying
    half a gigabyte, thousands of symlinks included, is time spent and a chance
    to lose one. Returns the launcher path.
    """
    contents = app / "Contents"
    (contents / "MacOS").mkdir(parents=True, exist_ok=True)
    (contents / "Resources").mkdir(parents=True, exist_ok=True)

    (contents / "Info.plist").write_bytes(info_plist(version))
    (contents / "PkgInfo").write_bytes(b"APPL????")

    launcher = contents / "MacOS" / EXECUTABLE
    launcher.write_text(launcher_script(), encoding="utf-8", newline="\n")
    launcher.chmod(launcher.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    if icon is not None and icon.is_file():
        (contents / "Resources" / ICON_FILE).write_bytes(icon.read_bytes())
    return launcher


# ---------------------------------------------------------------------------
# Finding what needs signing
# ---------------------------------------------------------------------------
_THIN = {b"\xfe\xed\xfa\xce", b"\xfe\xed\xfa\xcf", b"\xce\xfa\xed\xfe", b"\xcf\xfa\xed\xfe"}
_FAT = {b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca"}


def is_macho(path: Path) -> bool:
    """True if the file starts like a Mach-O binary (thin or universal).

    A universal ("fat") binary and a Java class file share the magic number
    0xCAFEBABE. They differ in the next four bytes: a fat header holds a small
    architecture count, a class file holds a version number of 45 or more. Without
    that check a stray .class file inside a dependency would be handed to
    `codesign` and fail the whole build.
    """
    try:
        with open(path, "rb") as handle:
            head = handle.read(8)
    except OSError:
        return False
    if len(head) < 8:
        return False
    magic = head[:4]
    if magic in _THIN:
        return True
    if magic in _FAT:
        count = int.from_bytes(head[4:8], "big" if magic == b"\xca\xfe\xba\xbe" else "little")
        return 1 <= count <= 30
    return False


def find_macho_files(root: Path) -> List[Path]:
    """Every Mach-O file under `root`, symlinks not followed, in a stable order.

    Symlinks are skipped, not resolved: signing a link's target twice is wasted
    work, and a framework's `Versions/Current` link would otherwise put the same
    binary in the list under two names.
    """
    found: List[Path] = []
    for directory, _dirs, files in os.walk(root, followlinks=False):
        for name in files:
            path = Path(directory) / name
            if path.is_symlink():
                continue
            if is_macho(path):
                found.append(path)
    return sorted(found)


# ---------------------------------------------------------------------------
# Signing and packaging command plans
# ---------------------------------------------------------------------------
AD_HOC = "-"


def signing_commands(
    files: Sequence[Path],
    identity: str = AD_HOC,
    entitlements: Optional[Path] = None,
    chunk: int = 200,
) -> List[List[str]]:
    """`codesign` invocations that sign each file individually.

    Every Mach-O is signed on its own *before* the bundle is, because the
    notarisation service inspects every binary in the archive and a bundle
    signature does not vouch for executables sitting in Resources.

    Ad-hoc (`-`) is not "unsigned": Apple Silicon refuses to run code with no
    signature at all, so even the free build needs one. It carries no identity
    and Gatekeeper will still prompt on first launch; only a Developer ID
    signature plus notarisation removes that.

    Hardened runtime and a secure timestamp are added only for a real identity --
    they are what notarisation requires, and they make no sense ad-hoc.
    """
    base = ["codesign", "--force", "--sign", identity]
    if identity != AD_HOC:
        base += ["--options", "runtime", "--timestamp"]
        if entitlements is not None:
            base += ["--entitlements", str(entitlements)]
    commands = []
    items = [str(f) for f in files]
    for start in range(0, len(items), max(1, chunk)):
        commands.append(base + items[start:start + chunk])
    return commands


def bundle_signing_command(
    app: Path, identity: str = AD_HOC, entitlements: Optional[Path] = None,
) -> List[str]:
    """Sign the .app itself, last. Never `--deep`: Apple documents `--deep` as
    unsuitable for signing (it applies one set of options to every nested item),
    and the nested code has already been signed individually."""
    command = ["codesign", "--force", "--sign", identity]
    if identity != AD_HOC:
        command += ["--options", "runtime", "--timestamp"]
        if entitlements is not None:
            command += ["--entitlements", str(entitlements)]
    return command + [str(app)]


def dmg_command(staging: Path, volume_name: str, output: Path) -> List[str]:
    """`hdiutil` command that turns a staging folder into a compressed image."""
    return [
        "hdiutil", "create",
        "-volname", volume_name,
        "-srcfolder", str(staging),
        "-ov", "-format", "UDZO", "-imagekey", "zlib-level=9",
        str(output),
    ]


def dmg_signing_command(dmg: Path, identity: str) -> List[str]:
    """Sign the disk image itself (needed before notarisation can staple it)."""
    return ["codesign", "--force", "--sign", identity, "--timestamp", str(dmg)]


def notarize_commands(dmg: Path, keychain_profile: str) -> List[List[str]]:
    """Submit for notarisation and wait, then staple the ticket to the image.

    Uses a stored `notarytool` keychain profile so no credential ever appears on
    a command line or in a CI log.
    """
    return [
        ["xcrun", "notarytool", "submit", str(dmg),
         "--keychain-profile", keychain_profile, "--wait"],
        ["xcrun", "stapler", "staple", str(dmg)],
    ]


# ---------------------------------------------------------------------------
# Downloads
# ---------------------------------------------------------------------------
def cpython_asset_name(arch: str, version: str, release: str) -> str:
    """The python-build-standalone file name for a macOS architecture."""
    if arch not in CPYTHON_TRIPLES:
        raise ValueError(f"unknown architecture {arch!r}; expected one of {ARCHITECTURES}")
    return (f"cpython-{version}+{release}-{CPYTHON_TRIPLES[arch]}"
            "-install_only_stripped.tar.gz")


def sha256_for(sums_text: str, filename: str) -> Optional[str]:
    """Look a file's digest up in a `SHA256SUMS` listing (`<hex>  <name>`)."""
    for line in sums_text.splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2 and parts[1].strip().lstrip("*") == filename:
            return parts[0].lower()
    return None


# ---------------------------------------------------------------------------
# Relocation and verification helpers
# ---------------------------------------------------------------------------
def scripts_with_absolute_shebang(bin_dir: Path) -> List[Path]:
    """Console scripts pip wrote with the *build machine's* path in `#!`.

    `pip install` writes `pip`, `pytest` and friends as scripts whose first line
    is an absolute path to the interpreter that installed them. Inside a bundle
    that is moved to a user's Applications folder the path is dead, so each of
    those scripts fails with "bad interpreter". They are never used by the app
    (`python3 -m pip` is the documented form) and a broken entry point that
    looks installed is worse than an absent one, so the build removes them.

    Real binaries (`python3`, `python3.12`) and links are left alone.
    """
    found: List[Path] = []
    if not bin_dir.is_dir():
        return found
    for path in sorted(bin_dir.iterdir()):
        if path.is_symlink() or not path.is_file() or is_macho(path):
            continue
        try:
            first = path.read_bytes()[:256].split(b"\n", 1)[0]
        except OSError:
            continue
        if first.startswith(b"#!/") and not first.startswith(b"#!/usr/bin/env"):
            found.append(path)
    return found


_FRAMEWORK_REF = re.compile(r"@rpath/(Qt\w+)\.framework/")


def qt_frameworks_referenced(otool_output: str) -> Set[str]:
    """Names of Qt frameworks a binary links, from `otool -L` output."""
    return set(_FRAMEWORK_REF.findall(otool_output))


def missing_frameworks(referenced: Iterable[str], present: Iterable[str]) -> List[str]:
    """Referenced frameworks that are not on disk. Sorted for stable messages."""
    have = set(present)
    return sorted(set(referenced) - have)


# ---------------------------------------------------------------------------
# What to prune from the macOS PySide6 wheel
# ---------------------------------------------------------------------------
# Derived from the real `pyside6_essentials-6.11.x-macosx_13_0_universal2` wheel
# (342 MB unpacked), not copied from the Windows list: the layout differs.
# Windows keeps DLLs beside the package; macOS keeps `.framework` bundles under
# `Qt/lib` and the QML tree under `Qt/qml`. The app imports QtCore, QtGui and
# QtWidgets and nothing else -- the same premise as the Windows prune.
#
# Every entry is removed only if present, and `build_mac.check_qt_links` then
# proves nothing kept still links something removed. That check is the
# safety net: this list is an assertion, and that is what tests it.
PYSIDE_PRUNE_PATHS = (
    "Qt/qml",              # the whole QML/Quick tree (37 MB); pure QtWidgets app
    # QML's debugger/profiler support plugins (libqmldbg_*.dylib) -- a different
    # directory from Qt/qml above (that's the importable QML *modules*; this is
    # QML *debugging* support), still linking QtQml/QtQuick after those
    # frameworks are pruned below. Missing this the first time is exactly what
    # build_mac.py::check_qt_links exists to catch: found on the first real
    # build, on a real Mac, in CI -- never reproducible on the Windows dev
    # machine, since nothing there can run otool.
    "Qt/plugins/qmltooling",
    # The second real build (CI runs 35920780382, 35940165488) found eleven more
    # binaries still linking pruned frameworks. Each is removed here, never
    # un-pruned, because nothing in a QtWidgets app loads any of them:
    "Qt/libexec/qmlcachegen", "Qt/libexec/qmlimportscanner",  # QML build tools
    "Qt/plugins/designer",       # Designer custom-widget plugins; Designer.app is pruned
    "Qt/plugins/qmllint",        # qmllint plugins; qmllint is pruned
    "Qt/plugins/vectorimageformats",   # Lottie -> Qt Quick VectorImage generator
    # Single files in directories the app does need. Both link frameworks that are
    # not in PySide6-Essentials at all (QtPdf, QtVirtualKeyboard), so they could
    # never load even unpruned. The app decodes PNG only (the chart preview) and
    # uses the system input method, not Qt's on-screen keyboard.
    "Qt/plugins/imageformats/libqpdf.dylib",
    "Qt/plugins/platforminputcontexts/libqtvirtualkeyboardplugin.dylib",
    "Qt/metatypes",        # build-time type registration data
    "Assistant.app", "Designer.app", "Linguist.app",   # Qt's GUI tools
    "typesystems", "include", "scripts", "glue",       # shiboken build material
)
PYSIDE_PRUNE_GLOBS = (
    "qmlls", "qmlformat", "qmllint", "qmlimportscanner", "qmlcachegen",
    "svgtoqml", "lupdate", "lrelease", "pyside6-*",
    # Python bindings for the Qt modules the app never imports.
    "QtQml*.abi3.so", "QtQuick*.abi3.so", "QtDesigner*.abi3.so", "QtTest*.abi3.so",
    # Found by the third real build (PySide6 6.12 added QtLabsStyleKit): a binding whose framework is
    # pruned above has to go too. Every pruned framework family now has its binding here.
    "QtLabs*.abi3.so", "QtLottie*.abi3.so",
    # PySide's QML support library; only the pruned QtQml binding loads it. The
    # version is in the file name, hence a glob.
    "libpyside6qml.abi3.*.dylib",
)
PYSIDE_PRUNE_FRAMEWORK_GLOBS = (
    "QtQml*.framework", "QtQuick*.framework", "QtLabs*.framework",
    "QtLottie*.framework", "QtDesigner*.framework", "QtTest.framework",
)
