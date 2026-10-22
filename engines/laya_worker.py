#!/usr/bin/env python
"""
Runs INSIDE Laya's isolated environment. Never imported by the main app.

The `laya` package (PyPI, `convaiinnovations/laya`) needs transformers 5.x and
torch 2.14 (per its published requirements). QualSafe's own engine is pinned to
transformers<5 and torch<3 specifically so the existing zero-shot/sentiment
pipeline stays byte-identical run to run -- that guarantee is load-bearing
throughout this codebase (kappa reproducibility, the manifest's provenance
claims, the whole test suite's determinism). `pip install`ing `laya` into the
same environment as the existing engine would silently upgrade transformers,
torch and (very likely) numpy under it. So this script is the ENTIRE surface
that ever imports `laya` -- it runs under a separate interpreter
(`core/venv_isolation.py`-style venv, see `engines/laya_setup.py`), talks to the
main process over stdin/stdout, and nothing else in this codebase imports this
module or `laya` directly. Mirrors why `core/model_manager.py` shells out to
`tools/download_models.py` in a subprocess rather than downloading in-process.

Protocol (JSON Lines over stdio, defined here -- not Laya's own, since Laya's
undocumented wire format for `pip install "laya[server]"`'s HTTP mode was not
verified and this project does not build against an unverified API):

    -> {"state": {"text": "..."}, "questions": {"q1": {"type": "noul", ...}, ...}}
    <- {"ok": true, "answers": {"q1": {"noul": 0.83, "confidence": 0.71}, ...}}
    <- {"ok": false, "error": "..."}

One JSON object per line each direction. `--preload` keeps the router resident
across requests (this is the whole point of running as a long-lived worker
rather than one process per response: the model load is the expensive part).

**UNVERIFIED.** Built from Laya's published docs and README (see
docs/ALT_SURVEY_FLOW_PLAN.md, "What Laya actually is" and its sources), not
against an installed copy -- installing it here, even in a throwaway venv,
risked no isolation boundary existing yet to install it correctly INTO. The one
call this script makes -- `laya.Router(preload=True).predict(state, questions)`
-- is the piece of the docs most consistently described across independent
sources; everything else here (error handling, the stdio framing) is this
project's own code and needs no verification against Laya at all. The first
real run against an installed `laya` (tracked in the plan doc) is expected to
need small fixes here, not a redesign.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from typing import Any, Dict


def _respond(obj: Dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="convaiinnovations/laya",
                        help="Hub checkpoint to load (default: the English checkpoint).")
    parser.add_argument("--subfolder", default=None,
                        help="'multilingual' or 'typed-decisions', for the other checkpoints.")
    args = parser.parse_args(argv)

    # The model is downloaded once, on purpose, by tools/setup_laya_env.py. Coding
    # never reaches the network: offline unless the person set otherwise.
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

    try:
        import laya  # noqa: F401  -- only ever imported here, inside the isolated venv
    except ImportError as exc:
        _respond({"ok": False, "error": f"laya is not installed in this environment: {exc}",
                  "fatal": True})
        return 1

    try:
        # One checkpoint only. `laya.Router(preload=True)` loads all three (about 1.16
        # billion parameters) and wants the two this tool never uses.
        agent = laya.load(args.model, subfolder=args.subfolder, device="cpu")
    except Exception as exc:  # noqa: BLE001 - report, don't crash the worker before it starts
        _respond({"ok": False, "error": f"failed to load Laya: {exc}", "fatal": True})
        return 1

    _respond({"ok": True, "ready": True})

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        if line == "__SHUTDOWN__":
            return 0
        try:
            request = json.loads(line)
            state = request["state"]
            questions = request["questions"]
        except (json.JSONDecodeError, KeyError) as exc:
            _respond({"ok": False, "error": f"malformed request: {exc}"})
            continue

        try:
            result = agent.predict(state, questions)
            _respond({"ok": True, "answers": result.get("answers", result)})
        except Exception as exc:  # noqa: BLE001 - one bad item must not kill the worker
            _respond({"ok": False, "error": str(exc), "traceback": traceback.format_exc()})

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
