#!/usr/bin/env python
"""
Deviant-case analysis: the responses that carry a code but do not look like it.

Finding and accounting for the cases that contradict the emerging pattern is
standard qualitative rigor and standard qualitative drudgery. Done by hand it
means re-reading everything, so in practice it is done thinly or asserted.

This project has sentence embeddings for every response, which no other package
in this market has. That makes one specific question cheap to answer: **of the
responses coded X, which sit furthest from what "coded X" usually looks like?**
Those are the ones worth re-reading — the genuine outliers, and, just as
usefully, the miscodings.

It is the first capability here that is not catching up with anyone. NVivo,
MAXQDA, ATLAS.ti and Dedoose cannot offer it, not because they did not think of
it but because they do not hold the vectors.

Design decisions
----------------
- **It proposes cases to read. It does not classify them as deviant.** Distance
  from a centroid is a property of the embedding, not a finding about the data,
  and a response can sit far out because it is genuinely atypical, because it is
  miscoded, because it is short, or because it is about something else entirely.
  All four are worth a human's attention and only a human can tell them apart.
  So this returns a **reading order**, never a label, and nothing it produces is
  written into the project.

- **The centroid is of the coded responses, not of the code's definition.** What
  the code *means to this analyst in this project* is expressed by what they
  applied it to. Embedding the definition instead would measure distance from the
  words in the codebook, which is a different and much less useful question.

- **A code with too few applications gets a refusal, not a ranking.** With four
  responses the centroid is barely distinguishable from any of them, and the
  "most deviant" of four is noise wearing a number. The threshold is stated and
  the caller is told why.

- **Cosine distance, on normalised vectors.** The pipeline normalises its
  embeddings, so cosine is the metric the rest of the project already thinks in,
  and it ignores the length differences that Euclidean distance would read as
  meaning.

- **Torch stays out of the import path.** `analysis/` is imported by the test
  suite and by the lite install, neither of which has the model stack. The
  embedding call is lazy, exactly as `analysis/code_similarity.py` does it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

import numpy as np

#: Below this many coded responses, a ranking is noise wearing a number: the
#: centroid of four points sits close to all four, and "furthest" means nothing.
MIN_APPLICATIONS = 8

#: How much of the code's own responses to offer for re-reading. A list of forty
#: is another corpus; a list of five is a morning's work.
DEFAULT_TOP_N = 5


@dataclass(frozen=True)
class Candidate:
    """One response proposed for re-reading, with the reason it was proposed."""

    source_id: str
    excerpt_id: str
    text: str
    #: Cosine distance from the centroid of everything else coded this way.
    #: Higher means less typical. It is a coordinate, not a verdict.
    distance: float
    #: Where it sits in the code's own spread, 0.0 (most typical) to 1.0.
    position: float

    def why(self) -> str:
        """One sentence a person can weigh, without a number pretending to rank."""
        if self.position >= 0.95:
            return "Furthest from how this code usually reads."
        if self.position >= 0.8:
            return "Well outside the usual range for this code."
        return "Somewhat outside the usual range for this code."


@dataclass(frozen=True)
class DeviantReport:
    """A reading order for one code, and what qualifies it."""

    code_name: str
    considered: int
    candidates: List[Candidate]
    #: Set when no ranking was produced, saying why in a sentence.
    refusal: str = ""

    @property
    def usable(self) -> bool:
        return not self.refusal and bool(self.candidates)

    def caveats(self) -> List[str]:
        """What has to be said alongside a list like this."""
        notes = [
            "These are responses to re-read, not responses the program has "
            "judged deviant. A response sits far out because it is genuinely "
            "atypical, because it is miscoded, because it is very short, or "
            "because it is about something else. Only reading it tells you which.",
            "Distance is measured from the other responses you coded this way, "
            "so it reflects how you have used the code in this project rather "
            "than what the codebook says it means.",
        ]
        if self.considered < 20:
            notes.append(
                f"Only {self.considered} responses carry this code, so the "
                "centroid they define is not very stable. Treat the order as a "
                "suggestion rather than a ranking.")
        return notes


def find_deviant_cases(
    texts: Sequence[str],
    identifiers: Sequence[Any],
    *,
    code_name: str,
    top_n: int = DEFAULT_TOP_N,
    embed=None,
) -> DeviantReport:
    """Rank coded responses by distance from their own centroid.

    `texts` and `identifiers` are parallel: one entry per response carrying the
    code. `embed` takes the texts and returns a 2-D array, and is injected so
    this function is testable without the model stack — the default resolves
    lazily to the project's own embedder.

    Each response is compared against the centroid of **the others**, not of the
    whole set. Including a response in the mean it is measured against pulls that
    mean towards it, which flatters exactly the outliers this is looking for.
    """
    if len(texts) != len(identifiers):
        raise ValueError("texts and identifiers must be the same length")

    considered = len(texts)
    if considered < MIN_APPLICATIONS:
        return DeviantReport(
            code_name=code_name, considered=considered, candidates=[],
            refusal=(
                f"“{code_name}” is on {considered} response(s). Below "
                f"{MIN_APPLICATIONS} the centre of a code is too close to every "
                "response for distance from it to mean anything, so no order is "
                "offered. Code a few more and come back."))

    vectors = np.asarray((embed or _default_embed)(list(texts)), dtype=float)
    if vectors.ndim != 2 or vectors.shape[0] != considered:
        raise ValueError("the embedder returned an unexpected shape")

    vectors = _normalise(vectors)
    total = vectors.sum(axis=0)

    distances = np.empty(considered, dtype=float)
    for index in range(considered):
        # Leave-one-out: a response must not vote on the centre it is measured
        # against, or the furthest ones flatter themselves.
        others = (total - vectors[index]) / (considered - 1)
        norm = np.linalg.norm(others)
        centre = others / norm if norm else others
        distances[index] = 1.0 - float(np.dot(vectors[index], centre))

    order = np.argsort(-distances)
    span = float(distances.max() - distances.min()) or 1.0
    low = float(distances.min())

    candidates = [
        Candidate(
            source_id=str(getattr(identifiers[i], "source_id", identifiers[i])),
            excerpt_id=str(getattr(identifiers[i], "excerpt_id", "")),
            text=texts[i],
            distance=float(distances[i]),
            position=(float(distances[i]) - low) / span,
        )
        for i in order[:max(1, top_n)]
    ]
    return DeviantReport(code_name=code_name, considered=considered,
                         candidates=candidates)


def coded_responses(project, code_name: str) -> Dict[str, List[Any]]:
    """The text and identity of every excerpt carrying `code_name`.

    Returns ``{"texts": [...], "identifiers": [...]}``. Excerpt text is read from
    the store rather than reconstructed, so what is ranked is what was coded.
    """
    coding = project.coding_table()
    if coding.empty or "code_name" not in coding.columns:
        return {"texts": [], "identifiers": []}

    wanted = coding[coding["code_name"] == code_name]
    excerpts = {e.excerpt_id: e for e in project.list_excerpts()}

    texts: List[str] = []
    identifiers: List[Any] = []
    for excerpt_id in dict.fromkeys(wanted["excerpt_id"].astype(str)):
        excerpt = excerpts.get(excerpt_id)
        if excerpt is None or not (excerpt.text or "").strip():
            continue
        texts.append(excerpt.text)
        identifiers.append(excerpt)
    return {"texts": texts, "identifiers": identifiers}


def _normalise(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return vectors / norms


def _default_embed(texts: List[str]) -> np.ndarray:
    """The project's own embedder, imported at call time.

    `analysis/` is imported by the test suite and by the lite install, neither of
    which has torch. Importing it at module scope would make this file
    unimportable in both.
    """
    from analysis.code_similarity import embed_with_model
    from core.model_manager import DEFAULT_MODELS

    return embed_with_model(texts, DEFAULT_MODELS["embedding"])
