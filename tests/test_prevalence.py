"""Prevalence with Wilson intervals and Newcombe differences (V7 Update 2, U1).

The reference values are the worked examples in Newcombe (1998a, 1998b), the
papers that compared these methods, so the numbers here are published, not
recomputed by the code under test.
"""

from __future__ import annotations

import pandas as pd
import pytest

from analysis.prevalence import (CAVEATS, SMALL_GROUP, compare_groups, newcombe_difference,
                                 pooling_caveat, prevalence_table, wilson_interval)


@pytest.mark.parametrize("k,n,lo,hi", [
    (81, 263, 0.2553, 0.3662),   # Newcombe 1998a, example (a)
    (15, 148, 0.0624, 0.1605),   # example (b)
    (0, 20, 0.0000, 0.1611),     # example (c): zero events stay inside [0, 1]
    (1, 29, 0.0061, 0.1718),     # example (d)
])
def test_wilson_matches_newcombe_1998a(k, n, lo, hi):
    got = wilson_interval(k, n)
    assert got[0] == pytest.approx(lo, abs=1e-4)
    assert got[1] == pytest.approx(hi, abs=1e-4)


def test_newcombe_difference_matches_1998b():
    """56/70 vs 48/80: difference 0.2000, method-10 interval 0.0524 to 0.3339."""
    d, lo, hi = newcombe_difference(56, 70, 48, 80)
    assert d == pytest.approx(0.2)
    assert lo == pytest.approx(0.0524, abs=1e-4)
    assert hi == pytest.approx(0.3339, abs=1e-4)


def test_empty_group_is_nan_not_an_error():
    assert all(v != v for v in wilson_interval(0, 0))


def _frames():
    # 40 Pell respondents (12 coded), 60 others (6 coded), 10 international (1 coded)
    desc, coding = [], []
    for i in range(110):
        group = "Pell" if i < 40 else ("Other" if i < 100 else "Intl")
        desc.append({"source_id": f"s{i}", "key": "aid", "value": group})
        coded = (i < 12) or (40 <= i < 46) or i == 100
        if coded:
            coding.append({"source_id": f"s{i}", "code_name": "Cost", "rater_id": "human_primary"})
    coding.append({"source_id": "s50", "code_name": "Belonging", "rater_id": "human_primary"})
    return pd.DataFrame(coding), pd.DataFrame(desc)


def test_every_group_appears_with_its_whole_size_as_n():
    coding, desc = _frames()
    table = prevalence_table(coding, desc, "aid")
    cost = table[table["code"] == "Cost"].set_index("group")
    assert cost.loc["Pell", ["k", "n"]].tolist() == [12, 40]
    assert cost.loc["Other", ["k", "n"]].tolist() == [6, 60]
    belonging = table[table["code"] == "Belonging"].set_index("group")
    assert belonging.loc["Pell", "k"] == 0, "a group nobody coded still appears, at 0%"


def test_small_groups_and_rare_codes_are_flagged():
    coding, desc = _frames()
    table = prevalence_table(coding, desc, "aid").set_index(["code", "group"])
    assert "small group" in table.loc[("Cost", "Intl"), "flag"]
    assert "few coded" in table.loc[("Belonging", "Other"), "flag"]
    assert table.loc[("Cost", "Pell"), "flag"] == ""


def test_group_comparison_uses_newcombe():
    coding, desc = _frames()
    table = prevalence_table(coding, desc, "aid")
    result = compare_groups(table, "Cost", "Pell", "Other")
    d, lo, hi = newcombe_difference(12, 40, 6, 60)
    assert (result["difference"], result["ci_low"], result["ci_high"]) == (d, lo, hi)
    assert result["excludes_zero"] == (lo > 0 or hi < 0)


def test_one_coder_can_be_chosen_and_pooling_is_named():
    coding, desc = _frames()
    coding = pd.concat([coding, pd.DataFrame([
        {"source_id": "s45", "code_name": "Cost", "rater_id": "rater_engine"}])])
    assert "2 coders" in pooling_caveat(coding)
    only_human = prevalence_table(coding, desc, "aid", rater_id="human_primary")
    assert only_human.set_index(["code", "group"]).loc[("Cost", "Other"), "k"] == 6
    assert pooling_caveat(coding[coding["rater_id"] == "human_primary"]) == ""


def test_the_caveats_name_the_coder_change_problem():
    assert any("change in the coder" in c for c in CAVEATS)
    assert any(str(SMALL_GROUP) in c for c in CAVEATS)


def test_d7_style_waves_recover_the_realized_prevalence():
    """Three waves of 300; the table must reproduce k/n exactly, the thing a
    perfect coder of the D7 file would see."""
    import numpy as np
    rng = np.random.default_rng(1)
    desc, coding, truth = [], [], {}
    for wave, p in ((2024, 0.28), (2025, 0.34), (2026, 0.41)):
        hits = rng.random(300) < p
        truth[wave] = int(hits.sum())
        for i, hit in enumerate(hits):
            sid = f"{wave}-{i}"
            desc.append({"source_id": sid, "key": "wave", "value": wave})
            if hit:
                coding.append({"source_id": sid, "code_name": "Cost", "rater_id": "gold"})
    table = prevalence_table(pd.DataFrame(coding), pd.DataFrame(desc), "wave").set_index("group")
    for wave, k in truth.items():
        assert table.loc[wave, "k"] == k and table.loc[wave, "n"] == 300
    change = compare_groups(table.reset_index(), "Cost", 2026, 2024)
    assert change["difference"] == pytest.approx((truth[2026] - truth[2024]) / 300)


def test_both_front_ends_print_the_same_sentence():
    from analysis.prevalence import describe_difference, display_table
    coding, desc = _frames()
    table = prevalence_table(coding, desc, "aid")
    shown = display_table(table).set_index(["code", "group"])
    assert shown.loc[("Cost", "Pell"), "coded / group"] == "12 / 40"
    assert shown.loc[("Cost", "Pell"), "prevalence"] == "30.0%"
    sentence = describe_difference(compare_groups(table, "Cost", "Pell", "Other"))
    assert sentence.startswith("Cost: 30.0% in Pell vs 10.0% in Other, a difference of +20.0 points")
