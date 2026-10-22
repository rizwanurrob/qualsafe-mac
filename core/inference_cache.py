#!/usr/bin/env python
"""
Per-response cache for model outputs (v4.9, Pass 18).

**The pipeline cached the one stage that costs nothing and recomputed the one
that costs everything.** `core/embedding_cache.py` has stored embeddings since
v3.1.1; on a 5,000-response run with six labels that stage is about 60 seconds
of a 7,680-second job. Zero-shot classification — 7,200 of those seconds, 94% of
the wall clock — was recomputed from scratch every single time.

Three consequences, all of them things a researcher actually does:

* **A crash costs the whole run.** The embedding cache is written once, at the
  end of its stage, keyed on the entire text list. A run that dies ninety
  minutes in has written nothing for the ninety minutes and starts over.
* **Adding one label re-codes everything.** Codebooks are iterative — that is
  the method, not a mistake — and a seventh label meant paying for the first six
  again.
* **Fixing one typo in one response re-codes everything.** The embedding cache
  key is a hash of every text concatenated, so a single edited character is a
  total miss.

This module is keyed per response instead, and writes as it goes.

Granularity, and why it differs by mode
---------------------------------------
Zero-shot scores are cached **per (response, label)** when `multi_label=True`
and **per (response, whole label set)** when it is False. That is not a
guess — measured on `facebook/bart-large-mnli`, holding the responses fixed and
changing the candidate set from six labels to two:

    multi_label=True    worst score drift 5.96e-08   (float noise)
    multi_label=False   worst score drift 3.85e-01

With `multi_label=True` each (premise, hypothesis) pair is scored on its own, so
a label's score does not depend on its company and may be reused freely. With
`multi_label=False` the pipeline softmaxes across the candidate set, so the same
label legitimately scores 0.56 among six labels and 0.94 among two. Caching that
per label would silently serve numbers from a different question, which is a
correctness bug wearing a performance costume — hence the whole set in the key.

Privacy
-------
Like the embedding cache, this is derived data computed from response text, and
the key is a hash of that text. It is therefore a PII artifact: it lives beside
the outputs it belongs to so `core/erasure.py` can find it, and erasure deletes
it. Hashes are not anonymisation — a hash of a known string is a lookup — so
nothing here is treated as safe to keep after an erasure request.

Storage
-------
SQLite, because the project already depends on it, a single file is easy to
delete wholesale for erasure, and each `put_many` commits — which is what makes
an interrupted run keep its work.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

LOGGER = logging.getLogger("inference_cache")

#: Bump when a key's meaning changes, so old entries are never served under a
#: new interpretation. This is the same contract as the embedding cache's, and
#: for the same reason: a stale hit is a wrong answer, not a slow one.
CACHE_VERSION = "v1"

#: The file, relative to a run's output directory.
CACHE_FILENAME = "inference_cache.sqlite"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
    key   TEXT PRIMARY KEY,
    kind  TEXT NOT NULL,
    value TEXT NOT NULL
);
"""


def _digest(*parts: str) -> str:
    """A key over the things that change the answer, and nothing else.

    The NUL delimiter is not decoration: without it ["ab", "c"] and ["a", "bc"]
    hash alike, and two different questions would share one cached answer. The
    embedding cache learned this the same way.
    """
    h = hashlib.sha256()
    h.update(CACHE_VERSION.encode())
    for part in parts:
        h.update(part.encode("utf-8", errors="replace"))
        h.update(b"\x00")
    return h.hexdigest()


def sentiment_key(model_name: str, text: str) -> str:
    """Sentiment depends on the response and the model. Nothing else."""
    return _digest("sentiment", model_name, text)


def zero_shot_key(
    model_name: str, text: str, labels: Sequence[str], multi_label: bool,
) -> str:
    """One label's key, or the whole set's, depending on the mode.

    Pass a single-element `labels` for the `multi_label=True` case and the full
    candidate set for the False one. The mode is in the key regardless, so the
    two families can never collide even on a one-label run.
    """
    mode = "multi" if multi_label else "softmax"
    return _digest("zero_shot", model_name, mode, *labels, text)


