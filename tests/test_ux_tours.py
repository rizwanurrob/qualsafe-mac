"""core/ux/help/tours: four plain cards per activity, and a remembered "seen" list."""

from __future__ import annotations

import json

import pytest

from core.ux import activities, words
from core.ux.help import tours

KEYS = tours.keys()


def test_there_is_a_tour_for_each_activity():
    assert KEYS == ["surveys", "charts", "interviews"]


@pytest.mark.parametrize("key", KEYS)
def test_a_tour_has_three_to_five_cards_each_pointing_at_something(key):
    cards = tours.tour(key)
    assert 3 <= len(cards) <= 5
    assert all(c.target in tours.TARGETS for c in cards)
    assert [c.target for c in cards] == ["rail", "main", "more", "help"]


@pytest.mark.parametrize("key", KEYS)
def test_the_cards_are_short_and_in_plain_words(key):
    for card in tours.tour(key):
        assert card.title and card.text
        assert len(card.text) <= 200 and len(card.title) <= 50
        assert words.find_never(card.text + card.title) == []
        assert words.find_replace(card.text + card.title) == []


@pytest.mark.parametrize("key", KEYS)
def test_the_first_card_names_the_real_steps(key):
    first = tours.tour(key)[0]
    activity = activities.get(key)
    assert str(len(activity.steps)) in first.title
    assert all(step.title in first.text for step in activity.steps)


def test_seen_round_trips_and_ignores_rubbish():
    seen = tours.mark_seen(set(), "charts")
    assert tours.parse(tours.dump(seen)) == {"charts"}
    assert tours.parse("not json") == set()
    assert tours.parse(json.dumps({"charts": 1})) == set()
    assert tours.parse(json.dumps(["charts", "no-such-activity", 3])) == {"charts"}
    assert tours.parse("") == set() and tours.parse(None) == set()


def test_only_real_activities_are_remembered_and_nothing_else_is_stored():
    assert tours.mark_seen(set(), "no-such-activity") == set()
    assert set(json.loads(tours.dump({"surveys", "charts"}))) == {"surveys", "charts"}


def test_a_tour_is_due_until_it_has_been_seen():
    assert tours.is_due(set(), "surveys") is True
    assert tours.is_due({"surveys"}, "surveys") is False
    assert tours.is_due({"surveys"}, "charts") is True
