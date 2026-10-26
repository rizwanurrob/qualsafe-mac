#!/usr/bin/env python
"""
In-app model management (v3.9.7, F4).

The tool's core promise is that analysis touches no network. Model *acquisition*
is therefore kept structurally separate from model *use*: this module downloads
models by **shelling out to `tools/download_models.py` in a subprocess**, so the
running Streamlit/analysis process never has the Hugging Face offline flags
lifted. (The earlier in-app downloader popped `HF_HUB_OFFLINE` in-process and
restored it in a `finally` — a weaker guarantee this replaces.)

Downloads are role-explicit — the caller says whether a model is the embedding,
sentiment, or zero-shot model — so any model can be fetched for the role it's
meant for, not just the three defaults, and the loader that a role implies also
smoke-checks that the model can be constructed for it.

Cache *status* is read in-process by `core.offline.model_cache_status` (scanning
the cache needs no network); only downloads and removals live here.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Callable, Dict, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DOWNLOAD_SCRIPT = PROJECT_ROOT / "tools" / "download_models.py"

ROLES = ("embedding", "sentiment", "zero-shot")

DEFAULT_MODELS: Dict[str, str] = {
    "embedding": "sentence-transformers/all-MiniLM-L6-v2",
    "sentiment": "distilbert/distilbert-base-uncased-finetuned-sst-2-english",
    "zero-shot": "facebook/bart-large-mnli",
}

ROLE_LABELS: Dict[str, str] = {
    "embedding": "Embedding (clustering & similarity)",
    "sentiment": "Sentiment",
    "zero-shot": "Zero-shot themes (coding)",
}

# What kind of model each role needs — shown in the UI so an analyst doesn't set,
# say, a plain classifier as the zero-shot (NLI) model.
ROLE_GUIDANCE: Dict[str, str] = {
    "embedding": "Any sentence-transformers embedding model.",
    "sentiment": "A text-classification model (e.g. an SST-2 sentiment model).",
    "zero-shot": "An NLI / MNLI model (used for zero-shot classification).",
}

# Session-state key that holds the selected model for each role.
ROLE_SESSION_KEY: Dict[str, str] = {
    "embedding": "adv_embedding_model",
    "sentiment": "adv_sentiment_model",
    "zero-shot": "adv_zero_shot_model",
}


def _parse_json_line(text: str) -> Optional[dict]:
    """Return the last JSON object printed on stdout, or None."""
    for line in reversed((text or "").splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                return json.loads(line)
            except Exception:  # noqa: BLE001
                continue
    return None


def download_model(
    repo_id: str,
    role: str,
    *,
    python_exe: Optional[str] = None,
    script_path: Optional[Path] = None,
    timeout: Optional[float] = 3600,
) -> dict:
    """Download one model for a role, in a subprocess. Returns a result dict.

    ``{"ok": bool, "message": str, "model": str, "role": str}``. Never raises for
    a download failure — the message carries the reason so the UI can show it. The
    subprocess is the point: this process's offline flags are never touched, so a
    download can't leave analysis able to reach the hub.
    """
    if role not in ROLES:
        raise ValueError(f"Unknown role: {role!r} (expected one of {ROLES}).")
    repo_id = (repo_id or "").strip()
    if not repo_id:
        return {"ok": False, "message": "No model id given.", "model": "", "role": role}

    cmd = [
        python_exe or sys.executable,
        str(script_path or DOWNLOAD_SCRIPT),
        "--model", repo_id, "--role", role, "--json",
    ]
    # This process runs offline (the program arms it at start-up), and a child inherits that. A download has
    # to reach the hub, so the child is started without the offline flags; this process's own are untouched.
    from core.offline import OFFLINE_VARS

    child_env = {k: v for k, v in os.environ.items() if k not in OFFLINE_VARS}
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=child_env)
    except subprocess.TimeoutExpired:
        return {"ok": False, "message": f"Download timed out after {timeout}s.",
                "model": repo_id, "role": role}
    except Exception as exc:  # noqa: BLE001 - e.g. the interpreter/script is missing
        return {"ok": False, "message": f"Could not start download: {exc}",
                "model": repo_id, "role": role}

    result = _parse_json_line(proc.stdout)
    if result is None:
        tail = (proc.stderr or proc.stdout or "").strip()
        tail = tail[-500:] if tail else f"exited with code {proc.returncode}"
        return {"ok": False, "message": f"Download failed: {tail}",
                "model": repo_id, "role": role}

    ok = bool(result.get("ok"))
    return {
        "ok": ok,
        "message": "Downloaded and ready." if ok else (result.get("error") or "Download failed."),
        "model": repo_id,
        "role": role,
    }


def remove_from_cache(repo_id: str) -> int:
    """Delete a model from the local Hugging Face cache. Returns bytes freed.

    Best-effort: an unknown repo id frees nothing (returns 0) rather than raising.
    """
    from huggingface_hub import scan_cache_dir

    cache = scan_cache_dir()
    freed = 0
    revisions = []
    for repo in cache.repos:
        if repo.repo_id == repo_id:
            freed += int(repo.size_on_disk)
            revisions.extend(rev.commit_hash for rev in repo.revisions)
    if revisions:
        cache.delete_revisions(*revisions).execute()
    return freed


def configured_role_models(get: Callable[[str, str], str]) -> Dict[str, str]:
    """Map each role to its currently selected model, via a session getter.

    ``get(key, default)`` mirrors ``st.session_state.get``; kept here (not in the
    UI) so the role→model resolution has one home the tests can exercise.
    """
    return {role: get(ROLE_SESSION_KEY[role], DEFAULT_MODELS[role]) for role in ROLES}
