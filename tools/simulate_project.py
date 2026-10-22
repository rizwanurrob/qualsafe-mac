#!/usr/bin/env python
"""
Generate a synthetic project with a known answer (`V6_PLAN.md` Phase D2).

Writes a real `.qnw` — respondents, documents, excerpts, codes, descriptors —
from a **stated** data-generating process, and returns the answer key. The
fixture in `tests/test_double_lasso.py` promoted to a tool and written into a
project file.

Why this exists
---------------
Every sample-size floor in `core/model_spec.py` is statistical judgement rather
than measurement: 100 cases for double lasso, 80 for a forest, 60 for a tree.
They are most likely wrong in the direction of refusing work a researcher
legitimately wants to do, and there has never been a way to find out.

There is now. `measure_coverage` runs the estimator against many simulated
projects at a given n and reports **how often the 95% interval actually contains
the known effect**. Nominal coverage is 0.95. Wherever measured coverage falls
away is where the floor belongs — a number somebody can argue with, rather than
an opinion.

It also exercises the whole program end to end without waiting for a real
project. That is **not** a substitute for `V5_PLAN.md` Phase C and must never be
described as one: a synthetic project cannot tell you whether the interface
makes sense to a person. It is the difference between untested and untested by
a human, which is smaller than it sounds.

Every generated project says what it is
---------------------------------------
- every source carries `simulated: true` and the generating parameters in its
  metadata;
- the coder is `simulated`, which is not a `human*` rater, so the design matrix
  already flags its codes as estimates rather than measurements;
- a `SIMULATED.txt` sits beside the `.qnw`;
- the response text says so in the first sentence.

A synthetic project that could be mistaken for research data would be a worse
defect than anything this helps find.

    python tools/simulate_project.py out/demo.qnw --cases 200
    python tools/simulate_project.py --calibrate 40,80,120,200,400
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.model import Code, CodeApplication, Descriptor, Excerpt, Source
from core.project import Project

#: The rater every simulated coding is attributed to. Deliberately not
#: `human*`: `analysis/design_matrix.py` flags non-human raters as estimates,
#: and a synthetic project should inherit that warning for free.
SIMULATED_RATER = "simulated"

#: Marker on every source's metadata, and the name of the sidecar file.
SIMULATED_KEY = "simulated"
SIDECAR_NAME = "SIMULATED.txt"

TREATMENT_CODE = "Cost concerns"
CONFOUNDER = "first_generation"
OUTCOME = "wellbeing"
BINARY_OUTCOME = "did_not_return"

#: Residual spread of the outcome. THIS is what makes recovery hard —
#: see `_generate` — not the size of the effect being recovered.
DEFAULT_NOISE = 0.5

_SENTENCES = [
    "This is simulated text generated for testing; it is not a real response.",
    "Synthetic respondent {index}, produced by tools/simulate_project.py.",
    "No person said this.",
]


@dataclass(frozen=True)
class Truth:
    """The answer key: what the generator actually did.

    Returned rather than written into the project, because a project carrying
    its own answer key would let an analysis look the answer up instead of
    estimating it.
    """

    n_cases: int
    seed: int
    #: The true effect of the treatment code on `OUTCOME`, in outcome units.
    effect: float
    #: How strongly the confounder drives the treatment.
    confounding: float
    #: The confounder's direct effect on the outcome. Negative and matched to
    #: the indirect path is what defeats single-selection lasso.
    direct: float
    treatment_code: str = TREATMENT_CODE
    confounder: str = CONFOUNDER
    outcome: str = OUTCOME
    noise_codes: List[str] = field(default_factory=list)

    def describe(self) -> str:
        return (f"{self.n_cases} simulated cases, seed {self.seed}: "
                f"“{self.treatment_code}” has a true effect of {self.effect:+.3f} "
                f"on {self.outcome}, confounded by {self.confounder}")


def _generate(*, n_cases: int, effect: float, seed: int, noise_codes: int,
              confounding: float, hide_confounder: bool,
              noise: float = DEFAULT_NOISE):
    """The data-generating process, as arrays. The single definition of it.

    Both `simulate_project` (which writes a store) and `simulated_matrix`
    (which does not) draw from here, so a calibration run and a demo project
    cannot come from two subtly different processes.

    **`noise` is the difficulty knob, not `effect`.** With an additive error the
    estimator's error does not scale with the true coefficient, so halving the
    effect shifts the target and leaves the estimation problem identical —
    measured, after a sensitivity run returned byte-identical bias at two very
    different effect sizes. What makes recovery hard is the residual spread and
    the number of candidate controls relative to n.
    """
    rng = np.random.default_rng(seed)

    first_generation = rng.integers(0, 2, n_cases)
    treated = (rng.random(n_cases) < 0.15 + 0.5 * first_generation).astype(int)

    # Negative and matched to the indirect path: the outcome-on-controls
    # regression then sees roughly nothing for the confounder and a lasso drops
    # it, while the treatment lasso keeps it. That is the case double lasso
    # exists for and the case naive analysis fails silently.
    direct = -effect * confounding * 0.5 if hide_confounder else 0.3
    outcome = (effect * treated + direct * first_generation
               + rng.normal(scale=noise, size=n_cases))

    names = [f"Theme {chr(65 + i)}" for i in range(noise_codes)]
    drawn = {
        "first_generation": first_generation,
        "treated": treated,
        "outcome": outcome,
        "did_not_return": (outcome < np.median(outcome)).astype(int),
        "noise_applied": rng.integers(0, 2, (n_cases, noise_codes)),
    }
    truth = Truth(n_cases=n_cases, seed=seed, effect=effect,
                  confounding=confounding, direct=direct, noise_codes=names)
    return drawn, truth


def simulate_project(
    path: Path | str,
    *,
    n_cases: int = 200,
    effect: float = 1.0,
    seed: int = 0,
    noise_codes: int = 8,
    confounding: float = 1.5,
    hide_confounder: bool = True,
    noise: float = DEFAULT_NOISE,
) -> Truth:
    """Write a synthetic `.qnw` and return its answer key.

    `hide_confounder` sets the confounder's direct effect on the outcome to
    cancel its indirect path through the treatment. A lasso of the outcome on
    the controls then sees nothing and drops it, while the treatment lasso
    catches it — the case that separates double lasso from single selection, and
    the one worth simulating because naive analysis fails it silently.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    drawn, truth = _generate(n_cases=n_cases, effect=effect, seed=seed,
                             noise_codes=noise_codes, confounding=confounding,
                             hide_confounder=hide_confounder, noise=noise)
    first_generation = drawn["first_generation"]
    treated = drawn["treated"]
    outcome = drawn["outcome"]
    did_not_return = drawn["did_not_return"]
    noise_names = truth.noise_codes
    noise_applied = drawn["noise_applied"]
    direct = truth.direct

    parameters = {
        "generator": "tools/simulate_project.py",
        "n_cases": n_cases, "seed": seed, "effect": effect,
        "confounding": confounding, "direct": direct,
    }

    with Project.create(path) as project:
        codes = {name: project.add_code(Code(code_id="", name=name))
                 for name in [TREATMENT_CODE] + noise_names}

        for index in range(n_cases):
            text = " ".join(s.format(index=index) for s in _SENTENCES)
            source_id = project.add_source(Source(
                source_id="", type="survey_response", raw_text=text,
                label="Simulated Q1",
                metadata={SIMULATED_KEY: True,
                          "response_id": f"sim_{index:05d}",
                          "generated_by": parameters["generator"]}))
            excerpt = project.add_excerpt(Excerpt(
                excerpt_id="", source_id=source_id, text=text,
                char_start=0, char_end=len(text)))

            applied = ([TREATMENT_CODE] if treated[index] else []) + [
                name for j, name in enumerate(noise_names)
                if noise_applied[index, j]]
            for name in applied:
                project.apply_code(CodeApplication(
                    application_id="", excerpt_id=excerpt,
                    code_id=codes[name], rater_id=SIMULATED_RATER))

            for key, value in ((CONFOUNDER, int(first_generation[index])),
                               (OUTCOME, round(float(outcome[index]), 4)),
                               (BINARY_OUTCOME, int(did_not_return[index]))):
                project.set_descriptor(Descriptor(
                    source_id=source_id, key=key, value=str(value)))

    _write_sidecar(path, parameters)
    return truth


