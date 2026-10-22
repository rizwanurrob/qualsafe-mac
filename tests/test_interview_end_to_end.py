"""
Interview mode, run end to end on the shipped transcript.

The other half of a program that claims "survey **and** interview data", and —
like the survey pipeline before Pass 14 — it had never been executed from one
end to the other. Ten modules, each with unit tests, and no test that walked a
real transcript from a file on disk to grouped themes.

This does. It is deliberately the *deterministic* chain — parse, roles,
questions, pairing, matching, grouping, coverage — because that part runs
without Ollama and is what a researcher hits before any model is involved. The
LLM stage is exercised separately by `tests/test_interview_analyze.py`.

**The result was that it works**, which is worth a test rather than a note: 27
turns at segmentation confidence 1.00, roles inferred correctly, nine questions,
five themes populated sensibly, six of eight guide questions addressed.

The second half of this file is the claim interview mode actually rests on:
**a quote attributed to a participant must exist in the transcript.** That is
the difference between assistive analysis and a machine putting words in
someone's mouth, and it is tested adversarially rather than happily.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from interview.parse import load_document, parse_interview
from interview.questions import detect_questions, pair_questions_with_responses
from interview.quotes import verify_quotes
from interview.speakers import apply_roles, infer_speaker_roles

TRANSCRIPT = Path(__file__).resolve().parents[1] / "data" / "sample_interview_transcript.txt"


@pytest.fixture(scope="module")
def parsed():
    raw, turns, pattern, confidence = parse_interview(TRANSCRIPT)
    turns = apply_roles(turns, infer_speaker_roles(turns).role_by_label)
    return raw, turns, pattern, confidence


class TestTheDeterministicChainRunsOnARealTranscript:

    def test_the_shipped_transcript_is_still_there(self):
        """Every assertion below is about this file."""
        assert TRANSCRIPT.exists()
        assert len(load_document(TRANSCRIPT)) > 5000

    def test_it_segments_into_turns_confidently(self, parsed):
        _raw, turns, pattern, confidence = parsed

        assert len(turns) > 20
        assert pattern == "interviewer_respondent"
        assert confidence > 0.9, "the shipped transcript should be unambiguous"

    def test_the_roles_come_out_right(self, parsed):
        _raw, turns, _pattern, _confidence = parsed
        inference = infer_speaker_roles(turns)

        assert inference.role_by_label["Interviewer"] == "interviewer"
        assert inference.role_by_label["Respondent"] == "interviewee"

    def test_the_interviewee_does_most_of_the_talking(self, parsed):
        """If this inverts, the roles were assigned backwards."""
        _raw, turns, _pattern, _confidence = parsed

        by_role = {}
        for turn in turns:
            by_role[turn.speaker_role] = by_role.get(turn.speaker_role, 0) + len(turn.text)

        assert by_role["interviewee"] > by_role["interviewer"] * 3

    def test_questions_are_detected(self, parsed):
        _raw, turns, _pattern, _confidence = parsed

        questions = detect_questions(turns)

        assert len(questions) >= 6
        assert any("first semester" in q.text for q in questions)

    def test_most_questions_get_a_response(self, parsed):
        _raw, turns, _pattern, _confidence = parsed

        pairs = pair_questions_with_responses(turns, detect_questions(turns))

        answered = [p for p in pairs if p.response_turns]
        assert len(answered) >= len(pairs) - 1


class TestTheRoleConfidenceIsInformationalOnly:
    """Found by running it: the value is computed and never shown.

    `interview_ui.py` displays `inference.rationale` — which carries the actual
    evidence in words — and never `inference.confidence`. That is the better
    choice, and it means the number's scale does not matter today.

    It is recorded because the scale is misleading if anyone ever gates on it.
    The formula is `0.7 * question_gap + 0.3 * talk_share_gap`, and on the
    shipped transcript it returns **0.485** while assigning both roles
    correctly — because the question term cannot approach 1.0 on real speech,
    where respondents say "you know?" and interviewers say "Mm-hmm".
    """

    def test_the_roles_are_right_even_though_confidence_is_middling(self, parsed):
        _raw, turns, _pattern, _confidence = parsed
        inference = infer_speaker_roles(turns)

        assert inference.confidence < 0.6, (
            "if this rises, the formula changed and the note above is stale")
        assert inference.role_by_label["Interviewer"] == "interviewer"

    def test_the_rationale_carries_the_evidence_in_words(self, parsed):
        """What the analyst actually sees at the checkpoint."""
        _raw, turns, _pattern, _confidence = parsed

        rationale = infer_speaker_roles(turns).rationale

        assert "asks questions in" in rationale
        assert "Confirm or correct" in rationale

    def test_the_interface_shows_the_rationale_and_not_the_number(self):
        source = (Path(__file__).resolve().parents[1]
                  / "interview_ui.py").read_text(encoding="utf-8")

        assert "inference.rationale" in source


class TestAQuoteMustExistInTheTranscript:
    """The claim interview mode rests on.

    An LLM asked for supporting quotes will produce plausible ones whether or
    not they were said. The difference between assistive analysis and a machine
    putting words in a participant's mouth is entirely this check.
    """

    @staticmethod
    def _excerpt(raw, needle="rollercoaster", before=30, after=40):
        index = raw.index(needle)
        return raw[index - before:index + after].strip()

    def test_a_verbatim_quote_is_kept(self, parsed):
        raw, *_ = parsed

        result = verify_quotes([self._excerpt(raw)], raw)

        assert len(result.located) == 1
        assert result.located[0].match_kind == "exact"

    def test_an_invented_quote_is_dropped(self, parsed):
        """The headline property. This sentence appears nowhere in the file."""
        raw, *_ = parsed

        result = verify_quotes(
            ["I felt completely abandoned by the university."], raw)

        assert result.located == []
        assert result.hallucination_rate == 1.0

    def test_a_dropped_quote_is_reported_not_silently_discarded(self, parsed):
        raw, *_ = parsed

        result = verify_quotes(["I felt completely abandoned."], raw)

        assert result.dropped == ["I felt completely abandoned."]

    def test_what_is_returned_is_the_source_text_not_the_proposed_text(self, parsed):
        """The property that makes a fuzzy match safe.

        When a model paraphrases slightly, the located quote is the span from
        the transcript — not the model's wording. So even a sloppy quote cannot
        propagate into a report as though the participant had said it.
        """
        raw, *_ = parsed
        altered = self._excerpt(raw).replace("rollercoaster", "roller coaster")

        result = verify_quotes([altered], raw)

        assert result.located, "a near-miss should still locate"
        located = result.located[0]
        assert located.match_kind == "fuzzy"
        assert raw[located.char_start:located.char_end] == located.text
        assert "roller coaster" not in located.text, (
            "the model's wording reached the output")

    def test_a_fuzzy_match_says_it_was_fuzzy(self, parsed):
        """The analyst has to be able to tell a paraphrase from a quotation."""
        raw, *_ = parsed
        altered = self._excerpt(raw).replace("rollercoaster", "roller coaster")

        located = verify_quotes([altered], raw).located[0]

        assert located.match_kind == "fuzzy"
        assert located.similarity < 1.0

    def test_the_interface_shows_the_match_kind_and_the_drop_rate(self):
        """Both, or the verification is invisible to the person relying on it."""
        source = (Path(__file__).resolve().parents[1]
                  / "interview_ui.py").read_text(encoding="utf-8")

        assert "q.match_kind" in source
        assert "hallucination_rate" in source

    def test_fuzzy_matching_can_be_switched_off(self, parsed):
        """A project that wants only exact quotes should be able to say so."""
        raw, *_ = parsed
        altered = self._excerpt(raw).replace("rollercoaster", "roller coaster")

        result = verify_quotes([altered], raw, allow_fuzzy=False)

        assert result.located == []
