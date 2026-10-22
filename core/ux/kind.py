"""Which activity a project belongs to, from what it holds.

A project made from a survey spreadsheet holds `survey_response` sources and
belongs to Surveys. A project of transcripts or other documents holds
`interview` or `document` sources and belongs to Interviews. An empty project
is made to import documents into, so it opens in Interviews too.

Charts has no project file, so it is never the answer here.
"""

from __future__ import annotations

from typing import Iterable, Tuple

SURVEY_TYPES = {"survey_response"}
DOCUMENT_TYPES = {"interview", "document"}


def activity_for_source_types(types: Iterable[str]) -> str:
    """`"surveys"` or `"interviews"` for the source types a project holds."""
    present = set(types)
    if present & SURVEY_TYPES and not present & DOCUMENT_TYPES:
        return "surveys"
    return "interviews"


def landing(types: Iterable[str], n_codes: int, n_codings: int) -> Tuple[str, str]:
    """(activity key, step key) where a project should open.

    Surveys: coded already, so read the results (Explore); a theme list but no
    coding yet, so Code; neither, so Themes. Interviews: documents present, so
    the reader (Code); an empty project, so Add transcripts. A survey project
    never lands on the document list, which has nothing in it.
    """
    types = list(types)
    activity = activity_for_source_types(types)
    if activity == "surveys":
        if n_codings > 0:
            return activity, "explore"
        return activity, "code" if n_codes > 0 else "themes"
    return activity, "code" if types else "add"