def _write_sidecar(path: Path, parameters: Dict[str, object]) -> None:
    """A file beside the project saying what it is, in words and in JSON."""
    (path.parent / SIDECAR_NAME).write_text(
        "This directory contains a SIMULATED project.\n\n"
        f"{path.name} was generated by tools/simulate_project.py. Every response\n"
        "in it is machine-written filler, every coding was applied by a\n"
        f"synthetic coder called “{SIMULATED_RATER}”, and no person said any of\n"
        "it. It exists to test the program and to calibrate its sample-size\n"
        "floors against a known answer.\n\n"
        "Do not report anything from it as a finding.\n\n"
        f"Parameters:\n{json.dumps(parameters, indent=2)}\n",
        encoding="utf-8")


# ── calibration ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Coverage:
    """How often the interval contained the truth, at one sample size."""

    n_cases: int
    trials: int
    covered: int
    #: Trials the method refused outright, e.g. below its own floor.
    refused: int
    mean_estimate: float
    true_effect: float

    @property
    def coverage(self) -> float:
        run = self.trials - self.refused
        return (self.covered / run) if run else float("nan")

    @property
    def bias(self) -> float:
        return self.mean_estimate - self.true_effect

    @property
    def standard_error(self) -> float:
        """Uncertainty on the coverage estimate itself.

        Reported because it is easy to over-read these numbers: at 50 trials
        the standard error is about 0.03, so 0.88 and 0.94 are not
        distinguishable and should not be used to place a floor between them.
        """
        run = self.trials - self.refused
        if run <= 0:
            return float("nan")
        share = self.covered / run
        return float((share * (1 - share) / run) ** 0.5)

    def verdict(self, nominal: float = 0.95, tolerance: float = 0.10) -> str:
        run = self.trials - self.refused
        if run == 0:
            return "refused every trial"
        # Two standard errors below nominal before calling it over-confident:
        # with 50 trials the noise alone moves coverage by ~0.06, and a floor
        # placed on noise is no better than a floor placed on a hunch.
        if self.coverage >= nominal - max(tolerance, 2 * self.standard_error):
            return "usable"
        return "over-confident"


