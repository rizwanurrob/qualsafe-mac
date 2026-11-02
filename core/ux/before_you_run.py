"""The "Before you run" card on the Run step: a short reminder, shown until it is dismissed.

Update 3, book-audit item F4. The books this tool follows all say a person reads, codes and thinks first;
a first pass at the push of a button makes it easy to skip exactly the reading that does the analytic work.
A line on a help page is weaker than a prompt on the screen, so this is said where the button is. It is
shown until the person says they have read it, and the choice is remembered. No front-end imports.
"""

from __future__ import annotations

#: The preference key (a flag, never anything derived from the answers).
KEY = "before_run_hidden"

TITLE = "Before you run"

#: Plain words, short. Each line is one thing to do or to know.
LINES = (
    "Read some of the answers first. Suggestions are a draft to check, not a finding.",
    "Check a few suggestions against the answers themselves before you rely on them.",
    "Do not report a count from suggestions nobody has reviewed.",
)

BUTTON = "Got it, do not show this again"


def is_hidden(value) -> bool:
    """Whether a stored preference value means the card has been dismissed."""
    return str(value or "").strip().lower() in {"1", "true", "yes"}


def as_text() -> str:
    """The card as plain text (the web build shows it as a list)."""
    return "\n".join(f"- {line}" for line in LINES)
