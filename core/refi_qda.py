#!/usr/bin/env python
"""
REFI-QDA codebook exchange — the standard every other package speaks.

REFI-QDA is the open interoperability standard for qualitative analysis
software, launched with DANS (the Dutch national data archive) so that a
qualitative project can be exchanged and archived rather than trapped in the
program that made it. NVivo, ATLAS.ti, MAXQDA, QDA Miner, f4analyse and Quirkos
all implement it. QualSafe did not, and that was the sharpest strategic gap in
the tool.

It cuts both ways, and the second way is worse:

- **Coming in.** A researcher with an existing NVivo or MAXQDA project could not
  bring their codebook here. Every potential user who already has a project —
  which is most of them — faced a wall on the first day.
- **Going out.** They could not hand a QualSafe codebook to a colleague who uses
  something else. For a free, local, MIT-licensed tool whose pitch is *no lock-in
  and no vendor*, being **more** locked-in than the commercial packages inverts
  the argument entirely.

There is a published critique of exactly this — *The Current State of CAQDAS is
Insufficient for Open Science Qualitative Research* (EASST) — which finds
support for the FAIR principles marginal across the field. Interoperability is
the "I" in FAIR, and this file is QualSafe's answer to that letter.

Scope
-----
This module implements the **`.qdc` codebook** half of the standard: codes,
their descriptions, and their hierarchy. That is a complete, useful artifact on
its own — sharing a codebook is the common case, and it is what a team agrees on
before anyone codes anything.

The **`.qdpx` whole-project** half — sources, selections, codings, and their
character offsets — is deliberately not here yet. It is a much larger surface
and it deserves its own pass, with a real round-trip against a file each rival
actually produced. `V5_PLAN.md` §B7 carries it.

Design decisions
----------------
- **`xml.etree`, no new dependency.** The `.qdc` schema is small and this project
  refuses dependencies it can avoid.

- **GUIDs are minted, not invented from names.** The standard wants a GUID per
  code. QualSafe's ids (`code_a1b2…`) are not GUIDs, so export derives a stable
  one by hashing the project's id — stable so that re-exporting the same
  codebook produces the same file, and a diff between two exports shows what
  actually changed rather than a wall of new identifiers.

- **Import is additive and name-matched**, exactly like the YAML path in
  `core/codebook_io.py`. A codebook arriving from someone else's project must
  never clobber the receiving analyst's own definitions; collisions are reported
  and skipped. Two exchange formats behaving differently on the same question
  would be a trap.

- **Unknown elements are ignored, not fatal.** Every package writes a superset of
  what the others read; the standard's own documentation says complex projects
  cannot transfer one-to-one. A codebook that is 90% readable is worth 90% more
  than a refusal.
"""

from __future__ import annotations

import hashlib
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional

#: The namespace every REFI-QDA codebook declares. Note the dot: `1.0`, not
#: `1:0`. It was written with a colon here until an XSD conformance check
#: caught it, and nothing else could have — this module's reader and writer
#: agreed on the wrong value, so every round-trip test passed. Two agreeing
#: implementations of a misreading look exactly like a correct one.
NAMESPACE = "urn:QDA-XML:codebook:1.0"

#: What we write into `<Codebook origin=...>`, so a receiving package can say
#: where a codebook came from when something does not line up.
ORIGIN = "QualSafe"


def _guid(seed: str) -> str:
    """A stable GUID-shaped identifier derived from a QualSafe id.

    Stable matters: re-exporting an unchanged codebook must produce an unchanged
    file, or every export looks like a rewrite and a diff tells you nothing.
    """
    digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()
    return (f"{digest[0:8]}-{digest[8:12]}-{digest[12:16]}-"
            f"{digest[16:20]}-{digest[20:32]}").upper()


# ── export ────────────────────────────────────────────────────────────────────

