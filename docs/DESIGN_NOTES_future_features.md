# Design notes — candidate features (post-Phase-2)

Forward-looking design, not committed work. Two features requested by the PI on
2026-07-16, captured here with concrete hooks so a later implementer starts from
architecture rather than a blank page. Both align with what Phase 1 built (the
`.qnw` store as the durable project of record) and with the multi-coder
groundwork planned for Phase 2.5 — neither is a rewrite.

---

## Feature A — Team task distribution (split coding across people)

**The ask:** a team wants to divide a coding job — by question, or by rows — so
several people work in parallel.

**The distinction that drives the design.** "Distribute" means two different
things, and the tool should be explicit about which:

- **Partition (throughput).** Disjoint assignments: A codes rows 1–200, B codes
  201–400; or A takes Q1–Q3, B takes Q4–Q6. Goal is to get through volume. There
  is *no* overlap, so there is no inter-rater reliability to compute — and the UI
  must not imply there is.
- **Overlap (reliability).** The same items are coded by ≥2 people on purpose, to
  measure agreement. This is the IRR path (Phase 2.5 / kappa), already partly
  planned as the "second-human import" flow.

A real project usually wants **both**: a small overlapping "calibration" set that
everyone codes (for κ), plus a partitioned remainder for throughput. The
assignment model below supports that as the natural case rather than a special
one.

### Where it hooks into the current architecture

The store already carries the hard parts. `CodeApplication` has `rater_id` +
`coder`; `Rater` exists; `replace_applications_for_rater` (Phase 1.1) already
scopes a save to one rater without touching others; `find_source_by_response_id`
gives a stable join key; and JSON export/import already exists as an interchange
format. What's missing is only the *assignment* layer.

1. **An assignment concept.** New lightweight table (needs a migration — the
   harness exists now):
   ```
   assignments(assignment_id, rater_id, scope_type, scope_value, mode)
     scope_type ∈ {"question", "source_id", "row_range"}
     mode       ∈ {"partition", "overlap"}
   ```
   The Lab filters the coding sample to "items assigned to me" via this table.
   `scope_type="question"` reuses the Lab's existing question-scoping directly.

2. **Two collaboration topologies** — pick based on the team's IT reality:
   - **Copy + merge (recommended default).** Each coder gets their own `.qnw`
     copy, codes their assignment, and the pieces are merged back. The merge is
     `import_json` per coder, mapping each coder to a distinct `rater_id`
     (`human_alice`, `human_bob`). This is the safe path — no shared-file locking,
     works over email/USB, and the audit trail stays clean because each rater's
     applications are already isolated. **The one rule:** merges must be
     idempotent and rater-scoped (reuse the `replace_applications_for_rater`
     pattern), so re-importing a coder's file twice doesn't double their codes.
   - **Shared store.** One `.qnw` on a network drive. Tempting, but SQLite over
     SMB/NFS has real locking hazards — do NOT do this without WAL mode, a
     coordinating lock, and Windows-share testing. Treat as a later, gated option.

3. **A coverage view.** "N items, X assigned, Y coded, Z double-coded." The
   double-coded subset is exactly the input to the Phase 2.5 κ path — so overlap
   assignments feed reliability for free.

### Pitfalls specific to this feature

- **Item identity across coders' copies.** Two people's `.qnw` files mint
  different `source_id`s for the same response. Merge MUST reconcile on
  `(response_id, question_text)` (the Phase 1 join), never on `source_id`.
- **Codebook divergence.** If Alice invents an emergent code "Cost worry" and Bob
  invents "Financial stress" for the same idea, the merge can't know they're one
  code. Surface a post-merge "reconcile similar codes" step (the deferred
  Jaccard/embedding merge-suggestion feature is the tool for this) rather than
  auto-merging.
- **Don't compute κ on a partition.** If assignments are disjoint, there is no
  shared item set; showing an agreement number there is meaningless. Gate the
  Agreement tab on the existence of an actual overlap set (it already needs
  shared items — make "no overlap" an explicit, explained empty state).

### Rough sequencing

Small enough to slot after Phase 2.5, which delivers the second-human import and
`rater_labels` this builds on. Order: assignment table + migration → Lab
"my assignment" filter → merge-with-rater-mapping → coverage view. The overlap→κ
path is then already wired.

---

## Feature B — Cross-question context for a wide-form respondent

**The ask:** in wide form, one row = one respondent answering several questions.
Does it make sense to consider a respondent's answers *together* — using what they
said in Q3 to inform how Q1 is read?

**Assessment: yes, and it's the survey analogue of interview regrouping.** A
respondent's answers are facets of one person's experience; "what's hardest" and
"what would help" are often the same story split across two columns. Reading them
jointly is exactly the move interview mode already makes when it regroups a
wandering transcript by theme — here the "wandering" is across columns instead of
across turns. So the capability already exists in spirit; this points it at survey
data.

