#!/usr/bin/env python
"""
Codebook exchange (v3.8.1, item 8.5).

A codebook is an institution's accumulated analytical vocabulary — the thing you
want to carry from the fall survey to the spring survey, or hand to a colleague
starting a parallel project. This module makes it a portable YAML artifact:
human-readable, diffable, and importable into any project.

Import is **additive and name-matched**: codes already present (by exact name)
are left untouched and reported as skipped, never clobbered — the receiving
project's codebook is its analyst's property. Hierarchy is preserved by parent
*name*, resolved after all codes exist, so order in the file doesn't matter.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import yaml


def export_codebook_yaml(project) -> str:
    """Serialize a project's codebook (names, definitions, hierarchy, origin)."""
    codes = project.get_codebook()
    name_by_id = {c.code_id: c.name for c in codes}
    entries: List[Dict[str, Any]] = []
    for code in codes:
        entry: Dict[str, Any] = {"name": code.name}
        if code.definition:
            entry["definition"] = code.definition
        if code.parent_id and code.parent_id in name_by_id:
            entry["parent"] = name_by_id[code.parent_id]
        entry["origin"] = code.origin
        # The operational rules a coder (human or machine) applies: they are what makes a code repeatable.
        if code.inclusion_criteria:
            entry["inclusion_criteria"] = code.inclusion_criteria
        if code.exclusion_criteria:
            entry["exclusion_criteria"] = code.exclusion_criteria
        if code.examples:
            entry["examples"] = list(code.examples)
        entries.append(entry)
    return yaml.safe_dump({"codebook": entries}, sort_keys=False, allow_unicode=True)


def parse_codebook_yaml(text: str) -> List[Dict[str, Any]]:
    """Validate and normalize a codebook YAML. Raises ValueError with a usable
    message on a malformed file (an analyst will see this string)."""
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ValueError(f"Not valid YAML: {exc}") from exc
    if not isinstance(data, dict) or "codebook" not in data:
        raise ValueError("Expected a top-level 'codebook:' list "
                         "(export one from the Codebook page to see the format).")
    entries = data["codebook"]
    if not isinstance(entries, list) or not entries:
        raise ValueError("'codebook:' must be a non-empty list of codes.")
    normalized = []
    seen = set()
    for i, raw in enumerate(entries):
        if not isinstance(raw, dict) or not str(raw.get("name", "")).strip():
            raise ValueError(f"Codebook entry {i + 1} is missing a 'name'.")
        name = str(raw["name"]).strip()
        if name in seen:
            raise ValueError(f"Duplicate code name in file: '{name}'.")
        seen.add(name)
        examples = raw.get("examples") or []
        if isinstance(examples, str):
            examples = [examples]
        if not isinstance(examples, list):
            raise ValueError(f"The examples for '{name}' must be a list.")
        normalized.append({
            "name": name,
            "definition": str(raw.get("definition", "") or ""),
            "parent": (str(raw["parent"]).strip() if raw.get("parent") else None),
            "origin": str(raw.get("origin", "a_priori") or "a_priori"),
            "inclusion_criteria": (str(raw["inclusion_criteria"]).strip() if raw.get("inclusion_criteria") else None),
            "exclusion_criteria": (str(raw["exclusion_criteria"]).strip() if raw.get("exclusion_criteria") else None),
            "examples": [str(x).strip() for x in examples if str(x).strip()],
        })
    return normalized


def import_codebook_yaml(project, text: str) -> Dict[str, Any]:
    """Additively import a codebook YAML into a project.

    Returns ``{"created": [...], "skipped_existing": [...], "parents_linked": n,
    "parents_unresolved": [...]}``. Existing codes (exact name) are never
    modified. Parents are linked by name after creation; a parent name that
    exists nowhere is reported, not invented.
    """
    return import_codebook_entries(project, parse_codebook_yaml(text))


def import_codebook_entries(project, entries: List[Dict[str, Any]]) -> Dict[str, Any]:
    """The import itself, over already-parsed entries.

    Split out from the YAML path so the REFI-QDA reader in `core/refi_qda.py`
    lands here too. Two exchange formats that disagreed about whether an existing
    code gets overwritten would be a trap, and the answer — never — belongs in
    one place.

    Each entry is ``{"name", "definition", "origin", "parent"}``; `definition`,
    `origin` and `parent` may be absent.
    """
    from core.model import Code

    entries = [
        {"name": e["name"], "definition": e.get("definition", "") or "",
         "origin": e.get("origin", "a_priori") or "a_priori",
         "parent": e.get("parent") or None,
         "inclusion_criteria": e.get("inclusion_criteria") or None,
         "exclusion_criteria": e.get("exclusion_criteria") or None,
         "examples": list(e.get("examples") or [])}
        for e in entries
    ]
    existing = {c.name: c.code_id for c in project.get_codebook()}

    created: List[str] = []
    skipped: List[str] = []
    id_by_name: Dict[str, str] = dict(existing)

    for entry in entries:
        if entry["name"] in existing:
            skipped.append(entry["name"])
            continue
        code_id = project.add_code(Code(
            code_id="", name=entry["name"], definition=entry["definition"],
            origin=entry["origin"], created_by="human",
            inclusion_criteria=entry["inclusion_criteria"], exclusion_criteria=entry["exclusion_criteria"],
            examples=entry["examples"]))
        id_by_name[entry["name"]] = code_id
        created.append(entry["name"])

    linked = 0
    unresolved: List[str] = []
    for entry in entries:
        parent = entry["parent"]
        if not parent or entry["name"] in skipped:
            continue  # never rewire codes the project already had
        if parent in id_by_name:
            project.set_code_parent(id_by_name[entry["name"]], id_by_name[parent])
            linked += 1
        else:
            unresolved.append(f"{entry['name']} → {parent}")

    project.log_event("codebook_imported", f"Codebook imported: {len(created)} code(s) added",
                      target_type="codebook", detail={"created": created, "skipped": skipped})
    return {"created": created, "skipped_existing": skipped,
            "parents_linked": linked, "parents_unresolved": unresolved}


def codebook_label_list(text: str) -> List[str]:
    """The code names from a codebook YAML, for use as Theme Setup labels."""
    return [e["name"] for e in parse_codebook_yaml(text)]
