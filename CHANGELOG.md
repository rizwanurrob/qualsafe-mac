# Changelog

## Unreleased

* **Update 3 on the web (4.13.0 test builds ux3 and later): one thing at a time.** The browser version opens
  on Home with three colour-coded activities (Surveys, Charts, Interviews), each a short list of steps with
  one main button and at most seven controls in view, matching the desktop screen for screen. Saved place
  per activity with *Continue* and *Start over*, plain words throughout, Help with the shared articles,
  tips, a first-visit tour and short clips. Charts draw in the browser (a Vega-Lite preview) and are saved
  as pictures by the server's renderer.
* **Web, Interviews:** after an import, QualSafe proposes who the interviewer is and you confirm it (*Who is
  speaking?*); an interview guide can suggest codes, which you can read and remove. Analysis caveats are one
  sentence beside the figure with the full text under *Why?*.
* **Web installer.** A separate Windows installer for the browser version (per-user, no administrator
  password, runs on this computer only, opens in the browser); the desktop installer carries no web server.
  Both pin `pyarrow` below 26, which needs NumPy 2 and broke every table on a fresh install.
* **The analysis engine installs from inside the program** (Settings, Models), into a folder of your own;
  see `CHANGELOG_DESKTOP.md`. The web shares the same installer.

* **Human-vs-engine κ says what it describes.** Every comparison of a person
  with the analysis engine (reports, and now the desktop screen) states that
  κ covers the responses the person coded, and measures whether those were
  chosen for difficulty: the engine's no-code rate on them against the rest,
  with a Newcombe interval. A review-queue sample is called out as harder than
  the rest, and κ on it as understating agreement.
  `core.agreement_pairs.compare_with_engine` compares a chosen coder and run.
* **The uninstaller finds a moved model cache** (`HF_HOME`, `XDG_CACHE_HOME`,
  `HF_HUB_CACHE`, resolved as `huggingface_hub` does), and refuses to remove a
  drive root, the home folder or the program folder if one is set by mistake.
* `CITATION.cff` cites the current desktop version and names the repository; a
  test keeps its version in step. `pyproject.toml` has the current email.

## v4.13.0 — September 2026: the audit trail

Plan: `V7_PLAN.md`, "Update 2, revised after 4.12" (project folder).
**Store format v8 → v9** (additive: `project_events`; memos gain dates).

* **Prevalence with 95% intervals.** The Code × Descriptor view (both builds)
  gives each group's prevalence a Wilson interval and compares two groups or
  waves with a Newcombe interval, checked against the published examples.
  Small groups are flagged, one coder can be chosen, and the caveat travels
  with every table: an interval sees sampling noise, never a change in the
  coder.
* **A dated record of every analytic decision.** Code created, renamed,
  redefined (before and after), moved, merged or deleted; memos; adjudication;
  imports; merges; auto-coding; erasure (by hash). It never holds response
  text or ids. Before this, a changed definition left no dated trace, and
  memos had no dates at all.
* **The audit trail export** (Word and Excel, both builds): that record plus
  everything that was always dated, oldest first. It's what a
  confirmability audit asks for. No response text, no ids, no document
  titles; memo text only on request.
* **Alt Survey Flow calibration.** A random sample coded by a person on every
  code gives per-code precision, recall and κ, a recommended confidence band
  (applied in one click), a reliability table, and a decisions export. The
  methods appendix reports it, and says so if the run was the demo engine.
* **Consistent pseudonyms** in the web PII gate, with the re-identification
  key offered once and never stored.
* **Fixed along the way:** the run manifest always said no masking had been
  applied, even after it had; masking wasn't offered for files whose only
  identifiers were names in prose; masking a bracketed phone number left a
  stray "(".

## v4.12.0 — September 2026: numbers you can defend

Fixes from the 2026-09-25 codebase review
(`CODEBASE_REVIEW_2026-09-25.md` in the project folder); every one was
reproduced first, and each commit carries the tests that failed before it.
**Store format v7 → v8** (additive: `rater_coverage`, `document_coverage`).

* **Kappa no longer drops "no code applies" (F1).** The store kept only the
  codes a rater applied, so a response a coder read and left uncoded vanished
  from the comparison, taking the disagreements with it (reproduced: true
  0.62, reported 1.00). The review record now keeps them. Coders from before
  v8 are flagged "likely overstated", never backfilled by guessing.
* **Every export compares the same two raters, chosen by role (F5).**
  Alphabetical choice had the Word, Excel and bundle exports comparing the
  adjudicated subset after one reconciliation. On real projects, where each
  run's engine has its own id, the Word, Excel and appendix exports never
  found the engine at all. Caveats now travel with every table, and the
  insufficient-N rule applies everywhere (no more kappa at support 1).
* **Span coding has agreement (F4)**, on sentences or paragraphs of documents
  both coders marked finished, in both builds. Still kappa.
* **Ids stay ids (F3).** Import a second coder read "000123" as 123 and put a
  colleague's codes on the wrong respondent, and refused Excel-saved files.
  Erasing respondent "000123" kept their row in the run CSVs.
* **Demo-engine runs are labelled, separable and removable (F2)**, and can no
  longer block a real run with the same name.
* **The PII scanner finds names, addresses and room numbers in answers (F6)**
  where a title or relationship anchors them, and says what it cannot see.
* **The test suite leaves your settings alone and finishes (F8).** Qt tests
  wrote the installed desktop app's real settings. The "hang" was windows
  never being deleted: each re-theme re-polished every one (129 s with
  eight alive). The full suite now runs in one process in about 12 minutes.
  `pytest-timeout` added.

### Also in 4.12.0: Alt Survey Flow, a preview (structured, codebook-based coding)

Marked *preview* in the app: Laya has never been installed anywhere this has
run, so every run so far used the demo engine. Plan and progress log in
`docs/ALT_SURVEY_FLOW_PLAN.md`. An alternative, codebook-first survey coding
workflow alongside (not replacing) the exploratory pipeline: define codes with
an inclusion/exclusion boundary, run a local structured-decision engine
("Laya", optional and isolated) against every response, review what it's
unsure about.

Store format v6 → v7 (additive: five new columns on `codes`, two new tables,
`coding_decisions` and `coding_run_configs`; every existing project opens
unchanged). New `core/segmentation.py`, `engines/laya_engine.py`,
`engines/laya_client.py`, `engines/laya_worker.py`, `engines/laya_setup.py`,
`tools/setup_laya_env.py`, `analysis/coding_validation.py`. Laya itself is
never installed by anything in this codebase yet, including its own tests —
`MockLayaEngine` stands in throughout, matching this project's torch-free,
offline, deterministic test discipline. See the plan doc for what's verified
against Laya's real documentation versus still unconfirmed.

**New "Alt Survey Flow" page in the web app** (survey mode nav, after
Iterative Labeling Lab): codebook editor for the structured fields, a Laya
install/status panel, run configuration (mode, confidence thresholds,
segmentation), a run button with progress/cancel/resume, and a Review Queue
(accept-all or per-item accept/reject/flag). Works standalone — it mints its
own project if none is active, rather than requiring the exploratory pipeline
to have run first. Falls back to a clearly-labelled demo engine when Laya
isn't installed, never silently. Not yet in the desktop (Qt) app.

### Also in 4.12.0: Data Charts (a chart builder for any spreadsheet)

New package `core/chartbuilder/` and two front ends: a **Data Charts** page in the web
app and a **Data Charts** tab in the desktop app (desktop 0.99.8). Engine version and
store format are unchanged: charting is not part of the analysis engine that a methods
appendix cites, and no `.qnw` table was added.

* **Layers, as asked.** Loader (CSV/TSV with delimiter and encoding detection, XLSX/XLS with
  a sheet picker), profiling (types, missing counts, warnings), cleaning (missing tokens,
  whitespace), transformation (filters, exclude/relabel/combine), survey parsing (Likert
  scales, top/bottom boxes, select-all, free text), aggregation into one canonical
  table (`category, group, count, denominator, percent, value, valid_n, missing_n,
  sort_order, display_label, color`), theme engine, a Vega-Lite renderer, and export. The
  UIs call these and decide nothing themselves, so the web page and the desktop tab draw
  the same chart from the same choices.
* **Questions.** Single choice; matrix/Likert (per-item base, scale order, top/bottom
  boxes labelled `70% (7/10)`, never valid N as the count); select-all with known-choice
  matching so `Relationships with friends, family, partners, or roommates` stays one
  answer, and unmatched pieces reported not charted; free text (response count, keyword
  frequency, response export).
* **Charts.** Vertical/horizontal bar, grouped, stacked, 100% stacked, pie, donut,
  heatmap, histogram, box, scatter, line and area. A number starts as a histogram and a
  date as a line; a pie is never suggested just because a field is categorical.
* **Rules that decide the numbers.** Blanks and the listed tokens never enter a denominator
  unless chosen; excluded categories leave the base; relabels that would merge two
  categories are refused; similar labels are reported, never merged; a percent shown with
  its numerator and base.
* **Export.** PNG at 96 to 600 DPI (a 16:9 figure at 300 DPI is exactly 4000 x 2250),
  SVG, PDF, transparent or white; summary table as CSV/XLSX; Windows-safe file names that
  keep the full path under 260 characters.
* **Themes and saving.** QualSafe default by default (gold, blue, silver, light purple,
  semantic colours for ordered scales, white border between same-colour neighbours), three
  other built-ins, custom themes and per-category colours; charts saved with their
  choices (never rows), reproducible on the same file structure and honest about what did
  not fit on another. Stored in the user's data folder.
* **Dependencies.** `xlrd` added for legacy `.xls`. The desktop installer no longer prunes
  `vl-convert` (about +79 MB installed, about +19 MB in the compressed installer), because
  every figure and export goes through it.

Guide: `docs/CHART_BUILDER_GUIDE.md`. Not yet done: a run on a Mac, and a look at the
desktop tab with real fonts on a real Windows machine (the automated tests draw offscreen).

## v4.11.1 — August 2026: the run manifest stops carrying your folders too

Having found that a `.qnw` shipped the author's filesystem, the obvious next
question was what *else* leaves this program. The run manifest had the same
defect one artifact over.

`input.file` recorded the **absolute path** of the analysed file, and a manifest
is written into every output folder and travels with it — to a supervisor, a
co-author, a submission. Nothing reads the field back; the only reference to it
anywhere is a comment. It now records the file's **name**, which is what "which
file produced this" actually needs. Provenance is not weakened: the run
directory already holds a snapshot of exactly what was analysed, which is a
better record than a path that may since have moved.

**A note on how nearly this was missed.** The first detector written for it
searched for a byte pattern containing an invalid Python escape, and duly
reported "no absolute user paths" for a file full of them. It was caught only
because a second, independent check for the literal private strings fired at the
same time. A scanner that reports clean is indistinguishable from a clean file,
so a privacy check has to be shown firing on a known-bad input before its
silence means anything.

**Still unchecked:** `.qdpx`, the Word methods appendix and the Excel workbooks.
The attempt this release failed on a wrong call signature rather than finding
them clean, and an unfinished check is not a passed one.

## v4.11.0 — August 2026: a shared project no longer carries your filesystem

**Store format v5 → v6.** Existing projects are migrated when opened.

The Streamlit checkbox calls a `.qnw` "a portable project file you can reopen or
share". The desktop offers it the same way. So the question worth asking is what
a recipient gets that the sender did not mean to send.

Every imported document recorded the **absolute path** it came from. A real one
is not neutral:

```
C:/Users/jsmith/OneDrive - State University/IRB-2026-0142/
Participant Interviews/P07_Maria_Gonzalez_transcript.docx
```

Measured by searching the bytes of a store built that way: the author's
username, their institution's OneDrive tenant, the IRB protocol number and a
participant's name were **all present in the file** — in the artifact a
FERPA/IRB-safe tool holds out for sharing.

**The privacy gate could not have caught it.** `privacy.scan.scan_frame` takes a
DataFrame: it scans what goes *in*. Nothing scanned what goes out, and store
metadata is not text any user typed.

**And nothing ever read the value back.** It was written by `add_document`,
asserted by exactly one test, and consumed by no code anywhere. The leak bought
nothing at all — the test that asserted it round-tripped was its only consumer,
and is now the test that asserts it does not.

**What changed**

- Only the file's **name** is stored. Splitting is done on both separators
  explicitly rather than via `PurePath`, because a store written on Windows may
  well be opened on Linux — which is the entire scenario — and `PurePosixPath`
  does not treat a backslash as a separator.
- Migration 5→6 shortens the value in projects already written, since those are
  the ones that exist and therefore the ones most likely to be shared.
- **The file is rebuilt afterwards.** SQLite marks a rewritten row's old page
  free and leaves it legible, so a migration that shortens a string can leave
  the long one sitting in the bytes. `core/erasure.py` measured that same effect
  for deletion; migrations that redact now VACUUM outside the migration
  transaction.

**What this deliberately does not do.** A filename containing a participant's
name is still in the store — as the **title**, which is made from that filename
and shown throughout the interface. That is the analyst's own choice, visible to
them, and silently renaming their documents would break matching a document
against their own records. It is a research-practice matter to surface, not a
string to rewrite behind somebody's back, and the tests say so rather than
implying a leak was closed further than it was.

## v4.10.0 — August 2026: it tells you what it needs before it starts

The models are not in the installer — the payload is 487 MB and the zero-shot
model alone is 1.6 GB — and they are acquired in one explicit, user-initiated
step. That is the privacy design and it is right. What was missing is the run
asking, before it starts, whether that step has happened.

**Measured**, on a machine holding only the embedding model with offline mode
armed:

    the run got through embeddings and cluster discovery -- 9 progress steps,
    24.8 seconds on 45 responses -- and then failed at sentiment

and on the next attempt it would have failed again at zero-shot, that time
against a 1.6 GB download. **Three failures, each after more waiting**, because
each model was only checked when its own stage first touched it. On the five
thousand responses this tool is for, the second failure lands after the
sentiment stage has run for six minutes.

`core.offline.model_cache_status` already knew all three answers before the run
began. Nothing asked it.

**Worse than the timing was the advice.** The message named
`python tools/download_models.py`, a *"Model status panel on the Run Analysis
page"*, and a README section — three remedies, **all of them Streamlit's**. A
desktop user has no shell, no page by that name (it is the **Models** tab), and
no README they can find. This is the same defect the encoding warning had in
v4.8.1: correct advice delivered to the build that cannot follow it, and the
installed desktop app is what a first user is most likely to be holding.

**What changed**

- `core/model_readiness.py` works out which models a *given configuration* will
  actually reach — sentiment is skipped when sentiment is off — and reports
  every absent one at once.
- The check runs as the first statement of `run_pipeline`, **before the output
  directory is created**, so a refused run leaves nothing behind and says so.
- Each front end registers advice its own user can act on. The desktop says
  "open the Models tab and press Download"; Streamlit names its panel.
- Both builds list it before the Run button: a blocker on the desktop, a warning
  beside the runtime estimate on the web app.

One deliberate subtlety: the zero-shot model is required even for a run
configured to use the local LLM engine, because `engines/factory.py` falls back
to the transformer engine whenever Ollama is unreachable, and its contract is
that the pipeline must always be able to complete. A fallback that cannot fall
back is not one.

The check is advisory in one direction only: a model cache it cannot read
reports **nothing** missing. This exists to spare somebody a wasted wait, not to
become a new way for an analysis to be refused, and the per-model error at point
of use still catches a genuine absence.

## v4.9.0 — August 2026: the second run is nearly free

v4.8.2 measured how long a run takes. This release asks how long the *second*
one takes, and the answer was: the same, because the pipeline cached the one
stage that costs nothing and recomputed the one that costs everything.

Using v4.8.2's measured constants, a 5,000-response run with six labels:

| stage | seconds | cached before? |
|---|---:|---|
| model loading | 45 | n/a |
| embeddings | 60 | **yes** |
| sentiment | 375 | no |
| zero-shot coding | 7,200 | no |

**0.8% of the run was cached. 94% was recomputed every time.** Three
consequences, each an ordinary thing a researcher does:

- **A crash cost the whole run.** The embedding cache writes once, at the end of
  its stage. A run that died ninety minutes in had written nothing for the
  ninety minutes.
- **Adding one label re-coded everything.** Iterating a codebook *is* the
  method, not a mistake. An analyst who has to choose between a better codebook
  and a two-hour wait takes the wait once, and then stops refining.
