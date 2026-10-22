"""Agreement on span-coded documents, on a declared unit (finding F4).

Two coders highlighting the same idea almost never pick identical character
spans, and kappa needs a shared set of items. V4 decided the answer: project
each coder's spans onto a declared unit (sentence or paragraph) over documents
both coders say they finished, and compute the existing per-code kappa on those
units. Still kappa-only; the unit and the overlap rule are part of the result.
"""

from __future__ import annotations

import pandas as pd
import pytest

from analysis.agreement import CrossUnitComparisonError, per_code_kappa
from analysis.unit_agreement import OVERLAP_RULES, project_spans_to_units

#                     0         1         2         3         4
#                     0123456789012345678901234567890123456789012345
DOC = "Money is tight. I work a lot. Friends help me."
UNITS = [(0, 15), (16, 29), (30, 46)]     # three sentences, as codeable_units gives


def _codings(rows):
    return pd.DataFrame(rows, columns=["rater_id", "source_id", "code_name", "char_start", "char_end"])


def test_unequal_spans_on_the_same_idea_agree_at_the_sentence_level():
    codings = _codings([
        ("A", "d1", "Cost", 0, 15),      # exactly sentence 1
        ("B", "d1", "Cost", 6, 14),      # "is tight" inside sentence 1
    ])
    units = project_spans_to_units(codings, {"d1": UNITS}, rule="any_overlap")
    assert units["A"] == units["B"] == {"d1#0": {"Cost"}, "d1#1": set(), "d1#2": set()}


def test_the_overlap_rule_decides_a_straddling_span():
    # A's span runs 4 characters into sentence 2 (13 characters long).
    codings = _codings([("A", "d1", "Cost", 0, 20)])
    anyo = project_spans_to_units(codings, {"d1": UNITS}, rule="any_overlap")["A"]
    most = project_spans_to_units(codings, {"d1": UNITS}, rule="majority")["A"]
    assert anyo["d1#1"] == {"Cost"}
    assert most["d1#1"] == set()
    assert set(OVERLAP_RULES) == {"any_overlap", "majority"}


def test_every_unit_of_a_finished_document_is_an_item_even_uncoded():
    codings = _codings([("A", "d1", "Work", 16, 29)])
    units = project_spans_to_units(codings, {"d1": UNITS}, rule="any_overlap",
                                   raters=["A", "B"])
    assert set(units["B"]) == {"d1#0", "d1#1", "d1#2"}
    assert all(v == set() for v in units["B"].values())


def test_kappa_on_units_matches_a_hand_built_table():
    """Two documents, three sentences each: six items. Cost: A on units
    0 and 3, B on 0 and 4 -> a=1, b=1, c=1, d=3, po=4/6, pe=(2/6)^2+(4/6)^2,
    kappa = (0.6667-0.5556)/(1-0.5556) = 0.25."""
    units = {"d1": UNITS, "d2": UNITS}
    codings = _codings([
        ("A", "d1", "Cost", 0, 15), ("A", "d2", "Cost", 0, 15),
        ("B", "d1", "Cost", 0, 15), ("B", "d2", "Cost", 16, 29),
    ])
    items = project_spans_to_units(codings, units, rule="any_overlap")
    row = per_code_kappa(items["A"], items["B"], min_support=1).iloc[0]
    assert row["n_items"] == 6
    assert row["kappa"] == pytest.approx(0.25, abs=1e-4)


def test_an_unknown_rule_is_refused():
    with pytest.raises(ValueError):
        project_spans_to_units(_codings([]), {"d1": UNITS}, rule="exact")


# ── the store side: which documents each coder finished ──────────────────────
def _doc_project(tmp_path):
    from core.model import Code, Source
    from core.project import Project
    from core.span_coding import apply_codes_to_span

    path = tmp_path / "d.qnw"
    with Project.create(path) as proj:
        proj.add_code(Code(code_id="", name="Cost"))
        for sid in ("d1", "d2"):
            proj.add_source(Source(source_id=sid, type="document", raw_text=DOC, label=sid))
        apply_codes_to_span(proj, "d1", 0, 15, ["Cost"], rater_id="human_primary")
        apply_codes_to_span(proj, "d1", 6, 14, ["Cost"], rater_id="human_B")
        apply_codes_to_span(proj, "d2", 30, 46, ["Cost"], rater_id="human_B")
    return path


def test_only_documents_both_coders_finished_are_compared(tmp_path):
    from core.agreement_pairs import span_comparison
    from core.project import Project

    path = _doc_project(tmp_path)
    with Project.open(path) as proj:
        assert span_comparison(proj, "human_primary", "human_B", unit="sentence") is None
        proj.mark_document_coded("human_primary", "d1")
        proj.mark_document_coded("human_B", "d1")
        proj.mark_document_coded("human_B", "d2")      # A never finished d2
        comp = span_comparison(proj, "human_primary", "human_B", unit="sentence")
    assert set(comp.labels_a) == {"d1#0", "d1#1", "d1#2"}
    assert comp.labels_a == comp.labels_b
    assert comp.unit == "sentence" and comp.rule == "any_overlap"
    assert any("sentence" in c for c in comp.caveats)


def test_unmarking_a_document_takes_it_back_out(tmp_path):
    from core.project import Project

    path = _doc_project(tmp_path)
    with Project.open(path) as proj:
        proj.mark_document_coded("human_B", "d1")
        proj.mark_document_coded("human_B", "d1", coded=False)
        assert proj.documents_coded_by("human_B") == set()


def test_sentence_and_paragraph_kappa_are_never_compared():
    from analysis.agreement import assert_comparable_units
    with pytest.raises(CrossUnitComparisonError):
        assert_comparable_units("sentence", "paragraph")
