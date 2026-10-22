"""
Caveats beside the number: one short sentence, with the full text one click away.

Update 3, design rule 5. A caveat is never removed, only moved next to the figure
it qualifies and shortened to its first sentence; *Why?* opens all of it. Both apps
use this so a caveat reads the same in each. No front-end imports.
"""

from __future__ import annotations

import re
from typing import Tuple

#: A short caveat is no longer than this many characters.
SHORT_LIMIT = 150

_TAGS = re.compile(r"<[^>]+>")
_BREAKS = re.compile(r"<\s*(br|/p|/li|/ul)\s*/?\s*>", re.IGNORECASE)
_LEADING_MARK = re.compile(r"^[\s" + chr(0x00B7) + chr(0x2022) + r"*\-]+")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9“\"'(])")


def plain(text: str) -> str:
    """Text with markup removed and spaces collapsed."""
    text = _BREAKS.sub(" | ", text or "")
    text = _TAGS.sub("", text).replace("&nbsp;", " ").replace("&amp;", "&")
    text = text.replace("&lt;", "<").replace("&gt;", ">")
    text = re.sub(r"(\s*\|\s*)+", " | ", text)
    return re.sub(r"\s+", " ", text).strip(" |")


def short_form(text: str, limit: int = SHORT_LIMIT) -> Tuple[str, bool]:
    """(the first sentence, whether there is more to read).

    Cuts at the first sentence end or line break, then at a word boundary if it is
    still longer than `limit`, adding an ellipsis. `more` is True when anything of
    the original text is left out.
    """
    whole = _LEADING_MARK.sub("", plain(text))
    if not whole:
        return "", False
    first = whole.split(" | ")[0]
    first = _SENTENCE_END.split(first)[0]
    if len(first) > limit:
        cut = first[:limit].rsplit(" ", 1)[0].rstrip(",;:")
        first = cut + "…"
    more = first.rstrip("…") != whole
    return first, more
