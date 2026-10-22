#!/usr/bin/env python
"""
Structured codebook coding over Laya (Alt Survey Flow).

This module is the coding *logic* -- question-building, hierarchical routing,
confidence-band decisions, segmentation -- and is deliberately independent of
how a score gets computed. It calls `predict_fn(state, questions) -> answers`,
a plain function with `engines.laya_client.LayaClient.predict`'s exact
signature, so tests and UI development use `MockLayaEngine.predict` (below,
offline, deterministic, no subprocess) while a real run uses a live
`LayaClient` bound to the isolated worker process. Same separation this
codebase already uses for `engines/llm_engine.py` (an injected client) and
`engines/transformer_engine.py` (an injected pipeline).

**Laya is the CODING layer, not the theme-discovery layer.** It answers
questions about codes an analyst has already named; it does not propose codes.
Keyword search, topic modeling, embeddings and clustering (already in
`analysis/` and `engines/transformer_engine.py`) remain how an analyst finds
candidate themes before the codebook is finalized -- this module is what runs
once the codebook exists.

**Scores are not probabilities of correctness unless calibrated.** Laya's own
docs describe base checkpoints as shipping "over-confident" (Expected
Calibration Error 0.466 before per-question-type temperature scaling, 0.081
after -- see docs/ALT_SURVEY_FLOW_PLAN.md). This project has no calibration
data for Laya yet (that is exactly what the calibration-sample workflow this
feature is building toward would produce). So every score this module returns
is a **model score**, never a probability, in every field name, log line, and
(once built) UI string -- `analysis/coding_validation.py` is where an actual
calibration curve, once measured against a human sample, would be reported.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from core.model import Code, CodingDecision, Rater
from core.project import new_id
from core.segmentation import Segment, segment_for_coding

#: `predict_fn(state, questions) -> {"question_name": {...answer...}, ...}`.
#: Matches `engines.laya_client.LayaClient.predict` exactly.
PredictFn = Callable[[Dict[str, Any], Dict[str, Any]], Dict[str, Any]]

CodingMode = str    # "multi_label_noul" | "single_label_choice"


@dataclass
class CodingRunSpec:
    """A coding run's settings -- the JSON shape stored in
    `core.model.CodingRunConfig.spec` (schema v7, `coding_run_configs`).

    A typed wrapper rather than a bare dict so the shape is defined in exactly
    one place; `to_dict`/`from_dict` are what the store actually persists.

    `text_column` and `question_scope` describe where the source text came from
    (which survey column, restricted to one question if the data has several) --
    informational for the run, since by the time coding runs the text is already
    in `Source`/`Excerpt` rows regardless of which column it started in.
    """
    text_column: str
    mode: CodingMode = "multi_label_noul"
    low_threshold: float = 0.35
    high_threshold: float = 0.65
    segmentation_token_budget: int = 350   # leaves headroom under Laya's 512-token
                                            # English-checkpoint context for the
                                            # questions themselves (~192-256 tokens)
    model: str = "convaiinnovations/laya"
    subfolder: Optional[str] = None
    question_scope: Optional[str] = None
    #: Also ask the engine each code's leave-out rule. Off by default: measured to make
    #: the engine worse (see `Code.as_laya_question`); the rule is shown to the reviewer.
    send_exclusions: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text_column": self.text_column, "mode": self.mode,
            "low_threshold": self.low_threshold, "high_threshold": self.high_threshold,
            "segmentation_token_budget": self.segmentation_token_budget,
            "model": self.model, "subfolder": self.subfolder,
            "question_scope": self.question_scope,
            "send_exclusions": self.send_exclusions,
        }

    @classmethod
    def from_dict(cls, spec: Dict[str, Any]) -> "CodingRunSpec":
        defaults = cls(text_column=spec.get("text_column", ""))
        return cls(
            text_column=spec.get("text_column", ""),
            mode=spec.get("mode", defaults.mode),
            low_threshold=float(spec.get("low_threshold", defaults.low_threshold)),
            high_threshold=float(spec.get("high_threshold", defaults.high_threshold)),
            segmentation_token_budget=int(spec.get("segmentation_token_budget",
                                                   defaults.segmentation_token_budget)),
            model=spec.get("model", defaults.model),
            subfolder=spec.get("subfolder"),
            question_scope=spec.get("question_scope"),
            send_exclusions=bool(spec.get("send_exclusions", False)),
        )


def route_by_confidence(score: Optional[float], *, low: float, high: float) -> str:
    """'confident_no' | 'ambiguous' | 'confident_yes'.

    The ONE definition of "ambiguous" this feature uses -- `core.project.
    Project.review_queue` filters on the same [low, high) band so a decision
    routed to the Review Queue and a decision this module marks ambiguous can
    never disagree about which items need a human. `score=None` (no model
    opinion at all, e.g. a human-added code) is treated as maximally ambiguous
    rather than silently skipped.
    """
    if score is None:
        return "ambiguous"
    if score < low:
        return "confident_no"
    if score >= high:
        return "confident_yes"
    return "ambiguous"


# ── question building (pure) ─────────────────────────────────────────────────
def build_questions_for_codes(codes: List[Code], mode: CodingMode,
                              send_exclusions: bool = False) -> Dict[str, Dict[str, Any]]:
    """Turn a flat list of sibling codes into Laya's typed-question dict.

    Score-typed codes (`decision_type == "score"`) always become their own
    `score` question regardless of `mode` -- a rubric rating is not a multi-label
    theme decision and is never folded into a `choice` or asked as `noul`.

    For the remaining ("noul") codes: `multi_label_noul` asks one independent
    `noul` question per code (any number may end up assigned -- the default, and
    the right choice whenever themes can co-occur, which is most qualitative
    coding). `single_label_choice` asks ONE `choice` question naming every code
    as an option -- use only when the analyst has said the codes at this level
    are genuinely mutually exclusive; Laya's own documentation says choice
    accuracy degrades past roughly 20 options (see docs/ALT_SURVEY_FLOW_PLAN.md),
    which is the reason the hierarchical walk below never hands one `choice`
    question a whole flat codebook.
    """
    questions: Dict[str, Dict[str, Any]] = {}
    choice_criteria: Dict[str, str] = {}

    for code in codes:
        if code.decision_type == "score":
            levels = code.rubric_levels or ["absent", "present"]
            questions[code.code_id] = {
                "type": "score",
                "instructions": code.as_laya_instructions(),
                "criteria": list(levels),
            }
        elif mode == "single_label_choice":
            choice_criteria[code.code_id] = code.as_laya_instructions()
        else:  # multi_label_noul (default)
            questions[code.code_id] = {
                "type": "noul",
                "instructions": code.as_laya_question(include_exclusion=send_exclusions)}

    if choice_criteria:
        questions["__choice__"] = {
            "type": "choice",
            "instructions": "Which of these best describes this response?",
            "criteria": choice_criteria,
        }
    return questions


def _unpack_answers(
    codes: List[Code], answers: Dict[str, Any], mode: CodingMode,
) -> Dict[str, Dict[str, Any]]:
    """Map Laya's answer dict back to one result per code_id.

    For a `choice` question, every option NOT selected is recorded with a score
    of 0.0 and `assigned=False` rather than being dropped -- the Review Queue and
    the export need to show "the model considered this and said no", the same
    audit-trail principle CodingDecision exists for.
    """
    results: Dict[str, Dict[str, Any]] = {}
    choice_answer = answers.get("__choice__")
    choice_distribution = (choice_answer or {}).get("distribution") if isinstance(choice_answer, dict) else None
    chosen = (choice_answer or {}).get("choice") if isinstance(choice_answer, dict) else None

    for code in codes:
        if code.code_id in answers:  # noul or score
            answer = answers[code.code_id]
            if code.decision_type == "score":
                score = answer.get("score")
                levels = code.rubric_levels or []
                normalized = (float(score) / (len(levels) - 1)) if score is not None and len(levels) > 1 else score
                results[code.code_id] = {
                    "score": normalized, "assigned": None,   # a rating, not a yes/no
                    "raw": answer,
                }
            else:
                score = answer.get("noul")
                results[code.code_id] = {"score": score, "assigned": None, "raw": answer}
        elif mode == "single_label_choice" and code.decision_type != "score":
            is_chosen = chosen == code.code_id
            score = _distribution_score(choice_distribution, code.code_id)
            if score is None:
                score = 1.0 if is_chosen else 0.0    # no per-option distribution given
            results[code.code_id] = {"score": score, "assigned": is_chosen, "raw": choice_answer}
    return results


def _distribution_score(distribution: Any, code_id: str) -> Optional[float]:
    """Best-effort read of a choice question's per-option probability.

    Laya's documented response shape for `distribution` is a plain list aligned
    to the criteria order in some descriptions and a dict keyed by option in
    others (the published examples were not fully consistent on this point --
    see docs/ALT_SURVEY_FLOW_PLAN.md's "unverified" list). Only the dict shape
    is read here; a list falls through to the chosen/not-chosen 1.0/0.0 the
    caller uses as a fallback, so a real response in either form still produces
    a usable (if less precise, for the list case) score.
    """
    if isinstance(distribution, dict) and code_id in distribution:
        return distribution[code_id]
    return None


# ── per-excerpt coding (one flat set of sibling codes) ───────────────────────
def code_excerpt(
    text: str, codes: List[Code], predict_fn: PredictFn, mode: CodingMode,
    send_exclusions: bool = False,
) -> Dict[str, Dict[str, Any]]:
    """One Laya call over one excerpt and one sibling group of codes.

    Returns `{code_id: {"score": float|None, "assigned": bool|None, "raw": dict}}`.
    `assigned` is None for a `score`-typed code (a rating has no yes/no) and for
    a `multi_label_noul` code before a threshold is applied (that happens in
    `route_by_confidence`, one layer up, because the threshold is a per-run
    setting, not something this pure per-excerpt call should decide).
    """
    if not codes:
        return {}
    questions = build_questions_for_codes(codes, mode, send_exclusions)
    answers = predict_fn({"text": text}, questions)
    return _unpack_answers(codes, answers, mode)


# ── hierarchical coarse-to-fine walk ─────────────────────────────────────────
def code_excerpt_hierarchical(
    text: str, root_codes: List[Code], children_by_parent: Dict[Optional[str], List[Code]],
    predict_fn: PredictFn, mode: CodingMode, *, low: float, high: float,
    send_exclusions: bool = False,
) -> Dict[str, Dict[str, Any]]:
    """Evaluate a codebook top-down: score the top-level codes first, and only
    descend into a code's children when that code itself was NOT ruled out
    (confident_no) -- i.e. for `confident_yes` and `ambiguous` parents alike, so
    borderline parents still get their children evaluated rather than silently
    losing that branch.

    This is not a convenience -- it is how a codebook larger than roughly 20
    codes stays accurate at all. Laya's own documentation reports choice/noul
    accuracy degrading past ~20 simultaneous options and specifically
    recommends "a two-step coarse-to-fine hierarchy" for large codebooks (see
    docs/ALT_SURVEY_FLOW_PLAN.md). `core.model.Code.parent_id` already gives
    QualSafe a real hierarchy; this function is what makes structured coding use
    it rather than flattening every code into one call.
    """
    results: Dict[str, Dict[str, Any]] = {}
    frontier = list(root_codes)
    while frontier:
        level_results = code_excerpt(text, frontier, predict_fn, mode, send_exclusions)
        results.update(level_results)
        next_frontier: List[Code] = []
        for code in frontier:
            verdict = level_results.get(code.code_id, {})
            band = route_by_confidence(verdict.get("score"), low=low, high=high)
            if band != "confident_no":
                next_frontier.extend(children_by_parent.get(code.code_id, []))
        frontier = next_frontier
    return results


# ── segmentation-aware, decision-producing entry point ───────────────────────
def draft_coding_decisions(
    excerpt_id: str, text: str, root_codes: List[Code],
    children_by_parent: Dict[Optional[str], List[Code]],
    predict_fn: PredictFn, run_id: str, spec: CodingRunSpec,
) -> List[CodingDecision]:
    """The end-to-end call for one excerpt: segment if needed, code every
    segment, de-duplicate across segments (keep the strongest evidence for each
    code), and return ready-to-store CodingDecision rows.

    De-duplication takes the MAX score across segments for a given code, not an
    average: `core/segmentation.py` overlaps sentences at chunk boundaries
    deliberately so a theme is never invisible for landing on a seam, and a
    response either does or doesn't touch a theme -- averaging a real mention
    against a segment that never discusses it would dilute genuine evidence.
    Does not write to the store; the caller passes the result to
    `Project.record_coding_decisions`.
    """
    segments = segment_for_coding(text, token_budget=spec.segmentation_token_budget)
    best: Dict[str, Dict[str, Any]] = {}
    for segment in segments:
        segment_results = code_excerpt_hierarchical(
            segment.text, root_codes, children_by_parent, predict_fn, spec.mode,
            low=spec.low_threshold, high=spec.high_threshold,
            send_exclusions=spec.send_exclusions,
        )
        for code_id, verdict in segment_results.items():
            score = verdict.get("score")
            current = best.get(code_id)
            if current is None or (score is not None and (current.get("score") is None or score > current["score"])):
                best[code_id] = verdict

    decisions: List[CodingDecision] = []
    for code_id, verdict in best.items():
        score = verdict.get("score")
        band = route_by_confidence(score, low=spec.low_threshold, high=spec.high_threshold)
        assigned = verdict.get("assigned")
        if assigned is None:   # noul: derive from the threshold band
            assigned = band == "confident_yes"
        decisions.append(CodingDecision(
            decision_id=new_id("dec"), excerpt_id=excerpt_id, code_id=code_id, run_id=run_id,
            model_score=score, model_assigned=bool(assigned),
            review_status="unreviewed",
        ))
    return decisions


# ── end-to-end run over a batch of excerpts (the UI's one entry point) ──────
def run_coding_pass(
    project: Any, excerpts: List[tuple], root_codes: List[Code],
    children_by_parent: Dict[Optional[str], List[Code]], predict_fn: PredictFn,
    run_id: str, spec: CodingRunSpec, *, rater_id: Optional[str] = None,
    progress_callback: Optional[Callable[[float, str], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None, skip_existing: bool = True,
) -> Dict[str, Any]:
    """Code a batch of excerpts end to end and write the results into the
    project as it goes -- the one function a UI needs to call.

    `excerpts` is `[(excerpt_id, text), ...]`. Writes are incremental, not
    buffered to the end: a cancelled run keeps every excerpt it already coded,
    the same checkpointing philosophy `core/checkpoint.py` uses for the LLM
    engine. `progress_callback(fraction, message)` matches `run_pipeline`'s own
    contract, so a Streamlit page's `st.progress` closure works unchanged.

    `skip_existing=True` (the default) makes a re-invocation over the same
    excerpts and run_id resumable: an excerpt that already has decisions for
    this run is skipped rather than re-asked, so continuing after a
    cancellation costs nothing for the work already done. Pass `False` for a
    deliberate re-run (e.g. after editing thresholds or a code's criteria).

    Every `model_assigned=True` decision also gets an automatic
    `CodeApplication`, under a machine rater (`kind='transformer'`,
    `model_id=spec.model`) -- mirroring how the existing survey pipeline
    already applies confident zero-shot/LLM codes without per-item human
    confirmation. An ambiguous decision stays CodingDecision-only until a human
    reviews it via `Project.review_coding_decision`, which is what actually
    creates a *human* application. `sync_machine_application` (not a plain
    `apply_code`) makes this idempotent, so `skip_existing=False` never
    duplicates an application for the same (excerpt, code, rater).
    """
    # A demo run (MockLayaEngine: hash scores, meaningless by design) must never
    # be recorded as real coding: its own rater id, a model id that says "mock",
    # and a name that says DEMO wherever the rater is listed (review finding F2).
    demo = is_demo_predict(predict_fn)
    if demo:
        rater_id = rater_id or f"{DEMO_RATER_PREFIX}{run_id}"
        project.add_rater(Rater(rater_id=rater_id, kind="structured", name=DEMO_RATER_NAME,
                                model_id=DEMO_MODEL_ID))
    else:
        rater_id = rater_id or f"laya_{run_id}"
        # Its own kind: a structured engine is neither the zero-shot pipeline
        # nor an LLM, and the methods appendix reports it through its
        # calibration sample, not as "the engine" (analysis.calibration).
        project.add_rater(Rater(rater_id=rater_id, kind="structured",
                                name="Laya structured coding", model_id=spec.model))

    total = len(excerpts)
    coded = skipped = assigned = 0
    cancelled = False
    for i, (excerpt_id, text) in enumerate(excerpts):
        if should_cancel is not None and should_cancel():
            cancelled = True
            break
        if skip_existing and project.list_coding_decisions(run_id=run_id, excerpt_id=excerpt_id):
            skipped += 1
            if progress_callback:
                progress_callback((i + 1) / max(total, 1), f"Already coded {i + 1}/{total}")
            continue

        decisions = draft_coding_decisions(
            excerpt_id, text, root_codes, children_by_parent, predict_fn, run_id, spec)
        project.record_coding_decisions(decisions)
        # Every code was asked about this excerpt, so the engine reviewed it in
        # full -- including codes it did not assign (store format v8).
        project.record_coverage(rater_id, [excerpt_id], run_id=run_id)
        for decision in decisions:
            if decision.model_assigned:
                project.sync_machine_application(
                    excerpt_id=decision.excerpt_id, code_id=decision.code_id,
                    rater_id=rater_id, run_id=run_id, confidence=decision.model_score)
                assigned += 1
        coded += 1
        if progress_callback:
            progress_callback((i + 1) / max(total, 1), f"Coded {i + 1}/{total}")

    return {"coded": coded, "skipped": skipped, "assigned": assigned,
            "cancelled": cancelled, "total": total}


# ── demo runs: named, separable, removable ─────────────────────────────────
DEMO_RATER_PREFIX = "laya_demo_"
DEMO_MODEL_ID = "mock:laya"
DEMO_RATER_NAME = "Laya DEMO (mock scores, not real coding)"


def is_demo_predict(predict_fn: Any) -> bool:
    """True when `predict_fn` is the mock's (a bound `MockLayaEngine.predict`,
    or any callable that declares `is_mock`)."""
    owner = getattr(predict_fn, "__self__", None)
    return bool(getattr(predict_fn, "is_mock", False) or getattr(owner, "is_mock", False))


def run_id_for(run_name: str, project_stem: str, *, demo: bool) -> str:
    """The run id for a named run. Demo and real runs never share one, so a
    real run started later under the same name codes every response instead
    of resuming -- that is, skipping -- the ones the demo "coded"."""
    kind = "demo" if demo else "laya"
    return f"{(run_name or '').strip() or 'run'}__{kind}_{project_stem}"


def demo_rater_ids(project: Any) -> List[str]:
    return [r.rater_id for r in project.list_raters()
            if r.rater_id.startswith(DEMO_RATER_PREFIX) or r.model_id == DEMO_MODEL_ID]


def remove_demo_codings(project: Any) -> Dict[str, int]:
    """Delete every demo run: its codings, review record, decisions and rater.

    Real runs, human codings, excerpts and codes are untouched.
    """
    report = {"raters": 0, "applications": 0, "decisions": 0}
    for rater_id in demo_rater_ids(project):
        run_ids = {d for d in project.run_ids_for_rater(rater_id) if d}
        for run_id in run_ids:
            report["decisions"] += project.delete_coding_decisions(run_id)
        counts = project.delete_rater(rater_id)
        report["applications"] += counts["applications"]
        report["raters"] += 1
    if report["raters"]:
        project.log_event("demo_codings_removed",
                          f"Demo-engine codings removed ({report['applications']})",
                          target_type="rater", detail=report)
    return report


# ── offline mock, for tests and UI development without a real install ───────
class MockLayaEngine:
    """A deterministic, offline stand-in for a real `LayaClient`.

    Scores are a stable hash of (excerpt text, code instructions) mapped into
    [0, 1] -- reproducible across runs (this codebase's byte-identical-output
    discipline) but NOT meaningful coding; nothing about the hash reflects
    whether the text actually matches the code. Exists so the schema, the
    hierarchical walk, segmentation, thresholds, the Review Queue and the
    calibration workflow can all be built and tested (`tests/test_laya_engine.py`)
    without `laya` installed anywhere -- consistent with every other engine in
    this codebase staying testable torch-free. MUST NOT be used to produce a
    result an analyst treats as real coding; the UI is responsible for labelling
    a mock-engine run as a demo, not hiding that distinction.

    `run_coding_pass` reads `is_mock` and records the run under a demo rater
    (`laya_demo_…`, model id `mock:laya`) that `remove_demo_codings` can delete.
    """

    is_mock = True

    def predict(self, state: Dict[str, Any], questions: Dict[str, Any]) -> Dict[str, Any]:
        text = str(state.get("text", ""))
        answers: Dict[str, Any] = {}
        for name, question in questions.items():
            if name == "__choice__":
                criteria = question.get("criteria", {})
                scored = {opt: self._score(text, instr) for opt, instr in criteria.items()}
                chosen = max(scored, key=scored.get) if scored else None
                answers[name] = {"choice": chosen, "distribution": scored,
                                 "confidence": scored.get(chosen, 0.0) if chosen else 0.0}
            elif question.get("type") == "score":
                levels = question.get("criteria", [])
                raw = self._score(text, question.get("instructions", ""))
                level_index = min(int(raw * len(levels)), max(len(levels) - 1, 0)) if levels else 0
                answers[name] = {"score": float(level_index), "confidence": raw}
            else:  # noul
                score = self._score(text, question.get("instructions", ""))
                answers[name] = {"noul": score, "confidence": score}
        return answers

    @staticmethod
    def _score(text: str, instructions: str) -> float:
        digest = hashlib.sha256(f"{text}||{instructions}".encode("utf-8")).digest()
        return int.from_bytes(digest[:4], "big") / 0xFFFFFFFF
