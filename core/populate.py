#!/usr/bin/env python
"""
Populate a `.qnw` project store from a completed survey run (v3, Phase 0b wiring).

This maps the survey pipeline's per-response DataFrame onto the shared project
model: each response becomes a Source with a whole-response Excerpt; designated
descriptor columns become Descriptors; the analyst's zero-shot labels become
a-priori Codes; and confident (strict-gated, or top-label) theme assignments
become CodeApplications tagged with the transformer Rater and this RunManifest.

It is called from run_pipeline only when `output.project_store_path` is set, so
default runs are unaffected (CSV outputs stay byte-identical). Sentiment and
cluster id are recorded on the Source metadata (sentiment stays a separate
attribute per the design decision, not folded into a code weight).
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import pandas as pd

# The one definition, not a local copy. This module used to declare its own
# PACKAGE_VERSION = "3.0.0-dev" and write it into the Run row of every survey
# run — so the store's own provenance named a version that had not existed for
# four releases, while interview/populate.py (which imports this) recorded the
# real one. The version a project says produced it has to come from one place.
from core.manifest import PACKAGE_VERSION


def _clean_scalar(value: Any) -> Any:
    """Coerce numpy/pandas scalars to JSON-serializable Python types."""
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if hasattr(value, "item"):  # numpy scalar
        try:
            return value.item()
        except Exception:  # noqa: BLE001
            return str(value)
    return value


def populate_project_store(
    work_df: pd.DataFrame,
    config: Dict[str, Any],
    store_path: Union[str, Path],
    *,
    engine: str = "transformer",
) -> str:
    """Add a run's results to the `.qnw` store at `store_path`, creating it if new.

    **Additive** (changed in v3.1.1): the store is the project of record, so it is
    no longer deleted and rebuilt each run. Instead this:

    - opens the existing store if present (migrating its schema if needed);
    - reuses the Source already minted for a response (matched on
      response_id + question_text) rather than inserting a duplicate;
    - reuses a Code that already exists by name rather than creating it twice;
    - tags this run's machine applications with a fresh run_id;
    - runs the whole thing in one transaction, so an interrupted populate leaves
      the store as it was, not half-written.

    Human codes entered in the Labeling Lab live in the same store (see
    core/populate.record_human_codings), so wiping it every run — the old
    behavior — would have destroyed the analyst's own coding on the next run.

    Returns the store path as a string.
    """
    # Local imports keep core/populate importable without the pipeline, and avoid
    # any import-cycle surprises.
    from core.model import (
        Code, CodeApplication, Descriptor, Excerpt, Rater, RunManifest, Source,
    )
    from core.project import Project, new_id

    store_path = Path(store_path)

    input_cfg = config.get("input", {})
    zero_cfg = config.get("zero_shot", {})
    strict_cfg = zero_cfg.get("strict_coding", {}) or {}
    model_cfg = config.get("models", {})

    descriptor_cols: List[str] = [
        c for c in (input_cfg.get("descriptor_columns", []) or []) if c in work_df.columns
    ]
    zero_labels: List[str] = list(zero_cfg.get("labels", []) or [])
    uncertain_label = str(strict_cfg.get("uncertain_label", "UNCERTAIN_REVIEW"))
    zero_shot_model = str(model_cfg.get("zero_shot_model", ""))
    # Unit of analysis (v4): "response" (default) or "sentence". Only affects which
    # excerpts are laid down; machine coding stays response-level.
    unit = str(config.get("unit", "response")).lower()

    has_zshot = "zshot_top_label" in work_df.columns
    has_strict = "zshot_strict_label" in work_df.columns

    with Project.create(store_path) as proj:
        # Everything below lands as one transaction (atomic populate).
        with proj.bulk():
            rater_id = ""
            run_id = ""
            if has_zshot:
                rater_id = proj.add_rater(Rater(
                    rater_id="", kind=engine, name=f"{engine} engine", model_id=zero_shot_model))
                run_id = proj.add_run(RunManifest(
                    run_id="", package_version=PACKAGE_VERSION, mode="survey", engine=engine,
                    model=zero_shot_model,
                    thresholds={k: strict_cfg.get(k) for k in
                                ("top1_min_score", "min_margin_over_second") if k in strict_cfg},
                    counts={"responses": int(len(work_df))},
                    exported_raw_text=True,
                ))

            # Code lookup: match existing codes by name so re-runs don't duplicate
            # the codebook. Seed from the store, then the analyst's a-priori labels.
            code_id_by_label: Dict[str, str] = {}
            for existing in proj.get_codebook():
                code_id_by_label.setdefault(existing.name, existing.code_id)

            def _code_id_for(label: str, origin: str = "a_priori") -> str:
                if label not in code_id_by_label:
                    code_id_by_label[label] = proj.add_code(Code(
                        code_id="", name=label, origin=origin, created_by="human"))
                return code_id_by_label[label]

            for label in zero_labels:
                _code_id_for(label)

            for _, row in work_df.iterrows():
                raw_text = str(row.get("response_text", "") or "")
                response_id = str(row.get("response_id", ""))
                question_text = str(row.get("question_text", "") or "")

                # Reuse the source for this (response_id, question) if it exists,
                # else mint a new one. This is what makes a re-run additive rather
                # than a source explosion.
                existing_source = (
                    proj.find_source_by_response_id(response_id, question=question_text)
                    if response_id else None
                )
                if existing_source is not None:
                    source_id = existing_source.source_id
                    excerpt = _whole_response_excerpt(proj, source_id)
                    excerpt_id = excerpt.excerpt_id if excerpt else proj.add_whole_response_excerpt(
                        Source(source_id=source_id, type="survey_response",
                               raw_text=raw_text, label=question_text, metadata={}))
                else:
                    metadata: Dict[str, Any] = {
                        "response_id": response_id,
                        "question_text": question_text,
                    }
                    # respondent_id (wide-form) groups a person's answers across
                    # questions; kept in metadata so the store can regroup them.
                    if "respondent_id" in work_df.columns:
                        metadata["respondent_id"] = str(row.get("respondent_id", "") or "")
                    for key in ("cluster_id", "sentiment_label", "sentiment_score"):
                        if key in work_df.columns:
                            metadata[key] = _clean_scalar(row.get(key))
                    source = Source(
                        source_id=new_id("src"), type="survey_response",
                        raw_text=raw_text, label=question_text, metadata=metadata,
                    )
                    proj.add_source(source)
                    excerpt_id = proj.add_whole_response_excerpt(source)
                    source_id = source.source_id
                    # v4 sentence unitization: when requested, also lay down
                    # sentence excerpts so finer (human/span) coding is possible.
                    # Machine coding stays on the whole-response excerpt below —
                    # the survey model codes the response, not each sentence.
                    if unit == "sentence":
                        proj.add_sentence_excerpts(source)

                for col in descriptor_cols:
                    proj.set_descriptor(Descriptor(
                        source_id=source_id, key=col,
                        value=str(_clean_scalar(row.get(col)) if row.get(col) is not None else "")))

                if not has_zshot:
                    continue

                # The engine judged this response against every label, whether it
                # applied one or left it uncertain: a complete review (format v8).
                proj.record_coverage(rater_id, [excerpt_id], run_id=run_id or None)

                applied_labels: List[str] = []
                confidence = _clean_scalar(row.get("zshot_top_score"))
                margin: Optional[float] = None
                if has_strict:
                    strict_label = str(row.get("zshot_strict_label", "") or "")
                    confident = bool(row.get("zshot_strict_confident", False))
                    margin = _clean_scalar(row.get("zshot_strict_margin"))
                    if confident and strict_label and strict_label != uncertain_label:
                        applied_labels = [lbl for lbl in strict_label.split("|") if lbl]
                else:
                    top_label = str(row.get("zshot_top_label", "") or "")
                    if top_label:
                        applied_labels = [top_label]

                for label in applied_labels:
                    proj.apply_code(CodeApplication(
                        application_id="", excerpt_id=excerpt_id, code_id=_code_id_for(label),
                        coder=engine, rater_id=rater_id or None, run_id=run_id or None,
                        confidence=confidence, margin=margin))

    return str(store_path)


def import_second_coder_sample(
    store_path: Union[str, Path],
    coding_sample_csv: Union[str, Path],
    *,
    rater_id: str = "human_secondary",
    rater_name: str = "",
    question_text: Optional[str] = None,
    delimiter: str = "|",
) -> Dict[str, int]:
    """Import a colleague's coded `coding_sample.csv` as a second human rater.

    This is the multi-coder groundwork (Phase 2.5): a second person codes the same
    `coding_sample.csv` and their codes enter the store under a distinct rater_id.
    Human-vs-human kappa then falls out of `per_code_kappa` over the two raters'
    `rater_labels`, with no new statistics code.

    Alignment is on `response_id`; the caller is expected to warn the analyst when
    the two coders' item sets don't fully overlap (kappa on the intersection is
    correct but the overlap N must be shown).
    """
    from core.encodings import read_csv_as_text

    # As text, with the encoding fallback: the colleague was told to edit this
    # file in Excel, which saves Windows-1252, and "000123" must stay "000123".
    read = read_csv_as_text(coding_sample_csv)
    df = read.frame
    if "response_id" not in df.columns or "human_labels" not in df.columns:
        raise ValueError("coding_sample.csv must have 'response_id' and 'human_labels' columns.")

    codings: Dict[str, List[str]] = {}
    for _, row in df.iterrows():
        labels = [p.strip() for p in str(row.get("human_labels", "")).split(delimiter) if p.strip()]
        codings[str(row["response_id"]).strip()] = labels

    result = record_human_codings(
        store_path, codings, question_text=question_text,
        rater_id=rater_id, rater_name=rater_name,
    )
    result["encoding"] = read.encoding
    result["encoding_note"] = read.note()
    from core.project import Project

    with Project.open(store_path) as proj:
        proj.log_event("coder_imported", f"Coder imported as {rater_id}",
                       target_type="rater", target_id=rater_id,
                       detail={"responses": result["excerpts"], "codings": result["applications"],
                               "unmatched": result["unmatched"], "encoding": read.encoding})
    return result


def _whole_response_excerpt(proj, source_id: str):
    """Return the source's whole-response excerpt (char_start 0), if one exists."""
    for exc in proj.list_excerpts(source_id):
        if exc.char_start == 0:
            return exc
    excs = proj.list_excerpts(source_id)
    return excs[0] if excs else None