- **Fixing one typo re-coded everything**, because the embedding cache key is a
  hash of every response concatenated.

`core/inference_cache.py` caches per response and commits as it goes.

**The correctness question underneath.** The obvious design — cache each label's
score — is right in one mode and wrong in the other. Measured on
`facebook/bart-large-mnli`, same responses, candidate set cut from six labels to
two:

```
multi_label=True     worst score drift  5.96e-08     (float noise)
multi_label=False    worst score drift  3.85e-01
```

With `multi_label=True` each (response, label) pair is scored independently.
With it False the pipeline softmaxes across the candidate set, so a label
legitimately scores 0.56 among six labels and 0.94 among two. Caching per label
there would serve a number computed for a different question — a correctness bug
wearing a performance costume. So the key is per (response, label) in the first
mode and per (response, whole label set) in the second.

**Measured on the real models**, 45 responses and six labels:

| run | time | models loaded |
|---|---:|---:|
| cold | 106.9 s | 3 |
| warm, everything cached | **4.4 s** | **0** |
| one label added to the six | 41.4 s | 1 |
| control, cache switched off | 98.4 s | 3 |

Each run in **its own process**, which is not pedantry. Measured all four in one
process the warm run looked like 2.5 s — because run one had already loaded the
models — and that flattering number hid a real defect: the cache skipped every
inference and then loaded a 1.6 GB NLI model it had no work for, 25.4 s of a
25.4 s run. The pipeline is now built on first use and named by the caller
rather than asked for its own name, so a fully cached run touches no model at
all.

The cached run's top labels and scores were identical to the control's, which
matters more than any of the timings. Scaled up, a 5,000-response re-run drops
from over two hours to seconds, and a seventh label costs about twenty minutes
instead of two and a half hours.

**A privacy defect this created, and closed in the same change.** The cache is
derived from response text and keyed by a SHA-256 of it, which makes it a PII
artifact. `core/erasure.py` deleted only `.npy` embedding caches, so a
right-to-be-forgotten request would have left a file holding the erased
respondent's sentiment and theme scores. Hashing is not anonymisation — a hash
of a known string is a lookup — and the file cannot be filtered without the text
being erased, so erasure now deletes it whole.

**Failure is always a miss, never an error.** The analyst did not ask for this
cache and it must not be able to end a run: an unopenable file, a read-only
directory or a row torn by a power cut costs a recomputation, not an afternoon.
Set `pipeline.use_inference_cache: false` for a run that must leave no derived
data behind.

**And it now says when it is resuming.** A run that died at ninety minutes and
silently restarts fast is good; one that states what it is skipping is honest,
and the difference matters to an analyst deciding whether to trust the output of
a job they did not watch. The notice goes through a new `note()` on the progress
reporter rather than `stage()` — `stage()` banks a stage, so it would have
overshot the final fraction and shifted the coding stage's own sub-progress into
the following stage's slice.

The uncached path is unchanged, so the v2.1 byte-identity harness still pins it.

## v4.8.2 — August 2026: the runtime estimate was wrong by twelve times

Before a run starts, the program tells the researcher roughly how long it will
take. That number had never been checked against a real run, because **nobody
has ever run this on more than 45 responses.** The largest file in `data/` is 45
lines; the largest fixture anywhere is 500 synthetic rows inside a unit test. A
first-year experience survey — this tool's literal audience — is routinely 500
to 5,000 open-text responses.

Measured on a 12-core CPU with the shipped models:

| stage | the estimate charged | measured |
|---|---|---|
| embeddings | 0.02 s/row | 0.011 — conservative, fine |
| sentiment | 0.03 s/row | 0.075 — 2.5x low |
| zero-shot | **0.12 s/row, flat** | **0.24 s/row _per label_** |

Zero-shot runs the NLI model once for every *(response, label)* pairing, so the
label count is the dominant term — and the old model ignored it completely.
Measured at 3, 6 and 12 labels: 0.259 / 0.245 / 0.236 seconds per row per label,
and linear in rows as well (2.01 / 1.90 / 1.90 s/row at n = 20 / 60 / 200).

With six labels that is 1.44 s/row against a predicted 0.12.

| responses | old estimate | reality |
|---|---|---|
| 500 | about 1–3 minutes | ~13 minutes |
| 1,000 | about 2–5 minutes | ~26 minutes |
| 5,000 | **about 9–26 minutes** | **over two hours** |

That is not a rounding error. It is a researcher starting a run before a meeting
and returning to find it nowhere near done — **exactly the interrupted long run
that crash-safe checkpointing exists to survive.** Somebody evidently hit this
and built the recovery; nobody went back and corrected the number that caused
it.

**What changed**

- Measured constants, and model-load time is now counted. It dominates a small
  run and is invisible in any per-row figure, which is why a tiny corpus feels
  slower than the arithmetic suggests.
- An explicit `n_labels` term, and **both front ends now pass their actual label
  count** rather than assuming six. A twelve-label codebook is quoted at twice a
  six-label one, which is what it costs.
- Long runs are quoted in hours. "About 77–230 minute(s)" is a unit conversion
  the reader should not be doing while deciding whether to start a run before a
  meeting.
- The range is asymmetric on purpose (0.6x to 1.8x the point estimate): a run
  that finishes early is a pleasant surprise, and one that overruns by an
  afternoon is a lost afternoon.
- The GPU figure is **labelled as an assumption** on both screens. No GPU was
  available to measure, and an assumption presented as a finding is the thing
  this release exists to correct.
- `estimate_runtime_seconds` splits the arithmetic from the wording, so the
  numeric properties can be asserted directly instead of scraped out of a
  sentence that changes units at two hours.

Fifteen tests pin the *shape* of the model rather than its constants — the
constants are machine-dependent and the shape is not — and two of them bracket
runs actually observed.

## v4.8.1 — August 2026: a CSV that Excel wrote now opens

A patch release with one fix in it, and the fix matters more than its size.

**`pd.read_csv` assumes UTF-8. Excel on Windows writes cp1252** unless the user
picks the *"CSV UTF-8"* menu item rather than the plain *"CSV"* one — and almost
nobody does, because the plain one sits higher in the menu and is what "Save as
CSV" has meant for twenty years. Measured, not reasoned:

```
UnicodeDecodeError: 'utf-8' codec can't decode byte 0x92 in position 49
```

`0x92` is a **curly apostrophe**, and free-text survey answers are made of them
because Word and Excel insert them automatically. So the failure was a raw
traceback, on the first screen, for a file the researcher believes is fine.

This was the most likely single reason a first user would give up on the
program, and it had been sitting behind a release blocker phrased as though
reaching it required a real research project. It required one file.

`core/encodings.py` tries utf-8 — which also covers Excel's BOM, verified rather
than assumed — then cp1252, then latin-1, and **reports which one worked**.

The reporting is the point. `latin-1` cannot fail: every byte decodes to
something. A wrong guess therefore does not crash, it produces a corpus where
every apostrophe is `â€™` and nobody notices until it is quoted in a paper. The
note names the remedy, which is to re-export as "CSV UTF-8".

**Both builds say so.** The desktop app had no raw `pd.read_csv` and so got the
fallback for free — but it got it silently, because `load_table` discarded the
note. That is the same silent-mojibake risk, on the build most likely to be
installed, and it would have shipped looking fixed.

**And every path a file can arrive through.** The first version of this fix
reached two readers and looked complete; running the pipeline against an
Excel-written file showed it had missed the one the pipeline actually uses. A
sweep then found nineteen callers of `pd.read_csv`, of which four read files a
person supplied:

| reader | what arrives there |
|---|---|
| `analyze_survey.py` | the CLI pipeline's own loader — the one that was still failing |
| `app/shared/io.py` | an uploaded CSV: a buffer, not a path, and the likeliest Excel export of all |
| `app/data_setup.py` | a downloaded public dataset, which can be in any encoding |
| `iterative_supervised_thematic.py` | **the file the analyst is asked to open in Excel and save back** |

That last one is the one worth naming: the iterative labelling workflow tells
the analyst to edit a CSV in Excel and return it. Excel re-encodes it, and
reading it back failed on a response they had just labelled.

The other fifteen read artifacts this program wrote, always as UTF-8, and are
allow-listed with a reason each — plus a test that flags an entry whose reason
has expired, because a permission outliving its justification is how such a list
rots.

### A guard the fallback made necessary

Because `latin-1` never raises, a `.csv` that is really a workbook or a
truncated download **loaded silently as a one-cell table of control
characters** — an empty-looking dataset with no error at all. A NUL byte cannot
occur in a valid CSV, so a file containing one is now refused with a message
naming the likely cause.


## v4.8.0 — August 2026: the models leave the program

v4.7.0 put statistical modelling beside the coding. This release is the half
that makes that worth doing rather than exporting a CSV and using Stata.

**Fitting a lasso next to the codes is a convenience.** A coefficient table that
arrives in a chapter still carrying the coding provenance, the specification,
the seed, the effective n and the caveats is a different thing, and it is the
only version of this feature worth defending.

### Three shapes, because three people read a result at three moments

- **Word** — the publishable table, with everything qualifying it printed
  *underneath* rather than left in the software. A coefficient table looks
  authoritative whatever produced it, and the person reading it in a chapter
  does not have the program open to be warned by it.
- **Excel** — estimates, specification and caveats on separate sheets. Merged
  into one, the caveats get scrolled past.
- **CSV, with a JSON sidecar** — the interoperability escape hatch. Refusing to
  let an analyst take their data to R or Stata would be the mistake the
  REFI-QDA work exists to avoid; letting it leave *uninterpretable* is a
  quieter version of the same mistake. The sidecar records the unit, the coder,
  the encoding, every reference level, every dropped column, and the one thing
  an outside analyst will otherwise get wrong: **a code column's zero is real,
  and a descriptor column's blank is not**.

### The methods appendix carries the model

`build_methods_appendix(..., models=[(result, request)])`. This is the document
a reviewer asks for, so a fitted model that is not in it is a model nobody can
check.

Placed after inter-rater reliability and before data handling, and a test pins
that order. A reader works down from how the coding was produced, to how much
the coders agreed, to what was then estimated from it. A model shown before its
coding's reliability invites reading the estimate as though the variables had
been measured rather than constructed by an analyst.

### A refused model is no longer exportable

`build_model_docx` would write a Word document for a model the program had
declined to fit: a title, a stamp, a seed, and blank space where the numbers
should be.

That is worse than no file, in a specific way. **A refusal on screen stays on
screen; a file gets circulated.** Somebody opens `model_results.docx` in a
shared folder six weeks later with no way to know it represents a model that was
never fitted. Now `RefusedModelError`, in both front ends, with the desktop
Export button disabled on a refusal.

It is the third instance of one rule here: a refusal is a finding, and findings
must not be silently downgraded into artifacts. `analysis/saturation.py` prints
no verdict, `analysis/deviant_cases.py` labels nothing deviant, and an unfitted
model now produces no document.

### Also

- **A decision tree that explains itself**, pruned by cross-validated
  cost-complexity so the rules are readable rather than fifteen leaves of noise.
  On a fixture whose truth is a shallow interaction it recovered the rule in
  three leaves and beat both ensembles. **Extremely randomised trees** alongside.
- **`tools/simulate_project.py`** — synthetic projects with a known answer, and
  `--calibrate` to measure how often a 95% interval actually contains it. It
  replaced the double-lasso sample-size floor with a measured rule that grows
  with the candidate count, `max(60, 3 × candidates)`; a flat 100 had been both
  too strict at small *p* and too **lenient** at large *p*, which is the
  dangerous direction. Every simulated project is marked as such four ways over.
- Backups made inside one clock tick no longer overwrite each other. `%f` is not
  microsecond-precise on Windows — eight consecutive calls return one value —
  so a five-deep safety net was quietly becoming one deep, worst exactly where
  depth was the point: the automatic backups taken before destructive
  operations, which arrive in bursts.
- Forests use 200 trees rather than 400. Measured at 100/200/400/800 for n = 100
  and n = 300, cross-validated accuracy was identical to four decimals up to
  400; the extra trees cost about thirty seconds a fit and bought nothing.


## v4.7.0 — August 2026: the quantitative half, without leaving the project

**The step every mixed-methods researcher currently takes outside the program.**
Export to SPSS, Stata or R, fit a model, paste the result into a paper where
nothing connects it to the coding that produced the variables. This release does
that step in the project file, with the provenance attached — and it is
open ground: NVivo and ATLAS.ti have no regression at all, Dedoose has
descriptor charts, and MAXQDA Stats stops at OLS.

Everything from scikit-learn, which was **already a declared dependency** in
`requirements.txt`, `requirements-light.txt` and `pyproject.toml`. No new
dependency, for a program whose selling point is that it installs and runs
offline. `statsmodels` was not added either: the one place it would have been
wanted, robust standard errors for the final stage, is twenty lines of numpy.

### The unit of analysis, which everything rests on

`analysis/design_matrix.py` produces **one row per case**. That sounds obvious
and is the single place this could have gone silently wrong:
`analysis/crosstab.join_descriptors` returns one row per *coding*, so regressing
on it would enter a respondent once per code they received — weighting the
sample by how much the analyst coded each person, which is an artifact of the
coding process rather than a property of the data.

Four decisions travel with it, each reported rather than assumed:

- **Absent is zero; missing is missing.** A code not applied is a real zero — it
  was read and not applied. A descriptor never collected is unknown, and making
  it zero would invent data.
- **Pooling coders is reported, and machine-coded columns are flagged.** Two
  coders in one matrix build a variable neither asserted. Unlike a heatmap,
  where that inflates a count, a regression reports a coefficient for it.
- **Categorical descriptors get a named, deterministic reference level.** A dummy
  coefficient with an unstated baseline cannot be interpreted.
- **"Parses as a number" is not "is a number".** Class year, cohort and Likert
  responses are numeric in form, and reading one as continuous asserts that
  equal steps mean equal things. Reported, flagged when the values are few, and
  overridable — found by building a realistic matrix and reading the columns,
  with every test passing.

### Drag and drop, in the grammar the chart builder already uses

`core/model_spec.py` is `core/chart_spec.py`'s shape for models: four shelves —
**Outcome**, **Treatment**, **Predictors**, **Controls** — with `problems()` in
sentences, `can_run()` separating blocking from advisory, and `to_dict`/
`from_dict` so a model saves with the project.

Eight methods, each with a **stated floor** and its own reason for it: below it a
double-lasso interval is "optimistic in a way that is not visible in the output",
and a forest's importance ranking "mostly reflects which cases landed in which
split". The number is printed with the refusal, so an analyst can disagree with a
number rather than with a mood.

Both front ends: a **Modelling** page in the web app and a **Modelling** screen
in the desktop build, the latter with real drop targets reusing the chart
builder's field palette. Named *Modelling* rather than *Models* because the
Models tab is the model *manager*, which downloads language models.

### Double lasso — the part no rival ships

Post-double-selection (Belloni–Chernozhukov–Hansen), in its own module because
it is inference and everything else is prediction. **Verified against a known
effect**, with a confounder built to defeat single selection:

| | estimate |
|---|---|
| true effect | 1.000 |
| naive, omitting the confounder | **0.287** |
| oracle, including it | 0.991 |
| **double lasso** | **0.984**, interval [0.934, 1.034] |

The outcome lasso selected only noise; the treatment lasso caught the
confounder. **Step 2 is the method**, and an implementation that lassoed only the
outcome would return 0.29 here and pass any test that merely checked a number
came back.

### What it will not do

`analysis/models.py` cannot report a confidence interval or a *p*-value. Not by
convention — there is no field on the result to hold one, and a test greps the
source to keep the words out. Fitting a lasso, reading which variables survived,
and then testing the survivors on the same data is invalid, and a panel offering
both methods makes it the easiest mistake available. Wanting an interval means
naming a treatment, which routes to the one module allowed to produce one.

Nothing calls a result causal. The interval is valid *despite the selection* —
which is what the method is for — under the assumption that the confounders are
among the controls, and in coded survey data that assumption is doing enormous
work. The caveats say so every time.

### Also

- **Code networks** (v4.6 dev work, previously unrecorded here): the coding frame
  as a map, with a **deterministic** layout, so unlike every rival's the same
  project always draws the same figure and a reviewer can reproduce it.
