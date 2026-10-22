"""
Tests for saturation analysis (v4.6, `V5_PLAN.md` §B5).

The curve is the easy part. What is actually being pinned here is that the
**caveats are inseparable from it**, because a saturation figure is quoted in a
Methods section and, once quoted, nobody goes back to the software to find out
what it excluded.

Three of those caveats are disqualifying often enough to matter: an a-priori
codebook makes the curve meaningless, ingestion order is not collection order,
and code saturation is not meaning saturation. A curve that could be read
without them would be a feature that invites the misuse it exists to prevent.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analysis.saturation import (
    saturation_caveats, saturation_curve, saturation_summary)
from core.model import Code


def _coding(pairs, rater="human_primary"):
    """`pairs` is [(source_id, code_name), ...] in coding order."""
    return pd.DataFrame(
        [{"source_id": s, "code_name": c, "rater_id": rater} for s, c in pairs])


class TestTheCurve:

    def test_new_codes_are_counted_once_each(self):
        curve = saturation_curve(_coding([
            ("s1", "Cost"), ("s2", "Cost"), ("s2", "Advising"), ("s3", "Cost"),
        ]))

        assert list(curve["new_codes"]) == [1, 1, 0]
        assert list(curve["cumulative_codes"]) == [1, 2, 2]

    def test_a_source_carrying_several_new_codes_counts_them_all(self):
        curve = saturation_curve(_coding([
            ("s1", "Cost"), ("s1", "Advising"), ("s1", "Belonging"),
        ]))
        assert list(curve["new_codes"]) == [3]

    def test_a_given_order_is_respected(self):
        coding = _coding([("s1", "Cost"), ("s2", "Advising")])

        curve = saturation_curve(coding, source_order=["s2", "s1"])

        assert list(curve["source_id"]) == ["s2", "s1"]

    def test_uncoded_sources_are_left_off_the_curve(self):
        """A zero sitting in the curve reads as evidence of a plateau and is not
        — the source was never read."""
        coding = _coding([("s1", "Cost"), ("s3", "Advising")])

        curve = saturation_curve(coding, source_order=["s1", "s2", "s3", "s4"])

        assert list(curve["source_id"]) == ["s1", "s3"]

    def test_a_coded_source_missing_from_the_order_is_still_included(self):
        coding = _coding([("s1", "Cost"), ("s9", "Advising")])
        curve = saturation_curve(coding, source_order=["s1"])
        assert set(curve["source_id"]) == {"s1", "s9"}

    def test_machine_coding_is_excluded_by_default(self):
        """A model applying a fixed list saturates instantly and has discovered
        nothing, so pooling it flatters the curve for the wrong reason."""
        coding = pd.concat([
            _coding([("s1", "Cost")], rater="human_primary"),
            _coding([("s2", "Machine")], rater="transformer"),
        ])

        assert list(saturation_curve(coding)["source_id"]) == ["s1"]
        assert len(saturation_curve(coding, humans_only=False)) == 2

    def test_an_empty_project_produces_an_empty_curve_not_an_error(self):
        curve = saturation_curve(pd.DataFrame())
        assert curve.empty
        assert list(curve.columns) == ["position", "source_id", "new_codes",
                                       "cumulative_codes"]


class TestTheSummary:

    def test_it_reports_where_the_last_new_code_appeared(self):
        curve = saturation_curve(_coding([
            ("s1", "A"), ("s2", "B"), ("s3", "A"), ("s4", "A"), ("s5", "A"),
        ]))

        summary = saturation_summary(curve)

        assert summary.codes_found == 2
        assert summary.sources_coded == 5
        assert summary.last_new_code_at == 2
        assert summary.plateau_length == 3

    def test_the_ninety_percent_point_is_the_flattening_people_mean(self):
        pairs = [(f"s{i}", f"C{i}") for i in range(1, 11)]  # ten codes, ten sources
        curve = saturation_curve(_coding(pairs))

        assert saturation_summary(curve).ninety_percent_at == 9

    def test_a_sentence_is_produced_for_a_methods_section(self):
        curve = saturation_curve(_coding([("s1", "A"), ("s2", "B"), ("s3", "A")]))

        sentence = saturation_summary(curve).as_sentence()

        assert "2 codes" in sentence and "3 coded source" in sentence
        assert "last new code appeared at source 2" in sentence

    def test_an_empty_curve_says_so_rather_than_dividing_by_zero(self):
        summary = saturation_summary(pd.DataFrame())
        assert summary.sources_coded == 0
        assert "no saturation curve" in summary.as_sentence()

    def test_sources_coded_with_no_codes_applied_is_stated_plainly(self):
        curve = pd.DataFrame([{"position": 1, "source_id": "s1", "new_codes": 0,
                               "cumulative_codes": 0}])
        assert "no codes applied" in saturation_summary(curve).as_sentence()


class TestTheCaveatsAreInseparable:

    def test_there_is_always_at_least_one(self):
        """A curve that could be read without a caveat would be the misuse this
        feature exists to prevent."""
        assert saturation_caveats(saturation_curve(_coding([("s1", "A")])))

    def test_an_entirely_a_priori_codebook_is_called_meaningless(self):
        codes = [Code(code_id="1", name="A", origin="a_priori"),
                 Code(code_id="2", name="B", origin="a_priori")]

        notes = saturation_caveats(
            saturation_curve(_coding([("s1", "A"), ("s2", "B")])), codes=codes)

        assert any("defined before coding began" in n and "not a meaningful claim" in n
                   for n in notes)

    def test_a_mixed_codebook_says_how_many_can_actually_saturate(self):
        codes = [Code(code_id="1", name="A", origin="a_priori"),
                 Code(code_id="2", name="B", origin="emergent")]

        notes = saturation_caveats(saturation_curve(_coding([("s1", "A")])),
                                   codes=codes)

        assert any("1 of 2 codes were defined before" in n for n in notes)

    def test_an_entirely_emergent_codebook_gets_no_a_priori_warning(self):
        codes = [Code(code_id="1", name="A", origin="emergent")]
        notes = saturation_caveats(saturation_curve(_coding([("s1", "A")])),
                                   codes=codes)
        assert not any("defined before coding began" in n for n in notes)

    def test_ingestion_order_is_flagged_as_not_collection_order(self):
        notes = saturation_caveats(saturation_curve(_coding([("s1", "A")])))
        assert any("not necessarily the order the data was collected" in n
                   for n in notes)

    def test_a_real_collection_order_removes_that_caveat(self):
        notes = saturation_caveats(saturation_curve(_coding([("s1", "A")])),
                                   order_is_collection_order=True)
        assert not any("not necessarily the order" in n for n in notes)

    def test_code_saturation_is_always_distinguished_from_meaning_saturation(self):
        notes = saturation_caveats(saturation_curve(_coding([("s1", "A")])),
                                   order_is_collection_order=True)
        assert any("not meaning saturation" in n for n in notes)

    def test_a_short_curve_says_it_cannot_show_a_plateau(self):
        notes = saturation_caveats(saturation_curve(_coding([("s1", "A")])))
        assert any("cannot show a plateau" in n for n in notes)

    def test_a_curve_still_finding_codes_says_it_has_not_flattened(self):
        pairs = [(f"s{i}", f"C{i}") for i in range(1, 13)]  # a new code every time
        notes = saturation_caveats(saturation_curve(_coding(pairs)))

        assert any("has not flattened" in n for n in notes)

    def test_a_flattened_curve_is_not_told_it_has_not_flattened(self):
        pairs = [("s1", "A"), ("s2", "B")] + [(f"s{i}", "A") for i in range(3, 14)]
        notes = saturation_caveats(saturation_curve(_coding(pairs)))

        assert not any("has not flattened" in n for n in notes)

    def test_no_verdict_is_ever_printed(self):
        """"Saturated" is a claim only a researcher can make. A tool that printed
        it would be laundering that judgement."""
        pairs = [("s1", "A")] + [(f"s{i}", "A") for i in range(2, 40)]
        curve = saturation_curve(_coding(pairs))

        blob = " ".join(saturation_caveats(curve)).lower()
        blob += " " + saturation_summary(curve).as_sentence().lower()

        assert "saturation was reached" not in blob
        assert "saturated" not in blob
