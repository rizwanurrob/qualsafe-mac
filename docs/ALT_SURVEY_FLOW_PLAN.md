# Alt Survey Flow — plan and progress log

**Started:** 2026-09-22, on branch `alt-survey-flow` (off `upstream-fixes` @
`05a76ab`), in `/loop every four hours` — a recurring session job, gone when
this session closes; see "Handoff to the next pass" at the end of this file for
how to pick it up in a fresh session.

**What this is.** An alternative, codebook-first survey coding workflow,
alongside (not replacing) the existing exploratory NLP pipeline: an analyst
defines codes with inclusion/exclusion criteria and examples, a local
structured-decision model ("Laya") scores every response against every code,
and a human reviews the ambiguous cases. Full spec in the commit that started
this branch; the load-bearing requirements are: multi-label by default (one
noul question per code, independent), hierarchical codebooks for accuracy at
scale, a full audit trail (every candidate code, not just accepted ones),
configurable confidence thresholds routing to a Review Queue, scores labelled
as model scores never as probabilities unless empirically calibrated, and Laya
kept as an **optional**, isolated component.

---

## What Laya actually is (researched before writing any code)

Not prior knowledge — verified 2026-09-22 via `convaiinnovations/laya` on
Hugging Face, its own docs site, and PyPI, because the name was unfamiliar and
building against a guessed API would have been worse than not building at all.

- **Real product.** `convaiinnovations/laya`, Apache 2.0, a **non-autoregressive
  encoder** (ModernBERT-large backbone, ~421M params) that answers typed
  questions about a piece of text in one forward pass instead of generating
  text. Three primitives, matching the user's spec's `noul`/`choice`/`score`
  wording exactly: `noul` = calibrated P(true) for a yes/no question, `choice`
  = pick one of N named options with a probability distribution, `score` =
  place a value on an ordinal rubric.
- **`pip install laya>=0.3.3`**, requires **Python 3.10+**, and needs
  **`transformers>=5.x` and `torch~=2.14`** per its published dependencies.
  This is the fact that shaped the whole architecture below — see "Why Laya is
  isolated."
- **Checkpoints:** English (`convaiinnovations/laya`, 512-token context),
  Multilingual (`subfolder="multilingual"`, mmBERT-base, 1024 tokens, 100+
  languages), Typed-decisions (`subfolder="typed-decisions"`, tuned for
  agent/structured-trace decisions rather than open survey text). English is
  the sane default for this workflow.
- **Accuracy is context-budget-limited, not just model-limited.** Laya's own
  docs report `choice` accuracy degrading past roughly 20 simultaneous options
  (a 77-option stress test scored 0.425) and **explicitly recommend a two-step
  coarse-to-fine hierarchy** for large label sets. This is not a nice-to-have
  for this feature — it is *why* `engines/laya_engine.py::
  code_excerpt_hierarchical` exists, and it validates the user's own
  instinct to make multi-label the default (independent noul questions sidestep
  the many-option problem entirely; only `single_label_choice` mode, for
  genuinely mutually-exclusive code sets, runs into the ceiling).