- `LogisticRegression(penalty=)` was deprecated in scikit-learn 1.8 and is
  removed in 1.10, which the pin `>=1.3,<2.0` already permits. It was code
  scheduled to break on an install the requirements allow, sitting behind a
  green suite and a `FutureWarning` nobody read. Version-gated both ways, with a
  test that turns `FutureWarning` into an error.
- The desktop screen fits on a worker thread, so a boosting run does not freeze
  the window.


## v4.6.0 — August 2026: interoperability, deviant cases, and erasure that leaves nothing behind

**The version stamp had stopped being true.** `PACKAGE_VERSION` still said
4.4.0 while the store had moved to schema v5, so every run manifest, methods
appendix and `.qdpx` claimed to have been produced by software that **cannot
open the file it produced** — a v5 store raises `SchemaTooNewError` in 4.4.0
rather than degrading. For a tool whose central claim is reproducibility, a
version that lies is not a clerical problem.

Two fixes, and the second matters more than the release:

- **The manifest and the methods appendix now record `schema_version` beside
  `package_version`.** Knowing which release made a project does not tell a
  reviewer whether their install can open it; the store format does, and it was
  the one number missing from the document written for exactly that purpose.
- **A test pins the changelog's newest release to `PACKAGE_VERSION`,** so the
  stamp cannot silently fall behind the code again. It is how this drifted for
  two releases without anyone noticing.

Chasing that test through the tree turned up a worse one. `core/populate.py`
declared a **second** `PACKAGE_VERSION`, `"3.0.0-dev"`, and wrote it into the
Run row of every survey run — inside the `.qnw`, not merely in an export, and
survey is the main path. `interview/populate.py` imported the real constant and
recorded it correctly, so interview projects were right while survey projects
named a version four releases dead. The copy is gone, the import is in, and a
test now asserts that `core/manifest.py` is the only module in the tree that
defines it.

Runs already stored in existing projects still read `3.0.0-dev`. That is left
alone: it is an accurate record that those runs were produced by software
carrying this defect, and rewriting stored provenance to read something tidier
would be the same class of mistake as the defect itself.

### Deviant-case analysis — the first thing no rival can copy

For a chosen code, the responses sitting furthest from how that code has been
used elsewhere in the project. Those are the ones worth re-reading: the genuine
outliers that sharpen an analysis, and the miscodings.

Finding and accounting for cases that contradict the emerging pattern is
standard qualitative rigor and standard qualitative drudgery. Done by hand it
means re-reading everything, so in practice it is done thinly or asserted.

**NVivo, MAXQDA, ATLAS.ti and Dedoose cannot offer this** — not for want of the
idea, but because they do not hold sentence embeddings for every response. This
project does, and has since v2.

- **It proposes cases to read; it does not classify them as deviant.** Distance
  from a centroid is a property of the embedding, not a finding about the data.
  A response sits far out because it is atypical, miscoded, very short, or about
  something else — all four worth attention, only a human able to tell them
  apart. The page says so, and a test asserts nothing is ever labelled deviant.
- **The centroid is of the coded responses, not the code's definition.** What a
  code means to this analyst in this project is expressed by what they applied
  it to.
- **Leave-one-out.** A response that votes on the mean it is measured against
  pulls that mean towards itself, which suppresses exactly the outliers this
  exists to surface.
- **A thinly used code gets a refusal, not a ranking.** Below eight
  applications the centre of a code sits close to every response and "furthest"
  is noise wearing a number.
- Torch stays out of the import path, so `analysis/` still imports in the lite
  install; the tab degrades with a sentence rather than an exception.

### XSD conformance — and the four bugs only it could find

The interop tests all compared this codebase against itself: the round trip
exports and re-imports, and the reader fixtures were written by this project.
Both are worth having, and neither can catch the error that matters most —
**two agreeing implementations of a misreading look exactly like a correct
one.**

Validating against the published REFI-QDA schemas is the only check with an
opinion this codebase did not supply, and it found four real defects that every
other test had passed:

1. **The codebook namespace was `urn:QDA-XML:codebook:1:0`** — a colon where the
   standard has a dot. Our reader and writer agreed on it, so every round trip
   was green and every file would have been rejected by NVivo.
2. **`VariableValue` was written before `PlainTextSelection`.** `TextSourceType`
   is an `xsd:sequence`, so order is part of validity, not presentation.
3. **Empty containers were written empty.** No container in that schema allows
   zero children, so `<Users/>` on a project with no coders yet — an entirely
   ordinary thing to export — made the whole file invalid. Containers are now
   omitted instead.
4. **An empty codebook produced a document.** `CodesType` requires at least one
   `Code`, so there is no valid way to express one; the exporter now refuses
   with a sentence rather than writing something another package will reject,
   because this program cannot explain a failure that happens inside that one.

The schemas are vendored under `tests/fixtures/refi_qda/` rather than fetched: a
conformance test that reaches the network fails on a train, and silently changes
meaning when the remote file does.

### REFI-QDA project export — and take it back out again

`core/qdpx_export.py` writes the same standard the importer reads. Together they
make **no lock-in a fact rather than a claim**, which for a free MIT-licensed
tool arguing against commercial packages on exactly that ground is the whole
point. A researcher can move to NVivo, MAXQDA or ATLAS.ti, hand a project to a
colleague who uses one, or deposit it in an archive — which is what the standard
was created for.

Import shipped first because it decides whether anyone tries the tool. This
matters to a different person: the one who already stayed and needs to know they
can leave.

- **The round trip is the test that matters**, and it needs no rival's file:
  export, import into a fresh project, and the codes, hierarchy, source text,
  excerpt offsets, codings and — the one most easily lost — *which coder made
  which coding* all have to arrive intact. That catches what a schema validator
  cannot, like an offset written against text it does not index.
- **Text is written to `Sources/` files, not inlined.** Both are legal and the
  reader accepts either, but files are what the other packages write and what an
  archive expects; inlining a corpus into one XML document makes a file nothing
  can open.
- **An excerpt carrying no coding is not written.** A selection with no code on
  it is not a finding, and whole-response excerpts alone would fill the file
  with empty highlights in the receiving program.
- **A `.qdpx` always contains the full text of every source**, and unlike the
  bundle or the workbook it cannot be redacted into something still worth
  exchanging. The page says so rather than offering a checkbox that would lie.
- GUIDs are hashed and stable, so re-exporting an unchanged project produces an
  unchanged manifest and a diff shows what actually changed.

### REFI-QDA project import — bring a project in from NVivo, MAXQDA or ATLAS.ti

`core/qdpx.py` reads a whole `.qdpx`: documents, coded passages with their exact
character positions, the coders who made them, and respondent variables. It is
the file every other package exports, and reading it is what turns QualSafe from
a tool you must switch to *wholesale* into one you can try on work you have
already done.

Import before export, deliberately: import is the adoption path and decides
whether anyone opens the program twice; export is the exit promise and matters
most to people who have already stayed.

Three decisions carry the feature:

- **Imported codings are never yours.** They land under `imported_<coder>`,
  never `human_primary`. This is the methodological centre, not a nicety: κ
  compares raters, so silently folding a colleague's coding into your own rater
  id would inflate agreement to 1.0 — perfect-looking and meaningless. Two
  coders in the file stay two coders. Same reasoning that already governs
  `auto_textsearch` and the pipeline's `transformer` rater.
- **Offsets are verified, never trusted.** A selection's positions index the
  exporting program's plain text, and what it counted may not be what lands in
  the zip — CRLF collapsing to LF shifts every later position, which is the bug
  class already recorded for Qt in `PORTED_BACK.md` §2. A selection that does not
  resolve against the imported text is **skipped and reported**, never stored at
  a guessed position. A wrong excerpt is worse than a missing one because it
  looks like evidence.
- **What is not imported is named and counted** — media sources, notes, sets,
  graphs, links. The standard's own documentation says complex projects cannot
  transfer one-to-one, and a silent partial import is how someone concludes
  their data came across when a third of it did not.

Also handles what other writers actually do: text stored inline or as a file in
`Sources/`, entry names in any case, namespaced or bare tags.

### REFI-QDA codebook exchange — the standard everyone else already speaks

**Schema v5.** REFI-QDA is the open interoperability standard for qualitative
software, launched with DANS (the Dutch national data archive) so a project can
be exchanged and archived rather than trapped in the program that made it.
NVivo, ATLAS.ti, MAXQDA, QDA Miner, f4analyse and Quirkos all implement it.
QualSafe did not, and it cut both ways — the second way worse than the first:

- **Coming in:** a researcher with an existing NVivo or MAXQDA codebook could
  not bring it here. Every potential user who already has a project — most of
  them — hit a wall on day one.
- **Going out:** they could not hand a QualSafe codebook to a colleague using
  something else. For a free, MIT-licensed, local-first tool whose pitch is *no
  vendor and no lock-in*, being **more** locked-in than the commercial packages
  inverted the entire argument.

`core/refi_qda.py` reads and writes the `.qdc` codebook format, offered beside
the existing YAML on the Codebook page. No new dependency — `xml.etree` is
enough. The whole-project `.qdpx` format is deliberately not here yet; it is a
much larger surface and `V5_PLAN.md` §B7 carries it.

- **The reader is tested against files a *different* writer would produce** —
  unqualified tags, a missing `<Codes>` wrapper, unknown vendor extensions. A
  reader that only reads its own output is not interoperability.
- **Unknown elements are ignored rather than fatal.** Every package writes a
  superset of what the others read, and the standard's own documentation says
  complex projects cannot transfer one-to-one. A codebook that is 90% readable
  beats a refusal.
- **Import is additive and shares one code path with the YAML importer**
  (`import_codebook_entries`). Two exchange formats disagreeing about whether an
  incoming code overwrites yours would be a trap, and the answer — never — now
  lives in one place.
- GUIDs are derived by hashing the code id, so re-exporting an unchanged
  codebook produces an unchanged file and a diff shows what actually changed.

### Saved charts

**Schema v5** also adds `saved_charts`. A chart's *definition* — mark, shelves,
aggregates, data source — is stored with the project, so re-opening it draws the
figure against the project **as it stands then**.

The PNG and CSV exports answer "get this figure into the document". This answers
the question a study that keeps collecting data actually has: a figure built
after twenty interviews comes back after forty without anyone remembering how it
was made, and a methods appendix can cite it by name.

Saving by name **replaces** rather than adding — an analyst who tweaks a chart
and saves it again means *that* chart, and a list of near-duplicates is how a
saved-view feature stops being used. Loading is deliberately forgiving: a spec
written by an older build opens with defaults for fields it lacks, because
refusing to open a saved chart loses it.



### Saturation (Analysis → Saturation)

"Was saturation reached?" is the most common methodological challenge to a
qualitative study, and **no CAQDAS package computes an answer** — NVivo, MAXQDA,
ATLAS.ti and Dedoose all leave the researcher to assert it in prose. The inputs
have been in the store the whole time: which codes were applied to which
sources, in order.

`analysis/saturation.py` plots new codes against sources coded and produces the
sentence a Methods section quotes — codes found, where the last new one
appeared, how many sources were read after it without another.

**The caveats are the feature, not the curve.** They render above the chart,
because a figure quoted in a Methods section travels without whatever sat below
it, and three of them are disqualifying often enough to matter:

- **An a-priori codebook makes the curve meaningless** — it measures how fast a
  fixed list was applied, not what the data contained. Detected from
  `Code.origin` and stated, rather than left to the reader to notice.
- **Ingestion order is not collection order** unless the project recorded it,
  and saturation is a claim about sequence.
- **Code saturation is not meaning saturation.** A flat curve means no new
  labels, not that the phenomenon is understood.

Machine coding is excluded by default: a model applying a fixed label set
saturates immediately and has discovered nothing, so including it flatters the
curve for the wrong reason.

**No verdict is ever printed.** "Saturated at n=17" is a claim only a researcher
can make, and a tool that printed it would be laundering that judgement. There
is a test asserting the word never appears.



### Joint displays (Analysis → Joint display)

The **named** integration artifact of mixed-methods research: quantitative
result and qualitative result side by side, with a column for the inference
drawn from reading them together. It has a Sage Handbook chapter and a published
methods paper about MAXQDA's implementation, and it is much of why MAXQDA is the
default recommendation for mixed-methods work.

This project already had every ingredient — descriptors, code × descriptor
crosstabs with drill-back, verified quotes, Word and Excel export — and assembled
none of them into the thing reviewers ask for by name. `analysis/joint_display.py`
is the assembly. It is a layout over analysis that already exists, not new
analysis.

- **The counts are the project's own counts**, straight from
  `analysis.crosstab.code_by_descriptor`. A display that computed its own would
  be a second answer to a question already answered, and the two would drift.
- **Percentages within subgroup are the default**, unlike the crosstab, because
  a display is for publication and the count-only version is the one that
  misleads: 10 of 20 first-generation students is a bigger deal than 15 of 200.
  The raw count travels alongside every percentage.
- **The integration column starts empty and stays the analyst's.** Pre-filling
  it would be the software writing the finding. Statements are saved with the
  project and replace rather than append — memo ids are not ordered by time, so
  appending would leave no reliable way to tell which edit was current.
- **Themes are ordered by prevalence, ties broken by name**, so the same project
  cannot export a table whose rows moved between runs.
- **The caveats print under the Word table**, not just on screen: small cells
  named with their counts, very unequal subgroups, and a counts-only display.
  The person reading the table in a chapter does not have the software open.
- Word carries the quotes (opt-in, like every other export here); the Excel
  workbook never does, so it stays safe to email.

### One pipeline config, not two

`app/shared/data.build_general_config` read every choice straight out of
`st.session_state`. That made the dict governing every analysis impossible to
import outside Streamlit and impossible to test anywhere, so the desktop build
reimplemented it — and `resolve_long_dataframe`, the melt that mints
`response_id` and the code behind this project's worst shipped bug, ended up
with two copies that had to agree by hand.

`core/run_config.py` is now the single implementation, driven by an explicit
`RunSettings`. Both front ends are thin adapters over it: the Streamlit layer's
whole job is `settings_from_session()`, one function, in one place.
`core/label_packs.BUILTIN_PACKS` takes the starter packs for the same reason.
`app/shared/data.py` drops from 497 lines to 285.

A test asserts that every field on `RunSettings` is read by
`settings_from_session` — a field added to one and not the other is a default
silently overriding the analyst's choice.

### Chart builder (new page, survey and interview modes)

The Analysis page answers the questions the tool decided are interesting.
This one answers the analyst's. Pick a chart type, put fields on X, Y, Colour
and Split-by, and read the result — the shape Tableau made ordinary and no
qualitative package offers without a licence.

- **`core/chart_spec.py`** is the whole grammar, and it imports no front end.
  Marks: bar, horizontal bar, stacked, 100% stacked, grouped, line, area,
  scatter, pie, donut, heatmap. Aggregates: count, distinct, sum, mean, median,
  min, max. Shelves may bin and sort.
- **The output is a Vega-Lite spec.** Altair already emits it, `core/viz_export`
  already renders it to PNG/SVG through offline `vl-convert`, and Streamlit
  already displays it — so the builder adds **no new dependency**. It also makes
  a figure reproducible: the exported `.vl.json` plus the exported `.csv`
  redraw it on any machine, with no QualSafe installed. NVivo, MAXQDA and
  Dedoose all hand you a picture.
- **`analysis/crosstab.join_descriptors`** widens the descriptor table onto the
  codings, so a theme can be charted against class year, program and
  first-generation status at once. A left join, deliberately: an inner one would
  silently shrink a frequency chart by dropping respondents who skipped the
  demographics.
- **"Start here"** offers one-click charts before the analyst has learned what a
  shelf is; the first is always "how often each code occurs".
- **A bad combination produces a sentence, not a different chart.** Asking for
  the mean of a text column, or a pie with nothing on Slices, says so. Silently
  substituting a mark is how a figure ends up in a paper meaning something else.
  Caveats that only make a chart *misleading* — a pie with many slices, a 100%
  bar hiding unequal totals — are stated and do not block.
- **No spec names a colour.** `core/theme.py` stays the only place that decides
  what blue means, in both skins. There is a test.
- The exported spec carries only the columns the chart uses. The rest would ride
  along inside a `.vl.json` the analyst intends to publish, and for a coding
  table that means raw identifiers.

*Not built:* true drag-and-drop. Streamlit has no shelf component and vendoring
one buys little over the selectboxes — same number of interactions, worse
accessibility, a JS bundle to maintain. The desktop build is where drag-and-drop
is native and worth having, onto this same engine. See `V5_PLAN.md` §B1.

