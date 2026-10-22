"""Help text shared by both apps (V8_PLAN.md section 6).

One folder, plain Markdown, read by the desktop app now and the web app in phase 4b, so
the two cannot drift apart and the word test covers every line. Nothing here imports Qt
or Streamlit.

`steps/<activity>-<step>.md` is the article for one step of one activity. Its first line
is a `# Title`. The one-line intro under each step title is not stored here: it is
`Step.intro` in `core/ux/activities.py`, the single source the screens already read.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Tuple

from core.ux import activities

HELP_DIR = Path(__file__).resolve().parent
STEPS_DIR = HELP_DIR / "steps"


def article_id(activity_key: str, step_key: str) -> str:
    return f"{activity_key}-{step_key}"


def article_path(activity_key: str, step_key: str) -> Path:
    return STEPS_DIR / f"{article_id(activity_key, step_key)}.md"


def article(activity_key: str, step_key: str) -> Optional[str]:
    """The Markdown for one step, or None if it has not been written."""
    path = article_path(activity_key, step_key)
    return path.read_text(encoding="utf-8") if path.is_file() else None


def title_of(markdown: str) -> str:
    for line in markdown.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def steps() -> List[Tuple[str, str]]:
    """(activity key, step key) for every step of every activity, in order."""
    return [(a.key, s.key) for a in activities.ACTIVITIES for s in a.steps]


def intro(activity_key: str, step_key: str) -> str:
    return activities.get(activity_key).step(step_key).intro


def missing() -> List[str]:
    """Steps that have no article yet."""
    return [article_id(a, s) for a, s in steps() if article(a, s) is None]


def index() -> List[Dict[str, str]]:
    """One row per step: what the contents list and the search box read."""
    rows = []
    for a in activities.ACTIVITIES:
        for s in a.steps:
            text = article(a.key, s.key) or ""
            rows.append({"id": article_id(a.key, s.key), "activity": a.title,
                         "step": s.title, "title": title_of(text) or s.title,
                         "intro": s.intro})
    return rows


# -- tasks, glossary, troubleshooting (item 4.4) -------------------------------------------

TASKS_DIR = HELP_DIR / "tasks"
GLOSSARY_PATH = HELP_DIR / "glossary.md"
TROUBLESHOOTING_PATH = HELP_DIR / "troubleshooting.md"


def task_ids() -> List[str]:
    """The task articles, in a fixed order (the order a researcher reaches for them)."""
    order = ["see-the-top-theme", "compare-two-groups", "check-the-computer-against-me",
             "make-a-chart-for-a-slide", "code-an-interview", "come-back-later",
             "write-the-methods", "erase-a-participant"]
    extra = sorted(p.stem for p in TASKS_DIR.glob("*.md") if p.stem not in order)
    return [t for t in order if (TASKS_DIR / f"{t}.md").is_file()] + extra


def task(task_id: str) -> Optional[str]:
    path = TASKS_DIR / f"{task_id}.md"
    return path.read_text(encoding="utf-8") if path.is_file() else None


def glossary() -> str:
    return GLOSSARY_PATH.read_text(encoding="utf-8")


def troubleshooting() -> str:
    return TROUBLESHOOTING_PATH.read_text(encoding="utf-8")


def glossary_entries() -> List[Tuple[str, str]]:
    """(plain term, the rest of the entry) for each `**Term** ...` paragraph."""
    out = []
    for block in glossary().split("\n\n"):
        block = block.strip()
        if block.startswith("**") and "**" in block[2:]:
            term, _, rest = block[2:].partition("**")
            out.append((term.strip().rstrip("."), rest.strip()))
    return out
