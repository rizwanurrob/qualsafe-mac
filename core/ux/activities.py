"""The three activities, their steps, and where every screen lives.

Surveys, Charts and Interviews are short numbered paths. Each step names the
screens it shows (`screens`) and the ones kept one click away (`more`), for each
front end. Screen names are the ones used today: the desktop tab titles and the
web sidebar page names. A desktop screen with sub-tabs is written
`Parent/Sub`, e.g. `Survey/Data`; `top_level()` gives the parent.

Nothing is deleted by this layout: `unplaced_screens()` must stay empty.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterator, Tuple

DESKTOP = "desktop"
WEB = "web"
SURFACES = (DESKTOP, WEB)

# Every screen that exists today (V8_PLAN.md section 3.5), per front end.
DESKTOP_SCREENS: Tuple[str, ...] = (
    "Documents", "Codebook", "Analysis", "Charts", "Data Charts", "Modelling",
    "Search", "Query", "Survey", "Reports", "Data", "Models", "Help",
)
WEB_SCREENS: Tuple[str, ...] = (
    "Data Setup", "Theme Setup", "Run Analysis", "Iterative Labeling Lab",
    "Alt Survey Flow", "Analysis", "Chart Builder", "Data Charts", "Modelling",
    "Codebook", "Documents", "Search", "Query & Synthesis",
    "Results & Downloads", "Data Management", "Model Manager",
    "Help & Troubleshooting", "Interview Mode",
)
ALL_SCREENS: Dict[str, Tuple[str, ...]] = {DESKTOP: DESKTOP_SCREENS, WEB: WEB_SCREENS}

Screens = Dict[str, Tuple[str, ...]]


@dataclass(frozen=True)
class Step:
    key: str
    title: str
    intro: str  # one plain line under the step title
    screens: Screens = field(default_factory=dict)  # shown in the step
    more: Screens = field(default_factory=dict)     # behind "More options"/"More tools"


@dataclass(frozen=True)
class Activity:
    key: str
    title: str
    tagline: str       # one sentence on the Home card
    colour_token: str  # key in core.theme (added in item 0.4)
    steps: Tuple[Step, ...]

    def step(self, key: str) -> Step:
        for s in self.steps:
            if s.key == key:
                return s
        raise KeyError(key)

    def step_number(self, key: str) -> int:
        return 1 + [s.key for s in self.steps].index(key)


def _s(desktop: Tuple[str, ...] = (), web: Tuple[str, ...] = ()) -> Screens:
    return {DESKTOP: tuple(desktop), WEB: tuple(web)}


SURVEYS = Activity(
    key="surveys",
    title="Surveys",
    tagline="Find the themes in open-ended answers.",
    colour_token="activity.surveys",
    steps=(
        Step("load", "Load",
             "Pick a file or the sample, and say which column holds the answers.",
             screens=_s(("Survey/Data",), ("Data Setup",))),
        Step("themes", "Themes",
             "Write or pick your list of themes.",
             screens=_s(("Survey/Themes",), ("Theme Setup",)),
             more=_s(("Codebook",), ("Codebook",))),
        Step("code", "Code",
             "Choose how to code the answers, then run it and review what needs review.",
             screens=_s(("Survey/Run",), ("Run Analysis",)),
             more=_s((), ("Iterative Labeling Lab", "Alt Survey Flow"))),
        Step("explore", "Explore",
             "Read the results: how often each theme comes up, and for whom.",
             screens=_s(("Analysis", "Charts", "Search", "Modelling"),
                        ("Analysis", "Chart Builder", "Search", "Modelling")),
             more=_s(("Query",), ("Query & Synthesis",))),
        Step("report", "Report",
             "Save the report you need.",
             screens=_s(("Reports",), ("Results & Downloads",))),
    ),
)

CHARTS = Activity(
    key="charts",
    title="Charts",
    tagline="Turn a spreadsheet of numbers or choices into charts and tables.",
    colour_token="activity.charts",
    steps=(
        Step("open", "Open",
             "Open a spreadsheet or the sample.",
             screens=_s(("Data Charts",), ("Data Charts",))),
        Step("question", "Pick a question",
             "Choose the question. QualSafe picks a chart that fits.",
             screens=_s(("Data Charts",), ("Data Charts",))),
        Step("adjust", "Adjust",
             "Filter, relabel, order, colour and title.",
             screens=_s(("Data Charts",), ("Data Charts",))),
        Step("save", "Save",
             "Save the picture or the table, or keep the chart in the project.",
             screens=_s(("Data Charts",), ("Data Charts",))),
    ),
)

INTERVIEWS = Activity(
    key="interviews",
    title="Interviews",
    tagline="Code transcripts and compare what people said.",
    colour_token="activity.interviews",
    steps=(
        Step("add", "Add transcripts",
             "Add your transcript files, one file for each interview.",
             screens=_s(("Documents",), ("Documents",)),
             more=_s((), ("Interview Mode",))),
        Step("code", "Code",
             "Read each transcript and code the passages.",
             screens=_s(("Documents",), ("Documents",))),
        Step("codebook", "Codebook",
             "Tidy your codes: rename, define, group.",
             screens=_s(("Codebook",), ("Codebook",))),
        Step("explore", "Explore",
             "Compare across interviews: codes by person or group, search, quotes.",
             screens=_s(("Analysis", "Charts", "Search", "Modelling"),
                        ("Analysis", "Chart Builder", "Search", "Modelling")),
             more=_s(("Query",), ("Query & Synthesis",))),
        Step("report", "Report",
             "Save the report you need.",
             screens=_s(("Reports",), ("Results & Downloads",))),
    ),
)

ACTIVITIES: Tuple[Activity, ...] = (SURVEYS, CHARTS, INTERVIEWS)

# Not activities: reachable from Home and from every screen.
SETTINGS_SCREENS: Screens = _s(("Models", "Data"), ("Model Manager", "Data Management"))
HELP_SCREENS: Screens = _s(("Help",), ("Help & Troubleshooting",))

MAX_STEPS = 5


def get(key: str) -> Activity:
    for a in ACTIVITIES:
        if a.key == key:
            return a
    raise KeyError(key)


#: Plain names for the screens a step offers a choice between on the web (the page names are older).
WEB_SCREEN_TITLES = {
    "Interview Mode": "One interview, with a guide and summaries",
    "Chart Builder": "Charts of themes",
    "Modelling": "Model an outcome",
    "Query & Synthesis": "Query",
}


def web_screen_title(screen: str) -> str:
    return WEB_SCREEN_TITLES.get(screen, screen)


def top_level(screen: str) -> str:
    """`Survey/Data` -> `Survey`."""
    return screen.split("/", 1)[0]


def placements(surface: str) -> Iterator[Tuple[str, str, str, bool]]:
    """Yield (activity key, step key, screen, is_more) for one front end."""
    for a in ACTIVITIES:
        for st in a.steps:
            for sc in st.screens.get(surface, ()):
                yield a.key, st.key, sc, False
            for sc in st.more.get(surface, ()):
                yield a.key, st.key, sc, True


def placed_screens(surface: str) -> set:
    found = {top_level(sc) for _, _, sc, _ in placements(surface)}
    found |= set(SETTINGS_SCREENS[surface]) | set(HELP_SCREENS[surface])
    return found


def unplaced_screens(surface: str) -> Tuple[str, ...]:
    """Screens that exist today but appear nowhere in the new layout."""
    have = placed_screens(surface)
    return tuple(s for s in ALL_SCREENS[surface] if s not in have)


def locations(surface: str, screen: str) -> Tuple[str, ...]:
    """Where a screen now lives, in words: `Surveys › 4 Explore`.

    A screen kept behind More tools says so. Settings and Help are not
    activities, so they read `Settings › Models` and `Help`.
    """
    top = top_level(screen)
    found = []
    for key, step_key, sc, more in placements(surface):
        if top_level(sc) != top:
            continue
        act = get(key)
        text = f"{act.title} › {act.step_number(step_key)} {act.step(step_key).title}"
        text += " (more tools)" if more else ""
        if text not in found:
            found.append(text)
    if top in SETTINGS_SCREENS[surface]:
        found.append("Settings › " + {"Models": "Models", "Data": "Project and backups",
                                      "Model Manager": "Models",
                                      "Data Management": "Project and backups"}[top])
    if top in HELP_SCREENS[surface]:
        found.append("Help (top right)")
    return tuple(found)


def activity_for(surface: str, screen: str) -> Tuple[str, ...]:
    """Keys of the activities that show this screen (shared tools show in two)."""
    top = top_level(screen)
    return tuple(sorted({k for k, _, sc, _ in placements(surface) if top_level(sc) == top}))
