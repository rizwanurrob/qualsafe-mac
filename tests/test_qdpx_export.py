"""
REFI-QDA whole-project export — `.qdpx` (v4.6, `V5_PLAN.md` §B7).

Import is the adoption path. This is the exit promise: a researcher can take
their work to NVivo, MAXQDA or ATLAS.ti, hand it to a colleague who uses one, or
deposit it in an archive. Together the two make "no lock-in" a fact instead of a
claim, which for a free tool arguing against commercial packages on exactly that
ground is the whole point.

**The round trip is the test that matters.** Export, import into a fresh project,
and everything has to arrive: the codes and their hierarchy, the sources and
their text, the excerpt offsets, the codings, and — the one most easily lost —
which coder made which coding. That check needs no rival's file and it catches
what a schema validator cannot: an offset written against the wrong text, a
coding attributed to the wrong person.
"""

from __future__ import annotations

import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.model import Code, CodeApplication, Descriptor, Excerpt, Rater, Source
from core.project import Project
from core.qdpx import PROJECT_ENTRY, import_qdpx, parse_project
from core.qdpx_export import SOURCES_DIR, export_qdpx

TEXT = ("Respondent: the cost of the books was the hard part.\n"
        "Making friends took most of the first term.")
COST = (12, 51)
FRIENDS = (52, len(TEXT))


@pytest.fixture()
def coded(tmp_path):
    """A project with hierarchy, two coders, offsets and a descriptor."""
    path = tmp_path / "source.qnw"
    with Project.create(path) as project:
        parent = project.add_code(Code(code_id="", name="Financial concerns",
                                       definition="Money worries"))
        child = project.add_code(Code(code_id="", name="Textbook cost",
                                      parent_id=parent))
        belonging = project.add_code(Code(code_id="", name="Sense of belonging"))

        project.add_rater(Rater(rater_id="human_primary", kind="human", name="Dana"))
        project.add_rater(Rater(rater_id="human_secondary", kind="human", name="Sam"))

        source_id = project.add_source(Source(
            source_id="", type="document", raw_text=TEXT, label="Interview 01",
            metadata={"title": "Interview 01"}))
        project.set_descriptor(Descriptor(source_id=source_id, key="class_year",
                                          value="First-year"))

        first = project.add_excerpt(Excerpt(
            excerpt_id="", source_id=source_id, text=TEXT[COST[0]:COST[1]],
            char_start=COST[0], char_end=COST[1]))
        second = project.add_excerpt(Excerpt(
            excerpt_id="", source_id=source_id, text=TEXT[FRIENDS[0]:FRIENDS[1]],
            char_start=FRIENDS[0], char_end=FRIENDS[1]))

        project.apply_code(CodeApplication(application_id="", excerpt_id=first,
                                           code_id=child, coder="human",
                                           rater_id="human_primary"))
        project.apply_code(CodeApplication(application_id="", excerpt_id=second,
                                           code_id=belonging, coder="human",
                                           rater_id="human_secondary"))
    return path


@pytest.fixture()
def exported(coded, tmp_path):
    with Project.open(coded) as project:
        return export_qdpx(project, tmp_path / "out.qdpx", project_name="Entry survey")


def _manifest(path: Path) -> ET.Element:
    with zipfile.ZipFile(path) as archive:
        return ET.fromstring(archive.read(PROJECT_ENTRY).decode("utf-8"))


def _tag(element) -> str:
    return element.tag.rsplit("}", 1)[-1]


