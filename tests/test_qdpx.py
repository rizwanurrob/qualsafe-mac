"""
REFI-QDA whole-project import — `.qdpx` (v4.6, `V5_PLAN.md` §B7).

This is the adoption path: the file NVivo, ATLAS.ti, MAXQDA and QDA Miner all
produce, and reading it is what lets someone try QualSafe on work they have
already done instead of switching to it wholesale.

Three things carry the weight, and they are the three the module's docstring
argues for:

**Imported codings are never yours.** κ compares raters. Merging a colleague's
coding into the analyst's own rater id would inflate agreement to 1.0 — perfect
and meaningless. Half these tests exist for that one property.

**Offsets are verified, never trusted.** What the exporting program counted may
not be what lands in the archive. A selection that does not resolve is skipped
and reported; storing it at a guessed position would produce a wrong excerpt,
and a wrong excerpt looks like evidence.

**What is not imported is named.** A silent partial import is how someone
concludes their data came across when a third of it did not.

The fixtures are written the way *another program* would write them, not the way
this reader would prefer.
"""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.project import Project
from core.qdpx import (
    IMPORTED_RATER_PREFIX, ImportReport, import_parsed, import_qdpx,
    parse_project, rater_id_for, read_project_xml)

TEXT = ("Respondent: the cost of the books was the hard part.\n"
        "Making friends took most of the first term.\n"
        "My advisor was hard to reach in October.")

#: Offsets into TEXT, computed here so the test and the fixture cannot disagree.
COST = (12, 51)
FRIENDS = (52, 94)


def _qde(*, selections: str = "", extra: str = "", text: str = TEXT) -> str:
    return f"""<?xml version="1.0" encoding="utf-8"?>
<Project xmlns="urn:QDA-XML:project:1.0" name="Entry survey" origin="NVivo (Windows) 15">
  <Users>
    <User guid="U-1" name="Dana Okonkwo"/>
    <User guid="U-2" name="Sam Reyes"/>
  </Users>
  <CodeBook>
    <Codes>
      <Code guid="C-1" name="Financial concerns" isCodable="true">
        <Description>Money worries of any kind</Description>
        <Code guid="C-2" name="Textbook cost" isCodable="true"/>
      </Code>
      <Code guid="C-3" name="Sense of belonging" isCodable="true"/>
    </Codes>
  </CodeBook>
  <Variables>
    <Variable guid="V-1" name="class_year" typeOfVariable="Text"/>
  </Variables>
  <Sources>
    <TextSource guid="S-1" name="Interview 01">
      <PlainTextContent>{text}</PlainTextContent>
      <VariableValue>
        <VariableRef targetGUID="V-1"/>
        <TextValue>First-year</TextValue>
      </VariableValue>
      {selections}
    </TextSource>
  </Sources>
  {extra}
</Project>"""


def _selection(start: int, end: int, code: str, user: str = "U-1") -> str:
    return (f'<PlainTextSelection guid="SEL-{start}" name="s" '
            f'startPosition="{start}" endPosition="{end}">'
            f'<Coding guid="CO-{start}" creatingUser="{user}">'
            f'<CodeRef targetGUID="{code}"/></Coding></PlainTextSelection>')


@pytest.fixture()
def parsed():
    return parse_project(_qde(selections=(
        _selection(*COST, "C-1") + _selection(*FRIENDS, "C-3", user="U-2"))))


@pytest.fixture()
def store(tmp_path):
    path = tmp_path / "p.qnw"
    Project.create(path).close()
    return path


class TestParsing:

    def test_the_codebook_comes_across_with_its_hierarchy(self, parsed):
        assert [c["name"] for c in parsed["codes"]] == [
            "Financial concerns", "Textbook cost", "Sense of belonging"]
        assert parsed["codes"][1]["parent"] == "Financial concerns"
        assert parsed["codes"][0]["definition"] == "Money worries of any kind"

    def test_the_source_text_comes_across(self, parsed):
        assert parsed["sources"][0]["text"] == TEXT
        assert parsed["sources"][0]["name"] == "Interview 01"

    def test_a_selection_becomes_a_span_with_its_text(self, parsed):
        first = parsed["sources"][0]["selections"][0]
        assert (first["start"], first["end"]) == COST
        assert first["text"] == TEXT[COST[0]:COST[1]]

    def test_codings_carry_the_coder_who_made_them(self, parsed):
        selections = parsed["sources"][0]["selections"]
        assert selections[0]["codings"][0] == {"code": "Financial concerns",
                                               "user": "Dana Okonkwo"}
        assert selections[1]["codings"][0]["user"] == "Sam Reyes"

    def test_variables_become_descriptor_values(self, parsed):
        assert parsed["variables"]["S-1"] == {"class_year": "First-year"}

    def test_the_origin_is_recorded(self, parsed):
        """So a report can say where a passage came from."""
        assert "NVivo" in parsed["origin"]

    def test_text_stored_as_a_file_is_found(self):
        xml = _qde(text="").replace(
            "<PlainTextContent></PlainTextContent>", "").replace(
            '<TextSource guid="S-1" name="Interview 01">',
            '<TextSource guid="S-1" name="Interview 01" '
            'plainTextPath="internal://Sources/doc1.txt">')

        result = parse_project(xml, {"doc1.txt": TEXT})

        assert result["sources"][0]["text"] == TEXT

    def test_a_source_with_no_text_anywhere_is_not_invented(self):
        xml = _qde(text="").replace("<PlainTextContent></PlainTextContent>", "")
        assert parse_project(xml)["sources"] == []


