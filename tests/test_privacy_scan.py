"""
Tests for the assistive PII scan and the per-file gate reset (v3.1.1, Phase 0.5).

Two things are being pinned here:

1. The scan finds the obvious signals and does not fire on ordinary survey prose.
   Both halves matter — a scan that cries wolf trains analysts to click through,
   which is worse than no scan, because it manufactures a record of review that
   never happened.
2. The confirmation checkbox attests to one dataset. Loading a second file must
   re-arm it.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from privacy.scan import (
    mask_example,
    mask_frame,
    mask_text_series,
    scan_frame,
    summarize_findings,
)


@pytest.fixture
def pii_frame():
    return pd.DataFrame(
        {
            "response_text": [
                "Reach me at jane.doe@example.edu about the class",
                "Call 617-555-0142 after 5pm",
                "The advising office was helpful",
            ],
            "student_id": ["1234567", "7654321", "1122334"],
            "clean_feedback": [
                "The library hours work well",
                "More parking would help",
                "Great orientation program",
            ],
        }
    )


def _signals_for(findings, column):
    return {f["signal"] for f in findings if f["column"] == column}


class TestScanDetection:
    def test_detects_email(self, pii_frame):
        assert "email address" in _signals_for(scan_frame(pii_frame), "response_text")

    def test_detects_phone(self, pii_frame):
        assert "phone-like number" in _signals_for(scan_frame(pii_frame), "response_text")

    def test_detects_suspicious_column_name(self, pii_frame):
        signals = _signals_for(scan_frame(pii_frame), "student_id")
        assert any("column name suggests PII" in s for s in signals)

    def test_detects_ssn(self):
        df = pd.DataFrame({"notes": ["my ssn is 123-45-6789"]})
        assert "SSN-like number" in _signals_for(scan_frame(df), "notes")

    def test_detects_name_like_column(self):
        df = pd.DataFrame(
            {"who": ["Jane Doe", "John Smith", "Maria Garcia", "Alan Turing", "Ada Lovelace"]}
        )
        assert "values look like personal names" in _signals_for(scan_frame(df), "who")

    def test_reports_hit_counts(self, pii_frame):
        findings = scan_frame(pii_frame)
        email = [f for f in findings if f["signal"] == "email address"][0]
        assert email["n_hits"] == 1


class TestScanRestraint:
    """The false-positive half. Noisy scans get ignored, and ignored gates are fake."""

    def test_clean_column_produces_no_findings(self, pii_frame):
        assert _signals_for(scan_frame(pii_frame), "clean_feedback") == set()

    def test_ordinary_prose_is_not_flagged(self):
        df = pd.DataFrame(
            {
                "response_text": [
                    "I loved the campus tour and the food was good",
                    "Nothing to add, everything went smoothly",
                    "The 2026 orientation was better than 2025",
                ]
            }
        )
        assert scan_frame(df) == []

    def test_numeric_columns_are_not_scanned_as_text(self):
        """Years and prices are not identifiers."""
        df = pd.DataFrame({"year": [2024, 2025, 2026], "price": [19.99, 5.00, 12.50]})
        assert scan_frame(df) == []

    def test_two_capitalized_words_alone_do_not_trigger_names(self):
        """A column of repeated proper nouns is a category, not a roster."""
        df = pd.DataFrame({"campus": ["Boston Campus", "Boston Campus", "Madrid Campus"] * 3})
        assert "values look like personal names" not in _signals_for(scan_frame(df), "campus")

    def test_empty_frame_is_safe(self):
        assert scan_frame(pd.DataFrame()) == []

    def test_none_frame_is_safe(self):
        assert scan_frame(None) == []


class TestMaskingExamples:
    def test_email_example_is_masked(self):
        masked = mask_example("contact jane.doe@example.edu now", "email address")
        assert "jane.doe" not in masked
        assert "@" in masked

    def test_phone_example_is_masked(self):
        masked = mask_example("call 617-555-0142", "phone-like number")
        assert "555-0142" not in masked

    def test_findings_never_carry_raw_pii(self, pii_frame):
        """A panel that prints the PII it found has leaked it."""
        for finding in scan_frame(pii_frame):
            assert "jane.doe@example.edu" not in finding["example_masked"]
            assert "617-555-0142" not in finding["example_masked"]


class TestMasking:
    def test_masks_email_phone_ssn(self):
        s = pd.Series(["mail me a@b.edu", "call 617-555-0142", "ssn 123-45-6789"])
        out = mask_text_series(s)
        assert out.tolist() == ["mail me [EMAIL]", "call [PHONE]", "ssn [SSN]"]

    def test_leaves_other_text_intact(self):
        s = pd.Series(["the library was great"])
        assert mask_text_series(s).iloc[0] == "the library was great"

    def test_non_strings_pass_through(self):
        s = pd.Series([42, None, "a@b.edu"])
        out = mask_text_series(s)
        assert out.iloc[0] == 42
        assert out.iloc[1] is None
        assert out.iloc[2] == "[EMAIL]"

    def test_mask_frame_only_touches_named_columns(self, pii_frame):
        out = mask_frame(pii_frame, ["response_text"])
        assert "[EMAIL]" in out["response_text"].iloc[0]
        assert out["student_id"].iloc[0] == "1234567"

    def test_mask_frame_does_not_mutate_input(self, pii_frame):
        mask_frame(pii_frame, ["response_text"])
        assert "jane.doe@example.edu" in pii_frame["response_text"].iloc[0]

    def test_masked_frame_scans_clean_for_those_signals(self, pii_frame):
        out = mask_frame(pii_frame, ["response_text"])
        assert _signals_for(scan_frame(out), "response_text") == set()


class TestSummary:
    def test_no_findings_summary_does_not_claim_safety(self):
        text = summarize_findings([])
        assert "not a guarantee" in text.lower()

    def test_summary_names_columns(self, pii_frame):
        text = summarize_findings(scan_frame(pii_frame))
        assert "response_text" in text


class TestGateResetLogic:
    """The gate re-arms per dataset (survey) / per transcript (interview)."""

    def test_survey_gate_resets_when_source_changes(self):
        import streamlit as st

        import streamlit_app

        st.session_state.clear()
        st.session_state["input_source"] = "upload:a.csv"
        st.session_state["last_confirmed_source"] = "upload:a.csv"
        st.session_state["pii_confirmed"] = True
        st.session_state["pii_confirm_checkbox"] = True

        # Same source: confirmation stands.
        streamlit_app.reset_pii_gate_if_source_changed()
        assert st.session_state["pii_confirmed"] is True

        # New file: attestation was about the old one.
        st.session_state["input_source"] = "upload:b.csv"
        streamlit_app.reset_pii_gate_if_source_changed()
        assert st.session_state["pii_confirmed"] is False
        # The widget key must go too, or the box re-renders ticked.
        assert "pii_confirm_checkbox" not in st.session_state
        st.session_state.clear()

    def test_interview_signature_changes_with_size(self):
        from interview_ui import upload_signature

        assert upload_signature("t.docx", 100) == upload_signature("t.docx", 100)
        # Same name, re-exported content — must re-attest.
        assert upload_signature("t.docx", 100) != upload_signature("t.docx", 200)
        assert upload_signature("a.docx", 100) != upload_signature("b.docx", 100)