class InferenceCache:
    """Model outputs keyed by response, held in one SQLite file.

    Every failure mode here is a *miss*, never an exception. A cache that can
    take a run down is worse than no cache: the analyst did not ask for it, it
    is invisible when it works, and a corrupt file on a laptop that lost power
    mid-write must cost a recomputation rather than an afternoon.
    """

    def __init__(self, path: Path):
        self.path = Path(path)
        self._conn: Optional[sqlite3.Connection] = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(self.path))
            self._conn.execute(_SCHEMA)
            self._conn.commit()
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Inference cache unavailable (%s); running uncached.", exc)
            self._conn = None

    @property
    def enabled(self) -> bool:
        return self._conn is not None

    def get_many(self, keys: Sequence[str]) -> Dict[str, Any]:
        """Whatever of `keys` is already known. Missing keys are simply absent."""
        if self._conn is None or not keys:
            return {}
        found: Dict[str, Any] = {}
        try:
            # Chunked because SQLite caps host parameters (999 on older builds),
            # and a 5,000-response run asks for 30,000 keys at once.
            for start in range(0, len(keys), 500):
                chunk = list(keys[start:start + 500])
                placeholders = ",".join("?" * len(chunk))
                rows = self._conn.execute(
                    f"SELECT key, value FROM entries WHERE key IN ({placeholders})",
                    chunk,
                ).fetchall()
                for key, value in rows:
                    try:
                        found[key] = json.loads(value)
                    except json.JSONDecodeError:
                        continue  # a torn row is a miss
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Cache read failed (%s); treating as empty.", exc)
            return {}
        return found

    def put_many(self, kind: str, items: Iterable[Tuple[str, Any]]) -> int:
        """Store results and commit. Returns how many were written.

        The commit is the point. Deferring it to the end of the stage would
        reproduce exactly the defect this module exists to fix: an interrupted
        two-hour run that saved nothing.
        """
        if self._conn is None:
            return 0
        payload = [(key, kind, json.dumps(value)) for key, value in items]
        if not payload:
            return 0
        try:
            self._conn.executemany(
                "INSERT OR REPLACE INTO entries (key, kind, value) VALUES (?, ?, ?)",
                payload,
            )
            self._conn.commit()
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Cache write failed (%s); continuing uncached.", exc)
            return 0
        return len(payload)

    def count(self) -> int:
        if self._conn is None:
            return 0
        try:
            return int(self._conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0])
        except Exception:  # noqa: BLE001
            return 0

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            finally:
                self._conn = None

    def __enter__(self) -> "InferenceCache":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()


def open_cache(output_dir: Path, *, enabled: bool = True) -> Optional[InferenceCache]:
    """The cache for a run's output directory, or None when switched off.

    Beside the outputs rather than in a user-wide location, so that erasing a
    project erases its derived data with it — the same placement rule the
    embedding cache follows, for the same reason.
    """
    if not enabled:
        return None
    return InferenceCache(Path(output_dir) / CACHE_FILENAME)


def clear_cache(output_dir: Path) -> bool:
    """Delete a run's inference cache. True if a file was removed.

    Wholesale, not row by row: the keys are hashes, so there is no way to find
    the entries belonging to one respondent without the respondent's text —
    which is the thing erasure is removing.
    """
    path = Path(output_dir) / CACHE_FILENAME
    try:
        if path.exists():
            path.unlink()
            return True
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("Could not delete inference cache (%s).", exc)
    return False


def plan_zero_shot(
    texts: Sequence[str],
    labels: Sequence[str],
    model_name: str,
    multi_label: bool,
    cached: Dict[str, Any],
) -> Tuple[List[Dict[str, float]], List[Tuple[int, List[str]]]]:
    """Split a zero-shot job into what is already known and what must be run.

    Returns the per-response scores recovered from the cache (a dict per text,
    possibly partial), and the work outstanding as `(text_index, labels)` pairs.

    Under `multi_label=True` the outstanding labels are per response, so adding
    a seventh label to a six-label codebook costs one label's work rather than
    seven. Under `multi_label=False` a response is all-or-nothing, because its
    scores are normalised across the whole candidate set.
    """
    known: List[Dict[str, float]] = []
    outstanding: List[Tuple[int, List[str]]] = []

    for index, text in enumerate(texts):
        if multi_label:
            have: Dict[str, float] = {}
            missing: List[str] = []
            for label in labels:
                key = zero_shot_key(model_name, text, [label], True)
                if key in cached:
                    have[label] = float(cached[key])
                else:
                    missing.append(label)
            known.append(have)
            if missing:
                outstanding.append((index, missing))
        else:
            key = zero_shot_key(model_name, text, labels, False)
            if key in cached:
                known.append({str(k): float(v) for k, v in cached[key].items()})
            else:
                known.append({})
                outstanding.append((index, list(labels)))

    return known, outstanding


def as_result(text: str, scores: Dict[str, float]) -> Dict[str, Any]:
    """Rebuild the shape a Hugging Face zero-shot pipeline returns.

    Descending by score, because that ordering is part of the contract every
    caller downstream reads (`item["labels"][0]` is the top label), and a cached
    result that arrived in a different order would change coding decisions
    without changing a single score.
    """
    ordered = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    return {
        "sequence": text,
        "labels": [label for label, _ in ordered],
        "scores": [float(score) for _, score in ordered],
    }