def export_codebook_qdc(project) -> str:
    """A project's codebook as a REFI-QDA `.qdc` document.

    Hierarchy is nested, because that is how the standard represents it — a flat
    list with parent references would be valid XML and an invalid codebook.
    """
    codes = project.get_codebook()
    if not codes:
        # `CodeBookType` requires `Codes`, and `CodesType` requires at least one
        # `Code`. An empty codebook therefore has no valid representation in this
        # format, so refusing beats emitting a document NVivo would reject —
        # especially since the analyst can see the codebook is empty and the
        # program cannot explain a rejection that happens in another package.
        raise ValueError(
            "There are no codes to export. Add at least one code first — the "
            "REFI-QDA format has no way to express an empty codebook.")

    children: Dict[Optional[str], List[Any]] = {}
    for code in codes:
        children.setdefault(code.parent_id, []).append(code)

    root = ET.Element("CodeBook", {"xmlns": NAMESPACE, "origin": ORIGIN})
    container = ET.SubElement(root, "Codes")

    def _emit(parent_element: ET.Element, parent_id: Optional[str]) -> None:
        for code in children.get(parent_id, []):
            attributes = {
                "guid": _guid(code.code_id),
                "name": code.name,
                # The standard's `isCodable` means "may be applied to data".
                # Every code here can be; QualSafe has no folder-only nodes.
                "isCodable": "true",
            }
            element = ET.SubElement(parent_element, "Code", attributes)
            if code.definition:
                ET.SubElement(element, "Description").text = code.definition
            _emit(element, code.code_id)

    _emit(container, None)

    ET.indent(root, space="  ")
    return ('<?xml version="1.0" encoding="utf-8"?>\n'
            + ET.tostring(root, encoding="unicode"))


# ── import ────────────────────────────────────────────────────────────────────

def parse_codebook_qdc(text: str) -> List[Dict[str, Any]]:
    """Read a `.qdc` into the flat shape `core/codebook_io` already uses.

    Returns `[{"name", "definition", "parent"}]` with `parent` as a *name*, so
    the two exchange formats converge on one import path rather than two.

    Raises `ValueError` with a usable message on anything that is not a codebook;
    unknown elements inside a valid one are ignored.
    """
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise ValueError(f"This is not readable XML: {exc}") from exc

    tag = _strip_namespace(root.tag)
    if tag != "CodeBook":
        raise ValueError(
            f"Expected a REFI-QDA CodeBook and found <{tag}>. A `.qdpx` project "
            "file is a different thing — this reads the `.qdc` codebook format.")

    entries: List[Dict[str, Any]] = []

    def _walk(element: ET.Element, parent_name: Optional[str]) -> None:
        for child in element:
            if _strip_namespace(child.tag) != "Code":
                continue
            name = (child.get("name") or "").strip()
            if not name:
                continue  # a code with no name cannot be matched or applied
            entry: Dict[str, Any] = {"name": name}
            description = child.find(f"{{{NAMESPACE}}}Description")
            if description is None:
                description = child.find("Description")
            if description is not None and (description.text or "").strip():
                entry["definition"] = description.text.strip()
            if parent_name:
                entry["parent"] = parent_name
            entries.append(entry)
            _walk(child, name)

    for container in root:
        if _strip_namespace(container.tag) == "Codes":
            _walk(container, None)
    if not entries:
        _walk(root, None)   # some writers omit the <Codes> wrapper

    if not entries:
        raise ValueError("That codebook contains no codes.")
    return entries


def import_codebook_qdc(project, text: str) -> Dict[str, Any]:
    """Add a `.qdc` codebook to a project, additively.

    Delegates to `core.codebook_io.import_codebook_entries` so a code arriving as
    XML and the same code arriving as YAML are treated identically — including
    the rule that an existing name is skipped rather than overwritten.
    """
    from core.codebook_io import import_codebook_entries

    return import_codebook_entries(project, parse_codebook_qdc(text))


def _strip_namespace(tag: str) -> str:
    """`{urn:…}Code` -> `Code`. Writers differ on whether they qualify tags."""
    return tag.rsplit("}", 1)[-1]
