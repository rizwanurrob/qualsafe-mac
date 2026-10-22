"""
Model Manager and Help.

The Model Manager is the screen without which a fresh install cannot run the
pipeline at all, so what is tested here is mostly refusal behaviour: it must not
pretend a download is possible when the transformer stack is absent, and it must
never lift offline mode to fetch something.

Help is tested lightly but deliberately: the guide is the tool's own answer to
"how do you know?", and a few claims in it are load-bearing enough that they
should fail a test if they quietly disappear.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]

pytest.importorskip("PySide6", reason="Qt front end not installed")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QThreadPool  # noqa: E402
from PySide6.QtGui import QUndoStack  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core.model_manager import DEFAULT_MODELS, ROLES  # noqa: E402
from qualsafe_qt.services.project_service import ProjectService  # noqa: E402
from qualsafe_qt.views.help_view import HELP_SECTIONS, HelpView, full_guide  # noqa: E402
from qualsafe_qt.views.models_view import (  # noqa: E402
    ENGINE_PACKAGES, ModelsView, engine_installed, missing_engine_packages,
)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def view(qapp):
    service = ProjectService()
    widget = ModelsView(service, QUndoStack())
    yield widget
    service.close()


def _drain(app, rounds: int = 60) -> None:
    for _ in range(rounds):
        app.processEvents()
        if QThreadPool.globalInstance().waitForDone(30):
            break
    for _ in range(10):
        app.processEvents()


# -- engine detection --------------------------------------------------------
_ENGINE_IMPORT_PROBE = """
import sys
from qualsafe_qt.views.models_view import (
    ENGINE_PACKAGES, engine_installed, missing_engine_packages,
)

missing_engine_packages()
engine_installed()

leaked = [name for name in ENGINE_PACKAGES if name in sys.modules]
if leaked:
    raise SystemExit("engine detection imported: " + ", ".join(leaked))
print("clean")
"""


def test_engine_detection_never_imports_the_stack():
    """Importing torch to discover whether torch exists costs seconds and
    hundreds of megabytes — the check is by spec.

    Run in a subprocess. The obvious version asserts on `sys.modules` in the
    current process, which silently depends on nothing *else* in the whole
    session having imported torch. That held only while the dev venv was
    torch-free; once the engine is installed, an unrelated test pulls torch in
    and this one fails without anything being wrong. A fresh interpreter tests
    the actual claim -- that *these two calls* do not import the stack --
    whatever else has run.
    """
    result = subprocess.run(
        [sys.executable, "-c", _ENGINE_IMPORT_PROBE],
        cwd=PROJECT_ROOT, capture_output=True, text=True,
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_the_screen_says_which_half_is_missing(view):
    """A model that will not download because the ML stack is absent is a very
    different problem from a network failure, and the screen must not conflate
    them."""
    text = view.engine_label.text()
    if missing_engine_packages():
        assert "analysis engine is not installed" in text
        for name in missing_engine_packages():
            assert name in text
        # And it says what still works, so the message is not just a wall.
        assert "coding" in text and "pipeline" in text
    else:
        assert "analysis engine is installed" in text


def test_downloading_without_the_engine_is_refused_with_an_explanation(
        view, monkeypatch):
    import qualsafe_qt.views.models_view as module

    if not missing_engine_packages():
        pytest.skip("this environment has the transformer stack installed")

    shown = []
    monkeypatch.setattr(module.QMessageBox, "information",
                        staticmethod(lambda _p, _t, msg, *a, **k: shown.append(msg)))
    started = []
    monkeypatch.setattr(module, "run_task",
                        lambda *a, **k: started.append(a))

    view._download("embedding")

    assert shown and "analysis engine" in shown[0]
    assert not started, "no download should be attempted"


# -- role selection ----------------------------------------------------------
def test_every_role_has_a_row_and_a_default(view):
    for role in ROLES:
        assert role in view._role_edits
        assert view._role_edits[role].text() == DEFAULT_MODELS[role]


def test_choosing_a_cached_model_announces_it_for_persistence(view):
    chosen = []
    view.model_chosen.connect(lambda role, model: chosen.append((role, model)))

    view._role_edits["embedding"].setText("some-org/some-embedder")
    view._use_cached("embedding")

    assert chosen == [("embedding", "some-org/some-embedder")]
    assert view.chosen_models()["embedding"] == "some-org/some-embedder"


def test_resetting_a_role_restores_the_default(view):
    view._role_edits["zero-shot"].setText("nonsense/model")
    view._use_cached("zero-shot")
    assert view.chosen_models()["zero-shot"] == "nonsense/model"

    view._reset("zero-shot")
    assert view.chosen_models()["zero-shot"] == DEFAULT_MODELS["zero-shot"]
    assert view._role_edits["zero-shot"].text() == DEFAULT_MODELS["zero-shot"]


def test_set_chosen_models_loads_persisted_choices(view):
    view.set_chosen_models({"embedding": "org/emb", "sentiment": "",
                            "zero-shot": None})
    assert view.chosen_models()["embedding"] == "org/emb"
    # Blank or missing entries fall back rather than blanking the role.
    assert view.chosen_models()["sentiment"] == DEFAULT_MODELS["sentiment"]
    assert view.chosen_models()["zero-shot"] == DEFAULT_MODELS["zero-shot"]


def test_the_cache_table_reports_status_for_every_chosen_model(view):
    frame = view.cache_model.frame
    assert set(frame.columns) == {"model", "status", "size", "detail"}
    assert set(frame["model"]) == set(view.chosen_models().values())
    assert set(frame["status"]) <= {"cached", "MISSING", "unknown"}


def test_missing_models_lists_what_blocks_a_run(view):
    missing = view.missing_models()
    assert isinstance(missing, list)
    assert set(missing) <= set(view.chosen_models().values())


# -- downloads stay isolated -------------------------------------------------
def test_a_download_never_touches_this_process_offline_flags(view, qapp, monkeypatch):
    """Invariant #2. The subprocess is the guarantee; the worker thread is only
    so the window stays responsive. Neither may change this process's flags."""
    import qualsafe_qt.views.models_view as module
    from core.offline import OFFLINE_VARS, local_mode_status

    before = local_mode_status()
    monkeypatch.setattr(module, "missing_engine_packages", lambda: [])
    monkeypatch.setattr(
        module, "_download_model",
        lambda model_id, role: {"ok": True, "model": model_id, "role": role,
                                "message": "Downloaded and ready."})

    view._role_edits["embedding"].setText("org/emb")
    view._download("embedding")
    _drain(qapp)

    assert local_mode_status() == before
    for var in OFFLINE_VARS:
        assert os.environ.get(var) == before[var]
    assert view.chosen_models()["embedding"] == "org/emb"


