#!/usr/bin/env python
"""
REFI-QDA whole-project export — `.qdpx`, the exit promise.

`core/qdpx.py` reads a project in. This writes one out, and the two together are
what make "no lock-in" a fact rather than a claim. A researcher can take their
work to NVivo, MAXQDA or ATLAS.ti, hand it to a colleague who uses one of those,
or deposit it in an archive like DANS — which is what the standard was created
for and the reason it exists at all.

Import shipped first because it is the adoption path. This matters to a
different person: the one who already stayed, and who needs to know they can
leave. For a free MIT-licensed tool arguing against commercial packages on
exactly that ground, shipping the import without the export would have been the
weaker half of the argument.

What is written
---------------
    Users            <- raters, so a coding keeps the coder who made it
    CodeBook         <- the codebook, nested by hierarchy
    Variables        <- descriptor keys
    Sources
      TextSource     <- one per source, text written to Sources/<guid>.txt
        PlainTextSelection  <- an excerpt, at its stored character offsets
          Coding/CodeRef   <- a code application, attributed to its rater
        VariableValue    <- that source's descriptor values (order matters; see below)

Design decisions
----------------
- **Text goes in `Sources/` files, not inline.** Both are legal and this reader
  accepts either, but files are what the other packages write and what an
  archive expects, and inlining a corpus into one XML document is a way to make
  a file nothing can open.

- **GUIDs are derived by hashing, and are stable.** Re-exporting an unchanged
  project produces an unchanged manifest, so a diff between two exports shows
  what actually changed. Same rule and same helper as the codebook exporter.

- **A `.qdpx` always contains the full source text.** That is what it is for, and
  it cannot be redacted into something still worth exchanging. Every other export
  here states what it contains and several offer a redacted mode; this one
  cannot, so the honest thing is to say so plainly at the point of export rather
  than offer a checkbox that would lie.

- **Empty containers are omitted, not written empty.** Every container in this
  schema requires at least one child, so `<Users/>` with no users is invalid.
  A project with no coders, no codes or no sources yet is an ordinary thing to
  export, and it has to produce a file the other packages accept.

- **Element order is part of validity.** `TextSourceType` is an `xsd:sequence`,
  so `VariableValue` must follow the selections rather than precede them. That
  is not presentation: a file with them the other way round is invalid, and our
  own reader accepted it happily. Validate against the schema, not against
  ourselves.

- **Round-tripping is the test that matters.** Export then import into a fresh
  project has to return the same codes, sources, offsets, codings and coders.
  That check does not need a rival's file and it catches the errors a schema
  validator would not — an offset written against the wrong text, a coding
  attributed to the wrong coder.
"""

from __future__ import annotations

import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Union

from core.qdpx import NAMESPACE, PROJECT_ENTRY
from core.refi_qda import _guid

#: Where source text lives inside the archive, as the standard expects.
SOURCES_DIR = "Sources"

#: What this writer calls itself in the manifest, so a receiving package can say
#: where a project came from when something does not line up.
ORIGIN_TEMPLATE = "QualSafe {version}"