- **Ships over-confident.** Reported Expected Calibration Error 0.466 before a
  per-question-type temperature-scaling fit on domain data, 0.081 after.
  **This project has no such fit yet.** It is exactly what the calibration
  workflow (comparing Laya's scores against a human-coded sample) would
  produce — until that has been run and shown to track the diagonal
  (`analysis/coding_validation.py::calibration_curve`), a Laya score is a
  **model score**, never a probability, in every field name and (eventually)
  UI string. This rule is stated in `core/model.py::CodingDecision` and
  `engines/laya_engine.py`'s module docstrings so it can't drift as the code
  is extended.
- **CPU feasibility: inferred, not confirmed.** Laya's own performance numbers
  (33ms/question, 7.2ms batched) are GPU (T4) figures; nothing in its docs
  states whether CPU inference is supported or how slow it is. It is a 421M-
  parameter BERT-family encoder doing single-forward-pass classification —
  architecturally the same shape as this codebase's existing zero-shot engine
  (`facebook/bart-large-mnli`, 1.5GB, already runs CPU-only for every user of
  this tool), so CPU inference should work, just far slower than the quoted
  GPU numbers. **Unverified until a real install runs on real hardware** — see
  "Open questions."

Sources fetched during research (not reproduced verbatim; summarized above):
`laya.convaiinnovations.com`, `huggingface.co/convaiinnovations/laya`, and web
search results surfacing `pypi.org/project/laya/`'s install/API description.

---

## Why Laya is isolated, not `pip install`ed into the main app

QualSafe's existing engine is hard-pinned — `transformers>=4.40,<5.0`,
`torch>=2.2,<3.0`, `numpy>=1.24,<2.0` — specifically so the zero-shot/sentiment
pipeline stays **byte-identical** run to run. That guarantee is load-bearing
throughout this codebase: kappa reproducibility, `run_manifest.json`'s
provenance claims, most of the test suite's determinism story. `pip install
laya` would want `transformers>=5.x` / `torch~=2.14` in the *same*
environment, silently upgrading the packages the existing engine is tested
against.

So Laya runs in its **own Python environment**, created by
`tools/setup_laya_env.py` (a plain `venv`, `pip install laya>=0.3.3` into it —
the one place outside `engines/laya_worker.py` that ever touches the `laya`
package), and talked to over a **subprocess this app launches**
(`engines/laya_client.py` → `engines/laya_worker.py`), never imported
in-process. This mirrors two patterns already in this codebase for the same
reason: `core/model_manager.py` shells out to `tools/download_models.py` so
the app process never has `HF_HUB_OFFLINE` lifted, and Ollama is a separate
server process the app talks to over HTTP rather than an in-process library.

**The wire protocol between the app and the worker is this project's own**
(JSON Lines over stdio — one request, one response, per line), not Laya's own
undocumented `pip install "laya[server]"` HTTP mode, because that mode's exact
request/response shape was never confirmed by the research above. Writing both
sides of a protocol this project controls removed that unknown; the only
unverified call left is the one line `laya_worker.py` makes into the package
itself (`laya.Router(preload=True).predict(state, questions)`), which was the
piece of documentation most consistently described across independent
sources.

---

## Locked design decisions (for future passes to keep, not re-litigate)

1. **`CodingDecision` is a new, separate table — not a repurposed
   `CodeApplication`.** This project's convention is that a `CodeApplication`
   exists only for an *accepted* code ("no code" = absence of a row, not a row
   saying no — see `core/adjudication.py`). That convention is correct for the
   analytical layer every existing frequency/co-occurrence/crosstab/kappa
   function reads, and must not change. But the human-in-the-loop audit trail
   the user asked for — *every* candidate code Laya was asked about, including
   ones scored low or rejected — needs the fuller record `CodeApplication` was
   never meant to hold. `CodingDecision` sits above it; when a decision's
   `human_assigned` becomes true, the caller also writes/keeps a matching
   `CodeApplication` so nothing downstream (frequency, co-occurrence, kappa,
   exports) needs to know `CodingDecision` exists at all.
2. **Mutual exclusivity (`choice`) is a per-run/per-branch setting, not a
   per-code property.** A code doesn't "know" it's mutually exclusive with its
   siblings; that's a relationship the analyst declares for a group. Modeled
   via `CodingRunSpec.mode` (`"multi_label_noul"` default, or
   `"single_label_choice"`), applied per level of the hierarchical walk.
3. **`score`-typed codes are not theme codes.** A code with
   `decision_type="score"` produces an ordinal rating (`rubric_levels`), not a
   yes/no assignment, and is never folded into multi-label roll-ups or a
   `choice` question. Kept as a `Code` (reuses the existing hierarchy/CRUD)
   rather than a new entity, because a rubric still needs a name, definition,
   and a place in the tree.
4. **Hierarchical coarse-to-fine walk, always available.** `Code.parent_id`
   already gives real hierarchy (v3's "flexible codebook hierarchy" decision).
   `code_excerpt_hierarchical` scores one level, then descends only into
   children of codes that were **not** `confident_no` — directly implementing
   Laya's own documented mitigation for its >20-option accuracy ceiling.
5. **Segmentation reuses `core/text_units.split_sentences`**, never
   re-implements sentence splitting. Sentence-group chunks, 1-sentence overlap
   by default, offset-exact (the same `text[start:end] == segment` invariant
   every other span in this codebase carries). An oversized single sentence is
   kept whole, never truncated — truncating a codeable unit invents a boundary
   the source doesn't have.
6. **De-duplication across segments takes the max score for a code**, not an
   average — a response either does or doesn't touch a theme; averaging a real
   mention against a segment that never discusses it would dilute genuine
   evidence.
7. **`route_by_confidence`'s `[low, high)` band is the one, shared definition
   of "ambiguous"** — used identically by `engines/laya_engine.py` when
   deriving `model_assigned` and by `core/project.py::Project.review_queue`
   when selecting what a human still needs to see. They must never diverge, or
   an item could be auto-assigned by one code path and simultaneously judged
   to need review by another.
8. **Validation metrics are additive to `analysis/agreement.py`, not a
   replacement.** Precision/recall/F1 answer *which kind* of mistake a code is
   making (over- vs. under-applying); kappa remains the reliability number.
   Reported side by side in `per_code_validation`, sharing the same
   `min_support` insufficient-N guard.

---

## Schema (v6 → v7, additive, migration `_migrate_6_to_7`)

- `codes` gains five columns, all defaulting to "behaves exactly as an
  existing code always did": `inclusion_criteria`, `exclusion_criteria`,
  `examples_json`, `decision_type` (default `'noul'`), `rubric_levels_json`.
- New table `coding_decisions`: the per-(excerpt, code, run) audit trail —
  model score, model verdict, review status, human correction, reviewer,
  timestamp, note. Unique on `(excerpt_id, code_id, run_id)` so re-running a
  coding pass over the same item replaces rather than duplicates (the
  resumability the workflow promises).
- New table `coding_run_configs`: named, JSON-spec run settings (`SavedChart`'s
  own pattern — spec as one JSON column so it can grow without a migration per
  field).
- Both new tables are in `Project._TABLES`, so `export_json`/`import_json`
  (the portable-project archive) already carry them.

## What is built and tested (Phase 0, this pass)

All of it runs fully offline; nothing here imports `laya` or spawns a real
subprocess in the test suite.

| Piece | File | Tests |
|---|---|---|
| Schema + migration | `core/model.py`, `core/project.py`, `core/migrations.py` | `tests/test_schema_v7_structured_coding.py` (23) |
| Segmentation | `core/segmentation.py` | `tests/test_segmentation.py` (9) |
| Coding logic (questions, hierarchy, thresholds) | `engines/laya_engine.py` | `tests/test_laya_engine.py` (17) |
| Isolated-worker protocol | `engines/laya_worker.py` | none — see "Open questions" |
| Subprocess client | `engines/laya_client.py` | `tests/test_laya_client.py` (12, fake process) |
| Isolated-env installer | `tools/setup_laya_env.py` | `tests/test_setup_laya_env.py` (10) |
| Install/detect wrapper | `engines/laya_setup.py` | `tests/test_laya_setup.py` (8) |
| Validation metrics | `analysis/coding_validation.py` | `tests/test_coding_validation.py` (12) |

**Full suite confirmed** (2026-09-22): the only failures were one test that
hardcoded `schema_version == 6` literally (fixed — see commit `26ac7eb`,
same pattern this project already corrected once for `test_schema_v4.py`)
and six pre-existing `tests/test_data_charts_page.py` failures (a Streamlit
`AppTest`/`session_state` incompatibility) confirmed, by reverting this
branch's changes and re-running that file alone, to predate this work
entirely — unrelated to Alt Survey Flow, out of scope for this branch.

`MockLayaEngine` (in `engines/laya_engine.py`) is a deterministic offline
stand-in — a hash of (text, code instructions) mapped to [0, 1] — used by the
tests above and available for building the UI before Laya is actually
installed anywhere. It must never be mistaken for real coding; the UI is
responsible for labelling a mock-engine run as a demo.

## Open questions / unverified (do not treat as settled)

1. **`engines/laya_worker.py`'s one call into the real package —
   `laya.Router(preload=True).predict(state, questions)`, and the shape of the
   `choice` question's `distribution` field (list vs. dict-by-option;
   `_distribution_items` in `laya_engine.py` handles the dict case
   defensively and is the first place to look if a real response doesn't
   parse)** — has never run against an installed `laya`. First real install
   should expect small fixes here, not a redesign; the surrounding protocol
   (stdio framing, lifecycle, error handling) is this project's own code and
   needs no correction regardless.
2. **CPU-only inference speed** is inferred from the model's architecture
   (see above), not measured. `tools/check_local_llm.py` (built for the
   portable-llm branch's Ollama-alternative work) is the template for a
   similar `tools/check_laya_speed.py` once Laya can actually be installed
   somewhere to measure it.
3. **No real install has happened anywhere in this project.** Deliberately —
   installing `laya` even into a throwaway venv on the *development* machine
   risked doing so before the isolation boundary existed to install it
   correctly into. The isolated-venv creation path (`tools/setup_laya_env.py`)
   is tested by mocking `subprocess`/`venv`, never by actually running pip.
4. `engines/laya_setup.CHECKPOINTS`' `context_tokens` figures are taken
   directly from Laya's docs and not independently confirmed.

## First real run (2026-10-05, Windows laptop, CPU only) — answers to the open questions above

Laya 0.3.28 was installed into the isolated environment and run for real, offline,
on `data/sample_survey_education.csv` (40 answers, 5 codes written by hand).

1. **The worker's one call into the package was wrong, and is fixed.**
   `laya.Router(preload=True)` loads all three checkpoints (about 1.16 billion
   parameters) and wants the two this tool never uses; it hung for over 12 minutes at
   4.8 GB. The worker now calls `laya.load("convaiinnovations/laya", device="cpu")`
   and `agent.predict(state, questions)`. The `noul` answer shape was as assumed
   (`{"noul": 0.80, ...}`); `choice` has not been run.
2. **The model download was implicit; it is now an explicit, consented step.** The
   worker fetched the checkpoint from the Hugging Face Hub on first start, so analysis
   could reach the network. `tools/setup_laya_env.py` now downloads the English model
   (about 0.8 GB, not the other two) as part of the install, and the worker starts
   with `HF_HUB_OFFLINE=1`. Measured size on disk: environment 813 MB + model 804 MB.
3. **CPU speed, measured:** about 100 to 114 s to load the model; about 2.7 s per code
   per answer. 40 answers x 5 codes took 543 s in all. A thousand answers with five
   codes would take about four hours, so the screen shows an estimate before a run.
   The start and per-answer timeouts (120 s and 30 s) were too tight and are now 600 s
   and 120 s.
4. **How a code is worded matters a great deal.** Twelve answers judged by hand
   (a small test, not a validation), the right code ranked first for:
   - statements ("Assign when: ... Do NOT assign when: ...", the original wording): 2 of 6;
   - "Is this answer about X? That means <count-it rule>.": 9 of 12 (mean gap +0.24);
   - the same with the leave-out rule added: 5 of 12 (mean gap +0.06).
   `Code.as_laya_question()` now asks the first form. The leave-out rule is kept for the
   person reviewing and is only sent to the engine if switched on (`send_exclusions`).
5. **Still not known:** accuracy on real data. Nothing here is a validation. That is
   what the calibration step (Update 3, item 3.15) is for: compare with a human-coded
   sample, per-code Cohen's kappa beside percent agreement and prevalence.

## Correction (2026-10-06): Laya does not need a separate environment

The section "Why Laya is isolated, not `pip install`ed into the main app" rested on Laya
needing transformers 5.x and torch 2.14. Laya's published requirements are only torch 2.0 or
newer, transformers 4.48 or newer and numpy 1.20 or newer, and this app's pins (transformers
4.57, torch 2.13, numpy 1.26) meet all three. Tested on a real install: the same 12 answers
scored identically to two decimals (9 of 12 right, mean gap +0.24) on transformers 5.18 /
torch 2.14 / numpy 2.5 in a separate environment, and on the app's own libraries with only the
Laya package added; a full run of 40 answers x 5 codes gave the same 16 applied codes.

So the install is now: `pip install --no-deps --target ~/.qualsafe/laya_pkg laya==0.3.28`
(a pinned package, under 1 MB, nothing else changed), plus the English model (0.8 GB). The
worker is still a separate process (it holds up to 4.8 GB, can crash on its own, and runs with
`HF_HUB_OFFLINE=1`), but it runs with this app's own Python and libraries, with the package
folder on `PYTHONPATH`. It needs the analysis engine (torch, transformers) installed first;
the status says so (`needs_engine`). The packaged app runs on `pythonw.exe`, so the worker and
installer use the `python.exe` beside it and no console window. The earlier note that a
separate Python 3.10 would be needed was wrong: the installer ships a full Python 3.12 with pip.

## Phase 1 — Streamlit tab (done, same day as Phase 0)

`app/alt_survey_flow.py`, wired into `SURVEY_NAV` in `streamlit_app.py`
(survey mode only — this is not an interview-mode feature). Reuses the
Data-Setup-mapped text column by default, with an override; reuses the app's
one active project if there is one, or mints its own the first time it needs
one (Alt Survey Flow works standalone, without the exploratory pipeline having
run first — verified by a test that never sets `active_project_path`).

- **Codebook editor**: add/edit a code's name, definition, inclusion/exclusion
  criteria, examples, decision type (noul/score + rubric), parent. Does not
  duplicate the existing Codebook page's rename/merge/delete/version-history —
  those stay there; this page only adds the structured-coding fields.
- **Engine status panel**: mirrors `render_ollama_setup_panel` exactly
  (`engines/laya_setup.py` already had the matching shape) — install/detect,
  a real "Install Laya" button running the isolated-venv installer with a
  spinner.
- **Run configuration**: mode (multi-label default / single-label), the
  confidence-band slider, segmentation budget, saved as a named
  `CodingRunConfig`.
- **Run**: resolves a real `LayaClient` if installed and startable, else
  `MockLayaEngine` with a visible "demo engine" notice (never silently) —
  `_resolve_predict_fn`, the `engines.factory.resolve_theme_engine`-style
  fallback this file's earlier draft called for. Progress bar via
  `run_coding_pass`'s `progress_callback`; a Cancel button sets a session flag
  the run loop checks; re-running the same run name resumes (skips
  already-coded excerpts) unless "force re-code" is ticked.
- **Review Queue**: reads `Project.review_queue`, accept-all or per-item
  accept/reject/flag, writing through `Project.review_coding_decision` (which
  now also syncs `code_applications` — see the orchestration commit).

**Verified against a real Streamlit render**, not just imported: two new
behavioral tests in `tests/test_app_smoke.py` drive the actual widgets (add a
code, confirm the demo-engine notice, run coding, confirm decisions were
written; separately, confirm the standalone project-creation path with no
active project). Both pass. The full `test_app_smoke.py` (63 tests, every
survey/interview page) still passes — the page's addition to `SURVEY_NAV`
required updating that file's own page list, which is itself asserted against
the shell (`test_the_page_lists_here_match_the_shell`), so a future page
added to one and not the other fails loudly rather than silently going
untested.

**Not built in Phase 1** (deliberately, to keep this landable in one pass):
hierarchical drag-to-reparent in this page's own editor (use the existing
Codebook page for that — codes are shared, so reparenting there applies
here too); a codebook-branch-level mode override (mode is currently one
setting for the whole run, not per parent); exporting the run's own
decisions/review state as a chart or table on this page (the data is all
queryable via `Project.coding_decisions_table`, just not surfaced here yet).

## Explicitly not done yet (future passes — this file is the handoff)

- **Phase 2 — Qt tab**, once Streamlit has been used for real (per the user's
  own answer: "Both, Streamlit first"). Mirror this page's structure in
  `qualsafe_qt/views/`, reusing every `engines.laya_engine`/`core.project`
  function unchanged — none of Phase 0 or Phase 1's logic is Streamlit-specific
  except `app/alt_survey_flow.py` itself.
- **Phase 3 — calibration workflow UI**: pick/import a human-coded sample,
  run `per_code_validation` + `calibration_curve`, and — only after a curve is
  actually shown to track the diagonal — the explicit, logged decision to
  start describing scores as calibrated probabilities for that project.
- **Exports.** CSV/XLSX carrying original response, every candidate code, its
  score, review status, final code, and validation info — extends
  `exports/bundle.py`/`exports/excel_workbook.py` rather than a new module;
  not started.
- **The real install + hardware spike** (see "Open questions" #2–3).

## Handoff to the next pass

This session's `/loop` cron (`45ff1fc2`, every 4 hours) dies when this session
closes and auto-expires after 7 days regardless. If a fresh session picks this
up: read this file top to bottom first, then `git log --oneline` on
`alt-survey-flow` (branched off `upstream-fixes`, currently only this pass's
commit(s)). Do not re-research "what is Laya" — it's all above. Start Phase 1.