def test_a_failed_download_is_reported_and_changes_nothing(view, qapp, monkeypatch):
    import qualsafe_qt.views.models_view as module

    warned = []
    monkeypatch.setattr(module.QMessageBox, "warning",
                        staticmethod(lambda *a, **k: warned.append(a)))
    monkeypatch.setattr(module, "missing_engine_packages", lambda: [])
    monkeypatch.setattr(
        module, "_download_model",
        lambda model_id, role: {"ok": False, "model": model_id, "role": role,
                                "message": "Download failed: no route to host"})

    before = view.chosen_models()["sentiment"]
    view._role_edits["sentiment"].setText("org/never-arrives")
    view._download("sentiment")
    _drain(qapp)

    assert warned
    assert view.chosen_models()["sentiment"] == before, \
        "a failed download must not change the selected model"


def test_buttons_are_disabled_while_a_download_runs(view, qapp, monkeypatch):
    import qualsafe_qt.views.models_view as module

    monkeypatch.setattr(module, "missing_engine_packages", lambda: [])
    monkeypatch.setattr(module, "run_task", lambda *a, **k: None)

    view._download("embedding")
    assert all(not b.isEnabled() for b in view._role_buttons["embedding"])

    view._on_download_done()
    assert all(b.isEnabled() for b in view._role_buttons["embedding"])


# -- the chosen model actually reaches the pipeline --------------------------
def test_the_pipeline_codes_with_the_chosen_model_not_the_default(qapp, monkeypatch):
    """A model setting that changes nothing about the run would be worse than
    no setting at all."""
    from qualsafe_qt.views.pipeline_view import PipelineView

    service = ProjectService()
    try:
        models = ModelsView(service, QUndoStack())
        pipeline = PipelineView(service, QUndoStack())
        pipeline.model_provider = models.chosen_models

        models._role_edits["zero-shot"].setText("org/my-nli-model")
        models._use_cached("zero-shot")

        assert pipeline.settings().zero_shot_model == "org/my-nli-model"
    finally:
        service.close()


# -- help --------------------------------------------------------------------
def test_the_guide_has_a_section_for_every_screen(qapp):
    titles = " ".join(t for t, _b in HELP_SECTIONS).lower()
    # "survey analysis", not "pipeline": the screen is named for what a
    # researcher is doing, not for the machinery behind it.
    for topic in ("start here", "coding", "codebook", "analysis", "search",
                  "survey", "report", "data", "sharing", "privacy", "shortcut",
                  "question", "troubleshoot"):
        assert topic in titles, f"the guide should cover {topic}"


def test_the_guide_opens_with_a_walkthrough_a_new_user_can_follow(qapp):
    """Someone who has never seen this should reach a real result before
    reading a definition, so the first section is a walkthrough."""
    first_title, first_body = HELP_SECTIONS[0]
    assert "start here" in first_title.lower()
    # It names the datasets that actually ship, so the steps can be followed.
    assert "sample_interview_transcript.txt" in first_body
    assert "sample_survey_education.csv" in first_body
    assert "synthetic_entering_student_survey_wide.csv" in first_body
    # And it teaches the core gesture.
    assert "drag across" in first_body.lower()


def test_the_walkthrough_datasets_really_exist(qapp):
    """A walkthrough that names a file which is not shipped is worse than none."""
    from pathlib import Path as _Path

    data = _Path(__file__).resolve().parent.parent / "data"
    for name in ("sample_interview_transcript.txt",
                 "sample_survey_education.csv",
                 "synthetic_entering_student_survey_wide.csv"):
        assert (data / name).exists(), f"the guide references missing {name}"


