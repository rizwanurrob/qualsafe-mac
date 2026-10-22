# Changes that should be considered for the upstream (Streamlit) build

The fork's rule is that the source project at
`…/v2.1_extracted/qual_nlp_tool_v2` is never written to — it is in live research
use. Anything discovered here that also applies there gets recorded in this file
so it can be merged upstream deliberately rather than by accident.

Nothing in this list is required for the Qt fork to work.

**Status (2026-08-28): this backlog is closed.**

Every finding here has been applied upstream, superseded, or was informational
to begin with. The three copies this fork carried because it could not edit the
engine — the categorical palettes, the erasure VACUUM, and the whole pipeline
config — are gone; `qualsafe_qt/theme.py` and `qualsafe_qt/pipeline_config.py`
re-export from `core/`, and `data_view._erase_respondent` is a call into
`core.erasure`.

| § | Finding | Outcome |
|---|---|---|
| 1 | `requirements-light` missing `huggingface_hub` | applied upstream |
| 2 | Qt text normalization | informational; no upstream change wanted |
| 3 | Bugs in this fork's own code | fixed here when found |
| 4 | `coding_spans` cost at scale | recorded; not a problem yet |
| 5 | Co-occurrence mixed coders | applied upstream, plus a filter on frequency |
| 6 | Why store-backed human-vs-model κ is absent | informational; **read before touching the agreement screen** |
| 7 | Label packs stranded behind Streamlit | applied upstream (`core.label_packs.BUILTIN_PACKS`) |
| 8 | Six categorical colours | applied upstream (`core.theme.category_colors`) |
| 9 | Pure helpers stranded behind Streamlit | applied upstream (`core/run_config.py`) |
| 10 | `uninstall.py` walked build output | applied upstream |
| 11 | Erasure left readable bytes | applied upstream, in `core/` |

New findings still belong here. The rule that made this file worth keeping — the
source project is never written to by accident — has not changed; what changed
is that the accumulated list is now empty.

---

## 1. `requirements-light.txt` is missing `huggingface_hub`

**Severity:** low, but it breaks a fresh contributor's first `pytest`.

`tests/test_model_manager.py` imports `huggingface_hub` in two tests
(`test_remove_from_cache`, `test_remove_unknown_repo_frees_nothing`). The package
is not listed in `requirements-light.txt`, so the documented light-install path

```bash
pip install -r requirements-light.txt && pytest tests/
```

fails those two tests on a clean machine. It passes in the existing `.venv`
because `huggingface_hub` arrived there transitively with the full stack.

`core/model_manager.py` and `core/offline.py` both import it at call time, so it
is a genuine runtime dependency of the light path, not just a test dependency.

**Suggested fix upstream:** add `huggingface_hub>=0.20,<1.0` to
`requirements-light.txt`.

**Applied upstream (2026-08-28)** on `upstream-fixes`.

**Status in this fork:** installed into the fork's venv; the requirements file
is left untouched so the two trees stay diffable.

---

## 2. Qt's document normalization is a trap the *engine* is already exposed to

**Severity:** informational — no upstream bug, but worth knowing.

The Qt reader had to grow `qualsafe_qt/text_offsets.py` because a
`QTextDocument` does not store the string it is given verbatim: `CRLF` collapses
to `LF` (which **shifts every later character offset**), and `CR`, `U+2028`,
`U+2029`, and `U+00A0` are each substituted 1:1.

That is a Qt fact, so it needs no upstream change. What is worth carrying over
is the finding underneath it: **`U+00A0` and `CRLF` are both common in this
corpus** — the first from `.docx` files Word produced, the second from Windows
`.txt` transcripts. Any future upstream feature that maps offsets through a
component that normalizes text (a JS selection widget, a rich-text editor, a
diff view) will hit the same class of bug, and the failure is silent: the
excerpt still satisfies `verify_offsets()` because the text is re-read from the
source at the stored offsets — it is simply the *wrong* passage.

The mitigation pattern is in `qualsafe_qt/text_offsets.py`: model the
transformation, then **verify** the model by reconstructing the expected output
and comparing, and refuse to code when verification fails rather than guessing.

