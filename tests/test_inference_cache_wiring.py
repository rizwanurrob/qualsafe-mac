"""
The cache, in the code path that uses it — with a fake pipeline, so no download.

`tests/test_inference_cache.py` covers the store and the planner. This file
covers the part that can be wired up wrongly while every unit test still passes:
whether the model is actually spared, whether the answers survive the round
trip, and whether the untouched default path is still the untouched default
path.

Measured on the real models, 45 responses and six labels, **each run in its own
process** so that none inherits another's already-loaded model:

    cold                    106.9 s     3 models loaded
    warm (all cached)         4.4 s     0 models loaded
    one label added          41.4 s     1 model loaded (the NLI one)
    cache off (control)      98.4 s     3 models loaded

and the cached run's top labels and scores were identical to the control's,
which is the claim that matters more than any of the timings.

The per-process framing is not pedantry. Measured all four in one process, the
warm run looked like 2.5 s -- because run one had already loaded the models --
and that number hid a real defect: the cache skipped every inference and then
loaded a 1.6 GB NLI model it had no work for. See
`TestAFullyCachedRunNeverBuildsTheModel`.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import analyze_survey  # noqa: E402
from core.inference_cache import InferenceCache  # noqa: E402

LABELS = ["billing", "delivery", "website"]
TEXTS = ["the site kept timing out", "delivery was quick", "billed me twice"]


class FakePipeline:
    """Stands in for a Hugging Face zero-shot pipeline, and counts its work.

    `calls` records the candidate sets it was asked for, which is how the tests
    tell "served from cache" from "recomputed and happened to match".
    """

    def __init__(self, name="facebook/bart-large-mnli"):
        self.calls = []

        class _Config:
            name_or_path = name

        class _Model:
            config = _Config()

        self.model = _Model()

    def __call__(self, texts, candidate_labels, multi_label, batch_size):
        texts = [texts] if isinstance(texts, str) else list(texts)
        self.calls.append((tuple(texts), tuple(candidate_labels)))
        out = []
        for text in texts:
            # Deterministic, and different per (text, label) so a mixed-up
            # result is visible rather than coincidentally right.
            scores = [((len(text) * (i + 3)) % 97) / 100.0
                      for i, _ in enumerate(candidate_labels)]
            ordered = sorted(zip(candidate_labels, scores), key=lambda kv: -kv[1])
            out.append({"sequence": text,
                        "labels": [lab for lab, _ in ordered],
                        "scores": [s for _, s in ordered]})
        return out

    @property
    def texts_seen(self):
        return {text for texts, _ in self.calls for text in texts}

    @property
    def labels_seen(self):
        return {label for _, labels in self.calls for label in labels}


def run(zsc, cache, texts=TEXTS, labels=LABELS, multi_label=True):
    return analyze_survey.run_zero_shot_with_pipeline(
        zsc=zsc, texts=list(texts), labels=list(labels),
        multi_label=multi_label, batch_size=8, cache=cache)


@pytest.fixture
def cache(tmp_path):
    with InferenceCache(tmp_path / "c.sqlite") as found:
        yield found


class TestTheCachedRunGivesTheSameAnswer:
    """The only claim that would matter if the timings were the other way up."""

    def test_a_warm_run_matches_a_cold_one_exactly(self, cache):
        cold = run(FakePipeline(), cache)
        warm = run(FakePipeline(), cache)

        assert warm == cold

    def test_a_cached_run_matches_an_uncached_one_exactly(self, cache):
        uncached = run(FakePipeline(), None)
        run(FakePipeline(), cache)                       # populate
        cached = run(FakePipeline(), cache)

        assert cached == uncached

    def test_the_ordering_contract_survives_the_round_trip(self, cache):
        """Downstream reads labels[0] as the top label."""
        run(FakePipeline(), cache)
        warm = run(FakePipeline(), cache)

        for item in warm:
            assert item["scores"] == sorted(item["scores"], reverse=True)


class TestTheModelIsActuallySpared:
    """Otherwise this is a cache that stores things and saves nothing."""

    def test_a_fully_cached_run_never_calls_the_model(self, cache):
        run(FakePipeline(), cache)

        second = FakePipeline()
        run(second, cache)

        assert second.calls == []

    def test_adding_a_label_asks_only_for_that_label(self, cache):
        """The workflow this exists for. A codebook is iterated, not authored
        once, and re-coding everything is what stops people iterating."""
        run(FakePipeline(), cache)

        second = FakePipeline()
        run(second, cache, labels=LABELS + ["returns"])

        assert second.labels_seen == {"returns"}
        assert second.texts_seen == set(TEXTS)

    def test_adding_a_response_asks_only_for_that_response(self, cache):
        run(FakePipeline(), cache)

        second = FakePipeline()
        run(second, cache, texts=TEXTS + ["a new answer"])

        assert second.texts_seen == {"a new answer"}

    def test_a_resumed_run_keeps_what_the_dead_one_finished(self, tmp_path):
        """The interrupted long run. Two hours of work must not evaporate
        because a laptop slept."""
        path = tmp_path / "c.sqlite"
        with InferenceCache(path) as first:
            run(FakePipeline(), first, texts=TEXTS[:2])

        resumed = FakePipeline()
        with InferenceCache(path) as second:
            run(resumed, second, texts=TEXTS)

        assert resumed.texts_seen == {TEXTS[2]}


class TestSoftmaxModeIsCachedWholeOrNotAtAll:
    """Measured drift when the candidate set changes under multi_label=False was
    0.385. Reusing a label across sets would serve a number computed for a
    different question."""

    def test_a_repeat_run_is_still_cached(self, cache):
        cold = run(FakePipeline(), cache, multi_label=False)

        second = FakePipeline()
        warm = run(second, cache, multi_label=False)

        assert warm == cold
        assert second.calls == []

    def test_changing_the_label_set_recomputes_everything(self, cache):
        run(FakePipeline(), cache, multi_label=False)

        second = FakePipeline()
        run(second, cache, labels=LABELS + ["returns"], multi_label=False)

        assert second.texts_seen == set(TEXTS)
        assert second.labels_seen == set(LABELS) | {"returns"}

    def test_the_two_modes_do_not_serve_each_other(self, cache):
        """Same responses, same labels, genuinely different numbers."""
        run(FakePipeline(), cache, multi_label=True)

        second = FakePipeline()
        run(second, cache, multi_label=False)

        assert second.texts_seen == set(TEXTS)


class TestADifferentModelIsADifferentAnswer:

    def test_switching_models_does_not_reuse_the_old_scores(self, cache):
        run(FakePipeline("facebook/bart-large-mnli"), cache)

        other = FakePipeline("MoritzLaurer/deberta-v3-base-zeroshot")
        run(other, cache)

        assert other.texts_seen == set(TEXTS)


class TestTheUncachedPathIsUntouched:
    """v2.1 byte-identity is pinned elsewhere in the suite; this is the guard
    that the new parameter did not quietly change the default."""

    def test_no_cache_means_one_call_with_every_label(self):
        zsc = FakePipeline()

        run(zsc, None)

        assert zsc.calls == [(tuple(TEXTS), tuple(LABELS))]

    def test_a_disabled_cache_takes_the_uncached_path(self, tmp_path):
        from core.inference_cache import CACHE_FILENAME, open_cache

        (tmp_path / CACHE_FILENAME).mkdir()
        disabled = open_cache(tmp_path)
        zsc = FakePipeline()

        run(zsc, disabled)

        assert zsc.calls == [(tuple(TEXTS), tuple(LABELS))]

    def test_an_empty_label_list_still_raises(self, cache):
        with pytest.raises(ValueError):
            run(FakePipeline(), cache, labels=[])


class TestADuplicatedLabelDoesNotChangeTheShape:
    """A codebook with the same label twice is one copy-paste away. The cached
    path keys scores by label, so a duplicate would collapse into one entry --
    dropped explicitly rather than allowed to differ from the uncached path in
    silence."""

    def test_the_duplicate_is_dropped_not_scored_twice(self, cache):
        found = run(FakePipeline(), cache, labels=["a", "b", "a"])

        assert sorted(found[0]["labels"]) == ["a", "b"]
        assert len(found[0]["scores"]) == 2

    def test_it_says_so(self, cache, caplog):
        import logging

        with caplog.at_level(logging.WARNING):
            run(FakePipeline(), cache, labels=["a", "b", "a"])

        assert any("Duplicate labels" in r.message for r in caplog.records)


class TestAFullyCachedRunNeverBuildsTheModel:
    """Found by measuring rather than by reading.

    The first version of this cache skipped every inference and still spent 25.4
    seconds of a 25.4-second warm run loading a 1.6 GB NLI model it had no work
    for, because the pipeline was built eagerly as a call argument. In one
    process the cost was invisible -- an earlier run had already loaded it -- so
    the timing looked like 2.5 s and the claim "the models are never loaded" was
    written down before it was true.

    Fresh process, 45 responses, six labels, everything cached: 25.4 s before,
    **4.4 s** after, with no model loaded at all.
    """

    @staticmethod
    def _counted(built):
        def build():
            built.append(1)
            return FakePipeline()
        return build

    @staticmethod
    def _named(zsc, cache, labels=LABELS):
        """As the engine calls it: the builder plus the model's name.

        The name is what makes the skip possible. Without it the cache key
        cannot be formed without asking the pipeline, and asking the pipeline
        means building it -- so a caller that omits `model_id` pays the load
        even on a fully cached run.
        """
        return analyze_survey.run_zero_shot_with_pipeline(
            zsc=None, zsc_builder=zsc, texts=list(TEXTS), labels=list(labels),
            multi_label=True, batch_size=8, cache=cache,
            model_id="facebook/bart-large-mnli")

    def test_the_builder_is_not_called_when_there_is_nothing_to_do(self, cache):
        built = []
        build = self._counted(built)

        self._named(build, cache)             # cold: must build
        assert built == [1]

        self._named(build, cache)             # warm: must not
        assert built == [1]

    def test_it_still_builds_when_one_label_is_missing(self, cache):
        built = []
        build = self._counted(built)

        self._named(build, cache)
        self._named(build, cache, labels=LABELS + ["returns"])

        assert len(built) == 2

    def test_the_builder_is_called_at_most_once_per_run(self, cache):
        """Several label groups in one run must not each rebuild it."""
        built = []
        build = self._counted(built)

        self._named(build, cache, labels=LABELS[:1])
        run(FakePipeline(), cache, texts=TEXTS[:1], labels=LABELS)
        built.clear()

        # Response 0 is missing two labels, responses 1 and 2 are missing three:
        # two groups, one build.
        self._named(build, cache, labels=LABELS)

        assert built == [1]

    def test_a_named_model_needs_no_pipeline_to_key_the_cache(self, cache):
        """The chicken and egg: the key needs the model's identity, and asking
        the pipeline for it would mean building the pipeline."""
        cold = analyze_survey.run_zero_shot_with_pipeline(
            zsc=FakePipeline(), texts=list(TEXTS), labels=list(LABELS),
            multi_label=True, batch_size=8, cache=cache,
            model_id="facebook/bart-large-mnli")

        def explode():
            raise AssertionError("the model was built for a fully cached run")

        warm = analyze_survey.run_zero_shot_with_pipeline(
            zsc=None, zsc_builder=explode, texts=list(TEXTS),
            labels=list(LABELS), multi_label=True, batch_size=8, cache=cache,
            model_id="facebook/bart-large-mnli")

        assert warm == cold

    def test_a_named_model_agrees_with_what_the_pipeline_reports(self, cache):
        """Otherwise the two ways of naming the model would partition the cache
        in two and every run would miss."""
        from core.inference_cache import zero_shot_key

        assert (analyze_survey._pipeline_model_id(FakePipeline())
                == "facebook/bart-large-mnli")

    def test_an_already_built_pipeline_is_used_as_given(self):
        zsc = FakePipeline()

        assert analyze_survey._resolve_pipeline(zsc) is zsc

    def test_a_builder_is_used_when_there_is_no_pipeline(self):
        zsc = FakePipeline()

        assert analyze_survey._resolve_pipeline(None, lambda: zsc) is zsc

    def test_a_bare_function_is_a_pipeline_when_passed_as_one(self):
        """The defect the first version had. A pipeline is itself callable, so
        sniffing for callability called a test double's pipeline as though it
        were a builder -- caught by `test_pipeline.py`'s chunking test, which
        passes exactly that."""
        def looks_like_a_pipeline(texts, candidate_labels, multi_label, batch_size):
            return []

        assert (analyze_survey._resolve_pipeline(looks_like_a_pipeline)
                is looks_like_a_pipeline)

    def test_neither_one_is_an_error_rather_than_a_crash_later(self):
        with pytest.raises(ValueError):
            analyze_survey._resolve_pipeline(None, None)


class TestAResumeIsAnnounced:
    """A run that died at ninety minutes and silently restarts fast is good; one
    that says what it is skipping is honest. The analyst deciding whether to
    trust the output of a job they did not watch needs to be able to tell a
    resumed run from a run that did nothing."""

    def test_nothing_is_announced_on_a_cold_run(self, cache):
        said = []

        run_with = lambda: analyze_survey.run_zero_shot_with_pipeline(
            zsc=FakePipeline(), texts=list(TEXTS), labels=list(LABELS),
            multi_label=True, batch_size=8, cache=cache,
            resume_callback=lambda done, total: said.append((done, total)))

        run_with()

        assert said == []

    def test_a_partial_resume_reports_what_it_skipped(self, cache):
        run(FakePipeline(), cache, texts=TEXTS[:2])
        said = []

        analyze_survey.run_zero_shot_with_pipeline(
            zsc=FakePipeline(), texts=list(TEXTS), labels=list(LABELS),
            multi_label=True, batch_size=8, cache=cache,
            resume_callback=lambda done, total: said.append((done, total)))

        assert said == [(2, 3)]

    def test_a_missing_callback_is_not_an_error(self, cache):
        """The CLI passes none."""
        run(FakePipeline(), cache, texts=TEXTS[:2])

        assert len(run(FakePipeline(), cache)) == 3

    def test_the_pipeline_supplies_one(self):
        source = (ROOT / "analyze_survey.py").read_text(encoding="utf-8")

        assert '"resume_callback"' in source

    def test_the_notice_does_not_consume_a_stage(self):
        """`stage()` banks a stage and moves the bar. A resume notice is not a
        stage: using it here would overshoot the final fraction and shift
        `item_callback`'s base, mapping the coding stage's own sub-progress into
        the next stage's slice."""
        seen = []
        reporter = analyze_survey._ProgressReporter(
            lambda frac, msg: seen.append((round(frac, 3), msg)), 4)

        reporter.stage("one")
        reporter.note("Resuming - 90 of 100 already coded")
        reporter.stage("two")

        assert [msg for _, msg in seen] == [
            "one", "Resuming - 90 of 100 already coded", "two"]
        assert [frac for frac, _ in seen] == [0.0, 0.25, 0.25]

    def test_the_notice_still_reaches_the_interface(self):
        seen = []
        reporter = analyze_survey._ProgressReporter(
            lambda frac, msg: seen.append(msg), 3)

        reporter.note("Resuming")

        assert seen == ["Resuming"]

    def test_a_note_without_a_callback_is_not_an_error(self):
        """The CLI has none, and a broken progress bar must not lose a run."""
        analyze_survey._ProgressReporter(None, 3).note("Resuming")

    def test_the_engine_forwards_it(self):
        source = (ROOT / "engines" / "transformer_engine.py").read_text(
            encoding="utf-8")

        assert 'resume_callback=config.get("resume_callback")' in source


