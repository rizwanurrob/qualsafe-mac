#!/usr/bin/env python
"""
Speaker role inference (v3.1, I1): which raw label is the interviewer?

Heuristics (from the handoff §5.4[3]): the interviewer asks most of the questions
and speaks less total text. This module only PROPOSES a mapping with a confidence
and a human-readable rationale — role assignment is consequential, so the analyst
confirms or corrects it at the mandatory review checkpoint in the UI. Never a
silent guess.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import Dict, List

from interview.parse import Turn


@dataclass
class SpeakerStats:
    label: str
    n_turns: int
    total_chars: int
    question_turns: int

    @property
    def question_ratio(self) -> float:
        return self.question_turns / self.n_turns if self.n_turns else 0.0


@dataclass
class RoleInference:
    role_by_label: Dict[str, str]        # label -> "interviewer" | "interviewee" | "other"
    confidence: float                    # 0..1 — how separable the two voices were
    rationale: str                       # human-readable, shown at the review checkpoint
    stats: List[SpeakerStats] = field(default_factory=list)


def speaker_stats(turns: List[Turn]) -> List[SpeakerStats]:
    by_label: Dict[str, SpeakerStats] = {}
    for t in turns:
        s = by_label.setdefault(t.speaker_raw, SpeakerStats(t.speaker_raw, 0, 0, 0))
        s.n_turns += 1
        s.total_chars += len(t.text)
        if "?" in t.text:
            s.question_turns += 1
    return list(by_label.values())


def infer_speaker_roles(turns: List[Turn]) -> RoleInference:
    """Propose interviewer/interviewee roles for the raw speaker labels.

    With one label (or none) the inference abstains (confidence 0.0). With more
    than two labels, the best interviewer candidate is chosen, the biggest
    remaining talker becomes interviewee, and the rest are "other" (focus groups
    are out of scope for v3.1; the model allows them).
    """
    stats = speaker_stats(turns)
    if len(stats) < 2:
        label = stats[0].label if stats else "UNKNOWN"
        return RoleInference(
            role_by_label={label: "interviewee"},
            confidence=0.0,
            rationale="Only one speaker label detected — roles cannot be inferred. Please review.",
            stats=stats,
        )

    total_chars = sum(s.total_chars for s in stats) or 1
    # Interviewer candidate: highest question ratio; tie-break on fewer chars.
    ranked = sorted(stats, key=lambda s: (-s.question_ratio, s.total_chars))
    interviewer = ranked[0]
    # Interviewee: whoever speaks the most among the rest.
    rest = sorted([s for s in stats if s.label != interviewer.label],
                  key=lambda s: -s.total_chars)
    interviewee = rest[0]

    role_by_label = {interviewer.label: "interviewer", interviewee.label: "interviewee"}
    for s in rest[1:]:
        role_by_label[s.label] = "other"

    # Confidence: separation in question-asking + separation in talk share.
    q_gap = max(0.0, interviewer.question_ratio - interviewee.question_ratio)
    share_gap = max(0.0, (interviewee.total_chars - interviewer.total_chars) / total_chars)
    confidence = round(min(1.0, 0.7 * q_gap + 0.3 * min(1.0, share_gap * 2)), 3)

    rationale = (
        f"'{interviewer.label}' asks questions in {interviewer.question_turns}/{interviewer.n_turns} "
        f"turns ({interviewer.question_ratio:.0%}) vs '{interviewee.label}' "
        f"({interviewee.question_ratio:.0%}), and speaks "
        f"{interviewer.total_chars / total_chars:.0%} of the text vs "
        f"{interviewee.total_chars / total_chars:.0%}. Confirm or correct before analysis."
    )
    return RoleInference(role_by_label=role_by_label, confidence=confidence,
                         rationale=rationale, stats=stats)


def apply_roles(turns: List[Turn], role_by_label: Dict[str, str]) -> List[Turn]:
    """Return turns with speaker_role filled from a (possibly analyst-corrected) mapping."""
    return [
        dataclasses.replace(t, speaker_role=role_by_label.get(t.speaker_raw, "other"))
        for t in turns
    ]
