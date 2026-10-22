#!/usr/bin/env python
"""
Shared project model for QualSafe (v3).

This module defines the entities that both survey mode and interview mode
populate. It is the conceptual backbone described in V3_PLAN.md §2.2. In this
phase the dataclasses are plain in-memory records with no persistence —
persistence (SQLite `.qnw`) arrives in Phase 0b via core/project.py.

Core entities:
- Source           : a unit of ingested data (a survey response, or an interview).
- Excerpt          : a span of source text that coding attaches to. In survey
                     mode the default excerpt is the whole response.
- Code             : a node in the hierarchical codebook (parent_id -> tree),
                     optionally carrying a weight scale.
- CodeApplication  : one code attached to one excerpt (the analytical join unit),
                     tied to the rater and run that produced it.
- Descriptor       : a per-source metadata *value* (program, class year, ...).
- DescriptorField  : the project-level *type* of a descriptor key (categorical /
                     ordinal / numeric) — drives correct sorting and aggregation.
- Memo             : a free-text analytic note attached to a code/excerpt/project.
- Rater            : an entity that applies codes (a human coder, or a model).
- RunManifest      : audit record of one automated pass.

Design notes (post-review, V3_PLAN.md §"schema refinements"):
- Offsets are first-class on Excerpt so every code application is traceable to
  exact source characters (the drill-back + anti-hallucination guarantee).
- `weight` on CodeApplication is the general valence/intensity mechanism; its
  *scale* is defined per Code via WeightScale so that weighted aggregates never
  mix incompatible scales. The v2.1 response-level sentiment column is kept
  separately for backward compatibility (V3_PLAN.md PUSHBACK #4).
- Every CodeApplication records `rater_id` and `run_id` so (a) inter-rater
  agreement can align raters over a shared overlap set of excerpts and (b) runs
  can be diffed / filtered. `coder` remains a coarse convenience kind.
- Descriptor *values* are stored as strings; their *type* lives on
  DescriptorField so ordinal descriptors (e.g. Age_Band) sort by declared level
  order rather than alphabetically, and numeric ones aggregate correctly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

# ── Controlled vocabularies (plain str literals; validated at the persistence
#    boundary in Phase 0b rather than via enums, to stay lightweight). ─────────
SourceType = str          # "survey_response" | "interview"
CodeOrigin = str          # "a_priori" | "emergent"
Coder = str               # "human" | "transformer" | "llm"
RaterKind = str           # "human" | "transformer" | "llm" | "structured" (Laya)
MemoTarget = str          # "code" | "excerpt" | "project"
DescriptorType = str      # "categorical" | "ordinal" | "numeric"
WeightKind = str          # "valence" | "intensity" | "confidence"

# ── Codebook roll-up policy (V3_PLAN.md schema refinement #5) ────────────────
# Default: applying a child code implies its ancestors for roll-up purposes, and
# parent-level frequency uses SET semantics (an excerpt coded with two children
# of the same parent counts ONCE at the parent). Both are the documented default
# and can be overridden per-analysis; expand_with_ancestors() implements them.
ROLLUP_IMPLIES_PARENT = True


def _normalize_ws(text: str) -> str:
    """Collapse runs of whitespace and strip — used for tolerant span matching."""
    return " ".join(text.split())


@dataclass
class Source:
    """A unit of ingested data.

    Survey mode: one Source per response. Interview mode: one Source per
    transcript. Descriptors attach to a Source and are inherited by its excerpts.
    """
    source_id: str
    type: SourceType
    raw_text: str
    label: str = ""                       # human-friendly name (e.g. question text, file name)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Excerpt:
    """A span of source text that carries codes.

    In survey mode the default excerpt spans the whole response, so
    (char_start, char_end) == (0, len(raw_text)). Interview mode uses sub-turn
    spans. `text` is denormalized for convenience and MUST equal
    source_raw_text[char_start:char_end]; verify_offsets() enforces that.
    """
    excerpt_id: str
    source_id: str
    text: str
    char_start: int
    char_end: int

    def verify_offsets(self, source_raw_text: str, *, tolerant_whitespace: bool = False) -> bool:
        """Return True if this excerpt's text matches the source at its offsets.

        This is the pure-function core of the anti-hallucination guarantee: any
        span (including an LLM-selected quote) can be checked against the source
        before it is surfaced. With tolerant_whitespace=True, differences that
        are only whitespace runs are ignored.

        NOTE: tolerant mode normalizes whitespace only — NOT Unicode (curly vs.
        straight apostrophes, dashes) or case. Robust LLM-quote matching in v3.1
        interview mode will need Unicode/quote folding on top of this; see
        V3_PLAN.md Decision 4.
        """
        if not (0 <= self.char_start <= self.char_end <= len(source_raw_text)):
            return False
        span = source_raw_text[self.char_start:self.char_end]
        if tolerant_whitespace:
            return _normalize_ws(span) == _normalize_ws(self.text)
        return span == self.text


@dataclass
class WeightScale:
    """Defines what a code's `weight` means, so weighted aggregates are valid.

    A weight of 0.5 is meaningless without its scale: valence (−1..+1), intensity
    (1..5), or confidence (0..1) are different constructs. Aggregations must only
    combine applications whose codes share a compatible scale.
    """
    kind: WeightKind                      # "valence" | "intensity" | "confidence"
    min_value: float
    max_value: float

    def contains(self, value: float) -> bool:
        return self.min_value <= value <= self.max_value


#: A code's decision primitive under Alt Survey Flow's structured coding.
#: "noul": an independent yes/no theme (the multi-label default -- one response
#: may legitimately hold several). "score": not a theme at all but an ordinal
#: rubric (`rubric_levels` gives the ordered level names); it produces a rating,
#: not a code assignment, and is never mixed into multi-label roll-ups.
#: Mutual exclusivity ("choice") is NOT a per-code property -- it is a relation
#: between siblings, decided per coding run (see CodingRunConfig).
CodeDecisionType = str    # "noul" | "score"


@dataclass
class Code:
    """A node in the hierarchical codebook.

    `parent_id` gives arbitrary-depth nesting (V3_PLAN.md: flexible hierarchy).
    `origin` distinguishes a-priori (analyst/template-defined) from emergent
    (discovered by clustering/LLM) codes. `weight_scale`, when set, declares the
    meaning/range of weights on this code's applications.

    Structured-coding fields (Alt Survey Flow, additive on top of the existing
    free-text `definition`): `inclusion_criteria` and `exclusion_criteria` are
    what actually gets asked of a coding engine ("does this response describe
    experiencing this?" is looser than "assign when X; do NOT assign for Y even
    though it sounds related") -- `definition` stays the human-readable summary,
    these are the operational boundary a coder (human or model) applies.
    `examples` are illustrative excerpts an analyst has already recognised as
    fitting; a structured engine can be given them as few-shot context.
    """
    code_id: str
    name: str
    definition: str = ""
    parent_id: Optional[str] = None
    origin: CodeOrigin = "a_priori"
    created_by: Coder = "human"
    weight_scale: Optional[WeightScale] = None
    inclusion_criteria: str = ""
    exclusion_criteria: str = ""
    examples: List[str] = field(default_factory=list)
    decision_type: CodeDecisionType = "noul"
    rubric_levels: Optional[List[str]] = None    # required when decision_type == "score"

    def as_laya_instructions(self) -> str:
        """Compose one instruction string for a structured coding engine.

        Kept on the dataclass (not scattered into engine code) because the
        composition rule -- definition, then the inclusion/exclusion boundary,
        then examples -- is part of what a code *means*, and every caller (the
        real engine, the mock, a future export of "what was actually asked")
        must build the same string from the same fields.
        """
        parts = [self.definition.strip()] if self.definition.strip() else []
        if self.inclusion_criteria.strip():
            parts.append(f"Assign when: {self.inclusion_criteria.strip()}")
        if self.exclusion_criteria.strip():
            parts.append(f"Do NOT assign when: {self.exclusion_criteria.strip()}")
        if self.examples:
            shown = "; ".join(f'"{e.strip()}"' for e in self.examples[:3] if e.strip())
            if shown:
                parts.append(f"Examples that fit: {shown}")
        return " ".join(parts) or f"Does this response describe '{self.name}'?"

    def as_laya_question(self, include_exclusion: bool = False) -> str:
        """The yes/no question asked of the engine for this code.

        A question, not a statement of rules: measured on the real engine (2026-10-05,
        12 hand-judged answers, a small test), "Is this answer about X? That means
        <the count-it rule>." put the right code first for 9 of 12 answers; the same
        rules as statements ("Assign when… Do NOT assign when…") did so for 2 of 6.
        Adding the leave-out rule to the question made it worse (5 of 12), so it is
        left out unless asked for (`include_exclusion`) and is shown to the person
        reviewing instead.
        """
        inclusion = (self.inclusion_criteria or "").strip()
        definition = (self.definition or "").strip()
        if not inclusion and not definition:
            return f"Does this response describe '{self.name}'?"
        question = f"Is this answer about {self.name.lower()}? That means {inclusion or definition}."
        exclusion = (self.exclusion_criteria or "").strip()
        if include_exclusion and exclusion:
            question += f" It does not count if it {exclusion}."
        return question


@dataclass
class Rater:
    """An entity that applies codes: a human coder or a model.

    Explicit rater identity is required for inter-rater reliability — kappa needs
    identifiable raters and a defined overlap set of excerpts both rated. For
    model raters, `model_id` records the exact model (e.g. facebook/bart-large-mnli
    or llama3.2:3b) so methods sections and per-model trust stats are precise.
    """
    rater_id: str
    kind: RaterKind                       # "human" | "transformer" | "llm"
    name: str = ""
    model_id: str = ""


@dataclass
class CodeApplication:
    """One code attached to one excerpt — the unit every analysis is built on.

    Carries the strict-coding gate outputs (confidence/margin) so the transformer
    and LLM engines are methodologically consistent, an optional `weight`
    (interpreted via the code's WeightScale), an LLM `rationale`, and the
    `rater_id` / `run_id` provenance needed for IRR and run-diffing.
    """
    application_id: str
    excerpt_id: str
    code_id: str
    coder: Coder = "transformer"          # coarse convenience kind
    rater_id: Optional[str] = None        # FK -> Rater (for IRR overlap alignment)
    run_id: Optional[str] = None          # FK -> RunManifest (for filtering/diffing)
    weight: Optional[float] = None
    confidence: Optional[float] = None
    margin: Optional[float] = None
    rationale: str = ""


#: Where one code's structured-coding verdict for one excerpt stands.
#: "unreviewed": only the model has spoken. "confirmed"/"rejected": a human
#: agreed or disagreed with the model. "added_by_human": the model was never
#: asked, or said no, and a person applied the code anyway. "flagged": the
#: response needs a second look for a reason unrelated to any one code (kept
#: distinct from "rejected" -- flagging is about the response, not the code).
CodingReviewStatus = str


@dataclass
class CodingDecision:
    """One code's model-and-human verdict for one excerpt (Alt Survey Flow).

    Deliberately NOT a CodeApplication. This project's convention is that a
    CodeApplication exists only for an ACCEPTED code -- "no code" is the absence
    of a row, not a row saying no (see core/adjudication.py). That convention is
    right for the coded-data layer: every existing frequency/co-occurrence/
    crosstab/kappa function reads code_applications and must keep working
    unchanged. But the human-in-the-loop review workflow needs the full audit
    trail the analyst was promised: every candidate the model was asked about,
    including the ones it or a human said no to, with the score that produced
    that call. CodingDecision is that audit layer; CodeApplication remains the
    canonical layer analysis reads. When a decision's human_assigned becomes
    True, the caller ALSO writes/keeps a matching CodeApplication (rater kind
    'transformer' if unreviewed-but-above-threshold, 'human' once a person acts)
    so nothing downstream needs to know CodingDecision exists.

    `model_score` is a bare float, deliberately not called a probability in any
    docstring or UI string that reaches a user -- see engines/laya_engine.py for
    why (Laya ships uncalibrated by default; calling an uncalibrated number a
    probability of correctness is a specific, named methodological error this
    project does not want to make silently).
    """
    decision_id: str
    excerpt_id: str
    code_id: str
    run_id: str                                 # FK -> RunManifest
    model_score: Optional[float] = None         # None: human-only, no model opinion recorded
    model_assigned: bool = False                # score >= this run's threshold for this code
    review_status: CodingReviewStatus = "unreviewed"
    human_assigned: Optional[bool] = None       # final verdict; None = not yet reviewed
    reviewer: str = ""
    reviewed_at: str = ""
    note: str = ""


@dataclass
class CodingRunConfig:
    """Alt Survey Flow's coding-run settings, saved with the project.

    JSON in one column (SavedChart's pattern, same reasoning): the settings this
    workflow needs -- text column, which codebook branches use noul vs. choice vs.
    score, per-code confidence thresholds, segmentation, which engine/model --
    will grow, and a schema migration for every new setting is a tax against
    adding one. `spec` shape is documented in engines/laya_engine.py::CodingRunSpec.
    """
    config_id: str
    name: str
    spec: Dict[str, Any]
    created_by: Coder = "human"
    created_at: str = ""


@dataclass
class Descriptor:
    """A per-source metadata *value* (key/value).

    The value is stored as a string; its type (categorical/ordinal/numeric) and,
    for ordinal fields, the level order live on DescriptorField so the analysis
    layer sorts and aggregates correctly.
    """
    source_id: str
    key: str
    value: str


@dataclass
class DescriptorField:
    """Project-level declaration of a descriptor key's type.

    Enables mixed-methods analysis to treat descriptors correctly: ordinal fields
    (e.g. Age_Band, Work_Hours_Per_Week) sort by `ordered_levels` rather than
    alphabetically; numeric fields aggregate as numbers; categorical fields are
    grouped as-is.
    """
    key: str
    dtype: DescriptorType                 # "categorical" | "ordinal" | "numeric"
    ordered_levels: Optional[List[str]] = None   # required for "ordinal"
    description: str = ""

    def sort_key(self, value: str):
        """Return a sort key that respects the declared type."""
        if self.dtype == "ordinal" and self.ordered_levels:
            try:
                return (0, self.ordered_levels.index(value))
            except ValueError:
                return (1, value)          # unknown levels sort after known ones
        if self.dtype == "numeric":
            try:
                return (0, float(value))
            except (TypeError, ValueError):
                return (1, float("inf"))
        return (0, value)                  # categorical: lexicographic


@dataclass
class Memo:
    """A free-text analytic note attached to a code, excerpt, or the project."""
    memo_id: str
    target_type: MemoTarget
    target_id: Optional[str]
    text: str
    author: Coder = "human"          # "human" | "llm_draft"
    #: Set by the store (format v9+); "" for a memo written before memos were dated.
    created_at: str = ""
    updated_at: str = ""


@dataclass
class SavedChart:
    """A figure's *definition*, stored with the project.

    Not a picture. `spec` is the JSON of a `core.chart_spec.ChartRequest`, so
    re-running it draws the chart against the project as it stands now — which is
    what a study that keeps collecting data needs, and what an exported image
    cannot do. `source` records which table it was built over ("codings" or
    "codings_with_descriptors"), because the same shelves mean different things
    over different frames.
    """
    chart_id: str
    name: str
    spec: Dict[str, Any]
    source: str = "codings"
    created_by: Coder = "human"
    created_at: str = ""


@dataclass
class RunManifest:
    """Audit record of one automated pass (written by both mode pipelines)."""
    run_id: str
    package_version: str
    mode: str                        # "survey" | "interview"
    engine: str                      # "transformer" | "llm"
    model: str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    thresholds: Dict[str, Any] = field(default_factory=dict)
    counts: Dict[str, Any] = field(default_factory=dict)
    template_version: Optional[str] = None
    exported_raw_text: bool = False
    exported_embeddings: bool = False


# ── Codebook hierarchy helpers (roll-up semantics, refinement #5) ────────────

def ancestors(code_id: str, codes_by_id: Dict[str, Code]) -> List[str]:
    """Return the ancestor code_ids of `code_id`, nearest parent first.

    Cycle-safe: a malformed codebook with a parent cycle stops at the first
    repeat rather than looping forever.
    """
    out: List[str] = []
    seen = {code_id}
    node = codes_by_id.get(code_id)
    while node is not None and node.parent_id is not None:
        parent_id = node.parent_id
        if parent_id in seen:
            break                          # cycle guard
        out.append(parent_id)
        seen.add(parent_id)
        node = codes_by_id.get(parent_id)
    return out


@dataclass
class Case:
    """A unit of analysis that spans sources — a person, site, or focus group.

    Descriptors attach to a Source, which is right for a survey row but wrong for
    a corpus: one interviewee may have three transcripts, and a focus group is one
    conversation with several speakers. A Case groups the sources that belong to
    the same subject so analyses can be reported per case rather than per file.
    Generalizes the wide-form `respondent_id` grouping to documents (v4).
    """
    case_id: str
    name: str
    kind: str = "person"                  # "person" | "site" | "group" | free text
    description: str = ""


@dataclass
class Annotation:
    """A note on a specific excerpt (span-level), as opposed to a Memo.

    Memos target the project, an analysis view, or a code — the analytic level.
    An Annotation targets one passage: "this is the clearest statement of the
    cost theme", written while reading. Different scope, different table.
    """
    annotation_id: str
    excerpt_id: str
    text: str
    author: str = "human"
    created_at: str = ""


@dataclass
class ExcerptLink:
    """A directed "see also" between two excerpts.

    Qualitative work is full of "this connects to that" observations that are not
    a code and not a memo — a contradiction, an echo, a before/after pair. Kinds
    are free text so the analyst names the relationship.
    """
    link_id: str
    from_excerpt: str
    to_excerpt: str
    kind: str = "see_also"
    note: str = ""


def expand_with_ancestors(code_ids, codes_by_id: Dict[str, Code]):
    """Roll a set of applied code_ids up to include ancestors (SET semantics).

    Implements the default roll-up policy (ROLLUP_IMPLIES_PARENT): applying a
    child implies its ancestors, and each ancestor is counted once regardless of
    how many descendants were applied to the same excerpt. Returns a set.
    """
    result = set(code_ids)
    if not ROLLUP_IMPLIES_PARENT:
        return result
    for cid in list(code_ids):
        result.update(ancestors(cid, codes_by_id))
    return result
