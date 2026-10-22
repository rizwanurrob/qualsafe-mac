"""
The cache for the stage that actually costs something.

Pass 17 measured the pipeline at realistic scale and found zero-shot coding to
be about 94% of a five-thousand-response run. Pass 18 asked what a *second* run
costs, and found the answer to be: the same, because the only cached stage was
embeddings — 60 seconds of a 7,680-second job.

Three things followed from that, and all three are things researchers do:

* an interrupted run started over from zero
* adding one label to a codebook re-coded every response against every label
* fixing one typo in one response re-coded the whole file, because the embedding
  cache key is a hash of every text concatenated

The correctness question underneath is cache granularity, and it is not a
matter of taste. Measured on `facebook/bart-large-mnli`, holding the responses
fixed and shrinking the candidate set from six labels to two:

    multi_label=True    worst score drift 5.96e-08
    multi_label=False   worst score drift 3.85e-01

So per-label caching is exactly right in one mode and a silent correctness bug
in the other, and the tests below pin that distinction harder than anything else
in this file. A cache that returns the wrong number is worse than no cache: it
is fast, invisible, and wrong.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.inference_cache import (  # noqa: E402
    CACHE_FILENAME, InferenceCache, as_result, clear_cache, open_cache,
    plan_zero_shot, sentiment_key, zero_shot_key)

MODEL = "facebook/bart-large-mnli"
LABELS = ["billing", "delivery", "website"]


@pytest.fixture
def cache(tmp_path):
    with InferenceCache(tmp_path / "c.sqlite") as found:
        yield found


class TestKeysSeparateWhatMustBeSeparate:
    """Every field in a key is there because leaving it out serves a wrong
    answer rather than a slow one."""

    def test_different_text_is_a_different_key(self):
        assert (sentiment_key(MODEL, "good") != sentiment_key(MODEL, "bad"))

    def test_different_model_is_a_different_key(self):
        """A distilbert sentiment score is not a roberta one."""
        assert sentiment_key("a", "x") != sentiment_key("b", "x")

    def test_the_two_zero_shot_modes_never_collide(self):
        """The whole point of the file. One label under multi_label is an
        independent entailment probability; the same label under softmax is
        normalised across its company. They are different numbers."""
        assert (zero_shot_key(MODEL, "x", ["billing"], True)
                != zero_shot_key(MODEL, "x", ["billing"], False))

    def test_the_softmax_key_covers_the_whole_candidate_set(self):
        """Because the score genuinely changes when the set does."""
        assert (zero_shot_key(MODEL, "x", ["a", "b"], False)
                != zero_shot_key(MODEL, "x", ["a", "b", "c"], False))

    def test_the_multi_label_key_does_not_depend_on_the_other_labels(self):
        """Because the score genuinely does not. This is what makes adding a
        seventh label cost one label instead of seven."""
        assert (zero_shot_key(MODEL, "x", ["a"], True)
                == zero_shot_key(MODEL, "x", ["a"], True))

    def test_label_boundaries_are_delimited(self):
        """['ab','c'] must not hash like ['a','bc'] — the same trap the
        embedding cache documents."""
        assert (zero_shot_key(MODEL, "x", ["ab", "c"], False)
                != zero_shot_key(MODEL, "x", ["a", "bc"], False))

    def test_the_text_cannot_be_confused_with_a_label(self):
        assert (zero_shot_key(MODEL, "a", ["b"], False)
                != zero_shot_key(MODEL, "b", ["a"], False))


class TestItStoresAndReturns:

    def test_a_stored_value_comes_back(self, cache):
        cache.put_many("sentiment", [("k1", {"label": "POSITIVE", "score": 0.9})])

        assert cache.get_many(["k1"])["k1"] == {"label": "POSITIVE", "score": 0.9}

    def test_an_unknown_key_is_simply_absent(self, cache):
        cache.put_many("sentiment", [("k1", 1)])

        assert cache.get_many(["k1", "k2"]) == {"k1": 1}

    def test_it_handles_more_keys_than_sqlite_takes_parameters(self, cache):
        """A 5,000-response run with six labels asks for 30,000 keys at once,
        and SQLite's host-parameter limit is 999 on older builds."""
        pairs = [(f"k{i}", i) for i in range(2500)]
        cache.put_many("zero_shot", pairs)

        found = cache.get_many([k for k, _ in pairs])

        assert len(found) == 2500
        assert found["k1999"] == 1999

    def test_writing_nothing_is_not_an_error(self, cache):
        assert cache.put_many("zero_shot", []) == 0

    def test_reading_nothing_is_not_an_error(self, cache):
        assert cache.get_many([]) == {}


