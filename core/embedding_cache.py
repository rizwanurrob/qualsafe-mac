#!/usr/bin/env python
"""
On-disk embedding cache (v3.1.1, Phase 1.5).

Extracted from `iterative_supervised_thematic.py`, which has cached embeddings
since v2 while the main survey pipeline re-encoded from scratch every run. Now
both callers share this module, so a second run over the same responses reuses
vectors instead of paying the full encode again.

Cache files live under `<cache_dir>/` as `embeddings_<hash>.npy` plus a
`.meta.json` sidecar. The key covers everything that changes the vectors —
texts, model name, and the normalize flag — because serving a stale vector that
was computed with different settings is a silent correctness bug, not a cache
miss.

Privacy note: an embedding of sensitive text is derived data. This cache is a PII
artifact, and `core/erasure.py` deletes these files outright when a respondent is
erased (you cannot surgically remove one row from a row-aligned array). Keep that
contract if you touch either module.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import List, Optional

import numpy as np

# Safe to import at module scope: analyze_survey defers its own torch imports to
# first model use (see core/offline.py), so this line pulls in no heavy stack.
# Module-level so tests can monkeypatch core.embedding_cache.build_embeddings.
from analyze_survey import build_embeddings

LOGGER = logging.getLogger("embedding_cache")

# Bump when the cache format or hashing changes, to invalidate old files.
CACHE_VERSION = "v3"


def texts_hash(texts: List[str], model_name: str, normalize: bool = True) -> str:
    """Stable cache key over the inputs that determine the vectors.

    Includes `normalize` (the v2 key did not): normalized and un-normalized
    vectors are different numbers, and a run that flips the flag must not be
    handed the other version's cache.
    """
    h = hashlib.sha256()
    h.update(CACHE_VERSION.encode())
    h.update(model_name.encode())
    h.update(b"norm=1" if normalize else b"norm=0")
    for t in texts:
        h.update(t.encode("utf-8", errors="replace"))
        h.update(b"\x00")  # delimiter: ["ab","c"] must not hash like ["a","bc"]
    return h.hexdigest()[:16]


def load_or_build_embeddings(
    texts: List[str],
    model_name: str,
    batch_size: int,
    cache_dir: Path,
    *,
    normalize_embeddings: bool = True,
    dedupe: bool = False,
    max_cache_files: Optional[int] = 50,
) -> np.ndarray:
    """Return cached embeddings if valid, else build them and write the cache."""
    cache_dir = Path(cache_dir)
    key = texts_hash(texts, model_name, normalize_embeddings)
    emb_path = cache_dir / f"embeddings_{key}.npy"
    meta_path = cache_dir / f"embeddings_{key}.meta.json"

    if emb_path.exists() and meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if (
                meta.get("n_texts") == len(texts)
                and meta.get("model") == model_name
                and meta.get("normalize") == normalize_embeddings
            ):
                LOGGER.info("Reusing cached embeddings: %s", emb_path)
                cached = np.load(emb_path)
                # Guard against a truncated/mismatched file silently returning the
                # wrong number of rows.
                if cached.shape[0] == len(texts):
                    return cached
                LOGGER.warning("Cached row count mismatch; rebuilding.")
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Cache read failed (%s); rebuilding.", exc)

    embeddings = build_embeddings(
        texts=texts,
        model_name=model_name,
        batch_size=batch_size,
        normalize_embeddings=normalize_embeddings,
        dedupe=dedupe,
    )
    cache_dir.mkdir(parents=True, exist_ok=True)
    np.save(emb_path, embeddings)
    meta_path.write_text(
        json.dumps({
            "n_texts": len(texts),
            "model": model_name,
            "normalize": normalize_embeddings,
            "cache_version": CACHE_VERSION,
        }),
        encoding="utf-8",
    )
    LOGGER.info("Embeddings cached: %s", emb_path)
    if max_cache_files:
        _evict_oldest(cache_dir, max_cache_files)
    return embeddings


def _evict_oldest(cache_dir: Path, keep: int) -> None:
    """Keep at most `keep` cache entries, deleting the least-recently-modified.

    Ten runs over a 50k-row file is real disk. Eviction is by mtime — a rough LRU
    that needs no access-time bookkeeping.
    """
    npys = sorted(cache_dir.glob("embeddings_*.npy"), key=lambda p: p.stat().st_mtime)
    excess = len(npys) - keep
    for path in npys[:max(excess, 0)]:
        for target in (path, path.with_suffix("").with_suffix(".meta.json")):
            try:
                target.unlink()
            except Exception:  # noqa: BLE001 - best-effort cleanup
                pass


def clear_cache(cache_dir: Path) -> int:
    """Delete all cache files. Returns the number of .npy files removed."""
    cache_dir = Path(cache_dir)
    if not cache_dir.exists():
        return 0
    removed = 0
    for path in cache_dir.glob("embeddings_*.npy"):
        try:
            path.unlink()
            removed += 1
        except Exception:  # noqa: BLE001
            pass
    for meta in cache_dir.glob("embeddings_*.meta.json"):
        try:
            meta.unlink()
        except Exception:  # noqa: BLE001
            pass
    return removed