def test_the_wide_walkthrough_names_real_columns(qapp):
    """Step C tells the reader to tick specific columns; they must be there."""
    import pandas as pd
    from pathlib import Path as _Path

    frame = pd.read_csv(
        _Path(__file__).resolve().parent.parent
        / "data" / "synthetic_entering_student_survey_wide.csv")
    for column in ("Response_ID", "First_Generation", "Class_Year",
                   "Student_Type"):
        assert column in frame.columns, f"the guide names a missing column {column}"


def test_there_is_an_faq(qapp):
    faq = next((b for t, b in HELP_SECTIONS if "frequently asked" in t.lower()), "")
    assert faq, "the guide should have an FAQ"
    lowered = faq.lower()
    for asked in ("leave this computer", "ollama", "internet", "disk space",
                  "published paper", "case", "encrypted"):
        assert asked in lowered, f"the FAQ should answer about {asked}"


def test_the_faq_answers_the_ollama_question_with_no(qapp):
    faq = next(b for t, b in HELP_SECTIONS if "frequently asked" in t.lower())
    index = faq.index("Do I need Ollama?")
    answer = faq[index:index + 200]
    assert "No." in answer, "Ollama is optional and the FAQ must say so plainly"


def test_the_guide_never_mentions_the_other_front_end(qapp):
    """The reader has not seen any other version of this tool. Design history
    belongs in code comments, not in a user guide."""
    guide = full_guide().lower()
    for internal in ("streamlit", "front end", "upstream", "the fork",
                     "invariant #"):
        assert internal not in guide, f"user-facing text should not say {internal!r}"


def test_the_guide_states_the_load_bearing_methodological_claims(qapp):
    """These are the tool's own answer to "how do you know?". If one quietly
    disappears, the tool starts overstating itself."""
    guide = full_guide().lower()
    assert "cohen" in guide
    assert "percent agreement" in guide
    assert "insufficient-n" in guide
    # Coder-vs-coder is people only; the engine has its own, caveated mode.
    flowed = " ".join(guide.split())
    assert "never pass for a second analyst" in flowed
    assert "only if those were a random sample" in flowed
    assert "can be read, but not reconciled" in flowed
    assert "character position" in guide
    assert "never uploaded" in guide


def test_the_guide_is_honest_about_maturity(qapp):
    guide = full_guide().lower()
    assert "no real research project" in guide


def test_the_guide_says_what_it_does_not_guarantee(qapp):
    guide = full_guide().lower()
    assert "guaranteed" in guide
    assert "not a compliance check" in guide
    assert "does not manage your irb" in guide


def test_the_guide_explains_how_to_share_work(qapp):
    sharing = next((b for t, b in HELP_SECTIONS if "sharing" in t.lower()), "")
    assert sharing
    lowered = sharing.lower()
    assert ".qnw" in lowered
    assert "second coder" in lowered
    assert "export yaml" in lowered
    # And it is honest that project merging is not built yet.
    assert "not in this program yet" in lowered


def test_help_renders_every_section(qapp):
    view = HelpView()
    for row in range(len(HELP_SECTIONS)):
        view.contents.setCurrentRow(row)
        assert view.body.toPlainText().strip(), f"section {row} rendered empty"


def test_the_filter_searches_the_whole_guide_not_just_titles(qapp):
    """Someone looking for "kappa" should find the agreement section even
    though the word is not in its name."""
    view = HelpView()
    view.filter_edit.setText("kappa")
    titles = [view.contents.item(i).text() for i in range(view.contents.count())]
    assert titles, "the filter should find something"
    assert any("agreement" in t.lower() or "question" in t.lower() for t in titles)

    view.filter_edit.setText("")
    assert view.contents.count() == len(HELP_SECTIONS)


def test_the_full_guide_exports_as_one_document(qapp):
    guide = full_guide()
    assert guide.startswith("# QualSafe — user guide")
    for _title, body in HELP_SECTIONS:
        first_line = body.strip().splitlines()[0]
        assert first_line in guide


# -- installing the engine from the Models screen -------------------------------------------------
def test_engine_button_shows_only_when_the_engine_is_missing(view, monkeypatch):
    import qualsafe_qt.views.models_view as mv
    monkeypatch.setattr(mv, "missing_engine_packages", lambda: ["torch"])
    view.refresh()
    assert not view.engine_button.isHidden()
    monkeypatch.setattr(mv, "missing_engine_packages", lambda: [])
    view.refresh()
    assert view.engine_button.isHidden()


def test_engine_task_returns_failure_as_data(monkeypatch):
    import qualsafe_qt.views.models_view as mv
    def boom(progress=None):
        raise mv.engine_install.EngineInstallError("no network", "log tail")
    monkeypatch.setattr(mv.engine_install, "install", boom)
    assert mv._install_engine_task() == {"ok": False, "message": "no network", "log": "log tail"}