But it is **not free**, and it changes the unit of analysis, so it must be opt-in
and engine-aware.

### The architectural hinge: respondent_id vs response_id

This is the crux, and the current code has a latent tension worth stating plainly.
`reshape_wide_to_long` carries `id_column` through the melt, so after melting, a
respondent's id **repeats** across all their question-rows. But `prepare_dataset`
turns `id_column` into `response_id`, which is meant to be the *per-answer* unique
key (it's the join key for the store and for agreement). A repeating respondent id
used as response_id collides — which is precisely what the Phase 0.6
duplicate-`response_id` warning now flags.

The fix is to separate the two identities:

- **`respondent_id`** — the wide row / person. Repeats across their answers.
  Becomes the grouping key.
- **`response_id`** — one answer. Unique. Naturally `f"{respondent_id}::{question}"`
  in wide form.

Once melted rows carry both, the store's `Source.metadata` gains `respondent_id`
alongside the existing `response_id` + `question_text`. That single addition
unlocks everything below, and it also *resolves* the duplicate-id warning for wide
data (the warning becomes "you mapped a respondent id where a response id was
expected — did you mean wide mode?").

### What it enables (in increasing cost)

1. **Respondent grouping in outputs (cheap, no model change).** `Project` gains
   `list_sources_by_respondent()`; the store already has everything needed. A
   "respondent view" shows all of one person's coded answers together. Pure
   analytics — no re-coding, no bias risk. Do this first; it's most of the value.

2. **Respondent-level descriptors and co-occurrence (cheap).** Co-occurrence
   currently means "codes on the same *response*." A `unit="respondent"` option
   would mean "codes anywhere in the same *person*" — a legitimately different and
   often more interesting question (themes a person raised across the whole
   survey). Mirrors the interview co-occurrence caveat already documented. Just a
   grouping-key swap in `analysis/cooccurrence.py`.

3. **Cross-question context at coding time (expensive, LLM-only, opt-in).** Give
   the LLM engine all of a respondent's answers as context when coding one:
   *"Here is everything this person said across the survey; code THIS response."*
   This is where the value and the risk both live:
   - **Value:** disambiguates terse answers ("same as above", "it") that are
     meaningless in isolation.
   - **Risk:** it changes the unit of analysis and can bias coding — a response
     gets a code justified by *other* answers, not its own text. That breaks the
     evidentiary link between an excerpt and its code, which is the thing
     qualitative rigor rests on.
   - **Constraint:** LLM engine only. The transformer engine codes each response
     independently by design; forcing cross-context there is a category error.
   - **Guardrail:** record on each `CodeApplication` whether cross-question context
     was used (a provenance flag), and default it OFF. An analyst should be able
     to see which codes were assigned "in isolation" vs "in respondent context"
     and filter accordingly.

4. **Per-respondent summary (expensive, LLM-only).** Literally interview mode's
   per-theme summarizer pointed at a respondent's answers — a short profile with
   verified verbatim quotes (reuse `interview/quotes.py`'s quote-verification so
   nothing is hallucinated). This is the strongest "treat a wide respondent like a
   mini-interview" framing, and it reuses interview infrastructure almost wholesale.

### Pitfalls specific to this feature

- **Never silently change the unit.** κ, prevalence, and co-occurrence all mean
  different things at response-level vs respondent-level. Record the `unit` in the
  manifest and refuse cross-unit comparisons (the interview work already
  established this discipline for sentence-vs-response units).
- **Wide-only, mostly.** Long-form data can have a respondent_id too, but the
  feature is motivated by wide surveys. Don't force a respondent grouping onto
  long data that lacks a real respondent key.
- **Context ≠ endorsement of bigger context windows.** Resist "just feed the whole
  survey." Bounded, respondent-scoped context is the point; more than that is
  cost and bias with no methodological gain.

### Rough sequencing

Step 1 (respondent grouping) and step 2 (respondent-unit co-occurrence) are cheap,
low-risk, and independently useful — good v3.x candidates once `respondent_id` is
threaded through `reshape_wide_to_long` + `prepare_dataset` + `Source.metadata`.
Steps 3–4 (LLM cross-context coding, per-respondent summaries) are v4-class, share
the interview engine, and need the provenance/guardrail work above before they're
safe to ship.

---

## Relationship to the current roadmap

- Feature A extends **Phase 2.5** (multi-coder groundwork) into a full workflow;
  it should follow it, not precede it.
- Feature B step 1–2 depend only on threading `respondent_id` through ingestion —
  a small, self-contained change that also cleans up the wide-form
  duplicate-`response_id` ambiguity. Steps 3–4 reuse the interview engine and
  belong with the v4 "method depth" work.
- Neither changes the locked design decisions (kappa-only IRR; local-first;
  whole-response excerpts as the default unit).