class TestSentimentToo:
    """Smaller than zero-shot -- 0.075 s/row against 1.44 -- but it is the same
    defect and the same fix, and at 5,000 responses it is still six minutes."""

    def test_a_second_run_does_not_call_the_model(self, cache, monkeypatch):
        calls = []

        def fake(texts, model_name, batch_size):
            calls.append(list(texts))
            return [{"label": "POSITIVE", "score": 0.9} for _ in texts]

        monkeypatch.setattr(analyze_survey, "_run_sentiment_uncached", fake)

        first = analyze_survey.run_sentiment(TEXTS, "distilbert", 8, cache=cache)
        second = analyze_survey.run_sentiment(TEXTS, "distilbert", 8, cache=cache)

        assert second == first
        assert len(calls) == 1

    def test_only_the_new_responses_are_scored(self, cache, monkeypatch):
        seen = []

        def fake(texts, model_name, batch_size):
            seen.extend(texts)
            return [{"label": "NEGATIVE", "score": 0.4} for _ in texts]

        monkeypatch.setattr(analyze_survey, "_run_sentiment_uncached", fake)
        analyze_survey.run_sentiment(TEXTS, "distilbert", 8, cache=cache)
        seen.clear()

        analyze_survey.run_sentiment(TEXTS + ["fresh"], "distilbert", 8, cache=cache)

        assert seen == ["fresh"]

    def test_the_order_of_the_answers_follows_the_texts(self, cache, monkeypatch):
        """A cached run reassembles the list; getting this wrong would attach
        every respondent's sentiment to a different respondent."""
        def fake(texts, model_name, batch_size):
            return [{"label": t.upper(), "score": 0.5} for t in texts]

        monkeypatch.setattr(analyze_survey, "_run_sentiment_uncached", fake)
        analyze_survey.run_sentiment(["a", "b"], "m", 8, cache=cache)

        found = analyze_survey.run_sentiment(["b", "a", "c"], "m", 8, cache=cache)

        assert [r["label"] for r in found] == ["B", "A", "C"]

    def test_without_a_cache_it_behaves_as_before(self, monkeypatch):
        calls = []

        def fake(texts, model_name, batch_size):
            calls.append(list(texts))
            return [{"label": "POSITIVE", "score": 0.9} for _ in texts]

        monkeypatch.setattr(analyze_survey, "_run_sentiment_uncached", fake)

        analyze_survey.run_sentiment(TEXTS, "distilbert", 8)
        analyze_survey.run_sentiment(TEXTS, "distilbert", 8)

        assert len(calls) == 2