class TestOffsetsAreVerifiedNeverTrusted:
    """What the exporting program counted may not be what landed in the archive.
    A wrong excerpt looks like evidence, so a doubtful one is not stored."""

    def test_a_selection_past_the_end_of_the_text_is_skipped(self):
        result = parse_project(_qde(selections=_selection(10, 9999, "C-1")))

        assert result["sources"][0]["selections"] == []
        assert result["unresolved_selections"] == 1

    def test_an_inverted_span_is_skipped(self):
        result = parse_project(_qde(selections=_selection(40, 10, "C-1")))
        assert result["unresolved_selections"] == 1

    def test_a_non_numeric_position_is_skipped_not_crashed_on(self):
        xml = _qde(selections=(
            '<PlainTextSelection startPosition="oops" endPosition="12">'
            '<Coding creatingUser="U-1"><CodeRef targetGUID="C-1"/></Coding>'
            '</PlainTextSelection>'))

        assert parse_project(xml)["unresolved_selections"] == 1

    def test_a_good_selection_beside_a_bad_one_still_comes_across(self):
        result = parse_project(_qde(selections=(
            _selection(*COST, "C-1") + _selection(10, 9999, "C-3"))))

        assert len(result["sources"][0]["selections"]) == 1
        assert result["unresolved_selections"] == 1

    def test_the_stored_excerpt_text_matches_its_offsets(self, store, parsed):
        """The store's own invariant, checked end to end."""
        with Project.open(store) as project:
            import_parsed(project, parsed)
            source = project.list_sources()[0]
            for excerpt in project.list_excerpts(source.source_id):
                assert excerpt.text == source.raw_text[excerpt.char_start:excerpt.char_end]


class TestImportedCodingsAreNeverYours:
    """The methodological centre of the feature."""

    def test_they_land_under_an_imported_rater(self, store, parsed):
        with Project.open(store) as project:
            import_parsed(project, parsed)
            raters = set(project.coding_table()["rater_id"])

        assert raters == {"imported_dana_okonkwo", "imported_sam_reyes"}

    def test_no_imported_coding_is_ever_a_human_rater(self, store, parsed):
        """The agreement screen lists `human*` raters as this project's own
        coders. Someone else's coding is not that until the analyst says so."""
        with Project.open(store) as project:
            import_parsed(project, parsed)
            raters = set(project.coding_table()["rater_id"])

        assert not any(r.startswith("human") for r in raters)
        assert all(r.startswith(IMPORTED_RATER_PREFIX) for r in raters)

    def test_two_coders_in_the_file_stay_two_coders(self, store, parsed):
        """Collapsing them would make κ between them impossible to compute."""
        with Project.open(store) as project:
            report = import_parsed(project, parsed)
        assert len(report.raters) == 2

    def test_the_rater_keeps_the_persons_name(self, store, parsed):
        with Project.open(store) as project:
            import_parsed(project, parsed)
            names = {r.rater_id: r.name for r in project.list_raters()}

        assert names["imported_dana_okonkwo"] == "Dana Okonkwo"

    def test_an_unnamed_coder_still_gets_a_stable_id(self):
        assert rater_id_for("") == "imported_unknown"
        assert rater_id_for("   ") == "imported_unknown"

    def test_ids_are_safe_and_stable(self):
        assert rater_id_for("Dana O'Konkwo-Smith") == "imported_dana_o_konkwo_smith"
        assert rater_id_for("Dana") == rater_id_for("dana")


