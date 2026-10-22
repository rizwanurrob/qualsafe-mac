"""The first-visit tour of each activity (V8_PLAN.md section 6, point 3).

Four short cards per activity, each pointing at a real control: the step row, the one main
button, the folded More options, and the help button. Shown once, skippable, and opened
again from Help. Shared by both apps; nothing here imports Qt or Streamlit.

`target` names what a card points at; the app decides how to find it on screen:

* `rail`  the row of numbered steps
* `main`  the step's one filled button
* `more`  the folded More options
* `help`  the "Help for this step" link

Which tours have been seen is stored as a list of activity keys: a preference, never
anything derived from a response.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import List, Set, Tuple

from core.ux import activities

TARGETS = ("rail", "main", "more", "help")


@dataclass(frozen=True)
class Card:
    title: str
    text: str
    target: str


def tour(activity_key: str) -> Tuple[Card, ...]:
    """The cards for one activity. The step names come from the same data the screens use."""
    activity = activities.get(activity_key)
    names = ", ".join(s.title for s in activity.steps)
    return (
        Card(f"{activity.title} has {len(activity.steps)} steps",
             f"Work along the row: {names}. You can go back to any step, and QualSafe "
             "keeps your place.", "rail"),
        Card("One main button",
             "Each step has one filled button. It is usually what to press next.", "main"),
        Card("Less-used choices are folded away",
             "Open More options to see the rest. The usual settings work for most files.",
             "more"),
        Card("Help for the step you are on",
             "This opens a short article. The small i beside a choice explains that "
             "choice.", "help"),
    )


def parse(raw: object) -> Set[str]:
    """Activity keys from a stored string; anything malformed is dropped, never raised."""
    try:
        data = json.loads(raw) if isinstance(raw, str) and raw else []
    except ValueError:
        return set()
    known = {a.key for a in activities.ACTIVITIES}
    return {k for k in data if isinstance(k, str) and k in known} if isinstance(data, list) else set()


def dump(seen: Set[str]) -> str:
    return json.dumps(sorted(seen))


def mark_seen(seen: Set[str], activity_key: str) -> Set[str]:
    return set(seen) | {activity_key} if activity_key in {a.key for a in activities.ACTIVITIES} else set(seen)


def is_due(seen: Set[str], activity_key: str) -> bool:
    return activity_key not in seen


def keys() -> List[str]:
    return [a.key for a in activities.ACTIVITIES]
