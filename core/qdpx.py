#!/usr/bin/env python
"""
REFI-QDA whole-project import — `.qdpx`, the adoption path.

`core/refi_qda.py` exchanges a codebook. This exchanges a *project*: the
documents, the coded passages and their character offsets, the coders, and the
respondent variables. It is the file NVivo, ATLAS.ti, MAXQDA and QDA Miner all
produce, and reading it is what turns QualSafe from a tool you must switch to
wholesale into one you can try on work you have already done.

Import first, export second, deliberately. Import is the adoption path and
decides whether anyone ever opens the program twice; export is the exit promise
and matters most to people who have already stayed.

The format
----------
A `.qdpx` is a zip holding `project.qde` — an XML document in the
`urn:QDA-XML:project:1.0` namespace — and a `Sources/` folder of the actual
files. The parts this reads:

    CodeBook/Codes/Code                 -> codes, nested by hierarchy
    Sources/TextSource                  -> a Source (type='document')
      PlainTextContent | plainTextPath  -> its text, inline or in the zip
      PlainTextSelection                -> an Excerpt at [startPosition, endPosition)
        Coding/CodeRef                  -> a CodeApplication
    Variables + VariableValue           -> descriptors
    Users                               -> rater names, for attribution

Three decisions worth reading before changing anything
------------------------------------------------------
**1. Imported codings are never yours.** They land under a rater id derived from
the file's own user — `imported_<name>` — never `human_primary`. This is the
methodological centre of the feature, not a nicety: κ compares raters, and
silently merging a colleague's coding into your own rater id would inflate
agreement to 1.0 and make the number meaningless while looking perfect. The same
reasoning already governs `auto_textsearch` and the pipeline's `transformer`
rater.

**2. Offsets are verified, never trusted.** A selection's `startPosition` and
`endPosition` index the source's plain text, and what the exporting program
counted may not be what lands in the zip — CRLF collapsing to LF shifts every
later position, and the same class of bug is already recorded for Qt
(`PORTED_BACK.md` §2). Every excerpt is checked against the text actually
imported; a selection whose offsets do not resolve is **skipped and reported**,
never stored at a guessed position. A wrong excerpt is worse than a missing one,
because a wrong one looks like evidence.

**3. What is not imported is named.** Media sources, notes, sets, graphs and
links have no home here yet, and the standard's own documentation says complex
projects cannot transfer one-to-one. The report lists every one, counted. A
silent partial import is how someone concludes their data came across when a
third of it did not.
"""

from __future__ import annotations

import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field as dataclass_field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

#: The project namespace. `core/refi_qda.py` handles the codebook one.
NAMESPACE = "urn:QDA-XML:project:1.0"

#: The XML document inside the archive. The standard names it, but writers vary
#: in case, so lookup is case-insensitive.
PROJECT_ENTRY = "project.qde"

#: Prefix for raters created by an import. Deliberately not `human_` — the
#: agreement screen lists `human*` raters as this project's own coders, and
#: someone else's codings are not that until the analyst adopts them.
IMPORTED_RATER_PREFIX = "imported"


@dataclass
class ImportReport:
    """What came across, and — as loudly — what did not."""

    codes: int = 0
    sources: int = 0
    excerpts: int = 0
    codings: int = 0
    descriptors: int = 0
    raters: List[str] = dataclass_field(default_factory=list)
    origin: str = ""
    #: Selections whose offsets did not resolve against the imported text.
    unresolved_selections: int = 0
    #: Element names present in the file that this reader has no home for.
    skipped: Dict[str, int] = dataclass_field(default_factory=dict)

    def summary(self) -> str:
        """One paragraph an analyst can read and check."""
        parts = [
            f"Imported {self.sources} document(s), {self.codes} code(s), "
            f"{self.excerpts} coded passage(s) and {self.codings} coding(s)"
        ]
        if self.raters:
            parts.append("under " + ", ".join(f"`{r}`" for r in self.raters))
        line = " ".join(parts) + "."
        if self.descriptors:
            line += f" {self.descriptors} descriptor value(s) came with them."
        if self.unresolved_selections:
            line += (f" **{self.unresolved_selections} passage(s) were skipped** "
                     "because their character positions did not match the text in "
                     "the file — they are not stored at a guessed position.")
        if self.skipped:
            named = ", ".join(f"{n} {k}" for k, n in sorted(self.skipped.items()))
            line += f" Not imported: {named}."
        return line


