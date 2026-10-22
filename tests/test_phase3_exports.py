"""
Tests for Phase 3 — export bundle, memos, guided sample project (v3.4).

The load-bearing test is the redaction guarantee: no source's raw text may appear
anywhere in a no-raw-text bundle, including the regenerated report and any memo.
"""

from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.model import Code, CodeApplication, Descriptor, Memo, Rater, Source
from core.project import Project, new_id
from exports.bundle import build_bundle


SECRET_QUOTE = "my advisor Dr Chen personally helped me every single week"


def _fixture_store(path):
    """A store with sources, codes, human+model codings, a descriptor, and a memo."""
    with Project.create(path) as p:
        p.add_rater(Rater(rater_id="transformer", kind="transformer", name="model"))
        p.add_rater(Rater(rater_id="human_primary", kind="human", name="analyst"))
        belonging = p.add_code(Code(code_id="", name="Belonging", definition="sense of fitting in"))
        cost = p.add_code(Code(code_id="", name="Cost", definition="money worries"))

        rows = [
            ("r1", SECRET_QUOTE, "First_Gen", "Yes", [belonging]),
            ("r2", "tuition is far too expensive for me", "First_Gen", "No", [cost]),
            ("r3", "I felt at home right away on campus", "First_Gen", "Yes", [belonging]),
            ("r4", "worried about paying for books", "First_Gen", "No", [cost]),
        ]
        for rid, text, dkey, dval, codes in rows:
            src = Source(source_id=new_id("src"), type="survey_response", raw_text=text,
                         label="Q1", metadata={"response_id": rid, "question_text": "Q1"})
            p.add_source(src)
            exc = p.add_whole_response_excerpt(src)
            p.set_descriptor(Descriptor(source_id=src.source_id, key=dkey, value=dval))
            for c in codes:
                p.apply_code(CodeApplication(application_id="", excerpt_id=exc, code_id=c,
                                             coder="transformer", rater_id="transformer"))
                p.apply_code(CodeApplication(application_id="", excerpt_id=exc, code_id=c,
                                             coder="human", rater_id="human_primary"))
        # A memo that quotes raw text — the sneaky leak path.
        p.add_memo(Memo(memo_id="", target_type="project", target_id=None,
                        text=f"Striking: {SECRET_QUOTE}", author="human"))
    return path


def _zip_members(zip_path):
    with zipfile.ZipFile(zip_path) as zf:
        return {name: zf.read(name).decode("utf-8", errors="replace") for name in zf.namelist()}


class TestRedaction:
    def test_no_raw_text_bundle_leaks_nothing(self, tmp_path):
        """The whole point: walk every member, assert the quote appears nowhere."""
        store = _fixture_store(tmp_path / "s.qnw")
        out = build_bundle(store, tmp_path / "redacted.zip",
                           include_raw_text=False, include_memos=True,
                           descriptor_keys=["First_Gen"])
        members = _zip_members(out)
        for name, content in members.items():
            assert SECRET_QUOTE not in content, f"raw text leaked into {name}"
            # A distinctive substring too, in case of partial copies.
            assert "Dr Chen" not in content, f"partial raw text leaked into {name}"

    def test_raw_text_bundle_includes_quotes_when_asked(self, tmp_path):
        store = _fixture_store(tmp_path / "s2.qnw")
        out = build_bundle(store, tmp_path / "full.zip", include_raw_text=True,
                           include_memos=True)
        members = _zip_members(out)
        assert any(SECRET_QUOTE in c for c in members.values())

    def test_redacted_excerpts_are_marked(self, tmp_path):
        store = _fixture_store(tmp_path / "s3.qnw")
        out = build_bundle(store, tmp_path / "r.zip", include_raw_text=False)
        excerpts = pd.read_csv(io.StringIO(_zip_members(out)["excerpts.csv"]))
        assert (excerpts["text"] == "[REDACTED]").all()

    def test_responses_scored_and_embeddings_never_included(self, tmp_path):
        store = _fixture_store(tmp_path / "s4.qnw")
        out = build_bundle(store, tmp_path / "r2.zip")
        names = set(_zip_members(out))
        assert not any("responses_scored" in n or n.endswith(".npy") for n in names)


