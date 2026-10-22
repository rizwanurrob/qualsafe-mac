#!/usr/bin/env python
"""
Are the language models this run needs actually on this machine? (v4.10, Pass 19)

The tool downloads models in one explicit, user-initiated step and then runs
with the Hugging Face hub pinned to the local cache (`core/offline.py`). That is
the right design and it is the privacy guarantee. What was missing is the
question a run should ask *before* it starts: **do I have what I need?**

Measured on a machine holding only the embedding model, with the other two
absent — which is exactly a first user who ran the download and interrupted it,
or who installed the desktop build and never opened the Models tab:

    the run reached 9 progress steps and 24.8 seconds on 45 responses,
    through embeddings and cluster discovery, and then failed at sentiment

and would have failed again at zero-shot after the next attempt, that time
against a 1.6 GB download. **Three failures, each after more waiting**, because
each model is only checked when it is first touched. On 45 responses that is
half a minute; on the five thousand this tool is for, the second failure lands
after the sentiment stage has run for six minutes.

`core.offline.model_cache_status` already knew all three answers before the run
started. Nothing asked it. This module asks.

Which models a run needs
------------------------
Only the ones its configuration will actually reach — sentiment is skipped when
sentiment is off, and so on. One deliberate exception: **the zero-shot model is
required whenever theme coding is enabled, even for a run configured to use the
local LLM engine.** `engines/factory.py` falls back to the transformer engine
whenever Ollama is unreachable or the model is not pulled, and its own contract
is that "the survey pipeline must always be able to complete". A fallback that
cannot fall back is not one.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

ROLE_EMBEDDING = "embedding"
ROLE_SENTIMENT = "sentiment"
ROLE_ZERO_SHOT = "theme coding"

#: What the CLI says. Front ends replace it with something their user can act
#: on — see `set_remedy`.
DEFAULT_REMEDY = (
    "Run the one-time model setup. It downloads model weights (it sends none of your "
    "text) and needs the analysis engine installed first:\n"
    "    python tools/download_models.py"
)

_remedy: str = DEFAULT_REMEDY


def set_remedy(text: str) -> None:
    """Tell this module how *this* build's user downloads a model.

    This exists because the advice was wrong for half the users. The message
    named `python tools/download_models.py`, the "Model status panel on the Run
    Analysis page", and a README section — three remedies, all of them
    Streamlit's. A desktop user has no shell, no page by that name (it is the
    **Models** tab), and no README they can find. It was the same defect the
    encoding warning had in v4.8.1: correct advice, delivered to the build that
    cannot follow it, and the desktop is the build a first user is most likely
    to be holding.
    """
    global _remedy
    _remedy = text


def remedy() -> str:
    """How the user of this build gets the missing models."""
    return _remedy


class ModelsNotReadyError(RuntimeError):
    """One or more models a run needs are not in the local cache.

    Raised once, naming every missing model, rather than once per model as each
    stage reaches it. The difference is between telling somebody what the job
    needs and letting them discover it three waits later.
    """

    def __init__(self, missing: Sequence[Tuple[str, str]]):
        self.missing = list(missing)
        listed = "\n".join(f"    {model}  ({role})" for role, model in missing)
        subject = ("One language model this analysis needs is"
                   if len(missing) == 1
                   else f"{len(missing)} language models this analysis needs are")
        super().__init__(
            f"{subject} not on this machine:\n\n{listed}\n\n"
            f"Nothing has been run and no data has been touched.\n\n{remedy()}"
        )


def as_config(source: Any) -> Dict[str, Any]:
    """Accept either a pipeline config dict or a `RunSettings`.

    The two front ends hold the run's choices in different shapes, and the
    question "which models does this need" should not require building a
    forty-key config just to be asked. Only the keys this module reads are
    filled in.
    """
    if isinstance(source, dict):
        return source
    return {
        "models": {
            "embedding_model": getattr(source, "embedding_model", ""),
            "sentiment_model": getattr(source, "sentiment_model", ""),
            "zero_shot_model": getattr(source, "zero_shot_model", ""),
        },
        "sentiment": {"enabled": bool(getattr(source, "use_sentiment", True))},
        "zero_shot": {"enabled": bool(getattr(source, "use_zero_shot", False))},
        # `use_question_theme` is embedding-based, so it needs no model of its
        # own; only the zero-shot variant does.
        "question_zero_shot": {
            "enabled": bool(getattr(source, "use_question_zero_shot", False))},
    }


def models_for_run(config: Dict[str, Any]) -> List[Tuple[str, str]]:
    """The (role, model id) pairs this configuration will actually reach.

    In the order the run would hit them, so a partial download is reported in
    the order it will bite. Deduplicated on model id: one model serving two
    roles is one download, and saying it twice reads like a bug.
    """
    config = as_config(config)
    models = config.get("models", {}) or {}
    wanted: List[Tuple[str, str]] = [
        (ROLE_EMBEDDING, models.get("embedding_model",
                                    "sentence-transformers/all-MiniLM-L6-v2")),
    ]

    if (config.get("sentiment", {}) or {}).get("enabled", True):
        wanted.append((ROLE_SENTIMENT, models.get("sentiment_model", "")))

    zero_shot_on = bool((config.get("zero_shot", {}) or {}).get("enabled", False))
    question_on = bool((config.get("question_zero_shot", {}) or {}).get("enabled", False))
    if zero_shot_on or question_on:
        # Required even under engine.type == "llm": see the module docstring.
        wanted.append((ROLE_ZERO_SHOT, models.get("zero_shot_model",
                                                  "facebook/bart-large-mnli")))

    seen = set()
    ordered: List[Tuple[str, str]] = []
    for role, model in wanted:
        if model and model not in seen:
            seen.add(model)
            ordered.append((role, model))
    return ordered


def missing_models(config: Dict[str, Any]) -> List[Tuple[str, str]]:
    """The models this run needs and does not have.

    A cache this cannot read reports nothing missing. That is deliberate: this
    gate's job is to spare somebody a wasted wait, not to become a new way for a
    run to be refused. If the cache is unreadable the run proceeds and the
    existing per-model error still catches a genuine absence at point of use.
    """
    from core.offline import model_cache_status

    wanted = models_for_run(as_config(config))
    status = {row["model"]: row["cached"]
              for row in model_cache_status([model for _role, model in wanted])}
    return [(role, model) for role, model in wanted if status.get(model) is False]


def check_models_ready(config: Dict[str, Any]) -> None:
    """Raise `ModelsNotReadyError` if anything this run needs is absent.

    Called before the first stage, so a run either starts or explains itself.
    """
    missing = missing_models(config)
    if missing:
        raise ModelsNotReadyError(missing)


def describe_missing(config: Dict[str, Any]) -> Optional[str]:
    """A one-line summary for a UI that lists what stands between here and a run.

    None when nothing is missing, so a caller can treat it as one more entry in
    a list of blockers.
    """
    missing = missing_models(config)
    if not missing:
        return None
    if len(missing) == 1:
        return f"download the {missing[0][0]} model ({missing[0][1]})"
    return (f"download {len(missing)} language models: "
            + ", ".join(model for _role, model in missing))
