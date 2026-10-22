"""Tests for the role-explicit single-model CLI path (v3.9.7, F4)."""

from __future__ import annotations

import json

import pytest

import tools.download_models as dm


def test_single_model_json_success(monkeypatch, capsys):
    calls = {}
    monkeypatch.setattr(dm, "download_one", lambda m, r: calls.update(model=m, role=r))
    rc = dm.main(["--model", "my/model", "--role", "embedding", "--json"])
    assert rc == 0
    assert calls == {"model": "my/model", "role": "embedding"}
    res = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert res == {"ok": True, "model": "my/model", "role": "embedding", "error": ""}


def test_single_model_json_failure(monkeypatch, capsys):
    def boom(m, r):
        raise RuntimeError("not an NLI model")
    monkeypatch.setattr(dm, "download_one", boom)
    rc = dm.main(["--model", "x", "--role", "zero-shot", "--json"])
    assert rc == 1
    res = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert res["ok"] is False and "NLI" in res["error"]


def test_role_dispatch_uses_expected_loader(monkeypatch):
    """download_one routes each role to the right loader — no name guessing.

    Only runs in the full venv: patching the loaders requires importing them,
    which pulls torch. The torch-free CI skips it.
    """
    sentence_transformers = pytest.importorskip("sentence_transformers")
    transformers = pytest.importorskip("transformers")
    seen = {}

    class FakeST:
        def __init__(self, name):
            seen["st"] = name

    def fake_pipeline(task, model=None, truncation=None):
        seen[task] = model

    monkeypatch.setattr(sentence_transformers, "SentenceTransformer", FakeST)
    monkeypatch.setattr(transformers, "pipeline", fake_pipeline)
    monkeypatch.setattr(dm, "enforce_local_mode", lambda **k: None)

    dm.download_one("emb", "embedding")
    dm.download_one("sent", "sentiment")
    dm.download_one("nli", "zero-shot")
    assert seen["st"] == "emb"
    assert seen["sentiment-analysis"] == "sent"
    assert seen["zero-shot-classification"] == "nli"


def test_model_without_role_errors():
    with pytest.raises(SystemExit):
        dm.main(["--model", "x"])
