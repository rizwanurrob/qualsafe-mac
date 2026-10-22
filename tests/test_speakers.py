"""core/speakers: who is speaking, kept with the transcript and nowhere else (item 4.5)."""

from __future__ import annotations

import json

import pytest

from core import speakers
from core.documents import add_document, import_documents
from core.project import Project

TRANSCRIPT = (
    "Interviewer: What has been the hardest part of this term?\n"
    "Respondent: Honestly the cost. The textbooks alone were more than I expected.\n"
    "Interviewer: And what helped?\n"
    "Respondent: My roommate. We study together and she keeps me going.\n"
)


def _span_text(text, span):
    return text[span[0]:span[1]]


def test_the_review_proposes_roles_from_the_shape_of_the_transcript():
    review = speakers.analyse(TRANSCRIPT)
    assert review.needs_roles and review.n_turns == 4
    roles = {r.label: r.role for r in review.rows}
    assert roles == {"Interviewer": "interviewer", "Respondent": "interviewee"}
    assert review.pattern not in ("", "none") and review.confidence > 0.5
    assert "Confirm or correct" in review.rationale
    assert review.preview[0][0] == "Interviewer" and len(review.preview) == 4


def test_one_speaker_means_nothing_to_confirm():
    review = speakers.analyse("Just one long block of text with no speaker labels at all.")
    assert not review.needs_roles and review.pattern == "none"
    assert review.rationale == ""


def test_the_shares_add_up_and_questions_are_counted():
    review = speakers.analyse(TRANSCRIPT)
    assert abs(sum(r.share for r in review.rows) - 1.0) < 1e-9
    by = {r.label: r for r in review.rows}
    assert by["Interviewer"].questions == 2 and by["Respondent"].questions == 0


def test_the_stored_record_has_labels_and_roles_but_no_words_from_the_transcript():
    review = speakers.analyse(TRANSCRIPT)
    record = speakers.to_metadata(review, {"Interviewer": "interviewer", "Respondent": "interviewee"})
    assert record["reviewed"] is True and record["pattern"] == review.pattern
    blob = json.dumps(record)
    for phrase in ("textbooks", "roommate", "hardest", "cost"):
        assert phrase not in blob


def test_an_unknown_role_is_stored_as_someone_else():
    review = speakers.analyse(TRANSCRIPT)
    record = speakers.to_metadata(review, {"Interviewer": "boss", "Respondent": "interviewee"})
    assert record["roles"]["Interviewer"] == "other"


def test_nothing_counts_until_the_person_has_confirmed():
    review = speakers.analyse(TRANSCRIPT)
    assert speakers.stored({}) is None and speakers.stored(None) is None
    assert speakers.turns_of(TRANSCRIPT, {"speakers": {"pattern": review.pattern, "roles": {}}}) == []
    unreviewed = {"speakers": {"pattern": review.pattern, "roles": {"Interviewer": "interviewer"}}}
    assert speakers.stored(unreviewed) is None


def test_turns_and_spans_come_back_from_the_stored_pattern():
    review = speakers.analyse(TRANSCRIPT)
    meta = {"speakers": speakers.to_metadata(
        review, {"Interviewer": "interviewer", "Respondent": "interviewee"})}
    turns = speakers.turns_of(TRANSCRIPT, meta)
    assert [t.speaker_role for t in turns] == ["interviewer", "interviewee"] * 2
    assert all(TRANSCRIPT[t.char_start:t.char_end] == t.text for t in turns)
    asked = speakers.spans_for(TRANSCRIPT, meta, roles=("interviewer",))
    assert [_span_text(TRANSCRIPT, s) for s in asked] == [
        "What has been the hardest part of this term?", "And what helped?"]


def test_a_pattern_this_version_does_not_know_shows_nothing_and_breaks_nothing():
    meta = {"speakers": {"pattern": "from_a_future_version", "roles": {"A": "interviewer"},
                         "reviewed": True}}
    assert speakers.turns_of(TRANSCRIPT, meta) == []
    assert speakers.spans_for(TRANSCRIPT, meta, roles=("interviewer",)) == []


