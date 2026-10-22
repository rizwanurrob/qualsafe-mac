"""The short list of recent projects shown on Home.

Each entry is a file path and the activity it belongs to, nothing else: no
document names, no codes, no text. The list is stored as one JSON string in the
desktop preferences (`recent_projects`), under the same rule as every other
preference: settings and paths, never anything derived from a response.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

MAX_RECENT = 5
MAX_PATH = 1024

Entry = Dict[str, str]

#: Only these two activities have project files.
_PROJECT_ACTIVITIES = ("surveys", "interviews")


def parse(raw: object) -> List[Entry]:
    """Entries from a stored string; anything malformed is dropped, never raised."""
    try:
        data = json.loads(raw) if isinstance(raw, str) and raw else []
    except ValueError:
        return []
    out: List[Entry] = []
    for item in data if isinstance(data, list) else []:
        if (isinstance(item, dict) and isinstance(item.get("path"), str)
                and 0 < len(item["path"]) <= MAX_PATH
                and item.get("activity") in _PROJECT_ACTIVITIES):
            out.append({"path": item["path"], "activity": item["activity"]})
    return out[:MAX_RECENT]


def dump(entries: List[Entry]) -> str:
    return json.dumps([{"path": e["path"], "activity": e["activity"]}
                       for e in entries[:MAX_RECENT]])


def add(entries: List[Entry], path: str, activity: str) -> List[Entry]:
    """`path` first, with the older copy of the same path removed."""
    if activity not in _PROJECT_ACTIVITIES or not path or len(path) > MAX_PATH:
        return list(entries)
    key = _same(path)
    rest = [e for e in entries if _same(e["path"]) != key]
    return ([{"path": path, "activity": activity}] + rest)[:MAX_RECENT]


def existing(entries: List[Entry]) -> List[Entry]:
    """Entries whose file is still there."""
    return [e for e in entries if Path(e["path"]).exists()]


def _same(path: str) -> str:
    return str(Path(path)).lower()
