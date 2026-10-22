"""
Conformance: what we write is what the REFI-QDA standard says, not what we think.

Every other interoperability test in this suite compares this codebase against
itself. The round trip exports and re-imports; the reader tests use fixtures this
project wrote. Both are worth having and neither can catch the one error that
matters most here:

    **Two agreeing implementations of a misreading look exactly like a correct
    one.**

Validating against the published XSD is the only check that has an opinion this
codebase did not supply. It immediately found two errors that had passed every
other test:

- the codebook namespace written `urn:QDA-XML:codebook:1:0`, a colon where the
  standard has a dot;
- `VariableValue` written before `PlainTextSelection`, when `TextSourceType` is
  an `xsd:sequence` and order is part of validity.

Both would have produced files NVivo and MAXQDA rejected, while every test here
stayed green.

The schemas are vendored in `tests/fixtures/refi_qda/` — see the README there for
why they are not fetched.
"""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

etree = pytest.importorskip(
    "lxml.etree",
    reason="XSD validation needs lxml; it arrives with python-docx in the full "
           "install, and this check is skipped rather than faked without it")

from core.model import (  # noqa: E402
    Code, CodeApplication, Descriptor, Excerpt, Rater, Source)
from core.project import Project  # noqa: E402
from core.qdpx import PROJECT_ENTRY  # noqa: E402
from core.qdpx_export import export_qdpx  # noqa: E402
from core.refi_qda import export_codebook_qdc  # noqa: E402

SCHEMAS = Path(__file__).parent / "fixtures" / "refi_qda"
TEXT = ("Respondent: the cost of the books was the hard part.\n"
        "Making friends took most of the first term.")


def _schema(name: str):
    return etree.XMLSchema(etree.parse(str(SCHEMAS / name)))


def _assert_valid(schema, xml_bytes: bytes) -> None:
    document = etree.fromstring(xml_bytes)
    if schema.validate(document):
        return
    problems = "\n".join(f"  line {e.line}: {e.message}" for e in schema.error_log)
    raise AssertionError("does not conform to the published schema:\n" + problems)


@pytest.fixture()
def rich_project(tmp_path):
    """Everything the exporter can emit, so validation sees all of it."""
    path = tmp_path / "p.qnw"
    with Project.create(path) as project:
        parent = project.add_code(Code(code_id="", name="Financial concerns",
                                       definition="Money worries"))
        child = project.add_code(Code(code_id="", name="Textbook cost",
                                      parent_id=parent))
        other = project.add_code(Code(code_id="", name="Sense of belonging"))
        project.add_rater(Rater(rater_id="human_primary", kind="human", name="Dana"))
        project.add_rater(Rater(rater_id="human_secondary", kind="human", name="Sam"))

        source_id = project.add_source(Source(
            source_id="", type="document", raw_text=TEXT, label="Interview 01"))
        project.set_descriptor(Descriptor(source_id=source_id, key="class_year",
                                          value="First-year"))
        project.set_descriptor(Descriptor(source_id=source_id, key="programme",
                                          value="Nursing"))

        first = project.add_excerpt(Excerpt(
            excerpt_id="", source_id=source_id, text=TEXT[12:51],
            char_start=12, char_end=51))
        second = project.add_excerpt(Excerpt(
            excerpt_id="", source_id=source_id, text=TEXT[52:],
            char_start=52, char_end=len(TEXT)))
        project.apply_code(CodeApplication(application_id="", excerpt_id=first,
                                           code_id=child, coder="human",
                                           rater_id="human_primary"))
        project.apply_code(CodeApplication(application_id="", excerpt_id=second,
                                           code_id=other, coder="human",
                                           rater_id="human_secondary"))
    return path