def test_lies_within_is_true_only_for_the_interviewers_own_words():
    review = speakers.analyse(TRANSCRIPT)
    meta = {"speakers": speakers.to_metadata(
        review, {"Interviewer": "interviewer", "Respondent": "interviewee"})}
    asked = speakers.spans_for(TRANSCRIPT, meta, roles=("interviewer",))
    start = TRANSCRIPT.index("What has")
    inside = (start, start + len("What has been the hardest"))
    assert speakers.lies_within(TRANSCRIPT, inside, asked)
    answer = TRANSCRIPT.index("Honestly")
    assert not speakers.lies_within(TRANSCRIPT, (answer, answer + 20), asked)
    straddling = (start, answer + 20)                    # runs from a question into an answer
    assert not speakers.lies_within(TRANSCRIPT, straddling, asked)
    assert not speakers.lies_within(TRANSCRIPT, (5, 5), asked) and not speakers.lies_within(TRANSCRIPT, inside, [])
    assert not speakers.lies_within("   ", (0, 3), [(0, 3)])      # only spaces: nothing to code


def test_the_summary_line_uses_plain_role_names():
    meta = {"speakers": {"pattern": "q_a", "reviewed": True,
                         "roles": {"Q": "interviewer", "A": "interviewee", "Z": "other"}}}
    assert speakers.summary(meta) == "Interviewer: Q · Participant: A · Someone else: Z"
    assert speakers.summary({}) == ""


# -- keeping it with the transcript ---------------------------------------------------------

def test_the_project_keeps_a_sources_metadata_between_sessions(tmp_path):
    path = tmp_path / "p.qnw"
    with Project.create(path) as proj:
        sid = add_document(proj, "Interview 1", TRANSCRIPT)
        before = proj.get_source(sid).metadata
        assert proj.update_source_metadata(sid, {"speakers": {"pattern": "x", "roles": {}, "reviewed": True}})
        assert proj.update_source_metadata(sid, {"note": "kept"})
    with Project.open(path) as proj:
        meta = proj.get_source(sid).metadata
        assert meta["speakers"]["reviewed"] is True and meta["note"] == "kept"
        assert meta["word_count"] == before["word_count"], "the rest of the metadata is untouched"
        assert proj.update_source_metadata(sid, {"note": None})
        assert "note" not in proj.get_source(sid).metadata
        assert proj.update_source_metadata("no-such-source", {"a": 1}) is False


def test_importing_reports_which_documents_were_added(tmp_path):
    path = tmp_path / "p.qnw"
    one, two = tmp_path / "a.txt", tmp_path / "b.txt"
    one.write_text(TRANSCRIPT, encoding="utf-8")
    two.write_text(TRANSCRIPT.replace("roommate", "tutor"), encoding="utf-8")
    with Project.create(path) as proj:
        result = import_documents(proj, [one, two])
        assert len(result["imported"]) == 2 and len(result["imported_ids"]) == 2
        assert all(proj.get_source(i) is not None for i in result["imported_ids"])
        again = import_documents(proj, [one])
        assert again["imported_ids"] == [] and again["skipped"] == ["a.txt"]


def test_deleting_a_transcript_leaves_no_speaker_label_in_the_file(tmp_path):
    """A label can be a person's name: it is in the same row as the transcript, so it goes with it."""
    text = ("Interviewer: What was hard?\nMariaGonzalez: The tuition, honestly.\n"
            "Interviewer: And?\nMariaGonzalez: Books.\n")
    path = tmp_path / "x.qnw"
    with Project.create(path) as proj:
        sid = add_document(proj, "Int 1", text)
        review = speakers.analyse(text)
        proj.update_source_metadata(sid, {"speakers": speakers.to_metadata(
            review, {row.label: row.role for row in review.rows})})
        proj.delete_source(sid)
        proj._conn.commit()
        proj._conn.execute("VACUUM")
    assert b"MariaGonzalez" not in path.read_bytes()
