"""
Tests for v3.1 I2: template matching + regrouping + coverage.

Fully offline: embeddings are injected as a deterministic dict-backed embed_fn
over orthonormal basis vectors, so every cosine similarity in these tests is an
exact, hand-checkable number.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from interview.grouping import group_by_theme, guide_question_coverage
from interview.matching import MatchedPair, match_qa_pairs, response_text
from interview.parse import Turn
from interview.questions import QAPair, Question
from interview.template import InterviewTemplate

# ── Deterministic embedding space ────────────────────────────────────────────
E1 = np.array([1.0, 0.0, 0.0, 0.0])   # "transition" guide question direction
E2 = np.array([0.0, 1.0, 0.0, 0.0])   # "belonging" guide question direction
E3 = np.array([0.0, 0.0, 1.0, 0.0])   # unrelated direction
E4 = np.array([0.0, 0.0, 0.0, 1.0])   # default / noise direction

GUIDE_TRANSITION = "How was your first semester?"
GUIDE_BELONGING = "Do you feel like you belong here?"

_B = math.sqrt(1 - 0.42 ** 2)
VEC = {
    GUIDE_TRANSITION: E1,
    GUIDE_BELONGING: E2,
    "Tell me about the start of the year.": E1,             # ~ transition guide
    "What clubs did you join?": E3,                          # unrelated question
    "I finally feel like part of a community on my floor.": E2,   # belonging response
    "Any final thoughts?": E3,
    "The dining hall pizza is underrated.": E4,              # off-template response
    "How did classes begin for you?": np.array([0.42, 0.0, _B, 0.0]),  # borderline 0.42 vs E1
    "I was homesick a lot at the beginning.": E4,            # keyword carrier, no embed signal
    "How was the whole experience overall?": (E1 + E2) / math.sqrt(2),  # multi-theme 0.7071
}


def fake_embed(texts):
    return np.array([VEC.get(t, E4) for t in texts], dtype=float)


def _template():
    return InterviewTemplate.from_dict({
        "interview_template": {
            "title": "T",
            "themes": [
                {"id": "transition", "label": "Transition to college",
                 "guide_questions": [GUIDE_TRANSITION], "keywords": ["homesick"]},
                {"id": "belonging", "label": "Sense of belonging",
                 "guide_questions": [GUIDE_BELONGING], "keywords": ["belong", "community"]},
            ],
        }
    })


def _pair(qid: str, turn_index: int, q_text: str, r_text: str = "") -> QAPair:
    q = Question(question_id=qid, turn_index=turn_index, text=q_text)
    responses = []
    if r_text:
        responses = [Turn(index=turn_index + 1, speaker_raw="R", text=r_text,
                          char_start=0, char_end=len(r_text), speaker_role="interviewee")]
    return QAPair(question=q, response_turns=responses)


# ─────────────────────────────────────────────────────────────────────────────
# Matching
# ─────────────────────────────────────────────────────────────────────────────

class TestMatching:
    def test_question_similarity_matches_theme(self):
        pairs = [_pair("q001", 0, "Tell me about the start of the year.",
                       "The dining hall pizza is underrated.")]
        out = match_qa_pairs(pairs, _template(), fake_embed)
        m = out[0].matches
        assert len(m) == 1 and m[0].theme_id == "transition"
        assert m[0].similarity == 1.0
        assert m[0].source.startswith("embedding_question")

    def test_wandering_response_counts_toward_theme(self):
        """Unrelated question, but the RESPONSE is about belonging → belonging match."""
        pairs = [_pair("q001", 0, "What clubs did you join?",
                       "I finally feel like part of a community on my floor.")]
        out = match_qa_pairs(pairs, _template(), fake_embed)
        m = out[0].matches
        assert m and m[0].theme_id == "belonging"
        assert m[0].source.startswith("embedding_response")
        # 'community' keyword also hits → recorded on the source
        assert "+keyword" in m[0].source

    def test_keyword_boost_lifts_borderline_over_gate(self):
        # q_sim = 0.42 (< 0.45); 'homesick' keyword in response → +0.05 = 0.47
        pairs = [_pair("q001", 0, "How did classes begin for you?",
                       "I was homesick a lot at the beginning.")]
        out = match_qa_pairs(pairs, _template(), fake_embed)
        m = out[0].matches
        assert m and m[0].theme_id == "transition"
        assert abs(m[0].similarity - 0.47) < 1e-6
        assert "+keyword" in m[0].source

    def test_keywords_alone_cannot_confirm(self):
        """A keyword hit with no embedding signal stays below the gate."""
        template = InterviewTemplate.from_dict({"interview_template": {"themes": [
            {"id": "kw_only", "label": "KW", "guide_questions": [], "keywords": ["pizza"]},
        ]}})
        pairs = [_pair("q001", 0, "Any final thoughts?",
                       "The dining hall pizza is underrated.")]
        out = match_qa_pairs(pairs, template, fake_embed)
        assert out[0].is_unclassified
        assert out[0].scores["kw_only"] <= 0.15   # boost cap, far below 0.45

    def test_no_match_is_unclassified_not_forced(self):
        pairs = [_pair("q001", 0, "Any final thoughts?",
                       "The dining hall pizza is underrated.")]
        out = match_qa_pairs(pairs, _template(), fake_embed)
        assert out[0].is_unclassified
        assert set(out[0].scores) == {"transition", "belonging"}   # transparency kept

    def test_multi_theme_match_allowed_by_default(self):
        pairs = [_pair("q001", 0, "How was the whole experience overall?")]
        out = match_qa_pairs(pairs, _template(), fake_embed)
        ids = {m.theme_id for m in out[0].matches}
        assert ids == {"transition", "belonging"}
        for m in out[0].matches:
            assert abs(m.similarity - 0.7071) < 1e-3

    def test_single_theme_mode_keeps_top_only(self):
        pairs = [_pair("q001", 0, "How was the whole experience overall?")]
        out = match_qa_pairs(pairs, _template(), fake_embed, {"allow_multi_theme": False})
        assert len(out[0].matches) == 1

    def test_min_similarity_config_respected(self):
        pairs = [_pair("q001", 0, "How did classes begin for you?")]  # 0.42, no keyword
        strict = match_qa_pairs(pairs, _template(), fake_embed, {"min_similarity": 0.45})
        loose = match_qa_pairs(pairs, _template(), fake_embed, {"min_similarity": 0.40})
        assert strict[0].is_unclassified
        assert loose[0].matches and loose[0].matches[0].theme_id == "transition"

    def test_empty_response_pair_is_handled(self):
        pairs = [_pair("q001", 0, "Tell me about the start of the year.")]  # no response turns
        out = match_qa_pairs(pairs, _template(), fake_embed)
        assert out[0].matches[0].theme_id == "transition"
        assert response_text(pairs[0]) == ""

    def test_empty_input(self):
        assert match_qa_pairs([], _template(), fake_embed) == []


# ─────────────────────────────────────────────────────────────────────────────
# Regrouping + off-template + coverage
# ─────────────────────────────────────────────────────────────────────────────

class TestGrouping:
    def _matched(self):
        pairs = [
            _pair("q001", 4, "Tell me about the start of the year."),           # transition (late)
            _pair("q002", 0, "What clubs did you join?",
                  "I finally feel like part of a community on my floor."),      # belonging (early)
            _pair("q003", 2, "How was the whole experience overall?"),          # both themes
            _pair("q004", 6, "Any final thoughts?",
                  "The dining hall pizza is underrated."),                      # off-template
        ]
        return pairs, match_qa_pairs(pairs, _template(), fake_embed)

    def test_regroups_by_theme_in_transcript_order(self):
        _, matched = self._matched()
        groups, off = group_by_theme(matched, _template())
        by_id = {g.theme_id: g for g in groups}
        # transition: multi-theme pair (turn 2) before the direct one (turn 4)
        assert [m.pair.question.question_id for m in by_id["transition"].items] == ["q003", "q001"]
        # belonging: early wandering pair then the multi-theme pair
        assert [m.pair.question.question_id for m in by_id["belonging"].items] == ["q002", "q003"]

    def test_multi_theme_pair_appears_in_both_groups(self):
        _, matched = self._matched()
        groups, _ = group_by_theme(matched, _template())
        counts = sum(1 for g in groups for m in g.items if m.pair.question.question_id == "q003")
        assert counts == 2

    def test_off_template_surfaced(self):
        _, matched = self._matched()
        _, off = group_by_theme(matched, _template())
        assert [m.pair.question.question_id for m in off] == ["q004"]

    def test_group_similarity_lookup(self):
        _, matched = self._matched()
        groups, _ = group_by_theme(matched, _template())
        transition = next(g for g in groups if g.theme_id == "transition")
        direct = next(m for m in transition.items if m.pair.question.question_id == "q001")
        assert transition.similarity_for(direct) == 1.0

    def test_coverage_addressed_and_skipped(self):
        # No multi-theme question here: belonging content arrives ONLY via a
        # response, so its guide question was never actually asked.
        pairs = [
            _pair("q001", 0, "Tell me about the start of the year."),
            _pair("q002", 2, "What clubs did you join?",
                  "I finally feel like part of a community on my floor."),
        ]
        rows = guide_question_coverage(pairs, _template(), fake_embed)
        by_gq = {r["guide_question"]: r for r in rows}
        # An asked question hits the transition guide question exactly.
        assert by_gq[GUIDE_TRANSITION]["addressed"]
        # The belonging theme got content (via the response) but its guide
        # question was never asked — coverage reports it as skipped. This is
        # exactly the coverage-vs-matching distinction the report exists to show.
        assert not by_gq[GUIDE_BELONGING]["addressed"]

    def test_coverage_counts_multi_theme_question_as_addressing_both(self):
        pairs = [_pair("q001", 0, "How was the whole experience overall?")]
        rows = guide_question_coverage(pairs, _template(), fake_embed)
        assert all(r["addressed"] for r in rows)   # 0.7071 vs both guides

    def test_coverage_with_no_pairs(self):
        rows = guide_question_coverage([], _template(), fake_embed)
        assert rows and all(not r["addressed"] for r in rows)
