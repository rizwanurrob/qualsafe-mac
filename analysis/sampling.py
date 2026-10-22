#!/usr/bin/env python
"""
Coding-sample selection (v3.2, Phase 2.1).

Which responses an analyst is asked to hand-code, and in what order, is a
methodological decision, not a UI detail — so the logic lives here as pure,
tested functions rather than inline in the workflow.

Two strategies:

- **Round 0 (no model yet): cluster-stratified random.** Pure random can miss
  whole regions of the response space on a small sample. Sampling proportionally
  across the unsupervised clusters spreads the seed set over the space so the
  first model sees the range of themes.
- **Later rounds: uncertainty-ordered.** Once a model exists, the most
  informative items to label next are the ones it is least sure about (active
  learning). Per row, uncertainty is `min_over_labels |p - 0.5|` — small when some
  label sits right on the fence.

**The caveat that must travel with this** (see `SAMPLING_CAVEATS`): the moment a
sample is uncertainty-selected it is no longer random, so (a) inter-rater
agreement computed on it is computed on a deliberately hard subset and will look
*worse* than agreement over the whole corpus, and (b) label prevalence estimated
from it is biased. Both are fine — as long as they are stated. A defensible method
discloses its sampling; a reviewer landmine hides it. The UI and run report must
print these whenever uncertainty sampling was used, which is why the strings are
defined here next to the code that earns them.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence

import numpy as np

SAMPLING_CAVEATS = {
    "uncertainty": (
        "This sample was selected by model uncertainty, not at random. Two "
        "consequences to report alongside any statistic from it: (1) inter-rater "
        "agreement (kappa) is computed over a deliberately hard subset, so it "
        "UNDERSTATES agreement over the full corpus; (2) label prevalence estimated "
        "from this sample is biased toward the uncertain region and should not be "
        "read as a population estimate."
    ),
    "stratified": (
        "This seed sample was drawn randomly but stratified across the discovered "
        "clusters, so every region of the response space is represented. Prevalence "
        "estimates from a stratified sample are still approximately unbiased."
    ),
    "random": (
        "This sample was drawn at random, so agreement and prevalence estimated "
        "from it are unbiased (within sampling error)."
    ),
}


def row_uncertainty(probabilities: Dict[str, float]) -> float:
    """Uncertainty of one row's multi-label prediction: min |p - 0.5| over labels.

    Small = at least one label sits on the decision boundary (most informative to
    label next). An empty/degenerate prediction is maximally uncertain (0.0) so it
    surfaces for review rather than hiding at the bottom.
    """
    if not probabilities:
        return 0.0
    return min(abs(float(p) - 0.5) for p in probabilities.values())


def order_ids_by_uncertainty(
    prob_by_id: Dict[str, Dict[str, float]],
    *,
    already_coded: Optional[Sequence[str]] = None,
) -> List[str]:
    """Order response ids most-uncertain first, skipping already-coded items."""
    coded = set(already_coded or [])
    candidates = [(rid, row_uncertainty(probs)) for rid, probs in prob_by_id.items()
                  if rid not in coded]
    # Stable tie-break on id keeps the order deterministic run-to-run.
    candidates.sort(key=lambda t: (t[1], t[0]))
    return [rid for rid, _ in candidates]


def stratified_sample_indices(
    cluster_labels: Sequence[int],
    n: int,
    *,
    random_state: int = 42,
) -> List[int]:
    """Pick `n` row indices spread proportionally across clusters.

    Allocates each cluster a share of `n` proportional to its size (largest-
    remainder rounding so the parts sum to exactly n), then samples without
    replacement within each cluster. Falls back gracefully when a cluster is
    smaller than its allocation.
    """
    labels = np.asarray(list(cluster_labels))
    total = len(labels)
    n = min(n, total)
    if n <= 0:
        return []

    rng = np.random.default_rng(random_state)
    unique = sorted(set(labels.tolist()))

    # Proportional allocation with largest-remainder rounding.
    sizes = {c: int(np.sum(labels == c)) for c in unique}
    raw = {c: n * sizes[c] / total for c in unique}
    alloc = {c: int(np.floor(raw[c])) for c in unique}
    remainder = n - sum(alloc.values())
    # Hand out the leftover to the largest fractional parts.
    for c in sorted(unique, key=lambda c: raw[c] - alloc[c], reverse=True)[:remainder]:
        alloc[c] += 1

    chosen: List[int] = []
    leftover_pool: List[int] = []
    for c in unique:
        idx = np.where(labels == c)[0]
        rng.shuffle(idx)
        take = min(alloc[c], len(idx))
        chosen.extend(idx[:take].tolist())
        leftover_pool.extend(idx[take:].tolist())

    # If some clusters were too small to fill their allocation, top up from the
    # rest so we still return exactly n.
    if len(chosen) < n and leftover_pool:
        rng.shuffle(leftover_pool)
        chosen.extend(leftover_pool[: n - len(chosen)])

    chosen.sort()
    return chosen[:n]