# ── reading the archive ───────────────────────────────────────────────────────

def read_project_xml(path: Union[str, Path]) -> str:
    """The `project.qde` text out of a `.qdpx`. Raises ValueError if it is not one."""
    path = Path(path)
    try:
        archive = zipfile.ZipFile(path)
    except zipfile.BadZipFile as exc:
        raise ValueError(
            "That file is not a .qdpx archive. A .qdpx is a zip; if you have a "
            "`.qdc` codebook instead, import it on the Codebook page.") from exc

    with archive:
        entry = _find_entry(archive, PROJECT_ENTRY)
        if entry is None:
            raise ValueError(
                "This archive has no `project.qde` inside it, so it is not a "
                "REFI-QDA project export.")
        return archive.read(entry).decode("utf-8-sig", errors="replace")


def _find_entry(archive: zipfile.ZipFile, name: str) -> Optional[str]:
    """Case- and folder-insensitive lookup. Writers disagree about both."""
    target = name.lower()
    for candidate in archive.namelist():
        if candidate.lower().rsplit("/", 1)[-1] == target:
            return candidate
    return None


# ── parsing ───────────────────────────────────────────────────────────────────

def _tag(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _children(element: ET.Element, name: str) -> List[ET.Element]:
    return [c for c in element if _tag(c) == name]


def _first(element: ET.Element, name: str) -> Optional[ET.Element]:
    found = _children(element, name)
    return found[0] if found else None


def parse_project(xml_text: str,
                  source_text: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Read a `project.qde` into plain dictionaries.

    `source_text` maps a source's `plainTextPath` to its content, for archives
    that store text as files rather than inline. Parsing is separated from
    importing so a caller can show the analyst what is in a file before writing
    any of it into their project.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise ValueError(f"The project file is not readable XML: {exc}") from exc

    if _tag(root) != "Project":
        raise ValueError(
            f"Expected a REFI-QDA <Project> and found <{_tag(root)}>.")

    # `_first(...) or fallback` would be wrong here, not just noisy: an element's
    # truth value is its child count today and will be identity in a later
    # Python, so an empty <Users/> silently changes which branch runs. Compare
    # against None explicitly.
    users_element = _first(root, "Users")
    users = {
        u.get("guid", ""): (u.get("name") or "").strip()
        for u in (_children(users_element, "User") if users_element is not None else [])
    }

    codes: List[Dict[str, Any]] = []
    code_names: Dict[str, str] = {}
    codebook = _first(root, "CodeBook")
    if codebook is not None:
        container = _first(codebook, "Codes")
        _walk_codes(container if container is not None else codebook,
                    None, codes, code_names)

    sources, unresolved = _parse_sources(root, source_text or {}, users, code_names)
    variables = _parse_variables(root)

    skipped: Dict[str, int] = {}
    for name, label in (("Notes", "note"), ("Sets", "set"), ("Graphs", "graph"),
                        ("Links", "link"), ("Cases", "case")):
        container = _first(root, name)
        if container is not None and len(container):
            skipped[label] = len(container)
    for media in ("PictureSource", "AudioSource", "VideoSource", "PDFSource"):
        found = _find_all(root, media)
        if found:
            skipped[media.replace("Source", "").lower() + " source"] = len(found)

    return {
        "origin": (root.get("origin") or "").strip(),
        "name": (root.get("name") or "").strip(),
        "users": users,
        "codes": codes,
        "sources": sources,
        "variables": variables,
        "unresolved_selections": unresolved,
        "skipped": skipped,
    }


def _find_all(root: ET.Element, name: str) -> List[ET.Element]:
    return [e for e in root.iter() if _tag(e) == name]


def _walk_codes(container: ET.Element, parent: Optional[str],
                out: List[Dict[str, Any]], names: Dict[str, str]) -> None:
    for element in _children(container, "Code"):
        name = (element.get("name") or "").strip()
        if not name:
            continue
        guid = element.get("guid") or ""
        names[guid] = name
        entry: Dict[str, Any] = {"name": name}
        description = _first(element, "Description")
        if description is not None and (description.text or "").strip():
            entry["definition"] = description.text.strip()
        if parent:
            entry["parent"] = parent
        # Everything in a .qdpx codebook was defined by a person before or during
        # their coding, which is what `a_priori` means here.
        entry["origin"] = "a_priori"
        out.append(entry)
        _walk_codes(element, name, out, names)


def _parse_sources(root: ET.Element, source_text: Dict[str, str],
                   users: Dict[str, str],
                   code_names: Dict[str, str]) -> tuple:
    sources: List[Dict[str, Any]] = []
    unresolved = 0

    container = _first(root, "Sources")
    if container is None:
        return sources, unresolved

    for element in _children(container, "TextSource"):
        text = _source_text(element, source_text)
        if text is None:
            unresolved += len(_children(element, "PlainTextSelection"))
            continue

        selections: List[Dict[str, Any]] = []
        for selection in _children(element, "PlainTextSelection"):
            start = _int(selection.get("startPosition"))
            end = _int(selection.get("endPosition"))
            # Verified, never trusted: what the exporting program counted may not
            # be what landed in the archive. A wrong excerpt looks like evidence.
            if start is None or end is None or not 0 <= start < end <= len(text):
                unresolved += 1
                continue
            codings = []
            for coding in _children(selection, "Coding"):
                reference = _first(coding, "CodeRef")
                target = reference.get("targetGUID") if reference is not None else None
                if not target or target not in code_names:
                    continue
                codings.append({
                    "code": code_names[target],
                    "user": users.get(coding.get("creatingUser", ""), ""),
                })
            selections.append({
                "start": start, "end": end, "text": text[start:end],
                "name": (selection.get("name") or "").strip(),
                "codings": codings,
            })

        sources.append({
            "guid": element.get("guid") or "",
            "name": (element.get("name") or "").strip() or "Untitled",
            "text": text,
            "selections": selections,
        })

    return sources, unresolved


def _source_text(element: ET.Element, source_text: Dict[str, str]) -> Optional[str]:
    """Inline content if present, else the file the archive pointed at."""
    inline = _first(element, "PlainTextContent")
    if inline is not None and inline.text is not None:
        return inline.text
    path = element.get("plainTextPath") or ""
    if path:
        key = path.replace("\\", "/").rsplit("/", 1)[-1]
        if key in source_text:
            return source_text[key]
    return None


def _parse_variables(root: ET.Element) -> Dict[str, Dict[str, str]]:
    """`{source guid: {variable name: value}}` — these become descriptors."""
    names: Dict[str, str] = {}
    container = _first(root, "Variables")
    if container is not None:
        for variable in _children(container, "Variable"):
            names[variable.get("guid", "")] = (variable.get("name") or "").strip()

    out: Dict[str, Dict[str, str]] = {}
    for element in root.iter():
        if _tag(element) != "TextSource":
            continue
        guid = element.get("guid") or ""
        for value in _children(element, "VariableValue"):
            reference = _first(value, "VariableRef")
            key = names.get(reference.get("targetGUID", ""), "") if reference is not None else ""
            if not key:
                continue
            for holder in value:
                if _tag(holder).endswith("Value") and (holder.text or "").strip():
                    out.setdefault(guid, {})[key] = holder.text.strip()
                    break
    return out


def _int(value: Optional[str]) -> Optional[int]:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


# ── importing ─────────────────────────────────────────────────────────────────

def rater_id_for(user_name: str) -> str:
    """The rater an imported coding lands under.

    Never `human_primary`. κ compares raters, so merging a colleague's coding
    into the analyst's own id would inflate agreement to 1.0 — perfect-looking
    and meaningless. An imported coder stays a distinct, named coder until the
    analyst decides otherwise.
    """
    cleaned = "".join(c if c.isalnum() else "_" for c in (user_name or "").strip())
    cleaned = cleaned.strip("_").lower() or "unknown"
    return f"{IMPORTED_RATER_PREFIX}_{cleaned}"


def import_qdpx(project, path: Union[str, Path]) -> ImportReport:
    """Import a `.qdpx` into an open project. Additive; nothing is overwritten."""
    path = Path(path)
    with zipfile.ZipFile(path) as archive:
        entry = _find_entry(archive, PROJECT_ENTRY)
        if entry is None:
            raise ValueError(
                "This archive has no `project.qde` inside it, so it is not a "
                "REFI-QDA project export.")
        xml_text = archive.read(entry).decode("utf-8-sig", errors="replace")
        texts = {
            name.replace("\\", "/").rsplit("/", 1)[-1]:
                archive.read(name).decode("utf-8-sig", errors="replace")
            for name in archive.namelist()
            if name.lower().endswith(".txt")
        }

    return import_parsed(project, parse_project(xml_text, texts))


def import_parsed(project, parsed: Dict[str, Any]) -> ImportReport:
    """Write an already-parsed project into the store.

    Split out so a caller can parse, show the analyst what is in the file, and
    only then write — and so this is testable without building a zip.
    """
    from core.codebook_io import import_codebook_entries
    from core.model import CodeApplication, Descriptor, Excerpt, Rater, Source

    report = ImportReport(
        origin=parsed.get("origin", ""),
        unresolved_selections=int(parsed.get("unresolved_selections", 0)),
        skipped=dict(parsed.get("skipped", {})),
    )

    codebook = import_codebook_entries(project, parsed.get("codes", []))
    report.codes = len(codebook["created"])
    code_ids = {c.name: c.code_id for c in project.get_codebook()}

    variables = parsed.get("variables", {})
    seen_raters: Dict[str, str] = {}

    for entry in parsed.get("sources", []):
        source_id = project.add_source(Source(
            source_id="", type="document", raw_text=entry["text"],
            label=entry["name"],
            metadata={"title": entry["name"], "imported_from": report.origin or "REFI-QDA"},
        ))
        report.sources += 1

        for key, value in (variables.get(entry["guid"], {}) or {}).items():
            project.set_descriptor(Descriptor(source_id=source_id, key=key, value=value))
            report.descriptors += 1

        for selection in entry["selections"]:
            excerpt_id = project.add_excerpt(Excerpt(
                excerpt_id="", source_id=source_id, text=selection["text"],
                char_start=selection["start"], char_end=selection["end"],
            ))
            report.excerpts += 1

            for coding in selection["codings"]:
                code_id = code_ids.get(coding["code"])
                if code_id is None:
                    continue
                rater_id = rater_id_for(coding["user"])
                if rater_id not in seen_raters:
                    project.add_rater(Rater(
                        rater_id=rater_id, kind="human",
                        name=coding["user"] or "Imported coder"))
                    seen_raters[rater_id] = coding["user"]
                project.apply_code(CodeApplication(
                    application_id="", excerpt_id=excerpt_id, code_id=code_id,
                    coder="human", rater_id=rater_id))
                report.codings += 1

    report.raters = sorted(seen_raters)
    project.log_event("qdpx_imported", f"REFI-QDA project imported ({report.codings} codings)",
                      target_type="import", detail={"coders": report.raters,
                                                    "codings": report.codings})
    return report
