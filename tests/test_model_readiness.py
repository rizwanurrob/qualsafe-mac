"""
Does this machine have the models this run needs? Asked before the run, not during.

Pass 19's question was the first-run one: **what does somebody see the first
time, on a machine that has just installed this?** The models are not in the
installer — the payload is 487 MB and the zero-shot model alone is 1.6 GB — and
they are acquired in one explicit step, which is the privacy design and is
right. What was missing is the run asking, before it starts, whether that step
has happened.

Measured, with only the embedding model present and offline mode armed:

    the run got through embeddings and cluster discovery -- 9 progress steps,
    24.8 seconds on 45 responses -- and then failed at sentiment

and on the next attempt would have failed again at zero-shot, that time against
a 1.6 GB download. **Three failures, each after more waiting**, because each
model was checked only when its own stage first touched it.
`core.offline.model_cache_status` knew all three answers before the run began;
nothing asked it.

Worse than the timing was the advice. The message named
`python tools/download_models.py`, a "Model status panel on the Run Analysis
page", and a README section — **three remedies, all of them Streamlit's**,
shown to desktop users who have no shell, no page by that name (it is the
**Models** tab) and no README they can find. That is the same defect the
encoding warning had in v4.8.1: correct advice delivered to the build that
cannot follow it, and the installed desktop app is what a first user is most
likely to be holding.

After the fix, the same partial cache stops the run immediately, names both
missing models at once, and writes nothing.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import model_readiness  # noqa: E402
from core.model_readiness import (  # noqa: E402
    DEFAULT_REMEDY, ModelsNotReadyError, as_config, check_models_ready,
    describe_missing, missing_models, models_for_run, remedy, set_remedy)

EMBED = "sentence-transformers/all-MiniLM-L6-v2"
SENTIMENT = "distilbert/distilbert-base-uncased-finetuned-sst-2-english"
ZERO_SHOT = "facebook/bart-large-mnli"


def config(sentiment=True, zero_shot=True, question_zero_shot=False, **models):
    base = {"embedding_model": EMBED, "sentiment_model": SENTIMENT,
            "zero_shot_model": ZERO_SHOT}
    base.update(models)
    return {
        "models": base,
        "sentiment": {"enabled": sentiment},
        "zero_shot": {"enabled": zero_shot},
        "question_zero_shot": {"enabled": question_zero_shot},
    }


@pytest.fixture
def cache_says(monkeypatch):
    """Pretend the model cache holds exactly the models named."""
    def install(*present):
        def fake(model_names):
            return [{"model": name, "cached": name in present,
                     "size_bytes": 0, "detail": ""} for name in model_names]
        monkeypatch.setattr("core.offline.model_cache_status", fake)
    return install


@pytest.fixture(autouse=True)
def restore_remedy():
    """The remedy is module state that front ends set at import. Tests that
    change it must not leak into the ones that read it."""
    original = remedy()
    yield
    set_remedy(original)


class TestARunNeedsOnlyWhatItWillReach:

    def test_a_full_run_needs_all_three(self):
        assert [m for _role, m in models_for_run(config())] == [
            EMBED, SENTIMENT, ZERO_SHOT]

    def test_sentiment_off_drops_the_sentiment_model(self):
        assert SENTIMENT not in [m for _r, m in models_for_run(
            config(sentiment=False))]

    def test_theme_coding_off_drops_the_zero_shot_model(self):
        assert [m for _r, m in models_for_run(
            config(sentiment=False, zero_shot=False))] == [EMBED]

    def test_question_level_coding_alone_still_needs_it(self):
        """A different stage, the same model."""
        found = models_for_run(config(zero_shot=False, question_zero_shot=True))

        assert ZERO_SHOT in [m for _r, m in found]

    def test_embeddings_are_always_needed(self):
        """Every path clusters, and clustering needs vectors."""
        assert models_for_run(config(sentiment=False, zero_shot=False))

    def test_one_model_serving_two_roles_is_named_once(self):
        """Saying the same download twice reads like a bug."""
        found = models_for_run(config(sentiment_model=EMBED))

        assert [m for _r, m in found].count(EMBED) == 1

    def test_they_come_back_in_the_order_the_run_would_hit_them(self):
        """So a partial download is reported in the order it will bite."""
        roles = [role for role, _m in models_for_run(config())]

        assert roles == ["embedding", "sentiment", "theme coding"]


class TestTheLlmEngineStillNeedsTheFallbackModel:
    """`engines/factory.py` falls back to the transformer engine whenever Ollama
    is unreachable or the model is not pulled, and its contract is that "the
    survey pipeline must always be able to complete". A fallback that cannot
    fall back is not one."""

    def test_an_llm_run_still_requires_the_zero_shot_model(self):
        llm = config()
        llm["engine"] = {"type": "llm", "llm": {"model": "llama3.2:3b"}}

        assert ZERO_SHOT in [m for _r, m in models_for_run(llm)]

    def test_the_factory_still_falls_back(self):
        """If this stops being true the requirement above should be revisited."""
        source = (ROOT / "engines" / "factory.py").read_text(encoding="utf-8")

        assert "falling back to the transformer engine" in source


class TestItReportsWhatIsAbsent:

    def test_nothing_missing_when_everything_is_cached(self, cache_says):
        cache_says(EMBED, SENTIMENT, ZERO_SHOT)

        assert missing_models(config()) == []
        assert describe_missing(config()) is None

    def test_it_names_every_missing_model_at_once(self, cache_says):
        """The whole point. One report, not one failure per stage."""
        cache_says(EMBED)

        assert [m for _r, m in missing_models(config())] == [SENTIMENT, ZERO_SHOT]

    def test_a_model_that_is_not_needed_is_not_missed(self, cache_says):
        cache_says(EMBED, SENTIMENT)

        assert missing_models(config(zero_shot=False)) == []

    def test_an_unreadable_cache_reports_nothing_missing(self, monkeypatch):
        """Deliberate. This gate exists to spare somebody a wasted wait, not to
        become a new way for a run to be refused; the per-model error at point
        of use still catches a genuine absence."""
        def unreadable(model_names):
            return [{"model": n, "cached": None, "size_bytes": 0,
                     "detail": "cache unreadable"} for n in model_names]

        monkeypatch.setattr("core.offline.model_cache_status", unreadable)

        assert missing_models(config()) == []


class TestTheRunStopsBeforeItStarts:

    def test_it_raises_when_something_is_missing(self, cache_says):
        cache_says(EMBED)

        with pytest.raises(ModelsNotReadyError) as caught:
            check_models_ready(config())

        assert len(caught.value.missing) == 2

    def test_it_does_not_raise_when_everything_is_there(self, cache_says):
        cache_says(EMBED, SENTIMENT, ZERO_SHOT)

        check_models_ready(config())

    def test_the_message_names_the_models(self, cache_says):
        cache_says(EMBED)

        with pytest.raises(ModelsNotReadyError) as caught:
            check_models_ready(config())

        assert SENTIMENT in str(caught.value)
        assert ZERO_SHOT in str(caught.value)

    def test_the_message_says_nothing_was_touched(self, cache_says):
        """A first user's first thought on seeing an error mid-analysis is
        whether their data survived it."""
        cache_says(EMBED)

        with pytest.raises(ModelsNotReadyError) as caught:
            check_models_ready(config())

        assert "no data has been touched" in str(caught.value)

    def test_both_plurals_read_as_english(self):
        one = str(ModelsNotReadyError([("sentiment", SENTIMENT)]))
        two = str(ModelsNotReadyError([("sentiment", SENTIMENT),
                                       ("theme coding", ZERO_SHOT)]))

        assert one.startswith("One language model this analysis needs is not")
        assert two.startswith("2 language models this analysis needs are not")

    def test_the_check_runs_before_anything_is_written(self):
        """The output directory must not exist after a refused run. The comment
        in `run_pipeline` claims this; an earlier draft placed the check after
        `ensure_output_dir` and the claim was false."""
        source = (ROOT / "analyze_survey.py").read_text(encoding="utf-8")
        preflight = source.index("check_models_ready(config)")
        make_dir = source.index("ensure_output_dir(output_dir)", preflight - 4000)

        assert preflight < make_dir, (
            "the readiness check must precede the first filesystem write")


class TestTheAdviceMatchesTheBuildTheUserIsIn:
    """The half of this that was actually wrong rather than merely late."""

    def test_the_default_is_the_command_line_one(self):
        assert "tools/download_models.py" in DEFAULT_REMEDY

    def test_a_front_end_can_replace_it(self):
        set_remedy("Open the Models tab and press Download.")

        assert remedy() == "Open the Models tab and press Download."

    def test_the_error_carries_whatever_is_set(self, cache_says):
        cache_says(EMBED)
        set_remedy("Open the Models tab and press Download.")

        with pytest.raises(ModelsNotReadyError) as caught:
            check_models_ready(config())

        assert "Models tab" in str(caught.value)

    @staticmethod
    def _registered_remedy(path: Path) -> str:
        """The string the file actually passes to `set_remedy`.

        Read out of the parsed tree rather than grepped. `qualsafe_qt/main.py`
        mentions `tools/download_models.py` in its module docstring, as an
        architectural note about why offline mode is armed where it is -- so a
        grep for that path matches the prose explaining the design and not the
        advice being asserted on. This project has been caught by that twice.
        """
        import ast

        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "set_remedy"
                    and node.args
                    and isinstance(node.args[0], ast.Constant)):
                return str(node.args[0].value)
        raise AssertionError(f"{path.name} never calls set_remedy")

    def test_the_desktop_registers_its_own(self):
        """A desktop user has no shell, and the page is not called
        'Run Analysis' there -- it is the Models tab."""
        advice = self._registered_remedy(ROOT / "qualsafe_qt" / "main.py")

        assert "Settings, then Models" in advice
        assert "python" not in advice, "a desktop user has no shell"
        assert "README" not in advice

    def test_the_streamlit_app_registers_its_own(self):
        advice = self._registered_remedy(ROOT / "app" / "__init__.py")

        assert "Settings, then Models" in advice

    def test_the_two_builds_do_not_give_the_same_advice(self):
        """If they ever do, one of them is wrong -- which is how this started."""
        assert (self._registered_remedy(ROOT / "qualsafe_qt" / "main.py")
                != self._registered_remedy(ROOT / "app" / "__init__.py"))

    def test_each_front_end_sets_it_before_anything_can_raise(self):
        """Registered at import of the package every entry point goes through,
        for the same reason offline mode is armed there."""
        for path in (ROOT / "qualsafe_qt" / "main.py",
                     ROOT / "app" / "__init__.py"):
            source = path.read_text(encoding="utf-8")
            assert (source.index("set_remedy(")
                    > source.index("enforce_local_mode()")), path.name


class TestItAcceptsEitherShapeOfSettings:
    """The two front ends hold a run's choices differently, and asking which
    models it needs should not require building a forty-key config."""

    def test_a_run_settings_object_works(self):
        from core.run_config import RunSettings

        found = models_for_run(RunSettings(use_sentiment=True, use_zero_shot=True))

        assert [m for _r, m in found] == [EMBED, SENTIMENT, ZERO_SHOT]

    def test_its_switches_are_honoured(self):
        from core.run_config import RunSettings

        found = models_for_run(
            RunSettings(use_sentiment=False, use_zero_shot=False))

        assert [m for _r, m in found] == [EMBED]

    def test_question_level_themes_need_no_extra_model(self):
        """`use_question_theme` is embedding-based; only the zero-shot variant
        pulls in the NLI model."""
        from core.run_config import RunSettings

        found = models_for_run(RunSettings(
            use_sentiment=False, use_zero_shot=False, use_question_theme=True))

        assert [m for _r, m in found] == [EMBED]

    def test_a_dict_is_passed_through_unchanged(self):
        given = config()

        assert as_config(given) is given


class TestBothFrontEndsSayItBeforeTheRun:

    def test_the_desktop_lists_it_as_a_blocker(self):
        source = (ROOT / "qualsafe_qt" / "views"
                  / "pipeline_view.py").read_text(encoding="utf-8")

        assert "_missing_models" in source
        assert "describe_missing" in source

    def test_the_streamlit_page_warns_next_to_the_estimate(self):
        source = (ROOT / "app" / "run_analysis.py").read_text(encoding="utf-8")

        assert "_warn_about_missing_models" in source
        assert source.index("_warn_about_missing_models()") < source.index(
            "Estimated time on an ordinary computer")

    def test_the_desktop_check_never_breaks_the_screen(self):
        """A cache that cannot be read must not stop somebody configuring a
        run."""
        source = (ROOT / "qualsafe_qt" / "views"
                  / "pipeline_view.py").read_text(encoding="utf-8")
        block = source[source.index("def _missing_models"):]

        assert "except Exception" in block[:900]


class TestTheDescriptionReadsAsAnInstruction:

    def test_one_missing_model_names_it(self, cache_says):
        cache_says(EMBED, ZERO_SHOT)

        assert describe_missing(config()) == (
            f"download the sentiment model ({SENTIMENT})")

    def test_several_are_counted_and_listed(self, cache_says):
        cache_says(EMBED)

        found = describe_missing(config())

        assert found.startswith("download 2 language models")
        assert SENTIMENT in found and ZERO_SHOT in found