---

## 3. Bugs found in the fork's own new code (recorded, not upstream issues)

Neither exists upstream; both are noted because the second is the kind of thing
that recurs.

- **Code-list selection lost on every refresh.** The Qt code list restored its
  selection by matching the row's *label*, which carries a `"1. "` keyboard-
  shortcut prefix, against the raw code name. Applying one code then silently
  deselected it, so the next Apply did nothing. Fixed by keying on
  `Qt.ItemDataRole.UserRole` (the code name) instead of the display text.
  Regression test: `tests/test_qt_documents_view.py::
  test_the_chosen_code_stays_ticked_after_coding_a_passage`.

  The general lesson matches HANDOFF §7.6's Streamlit widget-key traps: **never
  round-trip identity through a display string.**

- **Undo of a duplicate application.** `apply_codes_to_span` is idempotent per
  rater, so re-coding a passage that already carries the code applies nothing.
  The undo command therefore has to record what it *actually* applied (by
  diffing before/after) rather than what it was asked to apply — otherwise
  undoing the no-op deletes the original coding.

---

## 4. `core.documents.coding_spans` is the coding loop's bottleneck (optimization, not a bug)

**Severity:** none today; relevant if a document accumulates hundreds of codings.

Measured in the Qt reader (6 documents, applying one code with a keypress,
median of 10, Windows 11 / Python 3.12):

| project state | per coding action |
|---|---|
| 6 × 8k chars, 20 codings | 25 ms |
| 6 × 39k chars, 60 codings | 39 ms |
| 6 × 117k chars, 150 codings | 87 ms |
| 6 × 234k chars, 300 codings | 129 ms |

Reading is unaffected and fast throughout: opening a 234k-char / 41k-word
document takes 47 ms, scroll repaints 0.2 ms, selections 0.7 ms.

The cost is two `core.documents.coding_spans()` calls per refresh (~23 ms each
at 300 codings) — one unfiltered for the reader's highlights, one filtered to
the human rater for the analyst's own list. They cannot be collapsed into one in
the view: the unfiltered spans carry *every* code on an excerpt, so filtering
them by "the human touched this passage" would list a model's code as the
analyst's own and break invariant #6. The distinction is that `coding_spans`
filters **codings**, not just passages.

**If this ever needs fixing**, the shape is a single core function that returns
both views from one `coding_table()` pass — e.g. `coding_spans_by_rater(project,
source_id)` returning `{rater_id: spans}` plus the union. That belongs in
`core/documents.py` so both front ends get it, which is why it is recorded here
rather than worked around in the Qt view.

The Streamlit build does not hit this: it pages the reader at 6,000 characters
and re-renders on every interaction anyway, so the per-coding cost is lost in
the rerun.

---

## 5. Co-occurrence silently mixes coders

**Severity:** methodological — the number is not wrong arithmetically, but it
answers a question nobody asked.

`app/analysis_page._render_cooc_tab` builds the matrix from the whole
`Project.coding_table()`, which is every rater's applications together. In a
project where the pipeline auto-coded and an analyst then hand-coded — the
normal shape once the Labeling Lab or span coding has been used — a passage the
analyst marked *Financial concerns* and the model marked *Advising* counts as an
"A co-occurs with B" event that neither of them asserted.

Two consequences:

1. **The finding is not attributable.** "These themes travel together" reads as
   an analytic claim, but half the pairings can be human↔machine artifacts.
2. **It is unstable for the wrong reason.** Re-run the pipeline with a different
   model and the matrix moves, though no human changed their mind. A co-occurrence
   result should not be a function of the model version.

This was not visible when the feature was written: in v3 survey mode the store
was populated by one pipeline run, so `coding_table()` was homogeneous and the
matrix meant "the model found these together". The mixing appeared as human
coding entered the same store.

**What the Qt build does** (`qualsafe_qt/views/analysis_view.AnalysisView.
_refresh_cooccurrence`): keeps "all coders" as the default so the number matches
the Streamlit build — a project must not read differently in the two front ends
— but adds a **coder filter**, and when more than one rater has contributed it
states the mixing in an amber banner instead of leaving it silent. Same pattern
the project already uses for kappa caveats and insufficient-N flags: the caveat
travels with the number.

