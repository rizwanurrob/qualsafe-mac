#!/usr/bin/env python
"""
Write adjudicated (reconciled) codings to the store (v3.9.6, F2).

When two coders disagree on an item, the analyst resolves it to an agreed code
set. That decision is recorded as its own rater — `human_adjudicated` — so it
never overwrites either coder's original codings (which the reliability number
still depends on), and the reconciled set can serve as the gold standard for
model-vs-human comparison.

Excerpt-keyed (unlike `core.populate.record_human_codings`, which is
response-id-keyed), because adjudication happens on the Agreement tab over
`Project.rater_labels`, whose keys are excerpt ids. Idempotent: re-resolving an
item replaces this rater's codes on that excerpt rather than stacking them, via
the same `replace_applications_for_rater` used by the Labeling Lab.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Union

ADJUDICATED_RATER = "human_adjudicated"


def record_adjudications(
    store_path: Union[str, Path],
    decisions: Dict[str, List[str]],
    *,
    rater_id: str = ADJUDICATED_RATER,
    rater_name: str = "",
) -> Dict[str, int]:
    """Record resolved code sets, keyed by excerpt id.

    ``decisions`` maps ``excerpt_id -> [code_name, ...]`` (an empty list means the
    adjudicated decision is "no code here" — recorded as the rater touching the
    excerpt with no applications). Codes are matched by exact name; a name not yet
    in the codebook is created as an emergent human code so an adjudicator can
    introduce a reconciling label.

    Returns ``{"excerpts", "applications", "new_codes", "unmatched"}``.
    ``unmatched`` counts excerpt ids that don't exist in the store.
    """
    from core.model import Code, CodeApplication, Rater
    from core.project import Project

    store_path = Path(store_path)
    result = {"excerpts": 0, "applications": 0, "new_codes": 0, "unmatched": 0}

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
        for excerpt_id, labels in decisions.items():
            if proj.get_excerpt(excerpt_id) is None:
                result["unmatched"] += 1
                continue
            excerpt_ids.append(excerpt_id)
            for label in labels:
                if not str(label).strip():
                    continue
                applications.append(CodeApplication(
                    application_id="", excerpt_id=excerpt_id,
                    code_id=_code_id_for(str(label).strip()),
                    coder="human", rater_id=rater_id))

        counts = proj.replace_applications_for_rater(rater_id, excerpt_ids, applications)
        result["excerpts"] = len(set(excerpt_ids))
        result["applications"] = counts["inserted"]
        if excerpt_ids:
            proj.log_event("adjudication", f"{result['excerpts']} disagreement(s) resolved",
                           target_type="rater", target_id=rater_id,
                           detail={"items": result["excerpts"], "codings": result["applications"],
                                   "new_codes": result["new_codes"]})

    return result
