"""core/hand_coding.py: coding survey answers by hand, as whole answers (offline)."""

import pandas as pd
import pytest

from core import hand_coding as hc
from core.model import Code
from core.project import Project
from core.span_coding import HUMAN_RATER

FRAME = pd.DataFrame({
    "id": [f"r{n}" for n in range(1, 8)],
    "answer": ["Cost of books", "Made friends late", "", "Too many hours at work", "Advisor helped",
               "Rent is high", "Nothing major"],
})


@pytest.fixture
def path(tmp_path):
    p = tmp_path / "p.qnw"
    with Project.create(p) as proj:
        proj.add_code(Code(code_id="", name="Money"))
        proj.add_code(Code(code_id="", name="Belonging"))
    assert hc.prepare(p, FRAME, "answer", "id") == 6          # the empty answer is left out
    return p


def test_preparing_twice_adds_nothing_new(path):
    assert hc.prepare(path, FRAME, "answer", "id") == 6
    with Project.open(path) as proj:
        assert hc.total_answers(proj) == 6


def test_answers_come_in_the_order_of_the_spreadsheet(path):
    with Project.open(path) as proj:
        answers, _ = hc.page(proj, limit=10)
    assert [a.label for a in answers] == ["r1", "r2", "r4", "r5", "r6", "r7"]


def test_a_page_lists_answers_with_their_state_and_counts_all_matches(path):
    with Project.open(path) as proj:
        answers, total = hc.page(proj, limit=4)
        assert total == 6 and len(answers) == 4 and not any(a.judged for a in answers)
        rest, _ = hc.page(proj, offset=4, limit=4)
        assert len(rest) == 2


def test_search_finds_text_and_labels(path):
    with Project.open(path) as proj:
        by_text, n = hc.page(proj, search="advisor")
        assert n == 1 and by_text[0].text == "Advisor helped"
        by_label, m = hc.page(proj, search="r6")
        assert m == 1 and by_label[0].text == "Rent is high"


def test_saving_records_the_codes_and_marks_the_answer_judged(path):
    with Project.open(path) as proj:
        first = hc.page(proj, limit=1)[0][0]
        result = hc.save(proj, first.source_id, ["Money"], rater_name="Test")
        assert result["codes"] == ["Money"] and result["new_codes"] == []
        again = hc.get(proj, first.source_id)
        assert again.judged and again.codes == ["Money"]
        assert hc.progress(proj) == (1, 6)


def test_no_code_applies_is_a_judgement_not_a_gap(path):
    with Project.open(path) as proj:
        first = hc.page(proj, limit=1)[0][0]
        hc.save(proj, first.source_id, [])
        again = hc.get(proj, first.source_id)
        assert again.judged and again.codes == []
        assert proj.rater_item_set(HUMAN_RATER).recorded            # agreement will count it


def test_changing_your_mind_replaces_the_earlier_choice(path):
    with Project.open(path) as proj:
        first = hc.page(proj, limit=1)[0][0]
        hc.save(proj, first.source_id, ["Money", "Belonging"])
        hc.save(proj, first.source_id, ["Belonging"])
        assert hc.get(proj, first.source_id).codes == ["Belonging"]


def test_a_new_name_makes_a_new_code(path):
    with Project.open(path) as proj:
        first = hc.page(proj, limit=1)[0][0]
        result = hc.save(proj, first.source_id, ["Workload"])
        assert result["new_codes"] == ["Workload"]
        assert proj.find_code_by_name("Workload") is not None


def test_only_unjudged_hides_what_is_done(path):
    with Project.open(path) as proj:
        first = hc.page(proj, limit=1)[0][0]
        hc.save(proj, first.source_id, ["Money"])
        rest, total = hc.page(proj, only_unjudged=True)
        assert total == 5 and first.source_id not in [a.source_id for a in rest]


def test_next_unjudged_moves_on_and_wraps(path):
    with Project.open(path) as proj:
        ids = [a.source_id for a in hc.page(proj, limit=6)[0]]
        assert hc.next_unjudged(proj) == ids[0]
        hc.save(proj, ids[0], [])
        assert hc.next_unjudged(proj, ids[0]) == ids[1]
        for source_id in ids[1:]:
            hc.save(proj, source_id, [])
        assert hc.next_unjudged(proj, ids[-1]) is None               # all done
        # leave the first one undone: after the last, it wraps round to it
    with Project.open(path) as proj:
        proj.replace_applications_for_rater(HUMAN_RATER, [hc.get(proj, ids[0]).excerpt_id], [])
        proj._conn.execute("DELETE FROM rater_coverage WHERE excerpt_id = ?", (hc.get(proj, ids[0]).excerpt_id,))
        proj._conn.commit()
        assert hc.next_unjudged(proj, ids[-1]) == ids[0]


def test_a_missing_answer_is_refused(path):
    with Project.open(path) as proj:
        with pytest.raises(ValueError):
            hc.save(proj, "nope", ["Money"])
        assert hc.get(proj, "nope") is None


def test_hand_codes_are_compared_by_the_existing_agreement_machinery(path):
    """The human rater's judged items are what agreement reads, with 'no code' as a real answer."""
    with Project.open(path) as proj:
        answers = hc.page(proj, limit=3)[0]
        hc.save(proj, answers[0].source_id, ["Money"])
        hc.save(proj, answers[1].source_id, [])
        labels = proj.rater_item_set(HUMAN_RATER).labels
        assert labels[answers[0].excerpt_id] == {"Money"} and labels[answers[1].excerpt_id] == set()
        assert answers[2].excerpt_id not in labels                      # not judged: not a "no code"
