"""Interview guide mapping on the desktop: add a guide, get suggestions, remove them (item 4.6)."""

from __future__ import annotations

import os
import zlib
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("PySide6", reason="Qt front end not installed")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QUndoStack  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from core import speakers  # noqa: E402
from core.documents import add_document  # noqa: E402
from core.project import Project  # noqa: E402
from core.ux import words  # noqa: E402
from qualsafe_qt.services.project_service import ProjectService  # noqa: E402
from qualsafe_qt.views import documents_view  # noqa: E402
from qualsafe_qt.views.documents_view import DocumentsView  # noqa: E402
from qualsafe_qt.widgets.more_options import MAX_VISIBLE_CONTROLS, visible_controls  # noqa: E402
from qualsafe_qt.widgets.speaker_review import SpeakerReviewDialog  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
GUIDE = ROOT / "config" / "interview_template.example.yaml"
TRANSCRIPT = (ROOT / "data" / "sample_interview_transcript.txt").read_text(encoding="utf-8")


def fake_embed(texts):
    out = []
    for text in texts:
        v = np.zeros(64)
        for word in text.lower().split():
            v[zlib.crc32(word.encode()) % 64] += 1
        out.append(v / (np.linalg.norm(v) or 1.0))
    return np.array(out)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def service(qapp, tmp_path):
    with Project.create(tmp_path / "p.qnw") as proj:
        sid = add_document(proj, "Interview 01", TRANSCRIPT)
        review = speakers.analyse(TRANSCRIPT)
        proj.update_source_metadata(sid, {"speakers": speakers.to_metadata(
            review, {row.label: row.role for row in review.rows})})
    svc = ProjectService()
    svc.open(tmp_path / "p.qnw")
    svc.set_analyst_name("Test Analyst")
    yield svc
    svc.close()


@pytest.fixture
def docs(qapp, service, monkeypatch):
    # The engine and its model are "there", and the matcher is a small fixed stand-in.
    monkeypatch.setattr("tools.setup_laya_env.has_engine", lambda: True)
    monkeypatch.setattr("core.model_readiness.missing_models", lambda *a, **k: [])
    monkeypatch.setattr(documents_view, "guide_embedder", lambda: fake_embed)
    view = DocumentsView(service, QUndoStack())
    view.resize(1300, 800)
    view.show()
    view.refresh()
    qapp.processEvents()
    view.library.selectRow(0)
    qapp.processEvents()
    view.set_step("code")
    qapp.processEvents()
    yield view
    view.close()


def _wait_for_matching(view, qapp):
    for _ in range(400):
        qapp.processEvents()
        if view._guide_worker is None:
            return
        view._guide_worker.wait(50)
    raise AssertionError("the matching never finished")


def _add_guide(view, monkeypatch, path=GUIDE):
    monkeypatch.setattr(documents_view.QFileDialog, "getOpenFileName", lambda *a, **k: (str(path), ""))
    view._on_guide_clicked()


def test_the_guide_controls_are_folded_under_more_options_and_start_unavailable(docs):
    assert docs.guide_button.isHidden() or not docs.guide_button.isVisibleTo(docs)   # folded away
    assert not docs.guide_suggest_button.isEnabled() and not docs.guide_remove_button.isEnabled()
    assert docs.guide_label.text() == "No guide added yet."
    assert len(visible_controls(docs)) <= MAX_VISIBLE_CONTROLS


def test_adding_a_guide_keeps_it_and_adds_its_themes_to_the_codebook(docs, service, monkeypatch):
    _add_guide(docs, monkeypatch)
    assert docs.guide_label.text().startswith("Student Belonging Interview Guide: 5 themes")
    assert len(service.codebook()) == 5 and docs.code_list.count() == 5
    assert docs.guide_suggest_button.isEnabled()
    assert service.interview_guide() is not None


def test_a_guide_that_cannot_be_used_says_why_and_changes_nothing(docs, service, tmp_path, monkeypatch):
    bad = tmp_path / "bad.yaml"
    bad.write_text("just some words", encoding="utf-8")
    shown = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: shown.append(a[2]))
    _add_guide(docs, monkeypatch, bad)
    assert shown and "does not look like an interview guide" in shown[0]
    assert service.interview_guide() is None and service.codebook() == []


