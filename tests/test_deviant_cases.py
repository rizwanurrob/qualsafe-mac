"""
Deviant-case analysis (v4.6, `V5_PLAN.md` §B6).

The first capability here that is not catching up with anyone. NVivo, MAXQDA,
ATLAS.ti and Dedoose cannot offer it — not for want of the idea, but because
they do not hold sentence embeddings for every response.

Two things are under test, and the second is the one that keeps the feature
honest.

**The ranking is right.** A response planted to be unlike the others has to come
out at the top, and the leave-one-out centroid has to be what makes that
possible: a response that votes on the mean it is measured against flatters
itself, which would suppress exactly the outliers this exists to surface.

**It refuses when it cannot know.** Below a handful of applications, the centre
of a code sits close to every response and "furthest" is noise wearing a number.
The refusal is a sentence, not an empty list.

The embedder is injected throughout, so none of this needs the model stack.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analysis.deviant_cases import (
    DEFAULT_TOP_N, MIN_APPLICATIONS, coded_responses, find_deviant_cases)
from core.model import Code, CodeApplication, Excerpt, Source
from core.project import Project


def fake_embed(texts):
    """A stand-in embedder with a planted outlier.

    Everything starting "typical" lands in one tight cluster; anything else is
    put somewhere else entirely. That makes the expected answer knowable without
    a model, which is the point — a test that needed torch would not run in the
    lite install or in CI.
    """
    vectors = []
    for text in texts:
        if text.startswith("typical"):
            jitter = (len(text) % 5) * 0.01
            vectors.append([1.0, jitter, 0.0])
        elif text.startswith("odd"):
            vectors.append([0.0, 1.0, 0.0])
        else:
            vectors.append([0.0, 0.0, 1.0])
    return np.array(vectors, dtype=float)


def _texts(typical: int, odd: int = 0, other: int = 0):
    return ([f"typical response {i}" for i in range(typical)]
            + [f"odd one out {i}" for i in range(odd)]
            + [f"another thing {i}" for i in range(other)])


class TestTheRanking:

    def test_the_planted_outlier_comes_first(self):
        texts = _texts(12, odd=1)

        report = find_deviant_cases(texts, list(range(len(texts))),
                                    code_name="Cost", embed=fake_embed)

        assert report.usable
        assert report.candidates[0].text.startswith("odd")

    def test_a_typical_response_is_not_proposed_first(self):
        texts = _texts(12, odd=1)
        report = find_deviant_cases(texts, list(range(len(texts))),
                                    code_name="Cost", embed=fake_embed)
        assert not report.candidates[0].text.startswith("typical")

    def test_the_centroid_leaves_the_response_out(self):
        """A response that votes on the mean it is measured against pulls that
        mean towards itself, which suppresses the outliers this exists to find.

        With two unlike responses out of fourteen, an including-self centroid
        would drag both toward the middle; leave-one-out keeps them at the top.
        """
        texts = _texts(12, odd=2)

        report = find_deviant_cases(texts, list(range(len(texts))),
                                    code_name="Cost", top_n=2, embed=fake_embed)

        assert all(c.text.startswith("odd") for c in report.candidates)

    def test_it_returns_at_most_the_number_asked_for(self):
        texts = _texts(20, odd=3)
        report = find_deviant_cases(texts, list(range(len(texts))),
                                    code_name="Cost", top_n=4, embed=fake_embed)
        assert len(report.candidates) == 4

    def test_the_default_is_a_mornings_work_not_another_corpus(self):
        assert DEFAULT_TOP_N <= 6

    def test_position_runs_from_zero_to_one_across_the_spread(self):
        texts = _texts(12, odd=1)
        report = find_deviant_cases(texts, list(range(len(texts))),
                                    code_name="Cost", top_n=len(texts),
                                    embed=fake_embed)

        positions = [c.position for c in report.candidates]
        assert positions[0] == pytest.approx(1.0)
        assert min(positions) == pytest.approx(0.0)

    def test_identical_responses_do_not_crash_the_spread(self):
        """Every distance equal means a zero span, and a naive normalisation
        divides by it."""
        texts = ["typical response"] * 10

        report = find_deviant_cases(texts, list(range(10)), code_name="Cost",
                                    embed=fake_embed)

        assert report.usable
        assert all(0.0 <= c.position <= 1.0 for c in report.candidates)


class TestItRefusesWhenItCannotKnow:

    def test_too_few_applications_gets_a_sentence_not_an_empty_list(self):
        texts = _texts(3)

        report = find_deviant_cases(texts, [1, 2, 3], code_name="Cost",
                                    embed=fake_embed)

        assert not report.usable
        assert "Cost" in report.refusal
        assert str(MIN_APPLICATIONS) in report.refusal

    def test_the_refusal_says_what_to_do_about_it(self):
        report = find_deviant_cases(["typical a"], [1], code_name="Cost",
                                    embed=fake_embed)
        assert "Code a few more" in report.refusal

    def test_no_code_is_ranked_below_the_threshold(self):
        for count in range(1, MIN_APPLICATIONS):
            report = find_deviant_cases(_texts(count), list(range(count)),
                                        code_name="Cost", embed=fake_embed)
            assert not report.usable, f"{count} responses should not be ranked"

    def test_mismatched_inputs_are_refused_loudly(self):
        with pytest.raises(ValueError, match="same length"):
            find_deviant_cases(["a", "b"], [1], code_name="Cost", embed=fake_embed)

    def test_a_misbehaving_embedder_is_caught(self):
        with pytest.raises(ValueError, match="unexpected shape"):
            find_deviant_cases(_texts(10), list(range(10)), code_name="Cost",
                               embed=lambda t: np.zeros((3, 3)))


class TestItProposesRatherThanJudges:
    """Distance from a centroid is a property of the embedding, not a finding
    about the data. Everything user-facing here has to say so."""

    def test_nothing_is_labelled_deviant(self):
        texts = _texts(12, odd=1)
        report = find_deviant_cases(texts, list(range(len(texts))),
                                    code_name="Cost", embed=fake_embed)

        blob = " ".join(c.why() for c in report.candidates).lower()
        assert "deviant" not in blob
        assert "wrong" not in blob and "error" not in blob

    def test_the_reason_describes_position_not_verdict(self):
        texts = _texts(12, odd=1)
        report = find_deviant_cases(texts, list(range(len(texts))),
                                    code_name="Cost", embed=fake_embed)
        assert "usually reads" in report.candidates[0].why()

    def test_the_caveats_name_all_four_reasons_a_response_sits_far_out(self):
        texts = _texts(12, odd=1)
        report = find_deviant_cases(texts, list(range(len(texts))),
                                    code_name="Cost", embed=fake_embed)

        blob = " ".join(report.caveats()).lower()
        for reason in ("atypical", "miscoded", "short", "something else"):
            assert reason in blob, f"the caveats do not mention {reason}"

    def test_a_small_code_says_the_centroid_is_unstable(self):
        texts = _texts(10)
        report = find_deviant_cases(texts, list(range(10)), code_name="Cost",
                                    embed=fake_embed)
        assert any("not very stable" in note for note in report.caveats())

    def test_the_caveats_say_it_reflects_this_analysts_usage(self):
        """Not what the codebook says the code means."""
        texts = _texts(30)
        report = find_deviant_cases(texts, list(range(30)), code_name="Cost",
                                    embed=fake_embed)
        assert any("how you have used the code" in n for n in report.caveats())


class TestReadingFromAProject:

    @pytest.fixture()
    def project(self, tmp_path):
        path = tmp_path / "p.qnw"
        with Project.create(path) as project:
            code = project.add_code(Code(code_id="", name="Cost"))
            other = project.add_code(Code(code_id="", name="Belonging"))
            for index in range(10):
                text = f"typical response {index}"
                source_id = project.add_source(Source(
                    source_id="", type="survey_response", raw_text=text,
                    label="Q1", metadata={"response_id": f"r{index}"}))
                excerpt = project.add_excerpt(Excerpt(
                    excerpt_id="", source_id=source_id, text=text,
                    char_start=0, char_end=len(text)))
                project.apply_code(CodeApplication(
                    application_id="", excerpt_id=excerpt,
                    code_id=code if index else other, rater_id="human_primary"))
        return path

    def test_it_collects_only_the_chosen_code(self, project):
        with Project.open(project) as proj:
            collected = coded_responses(proj, "Cost")

        assert len(collected["texts"]) == 9

    def test_the_text_is_the_excerpt_that_was_coded(self, project):
        with Project.open(project) as proj:
            collected = coded_responses(proj, "Cost")

        assert all(t.startswith("typical response") for t in collected["texts"])

    def test_identifiers_carry_the_excerpt_and_its_source(self, project):
        with Project.open(project) as proj:
            collected = coded_responses(proj, "Cost")
            report = find_deviant_cases(
                collected["texts"] + ["odd one out"],
                collected["identifiers"] + [collected["identifiers"][0]],
                code_name="Cost", embed=fake_embed)

        assert report.candidates[0].source_id
        assert report.candidates[0].excerpt_id

    def test_an_unknown_code_gives_nothing_rather_than_raising(self, project):
        with Project.open(project) as proj:
            assert coded_responses(proj, "never used")["texts"] == []

    def test_an_empty_project_gives_nothing(self, tmp_path):
        path = tmp_path / "empty.qnw"
        Project.create(path).close()
        with Project.open(path) as proj:
            assert coded_responses(proj, "Cost")["texts"] == []


def test_the_module_imports_without_torch():
    """`analysis/` is imported by the lite install and by this suite, neither of
    which has the model stack. A module-scope import of the embedder would make
    the file unimportable in both.

    Checked on the parsed imports rather than on the text: the first version of
    this test searched the source for "code_similarity" and matched the
    docstring explaining why the import is lazy.
    """
    import ast

    import analysis.deviant_cases as module

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    top_level = [
        node.module or ""
        for node in tree.body                      # module scope only
        if isinstance(node, ast.ImportFrom)
    ] + [
        alias.name
        for node in tree.body if isinstance(node, ast.Import)
        for alias in node.names
    ]

    heavy = {"analyze_survey", "torch", "transformers", "sentence_transformers",
             "analysis.code_similarity", "core.model_manager"}
    assert not heavy & set(top_level), (
        f"{sorted(heavy & set(top_level))} imported at module scope; the lite "
        "install cannot import this file")