def measure_coverage(n_cases: int, *, trials: int = 50, effect: float = 1.0,
                     seed: int = 0, noise_codes: int = 8,
                     noise: float = DEFAULT_NOISE) -> Coverage:
    """Fit double lasso against `trials` simulated projects and count coverage.

    The number that turns a floor from an opinion into a measurement: a 95%
    interval should contain the true effect about 95% of the time. Where that
    stops being true, the method is over-confident at that sample size, and
    that is where a refusal belongs.

    Deliberately builds the design matrix in memory rather than writing a
    `.qnw` per trial — the store round trip is tested elsewhere and fifty of
    them per sample size would make this too slow to run.
    """
    import tempfile

    from core.model_spec import ModelRequest, Shelf

    covered = refused = 0
    estimates: List[float] = []

    for trial in range(trials):
        matrix, truth = simulated_matrix(
            n_cases=n_cases, effect=effect, seed=seed * 1000 + trial,
            noise_codes=noise_codes, noise=noise)
        request = ModelRequest(
            method="double_lasso",
            outcome=Shelf((f"desc::{OUTCOME}",)),
            treatment=Shelf((f"code::{TREATMENT_CODE}",)),
            predictors=Shelf(tuple(c for c in matrix.frame.columns
                                   if c not in ("case_id", f"desc::{OUTCOME}",
                                                f"code::{TREATMENT_CODE}",
                                                f"desc::{BINARY_OUTCOME}"))),
            seed=20260829)

        # ALWAYS the estimator, never `fit`. The floor is what is being
        # measured, so it must not also be the gate. The first version called
        # `fit` above the flat base floor and `_force` below it, which was fine
        # until the rule grew with the candidate count — then the harness
        # started refusing exactly the cases it existed to measure, and
        # reported 150 refusals out of 150 at n = 80 rather than a coverage.
        # An instrument contaminated by the thing it measures is worse than no
        # instrument, because it still prints a number.
        result = _force(matrix, request)
        if not result.usable or result.effect is None:
            refused += 1
            continue
        low, high = result.effect.interval
        estimates.append(result.effect.coefficient)
        if low <= truth.effect <= high:
            covered += 1

    return Coverage(
        n_cases=n_cases, trials=trials, covered=covered, refused=refused,
        mean_estimate=float(np.mean(estimates)) if estimates else float("nan"),
        true_effect=effect)


