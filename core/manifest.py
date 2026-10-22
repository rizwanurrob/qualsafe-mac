#!/usr/bin/env python
"""
Audit manifest (v3, Phase 6).

Every run writes a `run_manifest.json` recording exactly how the outputs were
produced — package version, mode, engine, model, thresholds, counts, timestamp,
and what was exported. This is the FERPA/IRB audit trail promised in the handoff
(§13): it is written unconditionally from `run_pipeline`, so it exists for CLI and
Streamlit runs alike, regardless of whether the optional project store was saved.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Union

from core.offline import is_offline_enforced, local_mode_status

PACKAGE_VERSION = "4.13.0"

PRIVACY_NOTE = (
    "All processing was local. No survey/interview text left this machine. "
    "Runtime network access to model hubs is disabled (Hugging Face offline mode); "
    "model downloads occur only in the explicit, separate setup step "
    "(tools/download_models.py). Local LLM inference runs against Ollama on "
    "localhost. The analyzed content is never transmitted."
)


def _input_filename(file_path: Any) -> Optional[str]:
    """The input file's name, with the directories that led to it removed.

    Split on both separators rather than with `PurePath`, because a manifest may
    be read on a platform other than the one that wrote it.
    """
    if not file_path:
        return file_path
    return str(file_path).replace("\\", "/").rsplit("/", 1)[-1].strip()


def write_run_manifest(
    output_dir: Union[str, Path],
    config: Dict[str, Any],
    run_summary: Dict[str, Any],
    *,
    engine_type: str,
    engine_model: Optional[str],
    mode: str = "survey",
    template_version: Optional[str] = None,
) -> Path:
    """Write run_manifest.json into output_dir and return its path."""
    input_cfg = config.get("input", {}) or {}
    output_cfg = config.get("output", {}) or {}
    prep_cfg = config.get("preprocessing", {}) or {}
    pipeline_cfg = config.get("pipeline", {}) or {}
    strict_cfg = (config.get("zero_shot", {}) or {}).get("strict_coding", {}) or {}

    from core.project import SCHEMA_VERSION

    manifest = {
        "package_version": PACKAGE_VERSION,
        # The store format this run wrote. Knowing the package version is not
        # enough to know whether an install can open the project: a store from a
        # newer schema raises SchemaTooNewError rather than degrading, so the
        # number a person needs in order to reproduce a run is this one.
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "mode": mode,
        "engine": engine_type,
        "model": engine_model,
        "template_version": template_version,
        "input": {
            # The file's name, not the path it lived at. A run manifest is
            # written into every output folder and travels with it -- to a
            # supervisor, a co-author, a submission -- and an absolute path
            # carries the analyst's username and folder structure to all of
            # them. That is the same leak store format v6 closed in the `.qnw`,
            # one artifact over, and nothing reads this field back either.
            #
            # Provenance survives: the name says which file, and the run
            # directory holds the snapshot of exactly what was analysed, which
            # is a better record than a path that may since have moved.
            "file": _input_filename(input_cfg.get("file_path")),
            "text_column": input_cfg.get("text_column"),
            "descriptor_columns": input_cfg.get("descriptor_columns", []) or [],
        },
        "thresholds": {
            "strict_coding_enabled": bool(strict_cfg.get("enabled", False)),
            # The effective pair the gate actually used (per-engine overlay already
            # applied in run_pipeline), so the manifest records the right numbers
            # for whichever engine ran.
            "top1_min_score": strict_cfg.get("top1_min_score"),
            "min_margin_over_second": strict_cfg.get("min_margin_over_second"),
            "strict_thresholds_by_engine": config.get("strict_thresholds"),
        },
        "counts": {
            "total_responses": run_summary.get("total_responses"),
            "unique_response_texts": run_summary.get("unique_response_texts"),
            "clusters_found": run_summary.get("clusters_found"),
            "questions_total": run_summary.get("questions_total"),
            "questions_coded": run_summary.get("questions_coded"),
        },
        # Both of these change results on identical input, so an audit trail that
        # omitted them could not explain why two runs disagreed.
        "preprocessing": {
            "drop_duplicates": bool(prep_cfg.get("drop_duplicates", False)),
            "min_chars": prep_cfg.get("min_chars"),
            "dedupe_embeddings": bool(pipeline_cfg.get("dedupe_embeddings", False)),
            # Unit of analysis (v4). Agreement/co-occurrence computed at different
            # units are NOT comparable, so it's recorded here for every run.
            "unit": str(config.get("unit", "response")),
        },
        "exports": {
            "output_dir": str(output_dir),
            "exported_raw_text": True,  # responses_scored.csv includes raw response text
            "exported_embeddings": bool(output_cfg.get("save_embeddings", False)),
            "project_store": run_summary.get("project_store"),
        },
        # Recorded, not asserted: an auditor can see whether the offline flags were
        # actually active for this run instead of trusting the note below.
        "local_mode": {
            "offline_enforced": is_offline_enforced(),
            "env": local_mode_status(),
            "pii_masking_applied": bool(run_summary.get("pii_masking_applied", False)),
            "pii_pseudonymised": bool(run_summary.get("pii_pseudonymised", False)),
        },
        "privacy_note": PRIVACY_NOTE,
    }
    path = Path(output_dir) / "run_manifest.json"
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return path
