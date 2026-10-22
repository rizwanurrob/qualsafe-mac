"""
Tests for the v3.7.1 built-in sample datasets and default presets.

The samples are the tool's first impression: the survey CSV must parse cleanly,
be PII-quiet, and pair with the default label pack; the interview transcript must
walk the whole parsing pipeline (segmentation → roles → questions → pairing) at
high confidence, since that's exactly what the sample button promises.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

DATA = Path(__file__).resolve().parents[1] / "data"
SURVEY_CSV = DATA / "sample_survey_education.csv"
TRANSCRIPT = DATA / "sample_interview_transcript.txt"


class TestEducationSurveySample:
    def test_parses_with_default_reader(self):
        """The old sample shipped malformed (unquoted commas); never again."""
        df = pd.read_csv(SURVEY_CSV)
        assert list(df.columns) == ["response_id", "question_text", "response_text"]

    def test_forty_rows_one_question(self):
        df = pd.read_csv(SURVEY_CSV)
        assert len(df) == 40
        assert df["question_text"].nunique() == 1

    def test_ids_unique_and_no_empty_text(self):
        df = pd.read_csv(SURVEY_CSV)
        assert df["response_id"].is_unique
        assert df["response_text"].str.strip().str.len().gt(0).all()

    def test_pii_scan_is_quiet(self):
        """The sample walks users through the PII gate; it must not cry wolf."""
        from privacy.scan import scan_frame

        df = pd.read_csv(SURVEY_CSV)
        findings = scan_frame(df)
        signals = {f["signal"] for f in findings}
        assert not any("email" in s or "phone" in s or "SSN" in s for s in signals), findings

    def test_pairs_with_default_label_pack(self):
        """Sample keywords should overlap the Education pack's themes — the
        out-of-the-box demo depends on codings actually landing."""
        from streamlit_app import make_suggested_labels

        packs = make_suggested_labels()
        first_pack = next(iter(packs))
        assert first_pack == "Education / Student Experience"  # default = education

        text = " ".join(pd.read_csv(SURVEY_CSV)["response_text"].str.lower())
        # Spot-check that the dataset speaks the pack's language.
        for needle in ("cost", "friends", "advisor", "counseling", "commut"):
            assert needle in text


class TestInterviewSample:
    def test_segments_at_full_confidence(self):
        from interview.parse import load_document, segment_turns

        raw = load_document(TRANSCRIPT)
        turns, pattern, confidence = segment_turns(raw)
        assert pattern == "interviewer_respondent"
        assert confidence >= 0.9
        assert len(turns) >= 20

    def test_roles_inferred_correctly(self):
        from interview.parse import load_document, segment_turns
        from interview.speakers import infer_speaker_roles

        turns, _, _ = segment_turns(load_document(TRANSCRIPT))
        inference = infer_speaker_roles(turns)
        assert inference.role_by_label.get("Interviewer") == "interviewer"
        assert inference.role_by_label.get("Respondent") == "interviewee"

    def test_five_main_questions_detected(self):
        """The brief: 5 general unstructured questions. Follow-ups may add more,
        but at least the 5 mains must be found and paired."""
        from interview.parse import load_document, segment_turns
        from interview.questions import detect_questions, pair_questions_with_responses
        from interview.speakers import apply_roles, infer_speaker_roles

        turns, _, _ = segment_turns(load_document(TRANSCRIPT))
        roled = apply_roles(turns, infer_speaker_roles(turns).role_by_label)
        questions = detect_questions(roled)
        assert len(questions) >= 5
        pairs = pair_questions_with_responses(roled, questions)
        # When one turn asks two questions, the answer attaches to the LAST one
        # (by design), so count pairs that actually carry content.
        answered = [p for p in pairs if p.response_turns]
        assert len(answered) >= 5

    def test_roughly_fifteen_minutes(self):
        """~15 min at conversational transcription pace (90–160 wpm)."""
        words = len(TRANSCRIPT.read_text(encoding="utf-8").split())
        assert 1200 <= words <= 2600, f"{words} words is out of the ~15-minute range"

    def test_matches_example_template_themes(self):
        """The sample transcript + example template are a set: every template
        theme should find at least one matching guide question topic in the text."""
        import yaml

        template = yaml.safe_load(
            (Path(__file__).resolve().parents[1] / "config" /
             "interview_template.example.yaml").read_text(encoding="utf-8"))
        themes = template["interview_template"]["themes"]
        assert len(themes) >= 5
        text = TRANSCRIPT.read_text(encoding="utf-8").lower()
        for theme in themes:
            hits = [k for k in theme.get("keywords", []) if k.lower() in text]
            assert hits, f"template theme '{theme['id']}' has no keyword presence in the sample"
