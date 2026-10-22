#!/usr/bin/env python
"""
Question detection + Q/A pairing (v3.1, I1). Handoff stages [4] and [5].

Detection is deterministic in this increment: within interviewer turns, a
sentence is a question if it ends with "?" (and isn't a one-word backchannel like
"Right?"), or if it opens with an interrogative/imperative prompt ("Tell me
about…", "Describe…", "How…") — interview guides often phrase prompts without a
question mark. An LLM classifier for ambiguous cases is a later enhancement; the
seam is `detect_questions`.

Pairing: each question is paired with the interviewee turns that follow it, up to
the next question. When one interviewer turn contains several questions, the
respondent's answer follows the whole turn, so the response block attaches to the
LAST question of that turn (earlier ones get no direct response and surface in the
coverage report instead of being force-fit).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List

from interview.parse import Turn

# Sentence boundary: split after ./?/! followed by whitespace.
_SENTENCE_SPLIT = re.compile(r"(?<=[.?!])\s+")

# Openers that make an unmarked sentence a question/prompt in interview context.
INTERROGATIVE_OPENERS = (
    "how", "what", "why", "when", "where", "who", "which",
    "do", "does", "did", "can", "could", "would", "will", "are", "is", "was", "were",
    "tell", "describe", "walk", "talk", "explain", "say",
)

_MIN_QUESTION_WORDS = 2   # filters one-word backchannels ("Right?", "Yeah?")


@dataclass
class Question:
    question_id: str
    turn_index: int
    text: str


@dataclass
class QAPair:
    question: Question
    response_turns: List[Turn] = field(default_factory=list)


def _sentences(text: str) -> List[str]:
    return [s.strip() for s in _SENTENCE_SPLIT.split(text) if s.strip()]


def _is_question_sentence(sentence: str) -> bool:
    words = sentence.split()
    if len(words) < _MIN_QUESTION_WORDS:
        return False
    if sentence.endswith("?"):
        return True
    first = words[0].lower().strip(",")
    return first in INTERROGATIVE_OPENERS and len(words) >= 4


def detect_questions(turns: List[Turn]) -> List[Question]:
    """Tag question sentences inside interviewer turns (roles must be applied first)."""
    questions: List[Question] = []
    counter = 0
    for turn in turns:
        if turn.speaker_role != "interviewer":
            continue
        for sentence in _sentences(turn.text):
            if _is_question_sentence(sentence):
                counter += 1
                questions.append(Question(
                    question_id=f"q{counter:03d}",
                    turn_index=turn.index,
                    text=sentence,
                ))
    return questions


def pair_questions_with_responses(turns: List[Turn], questions: List[Question]) -> List[QAPair]:
    """Attach interviewee response turns to each question (up to the next question's turn)."""
    pairs: List[QAPair] = []
    ordered = sorted(questions, key=lambda q: (q.turn_index, q.question_id))

    for i, q in enumerate(ordered):
        # Same-turn follow-up questions: only the last question of a turn takes
        # the response block; earlier ones get none (visible in coverage).
        if i + 1 < len(ordered) and ordered[i + 1].turn_index == q.turn_index:
            pairs.append(QAPair(question=q, response_turns=[]))
            continue
        next_turn_index = ordered[i + 1].turn_index if i + 1 < len(ordered) else None
        responses = [
            t for t in turns
            if t.speaker_role == "interviewee"
            and t.index > q.turn_index
            and (next_turn_index is None or t.index < next_turn_index)
        ]
        pairs.append(QAPair(question=q, response_turns=responses))
    return pairs
