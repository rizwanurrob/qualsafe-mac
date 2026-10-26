#!/usr/bin/env python
"""
One-time model setup — the only part of this tool that downloads anything.

Analysis runs are pinned to the local model cache (see `core/offline.py`), so the
models have to be fetched once, deliberately, by this script. Splitting
acquisition from use is what lets the tool state plainly that analyzing your data
touches no network at all.

This downloads *model weights* from Hugging Face. It does not upload anything:
your survey and interview text is never involved in this step, and this script
does not read your data files.

Usage
-----
    python tools/download_models.py                      # defaults from config.example.yaml
    python tools/download_models.py --config config/my_project.yaml
    python tools/download_models.py --check              # report cache status, download nothing
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.engine_install import activate as _activate_engine  # noqa: E402

_activate_engine()          # the engine may be in the per-user folder, not the program's own packages

from core.offline import (  # noqa: E402
    enforce_local_mode,
    human_size,
    model_cache_status,
)

# Fallbacks match config/config.example.yaml. Kept here so `--check` works before
# a user has written their own config.
DEFAULT_MODELS = {
    "embedding_model": "sentence-transformers/all-MiniLM-L6-v2",
    "sentiment_model": "distilbert/distilbert-base-uncased-finetuned-sst-2-english",
    "zero_shot_model": "facebook/bart-large-mnli",
}


def models_from_config(config_path: Path) -> Dict[str, str]:
    """Read the three model names out of a pipeline config, filling gaps with defaults."""
    import yaml

    models = dict(DEFAULT_MODELS)
    if config_path.exists():
        data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        configured = (data.get("models") or {}) if isinstance(data, dict) else {}
        for key in DEFAULT_MODELS:
            if configured.get(key):
                models[key] = str(configured[key])
    return models


def report_status(models: Dict[str, str]) -> List[Dict[str, object]]:
    """Print per-model cache status; return the raw rows."""
    rows = model_cache_status(sorted(set(models.values())))
    print("\nModel cache status")
    print("-" * 70)
    for row in rows:
        if row["cached"] is None:
            mark, detail = "?", row["detail"]
        elif row["cached"]:
            mark, detail = "OK", f"{human_size(float(row['size_bytes']))} — {row['detail']}"
        else:
            mark, detail = "--", "not downloaded"
        print(f"  [{mark:>2}] {row['model']}")
        print(f"       {detail}")
    print("-" * 70)
    return rows


def download_one(model: str, role: str) -> None:
    """Fetch a single model for a specific role, using the right loader.

    Role drives the loader (not a guess from the model's name), so any model can
    be downloaded for the role it's meant for — a custom NLI zero-shot model, a
    different sentiment classifier, an alternative embedding model. Loading the
    model here also doubles as a smoke check that it can be constructed for its
    role: a model that can't be used that way fails here, with a clear message,
    rather than mid-analysis.

    Runs in this process only (the offline flags lifted here die with it), so the
    app that shells out to this script stays offline-pinned.
    """
    enforce_local_mode(allow_downloads=True)
    if role == "embedding":
        from sentence_transformers import SentenceTransformer

        SentenceTransformer(model, device="cpu")   # a download needs the weights, not the GPU
    elif role == "sentiment":
        from transformers import pipeline

        pipeline("sentiment-analysis", model=model, truncation=True)
    elif role == "zero-shot":
        from transformers import pipeline

        pipeline("zero-shot-classification", model=model, truncation=True)
    else:
        raise ValueError(f"Unknown role: {role!r} (expected embedding|sentiment|zero-shot).")


def download(models: Dict[str, str]) -> int:
    """Fetch each model into the local cache. Returns a process exit code."""
    # This is the one place the offline flags are lifted, and it runs as its own
    # process — the analysis entry points can never reach this state, because env
    # vars set here die with this script.
    enforce_local_mode(allow_downloads=True)

    failures: List[str] = []

    embedding_model = models["embedding_model"]
    print(f"\n[1/3] Embedding model: {embedding_model}")
    try:
        from sentence_transformers import SentenceTransformer

        SentenceTransformer(embedding_model, device="cpu")
        print("      done.")
    except Exception as exc:  # noqa: BLE001 - report and continue to the next model
        failures.append(f"{embedding_model}: {exc}")
        print(f"      FAILED: {exc}")

    from transformers import pipeline

    for step, (key, task) in enumerate(
        (("sentiment_model", "sentiment-analysis"), ("zero_shot_model", "zero-shot-classification")),
        start=2,
    ):
        name = models[key]
        print(f"\n[{step}/3] {task}: {name}")
        try:
            pipeline(task, model=name, truncation=True)
            print("      done.")
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{name}: {exc}")
            print(f"      FAILED: {exc}")

    if failures:
        print("\nSome models did not download:")
        for line in failures:
            print(f"  - {line}")
        print("\nCheck your internet connection and re-run. If you are behind a proxy,")
        print("set HTTPS_PROXY in your environment first.")
        return 1

    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Download the models this tool uses (one-time; requires internet)."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=PROJECT_ROOT / "config" / "config.example.yaml",
        help="Pipeline config to read model names from.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Only report cache status; download nothing.",
    )
    parser.add_argument(
        "--model", default=None,
        help="Download a single model repo id (requires --role). The in-app Model "
             "Manager uses this so the app itself never lifts offline mode.",
    )
    parser.add_argument(
        "--role", choices=["embedding", "sentiment", "zero-shot"], default=None,
        help="The role the --model is for; drives which loader is used.",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Emit a single machine-readable JSON result line (for the app).",
    )
    args = parser.parse_args(argv)

    # Single-model, role-explicit path (the in-app Model Manager's engine).
    if args.model or args.role:
        if not (args.model and args.role):
            parser.error("--model and --role must be given together.")
        result = {"ok": True, "model": args.model, "role": args.role, "error": ""}
        try:
            download_one(args.model, args.role)
        except Exception as exc:  # noqa: BLE001 - report, don't traceback, for the UI
            result["ok"] = False
            result["error"] = str(exc)
        if args.json:
            print(json.dumps(result))
        elif result["ok"]:
            print(f"Downloaded {args.model} ({args.role}).")
        else:
            print(f"FAILED: {result['error']}")
        return 0 if result["ok"] else 1

    models = models_from_config(args.config)

    print("QualSafe — model setup")
    print(f"Config: {args.config}")
    for key, name in models.items():
        print(f"  {key:<16} {name}")

    rows = report_status(models)

    if args.check:
        missing = [r for r in rows if r["cached"] is False]
        if missing:
            print(f"\n{len(missing)} model(s) not downloaded. Run without --check to fetch them.")
            return 1
        print("\nAll models are cached. You can run the tool fully offline.")
        return 0

    if all(r["cached"] for r in rows if r["cached"] is not None):
        print("\nAll models already cached — nothing to download.")
        return 0

    print("\nDownloading missing models. This is a large one-time download")
    print("(~1.6 GB, mostly facebook/bart-large-mnli) and may take several minutes.")
    code = download(models)
    if code == 0:
        report_status(models)
        print("\nSetup complete. Analysis runs will now work with the network off.")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
