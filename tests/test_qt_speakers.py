"""Speaker separation on the desktop: the checkpoint, the reader, and the guard (item 4.5)."""

from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6", reason="Qt front end not installed")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QUndoStack  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from core import speakers  # noqa: E402
from core.documents import add_document  # noqa: E402
from core.model import Code  # noqa: E402
from core.project import Project  # noqa: E402
from core.ux import words  # noqa: E402
from qualsafe_qt.services.project_service import ProjectService  # noqa: E402
from qualsafe_qt.views import documents_view  # noqa: E402
from qualsafe_qt.views.documents_view import DocumentsView  # noqa: E402
from qualsafe_qt.widgets.more_options import MAX_VISIBLE_CONTROLS, visible_controls  # noqa: E402
from qualsafe_qt.widgets.speaker_review import SpeakerReviewDialog  # noqa: E402

TRANSCRIPT = (
    "Interviewer: What has been the hardest part of this term?\n"
    "Respondent: Honestly the cost. The textbooks alone were more than I expected.\n"
    "Interviewer: And what helped?\n"
    "Respondent: My roommate. We study together and she keeps me going.\n"
)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def service(qapp, tmp_path):
    with Project.create(tmp_path / "p.qnw") as proj:
        add_document(proj, "Interview 01", TRANSCRIPT)
        proj.add_code(Code(code_id="", name="Financial concerns", definition="Cost."))
    svc = ProjectService()
    svc.open(tmp_path / "p.qnw")
    svc.set_analyst_name("Test Analyst")
    yield svc
    svc.close()


@pytest.fixture
def docs(qapp, service):
    view = DocumentsView(service, QUndoStack())
    view.resize(1300, 800)
    view.show()
    view.refresh()
    qapp.processEvents()
    view.library.selectRow(0)
    qapp.processEvents()
    yield view
    view.close()


def _confirm(monkeypatch, roles=None):
    """Make the checkpoint answer 'Use these roles' (optionally changing a role first)."""
    def run(self):
        for label, role in (roles or {}).items():
            combo = self.combos[label]
            combo.setCurrentIndex(combo.findData(role))
        return SpeakerReviewDialog.DialogCode.Accepted
    monkeypatch.setattr(SpeakerReviewDialog, "exec", run)


def test_the_dialog_proposes_roles_and_lets_the_person_change_them(qapp):
    review = speakers.analyse(TRANSCRIPT)
    dialog = SpeakerReviewDialog("Interview 01", review)
    assert dialog.roles() == {"Interviewer": "interviewer", "Respondent": "interviewee"}
    assert dialog.table.rowCount() == 2 and dialog.use_button.property("main") is True
    assert "2 speakers" in dialog.intro.text() and "Confirm or correct" in dialog.intro.text()
    assert dialog.warning.text() == ""
    for label, combo in dialog.combos.items():
        combo.setCurrentIndex(combo.findData("other"))
    assert "interviewer or participant" in dialog.warning.text().lower()    # warns, does not block


def test_the_dialog_is_in_plain_words(qapp):
    dialog = SpeakerReviewDialog("Interview 01", speakers.analyse(TRANSCRIPT))
    shown = " ".join([dialog.intro.text(), dialog.skip_button.text(), dialog.use_button.text(),
                      *[dialog.table.horizontalHeaderItem(i).text() for i in range(5)],
                      *[c.itemText(i) for c in dialog.combos.values() for i in range(c.count())]])
    assert words.find_never(shown) == [] and words.find_replace(shown) == []


def test_confirming_keeps_the_roles_with_the_transcript_and_shows_them(docs, service, monkeypatch, qapp):
    source_id = docs._source_id
    _confirm(monkeypatch)
    assert docs._review_speakers(source_id) is True
    meta = service.document_metadata(source_id)
    assert meta["speakers"]["reviewed"] is True
    assert speakers.summary(meta) == "Interviewer · Participant: Respondent"
    docs.set_step("code")
    qapp.processEvents()
    assert docs.speaker_label.isVisibleTo(docs)
    assert "italics" in docs.speaker_label.text()
    assert [docs.reader.text[s:e] for s, e in docs.reader._speaker_spans] == [
        "What has been the hardest part of this term?", "And what helped?"]


def test_skipping_leaves_the_transcript_exactly_as_it_was(docs, service, monkeypatch):
    source_id = docs._source_id
    before = service.document_metadata(source_id)
    monkeypatch.setattr(SpeakerReviewDialog, "exec", lambda self: SpeakerReviewDialog.DialogCode.Rejected)
    assert docs._review_speakers(source_id) is False
    assert service.document_metadata(source_id) == before
    assert docs.reader._speaker_spans == [] and docs.speaker_label.text() == ""


def test_a_transcript_with_one_speaker_asks_nothing(docs, service, monkeypatch):
    asked = []
    monkeypatch.setattr(SpeakerReviewDialog, "exec", lambda self: asked.append(1))
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: asked.append("told"))
    service.project._conn.execute("UPDATE sources SET raw_text = ? WHERE source_id = ?",
                                  ("One person talking with no labels.", docs._source_id))
    service.project._conn.commit()
    assert docs._review_speakers(docs._source_id) is False and asked == []
    assert docs._review_speakers(docs._source_id, force=True) is False and asked == ["told"]


