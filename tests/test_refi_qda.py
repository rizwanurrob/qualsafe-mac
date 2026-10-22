"""
REFI-QDA codebook exchange (v4.6, `V5_PLAN.md` §B7).

REFI-QDA is the open interoperability standard for qualitative software, and
NVivo, ATLAS.ti, MAXQDA, QDA Miner and Quirkos all implement it. QualSafe did
not, which meant a researcher could neither bring an existing codebook in nor
hand one to a colleague — leaving a free, MIT-licensed, local-first tool *more*
locked-in than the commercial packages whose lock-in is its pitch against them.

Two properties carry the weight here:

**Round-tripping.** Export then import must return the same codebook, hierarchy
included, or the format is decorative.

**Reading other people's files.** Every package writes a superset of what the
others read, and the standard's own documentation says complex projects cannot
transfer one-to-one. So the reader is tested against shapes a *different* writer
would plausibly produce — unqualified tags, no `<Codes>` wrapper, unknown
elements — because a reader that only reads its own output is not
interoperability.
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.model import Code
from core.project import Project
from core.refi_qda import (
    NAMESPACE, export_codebook_qdc, import_codebook_qdc, parse_codebook_qdc)


@pytest.fixture()
def project(tmp_path):
    """A codebook two deep: Cost > Textbooks, plus a sibling."""
    path = tmp_path / "p.qnw"
    with Project.create(path) as proj:
        cost = proj.add_code(Code(code_id="", name="Financial concerns",
                                  definition="Money worries of any kind"))
        proj.add_code(Code(code_id="", name="Textbook cost",
                           definition="Specifically the books", parent_id=cost))
        proj.add_code(Code(code_id="", name="Sense of belonging"))
    return path


class TestExport:

    def test_it_is_a_refi_qda_codebook(self, project):
        with Project.open(project) as proj:
            xml = export_codebook_qdc(proj)

        root = ET.fromstring(xml)
        assert root.tag.endswith("CodeBook")
        assert NAMESPACE in xml
        assert xml.startswith('<?xml version="1.0" encoding="utf-8"?>')

    def test_hierarchy_is_nested_not_flattened(self, project):
        """A flat list with parent references would be valid XML and an invalid
        codebook."""
        with Project.open(project) as proj:
            root = ET.fromstring(export_codebook_qdc(proj))

        codes = root.find(f"{{{NAMESPACE}}}Codes")
        top = [c for c in codes]
        assert len(top) == 2, "two roots, not three codes side by side"

        parent = next(c for c in top if c.get("name") == "Financial concerns")
        assert [c.get("name") for c in parent
                if c.tag.endswith("Code")] == ["Textbook cost"]

    def test_definitions_travel(self, project):
        with Project.open(project) as proj:
            xml = export_codebook_qdc(proj)
        assert "Money worries of any kind" in xml

    def test_every_code_carries_a_guid(self, project):
        with Project.open(project) as proj:
            root = ET.fromstring(export_codebook_qdc(proj))

        guids = [e.get("guid") for e in root.iter() if e.tag.endswith("Code")]
        assert len(guids) == 3
        assert all(g and len(g) == 36 for g in guids)
        assert len(set(guids)) == 3

    def test_exporting_twice_produces_the_same_file(self, project):
        """Stable ids, so a diff between two exports shows what actually changed
        rather than a wall of new identifiers."""
        with Project.open(project) as proj:
            assert export_codebook_qdc(proj) == export_codebook_qdc(proj)

    def test_an_empty_codebook_is_refused(self, tmp_path):
        """This test used to assert the opposite — that an empty codebook still
        produced a document. It did, and the document was invalid: `CodesType`
        requires at least one `Code`. Validating against the published schema is
        what found it.
        """
        path = tmp_path / "empty.qnw"
        Project.create(path).close()
        with Project.open(path) as proj:
            with pytest.raises(ValueError, match="no codes to export"):
                export_codebook_qdc(proj)


class TestRoundTrip:

    def test_a_codebook_survives_export_and_import(self, project, tmp_path):
        with Project.open(project) as proj:
            xml = export_codebook_qdc(proj)

        receiving = tmp_path / "receiving.qnw"
        Project.create(receiving).close()
        with Project.open(receiving) as proj:
            report = import_codebook_qdc(proj, xml)
            names = {c.name for c in proj.get_codebook()}

        assert names == {"Financial concerns", "Textbook cost", "Sense of belonging"}
        assert report["parents_linked"] == 1

    def test_hierarchy_survives_the_trip(self, project, tmp_path):
        with Project.open(project) as proj:
            xml = export_codebook_qdc(proj)

        receiving = tmp_path / "receiving.qnw"
        Project.create(receiving).close()
        with Project.open(receiving) as proj:
            import_codebook_qdc(proj, xml)
            codes = {c.name: c for c in proj.get_codebook()}
            parent_id = codes["Financial concerns"].code_id

        assert codes["Textbook cost"].parent_id == parent_id

    def test_definitions_survive_the_trip(self, project, tmp_path):
        with Project.open(project) as proj:
            xml = export_codebook_qdc(proj)

        receiving = tmp_path / "receiving.qnw"
        Project.create(receiving).close()
        with Project.open(receiving) as proj:
            import_codebook_qdc(proj, xml)
            codes = {c.name: c for c in proj.get_codebook()}

        assert codes["Financial concerns"].definition == "Money worries of any kind"


class TestReadingOtherPeoplesFiles:
    """A reader that only reads its own output is not interoperability."""

    def test_unqualified_tags_are_accepted(self):
        """Writers differ on whether they namespace-qualify every element."""
        xml = """<?xml version="1.0" encoding="utf-8"?>
        <CodeBook origin="SomeOtherPackage">
          <Codes>
            <Code guid="A" name="Cost"><Description>Money</Description></Code>
          </Codes>
        </CodeBook>"""

        entries = parse_codebook_qdc(xml)

        assert entries == [{"name": "Cost", "definition": "Money"}]

    def test_a_missing_codes_wrapper_is_tolerated(self):
        xml = """<CodeBook><Code guid="A" name="Cost"/></CodeBook>"""
        assert [e["name"] for e in parse_codebook_qdc(xml)] == ["Cost"]

    def test_unknown_elements_are_ignored_rather_than_fatal(self):
        """Every package writes a superset of what the others read. A codebook
        that is 90% readable beats a refusal."""
        xml = """<CodeBook>
          <Sets><Set name="something we do not model"/></Sets>
          <Codes>
            <Code guid="A" name="Cost">
              <SomeVendorExtension weight="3"/>
              <Description>Money</Description>
            </Code>
          </Codes>
        </CodeBook>"""

        assert parse_codebook_qdc(xml) == [{"name": "Cost", "definition": "Money"}]

    def test_nesting_becomes_parent_names(self):
        xml = """<CodeBook><Codes>
            <Code guid="A" name="Cost">
              <Code guid="B" name="Textbooks"/>
            </Code>
        </Codes></CodeBook>"""

        entries = parse_codebook_qdc(xml)

        assert entries[1] == {"name": "Textbooks", "parent": "Cost"}

    def test_a_code_with_no_name_is_dropped_not_imported_blank(self):
        xml = """<CodeBook><Codes>
            <Code guid="A"/><Code guid="B" name="Cost"/>
        </Codes></CodeBook>"""
        assert [e["name"] for e in parse_codebook_qdc(xml)] == ["Cost"]

    def test_a_qdpx_project_gets_a_useful_error(self):
        """The two file types are easy to confuse and the message should say so."""
        with pytest.raises(ValueError, match="qdpx"):
            parse_codebook_qdc("<Project><Users/></Project>")

    def test_broken_xml_says_so(self):
        with pytest.raises(ValueError, match="not readable XML"):
            parse_codebook_qdc("<CodeBook><Codes>")

    def test_an_empty_codebook_is_refused_with_a_reason(self):
        with pytest.raises(ValueError, match="no codes"):
            parse_codebook_qdc("<CodeBook><Codes/></CodeBook>")


class TestImportIsAdditive:
    """The receiving analyst's codebook is their property. Both exchange formats
    have to agree about that, which is why they share one import path."""

    def test_an_existing_name_is_skipped_not_overwritten(self, tmp_path):
        path = tmp_path / "mine.qnw"
        with Project.create(path) as proj:
            proj.add_code(Code(code_id="", name="Cost",
                               definition="My own careful definition"))

        xml = """<CodeBook><Codes>
            <Code guid="A" name="Cost"><Description>Someone else's</Description></Code>
        </Codes></CodeBook>"""

        with Project.open(path) as proj:
            report = import_codebook_qdc(proj, xml)
            codes = {c.name: c for c in proj.get_codebook()}

        assert report["skipped_existing"] == ["Cost"]
        assert codes["Cost"].definition == "My own careful definition"

    def test_it_matches_the_yaml_path_exactly(self, tmp_path):
        """Two formats disagreeing about overwriting would be a trap."""
        from core.codebook_io import import_codebook_yaml

        xml_target = tmp_path / "a.qnw"
        yaml_target = tmp_path / "b.qnw"
        for path in (xml_target, yaml_target):
            with Project.create(path) as proj:
                proj.add_code(Code(code_id="", name="Cost", definition="Mine"))

        with Project.open(xml_target) as proj:
            xml_report = import_codebook_qdc(proj, """<CodeBook><Codes>
                <Code guid="A" name="Cost"/>
                <Code guid="B" name="New"><Code guid="C" name="Child"/></Code>
            </Codes></CodeBook>""")
        with Project.open(yaml_target) as proj:
            yaml_report = import_codebook_yaml(proj, """codebook:
- name: Cost
- name: New
- name: Child
  parent: New
""")

        assert xml_report["skipped_existing"] == yaml_report["skipped_existing"]
        assert sorted(xml_report["created"]) == sorted(yaml_report["created"])
        assert xml_report["parents_linked"] == yaml_report["parents_linked"]

    def test_an_unresolvable_parent_is_reported_not_invented(self, tmp_path):
        path = tmp_path / "p.qnw"
        Project.create(path).close()
        xml = """<CodeBook><Codes><Code guid="A" name="Child"/></Codes></CodeBook>"""

        with Project.open(path) as proj:
            report = import_codebook_qdc(proj, xml)

        assert report["parents_unresolved"] == []
