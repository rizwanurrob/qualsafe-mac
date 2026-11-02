"""The project's research question: what the person is trying to find out, kept with the project.

Update 3, book-audit item F2. Saldaña (2013, p. 21) has the analyst keep the research question and goals
beside them while coding, and Creswell has the write-up open with it. It is one short piece of text kept in
the project's `meta` table (so it travels with the `.qnw` file) and shown on the coding screens. It is the
analyst's own words about their study, not anything from a response. No front-end imports.
"""

from __future__ import annotations

KEY = "research_question"

#: Long enough for a question and its sub-questions; not a place to paste a proposal.
MAX_CHARS = 600

LABEL = "Research question"
PROMPT = "What are you trying to find out?"


def clean(text: str) -> str:
    """The text as it will be kept: one run of words, trimmed, within the limit."""
    return " ".join(str(text or "").split())[:MAX_CHARS]


def get(project) -> str:
    return clean(project.get_meta(KEY, ""))


def set(project, text: str) -> str:  # noqa: A001 - reads naturally as research_question.set(project, ...)
    kept = clean(text)
    project.set_meta(KEY, kept)
    return kept