**Suggested fix upstream:** the same, in `app/analysis_page._render_cooc_tab` —
a `st.selectbox` over `coding["rater_id"].unique()` and a `st.warning` when the
selection is "all" and more than one rater contributed. No engine change is
needed; `coding_table()` already carries `rater_id`, so the filter is one
DataFrame mask before `cooccurrence_matrix`.

**Applied upstream (2026-08-28)** on `upstream-fixes`, as a shared
`_rater_filtered()` helper so frequency gets the same picker. Frequency passes
`pooled_is_misleading=False`: it keeps the choice and drops the banner, because
a count of applications is honest about being a count of applications.

Frequency and code×descriptor have the same property and are *less* misleading
(a count of applications per code is honest about being a count of
applications), but a rater filter there would be cheap and consistent.

---

## 6. Why store-backed human-vs-model kappa is *correctly* absent

**Severity:** none — this records a design reason that is currently implicit,
so a future session does not "helpfully" add the missing feature.

The Qt Agreement screen compares two **human** raters only. It would be easy to
also offer `human_primary` vs `transformer`, since both raters are sitting in
the same store, and doing so would be wrong.

The reason is `in_training_sample`. `iterative_supervised_thematic.py` writes
that flag into `responses_scored.csv`, and `app/analysis_page._render_agreement_tab`
excludes those rows before computing κ, because the model was *fitted* on them —
its predictions there are not held out, and including them overstates
performance. **The store carries no equivalent.** A `CodeApplication` records
`rater_id` and `run_id`, not whether that item trained the model. So a κ computed
from store codings would quietly fold the model's own training items into its
score.

That is why invariant #6's "the agreement UI lists only raters whose id starts
with `human`" is a methodological rule and not merely a UI convention, and why
human-vs-model κ lives on the pipeline-artifact path.

The Qt build now says this in the UI when a project contains machine coding,
rather than leaving the omission to look like an oversight. If human-vs-model κ
is ever wanted from the store, the prerequisite is a provenance flag on
`CodeApplication` recording held-out status — which is the same missing
provenance field HANDOFF §10.3 already identifies for cross-question coding.

---

## 7. `make_suggested_labels` is content sitting in the Streamlit layer

**Severity:** low — a duplication the fork had to make, not a bug.

`app/shared/data.make_suggested_labels()` is a pure function returning the five
starter label packs (Education, Customer Experience, Employee Feedback,
Healthcare, Course Feedback). It takes no arguments, touches no session state,
and returns a literal — but it lives in `app/shared/data.py`, which imports
Streamlit at module scope. Importing it from the Qt app would pull Streamlit into
a process that must not depend on it, so the packs are duplicated in
`qualsafe_qt/pipeline_config.SUGGESTED_LABEL_PACKS`.

Two copies of the same content will drift. `core/label_packs.py` already exists
and already owns the *custom* packs an analyst saves, so the built-ins belong
beside them.

**Suggested fix upstream:** move the dict into `core/label_packs.py` as
`BUILTIN_PACKS`, have `make_suggested_labels()` return it, and delete the copy in
`qualsafe_qt/pipeline_config.py`. Nothing else changes.

The same argument applies more weakly to `estimate_runtime_minutes`,
`parse_labels_from_text`, and `resolve_long_dataframe` — all reshaping or
formatting logic with no UI in them, all currently unreachable from anything but
Streamlit, and `resolve_long_dataframe` in particular is the code that mints the
per-answer `response_id`. That one is load-bearing enough (HANDOFF §7.1) that
having two implementations is a real risk; the Qt copy is in
`qualsafe_qt/pipeline_config.resolve_long_dataframe` and is tested, but the right
end state is one implementation in `core/`.

---

## 8. Six categorical colours is not enough for a codebook

**Severity:** moderate, and it affects both front ends.