### More than six code colours, and a colour-vision-safe palette

Six is right for a chart legend and wrong for a codebook. At seven codes the
seventh wrapped to the first, and in the reader's margin stripes — where colour
is a code's only identifier — two codes became indistinguishable. The chart
builder above made it sharper, because it colours by code too.

`core/theme.category_colors(mode, palette)` returns at least sixteen. The
palettes' original six come **first and unchanged**, appended never reordered, so
a project that already exists keeps every colour it had. Two alternatives are
offered: **Okabe-Ito**, the standard palette designed for colour-vision
deficiency — worth having when red and green sit adjacent in the default list
and these figures get published — and a high-contrast set. Chosen in the sidebar
under Appearance, persisted like the skin.

The Altair theme registers per palette as well as per skin, because Altair caches
a registered theme by name and one name across palettes would enable the first
choice forever.

### Co-occurrence no longer mixes coders silently

The matrix was built from every rater's applications pooled together. That was
harmless when one pipeline run populated the store, and wrong the moment human
coding entered it: a passage the analyst marked *Financial concerns* and the
model marked *Advising* counted as an "A co-occurs with B" event **neither of
them asserted**. Two consequences — the finding is not attributable, and it moves
when the model version changes though no human changed their mind.

There is now a coder picker on the tab, and when the selection pools more than
one rater the mixing is stated in a banner rather than passing silently. "All
coders" stays the default so a project reads identically here and in the desktop
build. Same pattern the project already uses for the kappa caveats: the caveat
travels with the number.

Frequency gets the same picker without the banner — a count of applications is
honest about being a count of applications, but an analyst asking "how much did
*I* code" should not have to subtract the model's work in their head.

### Erasure now erases the file, not just the rows

`core/erasure.erase_respondent()` was correct about every query — the respondent
was gone from the store, the CSVs, the report, and the caches — and wrong about
the file. SQLite marks a deleted row's page free and does not overwrite it, so
`strings project.qnw` printed the erased response back. That is not the usual
"deletion is not shredding" caveat about disks: it is the **live project file**
the analyst goes on using, copies to a colleague, and attaches to an archive,
still holding the words of someone who withdrew consent. The pre-erase safety
backup held a whole un-erased copy beside it.

- **`VACUUM` after the delete**, reported as `report["vacuumed"]`. A failed
  rebuild is reported, never fatal — it must not undo an erasure that succeeded.
- **`purge_backups=`** (default `False`) removes the backups that still hold the
  data, **after** the erasure. Purging first would destroy the safety net ahead
  of the risky step.
- **`report["backups_retaining_data"]`** always names what still holds it, so no
  front end can leave the step out silently.
- The audit event records both outcomes.
- Data Management gains the purge checkbox (default on, matching the desktop
  build) and warns when the rebuild could not run.
- `tests/test_erasure_remnants.py` asserts on the file's **bytes**. Querying the
  store passed the entire time this defect existed and proved nothing.

### Fixed

- **`tools/uninstall.py` walked packaged build output.** `plan_targets()`
  excluded `.venv` but not `build/`, so once the desktop installer's payload
  existed — a whole relocatable CPython — "clear caches" offered hundreds of
  bytecode directories belonging to third-party packages. `build` and `dist` now
  join `.venv`. The model-cache assertions match the cache *path* instead of the
  substring `huggingface`, which was firing on the `huggingface_hub` package and
  turning the suite red on any machine that had built a payload.
- **`requirements-light.txt` was missing `huggingface_hub`.** `core/model_manager.py`
  and `core/offline.py` both import it at call time, so the documented light
  install failed two tests on a clean machine.

## v4.4.0 — July 2026: reports, and ready to install elsewhere (v4 Phase 5)

Deliverables and distribution. Phase 4 (focus groups, OCR, timestamped
transcripts) was **dropped** — those input types aren't in use, so building them
would have been speculative.

### Reports (Results & Downloads → Reports)

- **Codebook report** (`.docx`) — the hierarchy, each code's definition, origin,
  and application count, with optional example quotes. The appendix a
  dissertation or an IR deliverable attaches. Quotes are **opt-in**, so the
  default document is safe to circulate.
- **Methods & reliability appendix** (`.docx`) — the document a reviewer or IRB
  asks for, assembled from what the project already records: engine, model and
  thresholds; who coded; per-code kappa for every comparable rater pair; how many
  disagreements were adjudicated; the codebook version; and the privacy
  statement. **The caveats travel with the table** — insufficient-N, the kappa
  paradox, cross-unit incomparability, and the uncertainty-sampling bias — because
  a reliability figure reported without them is how a kappa on six items ends up
  in a paper. States plainly when no reliability figure is reportable rather than
  printing an empty table. Contains no verbatim response text.
- **Framework matrix** (`.docx` and `.xlsx`) — Word as a narrative (a section per
  case, its themes and summaries beneath, the shape a findings chapter takes);
  Excel as a coverage grid plus a summaries sheet. Supporting passages are opt-in
  in Word and never present in Excel.

*Not built:* Phase 5.4's extra chart types (treemap, network, dendrogram). The
existing charts are already themed and exportable as PNG/SVG; more chart types
were decoration next to the three documents above.

### Ready to install elsewhere

- **`tools/verify_install.py`** — a one-command check for a colleague's machine:
  Python version (including the 3.13/3.14 refusal), every required and optional
  library, a real create-write-read against a throwaway project store, FTS5
  availability, and (with `--check-models`) the model cache. Each problem gets one
  plain sentence. Exit code 0 means ready. Added as step 3 of `INSTALL_FIRST.txt`.
- **`docs/RELEASE_VERIFICATION_CHECKLIST.md` rewritten for v4.** It was last
  accurate at v3.1.1 — thirteen releases ago — and covered none of Documents,
  span coding, Search, Query, the framework matrix, or Reports. It now also has
  sections for **installing on someone else's machine** and **upgrading an
  existing project to schema v4**, which is what a first multi-machine rollout
  will actually hit.

## v4.3.1 — July 2026: queries and the framework matrix (v4 Phase 3 complete)

Where coding turns into findings. A new **Query & Synthesis** page with four
tabs.

- **Boolean retrieval** (`analysis/query.py`). `Cost AND NOT FirstGen`,
  `"Cost worry" OR Housing`, `(A OR B) AND C`, `Cost NEAR/200 dropout`.
  Co-occurrence could only ever *count*; this returns the actual passages, with
  a CSV download, and queries can be saved by name.
  **The unit is explicit**, because the same query means different things at
  different scopes: `Cost AND Dropout` at *excerpt* level means one passage
  carries both, at *source* level means the same document, at *case* level the
  same person's material. It is a visible control rather than a hidden
  assumption — the discipline the tool already applies to response-vs-sentence
  units. Proximity is measured in **characters** (excerpts carry offsets, so
  nothing has to be re-tokenized) and never matches across two documents.
- **Matrix queries.** Code × Code, Code × Descriptor (optionally normalized by
  group size), and the new Code × Case, each downloadable.
- **Framework matrix** (`analysis/framework.py`) — NVivo's flagship synthesis
  instrument: cases down the side, themes across the top, each cell summarising
  what that case said about that theme, with its passages underneath. **The local
  LLM can draft a cell** from the passages already coded there, and every quote
  it offers is **verified verbatim against the source** with the same matcher
  used for interview summaries — an altered or invented quote is dropped and
  counted, never printed. Drafts are labelled, unsaved until you save them, and
  fully editable. Cell text is stored as a `Memo` with
  `target_type='framework_cell'`, so this needed no schema change.
- **Cases.** Create them by hand, or **in bulk from a descriptor or the wide-form
  respondent id** — one case per value, with every source assigned. That is what
  makes a framework matrix usable on survey data, not just documents.
- **`Project.coding_spans_table()`**: the coding table joined with character
  offsets and case membership. A new method rather than extra columns on
  `coding_table()`, which many callers already consume.

*Known gap:* case-level *classifications* (attributes on a case, as opposed to on
a source) are not implemented — descriptors remain source-level, and crosstabs
already work on them. That needs a schema addition and is deferred.

## v4.3.0 — July 2026: manual span coding (v4 Phase 2b) — Phase 2 complete

The defining act of qualitative analysis, and the last big thing QualSafe
couldn't do: **select a passage and give it a code.** Everything else here codes
a whole unit automatically; this is the one where the analyst chooses the
boundaries.

**Documents → Code** offers two ways to choose a passage, both landing the same
`Excerpt` + `CodeApplication`:

- **Pick sentences or paragraphs.** The document is split into units with exact
  offsets and you tick the ones to code. A run of consecutive ticks is stored as
  **one** passage, not several — ticking three sentences means "this passage",
  and one excerpt keeps the quote readable and the co-occurrence counts honest.
- **Paste a passage.** Copy any wording out of the Read tab; it is located in the
  document using the same three-tier matcher that verifies LLM quotes (exact →
  normalized → bounded fuzzy), so a difference in smart quotes or spacing still
  resolves, and a passage that isn't really in the document is **refused** rather
  than coded to the wrong place.

Plus **in-vivo coding** (name the code after the selected text), multiple and
overlapping codes on one passage, and **uncoding** that is scoped to your own
rater — removing your coding never touches a colleague's or the model's, and the
excerpt survives if someone else is still coding it.

*The invariant, everywhere:* the stored excerpt's text is taken **from the source
by offset**, never from what was typed or pasted. A paste that differs from the
document is stored as the document's characters.

*On the missing third way:* the plan's preferred interaction is a real
drag-to-select component, which needs a JavaScript build step to return character
offsets. `core/span_coding.apply_codes_to_span` already takes raw offsets, so
such a component plugs straight in and nothing else changes. Until then the two
paths above cover the same ground without shipping a build toolchain.

## v4.2.0 — July 2026: document library and reader (v4 Phase 2a)

The first half of the phase that makes QualSafe a corpus-first tool: a project
can now hold a **folder of documents**, and you can **read them in the app** with
your coding shown inline. (Highlight-to-code — creating those codings by hand —
is Phase 2b.)

- **Documents page → Library.** Import from a folder on this computer or by
  uploading files (`.txt`, `.md`, `.docx`, `.pdf`). Nothing is written to the
  project until you pass a **PII gate** covering the whole batch: the files are
  read, scanned, and previewed first, and the import button stays disabled until
  you attest. Changing the selection re-arms the gate. Re-importing a folder
  skips documents already in the project (matched on content, not filename), one
  unreadable file cannot abort the batch, and a scanned PDF with no extractable
  text is reported rather than silently imported as an empty document.
- **Documents page → Read.** The document rendered with **coding stripes** —
  coded passages highlighted and coloured by code, filterable by code and by
  coder, with word count, coded-passage count, and **coverage** (share of the
  document under at least one coding). Long documents are paged so reading stays
  responsive. Overlapping and nested codings both render: a passage coded *Cost*
  and *Belonging* keeps both.
- **Cases.** Create a case (person, site, focus group) and assign documents to
  it, so analyses can be reported per case rather than per file. Uses the `cases`
  tables added in schema v4.
- **`core/documents.py`**: import, the library table, coded-span retrieval, and
  the pure `segment_by_spans` / `coding_density` functions the reader renders
  from. Document text is HTML-escaped before any markup is added.

*Design note:* a document is a `Source` with `type='document'` — no new table —
so every existing analysis (frequency, co-occurrence, kappa, exports) already
works on documents. And unlike a survey response, a document gets **no automatic
whole-source excerpt**: a whole-document excerpt would be a meaningless 40-page
quote. Documents get excerpts only where they are coded.

## v4.1.0 — July 2026: the UI split into page modules (v4 Phase 0.1 complete)

No behaviour changes — a structural release that completes v4 Phase 0.

`streamlit_app.py` was **3,745 lines** and was the project's biggest
maintainability liability: the v4 corpus features (a document library, a reader
with coding stripes) could not be added to it responsibly, and a UI layer that
can never be broken up can never be replaced either. It is now a **186-line
shell** — terminal logging, navigation, `main()` — with every page in its own
module:

```
app/                 wizard, data_setup, theme_setup, run_analysis, labeling_lab,
                     analysis_page, codebook, search_page, results,
                     data_management, model_manager, help_page
app/shared/          constants -> io -> data -> projects -> models -> widgets -> state
```

- **The rule that keeps it that way** (in `app/__init__`): a page module imports
  only from `core/`, `analysis/`, `exports/`, `app.shared`, and Streamlit — never
  from the shell. Anything a page needs from the shell is passed in as an
  argument. That single constraint is what prevents the circular imports that
  make a monolith impossible to break up later.
- **`app/shared/` is strictly layered** (constants → io → data → projects →
  models → widgets → state); a module may import only from the levels below it,
  which the extraction verified mechanically. No module now exceeds ~515 lines.
- **Offline mode is armed in `app/__init__`**, not the shell: every page import
  goes through the package, so the guarantee no longer depends on the order in
  which the shell imports pages. A new test asserts it behaviourally (importing
  `app` sets the offline flags), alongside the existing grep-level guard.
- **Backwards compatible**: helpers that moved are re-exported from
  `streamlit_app`, so existing imports (and the test suite) still work. New code
  should import from `app.shared.*`.

Verified by the render-smoke suite exercising all 12 pages in both modes, plus
the full 608-test suite.

## v4.0.0 — July 2026: corpus search (v4 Phases 0 + 1)

The first instalment of `V4_PLAN.md` — the arc that turns QualSafe from a
pipeline-first NLP tool into a corpus-first QDA environment. Until now every
analysis was **over codes**: you could ask how often a code was applied, but not
what words the data actually uses, and you could not find a phrase at all. That
is backwards for the first hour of a project, before a codebook exists.

**Schema v4** (`.qnw` stores upgrade automatically on open; older QualSafe
versions cannot open a v4 store, which is why this is a major version).

- **Corpus tables** — `cases` + `case_membership` (a case is a person, site, or
  focus group that spans several sources — the unit `respondent_id` only
  approximated), `annotations` (notes on a *passage*, distinct from memos, which
  target the project/view/code), and `excerpt_links` ("see also" between
  passages). Additive: a v3 project opens with its contents untouched.
  A *document* needs no new table — it is a `Source` with `type='document'`.
- **Full-text index** over source text (SQLite FTS5), kept in step by triggers —
  including on delete, so an erased respondent leaves no searchable ghost. It is
  created opportunistically and backfilled on first open, and a SQLite built
  without FTS5 still opens the store and simply searches by scanning.
- **Corpus-scale reads** — `count_sources`, paged `iter_sources`, `source_types`,
  and an index on `sources(type)`, so a large corpus is never loaded whole.

**Search & lexical exploration** — a new **Search** page.

- **Find any phrase or pattern** across every source, with **KWIC** (keyword in
  context) results grouped by document, exact character offsets, and filters by
  source type, case, or existing code. Text and regex modes; whole-word and
  case-sensitivity toggles.
- **Word frequency** (`analysis/lexical.py`) with an editable stop-word list, a
  themed bar chart and word cloud (both exportable via the v3.9.9 panel), and a
  `documents` column that separates a word one person repeated from a word
  everyone used.
- **Words around the term** — what immediately precedes and follows a query
  across all hits: the legible core of a word tree.
- **Auto-code every hit** — turn a query into codings in one action. Each hit
  becomes an excerpt covering exactly the matched characters, applied under a
  distinct **`auto_textsearch`** rater whose kind is not `human`, so it is
  excluded from human-vs-human kappa and from project merges — auto-coding can
  never inflate a reliability number. Idempotent and fully reversible.

**Architecture.** The new `app/` package starts Phase 0.1: page modules import
only from `core`/`analysis`/`exports` and never from `streamlit_app`, which is
what keeps the UI layer swappable. Search is its first tenant; the existing pages
migrate one at a time in later releases rather than in one risky rewrite.

*Design note:* FTS narrows, Python locates. The index says which sources contain
a term; exact offsets are found in Python, because offsets are what KWIC and
auto-coding need. A consequence worth knowing: the index is token-based, so it is
only used for **whole-word** searches — substring searches ("advis" inside
"advisor") scan the text, since shortlisting them through the index would
silently drop real matches.

## v3.9.9 — July 2026: chart color choice + image export

