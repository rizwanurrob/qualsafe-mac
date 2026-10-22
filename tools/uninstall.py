#!/usr/bin/env python
"""
Uninstall / clean-slate helper (v3.6).

Removes the tool's installed environment and generated data so a fresh install
starts clean. It reports what it will remove and what it removed — nothing is
deleted silently. The installer scripts call this after the user confirms.

Scope (in order of how far it reaches):
  --caches   (default)  : embedding caches, __pycache__, session inputs, outputs
  --env                 : also the virtual environment (.venv)
  --models              : also the downloaded Hugging Face model cache
  --all                 : env + models + caches

It never touches your source data files or your `.qnw` projects outside the
tool's own output folders — those are yours. Ollama and its models are separate
software and are left alone (uninstall Ollama through your OS if you want).
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path
from typing import List, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# (path, description) — generated artifacts safe to remove.
CACHE_TARGETS: List[Tuple[Path, str]] = [
    (PROJECT_ROOT / "output", "CLI pipeline outputs"),
    (PROJECT_ROOT / "output_streamlit", "GUI run outputs (incl. project stores)"),
    (PROJECT_ROOT / "output_iterative", "iterative labeling outputs"),
    (PROJECT_ROOT / "output_interview", "interview outputs"),
    (PROJECT_ROOT / "data" / "session_inputs", "legacy session input snapshots"),
    (PROJECT_ROOT / "data" / "public_datasets", "downloaded public datasets"),
]


def _human_size(path: Path) -> str:
    if not path.exists():
        return "0 B"
    total = sum(f.stat().st_size for f in path.rglob("*") if f.is_file()) if path.is_dir() \
        else path.stat().st_size
    for unit in ("B", "KB", "MB", "GB"):
        if total < 1024:
            return f"{total:.1f} {unit}"
        total /= 1024
    return f"{total:.1f} TB"


def _remove(path: Path, dry_run: bool) -> bool:
    if not path.exists():
        return False
    if dry_run:
        return True
    try:
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"  ! could not remove {path}: {exc}")
        return False


# Trees that contain somebody else's Python, not ours. `.venv` was always here;
# `build`/`dist` joined it once the desktop installer started assembling a whole
# relocatable CPython at `build/payload/python/Lib/site-packages/`. Walking that
# offered hundreds of bytecode directories belonging to third-party packages for
# deletion — wider than "clear caches" promises, and it turned the suite red,
# because two tests use `"huggingface" in path` as a stand-in for "the model
# cache" and `site-packages/huggingface_hub/__pycache__` matches the substring.
FOREIGN_TREES = (".venv", "build", "dist")


def _rglob_excluding_venv(pattern: str):
    """rglob under the project but never descend into an environment we did not
    write: `.venv` and any packaged build output (huge, and their caches belong to
    installed packages, not to us)."""
    foreign = [PROJECT_ROOT / name for name in FOREIGN_TREES]
    for p in PROJECT_ROOT.rglob(pattern):
        if not any(root in p.parents for root in foreign):
            yield p


def plan_targets(scope: str) -> List[Tuple[Path, str]]:
    """Resolve which paths a scope removes."""
    targets = list(CACHE_TARGETS)
    # Our own caches only — not the ones inside installed packages under .venv.
    targets += [(p, "embedding cache") for p in _rglob_excluding_venv(".embedding_cache")]
    targets += [(p, "Python bytecode cache") for p in _rglob_excluding_venv("__pycache__")]

    if scope in ("env", "all"):
        targets.append((PROJECT_ROOT / ".venv", "virtual environment (.venv)"))
    if scope in ("models", "all"):
        targets += model_cache_targets()
    return targets


def model_cache_dirs() -> List[Tuple[Path, str]]:
    """Where Hugging Face keeps downloaded models, resolved the way
    `huggingface_hub` resolves it: the app finds its models through that library
    (core/model_manager.py), so the uninstaller must look where it looks.

    `HF_HOME` moves the whole cache (default `$XDG_CACHE_HOME/huggingface`, else
    `~/.cache/huggingface`); `HF_HUB_CACHE` (or the older `HUGGINGFACE_HUB_CACHE`)
    moves just the model store, which is otherwise `<HF_HOME>/hub`. A hard-coded
    `~/.cache/huggingface` missed a moved cache and reported "already clean".
    stdlib only: this runs on the system Python, possibly after `.venv` is gone.
    """
    env = os.environ
    if env.get("HF_HOME"):
        home, why = Path(env["HF_HOME"]).expanduser(), "set by HF_HOME"
    elif env.get("XDG_CACHE_HOME"):
        home, why = Path(env["XDG_CACHE_HOME"]).expanduser() / "huggingface", "set by XDG_CACHE_HOME"
    else:
        home, why = Path.home() / ".cache" / "huggingface", "default location"
    dirs = [(home, why)]
    hub_var = next((k for k in ("HF_HUB_CACHE", "HUGGINGFACE_HUB_CACHE") if env.get(k)), None)
    if hub_var:
        hub = Path(env[hub_var]).expanduser()
        if not _is_within(hub, home):
            dirs.append((hub, f"set by {hub_var}"))
    return dirs


def unsafe_to_remove(path: Path) -> str:
    """Why `path` must never be deleted wholesale, or "" if it may be.

    The model cache's location comes from environment variables, and a mistaken
    `HF_HOME=~` (or a drive root, or this program's folder) would otherwise turn
    "remove downloaded models" into "remove everything". Refuse a drive root, and
    anything that is or contains the home folder or this program.
    """
    p = Path(os.path.abspath(path))
    if p == Path(p.anchor):
        return "it is the root of a drive"
    for name, other in (("your home folder", Path.home()), ("this program's folder", PROJECT_ROOT)):
        if _is_within(other, p):
            return f"it is, or contains, {name}"
    return ""


def _is_within(child: Path, parent: Path) -> bool:
    child, parent = Path(os.path.abspath(child)), Path(os.path.abspath(parent))
    return child == parent or parent in child.parents


def model_cache_targets() -> List[Tuple[Path, str]]:
    """The model cache folders that are safe to offer for removal; any that
    are not are named, with the reason, and left alone."""
    out = []
    for path, why in model_cache_dirs():
        reason = unsafe_to_remove(path)
        if reason:
            print(f"  ! not removing the model cache at {path} ({why}): {reason}. "
                  f"Delete the models inside it by hand if you want them gone.")
            continue
        out.append((path, f"Hugging Face model cache, {why} (shared by every tool that uses it!)"))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Remove the tool's environment and generated data.")
    parser.add_argument("--scope", choices=["caches", "env", "models", "all"], default="caches")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be removed, remove nothing.")
    parser.add_argument("--yes", action="store_true", help="Skip the confirmation prompt.")
    args = parser.parse_args()

    targets = [(p, d) for (p, d) in plan_targets(args.scope) if p.exists()]
    if not targets:
        print("Nothing to remove — already clean.")
        return 0

    print(f"\nUninstall scope: {args.scope}")
    print("Will remove:")
    for path, desc in targets:
        print(f"  - {path}  ({_human_size(path)})  — {desc}")
    if args.scope in ("models", "all"):
        print("\n  NOTE: the Hugging Face cache is shared. Removing it affects any other")
        print("  tool on this machine that uses Hugging Face models.")

    if args.dry_run:
        print("\nDry run — nothing removed.")
        return 0

    if not args.yes:
        reply = input("\nProceed? Type 'yes' to confirm: ").strip().lower()
        if reply != "yes":
            print("Cancelled.")
            return 1

    removed = 0
    for path, _desc in targets:
        if _remove(path, dry_run=False):
            removed += 1
            print(f"  removed {path}")
    print(f"\nDone. Removed {removed} item(s).")
    if args.scope in ("env", "all"):
        print("Re-install with the installer for your OS (install_windows.bat / install_mac_linux.sh).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
