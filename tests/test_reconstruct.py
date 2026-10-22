"""Tests for rebuilding a working dataset from a project store (v3.9.1)."""

from __future__ import annotations

import pandas as pd

from core.model import Descriptor, Source
from core.project import Project
from core.reconstruct import (
    QUESTION_COL,
    RESPONSE_ID_COL,
    TEXT_COL,
    dataframe_from_store,
    descriptor_columns,
)


def _seed_store(path, rows):
    """rows: list of (response_id, question, text, {descriptors}, respondent_id|None)."""
    with Project.create(path) as proj:
        for i, (rid, q, text, descs, resp) in enumerate(rows):
            meta = {"response_id": rid, "question_text": q}
            if resp is not None:
                meta["respondent_id"] = resp
            src = Source(source_id=f"src_{i}", type="survey_response",
                         raw_text=text, label=q, metadata=meta)
            proj.add_source(src)
            proj.add_whole_response_excerpt(src)
            for k, v in descs.items():
                proj.set_descriptor(Descriptor(source_id=src.source_id, key=k, value=v))


def test_reconstructs_core_columns_and_text(tmp_path):
    store = tmp_path / "project.qnw"
    _seed_store(store, [
        ("101", "What helped?", "The advising was great", {}, None),
        ("102", "What helped?", "Free tutoring", {}, None),
    ])
    df = dataframe_from_store(store)
    assert list(df.columns[:3]) == [RESPONSE_ID_COL, QUESTION_COL, TEXT_COL]
    assert len(df) == 2
    assert set(df[RESPONSE_ID_COL]) == {"101", "102"}
    assert "The advising was great" in set(df[TEXT_COL])


def test_reconstructs_descriptors_and_respondent(tmp_path):
    store = tmp_path / "project.qnw"
    _seed_store(store, [
        ("1", "Q1", "answer a", {"program": "Nursing", "year": "1"}, "R1"),
        ("2", "Q1", "answer b", {"program": "Biology", "year": "2"}, "R2"),
    ])
    df = dataframe_from_store(store)
    assert "respondent_id" in df.columns
    assert set(descriptor_columns(df)) == {"program", "year"}
    row = df[df[RESPONSE_ID_COL] == "1"].iloc[0]
    assert row["program"] == "Nursing"
    assert row["respondent_id"] == "R1"


def test_response_id_stays_string(tmp_path):
    """Numeric-looking ids must not be float-coerced (join-key integrity)."""
    store = tmp_path / "project.qnw"
    _seed_store(store, [("101", "Q", "text", {}, None)])
    df = dataframe_from_store(store)
    assert df[RESPONSE_ID_COL].dtype == object
    assert df[RESPONSE_ID_COL].iloc[0] == "101"  # not "101.0", not 101


def test_respondent_column_absent_when_none(tmp_path):
    store = tmp_path / "project.qnw"
    _seed_store(store, [("1", "Q", "t", {}, None)])
    df = dataframe_from_store(store)
    assert "respondent_id" not in df.columns


def test_empty_store_returns_empty_frame_with_core_cols(tmp_path):
    store = tmp_path / "project.qnw"
    with Project.create(store):
        pass
    df = dataframe_from_store(store)
    assert df.empty
    assert list(df.columns) == [RESPONSE_ID_COL, QUESTION_COL, TEXT_COL]


def test_interview_sources_are_skipped(tmp_path):
    store = tmp_path / "project.qnw"
    with Project.create(store) as proj:
        s1 = Source(source_id="s1", type="survey_response", raw_text="survey text",
                    label="Q", metadata={"response_id": "1", "question_text": "Q"})
        proj.add_source(s1)
        proj.add_whole_response_excerpt(s1)
        s2 = Source(source_id="s2", type="interview", raw_text="transcript turn",
                    label="", metadata={})
        proj.add_source(s2)
        proj.add_whole_response_excerpt(s2)
    df = dataframe_from_store(store)
    assert len(df) == 1
    assert df[TEXT_COL].iloc[0] == "survey text"


def test_missing_store_raises(tmp_path):
    try:
        dataframe_from_store(tmp_path / "nope.qnw")
        assert False, "expected FileNotFoundError"
    except FileNotFoundError:
        pass