`core/theme.py` ships six `category` colours. That is right for a chart legend
and wrong for a codebook: with twelve codes the seventh wraps to the first, and
in the Qt reader's **margin stripes** — where colour is the only identifier —
two different codes become literally indistinguishable. Real codebooks run to
twenty or forty codes. The Streamlit reader has the same wrap in
`app/documents_page._code_colors`; it is less acute there only because that
reader shows inline highlights with a tooltip rather than bare bars.

**What the Qt build does:** `qualsafe_qt/theme.category_colors` keeps the
upstream six **first, unchanged** — so a small project looks identical in both
front ends — and appends ten more per skin. It also offers Okabe-Ito (the
standard palette designed for colour-vision deficiency) and a high-contrast set
as alternatives.

**Suggested fix upstream:** extend `DARK["category"]` and `LIGHT["category"]`
past six, appending rather than reordering so existing projects keep their
colours. A colour-blind-safe option is worth having in a tool used for published
research; red and green sit adjacent in the current list.

**Applied upstream (2026-08-28)** on `upstream-fixes`, as
`core.theme.category_colors(mode, palette)` with this fork's exact extra hues,
Okabe-Ito and high-contrast sets. Picker in the sidebar, persisted via
`app_settings`. One trap found while doing it: the Altair theme has to register
under a **per-palette** name as well as a per-mode one — Altair caches a
registered theme by name, so a single name would enable whichever palette was
chosen first and silently ignore every later change.

---

## 9. Pure helpers stranded behind Streamlit imports (a recurring shape)

Recorded once as a pattern rather than per-item, because it keeps recurring.

`app/shared/` holds several functions that touch no UI at all but cannot be
imported without pulling Streamlit into the process:

| function | what it is |
|---|---|
| `data.make_suggested_labels` | five literal label packs |
| `data.resolve_long_dataframe` | the wide→long melt that mints `response_id` |
| `data.build_general_config` | the whole `run_pipeline` config |
| `data.estimate_runtime_minutes` | arithmetic |
| `data.parse_labels_from_text` | string splitting |
| `io.load_file_from_path` | a `read_csv` / `read_excel` switch |

Each had to be reimplemented in `qualsafe_qt/pipeline_config.py`. Most are
harmless duplication; **`resolve_long_dataframe` is not**, because it is the code
behind this project's worst shipped bug (HANDOFF §7.1) and now has two
implementations that must agree.

`build_general_config` is the sharpest case for a different reason: reading
`st.session_state` directly makes it **untestable**, so the config dict that
governs every analysis has no test anywhere upstream. The Qt version takes an
explicit dataclass and is pinned key by key in
`tests/test_qt_pipeline_config.py`.

**Suggested fix upstream:** move the reshaping and config construction into
`core/`, taking explicit arguments, and leave `app/shared/data.py` as a thin
adapter that reads session state and calls them. That is testable, and it
collapses the duplication.

---

## 10. `tools/uninstall.py` walks build output when planning cache deletion

**Affects both builds. One line to fix. Found while packaging the desktop app.**

`plan_targets()` collects `__pycache__` directories by walking the project tree,
excluding `.venv`. It does not exclude `build/`. Once anything creates a build
tree containing an installed Python — which the desktop installer's payload
does, at `build/payload/python/Lib/site-packages/` — the planner offers
hundreds of bytecode directories inside third-party packages for deletion.

Two consequences, in increasing order of importance:

1. **The suite goes red on a machine that has built a payload.** Two assertions
   in `tests/test_uninstall.py` use `"huggingface" in path` as a proxy for "the
   model cache", so `site-packages/huggingface_hub/__pycache__` trips them:

   ```
   FAILED tests/test_uninstall.py::TestScopePlanning::test_caches_scope_excludes_venv_and_models
   FAILED tests/test_uninstall.py::TestScopePlanning::test_env_scope_includes_venv_not_models
   ```

   Neither failure indicates anything wrong with `uninstall.py`'s real job. The
   test is asserting "do not offer to delete the model cache" and catching a
   package that merely shares the name.

