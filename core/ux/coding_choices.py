"""The three ways to code survey answers (V8_PLAN.md section 3.2, UX-10), shared by both apps.

Surveys, step 3. Each way has one line saying when to use it. The desktop and the web app show
the same words; this file is where they live. Nothing here imports Qt or Streamlit.
"""

from __future__ import annotations

from typing import Dict, Tuple

#: (key, title, when to use it)
CHOICES: Tuple[Tuple[str, str, str], ...] = (
    ("suggest", "Suggest codes for me to check",
     "You have a list of themes but no coded examples. QualSafe suggests a code for "
     "every answer and you review them."),
    ("codebook", "Code with a written codebook",
     "Each code has a definition with rules for what to include and leave out. A "
     "preview: it needs a separate download the first time, and its codes should be "
     "checked against your own."),
    ("hand", "I'll code by hand",
     "A small sample, or to check the computer's suggestions. You read each answer and tick "
     "the codes that apply to it."),
)
KEYS = tuple(c[0] for c in CHOICES)

#: The web page behind each choice (the web app's page names).
WEB_PAGE: Dict[str, str] = {
    "suggest": "Run Analysis",
    "codebook": "Alt Survey Flow",
    "hand": "Iterative Labeling Lab",
}
CHOICE_FOR_WEB_PAGE: Dict[str, str] = {page: key for key, page in WEB_PAGE.items()}


def title(key: str) -> str:
    return next(t for k, t, _w in CHOICES if k == key)
