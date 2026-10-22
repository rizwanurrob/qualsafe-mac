"""
The application shell: menus, the undo stack, the status bar, the screens.

Deliberately thin. It owns the one `ProjectService` and the one `QUndoStack` and
hands both to each view; it holds no analytical state of its own. At this stage
only the Documents screen exists -- the fork is being built thesis-first, so the
coding surface is proved before the rest of the app is ported.

Preferences are stored with `QSettings` under a **whitelist** (`_PERSISTED_KEYS`),
matching the rule `core/app_settings.py` enforces for the Streamlit build:
preferences only, never anything derived from response text.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, List, Optional

#: The installation root: this file is qualsafe_qt/windows/main_window.py.
PROJECT_ROOT = Path(__file__).resolve().parents[2]

from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence, QUndoStack
from PySide6.QtWidgets import (
    QFileDialog, QInputDialog, QLabel, QMainWindow, QMessageBox, QStackedWidget,
    QTabWidget, QVBoxLayout, QWidget,
)

from qualsafe_qt.keys import native
from core.ux import activities, progress, recent
from core.ux.kind import activity_for_source_types, landing
from qualsafe_qt.widgets.activity import ActivityView, TopBar
from qualsafe_qt.widgets.home import HomeView
from qualsafe_qt.widgets.settings_general import GeneralSettings

from qualsafe_qt.services.project_service import ProjectService
from qualsafe_qt.services.tasks import run_task
from qualsafe_qt.views.analysis_view import AnalysisView
from qualsafe_qt.views.model_view import ModelView
from qualsafe_qt.views.charts_view import ChartsView
from qualsafe_qt.views.data_charts_view import DataChartsView
from qualsafe_qt.views.codebook_view import CodebookView
from qualsafe_qt.views.data_view import DataView
from qualsafe_qt.views.documents_view import DocumentsView
from qualsafe_qt.views.help_view import HelpView
from qualsafe_qt.widgets import info_tip
from qualsafe_qt.widgets.clip_player import ClipDialog
from core.ux.help import media
from qualsafe_qt.widgets.tour import TourOverlay, find_main_button, find_more_options
from core.ux.help import tours
from qualsafe_qt.views.models_view import ModelsView
from qualsafe_qt.views.pipeline_view import PipelineView
from qualsafe_qt.views.query_view import QueryView
from qualsafe_qt.views.results_view import ResultsView
from qualsafe_qt.views.search_view import SearchView

ORGANIZATION = "QualSafe"
APPLICATION = "QualSafe Desktop"


def open_settings() -> QSettings:
    """The desktop app's preferences store.

    `QSettings(ORGANIZATION, APPLICATION)` always means the native store (the
    registry on Windows) and ignores `QSettings.setDefaultFormat`, so a test
    could not redirect it: the suite was writing the installed app's real
    settings. Passing the default format explicitly is identical in the shipped
    app, where the default is native, and lets `tests/conftest.py` point every
    test at a temp folder.
    """
    return QSettings(QSettings.defaultFormat(), QSettings.Scope.UserScope,
                     ORGANIZATION, APPLICATION)

#: The only keys written to disk. Everything here is a UI preference; none of it
#: is derived from a response, a document, or a code. Matches the whitelist
#: discipline of `core.app_settings.PERSISTED_KEYS`.
_PERSISTED_KEYS = ("last_project_path", "analyst_name", "theme_mode",
                   # Paths and an activity name only (core/ux/recent.py).
                   "recent_projects",
                   # Which first-visit tours have been seen: activity names only.
                   "tours_seen",
                   "window_geometry", "window_state",
                   # Per-role model ids chosen in the Model Manager. These are
                   # Hugging Face repo names, not data -- the whitelist rule is
                   # about never persisting anything derived from a response.
                   "model_embedding", "model_sentiment", "model_zero-shot",
                   # Appearance. All preferences, none derived from data.
                   "font_pt", "category_palette", "heatmap_scheme")


class MainWindow(QMainWindow):
    """The desktop shell."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(APPLICATION)
        self.resize(1500, 940)

        self._settings = open_settings()
        self._tours_seen = tours.parse(self._settings.value("tours_seen", ""))
        self._tour = None
        #: Tests turn the tour off; nothing else does.
        self._tours_enabled = not os.environ.get("QUALSAFE_NO_TOUR")
        #: Appearance preferences, applied through one path (`_apply_appearance`).
        self._appearance = {"theme_mode": "dark", "font_pt": 10.5,
                            "category_palette": "", "heatmap_scheme": ""}
        self._service = ProjectService(self)
        self._undo = QUndoStack(self)

        # One tab per screen, mirroring the Streamlit build's numbered nav. Both
        # share the one ProjectService and the one undo stack, so a code created
        # while coding appears in the codebook immediately and Ctrl+Z means the
        # same thing on either screen.
        self.documents = DocumentsView(self._service, self._undo, self)
        self.codebook = CodebookView(self._service, self._undo, self)
        self.analysis = AnalysisView(self._service, self._undo, self)
        self.modelling = ModelView(self._service, self._undo, self)
        self.charts = ChartsView(self._service, self._undo, self)
        self.data_charts = DataChartsView(self._service, self._undo, self)
        self.search = SearchView(self._service, self._undo, self)
        self.query = QueryView(self._service, self._undo, self)
        self.pipeline = PipelineView(self._service, self._undo, self)
        self.data = DataView(self._service, self._undo, self)
        self.results = ResultsView(self._service, self._undo, self)
        self.models = ModelsView(self._service, self._undo, self)
        self.help = HelpView(self)

        # Home, then one activity container whose steps mount the views above
        # (what each step shows is data: `core.ux.activities`), then Settings and
        # Help. The views are built once; a step mounts the ones it names.
        self.pipeline.tabs.tabBar().hide()     # the step rail replaces its tab row
        self.home = HomeView()
        self.activity = ActivityView(
            screens={
                "Documents": self.documents, "Codebook": self.codebook,
                "Analysis": self.analysis, "Charts": self.charts,
                "Data Charts": self.data_charts, "Modelling": self.modelling,
                "Search": self.search, "Query": self.query, "Reports": self.results,
                "Survey/Data": self.pipeline, "Survey/Themes": self.pipeline,
                "Survey/Run": self.pipeline,
            },
            selectors={
                "Survey/Data": lambda: self.pipeline.tabs.setCurrentIndex(0),
                "Survey/Themes": lambda: self.pipeline.tabs.setCurrentIndex(1),
                "Survey/Run": lambda: self.pipeline.tabs.setCurrentIndex(2),
            })
        # Settings holds the two screens that are not an activity. "Models" is the
        # model *manager* (it downloads language models); "Modelling" is the
        # regression screen inside an activity. They are never in one place.
        self.general = GeneralSettings()
        self.settings_tabs = QTabWidget()
        self.settings_tabs.addTab(self.general, "General")
        self.settings_tabs.addTab(self.models, "Models")
        self.settings_tabs.addTab(self.data, "Project and backups")

        self.pages = QStackedWidget()
        for page in (self.home, self.activity, self.settings_tabs, self.help):
            self.pages.addWidget(page)
        self.top_bar = TopBar()
        shell = QWidget()
        shell_layout = QVBoxLayout(shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)
        shell_layout.addWidget(self.top_bar)
        shell_layout.addWidget(self.pages, 1)
        self.setCentralWidget(shell)
        self.top_bar.home_requested.connect(self.go_home)
        self.top_bar.settings_requested.connect(self.open_settings_page)
        self.top_bar.help_requested.connect(self.open_help)
        self.general.analyst_name_changed.connect(self._save_analyst_name)
        self.general.theme_changed.connect(self._apply_theme)
        self.general.appearance_requested.connect(self._show_appearance)
        self.home.activity_requested.connect(self.open_activity)
        self.home.sample_requested.connect(self._open_sample_project)
        self.home.guide_requested.connect(self.open_help)
        self.home.open_requested.connect(self._open_project)
        self.home.recent_requested.connect(self._open_recent)
        self.home.continue_requested.connect(self._continue_activity)
        self.home.find_requested.connect(self._find_missing_file)
        self.home.start_over_requested.connect(self._start_over)
        #: Set when a person asks to open something; the next project that opens
        #: is then shown in its own activity and step. Reopening the last project
        #: at launch does not set it: the app starts on Home.
        self._land_after_open = False
        self._recent: list = []
        self.activity.step_changed.connect(lambda *_: self._update_location())
        self.activity.step_changed.connect(self._on_step_changed)
        self.activity.step_help_requested.connect(self.open_help_for_step)
        self.activity.watch_requested.connect(self.open_clips_for_step)
        info_tip.set_article_opener(self.open_help_for_article)
        self.help.tour_requested.connect(self.retake_tour)
        #: The step each activity was left on, this session (see `open_activity`).
        self._last_step: Dict[str, str] = {}
        self._saved: Dict[str, str] = {}
        #: Saved places are written when you leave an activity, when the window
        #: closes, and every 30 seconds while one is open.
        self._progress_timer = QTimer(self)
        self._progress_timer.setInterval(30_000)
        self._progress_timer.timeout.connect(self.save_progress)
        self._progress_timer.start()
        self.go_home()

        self._offline_label = QLabel()
        self.statusBar().addPermanentWidget(self._offline_label)
        self.documents.status.connect(self._show_status)
        # The welcome panel reuses File > Open and File > New rather than
        # duplicating them, so there is one implementation of each.
        self.documents.welcome.open_requested.connect(self._open_project)
        self.documents.welcome.create_requested.connect(self._new_project)
        self.documents.welcome.sample_requested.connect(self._open_sample_project)
        self.documents.welcome.guide_requested.connect(self.open_help)
        self.codebook.status.connect(self._show_status)
        self.data_charts.status.connect(self._show_status)
        self.data_charts.step_requested.connect(lambda key: self.activity.show_step("charts", key))
        self.documents.step_requested.connect(lambda key: self.activity.show_step("interviews", key))
        self.analysis.status.connect(self._show_status)
        self.analysis.open_in_reader.connect(self._open_in_reader)
        self.search.status.connect(self._show_status)
        # A search hit is a place, not just a line of text: send it to the
        # reader with the match selected, ready to code by hand. This is the
        # jump Streamlit could never make -- SearchHit has always carried exact
        # offsets, but there was nowhere to send them.
        self.search.open_in_reader.connect(self._open_in_reader)
        self.query.status.connect(self._show_status)
        self.query.open_in_reader.connect(self._open_in_reader)
        self.pipeline.status.connect(self._show_status)
        # A pipeline run writes its own .qnw on a worker thread; opening it here
        # is what makes the run's coding visible on every other screen.
        self.pipeline.project_written.connect(self._open_written_project)
        self.data.status.connect(self._show_status)
        self.data.analyst_name_changed.connect(self._save_analyst_name)
        self.results.status.connect(self._show_status)
        self.models.status.connect(self._show_status)
        self.models.model_chosen.connect(self._on_model_chosen)
        self.help.status.connect(self._show_status)
        # The pipeline codes with whatever models the Model Manager selected,
        # not always the defaults -- otherwise choosing a model would change
        # nothing about the analysis.
        self.pipeline.model_provider = self.models.chosen_models
        self._service.message.connect(self._show_status)
        self._service.project_changed.connect(self._on_project_changed)

        self._build_menus()
        self._restore_preferences()
        self._update_offline_indicator()
        self._refresh_home_progress()

    # -- menus ---------------------------------------------------------------
    def _build_menus(self) -> None:
        file_menu = self.menuBar().addMenu("&File")

        open_action = QAction("&Open project…", self)
        open_action.setShortcut(QKeySequence.StandardKey.Open)
        open_action.triggered.connect(self._open_project)
        file_menu.addAction(open_action)

        new_action = QAction("&New project…", self)
        new_action.setShortcut(QKeySequence.StandardKey.New)
        new_action.triggered.connect(self._new_project)
        file_menu.addAction(new_action)

        file_menu.addSeparator()
        close_action = QAction("&Close project", self)
        close_action.triggered.connect(self._service.close)
        file_menu.addAction(close_action)

        file_menu.addSeparator()
        quit_action = QAction("E&xit", self)
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        # macOS moves this into the application menu as "Quit QualSafe Desktop"
        # only when told what it is; matching on the word "Exit" is a guess.
        # Ignored everywhere else.
        quit_action.setMenuRole(QAction.MenuRole.QuitRole)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        edit_menu = self.menuBar().addMenu("&Edit")
        undo_action = self._undo.createUndoAction(self, "&Undo")
        undo_action.setShortcut(QKeySequence.StandardKey.Undo)
        redo_action = self._undo.createRedoAction(self, "&Redo")
        redo_action.setShortcut(QKeySequence.StandardKey.Redo)
        edit_menu.addAction(undo_action)
        edit_menu.addAction(redo_action)

        edit_menu.addSeparator()
        name_action = QAction("Set your &analyst name…", self)
        name_action.triggered.connect(self._set_analyst_name)
        name_action.setStatusTip(
            "Recorded on your codings so agreement analysis can attribute them.")
        edit_menu.addAction(name_action)

        view_menu = self.menuBar().addMenu("&View")
        home_action = QAction("Go to &Home", self)
        home_action.setShortcut("Ctrl+H")
        home_action.triggered.connect(self.go_home)
        view_menu.addAction(home_action)
        view_menu.addSeparator()
        self._theme_action = QAction("Use &light skin", self)
        self._theme_action.setCheckable(True)
        self._theme_action.toggled.connect(self._on_theme_toggled)
        view_menu.addAction(self._theme_action)
        view_menu.addSeparator()
        appearance_action = QAction("&Appearance…", self)
        appearance_action.triggered.connect(self._show_appearance)
        appearance_action.setStatusTip(
            "Theme, text size, code colours, and the heatmap ramp.")
        view_menu.addAction(appearance_action)

        help_menu = self.menuBar().addMenu("&Help")
        guide_action = QAction("&User guide", self)
        guide_action.setShortcut(QKeySequence.StandardKey.HelpContents)
        guide_action.triggered.connect(self.open_help)
        help_menu.addAction(guide_action)
        shortcuts_action = QAction("&Coding shortcuts", self)
        shortcuts_action.triggered.connect(self._show_shortcuts)
        help_menu.addAction(shortcuts_action)
        about_action = QAction("&About", self)
        about_action.triggered.connect(self._show_about)
        about_action.setMenuRole(QAction.MenuRole.AboutRole)
        help_menu.addAction(about_action)

    # -- where you are -------------------------------------------------------
    def go_home(self) -> None:
        self.save_progress()
        self._refresh_home_progress()
        self.pages.setCurrentWidget(self.home)
        self.top_bar.set_location()
        self.home.start_buttons["surveys"].setFocus()

    def open_activity(self, key: str, step: Optional[str] = None) -> None:
        """Show an activity at `step`: where it was left this session, else its
        first step. Switching activity and coming back loses nothing."""
        if self.pages.currentWidget() is self.activity and self.activity.activity_key != key:
            self.save_progress()
        if step is None:
            step = self._last_step.get(key) or activities.get(key).steps[0].key
        self.activity.show_step(key, step)
        self.pages.setCurrentWidget(self.activity)
        self._update_location()
        if self._tours_enabled and tours.is_due(self._tours_seen, key):
            QTimer.singleShot(0, lambda: self.start_tour(key))

    # -- the first-visit tour (core/ux/help/tours.py) --------------------------
    def start_tour(self, activity_key: str, *, force: bool = False) -> None:
        """Show the tour of an activity: the first time it is opened, or on request."""
        if getattr(self, "_tour", None) is not None:
            return
        if not force and not tours.is_due(self._tours_seen, activity_key):
            return
        if self.pages.currentWidget() is not self.activity or self.activity.activity_key != activity_key:
            return                                       # the person already went elsewhere
        finders = {"rail": lambda: self.activity.rail,
                   "main": lambda: find_main_button(self.activity),
                   "more": lambda: find_more_options(self.activity),
                   "help": lambda: self.activity.step_help}
        self._tour = TourOverlay(self, activity_key, finders)
        self._tour.finished.connect(self._tour_finished)

    def _tour_finished(self, activity_key: str, _completed: bool) -> None:
        self._tour = None
        self._tours_seen = tours.mark_seen(self._tours_seen, activity_key)
        self._settings.setValue("tours_seen", tours.dump(self._tours_seen))

    def retake_tour(self, activity_key: str) -> None:
        """From Help: go to the activity and show its tour again."""
        self.open_activity(activity_key)
        QTimer.singleShot(0, lambda: self.start_tour(activity_key, force=True))

    def open_settings_page(self) -> None:
        self.save_progress()
        self.pages.setCurrentWidget(self.settings_tabs)
        self.top_bar.set_location("Settings")

    def open_help(self) -> None:
        self.save_progress()
        self.pages.setCurrentWidget(self.help)
        self.top_bar.set_location("Help")

    def open_help_for_step(self, activity_key: str, step_key: str) -> None:
        """The article for the step you are on; the general guide if it has none."""
        self.open_help()
        self.help.show_step(activity_key, step_key)

    def open_clips_for_step(self, activity_key: str, step_key: str) -> None:
        """The short clips for a step, in a small window (paused until the person presses Play)."""
        ids = [c.clip_id for c in media.for_article(f"{activity_key}-{step_key}")]
        if not ids:
            return
        dialog = ClipDialog(ids, self)
        self._clip_dialog = dialog
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.show()

    def open_help_for_article(self, article: str) -> None:
        """From a tip's More link: an article id such as `surveys-code`."""
        activity_key, _, step_key = article.partition("-")
        self.open_help_for_step(activity_key, step_key)

    # -- saved place per activity (core/ux/progress.py) -----------------------
    def _on_step_changed(self, activity_key: str, step_key: str) -> None:
        self._last_step[activity_key] = step_key
        if activity_key == "charts":
            self.data_charts.set_step(step_key)
        elif activity_key == "interviews":
            self.documents.set_step(step_key)
        self.save_progress(activity_key)     # the page is not switched yet on first entry

    def _progress_state(self, key: str) -> dict:
        """The saved shape of one activity: paths, choices and labels, never text."""
        if key == "surveys":
            state = self.pipeline.progress_state()
        elif key == "charts":
            state = self.data_charts.progress_state()
        else:
            state = self.documents.progress_state()
        if key != "charts" and self._service.is_open and self._service.path:
            state["project_path"] = str(self._service.path)
        if (key == self.activity.activity_key and self.activity.step_key == "explore"
                and self.pages.currentWidget() is self.activity):
            state["explore_tab"] = self.activity.current_screen()
        return state

    def save_progress(self, activity_key: Optional[str] = None) -> None:
        """Write where the person is in an activity (the one showing, by default).

        A failure to write never gets in the way of working. Nothing is written
        when nothing has changed since the last write."""
        key = activity_key or (self.activity.activity_key
                               if self.pages.currentWidget() is self.activity else "")
        step = self._last_step.get(key, "")
        if not key or not step:
            return
        try:
            state = self._progress_state(key)
            fingerprint = json.dumps([step, state], sort_keys=True, default=str)
            if self._saved.get(key) == fingerprint:
                return
            progress.save(key, step, state)
            self._saved[key] = fingerprint
        except Exception:  # noqa: BLE001 - saving a place must never block the work
            return

    def _refresh_home_progress(self) -> None:
        """Tell each Home card where its activity was left (or nothing)."""
        try:
            self.home.set_progress({a.key: progress.summary(a.key)
                                    for a in activities.ACTIVITIES})
        except Exception:  # noqa: BLE001 - Home must always open
            self.home.set_progress({})

    def _continue_activity(self, key: str) -> None:
        """Pick an activity up where an earlier session left it."""
        missing = self.restore_progress(key)
        if missing:
            self._show_status("Could not find: " + ", ".join(Path(p).name for p in missing))

    #: What *Start over* forgets, in the words the confirmation uses.
    _FORGETS = {
        "surveys": "the data file, your column choices and your theme list",
        "charts": "the spreadsheet and your chart choices",
        "interviews": "which document you were on and how far you had read",
    }

    def _start_over_box(self, key: str):
        """The question put to the person: (dialog, its Start over button)."""
        title = activities.get(key).title
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(f"Start over in {title}?")
        box.setText(f"Start over in {title}?")
        box.setInformativeText(
            f"This forgets {self._FORGETS[key]}.\n\n"
            "Your files and projects are not changed or deleted, and the other "
            "activities keep their places.")
        start = box.addButton("Start over", QMessageBox.ButtonRole.DestructiveRole)
        keep = box.addButton("Keep my place", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(keep)
        return box, start

    def _confirm_start_over(self, key: str) -> bool:
        box, start = self._start_over_box(key)
        box.exec()
        return box.clickedButton() is start

    def _start_over(self, key: str) -> None:
        """Forget where one activity was left, in the file and on screen.

        Only this activity: the others keep their places, and nothing on disk is
        deleted. The open project stays open, because Surveys and Interviews share it."""
        if not self._confirm_start_over(key):
            return
        progress.clear(key)
        self._saved.pop(key, None)
        self._last_step.pop(key, None)
        self.activity.forget_activity(key)
        {"surveys": self.pipeline, "charts": self.data_charts,
         "interviews": self.documents}[key].reset_session()
        self._refresh_home_progress()
        self._show_status(f"{activities.get(key).title}: started over. "
                          "Your files and projects were not changed.")

    def _find_missing_file(self, key: str) -> None:
        """A saved file has moved: ask where it is now, then carry on."""
        info = progress.summary(key)
        for old in (info.missing if info else ()):
            title = f"Find {Path(old).name}"
            suffix = Path(old).suffix
            pattern = f"*{suffix};;All files (*)" if suffix else "All files (*)"
            chosen, _filter = QFileDialog.getOpenFileName(self, title, "", pattern)
            if not chosen:
                self._refresh_home_progress()
                return                       # the person gave up; nothing changes
            progress.replace_path(key, old, chosen)
        self._refresh_home_progress()
        self._continue_activity(key)

    def restore_progress(self, key: str) -> List[str]:
        """Put an activity back as it was saved, from an earlier session.

        Reloading a survey file is a load, so its privacy gate is asked again.
        Returns the saved file paths that no longer exist (empty when all is well).
        """
        entry = progress.load(key)
        if entry is None:
            return []
        state = entry["state"]
        missing = list(progress.missing_paths(key))
        project = str(state.get("project_path", ""))
        if project and project not in missing and (
                not self._service.is_open or str(self._service.path) != project):
            self._land_after_open = False
            try:
                self._service.open(Path(project))
            except Exception:  # noqa: BLE001 - report it as missing, do not crash
                missing.append(project)
        view = {"surveys": self.pipeline, "charts": self.data_charts,
                "interviews": self.documents}[key]
        view.restore_progress(state)
        self._last_step[key] = entry["step"]
        self.open_activity(key, entry["step"])
        if state.get("explore_tab"):
            self.activity.show_named_screen(str(state["explore_tab"]))
        return missing

    def _update_location(self) -> None:
        if self.pages.currentWidget() is self.activity:
            self.top_bar.set_location(*self.activity.location(),
                                      activity=self.activity.activity_key)

    # -- project -------------------------------------------------------------
    def _open_project(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(
            self, "Open a QualSafe project", "", "QualSafe project (*.qnw);;All files (*)")
        if not path:
            return
        self._land_after_open = True
        try:
            self._service.open(Path(path))
        except Exception as exc:  # noqa: BLE001 - report, never crash the shell
            self._land_after_open = False
            QMessageBox.critical(self, "Could not open project", str(exc))

    def _new_project(self) -> None:
        path, _filter = QFileDialog.getSaveFileName(
            self, "Create a QualSafe project", "project.qnw",
            "QualSafe project (*.qnw)")
        if not path:
            return
        self._land_after_open = True
        try:
            self._service.create(Path(path))
        except Exception as exc:  # noqa: BLE001
            self._land_after_open = False
            QMessageBox.critical(self, "Could not create project", str(exc))

    def _open_sample_project(self) -> None:
        """Build the guided sample if it is not there, then open it.

        Built on demand rather than shipped as a `.qnw`, because a store carries
        a schema version and a stale one in the installer would need migrating
        on first run to prove nothing. The CSV it is built from does ship.

        Runs on a worker: it writes a few dozen sources and codings, which is
        fast but not instant, and a window that freezes on the first button a
        new user presses is indistinguishable from one that crashed.
        """
        from core.sample_project import build_sample_project, default_sample_path

        output_root = Path.home() / ".qualsafe" / "samples"
        target = default_sample_path(output_root)
        if target.exists():
            self._open_written_project(str(target))
            return

        csv_path = PROJECT_ROOT / "data" / "sample_survey_education.csv"
        if not csv_path.exists():
            QMessageBox.warning(
                self, "Sample data is missing",
                "The sample survey this project is built from is not in the "
                f"installation. It should be at {csv_path}. Open or create a "
                "project instead.")
            return

        self._show_status("Building the sample project…")
        target.parent.mkdir(parents=True, exist_ok=True)
        run_task(
            build_sample_project, csv_path, target,
            on_finished=lambda written: self._open_written_project(str(written)),
            on_failed=lambda message, _tb: QMessageBox.critical(
                self, "Could not build the sample", message),
        )

    def _open_recent(self, path: str, _activity: str = "") -> None:
        self._land_after_open = True
        try:
            self._service.open(Path(path))
        except Exception as exc:  # noqa: BLE001 - report, never crash the shell
            self._land_after_open = False
            QMessageBox.critical(self, "Could not open project", str(exc))

    def _show_landing(self) -> None:
        """Show the open project where it belongs (UX-5): a survey project in
        Surveys at the step its progress calls for, a document project in
        Interviews, never the empty document list."""
        try:
            project = self._service.project
            where = landing(project.source_types(), len(project.get_codebook()),
                            sum(project.code_frequency().values()))
        except Exception:  # noqa: BLE001 - landing is a convenience; stay put
            return
        self.open_activity(*where)

    def _remember_recent(self, path: str) -> None:
        """Add the open project to the Home list: its path and activity only."""
        try:
            kind = activity_for_source_types(self._service.project.source_types())
        except Exception:  # noqa: BLE001 - a recent list is a convenience
            return
        self._recent = recent.add(self._recent, path, kind)
        self._settings.setValue("recent_projects", recent.dump(self._recent))
        self.home.set_recent(self._recent)

    def _on_project_changed(self, path: str) -> None:
        self._undo.clear()      # undo history belongs to one open project
        if path:
            self.setWindowTitle(f"{Path(path).name} — {APPLICATION}")
            self._settings.setValue("last_project_path", path)
            self._remember_recent(path)
            self._show_status(f"Opened {path}")
            if self._land_after_open:
                self._land_after_open = False
                self._show_landing()
        else:
            self.setWindowTitle(APPLICATION)

    def _set_analyst_name(self) -> None:
        name, ok = QInputDialog.getText(
            self, "Analyst name", "Your name (recorded on your codings):",
            text=self._service.analyst_name)
        if ok:
            self._save_analyst_name(name)

    def _save_analyst_name(self, name: str) -> None:
        self._service.set_analyst_name(name)
        self._settings.setValue("analyst_name", name.strip())
        self.general.set_analyst_name(name.strip())
        if self.data.analyst_name.text().strip() != name.strip():
            self.data.analyst_name.setText(name.strip())
        self._show_status("Name saved." if name.strip() else "Name cleared.")

    # -- appearance ----------------------------------------------------------
    def _on_theme_toggled(self, light: bool) -> None:
        self._appearance["theme_mode"] = "light" if light else "dark"
        self._apply_appearance()

    def _show_appearance(self) -> None:
        """Appearance settings, previewed live and reversible on Cancel."""
        from qualsafe_qt.windows.appearance_dialog import AppearanceDialog

        dialog = AppearanceDialog(dict(self._appearance), self)
        dialog.changed.connect(self._preview_appearance)
        dialog.exec()
        self._persist_appearance()

    def _preview_appearance(self, settings: dict) -> None:
        self._appearance.update(settings)
        self._apply_appearance()

    def _persist_appearance(self) -> None:
        for key, value in self._appearance.items():
            self._settings.setValue(key, value)

    def _apply_appearance(self) -> None:
        """Push the current appearance settings through the whole app.

        One path for every source of change -- the View menu toggle, the
        Appearance dialog, and start-up restore all land here, so a skin can
        never be half-applied.
        """
        from PySide6.QtWidgets import QApplication

        from qualsafe_qt.theme import apply_theme

        mode = str(self._appearance.get("theme_mode", "dark"))
        palette = str(self._appearance.get("category_palette", ""))
        scheme = str(self._appearance.get("heatmap_scheme", ""))
        font_pt = float(self._appearance.get("font_pt", 10.5))

        app = QApplication.instance()
        if app is not None:
            apply_theme(app, mode, font_pt=font_pt)

        self._theme_action.blockSignals(True)
        self._theme_action.setChecked(mode == "light")
        self._theme_action.blockSignals(False)

        self.general.set_theme_mode(mode)
        self.home.set_theme_mode(mode)
        self.activity.set_theme_mode(mode)
        self.top_bar.set_theme_mode(mode)
        self.documents.set_theme_mode(mode, palette)
        self.codebook.set_theme_mode(mode, palette)
        self.analysis.set_theme_mode(mode, palette, scheme)
        self.search.set_theme_mode(mode, palette)
        self.charts.set_theme_mode(mode, palette)
        self._update_offline_indicator()

    def _apply_theme(self, mode: str) -> None:
        """Set just the skin. Kept because it is the simplest entry point."""
        self._appearance["theme_mode"] = mode
        self._apply_appearance()
        self._persist_appearance()

    def _on_model_chosen(self, role: str, model_id: str) -> None:
        self._settings.setValue(f"model_{role}", model_id)

    def _restore_model_choices(self) -> None:
        from core.model_manager import DEFAULT_MODELS

        self.models.set_chosen_models({
            role: str(self._settings.value(f"model_{role}", default) or default)
            for role, default in DEFAULT_MODELS.items()
        })

    def _open_written_project(self, path: str) -> None:
        """Open the store a finished run produced.

        The worker opened its own connection to write it -- a sqlite3 connection
        belongs to the thread that made it -- so the GUI has to connect afresh
        rather than reuse anything the run left behind.
        """
        self._land_after_open = True
        try:
            self._service.open(Path(path))
        except Exception as exc:  # noqa: BLE001 - report, never crash the shell
            self._land_after_open = False
            self._show_status(f"Run finished but the project could not be opened: {exc}")

    def _open_in_reader(self, source_id: str, char_start: int, char_end: int) -> None:
        """Switch to the reader and select a span -- from a search hit or a query."""
        self.open_activity("interviews", "code")
        self.activity.content.setCurrentWidget(self.documents)
        if self.documents.select_source_span(source_id, char_start, char_end):
            self._show_status(
                f"Opened characters {char_start}-{char_end}. Pick a code and "
                "press Enter, or 1-9.")
        else:
            self._show_status("That document is no longer in the project.")

    # -- status --------------------------------------------------------------
    def _show_status(self, message: str) -> None:
        self.statusBar().showMessage(native(message), 8000)

    def _update_offline_indicator(self) -> None:
        """Show whether the offline guarantee is actually armed, not assumed.

        `core.offline.is_offline_enforced` reads the real environment, so this
        reports the state of the process rather than the intention of the code.
        """
        from core.offline import is_offline_enforced

        self.general.set_offline(is_offline_enforced(), str(self._appearance.get("theme_mode", "")))
        if is_offline_enforced():
            self._offline_label.setText("  Offline mode: on  ")
            self._offline_label.setToolTip(
                "Model files are only read from this computer. Analysis "
                "cannot reach the network.")
            self._offline_label.setStyleSheet("color: #4FAF7C;")
        else:
            self._offline_label.setText("  Offline mode: OFF  ")
            self._offline_label.setToolTip(
                "The offline switches are not both on. Model "
                "downloads are meant to be a separate, explicit step.")
            self._offline_label.setStyleSheet("color: #E0A040; font-weight: bold;")

    # -- help ----------------------------------------------------------------
    def _show_shortcuts(self) -> None:
        QMessageBox.information(
            self, "Coding shortcuts",
            native("<b>In the document reader</b><br>"
            "<table cellpadding=4>"
            "<tr><td><b>Drag</b></td><td>select the passage to code</td></tr>"
            "<tr><td><b>1</b>–<b>9</b></td><td>apply that code from the list</td></tr>"
            "<tr><td><b>Enter</b></td><td>apply every code ticked in the list</td></tr>"
            "<tr><td><b>Ctrl+E</b></td><td>grow the selection to whole sentences</td></tr>"
            "<tr><td><b>Ctrl+Z</b></td><td>undo the last coding</td></tr>"
            "<tr><td><b>Ctrl+Y</b></td><td>redo</td></tr>"
            "</table>"))

    def _show_about(self) -> None:
        from qualsafe_qt.version import store_format, version_line

        QMessageBox.about(
            self, "About QualSafe Desktop",
            f"<b>{APPLICATION}</b><br>"
            f"Version {version_line()}<br><br>"
            "A local-first qualitative analysis workbench: read and code "
            "documents, build a codebook, and analyse survey text.<br><br>"
            "A project is a single <code>.qnw</code> file you can copy or "
            f"share. This build reads and writes <b>project format "
            f"v{store_format()}</b>; a project saved by a newer version will "
            "not open here.<br><br>"
            "<b>All analysis runs on this machine.</b> Your text is never "
            "uploaded.<br><br>"
            "Press <b>F1</b> for the user guide.")

    # -- preferences ---------------------------------------------------------
    def _restore_preferences(self) -> None:
        geometry = self._settings.value("window_geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)

        name = str(self._settings.value("analyst_name", "") or "")
        self._service.set_analyst_name(name)
        self.general.set_analyst_name(name)

        from qualsafe_qt.theme import DEFAULT_CATEGORY_PALETTE
        from core.theme import DEFAULT_HEATMAP_SCHEME

        self._appearance = {
            "theme_mode": str(self._settings.value("theme_mode", "dark") or "dark"),
            "font_pt": float(self._settings.value("font_pt", 10.5) or 10.5),
            "category_palette": str(self._settings.value(
                "category_palette", DEFAULT_CATEGORY_PALETTE) or DEFAULT_CATEGORY_PALETTE),
            "heatmap_scheme": str(self._settings.value(
                "heatmap_scheme", DEFAULT_HEATMAP_SCHEME) or DEFAULT_HEATMAP_SCHEME),
        }
        self._apply_appearance()

        self._restore_model_choices()
        self._recent = recent.parse(self._settings.value("recent_projects", ""))
        self.home.set_recent(self._recent)

        last = str(self._settings.value("last_project_path", "") or "")
        if last and Path(last).exists():
            try:
                self._service.open(Path(last))
            except Exception:  # noqa: BLE001 - a stale path must not block startup
                self._show_status(f"Could not reopen {last}.")

    def closeEvent(self, event) -> None:  # noqa: D102 - Qt override
        self.save_progress()
        self._progress_timer.stop()
        self._settings.setValue("window_geometry", self.saveGeometry())
        self._service.close()
        super().closeEvent(event)