class TestTheArchive:

    def test_it_is_a_zip_with_a_project_file(self, exported):
        with zipfile.ZipFile(exported) as archive:
            names = archive.namelist()
        assert PROJECT_ENTRY in names

    def test_source_text_is_written_as_a_file(self, exported):
        """Both forms are legal; files are what the other packages write, and
        inlining a corpus into one XML document makes a file nothing can open."""
        with zipfile.ZipFile(exported) as archive:
            texts = [n for n in archive.namelist() if n.startswith(SOURCES_DIR + "/")]
            assert len(texts) == 1
            assert archive.read(texts[0]).decode("utf-8") == TEXT

    def test_the_source_points_at_its_file(self, exported):
        root = _manifest(exported)
        source = next(e for e in root.iter() if _tag(e) == "TextSource")
        assert source.get("plainTextPath", "").endswith(".txt")

    def test_the_origin_names_this_program(self, exported):
        assert "QualSafe" in _manifest(exported).get("origin", "")

    def test_exporting_twice_produces_the_same_manifest(self, coded, tmp_path):
        """Stable GUIDs, so a diff between two exports shows what changed."""
        with Project.open(coded) as project:
            first = export_qdpx(project, tmp_path / "a.qdpx")
            second = export_qdpx(project, tmp_path / "b.qdpx")

        def manifest_without_timestamp(path):
            root = _manifest(path)
            root.attrib.pop("creationDateTime", None)
            root.attrib.pop("name", None)
            return ET.tostring(root, encoding="unicode")

        assert manifest_without_timestamp(first) == manifest_without_timestamp(second)


class TestTheManifest:

    def test_the_codebook_is_nested(self, exported):
        root = _manifest(exported)
        codes = next(e for e in root.iter() if _tag(e) == "Codes")
        top = [c for c in codes if _tag(c) == "Code"]

        assert {c.get("name") for c in top} == {"Financial concerns",
                                                "Sense of belonging"}
        parent = next(c for c in top if c.get("name") == "Financial concerns")
        assert [c.get("name") for c in parent if _tag(c) == "Code"] == ["Textbook cost"]

    def test_every_rater_becomes_a_user(self, exported):
        root = _manifest(exported)
        names = {u.get("name") for u in root.iter() if _tag(u) == "User"}
        assert names == {"Dana", "Sam"}

    def test_descriptors_become_variables_with_values(self, exported):
        root = _manifest(exported)
        variables = {v.get("name") for v in root.iter() if _tag(v) == "Variable"}
        values = [v for v in root.iter() if _tag(v) == "VariableValue"]

        assert variables == {"class_year"}
        assert len(values) == 1

    def test_selections_carry_their_offsets(self, exported):
        root = _manifest(exported)
        spans = {(int(s.get("startPosition")), int(s.get("endPosition")))
                 for s in root.iter() if _tag(s) == "PlainTextSelection"}
        assert spans == {COST, FRIENDS}

    def test_a_coding_names_the_coder_who_made_it(self, exported):
        """The property most easily lost, and the one κ depends on."""
        root = _manifest(exported)
        users = {u.get("guid"): u.get("name")
                 for u in root.iter() if _tag(u) == "User"}
        coders = {users[c.get("creatingUser")]
                  for c in root.iter() if _tag(c) == "Coding"}
        assert coders == {"Dana", "Sam"}

    def test_an_uncoded_excerpt_is_not_written(self, tmp_path):
        """A selection with no coding is not a finding, and whole-response
        excerpts alone would fill the file with empty highlights."""
        path = tmp_path / "bare.qnw"
        with Project.create(path) as project:
            source_id = project.add_source(Source(
                source_id="", type="document", raw_text=TEXT, label="Doc"))
            project.add_excerpt(Excerpt(excerpt_id="", source_id=source_id,
                                        text=TEXT, char_start=0, char_end=len(TEXT)))
            out = export_qdpx(project, tmp_path / "out.qdpx")

        root = _manifest(out)
        assert not [s for s in root.iter() if _tag(s) == "PlainTextSelection"]

    def test_an_empty_project_still_exports(self, tmp_path):
        path = tmp_path / "empty.qnw"
        Project.create(path).close()
        with Project.open(path) as project:
            out = export_qdpx(project, tmp_path / "empty.qdpx")
        assert _tag(_manifest(out)) == "Project"


