"""Where you are in the web app: Home, a step of an activity, Settings, or Help (phase 4b).

Update 3 replaces the mode wizard and the long page list with Home and three activities
(Surveys, Charts, Interviews), each a short path of steps (`core/ux/activities.py`, the same
data the desktop app reads). A step shows one screen, or a few to pick between, and tucks the
rest under "More tools".

State, all in `st.session_state`:

* `view`      "home" | "activity" | "settings" | "help"
* `activity`  the current activity key, when `view` is "activity"
* `step_<activity>`      the step the person is on in each activity (kept when they leave)
* `screen_<activity>_<step>`   the screen showing in that step (a legacy page name)
* `nav_target`  a legacy page name ("Run Analysis") set by a Continue or Go-to button anywhere;
  `apply_nav_target` turns it into the right place. Every existing page can keep saying
  `goto("Analysis")` and it lands in the right activity and step.
* `app_mode`  "survey" | "interview" | "": kept in step with the activity, because older tests and
  settings know it. It is no longer chosen on a wizard and is not restored on launch (the app
  opens on Home).

Pure logic with `st.session_state` as its only store, so it is tested without a browser.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

import streamlit as st

from core.ux import activities, coding_choices

SURFACE = activities.WEB
HOME, ACTIVITY, SETTINGS, HELP = "home", "activity", "settings", "help"
ACTIVITY_MODE = {"surveys": "survey", "interviews": "interview", "charts": ""}
MODE_ACTIVITY = {"survey": "surveys", "interview": "interviews"}

#: Pages that live in Settings, with the tab each opens on.
SETTINGS_TABS = ("General", "Models", "Project and backups")
SETTINGS_PAGES = {"Model Manager": "Models", "Data Management": "Project and backups"}
HELP_PAGES = ("Help & Troubleshooting",)


def init_nav() -> None:
    """Default state: Home. An old-style `app_mode` set before the first run (a test, an old
    link) opens the matching activity instead, so those keep working."""
    state = st.session_state
    if "view" not in state:
        mode = state.get("app_mode", "")
        if mode in MODE_ACTIVITY:
            state["view"], state["activity"] = ACTIVITY, MODE_ACTIVITY[mode]
        else:
            state["view"], state["activity"] = HOME, ""
    state.setdefault("activity", "")
    state.setdefault("settings_tab", SETTINGS_TABS[0])


# -- places ------------------------------------------------------------------------------

def view() -> str:
    return st.session_state.get("view", HOME)


def current_activity() -> str:
    return st.session_state.get("activity", "") if view() == ACTIVITY else ""


def go_home() -> None:
    st.session_state["view"], st.session_state["activity"] = HOME, ""
    st.session_state["app_mode"] = ""


def go_settings(tab: str = "") -> None:
    st.session_state["view"] = SETTINGS
    if tab in SETTINGS_TABS:
        st.session_state["settings_tab"] = tab


def go_help(article: str = "") -> None:
    """Open Help, at an article (`<activity>-<step>`, a task id, or ""), remembering where to go back to."""
    state = st.session_state
    if state.get("view") == ACTIVITY and state.get("activity"):
        state["help_back"] = (state["activity"], step_of(state["activity"]))
    state["view"] = HELP
    if article:
        state["help_article"] = article


def step_of(activity_key: str) -> str:
    """The step a person is on in an activity (the first one if they have not started)."""
    steps = [s.key for s in activities.get(activity_key).steps]
    chosen = st.session_state.get(f"step_{activity_key}")
    return chosen if chosen in steps else steps[0]


def go_activity(activity_key: str, step_key: str = "", screen: str = "") -> None:
    """Open an activity at a step (where they were, by default) and optionally a screen."""
    activity = activities.get(activity_key)
    if step_key:
        activity.step(step_key)                                   # KeyError if there is no such step
        st.session_state[f"step_{activity_key}"] = step_key
    st.session_state[f"step_{activity_key}"] = step_of(activity_key)
    st.session_state["view"], st.session_state["activity"] = ACTIVITY, activity_key
    st.session_state["app_mode"] = ACTIVITY_MODE[activity_key]
    if screen:
        st.session_state[screen_key(activity_key, step_of(activity_key))] = screen


def screen_key(activity_key: str, step_key: str) -> str:
    return f"screen_{activity_key}_{step_key}"


def screens(activity_key: str, step_key: str) -> Tuple[List[str], List[str]]:
    """(main screens, more tools) of a step on the web."""
    step = activities.get(activity_key).step(step_key)
    return list(step.screens.get(SURFACE, ())), list(step.more.get(SURFACE, ()))


def current_screen(activity_key: str, step_key: str) -> str:
    """The screen to show in a step: the one chosen, else the first main screen."""
    main, more = screens(activity_key, step_key)
    chosen = st.session_state.get(screen_key(activity_key, step_key))
    return chosen if chosen in main + more else (main[0] if main else (more[0] if more else ""))


def set_screen(activity_key: str, step_key: str, screen: str) -> None:
    st.session_state[screen_key(activity_key, step_key)] = screen


# -- turning a page name into a place ----------------------------------------------------------

def resolve(page: str, prefer: str = "") -> Optional[Tuple[str, str]]:
    """(activity, step) that shows a legacy page; the preferred activity wins if it has it."""
    found = [(a, s) for a, s, sc, _more in activities.placements(SURFACE)
             if activities.top_level(sc) == activities.top_level(page)]
    if not found:
        return None
    for a, s in found:
        if a == prefer:
            return a, s
    return found[0]


def apply_nav_target() -> str:
    """Act on a pending `nav_target`. Returns the page it moved to, or an empty string."""
    state = st.session_state
    page = state.pop("nav_target", None)
    if not page:
        return ""
    if page in SETTINGS_PAGES:
        go_settings(SETTINGS_PAGES[page])
        return page
    if page in HELP_PAGES:
        go_help()
        return page
    where = resolve(page, prefer=state.get("activity", ""))
    if where is None:
        return ""
    activity_key, step_key = where
    go_activity(activity_key, step_key, screen=page)
    if (activity_key, step_key) == ("surveys", "code") and page in coding_choices.CHOICE_FOR_WEB_PAGE:
        state["code_choice"] = coding_choices.CHOICE_FOR_WEB_PAGE[page]      # which way to code
    return page


def breadcrumb() -> str:
    """`QualSafe › Surveys › 3 Code`, `QualSafe › Settings`, or just `QualSafe`."""
    parts = ["QualSafe"]
    current = view()
    if current == ACTIVITY and st.session_state.get("activity"):
        activity = activities.get(st.session_state["activity"])
        step = step_of(activity.key)
        parts += [activity.title, f"{activity.step_number(step)} {activity.step(step).title}"]
    elif current == SETTINGS:
        parts.append("Settings")
    elif current == HELP:
        parts.append("Help")
    return " › ".join(parts)