def record_human_codings(
    store_path: Union[str, Path],
    codings: Dict[str, List[str]],
    *,
    question_text: Optional[str] = None,
    rater_id: str = "human_primary",
    rater_name: str = "",
    run_id: str = "",
) -> Dict[str, int]:
    """Write Labeling-Lab codes into the project store as human CodeApplications.

    `codings` maps a CSV `response_id` to the list of labels the analyst assigned.
    This is where Lab-invented labels become first-class codes (origin="emergent",
    created_by="human") and where human coding enters the shared store so the
    Agreement tab can compare it against the model.

    Re-saving a sample *replaces* this rater's applications on those excerpts
    rather than appending, so recoding a response doesn't double it up.

    Returns ``{"excerpts", "applications", "new_codes", "unmatched"}``. Responses
    whose id can't be resolved to a Source are reported in `unmatched` rather than
    silently dropped — an unmatched id means the store and the Lab disagree about
    what was coded, which the analyst should see.
    """
    from core.model import Code, CodeApplication, Rater
    from core.project import Project

    store_path = Path(store_path)
    result: Dict[str, Any] = {"excerpts": 0, "applications": 0, "new_codes": 0,
                              "unmatched": 0, "unmatched_ids": []}

    with Project.create(store_path) as proj:
        proj.add_rater(Rater(rater_id=rater_id, kind="human", name=rater_name))

        code_id_by_name: Dict[str, str] = {c.name: c.code_id for c in proj.get_codebook()}

        def _code_id_for(label: str) -> str:
            if label not in code_id_by_name:
                code_id_by_name[label] = proj.add_code(Code(
                    code_id="", name=label, origin="emergent", created_by="human"))
                result["new_codes"] += 1
            return code_id_by_name[label]

        excerpt_ids: List[str] = []
        applications: List[CodeApplication] = []
        for response_id, labels in codings.items():
            source = proj.find_source_by_response_id(str(response_id), question=question_text)
            excerpt = _whole_response_excerpt(proj, source.source_id) if source else None
            if excerpt is None:
                result["unmatched"] += 1
                result["unmatched_ids"].append(str(response_id))
                continue
            excerpt_ids.append(excerpt.excerpt_id)
            for label in labels:
                if not label:
                    continue
                applications.append(CodeApplication(
                    application_id="", excerpt_id=excerpt.excerpt_id, code_id=_code_id_for(label),
                    coder="human", rater_id=rater_id, run_id=run_id or None))

        counts = proj.replace_applications_for_rater(rater_id, excerpt_ids, applications)
        result["excerpts"] = len(set(excerpt_ids))
        result["applications"] = counts["inserted"]

    return result
