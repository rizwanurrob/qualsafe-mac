#!/usr/bin/env python
"""
Build a clean, distributable release zip of the whole tool (v3.6+).

Replaces the older PowerShell packager, which predated the core/engines/analysis/
interview/exports/privacy packages and silently shipped an incomplete app. This
copies the entire source tree and *excludes* the things that must never ship — the
virtual environment, run outputs, caches, git internals, and prior builds — then
zips the result.

    python tools/build_release.py                 # -> dist/QualSafe_v<version>.zip
    python tools/build_release.py --version 3.9.1
    python tools/build_release.py --outdir /path  # also drop a copy here

The zip is the end-user installer package: it ships the app, installers, sample
data, user docs (README, CHANGELOG, INSTALL_FIRST, user guide, cheat sheet), and
the test suite — but not the internal development documentation (handoff, design
notes, progress logs, release checklist) or repo/CI metadata.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Directory / file names never included in a release, matched at any depth.
EXCLUDE_NAMES = {
    ".venv", ".git", "dist", "build", "__pycache__", ".pytest_cache", ".mypy_cache",
    "output", "output_streamlit", "output_iterative", "output_interview",
    ".embedding_cache", ".DS_Store",
    # Internal development documentation & repo metadata — not for end users.
    # User-facing docs (README, CHANGELOG, INSTALL_FIRST, user guide, cheat
    # sheet) stay in.
    "HANDOFF.md", "project_progress", "notebooks", ".github", ".gitattributes",
    ".gitignore",
    "DESIGN_NOTES_future_features.md", "RELEASE_VERIFICATION_CHECKLIST.md",
    "WEBSITE_DOWNLOAD_PACKAGING_GUIDE.md",
}
# Suffixes never included (generated artifacts).
EXCLUDE_SUFFIXES = {".pyc", ".qnw", ".npy"}


def _version() -> str:
    """Read the version from pyproject.toml so there's one source of truth."""
    try:
        import tomllib
        data = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        return str(data["project"]["version"])
    except Exception:  # noqa: BLE001
        return "0.0.0"


def _ignore(dir_path, names):
    """shutil.copytree ignore callback: drop excluded names/suffixes."""
    ignored = set()
    for name in names:
        if name in EXCLUDE_NAMES:
            ignored.add(name)
        elif any(name.endswith(sfx) for sfx in EXCLUDE_SUFFIXES):
            ignored.add(name)
    return ignored


def _rmtree_robust(path: Path, attempts: int = 5) -> None:
    """rmtree with retries — Windows briefly locks freshly-written files (an AV
    scan or a lingering handle), so a single rmtree can raise PermissionError on a
    directory whose contents were just copied. Retry with a short backoff; only
    the *last* failure propagates."""
    import time

    for i in range(attempts):
        try:
            shutil.rmtree(path)
            return
        except FileNotFoundError:
            return
        except PermissionError:
            if i == attempts - 1:
                raise
            time.sleep(0.5 * (i + 1))


def build(version: str, extra_outdir: Path | None) -> Path:
    dist = PROJECT_ROOT / "dist"
    dist.mkdir(exist_ok=True)
    name = f"QualSafe_v{version}"
    staging = dist / name
    if staging.exists():
        _rmtree_robust(staging)

    shutil.copytree(PROJECT_ROOT, staging, ignore=_ignore, dirs_exist_ok=False)
    # copytree with our ignore still descends the root; drop dist itself if copied.
    if (staging / "dist").exists():
        shutil.rmtree(staging / "dist")

    zip_base = dist / name
    archive = shutil.make_archive(str(zip_base), "zip", root_dir=dist, base_dir=name)
    archive_path = Path(archive)

    # Deliver the zip BEFORE cleaning staging: on Windows an antivirus scan can
    # briefly lock the just-copied files, and staging cleanup must never block the
    # actual deliverable (the zip + the outdir copy).
    if extra_outdir:
        extra_outdir = Path(extra_outdir)
        extra_outdir.mkdir(parents=True, exist_ok=True)
        dest = extra_outdir / archive_path.name
        shutil.copy2(archive_path, dest)
        print(f"Copied to: {dest}")

    # Clean the staging folder — best-effort; the zip is already built and copied.
    try:
        _rmtree_robust(staging)
    except Exception as exc:  # noqa: BLE001
        print(f"[WARN] Could not remove staging folder {staging}: {exc}\n"
              f"       The release zip is fine; delete the folder manually later.")

    return archive_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a release zip.")
    parser.add_argument("--version", default=None, help="Override version (default: pyproject).")
    parser.add_argument("--outdir", default=None, help="Also copy the zip here.")
    args = parser.parse_args()

    version = args.version or _version()
    print(f"Building release v{version}…")
    archive = build(version, Path(args.outdir) if args.outdir else None)
    size_mb = archive.stat().st_size / (1024 * 1024)
    print(f"Release zip: {archive}  ({size_mb:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