def test_it_explains_what_is_missing_instead_of_failing_when_the_engine_is_not_installed(docs, monkeypatch):
    _add_guide(docs, monkeypatch)
    monkeypatch.setattr("tools.setup_laya_env.has_engine", lambda: False)
    told = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: told.append(a[2]))
    docs._on_guide_suggest()
    assert told and "analysis engine" in told[0] and "Settings" in told[0]
    assert docs._guide_worker is None


def test_it_explains_when_the_small_model_is_not_downloaded(docs, monkeypatch):
    _add_guide(docs, monkeypatch)
    monkeypatch.setattr("core.model_readiness.missing_models",
                        lambda *a, **k: [("embedding", "sentence-transformers/all-MiniLM-L6-v2")])
    told = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: told.append(a[2]))
    docs._on_guide_suggest()
    assert told and "not on this computer yet" in told[0] and docs._guide_worker is None


def test_suggesting_makes_removable_suggestions_and_says_what_it_did(docs, service, qapp, monkeypatch):
    _add_guide(docs, monkeypatch)
    docs._on_guide_suggest()
    assert not docs.guide_suggest_button.isEnabled()                    # busy: no second run
    _wait_for_matching(docs, qapp)
    count = service.guide_suggestion_count(docs._source_id)
    assert count > 0 and service.coding_spans(docs._source_id)
    text = docs.guide_status.text()
    assert f"Suggested {count} code(s)" in text and "fit no theme" in text and "were not asked" in text
    assert docs.guide_remove_button.text() == f"Remove the guide's suggestions ({count})"
    assert docs.guide_suggest_button.isEnabled()


def test_removing_the_suggestions_asks_first_and_then_takes_only_those_away(docs, service, qapp, monkeypatch):
    _add_guide(docs, monkeypatch)
    docs._on_guide_suggest()
    _wait_for_matching(docs, qapp)
    before = service.guide_suggestion_count()
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)
    docs._on_guide_remove()
    assert service.guide_suggestion_count() == before                    # said no: nothing removed
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    docs._on_guide_remove()
    assert service.guide_suggestion_count() == 0 and service.coding_spans(docs._source_id) == []
    assert not docs.guide_remove_button.isEnabled()


def test_a_transcript_without_confirmed_speakers_is_asked_about_them_first(docs, service, qapp, monkeypatch):
    service.project.update_source_metadata(docs._source_id, {"speakers": None})
    _add_guide(docs, monkeypatch)
    asked = []

    def confirm(self):
        asked.append(1)
        return SpeakerReviewDialog.DialogCode.Accepted
    monkeypatch.setattr(SpeakerReviewDialog, "exec", confirm)
    docs._on_guide_suggest()
    _wait_for_matching(docs, qapp)
    assert asked == [1] and service.guide_suggestion_count(docs._source_id) > 0


def test_skipping_the_speaker_check_stops_the_matching_and_says_why(docs, service, monkeypatch):
    service.project.update_source_metadata(docs._source_id, {"speakers": None})
    _add_guide(docs, monkeypatch)
    monkeypatch.setattr(SpeakerReviewDialog, "exec", lambda self: SpeakerReviewDialog.DialogCode.Rejected)
    docs._on_guide_suggest()
    assert docs._guide_worker is None and "who is speaking" in docs.guide_status.text()
    assert service.guide_suggestion_count() == 0


def test_a_matching_failure_is_reported_and_leaves_the_project_alone(docs, service, qapp, monkeypatch):
    _add_guide(docs, monkeypatch)

    def broken(texts):
        raise RuntimeError("the model file is damaged")
    monkeypatch.setattr(documents_view, "guide_embedder", lambda: broken)
    docs._on_guide_suggest()
    _wait_for_matching(docs, qapp)
    assert "did not finish" in docs.guide_status.text() and "damaged" in docs.guide_status.text()
    assert service.guide_suggestion_count() == 0 and docs.guide_suggest_button.isEnabled()


def test_the_words_on_these_controls_are_plain(docs):
    shown = " ".join([docs.guide_button.text(), docs.guide_suggest_button.text(),
                      docs.guide_remove_button.text(), docs.guide_button.toolTip(),
                      docs.guide_suggest_button.toolTip(), docs.guide_remove_button.toolTip()])
    assert words.find_never(shown) == [] and words.find_replace(shown) == []