class TestTheSchemasAreUsable:

    def test_both_are_present_and_parse(self):
        """A vendored schema that stopped parsing would make every check below
        vacuously pass."""
        for name in ("Codebook.xsd", "Project.xsd"):
            assert (SCHEMAS / name).exists(), f"{name} missing from fixtures"
            _schema(name)

    def test_they_declare_the_namespaces_our_modules_use(self):
        """The check that would have caught the `1:0` typo on its own."""
        from core.qdpx import NAMESPACE as PROJECT_NS
        from core.refi_qda import NAMESPACE as CODEBOOK_NS

        codebook = etree.parse(str(SCHEMAS / "Codebook.xsd")).getroot()
        project = etree.parse(str(SCHEMAS / "Project.xsd")).getroot()

        assert codebook.get("targetNamespace") == CODEBOOK_NS
        assert project.get("targetNamespace") == PROJECT_NS


class TestTheCodebookConforms:

    def test_an_exported_codebook_validates(self, rich_project):
        with Project.open(rich_project) as project:
            xml = export_codebook_qdc(project)

        _assert_valid(_schema("Codebook.xsd"), xml.encode("utf-8"))

    def test_an_empty_codebook_is_refused_rather_than_written_invalid(self, tmp_path):
        """`CodesType` requires at least one `Code`, so an empty codebook has no
        valid representation in this format at all.

        Refusing beats emitting something NVivo rejects: the analyst can see
        their codebook is empty, and this program cannot explain a failure that
        happens inside another one.
        """
        path = tmp_path / "empty.qnw"
        Project.create(path).close()

        with Project.open(path) as project:
            with pytest.raises(ValueError, match="no codes to export"):
                export_codebook_qdc(project)


class TestTheProjectConforms:

    def test_an_exported_project_validates(self, rich_project, tmp_path):
        with Project.open(rich_project) as project:
            out = export_qdpx(project, tmp_path / "out.qdpx", project_name="Survey")

        with zipfile.ZipFile(out) as archive:
            _assert_valid(_schema("Project.xsd"), archive.read(PROJECT_ENTRY))

    def test_an_empty_project_validates(self, tmp_path):
        path = tmp_path / "empty.qnw"
        Project.create(path).close()
        with Project.open(path) as project:
            out = export_qdpx(project, tmp_path / "empty.qdpx", project_name="Empty")

        with zipfile.ZipFile(out) as archive:
            _assert_valid(_schema("Project.xsd"), archive.read(PROJECT_ENTRY))

    def test_a_project_with_no_descriptors_validates(self, tmp_path):
        """The Variables element is omitted entirely; an empty one is not valid."""
        path = tmp_path / "bare.qnw"
        with Project.create(path) as project:
            code = project.add_code(Code(code_id="", name="Cost"))
            source_id = project.add_source(Source(
                source_id="", type="document", raw_text=TEXT, label="Doc"))
            excerpt = project.add_excerpt(Excerpt(
                excerpt_id="", source_id=source_id, text=TEXT[0:10],
                char_start=0, char_end=10))
            project.apply_code(CodeApplication(
                application_id="", excerpt_id=excerpt, code_id=code,
                coder="human", rater_id="human_primary"))
            out = export_qdpx(project, tmp_path / "bare.qdpx", project_name="Bare")

        with zipfile.ZipFile(out) as archive:
            _assert_valid(_schema("Project.xsd"), archive.read(PROJECT_ENTRY))

    def test_element_order_is_what_the_sequence_demands(self, rich_project, tmp_path):
        """Pinned separately from validation so a regression names itself.

        `TextSourceType` is an xsd:sequence, so VariableValue after the
        selections is correctness, not layout — and getting it wrong produced a
        file this project's own reader accepted.
        """
        with Project.open(rich_project) as project:
            out = export_qdpx(project, tmp_path / "out.qdpx")

        with zipfile.ZipFile(out) as archive:
            root = etree.fromstring(archive.read(PROJECT_ENTRY))

        source = next(e for e in root.iter()
                      if e.tag.rsplit("}", 1)[-1] == "TextSource")
        order = [c.tag.rsplit("}", 1)[-1] for c in source]
        assert order.index("PlainTextSelection") < order.index("VariableValue")
