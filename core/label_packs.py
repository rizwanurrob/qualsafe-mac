#!/usr/bin/env python
"""
Custom label packs (v3.8.1, item 8.6).

The built-in packs are starting points; an analyst's *refined* label set is the
valuable artifact. This stores named packs as plain YAML next to the app
settings, so they reappear in the Theme Setup selectbox — and because it's just a
YAML file, a pack is also a shareable thing you can email a colleague.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]


#: Built-in starter label packs for zero-shot thematic coding.
#:
#: These lived in `app/shared/data.make_suggested_labels`, a pure function
#: returning a literal that could not be imported without pulling Streamlit into
#: the process — so the desktop build kept a second copy, and two copies of the
#: same content drift (PORTED_BACK.md §7). They belong here, beside the packs an
#: analyst saves.
#:
#: Dict order is the picker's order, so the first pack is the default. Education
#: leads because this tool's home audience is institutional research on student
#: data, and the pack matches the built-in sample dataset so the sample path
#: works out of the box.
BUILTIN_PACKS: Dict[str, List[str]] = {
    "Education / Student Experience": [
        "Sense of belonging",
        "Financial concerns",
        "Academic difficulty",
        "Time management & workload",
        "Advising & support services",
        "Mental health & stress",
        "Campus life & friendships",
        "Commuting & logistics",
        "Positive experience",
    ],
    "Customer Experience": [
        "Ease of use issue",
        "Reliability bug",
        "Speed/performance concern",
        "Support quality feedback",
        "Pricing/value concern",
        "Feature request",
        "Positive experience",
        "Trust or privacy concern",
    ],
    "Employee Feedback": [
        "Manager communication",
        "Workload pressure",
        "Career growth",
        "Compensation fairness",
        "Team collaboration",
        "Tools/process friction",
        "Recognition and morale",
        "Policy concern",
    ],
    "Healthcare Experience": [
        "Wait time concern",
        "Staff empathy",
        "Communication clarity",
        "Care quality concern",
        "Billing concern",
        "Access difficulty",
        "Follow-up request",
        "Positive care experience",
    ],
    "Course / Instruction Feedback": [
        "Instruction clarity",
        "Curriculum relevance",
        "Assessment fairness",
        "Student support",
        "Classroom environment",
        "Technology/tools issue",
        "Scheduling concern",
        "Positive learning experience",
    ],
}


def all_packs() -> Dict[str, List[str]]:
    """The built-in packs plus any the analyst saved, custom winning on a clash.

    A broken packs file must never block a run, so a failure to read the custom
    ones degrades to the built-ins rather than raising.
    """
    packs = dict(BUILTIN_PACKS)
    try:
        packs.update(load_custom_packs())
    except Exception:  # noqa: BLE001 - a broken packs file must not block a run
        pass
    return packs


def _packs_path() -> Path:
    override = os.environ.get("QNW_SETTINGS_DIR", "").strip()
    base = Path(override) if override else PROJECT_ROOT
    return base / "label_packs.yaml"


def load_custom_packs() -> Dict[str, List[str]]:
    """User-saved packs; {} when absent or unreadable."""
    path = _packs_path()
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    if not isinstance(data, dict):
        return {}
    packs: Dict[str, List[str]] = {}
    for name, labels in data.items():
        if isinstance(labels, list):
            cleaned = [str(x).strip() for x in labels if str(x).strip()]
            if cleaned:
                packs[str(name)] = cleaned
    return packs


def save_custom_pack(name: str, labels: List[str]) -> Path:
    """Save (or overwrite) one named pack. Returns the packs file path."""
    name = str(name).strip()
    cleaned = [str(x).strip() for x in labels if str(x).strip()]
    if not name:
        raise ValueError("Pack name is required.")
    if not cleaned:
        raise ValueError("A pack needs at least one label.")
    packs = load_custom_packs()
    packs[name] = cleaned
    path = _packs_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(packs, sort_keys=True, allow_unicode=True),
                    encoding="utf-8")
    return path


def delete_custom_pack(name: str) -> bool:
    """Remove a pack. Returns True if it existed."""
    packs = load_custom_packs()
    if name not in packs:
        return False
    del packs[name]
    _packs_path().write_text(yaml.safe_dump(packs, sort_keys=True, allow_unicode=True),
                             encoding="utf-8")
    return True