def test_the_button_is_on_the_add_step_and_the_step_still_shows_seven_controls_or_fewer(docs, qapp):
    docs.set_step("add")
    qapp.processEvents()
    assert docs.speakers_button.isVisibleTo(docs) and docs.speakers_button.isEnabled()
    assert len(visible_controls(docs)) <= MAX_VISIBLE_CONTROLS
    docs.set_step("code")
    qapp.processEvents()
    assert not docs.speakers_button.isVisibleTo(docs)


def test_coding_only_the_interviewers_words_asks_first(docs, service, monkeypatch, qapp):
    _confirm(monkeypatch)
    docs._review_speakers(docs._source_id)
    docs.set_step("code")
    qapp.processEvents()
    start = TRANSCRIPT.index("What has")
    docs.reader.select_span(start, start + len("What has been the hardest"))
    asked = []
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: asked.append(a[2]) or QMessageBox.StandardButton.No)
    docs._code_selection(["Financial concerns"])
    assert len(asked) == 1 and "interviewer's words" in asked[0]
    assert service.coding_spans(docs._source_id) == []                  # said no: nothing coded

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    docs._code_selection(["Financial concerns"])
    assert len(service.coding_spans(docs._source_id)) == 1               # said yes: coded


def test_coding_the_participants_words_does_not_ask(docs, service, monkeypatch, qapp):
    _confirm(monkeypatch)
    docs._review_speakers(docs._source_id)
    docs.set_step("code")
    qapp.processEvents()
    start = TRANSCRIPT.index("Honestly")
    docs.reader.select_span(start, start + len("Honestly the cost."))
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: pytest.fail("asked about the participant's own words"))
    docs._code_selection(["Financial concerns"])
    assert len(service.coding_spans(docs._source_id)) == 1


def test_a_transcript_nobody_confirmed_behaves_as_before(docs, service, monkeypatch, qapp):
    docs.set_step("code")
    qapp.processEvents()
    start = TRANSCRIPT.index("What has")
    docs.reader.select_span(start, start + 12)
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: pytest.fail("asked although no roles were confirmed"))
    docs._code_selection(["Financial concerns"])
    assert len(service.coding_spans(docs._source_id)) == 1


def test_importing_a_folder_reviews_each_new_transcript(docs, service, monkeypatch, tmp_path):
    folder = tmp_path / "more"
    folder.mkdir()
    (folder / "b.txt").write_text(TRANSCRIPT.replace("roommate", "tutor"), encoding="utf-8")
    (folder / "c.txt").write_text(TRANSCRIPT.replace("textbooks", "rent"), encoding="utf-8")
    monkeypatch.setattr(documents_view.QFileDialog, "getExistingDirectory", lambda *a, **k: str(folder))
    monkeypatch.setattr(documents_view, "_confirm_import", lambda *a, **k: True)
    reviewed = []
    monkeypatch.setattr(docs, "_review_speakers", lambda sid, **k: reviewed.append(sid) or False)
    docs._on_import_clicked()
    assert len(reviewed) == 2 and docs._source_id not in reviewed


def test_the_interviewers_words_really_are_drawn_in_italics_and_the_text_is_untouched(qapp):
    from PySide6.QtGui import QTextCursor

    from qualsafe_qt.widgets.document_view import DocumentView

    view = DocumentView()
    view.set_document("s1", TRANSCRIPT)
    asked = TRANSCRIPT.index("What has")
    view.set_speaker_spans([(asked, asked + len("What has been the hardest part of this term?"))])
    doc = view.editor.document()

    def italic_at(position):
        cursor = QTextCursor(doc)
        cursor.setPosition(position + 1)
        return cursor.charFormat().fontItalic()

    assert italic_at(view._offsets.to_qt(asked)) is True
    assert italic_at(view._offsets.to_qt(TRANSCRIPT.index("Honestly"))) is False
    assert view.editor.toPlainText() == TRANSCRIPT              # no character added or lost
    view.set_speaker_spans([])
    assert italic_at(view._offsets.to_qt(asked)) is False


def test_the_dialog_names_the_transcript_straight_after_an_import(docs, service, monkeypatch, tmp_path):
    """Found walking T3: the heading was blank, because the library list is rebuilt only after the review."""
    folder = tmp_path / "new"
    folder.mkdir()
    (folder / "Second interview.txt").write_text(TRANSCRIPT.replace("roommate", "tutor"), encoding="utf-8")
    monkeypatch.setattr(documents_view.QFileDialog, "getExistingDirectory", lambda *a, **k: str(folder))
    monkeypatch.setattr(documents_view, "_confirm_import", lambda *a, **k: True)
    titles = []
    original = SpeakerReviewDialog.__init__

    def record(self, title, review, parent=None):
        titles.append(title)
        original(self, title, review, parent)

    monkeypatch.setattr(SpeakerReviewDialog, "__init__", record)
    monkeypatch.setattr(SpeakerReviewDialog, "exec", lambda self: SpeakerReviewDialog.DialogCode.Rejected)
    docs._on_import_clicked()
    assert titles and all(t.strip() for t in titles), titles
    assert "Second interview" in titles[0]
