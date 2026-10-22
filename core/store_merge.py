#!/usr/bin/env python
"""
Project-store merge (v3.8.1, item 8.7).

The collaboration topology is copy-and-merge: a colleague codes in their own copy
of the project, and their `.qnw` comes back to be folded into yours. This merges
the *human* work — codings and emergent codes — into the target store.

Rules (all from the design notes, all deliberate):

- **Reconcile on (response_id, question_text), never on source ids.** Two copies
  of a project mint different internal ids for the same response; the response id
  is the shared truth.
- **Codes match by exact name.** A near-miss ("Cost worry" vs "Financial
  stress") is *reported* as a suggestion, never auto-merged — deciding that two
  codes mean the same thing is analyst judgment, and the Codebook page's merge
  tool exists for exactly that decision.
- **Each incoming human rater stays distinct**, and their applications are
  replaced-not-appended per merge (via `replace_applications_for_rater`), so
  re-merging an updated file is idempotent rather than duplicating.
- **Machine codings are not merged.** The target's own runs produce those; a
  colleague's model output on their copy is redundant at best and
  double-counting at worst.

The target is backed up before any write.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union


def _near(a: str, b: str) -> bool:
    """Cheap near-name signal: case-insensitive equal or one contains the other."""
    a_low, b_low = a.lower().strip(), b.lower().strip()
    if a_low == b_low:
        return True
    return (len(a_low) >= 4 and len(b_low) >= 4
            and (a_low in b_low or b_low in a_low))


def merge_project_stores(
    target_path: Union[str, Path],
    incoming_path: Union[str, Path],
) -> Dict[str, Any]:
    """Merge a colleague's human codings + emergent codes into the target store.

    Returns a report:
    ``{"raters_merged": {rater: n_applications}, "codes_created": [...],
    "near_name_suggestions": [(incoming, existing), ...],
    "unmatched_responses": [...], "matched": n, "backup": path}``.
    """
    from core.backups import backup_store
    from core.model import Code, CodeApplication, Rater
    from core.project import Project

    target_path = Path(target_path)
    incoming_path = Path(incoming_path)

    backup = backup_store(target_path, reason="pre_store_merge")

    report: Dict[str, Any] = {
        "raters_merged": {}, "codes_created": [], "near_name_suggestions": [],
        "unmatched_responses": [], "matched": 0,
        "backup": str(backup) if backup else None,
    }

    with Project.open(incoming_path) as src:
        # Who are the incoming humans?
        human_raters = {r.rater_id: r for r in src.list_raters() if r.kind == "human"}
        if not human_raters:
            report["note"] = "No human raters found in the incoming project."
            return report

        # Incoming lookups: excerpt -> source -> (response_id, question).
        src_sources = {s.source_id: s for s in src.list_sources()}
        excerpt_key: Dict[str, Tuple[str, str]] = {}
        for exc in src.list_excerpts():
            source = src_sources.get(exc.source_id)
            if source is None:
                continue
            excerpt_key[exc.excerpt_id] = (
                str(source.metadata.get("response_id", "")),
                str(source.metadata.get("question_text", "")),
            )
        code_name_by_id = {c.code_id: c for c in src.get_codebook()}

        # Group the incoming human applications per rater.
        apps_by_rater: Dict[str, List] = defaultdict(list)
        for app in src.list_applications():
            if app.rater_id in human_raters:
                apps_by_rater[app.rater_id].append(app)
        # And what each of them reviewed (format v8), including responses they
        # left uncoded: "no code applies" has to survive a merge, or kappa in
        # the merged project drops the colleague's disagreements (review F1).
        reviewed_by_rater = {r: src.coverage_excerpt_ids(r) for r in human_raters}

    with Project.open(target_path) as dst:
        existing_names = {c.name: c.code_id for c in dst.get_codebook()}

        def _dst_code_id(incoming_code: Code) -> str:
            if incoming_code.name in existing_names:
                return existing_names[incoming_code.name]
            # Near-name? Report the suggestion, and still create the incoming
            # code verbatim — merging meanings is the analyst's call, later.
            for existing in list(existing_names):
                if _near(incoming_code.name, existing):
                    suggestion = (incoming_code.name, existing)
                    if suggestion not in report["near_name_suggestions"]:
                        report["near_name_suggestions"].append(suggestion)
            new_id_ = dst.add_code(Code(
                code_id="", name=incoming_code.name,
                definition=incoming_code.definition,
                origin=incoming_code.origin or "emergent", created_by="human"))
            existing_names[incoming_code.name] = new_id_
            report["codes_created"].append(incoming_code.name)
            return new_id_

        unmatched: set = set()

        def _target_excerpt(src_excerpt_id: str) -> Optional[str]:
            """The target's whole-response excerpt for an incoming excerpt, or None."""
            key = excerpt_key.get(src_excerpt_id)
            if key is None or not key[0]:
                unmatched.add(src_excerpt_id)
                return None
            response_id, question = key
            target_source = dst.find_source_by_response_id(
                response_id, question=question or None)
            target_excerpts = dst.list_excerpts(target_source.source_id) if target_source else []
            if not target_excerpts:
                unmatched.add(f"{response_id} ({question})")
                return None
            return next((e for e in target_excerpts if e.char_start == 0),
                        target_excerpts[0]).excerpt_id

        for rater_id in sorted(set(apps_by_rater) | {r for r, ids in reviewed_by_rater.items() if ids}):
            rater = human_raters[rater_id]
            dst.add_rater(Rater(rater_id=rater_id, kind="human",
                                name=rater.name, model_id=rater.model_id))
            excerpt_ids: List[str] = []
            new_apps: List[CodeApplication] = []
            for app in apps_by_rater.get(rater_id, []):
                target = _target_excerpt(app.excerpt_id)
                incoming_code = code_name_by_id.get(app.code_id)
                if target is None or incoming_code is None:
                    continue
                excerpt_ids.append(target)
                new_apps.append(CodeApplication(
                    application_id="", excerpt_id=target,
                    code_id=_dst_code_id(incoming_code), coder="human",
                    rater_id=rater_id, run_id=app.run_id,
                    weight=app.weight, rationale=app.rationale))
            reviewed = reviewed_by_rater.get(rater_id, set())
            for src_excerpt_id in sorted(reviewed):
                target = _target_excerpt(src_excerpt_id)
                if target is not None:
                    excerpt_ids.append(target)
            # A pre-v8 colleague has no review record; copying one into the
            # target would claim reviews nobody recorded.
            counts = dst.replace_applications_for_rater(
                rater_id, excerpt_ids, new_apps, record_review=bool(reviewed))
            report["raters_merged"][rater_id] = counts["inserted"]
            report["matched"] += counts["inserted"]

        report["unmatched_responses"] = sorted(unmatched)
        dst.log_event("project_merged",
                      f"Merged coding from another project: {', '.join(report['raters_merged']) or 'no coders'}",
                      target_type="project", target_id=incoming_path.name,
                      detail={"coders": report["raters_merged"], "codes_created": report["codes_created"],
                              "unmatched": len(report["unmatched_responses"])})

    return report