- **Choose the heatmap colors.** The Analysis co-occurrence chart has a color-ramp
  picker (Blue→Orange, Red→Orange→White, Green→Orange, Purple→Yellow, Teal→Yellow),
  defined in `core/theme.py` and applied to the chart's scale; the choice persists.
  Every ramp keeps low cells visible rather than fading to the background.
- **Export / copy charts.** An "Export / copy this chart" panel under the
  co-occurrence and frequency charts downloads the figure as **PNG** or **SVG**
  (rendered offline by `vl-convert`), the **Vega-Lite spec** (`.json`), and the
  **underlying data** (`.csv`). The image renders on demand (not on every rerun).
  You can also use the chart's own ⋯ menu to save an image, or right-click the
  chart to copy it. `core/viz_export.py` degrades gracefully if `vl-convert` is
  absent (spec + data still download).
- The **frequency** chart is now an Altair bar chart too, so it gets the same
  theming and export. `vl-convert-python` is a new (small, offline, torch-free)
  dependency.

## v3.9.8 — July 2026: light + dark skins and readable heatmaps

- **Two skins — dark (default) and light — with a sidebar toggle.** `core/theme.py`
  now holds two full palettes (same keys) selected by mode; `brand_css(mode)` and
  the Altair theme are built from the chosen one. The **Appearance** control in the
  sidebar (on every page and the start wizard) switches the whole page — chrome,
  panels, banners, inputs, metrics, tabs, and the charts — and the choice persists
  across restarts (via the app-settings whitelist). On the light skin the accent
  red is darkened so headings stay legible on a pale background.
- **Heatmaps are readable again (the "black cells" fix).** The co-occurrence
  matrix used a red-on-near-black ramp whose low/zero cells faded into the
  background — indistinguishable. Both skins now use a high-contrast **blue →
  orange → light** ramp whose low end is a *visible* color, so small counts read
  instead of vanishing, and it's colorblind-safer and distinct from the red brand
  chrome. (Change the ramp in one place — the `heat` key of each palette.)
- **Note on the data grid.** The interactive `st.dataframe` grid renders on a
  canvas that follows Streamlit's *own* theme (⋮ → Settings → Theme), which an app
  can't set at runtime; the skin toggle re-themes everything else, including the
  colored heatmap. For a fully light data grid a user also flips that menu.

## v3.9.7 — July 2026: in-app Model Manager (download any model, offline preserved)

Model acquisition is now a first-class in-app page instead of a script you run by
hand — and it can fetch **any** model for a role, not just the three defaults
(F4 of `V3.9.5_PLAN.md`).

- **Model Manager page** (sidebar, both modes). Shows cache status; lets you point
  each role — **embedding**, **sentiment**, **zero-shot** — at a different Hugging
  Face model and download it, use one that's already cached, or reset to the
  default; and remove models from the cache to reclaim disk. Role guidance is shown
  inline (e.g. the zero-shot slot wants an NLI/MNLI model).
- **Downloads run in a subprocess — the offline guarantee is now structural.**
  The app shells out to `tools/download_models.py` (extended with
  `--model/--role/--json`) rather than lifting `HF_HUB_OFFLINE` in its own process.
  The analysis process is therefore *never* un-pinned by a download; a test asserts
  the app's offline env vars are untouched across a download call. This replaces the
  prior in-process flag-lift on the Run Analysis "Model status" panel (which now
  routes through the same subprocess).
- **Role-explicit downloads fix the name-guess bug.** The old in-app path inferred a
  model's role from its name (`"bart-large-mnli"`→zero-shot), so any custom model
  failed. Downloads now carry the role, and the loader for that role also
  smoke-checks the model can be constructed for it.
- **Sentiment + zero-shot models are now selectable and persist.** Previously only
  the embedding model could be changed, and none persisted; all three now flow
  through `build_general_config` and are remembered across restarts (names only, via
  the app-settings whitelist — never data). `tools/download_models.py` stays the one
  download implementation, shared by the installer and the app.

## v3.9.6 — July 2026: collaborative coding, finished (reconcile the rigor loop)

The plumbing for copy-and-merge collaboration shipped in v3.6/v3.8/v3.9.1; this
closes the *rigor loop* on top of it — code independently → measure agreement →
**reconcile** → report. Three features (F1–F3 of `V3.9.5_PLAN.md`); the in-app
Model Manager (F4) follows separately in v3.9.7.

- **Disagreement drill-down & adjudication (F2).** The Agreement tab's
  human-vs-human view now lists the exact items two coders coded differently —
  each response with both coders' codes side by side — and lets you **resolve**
  each to an agreed set. Resolutions are written as a distinct `human_adjudicated`
  rater (`core/adjudication.py`, `analysis/disagreement.py`), so neither coder's
  original codings (which κ depends on) are touched, and the reconciled set can
  serve as the gold standard. Idempotent; a "no code" resolution is recorded as
  the absence of an application, consistent with the Labeling Lab.
- **Semantic merge suggestions (F1).** The Codebook page gains **"Possible
  duplicate codes"** — pairs whose name + definition are semantically similar
  ("Cost worry" ≈ "Financial stress"), from cosine similarity over the cached
  local embedding model (`analysis/code_similarity.py`, offline, no new
  download), each with a one-click merge. Replaces the crude substring-only check
  that was the only prior signal. Nothing is ever auto-merged — the human
  confirms every pair.
- **Codebook health (F3).** A Codebook-page panel (`analysis/codebook_health.py`)
  flags **dead codes** (never applied), **singletons** (applied once), **undefined
  codes**, **orphan parents**, and **over-deep nesting** — most useful right after
  a merge introduces emergent codes.

All logic is pure, offline, and tested (22 new unit tests + an AppTest that drives
the render and the adjudication write). No locked decisions changed: IRR stays
kappa-only, collaboration stays copy-and-merge, the whole-response unit is
unchanged.

## v3.9.1 — July 2026: portable project archive + self-sufficient project files

Two features that make a project genuinely portable between installations and
collaborators — the follow-through on v3.8's copy-and-merge collaboration model.

- **Whole-project archive (.zip).** Data Management → **Project archive (.zip)**
  exports the entire project folder — the `.qnw` store plus its run outputs and
  report — as one zip to carry to another machine, and imports it there in one
  step (sets it active). `core/project_archive.py` deliberately excludes
  `project_backups/` (which can hold a pre-erasure copy of an erased respondent),
  embedding caches, and `__pycache__`; import is zip-slip-safe. Complements the
  existing single-file `.qnw` share and the JSON interchange.
