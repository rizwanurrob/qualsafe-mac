"""
Tests for v3.8.1 (P1) — codebook YAML exchange, custom label packs, store merge.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.codebook_io import (
    codebook_label_list,
    export_codebook_yaml,
    import_codebook_yaml,
    parse_codebook_yaml,
)
from core.label_packs import delete_custom_pack, load_custom_packs, save_custom_pack
from core.model import Code, CodeApplication, Rater, Source
from core.project import Project, new_id
from core.store_merge import merge_project_stores


@pytest.fixture(autouse=True)
def _tmp_settings_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("QNW_SETTINGS_DIR", str(tmp_path))
    return tmp_path


# ── 8.5 codebook YAML ────────────────────────────────────────────────────────

class TestCodebookYaml:
    def _project(self, tmp_path):
        p = Project.create(tmp_path / "cb.qnw")
        parent = p.add_code(Code(code_id="", name="Finances",
                                 definition="Money matters"))
        p.add_code(Code(code_id="", name="Tuition", definition="Tuition costs",
                        parent_id=parent))
        return p

    def test_export_import_roundtrip_with_hierarchy(self, tmp_path):
        src = self._project(tmp_path)
        yaml_text = export_codebook_yaml(src)
        src.close()

        with Project.create(tmp_path / "target.qnw") as dst:
            result = import_codebook_yaml(dst, yaml_text)
            assert sorted(result["created"]) == ["Finances", "Tuition"]
            codes = {c.name: c for c in dst.get_codebook()}
            assert codes["Tuition"].parent_id == codes["Finances"].code_id
            assert codes["Finances"].definition == "Money matters"

    def test_import_is_additive_and_never_clobbers(self, tmp_path):
        src = self._project(tmp_path)
        yaml_text = export_codebook_yaml(src)
        src.close()

        with Project.create(tmp_path / "t2.qnw") as dst:
            dst.add_code(Code(code_id="", name="Finances",
                              definition="MY definition, not yours"))
            result = import_codebook_yaml(dst, yaml_text)
            assert result["skipped_existing"] == ["Finances"]
            assert result["created"] == ["Tuition"]
            mine = next(c for c in dst.get_codebook() if c.name == "Finances")
            assert mine.definition == "MY definition, not yours"  # untouched

    def test_malformed_yaml_raises_usable_message(self):
        with pytest.raises(ValueError, match="codebook"):
            parse_codebook_yaml("just: something_else")
        with pytest.raises(ValueError, match="name"):
            parse_codebook_yaml("codebook:\n  - definition: no name here")
        with pytest.raises(ValueError, match="Duplicate"):
            parse_codebook_yaml("codebook:\n  - name: A\n  - name: A")

    def test_label_list(self):
        text = "codebook:\n  - name: Cost\n  - name: Belonging\n"
        assert codebook_label_list(text) == ["Cost", "Belonging"]

    def test_unresolved_parent_reported_not_invented(self, tmp_path):
        text = "codebook:\n  - name: Child\n    parent: Ghost\n"
        with Project.create(tmp_path / "t3.qnw") as dst:
            result = import_codebook_yaml(dst, text)
            assert result["parents_unresolved"] == ["Child → Ghost"]
            assert [c.name for c in dst.get_codebook()] == ["Child"]


# ── 8.6 label packs ──────────────────────────────────────────────────────────

class TestLabelPacks:
    def test_save_load_roundtrip(self):
        save_custom_pack("My Pack", ["Cost", "Belonging", ""])
        packs = load_custom_packs()
        assert packs["My Pack"] == ["Cost", "Belonging"]  # blank dropped

    def test_overwrite_and_delete(self):
        save_custom_pack("P", ["A"])
        save_custom_pack("P", ["B"])
        assert load_custom_packs()["P"] == ["B"]
        assert delete_custom_pack("P") is True
        assert "P" not in load_custom_packs()
        assert delete_custom_pack("P") is False

    def test_empty_name_or_labels_rejected(self):
        with pytest.raises(ValueError):
            save_custom_pack(" ", ["A"])
        with pytest.raises(ValueError):
            save_custom_pack("X", ["", "  "])


# ── 8.7 store merge ──────────────────────────────────────────────────────────

def _project_with_responses(path, response_ids=("r1", "r2", "r3"), question="Q1"):
    with Project.create(path) as p:
        for rid in response_ids:
            src = Source(source_id=new_id("src"), type="survey_response",
                         raw_text=f"text {rid}", label=question,
                         metadata={"response_id": rid, "question_text": question})
            p.add_source(src)
            p.add_whole_response_excerpt(src)
    return path


def _add_human_codings(path, rater_id, codings, question="Q1", code_defs=None):
    """codings: {response_id: [code names]}."""
    with Project.open(path) as p:
        p.add_rater(Rater(rater_id=rater_id, kind="human", name=rater_id))
        name_to_id = {c.name: c.code_id for c in p.get_codebook()}
        for rid, names in codings.items():
            src = p.find_source_by_response_id(rid, question=question)
            exc = p.list_excerpts(src.source_id)[0]
            for name in names:
                if name not in name_to_id:
                    definition = (code_defs or {}).get(name, "")
                    name_to_id[name] = p.add_code(Code(
                        code_id="", name=name, definition=definition, origin="emergent"))
                p.apply_code(CodeApplication(
                    application_id="", excerpt_id=exc.excerpt_id,
                    code_id=name_to_id[name], coder="human", rater_id=rater_id))


class TestStoreMerge:
    def test_merges_colleague_codings_under_their_rater(self, tmp_path):
        target = _project_with_responses(tmp_path / "mine.qnw")
        incoming = _project_with_responses(tmp_path / "theirs.qnw")
        _add_human_codings(incoming, "human_bob", {"r1": ["Cost"], "r2": ["Belonging"]})

        result = merge_project_stores(target, incoming)

        assert result["matched"] == 2
        assert result["raters_merged"] == {"human_bob": 2}
        assert sorted(result["codes_created"]) == ["Belonging", "Cost"]
        with Project.open(target) as p:
            assert "human_bob" in p.rater_ids()
            labels = p.rater_labels("human_bob")
            assert sum(len(v) for v in labels.values()) == 2

    def test_remerge_is_idempotent(self, tmp_path):
        """Merging the same file twice must not duplicate codings."""
        target = _project_with_responses(tmp_path / "m2.qnw")
        incoming = _project_with_responses(tmp_path / "t2.qnw")
        _add_human_codings(incoming, "human_bob", {"r1": ["Cost"]})

        merge_project_stores(target, incoming)
        merge_project_stores(target, incoming)

        with Project.open(target) as p:
            apps = [a for a in p.list_applications() if a.rater_id == "human_bob"]
            assert len(apps) == 1

    def test_existing_code_matched_by_name_not_duplicated(self, tmp_path):
        target = _project_with_responses(tmp_path / "m3.qnw")
        with Project.open(target) as p:
            p.add_code(Code(code_id="", name="Cost", definition="target def"))
        incoming = _project_with_responses(tmp_path / "t3.qnw")
        _add_human_codings(incoming, "human_bob", {"r1": ["Cost"]})

        result = merge_project_stores(target, incoming)
        assert result["codes_created"] == []
        with Project.open(target) as p:
            names = [c.name for c in p.get_codebook()]
            assert names.count("Cost") == 1

    def test_near_name_suggested_never_auto_merged(self, tmp_path):
        target = _project_with_responses(tmp_path / "m4.qnw")
        with Project.open(target) as p:
            p.add_code(Code(code_id="", name="Financial stress"))
        incoming = _project_with_responses(tmp_path / "t4.qnw")
        _add_human_codings(incoming, "human_bob", {"r1": ["Financial stress and cost"]})

        result = merge_project_stores(target, incoming)
        # Suggested for human review…
        assert ("Financial stress and cost", "Financial stress") in result["near_name_suggestions"]
        # …but both codes exist — nothing was silently merged.
        with Project.open(target) as p:
            names = {c.name for c in p.get_codebook()}
            assert {"Financial stress", "Financial stress and cost"} <= names

    def test_unmatched_responses_reported(self, tmp_path):
        target = _project_with_responses(tmp_path / "m5.qnw", response_ids=("r1",))
        incoming = _project_with_responses(tmp_path / "t5.qnw", response_ids=("r1", "r99"))
        _add_human_codings(incoming, "human_bob", {"r1": ["A"], "r99": ["B"]})

        result = merge_project_stores(target, incoming)
        assert result["matched"] == 1
        assert any("r99" in u for u in result["unmatched_responses"])

    def test_machine_codings_not_merged(self, tmp_path):
        target = _project_with_responses(tmp_path / "m6.qnw")
        incoming = _project_with_responses(tmp_path / "t6.qnw")
        with Project.open(incoming) as p:
            p.add_rater(Rater(rater_id="transformer", kind="transformer", name="model"))
            code = p.add_code(Code(code_id="", name="MachineTheme"))
            src = p.find_source_by_response_id("r1", question="Q1")
            exc = p.list_excerpts(src.source_id)[0]
            p.apply_code(CodeApplication(application_id="", excerpt_id=exc.excerpt_id,
                                         code_id=code, coder="transformer",
                                         rater_id="transformer"))
        result = merge_project_stores(target, incoming)
        assert result["matched"] == 0
        with Project.open(target) as p:
            assert "transformer" not in p.rater_ids()

    def test_backup_taken_before_merge(self, tmp_path):
        from core.backups import list_backups

        target = _project_with_responses(tmp_path / "m7.qnw")
        incoming = _project_with_responses(tmp_path / "t7.qnw")
        _add_human_codings(incoming, "human_bob", {"r1": ["A"]})
        result = merge_project_stores(target, incoming)
        assert result["backup"] is not None
        assert any("pre_store_merge" in b.name for b in list_backups(target))