class TestTheRoundTrip:
    """The test that matters, and the one that needs no rival's file."""

    @pytest.fixture()
    def reimported(self, exported, tmp_path):
        receiving = tmp_path / "receiving.qnw"
        Project.create(receiving).close()
        with Project.open(receiving) as project:
            report = import_qdpx(project, exported)
        return receiving, report

    def test_the_codes_and_their_hierarchy_survive(self, reimported):
        receiving, _report = reimported
        with Project.open(receiving) as project:
            codes = {c.name: c for c in project.get_codebook()}

        assert set(codes) == {"Financial concerns", "Textbook cost",
                              "Sense of belonging"}
        assert codes["Textbook cost"].parent_id == codes["Financial concerns"].code_id
        assert codes["Financial concerns"].definition == "Money worries"

    def test_the_source_text_survives_exactly(self, reimported):
        receiving, _report = reimported
        with Project.open(receiving) as project:
            assert project.list_sources()[0].raw_text == TEXT

    def test_the_offsets_survive_and_still_resolve(self, reimported):
        """The failure a schema validator cannot catch: an offset written
        against text that is not the text it indexes."""
        receiving, report = reimported
        with Project.open(receiving) as project:
            source = project.list_sources()[0]
            spans = {(e.char_start, e.char_end)
                     for e in project.list_excerpts(source.source_id)}
            for excerpt in project.list_excerpts(source.source_id):
                assert excerpt.text == source.raw_text[excerpt.char_start:excerpt.char_end]

        assert spans == {COST, FRIENDS}
        assert report.unresolved_selections == 0

    def test_every_coding_survives(self, reimported):
        receiving, _report = reimported
        with Project.open(receiving) as project:
            coding = project.coding_table()

        assert len(coding) == 2
        assert set(coding["code_name"]) == {"Textbook cost", "Sense of belonging"}

    def test_the_two_coders_stay_two_coders(self, reimported):
        """Attribution is what κ is computed over. Collapsing the coders would
        make agreement uncomputable and the round trip a lie."""
        receiving, report = reimported
        with Project.open(receiving) as project:
            raters = set(project.coding_table()["rater_id"])

        assert len(raters) == 2
        assert raters == {"imported_dana", "imported_sam"}
        assert len(report.raters) == 2

    def test_the_right_coder_keeps_the_right_coding(self, reimported):
        """Not just two coders — the *same* two, on the same passages."""
        receiving, _report = reimported
        with Project.open(receiving) as project:
            coding = project.coding_table()
            pairs = set(zip(coding["rater_id"], coding["code_name"]))

        assert pairs == {("imported_dana", "Textbook cost"),
                         ("imported_sam", "Sense of belonging")}

    def test_descriptors_survive(self, reimported):
        receiving, _report = reimported
        with Project.open(receiving) as project:
            descriptors = project.descriptor_table()

        assert len(descriptors) == 1
        assert descriptors.iloc[0]["key"] == "class_year"
        assert descriptors.iloc[0]["value"] == "First-year"

    def test_nothing_is_reported_as_skipped(self, reimported):
        """A clean round trip should have nothing to apologise for."""
        _receiving, report = reimported
        assert report.skipped == {}
        assert report.unresolved_selections == 0

    def test_our_own_parser_reads_our_own_manifest(self, exported):
        """Belt and braces: the reader path used on other people's files, run
        over ours, so a change to either side cannot silently diverge."""
        with zipfile.ZipFile(exported) as archive:
            xml = archive.read(PROJECT_ENTRY).decode("utf-8")
            texts = {n.rsplit("/", 1)[-1]: archive.read(n).decode("utf-8")
                     for n in archive.namelist() if n.endswith(".txt")}

        parsed = parse_project(xml, texts)

        assert len(parsed["codes"]) == 3
        assert len(parsed["sources"]) == 1
        assert len(parsed["sources"][0]["selections"]) == 2