- **Rebuild responses from a project (.qnw).** A colleague who receives only the
  project file previously couldn't code from it — the `.qnw` carries the analysis
  but not the original spreadsheet, so Data Setup and the Labeling Lab were empty.
  `core/reconstruct.py` regenerates the long-format working dataset directly from
  the store (every response's `response_id`, `question_text`, `response_text`,
  plus descriptors and any `respondent_id`), and **Data Setup → Option D →
  "Rebuild responses from active project"** loads it with the column mapping
  pre-set. The PII gate still re-arms (it's real response text). This makes the
  `.qnw` self-sufficient for independent labeling — no data-file hand-off needed.
  Response ids stay string-typed on the way out, preserving the coding/agreement
  join key.

## v3.9.0 — July 2026: rebrand to QualSafe + lean end-user release package

- **The tool is now named QualSafe** (formerly "Qualitative NLP Workbench").
  Renamed everywhere user-visible: the app title, installers/launchers/
  uninstallers, `INSTALL_FIRST.txt`, README, the Word-report footer, the
  model-setup banner, the schema-too-new error message, and the
  package metadata (`pyproject.toml` name is `qualsafe`; console entry points are
  `qualsafe-survey`, `qualsafe-iterative`, `qualsafe-download-models`). The
  release zip is now `QualSafe_v<version>.zip`.
  **Unchanged on purpose:** the `.qnw` project-file extension, the store schema,
  and all file formats — existing projects, backups, and exports open exactly as
  before. No analysis behavior changed.
- **The release zip is now an end-user installer package, not a repo snapshot.**
  `tools/build_release.py` additionally excludes the internal development
  documentation and repo metadata: `HANDOFF.md`, `project_progress/`, the design
  notes / release checklist / packaging guide in `docs/`, `notebooks/`, and `.github/`. The zip keeps everything an end user (or
  reviewer) needs: the app and installers, sample data, `README.md`,
  `CHANGELOG.md`, `INSTALL_FIRST.txt`, `LICENSE`, the user guide and analyst
  cheat sheet, and the offline test suite.
- **The app now opens a browser tab on launch again.** `.streamlit/config.toml`
  had `server.headless = true`, which starts the server but never opens the
  browser — the launcher window just sat there. Set to `false`; the installers
  now pre-seed an empty `~/.streamlit/credentials.toml` so this doesn't trigger
  Streamlit's first-run "Email:" console prompt.
- **Guard against unsupported Python (3.13 / 3.14).** The pinned stack
  (`numpy<2.0`, the CPU `torch` build) has no wheels for CPython 3.13+, so
  installing on 3.14 made pip compile NumPy with MinGW — the *"Numpy built with
  MINGW-W64 … experimental"* banner plus `getlimits.py` warnings and later
  crashes. The installers now (a) prefer the newest **supported** interpreter
  (3.12 → 3.9) even when a newer one is present, and (b) refuse 3.13+ with a
  plain-language message pointing to Python 3.12. `requires-python` is capped at
  `>=3.9,<3.13`; the README / INSTALL_FIRST requirement notes updated to match.
- **Fixed: survey Data Setup was stuck at the PII gate.** Confirming the FERPA/PII
  checkbox did nothing — the checkbox reverted to unticked on the rerun and
  **Column Mapping never appeared**, so no analysis could start. The re-arm
  helper (`reset_pii_gate_if_source_changed`) keyed "is this a new file?" off
  `last_confirmed_source`, which is only set *after* confirmation, so it fired on
  every rerun of an unconfirmed file and popped the checkbox's widget state
  before the confirmation could be recorded — an unbreakable loop. It now tracks
  the armed-for source separately (`pii_gate_armed_for`) and re-arms exactly once
  per genuinely new dataset. A new AppTest regression drives the real
  tick→rerun→mapping flow (the prior unit test exercised the helper in isolation
  and missed it). **Present since v3.1.1**; surfaced by the first real file
  upload.

## v3.8.0–3.8.2 — July 2026: live-project readiness (resume, recovery, collaboration, export)

Three releases from `V3.8_PLAN.md`, driven by a code-verified audit against six
axes: exporting, recovery, pausing/resuming, team collaboration, ingestion, and
sharing codes. The audit surfaced two features that were fully built but had no
UI, plus real gaps for a multi-day, multi-coder project.

### v3.8.0 (P0) — nothing lost, easy to resume

- **Labeling Lab autosave.** Every card action now writes through to
  `coding_sample.csv` (signature-guarded), so a Streamlit restart or a closed tab
  costs nothing — previously codes lived only in session state until you clicked
  save. One serialization is shared by autosave and the manual button (which now
  does the project-store write); the CSV is the reload source of truth.
- **Session resume.** `core/workspace.py` persists the session *shape* — the data
  file's path, ingestion mapping, descriptors, question scope, and theme labels —
  never response data. The start wizard offers a one-click **"Resume last
  session"**; the PII gate re-arms per load by design, and a workspace whose data
  file has moved is silently ignored rather than offered.
- **Store safety backups.** `core/backups.py` snapshots the `.qnw` before every
  destructive/bulk operation (respondent erasure, team merges, codebook restores),
  keeps the newest 5 in `project_backups/`, with restore + delete-all in Data
  Management. Erasure now warns that the pre-erasure backup must be deleted to
  complete an erasure.
- **Surfaced two buried features.** The Codebook page gains a **Version history**
  panel (list / tag / restore over the v3.5 snapshot backend, with a pre-restore
  backup); Data Management gains **project JSON export/import** over the
  long-existing `export_json`/`import_json`.

### v3.8.1 (P1) — sharing codes + real team merge

- **Codebook exchange** (`core/codebook_io.py`): export the codebook as YAML
  (names, definitions, hierarchy by parent name, origin — no data), and import it
  into any project. Import is **additive and name-matched** — codes you already
  have are skipped and reported, never clobbered; unresolved parents are reported,
  not invented. "Use as Theme Setup labels" loads a codebook's names as the label
  set. This is the "start the spring survey with our standard codebook" workflow.
- **Custom label packs** (`core/label_packs.py`): save the current labels as a
  named pack (plain YAML beside the app settings — also a shareable file); saved
  packs appear first (★) in the Theme Setup pack list.
- **Project-store merge** (`core/store_merge.py`): fold a colleague's `.qnw` into
  the active project — **human codings and emergent codes only**, reconciled on
  `(response_id, question)` (never internal source ids), each rater kept distinct,
  replace-per-rater so re-merging an updated file is idempotent. Codes match by
  exact name; near-name pairs ("Cost worry" ≈ "Financial stress") are *suggested*
  for you to merge on the Codebook page, never merged automatically. Machine
  codings are excluded; unmatched responses are reported; the target is backed up
  first.

### v3.8.2 (P2) — deliverable formats + ingestion breadth

- **Word report export** (`exports/docx_report.py`): a formatted `.docx` —
  codebook, frequencies, top co-occurrences, human–model agreement, and memos
  (where interview per-theme summaries live). Same redaction rule as the bundle:
  redacted by default, verbatim quotes only when explicitly included. IR
  deliverables are Word documents; this closes the last-mile gap.
- **Qualtrics-aware ingestion** (`core/ingest.strip_qualtrics_metadata`): detects
  the Qualtrics signature (an `ImportId` row in the first few rows) and strips the
  question-text/ImportId metadata rows that would otherwise be coded as responses,
  with a visible notice. No-op on normal files. Runs on every load.
- **Excel analysis workbook** (`exports/excel_workbook.py`): one `.xlsx` with
  codebook / frequency / co-occurrence / agreement sheets. **Never contains
  response text** — always safe to attach to an email.
- **Optional SPSS `.sav`** via `pyreadstat` (a `spss` extra). Loading a `.sav`
  without the package gives an actionable "pip install pyreadstat" message rather
  than a crash.

### Tests

- **454 → 493 passing**, offline and torch-free. New suites:
  `test_v380_recovery.py` (autosave roundtrip, workspace never stores data,
  stale-workspace ignore, backup prune/restore/undo, erasure+merge take backups),
  `test_v381_sharing.py` (codebook import is additive/never-clobbers, unresolved
  parents reported, label-pack CRUD, store merge idempotent + near-name suggested-
  not-merged + machine-codings-excluded + unmatched-reported + backup taken), and
  `test_v382_exports.py` (docx redaction walk of the .docx XML, Qualtrics strip,
  Excel sheets contain no raw text, `.sav` actionable-error).

## v3.7.1 — July 2026: tooltips, education defaults, better sample data

Incremental polish on the v3.7 UX pass.

### Hover explanations throughout

- Added `?` hover tooltips to the options that lacked them, written as plain-
  language explanations of *what the option does and when you'd change it*:
  Theme Setup (label pack, labels box, all four strict-coding controls — including
  what the threshold and margin actually gate), Run Analysis (all four mode
  checkboxes), Data Setup (folder browsing, sample loader), the Labeling Lab
  (sample size, output folder), the Agreement tab (minimum support), and the
  Code × Descriptor tab (descriptor choice, count-vs-percent normalization).

### Education presets are the default

- New **"Education / Student Experience"** label pack (belonging, financial
  concerns, academic difficulty, time management, advising, mental health, campus
  life, commuting) is now the **first/default** pack in Theme Setup — this tool's
  home audience is institutional research. The old classroom-feedback pack remains
  as "Course / Instruction Feedback".
- The wizard's "Try it with sample data" now also pre-fills the education labels
  (when you haven't typed your own), so the sample path runs end-to-end with zero
  configuration.

### New built-in sample datasets (both modes)

- **Survey:** `data/sample_survey_education.csv` — 40 responses to one open-ended
  question ("What has been the most challenging part of your first year, and what
  would help you succeed?"), written to sound like real students: varied length,
  overlapping themes, a few terse answers. Pairs with the default label pack and
  the guided sample project's codebook (both updated to match). PII-scan-quiet by
  test. Replaces the customer-experience CSV as the default sample (the old file
  remains in `data/`).
- **Interview:** `data/sample_interview_transcript.txt` — a ~15-minute synthetic
  first-year-student interview: 5 general unstructured questions plus natural
  follow-ups and backchannels, with deliberately wandering answers (money worries
  surface inside the belonging answer, and vice versa) so the theme-regrouping
  feature has something real to show. A **"Use the sample transcript" button** in
  Interview Mode loads it directly — no PII attestation needed for a file the tool
  ships. The example interview template gained matching "Work & finances" and
  "Suggestions for improvement" themes, so template matching and off-template
  detection both demonstrate.
- Verified end-to-end: the transcript segments at confidence 1.00 with the
  `Interviewer:/Respondent:` detector, roles infer correctly, and ≥5 main
  questions detect and pair.

### Tests

- **444 → 454 passing.** New `test_sample_datasets.py`: the survey CSV parses
  with a plain `pd.read_csv` (the old sample shipped malformed — never again),
  40 rows/one question/unique ids, PII scan stays quiet, dataset vocabulary
  overlaps the default pack; the transcript segments/roles/questions/pairs, sits
  in the ~15-minute word range, and every example-template theme has keyword
  presence in it.

## v3.7.0 — July 2026: start wizard and guided-workflow UX

A usability pass focused on the first-run and returning-user experience. No
analytical behavior changes.

### Start wizard (mode chooser)

- **The app now opens with "What are you analyzing?"** — two cards, mirroring the
  fork the whole tool is organized around: 📊 **Survey responses** (many rows,
  transformer or local-LLM engine) vs 🎙️ **Interview transcript** (one document,
  guided wizard). Two zero-friction on-ramps for new users: **"Try it with sample
  data"** (loads the synthetic survey and walks into the normal flow, PII gate and
  all) and **"Build & open a demo project"** (constructs the offline SAMPLE
  project and lands on the Analysis page — no data or models needed).

### Mode-aware, numbered navigation

- The flat 11-page sidebar — the biggest wall for a newcomer — is replaced by a
  **per-mode, workflow-ordered list with numbered steps** (Survey: 1·Data Setup →
  2·Theme Setup → 3·Run Analysis → 4·Labeling Lab → 5·Analysis …; Interview:
  1·Interview Mode → 2·Analysis …). A **"⇄ Switch mode"** button returns to the
  wizard at any time. Pages that don't apply to the current mode simply aren't
  shown.

### Guided next steps + status

- **"Continue →" buttons** lead from Data Setup → Theme Setup → Run Analysis, and
  a persistent **last-run panel** on Run Analysis offers "View results" /
  "Explore the analysis" — users are led through the workflow instead of hunting
  the sidebar.
- **A sidebar status panel** shows at a glance: rows loaded, PII check state,
  theme-label count, active engine/model, and the active project.

### Settings that survive restarts

- Mode, engine, LLM model, analyst name, and the active project now persist to a
  small local `app_settings.json` (new `core/app_settings.py`) and are restored on
  launch. A **whitelist, never a session dump** — no data or derived content is
  ever written, and the file is plain JSON a user can read. `QNW_SETTINGS_DIR`
  overrides the location (used by tests).

### Fixed

- **The guided sample project was invisible.** The Analysis/Codebook project
  pickers only globbed `run_*` directories, so `SAMPLE_guided_project` — the
  onboarding path built in v3.4 — never appeared in them. The picker now lists any
  output directory holding a `project.qnw`.

### Tests

- **431 → 444 passing**, offline and torch-free. The app smoke test is rewritten
  for mode-aware navigation (wizard render, every page per mode, interview nav
  omits survey-only pages) and now *drives* the wizard: clicking the survey card
  routes to Data Setup, and Switch mode returns to the wizard. Plus
  `test_app_settings.py` (roundtrip, whitelist, corrupt-file tolerance).

## v3.6.0 — July 2026: team coding, cross-question view, uninstall, packaging

Two collaboration/analysis features plus release tooling.

### Team task distribution

- **Split a coding sample across a team** from Data Management, in two explicit
  modes: **partition** (disjoint slices for throughput — no inter-rater agreement
  to compute, and the UI says so) or **overlap** (a shared calibration set everyone
  codes for reliability, plus a partitioned remainder). Each coder gets a CSV;
  filled files merge back, each coder mapped to a distinct rater in the store, with
  a coverage report showing how many items are double-coded (the overlap the
  Agreement tab computes kappa over). Copy-and-merge topology — no shared-file
  locking; the merge reconciles on `response_id`, never internal source ids.

### Wide-form cross-question view

- **`respondent_id` is now distinct from `response_id`.** Wide-format ingestion
  emits a unique per-answer `response_id` (respondent + question) *and* a
  `respondent_id` that groups a person's answers across questions — which also
  resolves the wide-form duplicate-id collision the ingestion warning flagged.
- **Respondent-level co-occurrence.** The Co-occurrence tab gains a "per
  respondent" unit: codes co-occur when the same *person* raised both, even across
  different questions — a wider "these themes travel together in a person" view
  than same-response co-mention. Wired through the store (respondent_id in the
  coding table + `sources_by_respondent`). LLM cross-question *coding* (giving the
  model a respondent's other answers as context) remains deferred — it changes the
  unit of analysis and needs a provenance flag.

### Uninstall / clean reinstall

- **`uninstall_windows.bat` / `uninstall_mac_linux.sh`** (+ `tools/uninstall.py`):
  remove caches and outputs, optionally the virtual environment, optionally the
  Hugging Face model cache — with a confirmation and a clear report of what's
  removed, so a fresh install starts clean. Run with system Python so it can
  delete `.venv`. Plus an in-app "Clear embedding caches" button.

### Packaging

- **`tools/build_release.py`** builds a clean distributable zip of the whole tool,
  excluding `.venv`, outputs, caches, and git internals (the old PowerShell
  packager predated half the packages and shipped an incomplete app). Version is
  read from `pyproject.toml` (single source of truth), bumped to **3.6.0**.

### Tests

- **414 → 431 passing**, offline and torch-free. New `test_features_ab.py` (split
  partition/overlap, merge + coverage, respondent_id through ingestion→store,
  respondent-level co-occurrence) and `test_uninstall.py`.

## v3.5.0 — July 2026: scale, method depth, Ollama setup, and quick preview

Phase 4 (the v4 "scale and method depth" work) plus two requested additions:
guided Ollama installation and a quick-preview run.

### Scale & method depth

- **LLM engine concurrency.** `LlmEngine.code_responses` now overlaps Ollama calls
  with a small thread pool (`engine.llm.concurrency`, default 3), preserving input
  order via indexed futures and thread-safe progress. Default is low on purpose —
  Ollama queues past its own parallelism, so more workers rarely helps.
- **Noise-aware review signal.** Responses far from their assigned cluster centroid
  are flagged `possible_outlier` (with `centroid_distance`) — the "belongs to no
  theme?" list, often the most interesting cases. Cheap and dependency-free (no
  HDBSCAN). Adds two columns to `responses_scored.csv`; set
  `clustering.flag_outliers: false` for the pre-v4 exact column set.
- **Codebook snapshots.** Every destructive codebook edit (merge / delete /
  reparent) now auto-snapshots the codebook first, in the same transaction, so the
  change is undoable; plus a manual "tag version" and a diff-based restore that
  preserves applications for surviving codes (a blanket restore would have
  cascade-wiped codings). New `codebook_versions` table (schema v3, migrated).
- **Sentence-level units.** New offline sentence splitter (no spaCy/NLTK download)
  with a char-offset guarantee; `unit: sentence` lays down sentence excerpts at
  populate time. The unit is recorded in every manifest and cross-unit agreement
  comparisons are refused (they measure different things).

### Guided Ollama installation

- **New "Ollama setup" panel** on the Run Analysis page: detects whether Ollama is
  installed, running, and has the selected model, and gives the exact OS-correct
  next step (Windows installer / macOS brew / Linux script) with a re-check button
  and consent-gated, progress-tracked model download. It never runs a system
  installer for you — that stays in your terminal — but it removes the guesswork.

### Quick preview run (Phase 5)

- **A "Quick preview run (50 rows)" button** on Run Analysis runs the pipeline on
  the first 50 responses for fast feedback on what the output will contain, before
  committing to the full dataset. The preview is clearly labeled, written to a
  `preview_*` folder, and never saved as the active project.

### Packaging

- **`pyproject.toml`** with console entry points (`qual-nlp-survey`,
  `qual-nlp-iterative`, `qual-nlp-download-models`), a `light` extra (no torch).

### Tests

- **387 → 413 passing**, offline and torch-free. New `test_phase4.py` (concurrency
  order + overlap, outlier flag, codebook snapshot/restore-preserves-applications,
  sentence splitter + offsets, cross-unit guard) and `test_ollama_setup.py`.

## v3.4.0 — July 2026: sharing, memos, and onboarding

Phase 3 — the two features V2 still owned, ported onto the `.qnw` store, plus a
first-run on-ramp.

### Shareable export bundle (store-backed, redacted by default)

- **New `exports/bundle.py`** builds a zip from the project store: codebook,
  code frequency, co-occurrence, human-vs-model agreement, optional descriptor
  crosstabs, a regenerated report, and a manifest. Exposed on the Data Management
  page.
- **Redaction is at the source, not over files.** With quotes excluded (the
  default) every excerpt/quote/source text is replaced with `[REDACTED]` as it is
  read from the store, and the report is regenerated from the redacted tables —
  fixing the V2 leak where the "redacted" zip copied the un-redacted report in.
  A test walks every zip member (including memos and the report) and asserts no
  source's verbatim text appears anywhere.
- **Descriptor crosstabs are opt-in** (subgroup labels are a re-identification
  vector): default none, chosen per key, with any cell below the threshold flagged
  the way an IR practitioner suppresses small cells. `responses_scored.csv` and
  embeddings are never included. Zip members use relative arcnames so a home-dir
  path can't leak a username.

### Memos

- **Analytic memos throughout the UI**, backed by the store's existing `memos`
  table: a project memo panel and per-view memos ("memo this view") on the
  Analysis page, and a per-code memo panel in the Codebook editor. Optionally
  included in the export bundle (redacted with the same guarantee).
- **Merging a code now re-targets its memos** to the surviving code instead of
  leaving them dangling on a deleted target. New `Project.list_memos` filters,
  `update_memo`, `delete_memo`.

### Guided sample project (onboarding)

- **One click builds a `SAMPLE_`-prefixed demo project** from the synthetic
  feedback dataset — a starter codebook, keyword-assigned machine codings, a few
  human codings (so the Agreement tab computes a real kappa), and a memo — so
  every analysis panel has something to show on a fresh install. Built entirely
  offline (no models, no Ollama). Clearly marked so it's never mistaken for real
  work.

### Fixed

- **Repaired `data/synthetic_customer_experience_feedback.csv`.** A third of its
  rows (15 of 45) had an unquoted comma in the question text, so `pd.read_csv`
  errored — which also silently broke the app's own "Load Synthetic Sample"
  button. The question field is now properly quoted; all 45 rows parse.

### Tests

- **374 → 387 passing**, offline and torch-free. New `test_phase3_exports.py`
  (the redaction-leak walk, bundle contents, memo CRUD + merge re-targeting, and
  the guided sample project producing a usable agreement table).

## Unreleased

### Fixed — Labeling Lab corrupted the training CSV (response_id integrity)

A data-integrity bug in the Iterative Labeling Lab could shift, `nan`, and
duplicate response ids, mangling `coding_sample.csv` and silently breaking the
human↔model agreement join. Two compounding causes:

- **CSV round-trip float coercion.** Reloading `coding_sample.csv` let pandas
  infer a numeric `response_id` column as float, so `"101"` came back as `101.0`
  → `"101.0"` — a different key than the coding widgets and the save mapping used.
  Codes appeared to vanish, and blank ids collapsed to duplicate `"nan"`. Fixed by
  reading the coding CSV as all-text (`dtype=str, keep_default_na=False`) in the
  Lab, the training step, and the Agreement tab, so ids stay stable and empty
  label cells stay `""` instead of `NaN`.
- **`prepare_dataset` minted `"nan"`/`"None"` ids.** A blank value in a mapped id
  column stringified to the literal `"nan"`, colliding across rows. Blank ids now
  get a unique positional fallback (`row_N`) with a warning, and whole-number
  float ids render without the spurious `.0` (new `clean_id_str`/`clean_id_series`).

This also repairs the IRR overlap: a float-coerced human `"101.0"` no longer
misses the model's `"101"`, which previously showed as "no overlapping ids".

### Fixed — pipeline progress feedback (GUI + terminal)

- **The default (transformer) engine now shows a real progress bar.** Previously
  only the LLM engine did; the transformer path — which most runs use — showed an
  indeterminate spinner while the actual progress (embedding, silhouette k-search)
  printed only to the terminal, so a slow CPU run looked hung. `run_pipeline` now
  reports `(fraction, message)` at every stage boundary (Building embeddings →
  Discovering clusters → Analyzing sentiment → Coding themes → Per-question → Writing
  outputs), and the LLM engine's per-response progress maps into its stage's slice
  so that bar keeps moving too. The two genuinely slow, formerly-silent stages —
  silhouette-based cluster selection and zero-shot coding — are now named while
  they run.
- **Terminal output is readable.** The Streamlit app now attaches a console log
  handler, so the pipeline's `[i/n] stage` banners (and existing INFO logs) appear
  in the launching terminal instead of only raw tqdm bars.
- The progress callback contract changed from `(done, total)` to
  `(fraction, message)` at the `run_pipeline` boundary; the per-item
  `(done, total)` contract inside the LLM/interview engines is unchanged.
- **Per-response detail within the slow transformer stages.** Zero-shot coding
  now reports per chunk and silhouette k-search reports per k, so the two
  formerly-frozen stages show a moving bar (e.g. "Coding themes (48/200)"). The
  detailed path is only taken when a GUI progress callback is present; with no
  callback the original single-shot calls run unchanged, so CLI/test output stays
  byte-identical (verified: chunked zero-shot output equals the single call).

## v3.3.0 — July 2026: methodological rigor

Phase 2 of the roadmap — the changes that make the tool's numbers defensible in a
write-up. Several change *results* on identical input; each is called out.

### ⚠️ Behavior changes (results)

- **Coding-sample selection is now strategy-driven** (`iterative_supervised.sampling`,
  default `auto`). Round 0 is cluster-stratified random so the seed set spans the
  response space; later rounds order by model uncertainty (active learning — label
  the most informative items next). **The caveat that travels with it:** an
  uncertainty-selected sample is no longer random, so kappa computed on it
  *understates* whole-corpus agreement and its label prevalence is biased. The tool
  writes `sampling_note.txt` stating which strategy ran and its consequences, and
  the Agreement tab surfaces it. Set `sampling: random` to keep an unbiased sample.
- **Tiny-sample quality is now cross-validated, not a single 30% holdout.** On the
  10–30-row samples this tool actually runs, one holdout tests on 3–9 items and
  swings wildly. Now: n<30 → leave-one-out, 30+ → 5-fold, with per-code metrics
  reported only where support ≥ 5 (reusing the `insufficient_support(<N)`
  convention from the agreement module). The quality report format changed
  accordingly.

### Rigor features

- **`in_training_sample` flag** on iterative predictions. The model was fit on
  those rows, so its agreement there is not held-out evidence — the Agreement tab
  **excludes training items from kappa by default** (with a toggle, and an explicit
  "no held-out items yet" empty state instead of a misleading number).
- **Per-engine strict thresholds** (`strict_thresholds: {transformer, llm}`). NLI
  entailment scores and LLM self-report scores are not comparable — an LLM's 0.6
  and a zero-shot model's 0.6 mean different things — so the confidence gate is
  stored per engine and the active engine's pair is overlaid at run time and
  recorded in the manifest. Legacy flat `strict_coding` still works (applies to
  whichever engine runs). LLM defaults start stricter (top-1 ≈ 0.70) because its
  scores cluster high; marked provisional pending calibration. The UI shows the
  active engine's thresholds with the non-comparability caption.
- **Multi-coder groundwork.** `Project.rater_labels(rater_id)` returns the
  `{excerpt: set(code)}` shape the agreement function already consumes, so
  **human-vs-human kappa falls out of the existing `per_code_kappa` with no new
  statistics code**. A second coder's `coding_sample.csv` imports as a distinct
  rater (`import_second_coder_sample`) from the Data Management page, and the
  Agreement tab gains a "Human vs. second human" mode that shows the overlap N and
  warns when coders only partly overlap. Still **kappa-only** — no Krippendorff's α
  (consistent with the locked design decision).

### Tests

- **330 → 359 passing**, offline and torch-free.
- New `test_phase2_rigor.py` (sampling order/stratification, CV scheme selection +
  per-code suppression, per-engine overlay + legacy fallback, human-vs-human κ from
  the existing function) and `test_iterative_flow.py` (mocked end-to-end:
  sampling note, training flag, cross-validated quality, and the round-2
  uncertainty transition).

## v3.2.0 — July 2026: the `.qnw` store becomes the project of record

Phase 1 of the roadmap. The project store stops being a per-run throwaway and
becomes the durable home for both machine and human coding — which is what makes
the Agreement/IRR surface meaningful and what a right-to-erasure request acts on.

### The store persists and accumulates

- **Populate is additive.** `core/populate.populate_project_store` no longer
  deletes and rebuilds the store each run. It opens the existing store, reuses the
  Source already minted for a response (matched on `response_id` + `question_text`),
  reuses Codes by name, tags this run's applications with a fresh `run_id`, and
  runs the whole thing in one transaction. **Why it matters:** the old
  delete-every-run behavior would have destroyed the analyst's own Lab coding on
  the next pipeline run.
- **Human codes enter the store.** Saving in the Iterative Labeling Lab now also
  writes `record_human_codings` into the active project: a `human_primary` rater,
  Lab-invented labels as first-class `origin="emergent"` codes, and
  `CodeApplication`s the Agreement tab can compare against the model. Re-saving a
  sample *replaces* that rater's codes on those excerpts rather than appending, so
  recoding a response doesn't double-count it.
- **The response_id ↔ source_id join.** The Lab keys on the CSV's `response_id`;
  the store keys on `source_id`. Populate now records `response_id` +
  `question_text` in each Source's metadata, and `Project.find_source_by_response_id`
  (SQLite `json_extract`, question-scoped) resolves the join — with an index so it
  stays fast on large stores.
- **Active-project rule.** The app tracks one active `.qnw` (set by the last run,
  or chosen on the new **Data Management** page); pipeline populate and the Lab
  both write to it, so human codes never land in a store the next run wipes.

### Schema migrations (built now, while stores are young)

- **New `core/migrations.py`.** A forward-only version→function migration harness,
  run on open inside one transaction. `SCHEMA_VERSION` is now 2 (adds the
  response_id index). Opening a store written by a *newer* version raises
  `SchemaTooNewError` rather than guessing. A startup check asserts SQLite's JSON1
  extension is present instead of failing cryptically mid-run.
- **`Project.bulk()`** context manager: defers per-write commits so populate is one
  atomic transaction (also fixes the thousands-of-commits slowness).

### Right to erasure

- **New `core/erasure.py`.** `erase_respondent` removes one person from the store
  (FKs cascade excerpts + applications) **and** the derived artifacts a run leaves
  behind: it drops matching rows from run CSVs (re-sanitized on the way out),
  scrubs the respondent's quoted text from `example_quotes` columns and the
  markdown report (which have no id to filter on), and deletes embedding caches
  outright (row-aligned arrays can't be surgically edited). An `audit_log.jsonl`
  event records *that* an erasure happened via `sha256(response_id)` — proof
  without retaining the identifier. `purge_project` deletes an entire project.
  Honest posture, documented: this unlinks files, it does not shred disk sectors.
- **New Data Management page:** pick the active project, set the analyst name,
  erase a respondent by id, or purge a project behind a typed confirmation.
- **`Project.delete_source` / `delete_by_response_id`**, with a test asserting the
  shared codebook survives a source deletion (deleting a respondent must never
  touch Codes).

### Shared embedding cache

- **New `core/embedding_cache.py`**, extracted from the iterative workflow so the
  main survey pipeline caches too — a re-run over the same responses reuses vectors
  instead of re-encoding. The cache key now includes the `normalize` flag (a run
  that flips it must not be served the other version), files are LRU-evicted, and
  the cache dir lives beside the run outputs so erasure/purge find it. The
  iterative module keeps its function name as a thin wrapper.

### Tests

- **311 → 330 passing**, still fully offline (verified again in a torch-free venv).
- New `test_phase1_store.py`: migrations (v1→v2, future-version refusal), human
  codings (emergent codes, replace-not-append, question-scoped join, unmatched
  reporting), erasure across artifacts (store + CSVs + report + caches + hashed
  audit), and the shared cache (hit/miss, normalize-in-key, clear).

## v3.1.1 — July 2026: release blockers, offline enforcement, dark theme

Phase 0 of the v3.1.1→v3.2 roadmap. No new analytical features — this closes the
gaps that should be shut before the first public tag.

### ⚠️ Behavior changes (results / workflow)

- **`config/iterative_supervised.example.yaml`: `drop_duplicates` is now `false`
  (was `true`).** Dropping duplicate responses discards real respondents: if 40
  students independently answer "cost", collapsing them to one row understates
  that theme's prevalence and biases every frequency and agreement statistic
  computed downstream. **Old behavior:** duplicate response texts within a
  question were removed before analysis. **New behavior:** every response is
  analyzed. **To restore:** set `preprocessing.drop_duplicates: true`. The main
  survey config already defaulted to `false`; only the iterative example changed.
- **Streamlit input snapshots moved.** They now live in the run's own output
  folder (`output_streamlit/run_*/input_snapshot.csv`) instead of accumulating in
  a global `data/session_inputs/`. Existing leftovers are detected and listed in
  Results & Downloads with a delete button; nothing is removed automatically.
- **`runOnSave = false`** in `.streamlit/config.toml`. Runs write files back into
  the project tree, so file-watching could re-trigger the script. Re-run from the
  button.
- **The PII confirmation now re-arms per file.** It previously persisted for the
  whole session, so a second dataset was processed under the first one's
  attestation.

### Privacy: the local-first claim is now enforced, not just intended

- **New `core/offline.py`.** `enforce_local_mode()` pins the Hugging Face stack to
  the local cache (`HF_HUB_OFFLINE`, `TRANSFORMERS_OFFLINE`) and disables
  telemetry, and is called at the top of every entry point. Uses `setdefault`, so
  a user on a proxy can still override from their environment. **Ollama is
  deliberately unaffected** — it is a localhost service, and gating it would
  break the LLM engine for no privacy gain.
- **Model acquisition split from model use.** New `tools/download_models.py` is
  the only code path that lifts the offline flags (plus one explicit,
  button-gated equivalent in the app, which restores the flags afterwards). Wired
  into both installers as an explicit step 5.
- **New "Model status" panel** on Run Analysis: per-model cache state and a
  download button. A missing model now raises `ModelNotDownloadedError` with
  instructions instead of an opaque HF traceback.
- **Corrected the manifest's privacy overclaim.** `PRIVACY_NOTE` said processing
  was local while runtime hub access was in fact wide open. It now describes what
  the code actually does, and the manifest additionally *records*
  `local_mode.offline_enforced` + the env state, so an auditor can check rather
  than trust the prose.
- **New `privacy/scan.py`** — assistive PII scan (emails, phones, SSNs, long
  numeric IDs, suspicious column names, name-like columns) rendered above the
  confirmation checkbox, with an optional one-click mask recorded in the
  manifest. Explicitly heuristics, never a verdict: it is presented as "review
  these", because a scan that blocks on false positives (years, prices) trains
  analysts to click through, which is worse than no scan.

### Fixes

- **CSV injection guard no longer depends on dtype.** `sanitize_for_csv` was
  applied only to `select_dtypes(include="object")` columns, which silently skips
  pandas' `StringDtype` — the default for text in pandas 3. New
  `sanitize_frame_for_csv` selects by exclusion (skip numeric/bool/datetime) and
  relies on the per-value `isinstance` guard, removing the failure mode rather
  than patching it. Numeric columns are still left untouched.
- **Duplicate `response_id` warning at ingestion.** Response ids are the join key
  for agreement and the project store, where a collision silently merges two
  respondents. User-supplied id columns are now checked and warned about at load
  time.

### Performance

- **Heavy imports are deferred.** `sentence_transformers` / `transformers` now
  import on first model use rather than at module scope. This is what makes
  offline enforcement possible (the env must be set before those libraries read
  it), and it drops the test suite from **84s to ~20s**. The module-level
  `SentenceTransformer` / `pipeline` names are retained as lazily-resolved
  sentinels, so they remain the single mock point for tests.
- **New `requirements-light.txt`** — the whole suite runs green with no torch
  installed (verified: 311 passed in a torch-free venv). CI is now split: a
  `light` job on every push (seconds, and re-run with the offline flags forced),
  and a weekly `full` job against the pinned ML stack.
- **Optional `pipeline.dedupe_embeddings`** (default `false`): encode each
  distinct text once and broadcast to duplicate rows. Off by default because it
  is not bit-for-bit reproducible — batching changes padding, float addition is
  not associative, and a last-bit difference can flip a borderline response into
  a different cluster. Opt in for large duplicate-heavy datasets; the setting is
  recorded in the manifest either way.
- Run report now states distinct-text counts when responses repeat, so duplicate
  mass pulling on cluster structure is visible to whoever reads the themes.

### Theme: dark mode (dark grey + red)

- Replaces the Navy/gold-on-white light theme. New **`core/theme.py`** is
  the single source of truth for the palette, the injected CSS, and the **Altair
  chart theme** — previously chart colors were a separate hardcoded copy, which
  is why charts would have stayed light-mode white on a dark page.
- **Warnings are now amber, not crimson.** With red promoted to the brand color,
  a red warning banner reads as ordinary UI rather than as a warning; amber keeps
  the interrupt signal that the strict-coding review queue and the PII gate rely
  on. Red is reserved for brand chrome and genuine errors.
- Contrast verified against WCAG AA: body text ≈15:1, muted text ≈7:1, accents
  ≈6.5:1, white-on-red buttons ≈5:1.

### Tests

- **235 → 311 passing**, all offline and mocked.
- New: `test_offline.py` (env enforcement, the single download path, lazy-import
  mock points, missing-model translation), `test_privacy_scan.py` (detection
  *and* restraint — ordinary prose and numeric columns must not fire),
  `test_session_data.py` (snapshot location, purge, Windows-lock tolerance),
  `test_dedupe.py` (duplicates survive; dedupe matches the undeduped result),
  plus `TestSanitizeFrameForCsv` (the StringDtype regression).

## v3.1 — July 2026: semi-structured interview mode

### I1 — interview parsing core (no LLM; fully offline-tested)
- New **`interview/`** package:
  - **`parse.py`** — document loaders (`.txt`, `.docx` via python-docx, `.pdf` via
    **pdfplumber** — chosen over PyMuPDF because PyMuPDF is AGPL, a license
    conflict with this MIT project) and **turn segmentation** via a library of
    speaker-pattern detectors (`Interviewer:/Respondent:`, `Q:/A:`, timestamped
    `[00:03:12] Speaker 1:`, name/initials + colon) scored per document with a
    confidence signal. No confident match ⇒ a single UNKNOWN turn at confidence
    0.0 — surfaced to the analyst, never silently guessed. **Offset guarantee:**
    every turn's text equals `raw[char_start:char_end]` verbatim (traceability).
  - **`speakers.py`** — role inference (interviewer asks more questions, talks
    less) that *proposes* a mapping with confidence + human-readable rationale;
    the analyst confirms at the review checkpoint. >2 speakers → extras = "other".
  - **`questions.py`** — question detection in interviewer turns (sentence `?` +
    implicit prompts like "Tell me about…", backchannel filter) and Q/A pairing
    (responses up to the next question; same-turn follow-ups attach to the last
    question rather than force-fitting).
  - **`template.py`** — interview-guide schema (YAML → validated
    `InterviewTemplate`), with `to_codes()` mapping themes onto shared-model
    **a-priori codes** (the guide IS a codebook). Example:
    `config/interview_template.example.yaml`.
- New synthetic fixtures in `tests/fixtures/` (one per format + a messy fallback
  case; no real interview data). DOCX exercised via a file generated at test time;
  PDF via mocked pdfplumber (no binaries in the repo).
- Dependencies: `python-docx`, `pdfplumber` added with bounds.
- `tests/test_interview_parse.py` (35). Suite: **191 passing**.

### I2 — template matching + regrouping (deterministic; embeddings injected)
- **`interview/matching.py`** — `match_qa_pairs(pairs, template, embed_fn, config)`:
  cosine of each pair's **question** and **response** against every theme's guide
  questions (weighted equally — a wandering response about belonging counts toward
  belonging regardless of what was asked), plus a **bounded keyword boost**
  (secondary signal: can lift a borderline match over the gate but can never
  confirm a theme alone). Confidence gate `min_similarity` (default 0.45) routes
  weak pairs to the **unclassified bucket** instead of force-fitting; multi-theme
  matches allowed by default (`allow_multi_theme`). Full per-theme scores kept on
  every pair for transparency; match `source` records what drove it
  (`embedding_question` / `embedding_response`, `+keyword`). Embeddings are
  injected (`embed_fn`) — tests use exact deterministic vectors; production wraps
  the shared `build_embeddings` via `default_embed_fn`.
- **`interview/grouping.py`** — `group_by_theme` inverts the transcript (every
  matched pair gathered under each theme, transcript-ordered; multi-theme pairs
  appear in each), surfacing **off-template** pairs; `guide_question_coverage`
  reports which guide questions were actually asked vs skipped (distinct from
  whether the *theme* got content via a response — the report shows both stories).
- `tests/test_interview_matching.py` (17, exact hand-checkable cosines). Suite:
  **208 passing**.

### I3 — per-theme LLM analysis + hardened quote verification + store population
- **`interview/quotes.py`** — the hardened anti-hallucination gate (the Phase 0a
  deferral, due now): locates an LLM-proposed quote in the source through three
  tiers — exact substring; **normalized** (NFKC + curly-quote/apostrophe/dash
  folding + casefold + whitespace collapse, with an index map recovering offsets
  in the ORIGINAL text); **bounded fuzzy** (sliding-window SequenceMatcher,
  ratio ≥ 0.90) for one-word slips. Whatever the tier, the returned quote is the
  SOURCE's own characters (`text == source[start:end]`) — never the model's
  version. Unverifiable quotes are dropped, logged, and counted: the per-theme
  **hallucination rate** is kept as a trust statistic.
- **`interview/analyze.py`** — per-theme LLM analysis over the regrouped material
  via the shared OllamaClient (structured JSON: summary, sub-themes, tone,
  quotes; prompt versioned in `prompts/theme_summary.txt`). Every quote passes
  quote verification before surfacing. Empty groups skip the LLM; a per-theme
  JSON failure degrades to a noted empty analysis; progress callback supported.
- **`interview/populate.py`** — interview runs land in the same `.qnw` model as
  surveys: transcript → Source("interview"); template themes → a-priori Codes;
  matched pairs → response-span Excerpts + CodeApplications (coder="transformer",
  confidence=similarity); **verified quotes → exact-offset Excerpts** +
  CodeApplications (coder="llm", rationale notes the match kind); summaries →
  Memos (author="llm_draft"); Raters + a mode="interview" RunManifest.
  Unclassified pairs produce no applications (off-template, surfaced in reports).
- `tests/test_interview_analyze.py` (17): curly-apostrophe/dash/case/whitespace
  recovery with source-verbatim guarantees, fuzzy word-drop, hallucination
  rejection + stats, mocked-LLM analysis incl. JSON-failure degradation, and
  end-to-end store population from a tiny transcript. Suite: **225 passing**.

### I4 — Interview Mode UI
- New **Interview Mode** page (`interview_ui.py`, wired into the sidebar): a
  sequential wizard —
  1. **Upload** (.txt/.docx/.pdf) behind an interview-specific FERPA/IRB gate;
  2. **Template** editor (YAML, load-example, live validation, theme table);
  3. **Parsing review — the mandatory human checkpoint**: detected pattern +
     segmentation confidence (low-confidence warning; hard stop with guidance
     when no speaker structure is found), proposed speaker roles **with the
     inference rationale** and per-label overrides, turn spot-check, then
     question detection + Q/A pairing on confirm;
  4. **Run**: matching threshold + multi-theme toggle; optional local-LLM
     per-theme summaries with a live progress bar and graceful skip when
     Ollama/model is unavailable;
  5. **Results**: per-theme summaries with **verified quotes** (match kind shown)
     and a dropped-quote/hallucination-rate warning, matched exchanges with
     similarities, guide-coverage table, off-template material.
- Interview runs save `run_iv_*/project.qnw` + a `run_manifest.json` into the
  same output convention as survey runs, so the existing **Analysis**,
  **Codebook**, and **Results & Downloads** pages pick them up with no extra
  wiring — the shared-backbone payoff, visible.
- **`tests/test_app_smoke.py`** (10): the AppTest render-smoke is now a formal
  part of the suite (a deferred P1 item), covering every page incl. Interview
  Mode. Suite: **235 passing**.

### I5 — docs + release
- **README** updated for v3.1: two-modes framing, interview-mode quickstart
  (upload → template → mandatory role checkpoint → run → verified-quote results),
  structure (`interview/`, `interview_ui.py`), and status (235 tests + CI).
- **Welcome page** rewritten to route survey vs. interview workflows.
- **`docs/RELEASE_VERIFICATION_CHECKLIST.md`** — the manual pre-release checks that
  CI can't cover (real models, live Ollama, the file-upload wizard, real
  transcripts, privacy/network spot-check, push + tag).
- v3.1 is feature-complete and green; the release checklist gates tagging.

## v3.0 — July 2026

### Phase 0a — engine abstraction + shared project model (additive, no behavior change)
- **`engines/base.py`**: `ThemeEngine` protocol + `ResponseCoding` dataclass — a
  superset of the v2.1 zero-shot columns that both coding backends return.
- **`engines/transformer_engine.py`**: `TransformerEngine`, a faithful wrapper
  that delegates to the existing `analyze_survey` functions (`run_zero_shot`,
  `run_sentiment`, `assign_strict_labels_from_results`). No model behavior
  changes — it only re-homes the current path behind the engine contract.
- **`core/model.py`**: the seven shared-project entities (Source, Excerpt, Code,
  CodeApplication, Descriptor, Memo, RunManifest) as in-memory dataclasses.
  Includes `Excerpt.verify_offsets()` — the pure-function core of the
  drill-back / anti-hallucination guarantee (with tolerant-whitespace mode for
  LLM-returned quotes).
- **`tests/test_engines.py`**: 16 tests proving the engine reproduces zero-shot,
  strict-gate, and sentiment values exactly, plus offset verification.
- `analyze_survey.py` is **unchanged**; the original 48 tests still pass.

### Phase 0a — schema refinements from design review (still additive, no behavior change)
Five gaps surfaced in the two-lens design review were closed before persistence:
- **Score provenance** on `ResponseCoding` (`score_kind`, `source_engine`,
  `model_id`) + a length invariant on `labels`/`scores`. The transformer engine
  now records whether scores are independent-NLI vs softmax, so downstream never
  compares them naively with LLM self-reported scores.
- **Descriptor typing** via `DescriptorField` (categorical / ordinal / numeric +
  `ordered_levels`), so e.g. `Age_Band` sorts by declared order, not alphabetically.
- **Per-code weight scale** (`WeightScale` on `Code`) so weighted aggregates never
  mix valence / intensity / confidence.
- **Rater + run provenance** on `CodeApplication` (`rater_id`, `run_id`) and a new
  `Rater` entity — the prerequisite for inter-rater (human-vs-AI) kappa alignment.
- **Codebook roll-up semantics** made explicit: `ancestors()` /
  `expand_with_ancestors()` implement the documented default (applying a child
  implies its ancestors; parent-level counts dedupe per excerpt), cycle-safe.
- Tests: **75 passing** total.

### Phase 0a — pipeline rewire (byte-identical, verified)
- `run_pipeline`'s global zero-shot + strict-coding path now runs **through
  `TransformerEngine`** instead of calling the zero-shot functions directly. This
  is the swap point where the Phase 2 local-LLM engine will plug in. The sentiment
  block and the per-question paths are unchanged.
- **`engines/adapt.py`**: adapters that map `ResponseCoding` lists back to the
  exact v2.1 DataFrame columns (same names, formatting, and assignment order).
- `TransformerEngine` now builds its HF zero-shot pipeline **once and reuses it**
  (was rebuilt per call), removing a latent per-question model-reload regression.
- **Verified byte-identical:** a mocked end-to-end harness hashed
  `responses_scored.csv`, `cluster_summary.csv`, `silhouette_scores.json`, and
  `question_theme_summary.csv` before and after the rewire — all four SHA-256
  hashes match. `analyze_survey.py`'s public functions are unchanged; the original
  smoke test and all 75 tests pass.
- **Phase 0a complete.**

### Field-testing fixes — ingestion + labeling lab UX (additive, byte-identity preserved)
Surfaced by end-to-end testing of the Streamlit app:
- **Wide-format ingestion** — Data Setup gains a shape selector (long / wide).
  Wide = pick the question columns (each header becomes a question), melt to long
  via new `core/ingest.reshape_wide_to_long`. Carries an id column + designated
  descriptor columns onto every response.
- **Manual question entry** — in long mode with no question column, type the
  question text instead of the silent "All Responses" default.
- **Descriptor designation** — mark respondent-attribute columns; `prepare_dataset`
  gained opt-in `descriptor_columns` retention (no-op when unset, so v2.1 outputs
  and byte-identity are unchanged). Full code × descriptor cross-tabs remain Phase 3.
- **Explicit scope note** — the UI now states what is analyzed and what is ignored.
- **Iterative Labeling Lab redesigned** as a card view: one response at a time with
  full text, a multi-select from the current theme labels, add-new-label, coder
  notes, prev/next + skip-to-uncoded navigation, and default sample size 30. Both
  the analysis and lab paths reshape identically via one `resolve_long_dataframe()`.
- New `tests/test_ingest.py` (12 tests). Suite: **87 passing**. Byte-identity of the
  survey pipeline re-verified after the `prepare_dataset` change.

### Phase 0b — SQLite `.qnw` project store
- **`core/project.py`**: `Project`, a SQLite-backed store persisting the shared
  model entities (sources, excerpts, codes, code applications, descriptors,
  descriptor fields, memos, raters, run manifests) behind a typed API — no other
  module writes SQL. Structural foreign keys enforced; `rater_id`/`run_id` are
  provenance columns; `WeightScale` flattened onto codes; descriptor levels stored
  as JSON; UUID id-minting; per-write autocommit. Embeddings stay out of the DB
  (npy cache). JSON export/import for portability. Additive: existing CSV outputs
  are unchanged.
- `tests/test_project.py` (10): round-trip persistence, hierarchy + weight scale,
  descriptor fields, FK enforcement, id-minting, JSON export/import.

### Phase 0b — pipeline population (gated, additive, byte-identity preserved)
- **`core/populate.py`**: `populate_project_store` maps a completed survey run's
  response frame onto the project model — each response → Source + whole-response
  Excerpt; descriptor columns → Descriptors; zero-shot labels → a-priori Codes;
  confident (strict-gated or top) assignments → CodeApplications tagged with the
  transformer Rater + RunManifest. Sentiment/cluster id recorded on Source metadata
  (sentiment stays separate, not a code weight).
- `run_pipeline` writes the store **only when `output.project_store_path` is set**,
  and does so **non-fatally** (a store bug can't break the CSV results). Default
  runs unchanged; byte-identity of the survey outputs re-verified.
- Streamlit **Run Analysis** gains an opt-in "Also save a portable project file
  (.qnw)" checkbox (default on); `run_summary` now returns `project_store`.
- `tests/test_populate.py` (4) + an end-to-end check that `run_pipeline` emits a
  populated store. Suite: **101 passing**.

### Phase 1 — Ollama client (mocked; no live server in CI)
- **`engines/ollama_client.py`**: `OllamaClient` — `version`/`is_available`,
  `list_models`/`has_model`, `pull` (streaming progress to a callback),
  `generate_json` (structured output via a JSON-schema `format`, low temperature +
  optional seed, bounded retry). Typed errors (`OllamaNotAvailable`,
  `OllamaTimeout`, `OllamaJSONError`). Host overridable via `OLLAMA_HOST`.
- **`extract_json`** — tolerant, string-aware recovery of the first JSON object
  from prose/fenced small-model output (the JSON-repair step).
- API verified against the live Ollama docs at build time (structured outputs via
  JSON schema, `/api/{version,tags,pull,generate}`), not assumed from the handoff.
- `tests/test_ollama_client.py` (20): all HTTP mocked (only `requests.get/post`
  patched so `requests.exceptions` stay real) — detection, listing, pull-progress,
  schema payload, JSON recovery, retry, and timeout paths. Suite: **121 passing**.
- No UI yet — the engine selector + graceful fallback arrive with Phase 2.

### Phase 2 — survey LLM engine (selectable, with graceful fallback)
- **`engines/llm_engine.py`**: `LlmEngine` implements the `ThemeEngine` contract on
  the Ollama client — prompts a local model per response, parses a structured JSON
  result into a `ResponseCoding` (score-descending per-label scores tagged
  `score_kind="llm_selfreport"`, sentiment, rationale), and applies the **shared
  strict-coding gate**. Invented labels are ignored (codebook stays human-owned);
  missing labels default to 0; a per-row JSON failure degrades to an uncertain
  coding rather than breaking the batch.
- **`prompts/survey_coding.txt`**: versioned, auditable prompt (not inline).
- **`engines/factory.py`**: `resolve_theme_engine` selects transformer vs. llm from
  the `engine.type` config block and **falls back to the transformer engine** when
  Ollama or the model is unavailable — the pipeline always completes.
- `run_pipeline` routes theme coding through the factory. On the **llm path only**
  it adds `zshot_rationale` + `zshot_llm_sentiment` columns (so the transformer
  output stays byte-identical). Sentiment continues to come from the dedicated
  sentiment model regardless of engine (consistent, comparable across engines).
- **Config**: new `engine:` block in `config.example.yaml`. **Streamlit**: a Coding
  Engine selector in Run Analysis with model/temperature/seed inputs and a "Check
  Ollama availability" button.
- `tests/test_llm_engine.py` (6) + `tests/test_factory.py` (6), all mocked; plus an
  end-to-end run through `run_pipeline` on the llm path. Transformer byte-identity
  re-verified. Suite: **133 passing**.

### Phase 3 — analytical core (the Dedoose payoff)
- New **`analysis/`** package of pure functions over the project store, each with
  drill-back ids behind every count:
  - **`frequency.code_frequency`** — applications per code + `excerpt_ids` (optional
    weighted mean).
  - **`cooccurrence.cooccurrence_matrix`** — symmetric code × code matrix (diagonal =
    per-code excerpt count) + per-pair drill-back; **`cooccurrence_jaccard`** for the
    size-independent view. (Whole-response excerpts ⇒ co-occurrence = within-respondent
    co-mention; documented.)
  - **`crosstab.code_by_descriptor`** — distinct-source counts by descriptor value,
    with `group_size` normalization (prevalence per subgroup) and DescriptorField-aware
    column ordering — the mixed-methods analysis.
- **`core/project.py`** gains `coding_table()` (applications joined to source + code
  name) and `descriptor_table()` — the joined inputs that feed the analysis.
- `tests/test_analysis.py` (8): counts/drill-back, co-occurrence matrix + Jaccard,
  cross-tab with group-size normalization + ordinal ordering, and an end-to-end run
  from a populated `Project`. Suite: **141 passing**. Interactive UI for these lands
  in Phase 5.

### Phase 4 — human-vs-AI inter-rater reliability (IRR)
- **`analysis/agreement.py`**: `per_code_kappa(human, model)` computes **per-code
  binary Cohen's kappa** over the shared item set (multi-label ⇒ per-code, not
  multinomial). Kappa-only, but each row also carries **percent agreement** +
  **prevalence** (human/model) — they fall out of the same 2×2, so the kappa
  paradox on rare codes is visible rather than hidden. Codes below `min_support`
  are flagged **insufficient-N** (kappa left NaN) instead of emitting an unstable
  number. `agreement_summary` gives mean + support-weighted mean kappa over
  reliable codes; `low_agreement_codes` routes weak/insufficient codes to review.
  `labels_from_delimited` adapts the tool's existing `human_labels` /
  `zshot_strict_label` columns into the `{item: set(labels)}` inputs.
- `tests/test_agreement.py` (9): a hand-computed kappa (0.6), perfect agreement,
  the **kappa paradox** (0.8 agreement, negative kappa, both surfaced), the
  insufficient-N flag, overlap-only alignment, the adapter, weighted summary, and
  routing. Suite: **150 passing**.

### Phase 5 — analysis + codebook UI
- **Analysis page** (Streamlit): loads a run's `.qnw` store and presents, in tabs,
  **Frequency** (bar + drill-back to responses), **Co-occurrence** (Altair heatmap +
  per-pair drill-back), **Code × Descriptor** (counts or group-size-normalized, with
  respondent drill-back), and **Agreement (IRR)** (per-code kappa vs. the coding
  sample, summary metrics, low-agreement routing).
- **Codebook page**: overview table + rename / define / reparent / **merge** codes,
  saved to the project store.
- **`core/project.py`** gains mutation methods (`rename_code`, `set_code_definition`,
  `set_code_parent` with a cycle guard, `merge_codes`, `delete_code`) and `get_excerpt`.
- `tests/test_project.py` +4 (codebook editing). Headless AppTest render-smoke of the
  new pages passes. Suite: **154 passing**.

### Phase 6 — hardening & release prep
- **`core/manifest.py`**: `run_manifest.json` written on **every** run (CLI + GUI) —
  version, mode, engine, model, thresholds, counts, exports, privacy note. The
  FERPA/IRB audit trail is now unconditional.
- **LLM progress**: the per-response LLM loop reports progress via `tqdm` (CLI) and a
  `progress_callback` driving a live Streamlit progress bar — no more opaque spinner.
- **`requirements.txt`**: `altair` pinned explicitly (used directly for the heatmap);
  new **`requirements-dev.txt`** (pytest).
- **CI**: `.github/workflows/tests.yml` runs the offline suite on push/PR.
- **README** rewritten for v3; `.gitignore`/`.gitattributes` hardened; repo initialized.
- `tests/test_manifest.py` + an LLM progress-callback test; the smoke test now asserts
  the manifest. Byte-identity of the four core outputs re-verified. Suite: **156 passing**.

## v2.0.0 — June 2026

### New Features
- **Test suite** (`tests/test_pipeline.py`): unit tests for strict coding logic,
  multi-label parsing, cluster extraction, and a full pipeline smoke test.
- **Embedding cache** in iterative workflow: embeddings are hashed and cached to disk;
  subsequent `train` runs reuse the cache instead of re-running the encoder.
- **Advanced Options** expander in Streamlit Theme Setup and Run Analysis pages:
  exposes clustering bounds (min_k / max_k), per-question label mapping, batch sizes,
  and embedding model selection — previously only accessible via CLI/YAML.
- **PII / FERPA warning** on the Data Setup page: explicit confirmation required
  before analysis can proceed; includes guidance on what to check.
- **Post-run coding summary** in Run Analysis: after each pipeline run, a summary
  table shows which questions were coded vs. skipped, closing the silent-skip gap.
- **Progress indicator** for k-selection loop: TQDM-based progress logging so users
  on CPU machines can see the clustering search is running.

### Bug Fixes
- Fixed pandas chained-assignment patterns throughout `analyze_survey.py` and
  `iterative_supervised_thematic.py` that would raise errors under pandas 3.x
  copy-on-write semantics. Results are now accumulated as lists and assigned once.
- Fixed silent label skip in `run_question_level_zero_shot`: missing labels for a
  question now raise a visible warning in both the CLI log and the Streamlit UI.

### Improvements
- `requirements.txt`: added tested upper bounds on fast-moving dependencies
  (`transformers`, `torch`, `sentence-transformers`) to prevent silent breakage
  on fresh installs.
- `.gitignore`, `LICENSE` (MIT), and `CHANGELOG.md` added for GitHub readiness.
- `data/synthetic_customer_experience_feedback.csv` now carries a header comment
  confirming it is synthetic, not real survey data.

## v1.0.0 — May 2026

Initial release. Phase 1 + Phase 2 complete:
- Core NLP pipeline (embedding, clustering, sentiment, zero-shot, strict coding).
- Streamlit GUI with drag-and-drop upload, question scope selector, iterative
  labeling lab, and results/download page.
- Iterative supervised workflow (sample → human code → train → unsupervised discovery).
- Analyst Cheat Sheet (MD / DOCX / PDF), packaging scripts, and user guide.