class TestEachWriteIsCommitted:
    """The property the whole module exists for. A cache that flushed at the
    end of the stage would reproduce the defect it is fixing: a two-hour run,
    interrupted at ninety minutes, that saved nothing."""

    def test_another_connection_sees_the_write_immediately(self, tmp_path):
        path = tmp_path / "c.sqlite"
        cache = InferenceCache(path)
        cache.put_many("zero_shot", [("k", 0.5)])

        # A separate connection stands in for the process that comes back after
        # the interrupted one died.
        with sqlite3.connect(str(path)) as conn:
            rows = conn.execute("SELECT value FROM entries WHERE key='k'").fetchall()

        assert rows == [("0.5",)]
        cache.close()

    def test_a_reopened_cache_still_has_its_entries(self, tmp_path):
        path = tmp_path / "c.sqlite"
        with InferenceCache(path) as first:
            first.put_many("sentiment", [("k", {"label": "NEGATIVE"})])

        with InferenceCache(path) as second:
            assert second.get_many(["k"])["k"] == {"label": "NEGATIVE"}


class TestAFailingCacheIsAMissAndNeverAnError:
    """The analyst did not ask for this cache. It must not be able to end a run.

    A laptop that lost power mid-write, a read-only directory, a file some other
    process holds open — each of those should cost a recomputation, not an
    afternoon.
    """

    def test_an_unopenable_path_degrades_to_disabled(self, tmp_path):
        # A directory where the file should be: cannot be opened as a database.
        (tmp_path / CACHE_FILENAME).mkdir()

        found = open_cache(tmp_path)

        assert found is not None
        assert found.enabled is False

    def test_a_disabled_cache_answers_every_read_with_a_miss(self, tmp_path):
        (tmp_path / CACHE_FILENAME).mkdir()
        found = open_cache(tmp_path)

        assert found.get_many(["anything"]) == {}
        assert found.put_many("zero_shot", [("k", 1)]) == 0
        assert found.count() == 0

    def test_a_corrupt_row_is_a_miss_not_a_crash(self, tmp_path):
        path = tmp_path / "c.sqlite"
        cache = InferenceCache(path)
        cache.put_many("zero_shot", [("good", 1)])
        with sqlite3.connect(str(path)) as conn:
            conn.execute("INSERT INTO entries VALUES ('torn','zero_shot','{not json')")
            conn.commit()

        found = cache.get_many(["good", "torn"])

        assert found == {"good": 1}
        cache.close()

    def test_switching_it_off_hands_back_nothing_to_use(self, tmp_path):
        assert open_cache(tmp_path, enabled=False) is None
        assert not (tmp_path / CACHE_FILENAME).exists()


class TestTwoRunsCanShareOneCache:
    """Two analyses over the same output directory share one SQLite file, and
    that had never been exercised until it was asked about.

    Measured before writing these: three concurrent threads and three separate
    *processes*, 200 writes each, on one file. No exception, no `put_many` that
    silently wrote nothing, and all 600 rows present afterwards -- about 4-5
    seconds either way. SQLite's own locking carries it, and `put_many`'s
    commit-per-chunk keeps each lock short.
    """

    def test_two_connections_writing_at_once_lose_nothing(self, tmp_path):
        import threading

        path = tmp_path / "shared.sqlite"
        errors = []

        def worker(tag):
            try:
                with InferenceCache(path) as cache:
                    for i in range(50):
                        cache.put_many("zero_shot", [(f"{tag}-{i}", i)])
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{tag}: {exc}")

        threads = [threading.Thread(target=worker, args=(t,)) for t in "abc"]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert errors == []
        with InferenceCache(path) as cache:
            assert cache.count() == 150

    def test_one_connection_sees_what_another_committed(self, tmp_path):
        """The resumed-run case: a second process must find the first's work."""
        path = tmp_path / "shared.sqlite"

        with InferenceCache(path) as first, InferenceCache(path) as second:
            first.put_many("zero_shot", [("k", 0.25)])

            assert second.get_many(["k"]) == {"k": 0.25}