2. **The scope is wider than the user is told.** "Clear caches" reads as *my*
   caches. Reaching into a build directory and deleting bytecode belonging to a
   packaged application is outside what that phrase promises. It is recoverable
   — bytecode regenerates — but the same walk would behave the same way against
   any vendored or bundled Python that appears in the tree later.

**Suggested fix upstream:** add `build` and `dist` to the same exclusion set
that already holds `.venv`. If the test's intent is worth tightening while
there, matching the *model cache path* rather than the substring `huggingface`
would stop it firing on a package name.

**Applied upstream (2026-08-28)** on `upstream-fixes`, both halves: a
`FOREIGN_TREES` tuple replaces the single `.venv` check, and the three scope
tests now compare against `~/.cache/huggingface` as a path prefix. A new
`TestForeignTrees` builds a payload-shaped `build/` tree and asserts nothing
inside it is ever planned for deletion.

**Worked around in the fork, not fixed:** `packaging/build_payload.py` strips
every `__pycache__` from the finished payload as its last step. That was worth
doing on its own merits — 18 MB of bytecode compiled by the build machine that
the user's machine regenerates anyway, and no chance of shipping stale `.pyc`
from a mismatched interpreter — and it happens to keep a built tree from
turning the suite red. `tools/uninstall.py` is inherited and was not modified.

---

## 11. Erased responses stay readable in the `.qnw` until the store is rebuilt

**Affects both builds. Two lines to fix. The most consequential finding in this
file.**

`core/erasure.erase_respondent()` deletes the respondent's rows correctly — they
are gone from every query, foreign keys cascade, the CSVs are rewritten, the
report is scrubbed, the caches are dropped, the audit event is appended. All of
that works.

But **SQLite does not overwrite a deleted row**. It marks the page free and
reuses it later, if ever. So the erased response remains legible in the file's
bytes, and `strings project.qnw` prints it back.

Measured on a two-response store, erasing `r1`:

| | |
|---|---|
| Row queryable after erase | no — correctly gone |
| Text present in the file's raw bytes | **yes** |
| Text present after `VACUUM` | no |

This matters more than the usual "deleted is not shredded" caveat, and it is a
different problem. That caveat is about disk forensics after a file is unlinked.
This is about the **live project file that the researcher goes on using, copies
to a colleague, and attaches to an archive** still containing the text of a
participant who withdrew consent. Anyone who opens it in a hex editor — or runs
any tool that reads free pages — recovers it.

For a feature whose whole purpose is acting on a withdrawal-of-consent request,
the gap between "erased" and "no longer indexed" is the gap between the claim
and the fact.

**Suggested fix upstream:** run `VACUUM` at the end of `erase_respondent`, after
the deletes and before the audit append, and record it in the returned report so
a caller can tell whether it succeeded. It is not free — VACUUM rewrites the
database — but erasure is rare and correctness dominates here.

Worth pairing with the existing note in that module about the pre-erase backup:
the backup also holds the un-erased data, so a genuine erasure must purge
`project_backups/` as well. The module defers that to "the UI", and the
Streamlit Data Management page does not currently do it either.

**Done in the fork:** `qualsafe_qt/views/data_view._erase_respondent()` runs the
VACUUM and purges the backups in one step, with the purge offered in the same
confirmation dialog rather than left as a follow-up nobody performs.
`tests/test_qt_data.py` pins it by reading the file as **bytes** — querying the
store passed the whole time and proved nothing.

**Applied upstream (2026-08-28)** on `upstream-fixes`, and in `core/` rather
than in a view — which is where it belonged all along, so both front ends and
any future caller inherit it. `erase_respondent()` now VACUUMs unconditionally
(reporting `vacuumed`, never raising), takes `purge_backups=` defaulting to
`False`, and always returns `backups_retaining_data` so no UI can omit the step
silently. `tests/test_erasure_remnants.py` asserts on bytes throughout.

**Follow-up for this fork:** once that lands, `data_view._erase_respondent()`
should shrink to a call into `core.erasure` with `purge_backups=` — the fork's
copy is a workaround for an engine it could not edit, and keeping two
implementations of an erasure guarantee is exactly the shape §9 warns about.
