"""
The frame around the screens: a top bar, a step rail, and the screens of a step.

Update 3 replaces the row of 13 tabs with three activities (Surveys, Charts,
Interviews), each a short numbered path. This file holds the three pieces that
make that work, none of which knows what any screen does:

* `TopBar`      Home, where you are (`QualSafe > Surveys > 3 Code`), Settings, Help.
* `StepRail`    the numbered steps of the current activity.
* `ActivityView` the rail, a one-line intro, and the screens of the current step.

The screens themselves are the existing views, built once by the main window and
handed in. A step *mounts* the ones it names (from `core.ux.activities`) and
unmounts the rest, so a view such as Analysis can sit in both Surveys and
Interviews without being built twice.
"""

from __future__ import annotations

from typing import Callable, Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup, QFrame, QHBoxLayout, QLabel, QPushButton, QTabWidget,
    QVBoxLayout, QWidget,
)

from core.ux import activities
from core.ux.help import media
from qualsafe_qt.theme import activity_shell_stylesheet, activity_topbar_stylesheet
from qualsafe_qt.version import APP_NAME

#: Plain names for the tabs inside a step. Anything not listed keeps its own name.
SCREEN_TITLES: Dict[str, str] = {
    "Charts": "Charts of themes",
    "Modelling": "Model an outcome",
    "Data Charts": "Charts",
    "Survey/Data": "Load",
    "Survey/Themes": "Themes",
    "Survey/Run": "Code",
}


class TopBar(QFrame):
    """Always visible: Home on the left, Settings and Help on the right."""

    home_requested = Signal()
    settings_requested = Signal()
    help_requested = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("topBar")
        self._mode = "dark"
        self._activity: Optional[str] = None
        row = QHBoxLayout(self)
        row.setContentsMargins(12, 6, 12, 6)

        self.home_button = QPushButton("Home")
        self.home_button.setToolTip("Back to the three activities. Your place is kept.")
        self.home_button.clicked.connect(self.home_requested.emit)
        row.addWidget(self.home_button)

        self.crumb = QLabel(APP_NAME)
        self.crumb.setObjectName("breadcrumb")
        font = self.crumb.font()
        font.setBold(True)
        self.crumb.setFont(font)
        row.addWidget(self.crumb, 1)

        self.settings_button = QPushButton("Settings")
        self.settings_button.clicked.connect(self.settings_requested.emit)
        row.addWidget(self.settings_button)
        self.help_button = QPushButton("Help")
        self.help_button.clicked.connect(self.help_requested.emit)
        row.addWidget(self.help_button)

    def set_location(self, *parts: str, activity: Optional[str] = None) -> None:
        """`set_location("Surveys", "3 Code", activity="surveys")` shows
        `QualSafe › Surveys › 3 Code` on a band in that activity's colour."""
        self.crumb.setText("  ›  ".join((APP_NAME,) + tuple(parts)))
        self.home_button.setVisible(bool(parts))
        self._activity = activity
        self._style()

    def set_theme_mode(self, mode: str) -> None:
        self._mode = mode
        self._style()

    def _style(self) -> None:
        self.setStyleSheet(activity_topbar_stylesheet(self._activity, self._mode)
                           if self._activity else "")


class StepRail(QWidget):
    """The numbered steps of one activity. Click a step to go to it."""

    step_selected = Signal(str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("stepRail")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)   # so the tint paints
        self._row = QHBoxLayout(self)
        self._row.setContentsMargins(12, 6, 12, 6)
        self._row.setSpacing(6)
        self._row.addStretch(1)
        self._buttons: Dict[str, QPushButton] = {}
        self._group: Optional[QButtonGroup] = None
        self._activity_key = ""

    def set_activity(self, activity: activities.Activity) -> None:
        if activity.key == self._activity_key:
            return
        self._activity_key = activity.key
        for button in self._buttons.values():
            self._row.removeWidget(button)
            button.hide()            # deleteLater waits for the event loop; hide now
            button.setParent(None)
            button.deleteLater()
        self._buttons = {}
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        for number, step in enumerate(activity.steps, start=1):
            button = QPushButton(f"{number}  {step.title}")
            button.setCheckable(True)
            button.setObjectName("stepButton")
            button.setProperty("step", step.key)
            button.clicked.connect(lambda _checked=False, k=step.key: self.step_selected.emit(k))
            self._group.addButton(button)
            self._row.insertWidget(len(self._buttons), button)   # before the stretch
            self._buttons[step.key] = button

    def set_current(self, step_key: str) -> None:
        button = self._buttons.get(step_key)
        if button is not None:
            button.setChecked(True)

    def step_keys(self) -> List[str]:
        return list(self._buttons)