class TestImportingIntoAProject:

    def test_everything_lands(self, store, parsed):
        with Project.open(store) as project:
            report = import_parsed(project, parsed)

        assert (report.codes, report.sources, report.excerpts, report.codings) == (3, 1, 2, 2)
        assert report.descriptors == 1

    def test_the_document_is_a_document(self, store, parsed):
        with Project.open(store) as project:
            import_parsed(project, parsed)
            source = project.list_sources()[0]

        assert source.type == "document"
        assert source.metadata["title"] == "Interview 01"
        assert "NVivo" in source.metadata["imported_from"]

    def test_descriptors_come_across(self, store, parsed):
        with Project.open(store) as project:
            import_parsed(project, parsed)
            descriptors = project.descriptor_table()

        assert descriptors.iloc[0]["key"] == "class_year"
        assert descriptors.iloc[0]["value"] == "First-year"

    def test_an_existing_code_is_not_overwritten(self, store, parsed):
        """Same rule as every other import path here."""
        from core.model import Code

        with Project.open(store) as project:
            project.add_code(Code(code_id="", name="Financial concerns",
                                  definition="My own careful definition"))
            import_parsed(project, parsed)
            codes = {c.name: c for c in project.get_codebook()}

        assert codes["Financial concerns"].definition == "My own careful definition"

    def test_codings_still_attach_to_a_pre_existing_code(self, store, parsed):
        """Skipping the code must not silently drop the codings that use it."""
        from core.model import Code

        with Project.open(store) as project:
            project.add_code(Code(code_id="", name="Financial concerns"))
            import_parsed(project, parsed)
            coding = project.coding_table()

        assert "Financial concerns" in set(coding["code_name"])

    def test_a_coding_referencing_an_unknown_code_is_dropped_not_invented(self, store):
        parsed = parse_project(_qde(selections=_selection(*COST, "C-999")))
        with Project.open(store) as project:
            report = import_parsed(project, parsed)
        assert report.codings == 0


class TestWhatIsNotImportedIsNamed:
    """A silent partial import is how someone concludes their data came across
    when a third of it did not."""

    def test_notes_and_sets_are_counted(self):
        extra = ("<Notes><Note guid='N-1' name='memo'/></Notes>"
                 "<Sets><Set guid='X-1' name='a set'/></Sets>")
        result = parse_project(_qde(extra=extra))

        assert result["skipped"] == {"note": 1, "set": 1}

    def test_media_sources_are_counted(self):
        xml = _qde().replace("</Sources>",
                             "<PictureSource guid='P-1' name='photo'/>"
                             "<AudioSource guid='A-1' name='tape'/></Sources>")
        result = parse_project(xml)

        assert result["skipped"]["picture source"] == 1
        assert result["skipped"]["audio source"] == 1

    def test_the_summary_says_all_of_it(self):
        report = ImportReport(codes=3, sources=1, excerpts=2, codings=2,
                              descriptors=1, raters=["imported_dana"],
                              unresolved_selections=2, skipped={"note": 4})

        summary = report.summary()

        assert "1 document(s)" in summary and "3 code(s)" in summary
        assert "imported_dana" in summary
        assert "2 passage(s) were skipped" in summary
        assert "4 note" in summary

    def test_a_clean_import_says_nothing_alarming(self):
        summary = ImportReport(codes=1, sources=1, excerpts=1, codings=1).summary()
        assert "skipped" not in summary and "Not imported" not in summary


class TestTheArchive:

    def _write(self, path: Path, xml: str, extra_files=None) -> Path:
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("project.qde", xml)
            for name, content in (extra_files or {}).items():
                archive.writestr(name, content)
        return path

    def test_a_real_archive_imports(self, tmp_path, store):
        path = self._write(tmp_path / "p.qdpx",
                           _qde(selections=_selection(*COST, "C-1")))

        with Project.open(store) as project:
            report = import_qdpx(project, path)

        assert report.sources == 1 and report.codings == 1

    def test_text_in_a_sources_folder_is_found(self, tmp_path, store):
        xml = _qde(text="").replace(
            "<PlainTextContent></PlainTextContent>", "").replace(
            '<TextSource guid="S-1" name="Interview 01">',
            '<TextSource guid="S-1" name="Interview 01" '
            'plainTextPath="internal://Sources/doc1.txt">')
        path = self._write(tmp_path / "p.qdpx", xml, {"Sources/doc1.txt": TEXT})

        with Project.open(store) as project:
            report = import_qdpx(project, path)
            assert project.list_sources()[0].raw_text == TEXT
        assert report.sources == 1

    def test_a_differently_cased_entry_is_found(self, tmp_path):
        """Writers disagree about the case of the entry name."""
        path = tmp_path / "p.qdpx"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("Project.QDE", _qde())

        assert "Project" in read_project_xml(path)

    def test_a_qdc_codebook_gets_a_useful_error(self, tmp_path):
        """The two file types are easy to confuse; the message should point at
        the page that reads the other one."""
        path = tmp_path / "codebook.qdc"
        path.write_text("<CodeBook/>", encoding="utf-8")

        with pytest.raises(ValueError, match="Codebook page"):
            read_project_xml(path)

    def test_a_zip_without_a_project_file_says_so(self, tmp_path):
        path = tmp_path / "p.qdpx"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("readme.txt", "nothing here")

        with pytest.raises(ValueError, match="no `project.qde`"):
            read_project_xml(path)

    def test_broken_xml_says_so(self):
        with pytest.raises(ValueError, match="not readable XML"):
            parse_project("<Project><Sources>")

    def test_the_wrong_root_element_says_what_it_found(self):
        with pytest.raises(ValueError, match="CodeBook"):
            parse_project("<CodeBook/>")
