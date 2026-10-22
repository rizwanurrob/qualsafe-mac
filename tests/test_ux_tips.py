"""core/ux/help/tips: short, plain, and each points at an article that exists."""

from __future__ import annotations

import re

import pytest

from core.ux import help as shared_help, words
from core.ux.help import tips

IDS = sorted(tips.TIPS)


def _sentences(text: str) -> int:
    return len([s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s])


@pytest.mark.parametrize("tip_id", IDS)
def test_a_tip_is_one_or_two_plain_sentences(tip_id):
    tip = tips.TIPS[tip_id]
    assert 1 <= _sentences(tip.text) <= 2, tip.text
    assert len(tip.text) <= 230, "a tip is a nudge, not an essay"
    assert words.find_never(tip.text) == [] and words.find_replace(tip.text) == []


@pytest.mark.parametrize("tip_id", IDS)
def test_a_tip_points_at_an_article_that_exists(tip_id):
    activity_key, _, step_key = tips.TIPS[tip_id].article.partition("-")
    assert shared_help.article(activity_key, step_key), tip_id


def test_every_label_finds_a_real_tip_and_every_tip_is_used():
    assert set(tips.LABEL_TIPS.values()) <= set(tips.TIPS)
    # model.method is chosen by id, because "Method" means something else on the Code step
    assert set(tips.TIPS) - set(tips.LABEL_TIPS.values()) == {"model.method"}


def test_a_label_that_means_two_things_is_not_matched_by_label_alone():
    assert tips.for_label("Method") == "code.method"
    assert tips.get("model.method").text != tips.get("code.method").text
    assert tips.for_label("a label nobody wrote a tip for") is None
