"""A CSV a person may have edited is read as text, with the encoding fallback
(review finding F3).

`response_id` is the join key for coding, agreement, erasure and the store. A
default `pd.read_csv` turns "000123" into the integer 123 -- so a colleague's
codes landed on respondent 123 with nothing reported unmatched, and erasing
respondent 000123 left their row in the run's CSVs (the filter compared "123"
with "000123"). Excel on Windows saves Windows-1252, which a plain read refuses.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from core.model import Code, Excerpt, Source
from core.populate import import_second_coder_sample
from core.project import Project

QUESTION = "What has been hardest?"


def _store(tmp_path, ids):
    path = tmp_path / "p.qnw"
    with Project.create(path) as proj:
        proj.add_code(Code(code_id="", name="Cost"))
        for i, rid in enumerate(ids):
            text = f"response {rid}"
            proj.add_source(Source(source_id=f"s{i}", type="survey_response", raw_text=text,
                                   metadata={"response_id": rid, "question_text": QUESTION}))
            proj.add_excerpt(Excerpt(excerpt_id=f"e{i}", source_id=f"s{i}", text=text,
                                     char_start=0, char_end=len(text)))
    return path


# ── Import a second coder ────────────────────────────────────────────────────
def test_second_coder_codes_land_on_the_right_respondent(tmp_path):
    path = _store(tmp_path, ["000123", "123"])
    csv = tmp_path / "coder2.csv"
    pd.DataFrame({"response_id": ["000123", "123"], "human_labels": ["Cost", ""]}).to_csv(csv, index=False)
    import_second_coder_sample(path, csv, rater_id="human_secondary", question_text=QUESTION)
    with Project.open(path) as proj:
        assert proj.rater_labels("human_secondary") == {"e0": {"Cost"}, "e1": set()}


def test_second_coder_file_saved_by_excel_imports(tmp_path):
    path = _store(tmp_path, ["1"])
    csv = tmp_path / "coder2.csv"
    csv.write_bytes("response_id,human_labels,note\n1,Cost,it’s money — mostly\n".encode("cp1252"))
    result = import_second_coder_sample(path, csv, rater_id="human_secondary", question_text=QUESTION)
    assert result["applications"] == 1
    assert result["encoding"] == "cp1252"


def test_second_coder_partial_overlap_is_reported(tmp_path):
    path = _store(tmp_path, ["1", "2", "3"])
    csv = tmp_path / "coder2.csv"
    pd.DataFrame({"response_id": ["1", "2", "99"], "human_labels": ["Cost", "", "Cost"]}).to_csv(csv, index=False)
    result = import_second_coder_sample(path, csv, rater_id="human_secondary", question_text=QUESTION)
    assert result["unmatched"] == 1
    assert result["unmatched_ids"] == ["99"]


# ── Erasure's rewrite of run CSVs ────────────────────────────────────────────
def test_erasing_a_leading_zero_id_drops_their_row_and_keeps_everyone_elses(tmp_path):
    from core.erasure import _rewrite_csv_dropping_response

    csv = tmp_path / "responses_scored.csv"
    csv.write_text("response_id,response_text,program\n"
                   "000123,my text,N/A\n"
                   "000124,other text,Nursing\n", encoding="utf-8")
    report = _rewrite_csv_dropping_response(csv, "000123", ["my text"])
    assert report["rows_dropped"] == 1
    after = pd.read_csv(csv, dtype=str, keep_default_na=False)
    assert after["response_id"].tolist() == ["000124"], "a neighbour's id must survive untouched"


def test_erasure_rewrite_keeps_literal_na_answers(tmp_path):
    from core.erasure import _rewrite_csv_dropping_response

    csv = tmp_path / "coding_sample.csv"
    csv.write_text("response_id,human_labels\n1,\n2,N/A\n", encoding="utf-8")
    _rewrite_csv_dropping_response(csv, "1", [])
    assert csv.read_text(encoding="utf-8").splitlines()[1] == "2,N/A"


# The ratchet over raw pandas reads lives in tests/test_encodings.py
# (MAY_READ_DIRECTLY); one list, so two lists cannot disagree.


def test_erasure_rewrite_leaves_every_other_cell_exactly_as_it_was(tmp_path):
    """Reading as text must not let the injection guard touch numbers: a
    sentiment of -0.87 prefixed with a quote is a corrupted column."""
    from core.erasure import _rewrite_csv_dropping_response

    csv = tmp_path / "responses_scored.csv"
    body = ("response_id,response_text,sentiment_score,centroid_distance\n"
            "a1,gone,0.5,1.25\n"
            "a2,kept text,-0.87,-1.5e-03\n")
    csv.write_text(body, encoding="utf-8")
    _rewrite_csv_dropping_response(csv, "a1", ["gone"])
    assert csv.read_text(encoding="utf-8").splitlines() == [
        "response_id,response_text,sentiment_score,centroid_distance",
        "a2,kept text,-0.87,-1.5e-03"]


def test_a_scrubbed_cell_is_still_guarded_against_formulas(tmp_path):
    from core.erasure import _rewrite_csv_dropping_response

    csv = tmp_path / "cluster_summary.csv"
    csv.write_text("cluster_id,example_quote\n0,=secret text\n", encoding="utf-8")
    _rewrite_csv_dropping_response(csv, "nobody", ["secret text"])
    assert csv.read_text(encoding="utf-8").splitlines()[1] == "0,'=[ERASED]"
