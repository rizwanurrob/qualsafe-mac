#!/usr/bin/env python
"""
Build QualSafe Desktop for macOS: a `.app` bundle and a `.dmg` to distribute it.

    python packaging/build_mac.py                     # host architecture, lite
    python packaging/build_mac.py --arch x86_64       # must match the host
    python packaging/build_mac.py --engine            # bundle torch too (large)
    python packaging/build_mac.py --no-dmg            # stop at the .app

**This only runs on a Mac.** It executes a macOS Python, `codesign`, `otool` and
`hdiutil`, none of which exist elsewhere, and Python wheels for macOS cannot be
installed from another operating system in a way that could then be tested. The
plans it executes -- the plist, the launcher, the signing commands -- are built in
`packaging/mac_bundle.py`, which is pure and is tested on any machine. Build one
architecture per machine, natively: `.github/workflows/mac.yml` does that.

Output:  build/mac-<arch>/QualSafe.app  and
         build/QualSafe-Desktop-<version>-macOS-<arch>.dmg

The design is the Windows installer's, deliberately (`build_payload.py`): a
relocatable CPython from python-build-standalone with ordinary site-packages,
not a frozen executable. See that file's docstring for why -- the LGPL argument
for PySide6 and the two-tier engine install both hold on macOS unchanged.

Signing is ad-hoc unless QUALSAFE_SIGN_IDENTITY names a Developer ID. Ad-hoc
builds run, but Gatekeeper asks the user to approve them once (INSTALL_MAC.md).
Notarisation runs only when QUALSAFE_NOTARY_PROFILE is also set.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.request
from pathlib import Path
from typing import List, Optional

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent

# The Windows build script is the single source of truth for what ships and
# which interpreter is pinned. Loading it by path (it is not a package) keeps
# one definition of APP_DIRS, DEPENDENCY_PRUNE and the verification script, so
# the two platforms cannot quietly ship different things. It is imported, never
# edited: tests/test_qt_packaging.py reads its source and must keep passing.
sys.path.insert(0, str(HERE))
import mac_bundle as mb  # noqa: E402


def _load_build_payload():
    spec = importlib.util.spec_from_file_location("build_payload", HERE / "build_payload.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bp = _load_build_payload()

BUILD_DIR = PROJECT_ROOT / "build"
DOWNLOAD_DIR = BUILD_DIR / "download"
PYTHON_MINOR = "3.12"          # the dependency pins' ceiling; see build_payload.py
ICON = PROJECT_ROOT / "qualsafe_qt" / "resources" / "qualsafe.icns"
INTEL_CONSTRAINTS = HERE / "constraints-macos-x86_64.txt"
RELEASE_BASE = "https://github.com/astral-sh/python-build-standalone/releases/download"


def _log(message: str) -> None:
    print(f"[mac] {message}", flush=True)


def _run(command: List[str], **kwargs) -> subprocess.CompletedProcess:
    _log(" ".join(str(c) for c in command[:8]) + (" ..." if len(command) > 8 else ""))
    return subprocess.run(command, check=True, **kwargs)


def _run_retrying(command: List[str], attempts: int = 4, delay: float = 10.0, **kwargs) -> subprocess.CompletedProcess:
    """`_run`, trying again after a pause. For `hdiutil create`, which fails now and then on a busy Mac with
    "Resource busy" (the volume or the staging folder is briefly held by Spotlight or a disk-image helper):
    it failed once on a GitHub runner whose earlier run, on the same commit, had passed."""
    import time

    for attempt in range(1, attempts + 1):
        try:
            return _run(command, **kwargs)
        except subprocess.CalledProcessError:
            if attempt == attempts:
                raise
            _log(f"that failed (attempt {attempt} of {attempts}); trying again in {delay:.0f} s")
            time.sleep(delay)


# ---------------------------------------------------------------------------
# Host checks
# ---------------------------------------------------------------------------
def host_architecture() -> str:
    machine = platform.machine().lower()
    return "arm64" if machine in ("arm64", "aarch64") else "x86_64"


def require_mac_host(arch: str) -> None:
    if sys.platform != "darwin":
        raise SystemExit(
            "This build only runs on macOS: it needs a macOS Python, codesign, "
            "otool and hdiutil.\nRun it on a Mac, or use the GitHub Actions "
            "workflow (.github/workflows/mac.yml), which builds each architecture "
            "on its own runner.")
    host = host_architecture()
    if arch != host:
        raise SystemExit(
            f"Building {arch} on a {host} Mac is not supported here.\n"
            f"pip would install {host} wheels into an {arch} bundle, or need "
            "Rosetta to run the target interpreter. Build each architecture on "
            "its own machine (the CI workflow does).")


# ---------------------------------------------------------------------------
# The interpreter
# ---------------------------------------------------------------------------
def fetch_cpython(arch: str) -> Path:
    """Download the pinned interpreter and verify it against the release's own
    SHA256SUMS. The Windows script only logs the hash; a build that ships an
    interpreter should check it, and the checksums are published alongside."""
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    name = mb.cpython_asset_name(arch, bp.CPYTHON_VERSION, bp.CPYTHON_RELEASE)
    archive = DOWNLOAD_DIR / name

    sums_url = f"{RELEASE_BASE}/{bp.CPYTHON_RELEASE}/SHA256SUMS"
    _log(f"fetching checksums {sums_url}")
    with urllib.request.urlopen(sums_url) as response:
        sums = response.read().decode("utf-8")
    expected = mb.sha256_for(sums, name)
    if not expected:
        raise SystemExit(f"{name} is not listed in the release's SHA256SUMS; "
                         "refusing to use an interpreter that cannot be verified.")

    if not archive.is_file():
        url = f"{RELEASE_BASE}/{bp.CPYTHON_RELEASE}/{name.replace('+', '%2B')}"
        _log(f"downloading {url}")
        with urllib.request.urlopen(url) as response:
            archive.write_bytes(response.read())
    actual = hashlib.sha256(archive.read_bytes()).hexdigest()
    if actual != expected:
        archive.unlink(missing_ok=True)
        raise SystemExit(f"checksum mismatch for {name}:\n  expected {expected}\n"
                         f"  got      {actual}\nThe download was removed; re-run.")
    _log(f"checksum verified  sha256={actual[:16]}...")
    return archive


def unpack_cpython(archive: Path, resources: Path) -> Path:
    """Unpack into `Resources/python`. Returns the interpreter."""
    _log(f"unpacking into {resources}")
    with tarfile.open(archive, "r:gz") as tar:
        # The `data` filter (3.12+, and later 3.9-3.11 patch releases) refuses
        # links that escape the destination. A Mac's system Python may predate it;
        # the archive has already been checked against the release's SHA256SUMS.
        if hasattr(tarfile, "data_filter"):
            tar.extractall(resources, filter="data")   # top-level dir is `python/`
        else:
            tar.extractall(resources)
    python = resources / "python" / "bin" / "python3"
    if not python.exists():
        raise SystemExit(f"no interpreter at {python}")
    mb.link_interpreter(resources / "python")
    return python


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------
def pip_install(python: Path, arguments: List[str]) -> None:
    env = dict(os.environ, PIP_DISABLE_PIP_VERSION_CHECK="1")
    _run([str(python), "-m", "pip", "install", "--no-cache-dir", *arguments],
         cwd=PROJECT_ROOT, env=env)


def install_dependencies(python: Path, arch: str, with_engine: bool) -> None:
    constraints: List[str] = []
    if arch == "x86_64":
        # Intel Macs: PyTorch stopped publishing x86_64 macOS wheels after 2.2.2.
        # Without this pin pip would fail to resolve rather than pick the newest.
        constraints = ["-c", str(INTEL_CONSTRAINTS)]
    pip_install(python, ["--upgrade", "pip"])
    pip_install(python, ["-r", "requirements-light.txt", "-r", "requirements-qt.txt",
                         *constraints])
    if with_engine:
        # PyPI's macOS torch wheels are already CPU/MPS builds, so unlike the
        # Windows script there is no CPU-only index to select.
        _log("adding the analysis engine")
        pip_install(python, ["torch>=2.2,<3.0", "transformers>=4.40,<5.0",
                             "sentence-transformers>=2.7,<4.0", *constraints])


def site_packages(resources: Path) -> Path:
    return resources / "python" / "lib" / f"python{PYTHON_MINOR}" / "site-packages"


def prune(resources: Path) -> None:
    """Remove what the app provably never loads. Reports what it reclaimed."""
    sp = site_packages(resources)
    before = bp._tree_size(sp)

    for name in bp.DEPENDENCY_PRUNE:
        bp._remove(sp / name)
        for dist in list(sp.glob(f"{name}-*.dist-info")) + \
                list(sp.glob(f"{name.replace('_', '-')}*.dist-info")):
            bp._remove(dist)

    pyside = sp / "PySide6"
    if pyside.is_dir():
        for relative in mb.PYSIDE_PRUNE_PATHS:
            bp._remove(pyside / relative)
        for pattern in mb.PYSIDE_PRUNE_GLOBS:
            for path in pyside.glob(pattern):
                bp._remove(path)
        for pattern in mb.PYSIDE_PRUNE_FRAMEWORK_GLOBS:
            for path in (pyside / "Qt" / "lib").glob(pattern):
                bp._remove(path)
        translations = pyside / "Qt" / "translations"
        if translations.is_dir():
            for path in translations.iterdir():
                if not path.name.startswith(("qt_en", "qtbase_en")):
                    bp._remove(path)

    # Console scripts pip wrote with the build machine's path in their shebang.
    for script in mb.scripts_with_absolute_shebang(resources / "python" / "bin"):
        _log(f"removing relocation-unsafe script {script.name}")
        script.unlink()

    after = bp._tree_size(sp)
    _log(f"pruned {(before - after) / 1e6:,.0f} MB "
         f"({before / 1e6:,.0f} -> {after / 1e6:,.0f} MB)")


def assert_payload_clean(resources: Path) -> None:
    """Refuse to ship anything unexpected at the top of Resources.

    Same guard as the Windows build, plus the icon this bundle adds itself.
    """
    expected = {"python", *bp.APP_DIRS, *bp.APP_FILES, mb.ICON_FILE}
    actual = {p.name for p in resources.iterdir()}
    unexpected = sorted(actual - expected)
    if unexpected:
        raise SystemExit("refusing to ship: unexpected files in Resources:\n  "
                         + "\n  ".join(unexpected))
    missing = sorted(set(bp.APP_DIRS) - actual)
    if missing:
        raise SystemExit(f"payload is missing: {', '.join(missing)}")
    _log(f"payload root is clean ({len(actual)} entries)")


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------
def verify(python: Path, resources: Path) -> None:
    """Run the same verification the Windows payload gets, with the bundle's own
    interpreter, then check the versions the bundle reports against the tree."""
    _log("verifying the payload")
    script = resources / "_verify.py"
    script.write_text(bp.VERIFY_SCRIPT, encoding="utf-8")
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONNOUSERSITE="1")
    try:
        result = subprocess.run([str(python), str(script)], cwd=resources,
                                capture_output=True, text=True, env=env)
    finally:
        script.unlink(missing_ok=True)
    print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    if result.returncode != 0:
        raise SystemExit(f"the payload failed its own verification "
                         f"(exit {result.returncode}); see the traceback above")
    bp._assert_versions_agree(result.stdout)


ENGINE_CHECK = r'''
import torch, transformers, sentence_transformers
from transformers import BartConfig, BartForSequenceClassification
# A real forward pass on a tiny randomly-initialised model: no download, no
# network. It exists because the Intel build runs torch 2.2.2 under a
# transformers release that documents a higher floor for one code path, and an
# import alone would not reveal whether the zero-shot model's own path works.
config = BartConfig(vocab_size=100, d_model=16, encoder_layers=1, decoder_layers=1,
                    encoder_attention_heads=2, decoder_attention_heads=2,
                    encoder_ffn_dim=32, decoder_ffn_dim=32, num_labels=3)
model = BartForSequenceClassification(config).eval()
with torch.no_grad():
    out = model(input_ids=torch.tensor([[0, 5, 6, 2]]))
assert out.logits.shape == (1, 3), out.logits.shape
print(f"engine ok: torch {torch.__version__}, transformers {transformers.__version__}")
'''


def verify_engine(python: Path, resources: Path) -> None:
    env = dict(os.environ, PYTHONNOUSERSITE="1", HF_HUB_OFFLINE="1",
               TRANSFORMERS_OFFLINE="1")
    result = subprocess.run([str(python), "-c", ENGINE_CHECK], cwd=resources,
                            capture_output=True, text=True, env=env)
    print(result.stdout, end="")
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        raise SystemExit("the bundled analysis engine failed its forward-pass check")


def check_qt_links(resources: Path) -> None:
    """Prove nothing that remains links a Qt framework that was pruned.

    The prune list is an assertion that the app never loads those frameworks.
    Import tests and an offscreen window cannot check it for the Cocoa plugin --
    that one only loads with a window server -- but `otool -L` lists what every
    binary would need at load time, so a dangling reference is found here rather
    than as a missing-library crash on a researcher's Mac.
    """
    lib = site_packages(resources) / "PySide6" / "Qt" / "lib"
    if not lib.is_dir():
        raise SystemExit(f"no Qt frameworks at {lib}")
    present = {p.name[:-len(".framework")] for p in lib.glob("*.framework")}
    problems = []
    for binary in mb.find_macho_files(site_packages(resources) / "PySide6"):
        out = subprocess.run(["otool", "-L", str(binary)], capture_output=True,
                             text=True).stdout
        missing = mb.missing_frameworks(mb.qt_frameworks_referenced(out), present)
        if missing:
            problems.append(f"  {binary.relative_to(resources)} needs {', '.join(missing)}")
    if problems:
        more = f"\n  ... and {len(problems) - 20} more" if len(problems) > 20 else ""
        raise SystemExit("pruning removed frameworks that remaining binaries link:\n"
                         + "\n".join(problems[:20]) + more
                         + "\n\nIf the app never loads the binary listed, prune it too "
                         "(PYSIDE_PRUNE_PATHS in mac_bundle.py); if it does, remove the "
                         "framework's entry from PYSIDE_PRUNE_* instead.")
    _log(f"Qt link check passed ({len(present)} frameworks kept)")


def smoke_launch(app: Path, seconds: int = 20) -> None:
    """Start the real launcher offscreen and require it to still be running.

    It exercises what nothing else does: the bundle's launcher script, its paths,
    the bundle's own interpreter, and the app's main() -- through
    `Contents/MacOS/QualSafe`, the exact file macOS would execute. A launcher
    that cannot find Python, or an app that raises during start-up, exits within
    a second or two. The Cocoa plugin is not exercised (offscreen); CI covers it
    with a real `open`.
    """
    launcher = app / "Contents" / "MacOS" / mb.EXECUTABLE
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    proc = subprocess.Popen([str(launcher)], env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True)
    try:
        deadline = time.time() + seconds
        while time.time() < deadline:
            if proc.poll() is not None:
                output = proc.stdout.read() if proc.stdout else ""
                raise SystemExit(f"the launcher exited with {proc.returncode} "
                                 f"within {seconds}s:\n{output}")
            time.sleep(0.5)
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
    _log(f"launcher stayed running for {seconds}s")


# ---------------------------------------------------------------------------
# Bytecode, signing, packaging
# ---------------------------------------------------------------------------
def precompile(python: Path, resources: Path) -> None:
    """Compile every module now, so the signed bundle never has to change.

    `checked-hash` pycs, not `unchecked-hash`: unchecked ones are never compared
    with their source, and these files are not listed in any package's RECORD, so
    a later `pip install --upgrade` inside the bundle would leave a stale one that
    Python trusts over the new source. Checked ones cost a hash of the source at
    import and cannot go stale.
    """
    _log("precompiling bytecode")
    flags = ["-m", "compileall", "-q", "-f", "-j", "0",
             "--invalidation-mode", "checked-hash"]
    # The application's own code must compile: a syntax error there is a bug.
    _run([str(python), *flags, *[str(resources / d) for d in bp.APP_DIRS],
          *[str(resources / f) for f in bp.APP_FILES if f.endswith(".py")]])
    # The interpreter tree is best-effort. The standard library ships test data
    # containing deliberate syntax errors (lib2to3's fixtures), and compileall
    # exits non-zero for those. A module that is not precompiled is compiled in
    # memory at import instead; nothing breaks, it just starts a little slower.
    result = subprocess.run([str(python), *flags, str(resources / "python")],
                            capture_output=True, text=True)
    if result.returncode:
        _log("some interpreter-tree files did not precompile (expected: stdlib "
             "test fixtures with deliberate syntax errors)")


def sign(app: Path, identity: str) -> None:
    entitlements: Optional[Path] = None
    if identity != mb.AD_HOC:
        entitlements = BUILD_DIR / "entitlements.plist"
        entitlements.write_bytes(mb.entitlements_plist())
    files = mb.find_macho_files(app)
    _log(f"signing {len(files)} binaries "
         f"({'ad-hoc' if identity == mb.AD_HOC else identity})")
    for command in mb.signing_commands(files, identity, entitlements):
        _run(command)
    _run(mb.bundle_signing_command(app, identity, entitlements))
    _run(["codesign", "--verify", "--verbose=2", str(app)])


def make_dmg(app: Path, version: str, arch: str, identity: str = mb.AD_HOC) -> Path:
    output = BUILD_DIR / f"QualSafe-Desktop-{version}-macOS-{arch}.dmg"
    staging = BUILD_DIR / f"dmg-{arch}"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    # `ditto` is macOS's own copier: it keeps symlinks as symlinks, plus the modes
    # and extended attributes a signed bundle depends on. shutil.copytree
    # follows or flattens some of those, and a bundle copied that way can fail its
    # own signature check.
    _run(["ditto", str(app), str(staging / app.name)])
    (staging / "Applications").symlink_to("/Applications")
    output.unlink(missing_ok=True)
    _run_retrying(mb.dmg_command(staging, f"{mb.DISPLAY_NAME} {version}", output))
    shutil.rmtree(staging, ignore_errors=True)
    if identity != mb.AD_HOC:
        # A disk image must carry its own signature before it can be notarised
        # and stapled; signing the app inside it does not cover the container.
        _run(mb.dmg_signing_command(output, identity))
    return output


def notarize(dmg: Path, profile: str) -> None:
    for command in mb.notarize_commands(dmg, profile):
        _run(command)


# ---------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--arch", choices=mb.ARCHITECTURES, default=host_architecture())
    parser.add_argument("--engine", action="store_true",
                        help="bundle torch/transformers (several GB more)")
    parser.add_argument("--no-dmg", action="store_true")
    parser.add_argument("--skip-verify", action="store_true")
    args = parser.parse_args()

    require_mac_host(args.arch)
    version = bp.app_version()
    identity = os.environ.get("QUALSAFE_SIGN_IDENTITY", mb.AD_HOC)
    notary = os.environ.get("QUALSAFE_NOTARY_PROFILE")
    if notary and identity == mb.AD_HOC:
        raise SystemExit("QUALSAFE_NOTARY_PROFILE is set but no Developer ID "
                         "identity is: notarisation rejects ad-hoc signatures.")

    _log(f"QualSafe Desktop {version} for macOS {args.arch}"
         f"{' + analysis engine' if args.engine else ' (lite)'}")

    out = BUILD_DIR / f"mac-{args.arch}"
    app = out / f"{mb.BUNDLE_NAME}.app"
    if app.exists():
        shutil.rmtree(app)
    resources = app / "Contents" / "Resources"
    mb.write_bundle_shell(app, version, ICON)

    python = unpack_cpython(fetch_cpython(args.arch), resources)
    install_dependencies(python, args.arch, args.engine)
    prune(resources)
    bp.copy_application(resources)
    assert_payload_clean(resources)
    check_qt_links(resources)

    if not args.skip_verify:
        verify(python, resources)
        if args.engine:
            verify_engine(python, resources)

    precompile(python, resources)
    sign(app, identity)
    if not args.skip_verify:
        smoke_launch(app)

    size = bp._tree_size(app)
    _log(f"app ready: {app}  ({size / 1e9:.2f} GB)")
    dmg: Optional[Path] = None
    if not args.no_dmg:
        dmg = make_dmg(app, version, args.arch, identity)
        if notary:
            notarize(dmg, notary)

    src = bp.source_versions()
    _log("-" * 60)
    _log(f"app {src['app']}   engine {src['engine']}   project format v{src['store']}")
    _log(f"architecture {args.arch}   signing "
         f"{'ad-hoc' if identity == mb.AD_HOC else identity}"
         f"{'   notarised' if notary else ''}")
    if dmg:
        _log(f"{dmg.name}  {dmg.stat().st_size / 1e6:.1f} MB")
        _log("sha256 " + hashlib.sha256(dmg.read_bytes()).hexdigest())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
