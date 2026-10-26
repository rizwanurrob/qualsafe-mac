#!/usr/bin/env python
"""
Local-mode enforcement (v3.1.1).

The tool promises that survey and interview text never leaves the machine. Until
now that promise rested on the fact that we never *wrote* code to send it
anywhere — but the Hugging Face stack will happily reach out to the model hub at
runtime (to check for model updates, or to fetch a model that isn't cached), and
it phones home telemetry by default. Nothing there transmits response text, but
"we didn't write that call" is a weaker guarantee than "the network is off," and
an audit should not have to take our word for it.

This module makes the guarantee structural: model *acquisition* is a separate,
explicit, user-initiated step (`tools/download_models.py`), and model *use* runs
with the hub pinned to the local cache.

Call `enforce_local_mode()` at the top of every entry point, before any
transformers / sentence-transformers import executes. `analyze_survey` defers
those imports to first use precisely so this ordering is achievable.

Ollama is deliberately unaffected: it is a localhost HTTP service, not a hub
client, and gating it here would break the local LLM engine for no privacy gain.
"""

from __future__ import annotations

import os
from typing import Dict, List

# The env vars this module manages. HF_HUB_OFFLINE and TRANSFORMERS_OFFLINE are
# the two halves of "don't touch the network" (hub-level and library-level); the
# other two disable telemetry and implicit token use even during downloads.
OFFLINE_VARS = ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE")
ALWAYS_VARS = ("HF_HUB_DISABLE_TELEMETRY", "HF_HUB_DISABLE_IMPLICIT_TOKEN")


def enforce_local_mode(allow_downloads: bool = False) -> None:
    """Pin the HF stack to the local cache. Call before importing transformers.

    Parameters
    ----------
    allow_downloads : bool
        When True, telemetry stays off but the offline flags are not set, so the
        hub can be reached. Only the dedicated model-setup tool passes True; the
        analysis entry points never do.

    Uses ``setdefault`` throughout so a user on a corporate proxy (or anyone with
    a deliberate reason) can override any of these from their own environment
    without editing the tool.
    """
    for var in ALWAYS_VARS:
        os.environ.setdefault(var, "1")
    if allow_downloads:
        # The program arms offline mode in its own environment, and a download is started from it as a child
        # process that inherits that environment. Not setting the flags is not enough: they have to be
        # removed, or the hub refuses with "We couldn't connect to 'https://huggingface.co'" (found on a
        # student's Mac). Only the explicit model-download step passes True.
        for var in OFFLINE_VARS:
            os.environ.pop(var, None)
    else:
        for var in OFFLINE_VARS:
            os.environ.setdefault(var, "1")


def local_mode_status() -> Dict[str, str]:
    """Return the current value of each managed env var (for manifests/UI)."""
    return {var: os.environ.get(var, "") for var in (*ALWAYS_VARS, *OFFLINE_VARS)}


def is_offline_enforced() -> bool:
    """True when both offline flags are active."""
    return all(os.environ.get(var) == "1" for var in OFFLINE_VARS)


def model_cache_status(model_names: List[str]) -> List[Dict[str, object]]:
    """Report whether each model appears in the local Hugging Face cache.

    Returns one dict per model: ``{"model", "cached", "size_bytes", "detail"}``.
    Best-effort by design — this drives an advisory UI panel, so a cache we can't
    read reports "unknown" rather than raising and blocking the page.
    """
    results: List[Dict[str, object]] = []
    try:
        from huggingface_hub import scan_cache_dir

        cache = scan_cache_dir()
        by_id = {repo.repo_id: repo for repo in cache.repos}
    except Exception as exc:  # noqa: BLE001 - advisory panel must not crash
        if type(exc).__name__ == "CacheNotFound":
            # A fresh machine (a new Mac, say) has no cache folder yet: that means nothing is downloaded, not a fault.
            return [
                {"model": name, "cached": False, "size_bytes": 0, "detail": "not downloaded"}
                for name in model_names
            ]
        return [
            {"model": name, "cached": None, "size_bytes": 0, "detail": f"cache unreadable: {exc}"}
            for name in model_names
        ]

    for name in model_names:
        repo = by_id.get(name)
        if repo is None:
            results.append(
                {"model": name, "cached": False, "size_bytes": 0, "detail": "not downloaded"}
            )
        else:
            results.append(
                {
                    "model": name,
                    "cached": True,
                    "size_bytes": int(repo.size_on_disk),
                    "detail": str(repo.repo_path),
                }
            )
    return results


def human_size(num_bytes: float) -> str:
    """Format a byte count for display (cache panel, download progress)."""
    for unit in ("B", "KB", "MB", "GB"):
        if abs(num_bytes) < 1024.0:
            return f"{num_bytes:3.1f} {unit}"
        num_bytes /= 1024.0
    return f"{num_bytes:.1f} TB"