class TestBundleContents:
    def test_core_members_present(self, tmp_path):
        store = _fixture_store(tmp_path / "s5.qnw")
        out = build_bundle(store, tmp_path / "b.zip")
        names = set(_zip_members(out))
        assert {"manifest.json", "report.md", "codebook.csv",
                "code_frequency.csv", "excerpts.csv"} <= names

    def test_arcnames_are_relative(self, tmp_path):
        store = _fixture_store(tmp_path / "s6.qnw")
        out = build_bundle(store, tmp_path / "b2.zip")
        with zipfile.ZipFile(out) as zf:
            for name in zf.namelist():
                assert not name.startswith("/") and ":" not in name  # no abs/user paths

    def test_descriptors_default_none(self, tmp_path):
        store = _fixture_store(tmp_path / "s7.qnw")
        out = build_bundle(store, tmp_path / "b3.zip")  # no descriptor_keys
        names = set(_zip_members(out))
        assert not any(n.startswith("crosstab_") for n in names)

    def test_descriptor_included_when_requested_with_small_cell_flags(self, tmp_path):
        store = _fixture_store(tmp_path / "s8.qnw")
        out = build_bundle(store, tmp_path / "b4.zip", descriptor_keys=["First_Gen"],
                           small_cell_threshold=5)
        members = _zip_members(out)
        assert "crosstab_First_Gen.csv" in members
        # All cells here are < 5, so the flag columns should appear.
        assert "__flag" in members["crosstab_First_Gen.csv"]

    def test_agreement_table_when_human_and_model_present(self, tmp_path):
        store = _fixture_store(tmp_path / "s9.qnw")
        out = build_bundle(store, tmp_path / "b5.zip")
        assert "agreement.csv" in _zip_members(out)


class TestMemos:
    def test_memo_crud_and_target_filter(self, tmp_path):
        with Project.create(tmp_path / "m.qnw") as p:
            code_id = p.add_code(Code(code_id="", name="X"))
            mid = p.add_memo(Memo(memo_id="", target_type="code", target_id=code_id,
                                  text="a note", author="human"))
            p.add_memo(Memo(memo_id="", target_type="project", target_id=None,
                            text="project note", author="human"))
            assert len(p.list_memos(target_type="code")) == 1
            assert len(p.list_memos(target_type="code", target_id=code_id)) == 1
            p.update_memo(mid, "edited note")
            assert p.list_memos(target_type="code")[0].text == "edited note"
            p.delete_memo(mid)
            assert p.list_memos(target_type="code") == []

    def test_merge_codes_retargets_memos(self, tmp_path):
        """A merged-away code's memo must move to the survivor, not dangle."""
        with Project.create(tmp_path / "m2.qnw") as p:
            keep = p.add_code(Code(code_id="", name="Keep"))
            gone = p.add_code(Code(code_id="", name="Gone"))
            p.add_memo(Memo(memo_id="", target_type="code", target_id=gone,
                            text="note on gone", author="human"))
            p.merge_codes(gone, keep)
            memos = p.list_memos(target_type="code", target_id=keep)
            assert len(memos) == 1 and memos[0].text == "note on gone"


class TestGuidedSampleProject:
    def test_build_from_synthetic_csv(self, tmp_path):
        from core.sample_project import SAMPLE_PREFIX, build_sample_project

        csv = Path(__file__).resolve().parents[1] / "data" / "sample_survey_education.csv"
        out = build_sample_project(csv, tmp_path / "sample.qnw", max_rows=30)
        with Project.open(out) as p:
            assert len(p.list_sources()) > 0
            assert len(p.get_codebook()) == 5
            # Both a model and a human rater coded, so Agreement has overlap.
            assert "transformer" in p.rater_ids() and "human_primary" in p.rater_ids()
            assert len(p.list_memos()) >= 1
        assert SAMPLE_PREFIX == "SAMPLE_"

    def test_agreement_computes_on_sample(self, tmp_path):
        from analysis.agreement import per_code_kappa
        from core.sample_project import build_sample_project

        csv = Path(__file__).resolve().parents[1] / "data" / "sample_survey_education.csv"
        out = build_sample_project(csv, tmp_path / "sample2.qnw")
        with Project.open(out) as p:
            kdf = per_code_kappa(p.rater_labels("human_primary"),
                                 p.rater_labels("transformer"), min_support=1)
        assert not kdf.empty  # the sample actually produces an agreement table
