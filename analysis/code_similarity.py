#!/usr/bin/env python
"""
Semantic merge suggestions for the codebook (v3.9.6, F1).

The store's merge already reports near-name code pairs, but with a crude
substring/equality test (`core/store_merge._near`): "Cost worry" and "Financial
stress" never match. This computes suggestions from **meaning** instead — cosine
similarity over each code's name + definition, using the same local embedding
model the pipeline already caches (so it stays offline and adds no new download).

Pure and injectable: `similar_code_pairs` takes an `embed_fn`, so tests pass
exact vectors and production wraps the MiniLM cache. Suggestions are just that —
the human confirms every merge on the Codebook page; nothing is ever auto-merged.
"""

from __future__ import annotations

from typing import Any, Callable, List, Optional, Sequence

import numpy as np

# embed_fn: takes a list of strings, returns an (n, d) float array of row vectors.
EmbedFn = Callable[[Sequence[str]], np.ndarray]


def code_text(code: Any) -> str:
    """The text a code is compared on: its name, plus its definition when set.

    Definition is included because two codes can share a name idea but be
    distinguished (or revealed as identical) by how they're defined.
    """
    name = str(getattr(code, "name", "") or "").strip()
    definition = str(getattr(code, "definition", "") or "").strip()
    return f"{name}. {definition}".strip() if definition else name


def similar_code_pairs(
    codes: Sequence[Any],
    embed_fn: EmbedFn,
    *,
    threshold: float = 0.80,
    top_k: Optional[int] = None,
) -> List[dict]:
    """Rank code pairs by cosine similarity of their name+definition text.

    Returns a list of dicts, most-similar first::

        {"code_id_a", "name_a", "code_id_b", "name_b", "similarity"}

    Only pairs at or above ``threshold`` are returned (and never a code with
    itself). ``top_k`` caps the list. Ordering is deterministic: by similarity
    descending, then by the two names, so the UI and tests are stable.
    """
    items = [c for c in codes if str(getattr(c, "name", "") or "").strip()]
    if len(items) < 2:
        return []

    vecs = np.asarray(embed_fn([code_text(c) for c in items]), dtype=float)
    if vecs.ndim != 2 or vecs.shape[0] != len(items):
        raise ValueError("embed_fn must return one row vector per code.")
    # Normalize so a dot product is cosine similarity; guard zero-length vectors.
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    unit = vecs / norms
    sim = unit @ unit.T

    pairs: List[dict] = []
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            score = float(sim[i, j])
            if score >= threshold:
                pairs.append({
                    "code_id_a": items[i].code_id, "name_a": items[i].name,
                    "code_id_b": items[j].code_id, "name_b": items[j].name,
                    "similarity": round(score, 4),
                })
    pairs.sort(key=lambda p: (-p["similarity"], p["name_a"].lower(), p["name_b"].lower()))
    return pairs[:top_k] if top_k else pairs


def embed_with_model(texts: Sequence[str], model_name: str) -> np.ndarray:
    """Production `embed_fn`: encode with the cached local embedding model.

    Imported lazily so `analysis/` stays torch-free to import (the test suite and
    the light CI never load this path). Runs offline — the model is read from the
    local cache like the rest of the pipeline.
    """
    from analyze_survey import build_embeddings

    return build_embeddings(list(texts), model_name, batch_size=32,
                            normalize_embeddings=True, dedupe=False)
