"""Who is speaking in an interview transcript (Update 3, item 4.5; V8_PLAN UX-11).

Wraps `interview/parse.py` (finds the turns) and `interview/speakers.py` (proposes who the
interviewer is) for the desktop app, and keeps the person's confirmed answer with the
transcript, in the source's existing `metadata` (no change to the project file format).

What is stored, and what is not
-------------------------------
`metadata["speakers"] = {"pattern": ..., "roles": {label: role}, "reviewed": True}`.
The turns themselves are not stored: they are found again from the transcript with the
stored pattern, so the transcript stays the single source of truth. A speaker label can be
a person's name, so this lives in the project file with the transcript and nowhere else:
never in settings, saved progress or logs.

Roles are only ever *proposed*; nothing is applied until the person confirms them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from interview.parse import Turn, segment_turns
from interview.speakers import apply_roles, infer_speaker_roles, speaker_stats

ROLES = ("interviewer", "interviewee", "other")

#: What the screens call each role.
ROLE_NAMES = {"interviewer": "Interviewer", "interviewee": "Participant", "other": "Someone else"}


@dataclass
class SpeakerRow:
    label: str            # exactly as written in the transcript
    turns: int
    share: float          # share of all the words said, 0..1
    questions: int        # turns that contain a question
    role: str             # the proposed role (the person may change it)


@dataclass
class SpeakerReview:
    pattern: str          # which transcript layout was recognised ("none" if none was)
    confidence: float     # how sure the layout was recognised, 0..1
    n_turns: int
    rows: List[SpeakerRow] = field(default_factory=list)
    rationale: str = ""
    preview: List[Tuple[str, str]] = field(default_factory=list)   # (label, start of the turn)

    @property
    def needs_roles(self) -> bool:
        """Two or more speakers: there is something to confirm."""
        return len(self.rows) >= 2


def analyse(raw_text: str, *, preview_turns: int = 6, preview_chars: int = 140) -> SpeakerReview:
    """Find the turns and propose roles. Pure: reads text, returns a proposal."""
    turns, pattern, confidence = segment_turns(raw_text)
    inference = infer_speaker_roles(turns)
    stats = speaker_stats(turns)
    total = sum(s.total_chars for s in stats) or 1
    rows = [SpeakerRow(label=s.label, turns=s.n_turns, share=s.total_chars / total,
                       questions=s.question_turns,
                       role=inference.role_by_label.get(s.label, "other"))
            for s in stats]
    preview = [(t.speaker_raw, _clip(t.text, preview_chars)) for t in turns[:preview_turns]]
    return SpeakerReview(pattern=pattern, confidence=confidence, n_turns=len(turns),
                         rows=rows, rationale=inference.rationale if len(rows) >= 2 else "",
                         preview=preview)


def _clip(text: str, limit: int) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "…"


def to_metadata(review: SpeakerReview, roles: Dict[str, str]) -> Dict[str, Any]:
    """The value stored under `metadata["speakers"]` once the person has confirmed `roles`."""
    clean = {label: (role if role in ROLES else "other") for label, role in roles.items()}
    return {"pattern": review.pattern, "roles": clean, "reviewed": True}


def stored(metadata: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The confirmed speaker record of a source's metadata, or None."""
    data = (metadata or {}).get("speakers")
    if (isinstance(data, dict) and data.get("reviewed") and isinstance(data.get("roles"), dict)
            and data.get("pattern") not in (None, "", "none")):
        return data
    return None


def turns_of(raw_text: str, metadata: Optional[Dict[str, Any]]) -> List[Turn]:
    """The transcript's turns with the confirmed roles filled in; [] if none were confirmed."""
    record = stored(metadata)
    if record is None:
        return []
    try:
        turns, _used, _conf = segment_turns(raw_text, pattern_name=record["pattern"])
    except ValueError:                 # a pattern name from a newer version: show nothing, break nothing
        return []
    return apply_roles(turns, record["roles"])


def spans_for(raw_text: str, metadata: Optional[Dict[str, Any]], *, roles: Tuple[str, ...]
              ) -> List[Tuple[int, int]]:
    """Character spans (start, end) of the turns spoken by someone in `roles`."""
    return [(t.char_start, t.char_end) for t in turns_of(raw_text, metadata) if t.speaker_role in roles]


def lies_within(text: str, span: Tuple[int, int], spans: List[Tuple[int, int]]) -> bool:
    """True when every word of `text[span]` falls inside `spans` (and the selection has words).

    Used to notice a selection that is only the interviewer's words. Spaces and line breaks
    between two turns do not count against it."""
    start, end = span
    if end <= start or not spans:
        return False
    inside = bytearray(end - start)
    for s, e in spans:
        lo, hi = max(start, s), min(end, e)
        if hi > lo:
            for i in range(lo - start, hi - start):
                inside[i] = 1
    has_text = False
    for offset, char in enumerate(text[start:end]):
        if not char.isspace():
            has_text = True
            if not inside[offset]:
                return False
    return has_text


def summary(metadata: Optional[Dict[str, Any]]) -> str:
    """One line for the document header, for example `Interviewer: Q · Participant: A`."""
    record = stored(metadata)
    if record is None:
        return ""
    by_role: Dict[str, List[str]] = {}
    for label, role in record["roles"].items():
        by_role.setdefault(role, []).append(label)
    parts = []
    for role in ROLES:
        labels = by_role.get(role)
        if not labels:
            continue
        name = ROLE_NAMES[role]
        # "Interviewer: Interviewer" says nothing twice
        parts.append(name if [l.lower() for l in labels] == [name.lower()] else f"{name}: {', '.join(labels)}")
    return " · ".join(parts)