class ActivityView(QWidget):
    """The rail, the step's one-line intro, and the screens the step shows."""

    #: (activity key, step key) after every change of step.
    step_changed = Signal(str, str)
    #: (activity key, step key) when "Help for this step" is pressed.
    step_help_requested = Signal(str, str)
    #: (activity key, step key) when "Watch" is pressed: the step has short clips.
    watch_requested = Signal(str, str)

    def __init__(self, screens: Dict[str, QWidget],
                 selectors: Optional[Dict[str, Callable[[], None]]] = None,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._screens = screens
        self._selectors = selectors or {}
        self.activity_key = ""
        self.step_key = ""
        self._mode = "dark"
        #: (activity, step) -> the screen that was showing when you left it.
        self._tab_memory: Dict[tuple, str] = {}
        # The views are created as children of the main window, so until a step
        # mounts one it would show itself on top of whatever is there.
        for widget in {id(w): w for w in screens.values()}.values():
            widget.hide()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.rail = StepRail()
        self.rail.step_selected.connect(lambda key: self.show_step(self.activity_key, key))
        layout.addWidget(self.rail)

        self.intro = QLabel()
        self.intro.setObjectName("stepIntro")
        self.intro.setWordWrap(True)
        self.intro.setContentsMargins(14, 6, 14, 6)
        self.step_help = QPushButton("Help for this step")
        self.step_help.setObjectName("stepHelp")
        self.step_help.setFlat(True)
        self.step_help.setCursor(Qt.CursorShape.PointingHandCursor)
        self.step_help.setToolTip("Open the short help article for this step.")
        self.step_help.clicked.connect(
            lambda: self.step_help_requested.emit(self.activity_key, self.step_key))
        self.watch_button = QPushButton("Watch")
        self.watch_button.setObjectName("stepHelp")
        self.watch_button.setFlat(True)
        self.watch_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.watch_button.setToolTip("Watch a short clip about this step. It starts paused.")
        self.watch_button.clicked.connect(
            lambda: self.watch_requested.emit(self.activity_key, self.step_key))
        self.watch_button.setVisible(False)
        intro_row = QHBoxLayout()
        intro_row.setContentsMargins(0, 0, 14, 0)
        intro_row.addWidget(self.intro, 1)
        intro_row.addWidget(self.watch_button, 0, Qt.AlignmentFlag.AlignVCenter)
        intro_row.addWidget(self.step_help, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(intro_row)

        self.content = QTabWidget()
        self.content.setDocumentMode(True)
        layout.addWidget(self.content, 1)

    # -- navigation ----------------------------------------------------------
    def show_step(self, activity_key: str, step_key: str) -> None:
        activity = activities.get(activity_key)
        step = activity.step(step_key)
        if self.activity_key:
            # Remember which screen of the step you were on (Analysis, Search…).
            self._tab_memory[(self.activity_key, self.step_key)] = self.current_screen()
        changed = activity_key != self.activity_key
        self.activity_key, self.step_key = activity_key, step_key
        if changed:
            self._style()

        self.rail.set_activity(activity)
        self.rail.set_current(step_key)
        self.intro.setText(step.intro)
        self._refresh_watch()
        self._mount(step)
        remembered = self._tab_memory.get((activity_key, step_key))
        if remembered:
            self.show_named_screen(remembered)
        self.step_changed.emit(activity_key, step_key)

    def _refresh_watch(self) -> None:
        """A Watch link when this step has clips, saying how long (or how many)."""
        clips = media.for_article(f"{self.activity_key}-{self.step_key}")
        self.watch_button.setVisible(bool(clips))
        if len(clips) == 1:
            self.watch_button.setText(f"Watch ({clips[0].seconds} s)")
        elif clips:
            self.watch_button.setText(f"Watch ({len(clips)} short clips)")

    def set_theme_mode(self, mode: str) -> None:
        self._mode = mode
        if self.activity_key:
            self._style()

    def _style(self) -> None:
        self.setStyleSheet(activity_shell_stylesheet(self.activity_key, self._mode))

    def show_screen(self, activity_key: str, screen: str) -> bool:
        """Go to the first step of an activity that shows `screen` and select it."""
        for step in activities.get(activity_key).steps:
            names = (step.screens.get(activities.DESKTOP, ())
                     + step.more.get(activities.DESKTOP, ()))
            if screen in names:
                self.show_step(activity_key, step.key)
                self.content.setCurrentWidget(self._screens[screen])
                return True
        return False

    def current_screen(self) -> str:
        """Name (as in `core.ux.activities`) of the screen showing now, or ''."""
        widget = self.content.currentWidget()
        for name, view in self._screens.items():
            if view is widget:
                return name
        return ""

    def forget_activity(self, activity_key: str) -> None:
        """Drop the remembered screens of one activity (Start over)."""
        for memo in [k for k in self._tab_memory if k[0] == activity_key]:
            del self._tab_memory[memo]
        if self.activity_key == activity_key:
            # Its screens are still mounted; do not let the next visit record
            # which one was showing and bring the old place back.
            self.activity_key = ""
            self.step_key = ""

    def show_named_screen(self, name: str) -> bool:
        """Select a screen that this step shows, by name. False if it is not here."""
        view = self._screens.get(name)
        if view is None or self.content.indexOf(view) < 0:
            return False
        self.content.setCurrentWidget(view)
        return True

    def location(self) -> tuple:
        """(activity title, "3 Code") for the breadcrumb."""
        activity = activities.get(self.activity_key)
        number = activity.step_number(self.step_key)
        return activity.title, f"{number} {activity.step(self.step_key).title}"

    # -- mounting ------------------------------------------------------------
    def _mount(self, step: activities.Step) -> None:
        self.content.blockSignals(True)
        while self.content.count():
            leaving = self.content.widget(0)
            self.content.removeTab(0)
            leaving.hide()
        main = step.screens.get(activities.DESKTOP, ())
        more = step.more.get(activities.DESKTOP, ())
        seen = set()
        for name in main + more:
            widget = self._screens.get(name)
            if widget is None or id(widget) in seen:
                continue
            seen.add(id(widget))
            title = SCREEN_TITLES.get(name, name)
            self.content.addTab(widget, f"More: {title}" if name in more else title)
        self.content.blockSignals(False)
        self.content.tabBar().setVisible(self.content.count() > 1)
        for name in main[:1]:
            select = self._selectors.get(name)
            if select is not None:
                select()
