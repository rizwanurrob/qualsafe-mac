#!/usr/bin/env python
"""
Project-store safety backups (v3.8.0, item 8.3).

Every destructive or bulk-import operation on a live `.qnw` — respondent erasure,
coder merges, codebook restores — now snapshots the store first. SQLite keeps the
file consistent; this keeps the *analyst* consistent, giving them a way back from
an operation that did what they asked but not what they meant.

Backups live in `project_backups/` beside the store, capped at the newest
`keep` copies. They contain the same sensitive data as the store itself, so they
live and die with the project directory (purge removes them too) and are covered
by the same on-encrypted-volume guidance.
"""

from __future__ import annotations

import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Union

BACKUP_DIR_NAME = "project_backups"
DEFAULT_KEEP = 5


def _backup_dir(store_path: Path) -> Path:
    return store_path.parent / BACKUP_DIR_NAME


def backup_store(store_path: Union[str, Path], reason: str = "manual",
                 keep: int = DEFAULT_KEEP) -> Optional[Path]:
    """Copy the store into project_backups/, pruning to the newest `keep`.

    Returns the backup path, or None when there is nothing to back up. Never
    raises into the caller — a failed backup shouldn't block the operation, but
    it IS surfaced by returning None so call sites can warn.
    """
    store_path = Path(store_path)
    if not store_path.exists():
        return None
    try:
        slug = re.sub(r"[^a-z0-9]+", "_", reason.lower()).strip("_") or "backup"
        # Timestamp in the NAME, and all ordering by name: copy2 preserves the
        # source's mtime, so every backup of one store shares an mtime —
        # sorting/pruning by mtime would delete arbitrary backups.
        #
        # `%f` is not reliably microsecond-precise. On Windows `datetime.now()`
        # advances in coarse ticks, so eight consecutive calls return one
        # identical stamp — measured, not assumed. (Linux and macOS are usually
        # fine-grained, but a name must not depend on the host clock.) Two
        # backups inside that window therefore produced the *same filename*,
        # and `copy2` silently overwrote the first. A five-deep safety net
        # quietly became one deep, and worst exactly where it matters: the
        # automatic backups taken before destructive operations arrive in
        # bursts.
        #
        # A zero-padded sequence number disambiguates, placed immediately after
        # the stamp so ordering by name stays chronological.
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        target_dir = _backup_dir(store_path)
        target_dir.mkdir(parents=True, exist_ok=True)
        target = _free_name(target_dir, stamp, slug)
        shutil.copy2(store_path, target)
        _prune(target_dir, keep)
        return target
    except Exception:  # noqa: BLE001
        return None


#: How many backups may share one clock tick before the caller is simply out of
#: names. Far above any realistic burst within one coarse Windows tick, and
#: bounded so a full directory cannot spin here.
_MAX_PER_TICK = 1000


def _free_name(target_dir: Path, stamp: str, slug: str) -> Path:
    """A filename in `target_dir` that no existing backup already holds.

    The sequence number is always present and zero-padded, never appended only
    on collision: `..._971360_manual.qnw` and `..._971360_1_manual.qnw` sort
    with the *later* file first under a plain name sort, which would make
    `list_backups` report the wrong newest backup and `_prune` delete the wrong
    one. Uniform names keep the ordering honest.
    """
    for sequence in range(_MAX_PER_TICK):
        candidate = target_dir / f"project_{stamp}_{sequence:03d}_{slug}.qnw"
        if not candidate.exists():
            return candidate
    raise RuntimeError(
        f"{_MAX_PER_TICK} backups already share the timestamp {stamp}")


def _prune(target_dir: Path, keep: int) -> None:
    backups = sorted(target_dir.glob("project_*.qnw"), key=lambda p: p.name, reverse=True)
    for old in backups[max(keep, 1):]:
        try:
            old.unlink()
        except Exception:  # noqa: BLE001
            pass


def list_backups(store_path: Union[str, Path]) -> List[Path]:
    """Backups for a store, newest first (by name-embedded timestamp)."""
    target_dir = _backup_dir(Path(store_path))
    if not target_dir.exists():
        return []
    return sorted(target_dir.glob("project_*.qnw"), key=lambda p: p.name, reverse=True)


def restore_backup(store_path: Union[str, Path], backup_path: Union[str, Path]) -> Path:
    """Replace the store with a backup. The current state is backed up first
    ("pre_restore"), so a restore is itself undoable."""
    store_path = Path(store_path)
    backup_path = Path(backup_path)
    if not backup_path.exists():
        raise FileNotFoundError(f"Backup not found: {backup_path}")
    backup_store(store_path, reason="pre_restore")
    shutil.copy2(backup_path, store_path)
    return store_path