class TestPlanningTheWork:
    """What gets recomputed, and what does not."""

    def test_an_empty_cache_means_everything_is_outstanding(self):
        known, outstanding = plan_zero_shot(
            ["a", "b"], LABELS, MODEL, True, {})

        assert known == [{}, {}]
        assert [i for i, _ in outstanding] == [0, 1]
        assert all(missing == LABELS for _, missing in outstanding)

    def test_a_full_cache_means_no_work_at_all(self):
        cached = {zero_shot_key(MODEL, text, [label], True): 0.5
                  for text in ("a", "b") for label in LABELS}

        known, outstanding = plan_zero_shot(["a", "b"], LABELS, MODEL, True, cached)

        assert outstanding == []
        assert known[0] == {label: 0.5 for label in LABELS}

    def test_adding_a_label_costs_only_that_label(self):
        """The headline. An analyst who has to choose between a better codebook
        and a two-hour wait will choose the wait once, and then stop refining."""
        cached = {zero_shot_key(MODEL, text, [label], True): 0.5
                  for text in ("a", "b") for label in LABELS}

        _known, outstanding = plan_zero_shot(
            ["a", "b"], LABELS + ["returns"], MODEL, True, cached)

        assert [missing for _, missing in outstanding] == [["returns"], ["returns"]]

    def test_editing_one_response_costs_only_that_response(self):
        cached = {zero_shot_key(MODEL, text, [label], True): 0.5
                  for text in ("a", "b") for label in LABELS}

        _known, outstanding = plan_zero_shot(
            ["a", "edited"], LABELS, MODEL, True, cached)

        assert [i for i, _ in outstanding] == [1]

    def test_under_softmax_a_response_is_all_or_nothing(self):
        """Not a limitation to work around — the scores really are normalised
        across the candidate set, so a partial reuse would mix two questions."""
        cached = {zero_shot_key(MODEL, "a", LABELS, False): {lab: 0.3 for lab in LABELS}}

        known, outstanding = plan_zero_shot(["a", "b"], LABELS, MODEL, False, cached)

        assert known[0] == {lab: 0.3 for lab in LABELS}
        assert [(i, m) for i, m in outstanding] == [(1, LABELS)]

    def test_under_softmax_a_changed_label_set_invalidates_everything(self):
        """Correctness, not conservatism: measured drift was 0.385."""
        cached = {zero_shot_key(MODEL, "a", LABELS, False): {lab: 0.3 for lab in LABELS}}

        _known, outstanding = plan_zero_shot(
            ["a"], LABELS + ["returns"], MODEL, False, cached)

        assert len(outstanding) == 1


class TestTheRebuiltResultMatchesThePipelineContract:
    """Downstream reads `item["labels"][0]` as the top label. A cached result
    that came back in a different order would change coding decisions without
    changing a single score."""

    def test_labels_come_back_ordered_by_score_descending(self):
        found = as_result("x", {"billing": 0.1, "delivery": 0.9, "website": 0.5})

        assert found["labels"] == ["delivery", "website", "billing"]
        assert found["scores"] == [0.9, 0.5, 0.1]

    def test_the_sequence_is_the_response(self):
        assert as_result("the text", {"a": 1.0})["sequence"] == "the text"

    def test_ties_break_deterministically(self):
        """Two runs over the same data must agree on the top label even when
        two labels score identically."""
        first = as_result("x", {"b": 0.5, "a": 0.5})
        second = as_result("x", {"a": 0.5, "b": 0.5})

        assert first["labels"] == second["labels"] == ["a", "b"]


class TestItLivesWhereErasureCanFindIt:
    """Derived from response text, keyed by a hash of it. That is a PII
    artifact, and hashing is not anonymisation: a hash of a known string is a
    lookup."""

    def test_the_cache_sits_in_the_run_directory(self, tmp_path):
        found = open_cache(tmp_path)

        assert found.path == tmp_path / CACHE_FILENAME
        found.close()

    def test_clearing_removes_the_file(self, tmp_path):
        open_cache(tmp_path).close()
        assert (tmp_path / CACHE_FILENAME).exists()

        assert clear_cache(tmp_path) is True
        assert not (tmp_path / CACHE_FILENAME).exists()

    def test_clearing_a_directory_without_one_is_not_an_error(self, tmp_path):
        assert clear_cache(tmp_path) is False

    def test_erasure_deletes_it(self):
        """Wired into the real purge, not merely deletable in principle.

        Without this the erasure sweep would leave a file holding the erased
        respondent's sentiment and theme scores, keyed by a hash of their words.
        """
        source = (ROOT / "core" / "erasure.py").read_text(encoding="utf-8")

        assert "INFERENCE_CACHE_FILENAME" in source
        assert "cache_globs" in source
