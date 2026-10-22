"""
Tests for the SQLite project store (Phase 0b), core/project.py.

Offline, no models. Covers: schema init, CRUD round-trips (close + reopen),
codebook hierarchy + weight scale, descriptors + typed fields, rater/run
provenance, foreign-key enforcement, code_frequency, and JSON export/import.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.model import (
    Code, CodeApplication, Descriptor, DescriptorField, Excerpt, Memo, Rater,
    RunManifest, Source, WeightScale,
)
from core.project import Project, new_id


def _seed(p: Project):
    """Populate one of everything and return the ids used."""
    src = Source(source_id="src1", type="survey_response", raw_text="advising was great but the portal is broken",
                 label="Q1", metadata={"batch": "fall"})
    p.add_source(src)
    eid = p.add_whole_response_excerpt(src)
    parent = p.add_code(Code(code_id="experience", name="Experience"))
    child = p.add_code(Code(
        code_id="advising", name="Advising", parent_id="experience",
        weight_scale=WeightScale(kind="valence", min_value=-1.0, max_value=1.0),
    ))
    p.add_rater(Rater(rater_id="rater_bart", kind="transformer", model_id="facebook/bart-large-mnli"))
    p.add_run(RunManifest(run_id="run1", package_version="v3", mode="survey",
                          engine="transformer", model="facebook/bart-large-mnli",
                          thresholds={"top1": 0.55}, counts={"rows": 1}))
    p.apply_code(CodeApplication(
        application_id="app1", excerpt_id=eid, code_id="advising", coder="transformer",
        rater_id="rater_bart", run_id="run1", weight=0.8, confidence=0.72, margin=0.5,
        rationale="mentions advising positively"))
    p.set_descriptor(Descriptor(source_id="src1", key="First_Generation", value="Yes"))
    p.add_descriptor_field(DescriptorField(key="Age_Band", dtype="ordinal",
                                           ordered_levels=["18-19", "20-21", "22+"]))
    p.add_memo(Memo(memo_id="memo1", target_type="code", target_id="advising",
                    text="captures advisor interactions", author="human"))
    return eid


class TestProjectBasics:
    def test_new_id_has_prefix(self):
        assert new_id("exc").startswith("exc_")
        assert new_id("exc") != new_id("exc")

    def test_create_and_reopen_roundtrips_everything(self, tmp_path):
        db = tmp_path / "study.qnw"
        with Project.create(db) as p:
            _seed(p)

        # Reopen: all entities persisted.
        with Project.open(db) as p:
            src = p.get_source("src1")
            assert src is not None and src.metadata == {"batch": "fall"}
            excerpts = p.list_excerpts("src1")
            assert len(excerpts) == 1 and excerpts[0].verify_offsets(src.raw_text)
            assert p.code_frequency() == {"advising": 1}
            apps = p.list_applications()
            assert apps[0].rater_id == "rater_bart" and apps[0].run_id == "run1"
            assert apps[0].weight == 0.8 and apps[0].confidence == 0.72
            assert p.get_descriptors("src1") == {"First_Generation": "Yes"}
            assert p.list_memos()[0].target_id == "advising"
            assert p.list_runs()[0].thresholds == {"top1": 0.55}

    def test_open_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            Project.open(tmp_path / "nope.qnw")


class TestCodebookAndScales:
    def test_hierarchy_and_weight_scale_persist(self, tmp_path):
        with Project.create(tmp_path / "c.qnw") as p:
            _seed(p)
            codes = {c.code_id: c for c in p.get_codebook()}
            assert codes["advising"].parent_id == "experience"
            ws = codes["advising"].weight_scale
            assert ws is not None and ws.kind == "valence" and ws.contains(0.8)
            # Parent has no weight scale.
            assert codes["experience"].weight_scale is None


class TestDescriptorFields:
    def test_ordinal_field_roundtrips_levels(self, tmp_path):
        with Project.create(tmp_path / "d.qnw") as p:
            _seed(p)
            fields = {f.key: f for f in p.get_descriptor_fields()}
            assert fields["Age_Band"].dtype == "ordinal"
            assert fields["Age_Band"].ordered_levels == ["18-19", "20-21", "22+"]

    def test_set_descriptor_upserts(self, tmp_path):
        with Project.create(tmp_path / "d2.qnw") as p:
            p.add_source(Source(source_id="s", type="survey_response", raw_text="x"))
            p.set_descriptor(Descriptor(source_id="s", key="program", value="Nursing"))
            p.set_descriptor(Descriptor(source_id="s", key="program", value="Finance"))
            assert p.get_descriptors("s") == {"program": "Finance"}


class TestForeignKeys:
    def test_excerpt_requires_existing_source(self, tmp_path):
        with Project.create(tmp_path / "fk.qnw") as p:
            with pytest.raises(sqlite3.IntegrityError):
                p.add_excerpt(Excerpt(excerpt_id="e", source_id="missing",
                                      text="x", char_start=0, char_end=1))

    def test_application_requires_existing_code(self, tmp_path):
        with Project.create(tmp_path / "fk2.qnw") as p:
            src = Source(source_id="s", type="survey_response", raw_text="hello")
            p.add_source(src)
            eid = p.add_whole_response_excerpt(src)
            with pytest.raises(sqlite3.IntegrityError):
                p.apply_code(CodeApplication(application_id="a", excerpt_id=eid, code_id="ghost"))


class TestIdMinting:
    def test_ids_minted_when_absent(self, tmp_path):
        with Project.create(tmp_path / "m.qnw") as p:
            src = Source(source_id="", type="survey_response", raw_text="text here")
            sid = p.add_source(src)
            assert sid.startswith("src_")
            # excerpt with empty id gets minted too
            eid = p.add_excerpt(Excerpt(excerpt_id="", source_id=sid, text="text here",
                                        char_start=0, char_end=9))
            assert eid.startswith("exc_")


class TestCodebookEditing:
    def test_rename_and_define(self, tmp_path):
        with Project.create(tmp_path / "e.qnw") as p:
            p.add_code(Code(code_id="c1", name="Old"))
            p.rename_code("c1", "New")
            p.set_code_definition("c1", "means X")
            c = {x.code_id: x for x in p.get_codebook()}["c1"]
            assert c.name == "New" and c.definition == "means X"

    def test_reparent_and_cycle_guard(self, tmp_path):
        with Project.create(tmp_path / "e2.qnw") as p:
            p.add_code(Code(code_id="parent", name="P"))
            p.add_code(Code(code_id="child", name="C"))
            p.set_code_parent("child", "parent")
            assert {x.code_id: x for x in p.get_codebook()}["child"].parent_id == "parent"
            # Making parent a child of child would create a cycle.
            with pytest.raises(ValueError, match="cycle"):
                p.set_code_parent("parent", "child")

    def test_merge_reassigns_applications_and_removes_code(self, tmp_path):
        with Project.create(tmp_path / "e3.qnw") as p:
            src = Source(source_id="s", type="survey_response", raw_text="hello world")
            p.add_source(src)
            eid = p.add_whole_response_excerpt(src)
            p.add_code(Code(code_id="keep", name="Keep"))
            p.add_code(Code(code_id="dupe", name="Dupe"))
            p.apply_code(CodeApplication(application_id="", excerpt_id=eid, code_id="dupe"))
            p.merge_codes("dupe", "keep")
            assert "dupe" not in {c.code_id for c in p.get_codebook()}
            assert p.code_frequency() == {"keep": 1}   # application moved

    def test_delete_code_cascades_applications(self, tmp_path):
        with Project.create(tmp_path / "e4.qnw") as p:
            src = Source(source_id="s", type="survey_response", raw_text="hi")
            p.add_source(src)
            eid = p.add_whole_response_excerpt(src)
            p.add_code(Code(code_id="c", name="C"))
            p.apply_code(CodeApplication(application_id="", excerpt_id=eid, code_id="c"))
            p.delete_code("c")
            assert p.get_codebook() == []
            assert p.list_applications() == []


class TestJsonInterchange:
    def test_export_then_import_roundtrips(self, tmp_path):
        db1 = tmp_path / "orig.qnw"
        with Project.create(db1) as p:
            _seed(p)
            bundle = p.export_json(tmp_path / "bundle.json")
        assert bundle.exists()

        db2 = tmp_path / "rebuilt.qnw"
        with Project.import_json(tmp_path / "bundle.json", db2) as p2:
            assert p2.get_source("src1") is not None
            assert p2.code_frequency() == {"advising": 1}
            codes = {c.code_id: c for c in p2.get_codebook()}
            assert codes["advising"].weight_scale.kind == "valence"
            assert p2.get_descriptors("src1") == {"First_Generation": "Yes"}
            assert p2.list_applications()[0].run_id == "run1"
