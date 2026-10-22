"""
Coding survey answers with a written codebook, without a front end.

Each code has a definition with rules for what to include and what to leave out.
A local coding engine (Laya, installed separately) scores every answer against
every code, and a person reviews the answers it is unsure about.

The Streamlit page (`app/alt_survey_flow.py`) and the desktop screen
(`qualsafe_qt/views/written_codebook_view.py`) both use this, so a run made in one
is the same run made in the other. Nothing here imports Qt or Streamlit.

Rules kept from `docs/ALT_SURVEY_FLOW_PLAN.md`:

* A score is a **model score**, never a probability, until it has been compared
  with a person's coding.
* The demo engine is never a real run: its codings carry a demo coder, a run
  never shares an id with a real run, and the result says it was a demo.
* Nothing derived from an answer is written anywhere but the project file.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

import pandas as pd

from core.model import Code, CodingRunConfig, Source
from core.project import Project

ProgressFn = Callable[[float, str], None]


def ensure_excerpts(project: Project, frame: pd.DataFrame, text_column: str,
                    id_column: str = "") -> List[Tuple[str, str]]:
    """Make sure every answer has a source and a whole-answer excerpt in `project`.

    An answer already in the project (matched by its response id) is reused, so an
    answer coded here and by the suggested-codes pipeline is one source, not two.
    Returns `[(excerpt_id, text), ...]` in row order, leaving out empty answers.
    """
    excerpts: List[Tuple[str, str]] = []
    for index, row in frame.iterrows():
        text = str(row.get(text_column, "") or "").strip()
        if not text:
            continue
        response_id = (str(row[id_column]) if id_column and id_column in frame.columns
                       else f"row_{index}")
        source = project.find_source_by_response_id(response_id)
        if source is None:
            source = Source(source_id="", type="survey_response", raw_text=text,
                            label=response_id, metadata={"response_id": response_id})
            source.source_id = project.add_source(source)
            excerpt_id = project.add_whole_response_excerpt(source)
        else:
            existing = project.list_excerpts(source.source_id)
            excerpt_id = (existing[0].excerpt_id if existing
                          else project.add_whole_response_excerpt(source))
        excerpts.append((excerpt_id, source.raw_text))
    return excerpts


def code_tree(codes: List[Code]) -> Tuple[List[Code], Dict[Optional[str], List[Code]]]:
    """The top-level codes and each parent's children, as the coding pass wants them."""
    children: Dict[Optional[str], List[Code]] = {}
    for code in codes:
        children.setdefault(code.parent_id, []).append(code)
    return [c for c in codes if c.parent_id is None], children


def usable_codes(codes: List[Code]) -> List[Code]:
    """Codes the engine can decide yes or no on. A rating scale is not a theme."""
    return [c for c in codes if c.decision_type != "score"]


#: Measured on a laptop CPU (2026-10-05 and 06): 2.7 to 3.2 seconds for each code asked of each
#: answer, and 100 to 330 seconds to start the engine (the start is slower the first time the
#: libraries are read). 40 answers x 5 codes took 543 s and then 754 s. A guide, not a promise.
SECONDS_PER_CODE_ANSWER = 3.0
SECONDS_TO_START = 180


def estimate_seconds(n_answers: int, n_codes: int) -> int:
    """A rough time for a real run on a laptop CPU. The demo engine takes seconds."""
    return int(SECONDS_TO_START + max(0, n_answers) * max(0, n_codes) * SECONDS_PER_CODE_ANSWER)


def estimate_text(n_answers: int, n_codes: int) -> str:
    seconds = estimate_seconds(n_answers, n_codes)
    if seconds < 90:
        return "under two minutes"
    if seconds < 3600:
        return f"about {round(seconds / 60)} minutes"
    return f"about {seconds / 3600:.1f} hours"


def has_rules(code: Code) -> bool:
    return bool((code.inclusion_criteria or "").strip() or (code.exclusion_criteria or "").strip())


def run(project_path, frame: pd.DataFrame, text_column: str, id_column: str,
        run_name: str, spec: Dict[str, Any], *, python_exe: Optional[str] = None,
        worker_env: Optional[Dict[str, str]] = None,
        force: bool = False, progress_callback: Optional[ProgressFn] = None,
        should_cancel: Optional[Callable[[], bool]] = None) -> Dict[str, Any]:
    """Code every answer in `frame` against the project's codebook.

    Opens its own `Project`, so it must run on a worker thread when called from a
    window (a store connection belongs to the thread that made it). With a
    `python_exe` for an environment that has Laya installed it uses the real
    engine; if that cannot start, or none is given, it uses the labelled demo
    engine and says why in `engine_note`.

    Returns the coding pass's result plus `run_id`, `engine` ("laya" or "demo"),
    `engine_note`, and `n_answers`.
    """
    from engines.laya_engine import CodingRunSpec, MockLayaEngine, run_coding_pass, run_id_for

    client = None
    engine, note = "demo", ""
    predict = MockLayaEngine().predict
    if python_exe:
        try:
            from engines.laya_client import LayaClient

            client = LayaClient(python_exe, env=worker_env)
            client.start()
            predict, engine = client.predict, "laya"
        except Exception as exc:  # noqa: BLE001 - say why, then fall back to the labelled demo
            client = None
            note = f"The coding engine could not start ({exc}). The demo engine was used instead."
    else:
        note = "The coding engine is not installed. The demo engine was used."

    try:
        with Project.open(project_path) as project:
            excerpts = ensure_excerpts(project, frame, text_column, id_column)
            if not excerpts:
                raise ValueError("No answers were found in that column.")
            codes = project.get_codebook()
            roots, children = code_tree(codes)
            run_id = run_id_for(run_name, project.path.stem, demo=engine != "laya")
            result = run_coding_pass(
                project, excerpts, roots, children, predict, run_id,
                CodingRunSpec.from_dict(spec), progress_callback=progress_callback,
                should_cancel=should_cancel, skip_existing=not force)
            project.save_coding_run_config(
                CodingRunConfig(config_id="", name=run_name, spec=spec))
    finally:
        if client is not None:
            try:
                client.stop()
            except Exception:  # noqa: BLE001 - the run is already written
                pass
    result = dict(result)
    result.update(run_id=run_id, engine=engine, engine_note=note, n_answers=len(excerpts))
    return result


def queue(project: Project, run_id: str, low: float, high: float) -> pd.DataFrame:
    """The candidate codes still waiting for a person to look at them."""
    return project.review_queue(run_id, low=low, high=high)


def review(project: Project, decision_id: str, verdict: str, reviewer: str,
           model_assigned: bool = False) -> None:
    """Record a person's verdict: "accept", "reject" or "flag"."""
    who = reviewer or "analyst"
    if verdict == "accept":
        project.review_coding_decision(decision_id, human_assigned=True, reviewer=who)
    elif verdict == "reject":
        project.review_coding_decision(decision_id, human_assigned=False, reviewer=who)
    elif verdict == "flag":
        project.review_coding_decision(decision_id, human_assigned=bool(model_assigned),
                                       reviewer=who, review_status="flagged")
    else:
        raise ValueError(f"Unknown verdict: {verdict!r}")
