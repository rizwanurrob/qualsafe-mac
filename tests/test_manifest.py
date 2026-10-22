"""Tests for core/manifest.py — the always-on audit manifest."""

from __future__ import annotations

import json
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.manifest import PACKAGE_VERSION, write_run_manifest


def test_manifest_records_provenance(tmp_path):
    config = {
        "input": {"file_path": "data/x.csv", "text_column": "response_text",
                  "descriptor_columns": ["program"]},
        "output": {"save_embeddings": False},
        "zero_shot": {"strict_coding": {"enabled": True, "top1_min_score": 0.6,
                                        "min_margin_over_second": 0.1}},
    }
    run_summary = {"total_responses": 42, "clusters_found": 5, "questions_total": 3,
                   "questions_coded": 3, "project_store": str(tmp_path / "p.qnw")}
    path = write_run_manifest(tmp_path, config, run_summary,
                              engine_type="llm", engine_model="llama3.2:3b")
    assert path.exists() and path.name == "run_manifest.json"
    m = json.loads(path.read_text(encoding="utf-8"))
    assert m["package_version"] == PACKAGE_VERSION
    assert m["engine"] == "llm" and m["model"] == "llama3.2:3b"
    assert m["mode"] == "survey"
    assert m["counts"]["total_responses"] == 42
    assert m["thresholds"]["strict_coding_enabled"] is True
    assert m["thresholds"]["top1_min_score"] == 0.6
    assert m["input"]["descriptor_columns"] == ["program"]
    assert m["exports"]["exported_raw_text"] is True
    assert "local" in m["privacy_note"].lower()