def export_qdpx(project, out_path: Union[str, Path], *,
                project_name: str = "") -> Path:
    """Write an open project as a `.qdpx`. Returns the path.

    The archive always carries the full text of every source; see the module
    docstring for why there is no redacted variant.
    """
    out_path = Path(out_path)
    sources = project.list_sources()
    raters = project.list_raters()
    codebook = project.get_codebook()
    descriptors = project.descriptor_table()
    spans = project.coding_spans_table()

    manifest = _build_manifest(
        project_name=project_name or out_path.stem,
        sources=sources, raters=raters, codebook=codebook,
        descriptors=descriptors, spans=spans,
        excerpts_by_source={
            source.source_id: project.list_excerpts(source.source_id)
            for source in sources
        },
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(PROJECT_ENTRY, manifest)
        for source in sources:
            archive.writestr(f"{SOURCES_DIR}/{_guid(source.source_id)}.txt",
                             source.raw_text or "")
    return out_path


def _build_manifest(*, project_name: str, sources, raters, codebook,
                    descriptors, spans, excerpts_by_source) -> str:
    from core.manifest import PACKAGE_VERSION

    root = ET.Element("Project", {
        "xmlns": NAMESPACE,
        "name": project_name,
        "origin": ORIGIN_TEMPLATE.format(version=PACKAGE_VERSION),
        "creationDateTime": datetime.now().isoformat(timespec="seconds"),
    })

    # Users first: a coding references one, and a reader that meets the
    # reference before the definition has to buffer.
    #
    # Omitted entirely when there are none. Every container in this schema
    # requires at least one child -- `UsersType` has no `minOccurs="0"` on
    # `User` -- so an empty `<Users/>` is invalid, and a project with no coders
    # yet is an ordinary thing to export.
    if raters:
        users = ET.SubElement(root, "Users")
        for rater in raters:
            ET.SubElement(users, "User", {
                "guid": _guid(rater.rater_id),
                "name": rater.name or rater.rater_id,
            })

    _emit_codebook(root, codebook)
    variable_guids = _emit_variables(root, descriptors)

    codings_by_excerpt: Dict[str, List[Dict[str, str]]] = {}
    if not spans.empty:
        for _index, row in spans.iterrows():
            codings_by_excerpt.setdefault(str(row["excerpt_id"]), []).append({
                "code_id": str(row["code_id"]),
                "rater_id": str(row["rater_id"] or ""),
                "application_id": str(row["application_id"]),
            })

    descriptor_values: Dict[str, Dict[str, str]] = {}
    if not descriptors.empty:
        for _index, row in descriptors.iterrows():
            descriptor_values.setdefault(str(row["source_id"]), {})[
                str(row["key"])] = str(row["value"])

    # Same rule as Users: `SourcesType` requires at least one source, so an empty
    # `<Sources/>` is invalid and the element is left out instead.
    container = ET.SubElement(root, "Sources") if sources else None
    for source in sources:
        element = ET.SubElement(container, "TextSource", {
            "guid": _guid(source.source_id),
            "name": source.label or source.metadata.get("title", "") or "Untitled",
            "plainTextPath": f"internal://{SOURCES_DIR}/{_guid(source.source_id)}.txt",
        })

        for excerpt in excerpts_by_source.get(source.source_id, []):
            codings = codings_by_excerpt.get(excerpt.excerpt_id, [])
            if not codings:
                # A selection carrying no coding is not a finding, and writing
                # one produces a file full of empty highlights in the receiving
                # program. Whole-response excerpts alone would fill it.
                continue
            selection = ET.SubElement(element, "PlainTextSelection", {
                "guid": _guid(excerpt.excerpt_id),
                "name": (excerpt.text or "")[:60],
                "startPosition": str(excerpt.char_start),
                "endPosition": str(excerpt.char_end),
            })
            # Deduplicated: the spans table yields one row per case, so a source
            # in two cases would otherwise write the same coding twice.
            seen = set()
            for coding in codings:
                if coding["application_id"] in seen:
                    continue
                seen.add(coding["application_id"])
                holder = ET.SubElement(selection, "Coding", {
                    "guid": _guid(coding["application_id"]),
                    "creatingUser": _guid(coding["rater_id"]),
                })
                ET.SubElement(holder, "CodeRef",
                              {"targetGUID": _guid(coding["code_id"])})

        # VariableValue comes *after* the selections. TextSourceType is an
        # xsd:sequence -- Description, PlainTextContent, PlainTextSelection,
        # Coding, NoteRef, VariableValue -- so order is part of validity, not
        # presentation. Writing the variables first produced a file our own
        # reader accepted and the schema rejected.
        for key, value in sorted(descriptor_values.get(source.source_id, {}).items()):
            if key not in variable_guids:
                continue
            holder = ET.SubElement(element, "VariableValue")
            ET.SubElement(holder, "VariableRef", {"targetGUID": variable_guids[key]})
            ET.SubElement(holder, "TextValue").text = value

    ET.indent(root, space="  ")
    return ('<?xml version="1.0" encoding="utf-8"?>\n'
            + ET.tostring(root, encoding="unicode"))


def _emit_codebook(root: ET.Element, codebook) -> None:
    if not codebook:
        # `CodeBookType` requires `Codes`, which requires at least one `Code`.
        # A project with no codes yet still has to export.
        return

    children: Dict[str, List] = {}
    for code in codebook:
        children.setdefault(code.parent_id or "", []).append(code)

    book = ET.SubElement(root, "CodeBook")
    container = ET.SubElement(book, "Codes")

    def _emit(parent_element: ET.Element, parent_id: str) -> None:
        for code in children.get(parent_id, []):
            element = ET.SubElement(parent_element, "Code", {
                "guid": _guid(code.code_id),
                "name": code.name,
                "isCodable": "true",
            })
            if code.definition:
                ET.SubElement(element, "Description").text = code.definition
            _emit(element, code.code_id)

    _emit(container, "")


def _emit_variables(root: ET.Element, descriptors) -> Dict[str, str]:
    """Declare each descriptor key as a Variable. Returns `{key: guid}`."""
    if descriptors is None or descriptors.empty:
        return {}
    keys = sorted({str(k) for k in descriptors["key"].dropna().unique()})
    if not keys:
        return {}

    container = ET.SubElement(root, "Variables")
    guids: Dict[str, str] = {}
    for key in keys:
        guids[key] = _guid(f"variable:{key}")
        ET.SubElement(container, "Variable", {
            "guid": guids[key],
            "name": key,
            # Everything QualSafe stores as a descriptor is text; declaring it
            # honestly beats guessing a numeric type a receiving package would
            # then fail to parse.
            "typeOfVariable": "Text",
        })
    return guids