def _force(matrix, request):
    """Estimate below the method's own floor, for calibration only.

    `fit` refuses below the floor, which is right for an analyst and useless for
    measuring whether the floor is in the right place. This calls the estimator
    directly and is not reachable from either front end.
    """
    from analysis.double_lasso import estimate_effect

    return estimate_effect(matrix, request)


def simulated_matrix(*, n_cases: int = 200, effect: float = 1.0, seed: int = 0,
                     noise_codes: int = 8, confounding: float = 1.5,
                     hide_confounder: bool = True,
                     noise: float = DEFAULT_NOISE):
    """A `DesignMatrix` from the same process, without touching the disk.

    Built directly rather than through a `.qnw` round trip. The first version of
    this wrote and reopened a store per trial against a docstring saying it did
    not, which made a six-size calibration run take longer than the entire test
    suite. The store path is exercised by `simulate_project` and its tests; a
    calibration loop does not need it, and cannot afford it.

    Column names match what `matrix_from_project` produces for the same project,
    and a test asserts that rather than trusting it.
    """
    import pandas as pd

    from analysis.design_matrix import CODE_PREFIX, DESC_PREFIX, DesignMatrix

    drawn, truth = _generate(n_cases=n_cases, effect=effect, seed=seed,
                             noise_codes=noise_codes, confounding=confounding,
                             hide_confounder=hide_confounder, noise=noise)

    columns = {"case_id": [f"sim_{i:05d}" for i in range(n_cases)],
               f"{CODE_PREFIX}{TREATMENT_CODE}": drawn["treated"]}
    for index, name in enumerate(truth.noise_codes):
        columns[f"{CODE_PREFIX}{name}"] = drawn["noise_applied"][:, index]
    columns[f"{DESC_PREFIX}{CONFOUNDER}"] = drawn["first_generation"]
    columns[f"{DESC_PREFIX}{OUTCOME}"] = drawn["outcome"]
    columns[f"{DESC_PREFIX}{BINARY_OUTCOME}"] = drawn["did_not_return"]

    frame = pd.DataFrame(columns)
    code_columns = [c for c in frame.columns if c.startswith(CODE_PREFIX)]
    frame["n_codes"] = frame[code_columns].sum(axis=1)

    matrix = DesignMatrix(frame=frame, unit="source_id", encoding="binary",
                          rater_id=SIMULATED_RATER,
                          raters_pooled=[SIMULATED_RATER])
    return matrix, truth


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", nargs="?", type=Path,
                        help="where to write the simulated .qnw")
    parser.add_argument("--cases", type=int, default=200)
    parser.add_argument("--effect", type=float, default=1.0)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--noise-codes", type=int, default=8)
    parser.add_argument("--calibrate", metavar="N,N,N",
                        help="measure interval coverage at these sample sizes")
    parser.add_argument("--trials", type=int, default=50)
    parser.add_argument("--noise", type=float, default=DEFAULT_NOISE,
                        help="residual spread — the difficulty knob")
    arguments = parser.parse_args(argv)

    if arguments.calibrate:
        sizes = [int(part) for part in arguments.calibrate.split(",") if part]
        print(f"Double lasso, {arguments.trials} trials per size, "
              f"true effect {arguments.effect:+.2f}, noise {arguments.noise}, "
              f"{arguments.noise_codes} noise codes")
        print(f"{'n':>6}  {'coverage':>9}  {'se':>7}  {'bias':>8}  "
              f"{'refused':>7}  verdict")
        for size in sizes:
            found = measure_coverage(size, trials=arguments.trials,
                                     effect=arguments.effect, seed=arguments.seed,
                                     noise_codes=arguments.noise_codes,
                                     noise=arguments.noise)
            print(f"{size:>6}  {found.coverage:>9.3f}  "
                  f"{found.standard_error:>7.3f}  {found.bias:>+8.3f}  "
                  f"{found.refused:>7}  {found.verdict()}")
        print("\nNominal coverage is 0.950. A floor belongs where coverage "
              "stops holding.")
        return 0

    if arguments.output is None:
        parser.error("give an output path, or --calibrate")

    truth = simulate_project(arguments.output, n_cases=arguments.cases,
                             effect=arguments.effect, seed=arguments.seed,
                             noise_codes=arguments.noise_codes)
    print(truth.describe())
    print(f"written to {arguments.output}")
    print(f"marker written to {arguments.output.parent / SIDECAR_NAME}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
