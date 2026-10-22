# QualSafe Desktop (Qt fork) — status and how to run it

A native PySide6 front end over the **unmodified** QualSafe engine. Forked from
`…/v2.1_extracted/qual_nlp_tool_v2` at v4.4.0 (`2ff7f29`), on branch
`qt-desktop`.

**Tiers 1, 2, and the pipeline path are complete**: the document reader with
manual span coding, the codebook, analysis, search, query & synthesis, and Data /
Themes / Run. The Labeling Lab, interview mode, and the Tier 4 supporting screens
are not started. See `QUALSAFE_QT_FORK_HANDOFF.md` §4 for the order.

---

## Run it

```bash
.venv/Scripts/python.exe -m qualsafe_qt.main
```

Fresh install:

```bash
python -m venv .venv && .venv/Scripts/python.exe -m pip install -r requirements-light.txt -r requirements-qt.txt
```

Tests (offline, deterministic, no torch, no models):

```bash
.venv/Scripts/python.exe -m pytest tests -q
```

---

## What works

Open or create a `.qnw`, import a folder of `.txt` / `.md` / `.docx` / `.pdf`
behind the PII gate, then read and code:

| | |
|---|---|
| **Drag** across text | select the passage to code |
| **1**–**9** | apply that code from the list |
| **Enter** | apply every code ticked in the list |
| **Ctrl+E** | grow the selection to whole sentences |
| **Ctrl+Z / Ctrl+Y** | undo / redo the coding |

Coded passages show as inline highlights and as coloured bars in the margin,
with overlapping codings in separate lanes. Clicking a bar jumps to its passage.

The **Codebook** tab is a real tree: drag a code onto another to nest it, or onto
empty space to promote it. Right-click to add, merge, or delete. It also carries
per-code memos, codebook health, semantic duplicate suggestions, version
tag/restore, and YAML export/import.

Merge and delete are **not** undoable with Ctrl+Z, on purpose: both move or
cascade *applications*, and a codebook snapshot restores codes, not the coding
that was reassigned. Each is confirmed with a dialog saying exactly what will
happen, and a restore backs up the project file first.

The **Analysis** tab has four views, each with drill-back — click a bar, a
heatmap cell, or a crosstab cell to read the passages behind the number:

* **Frequency** — how often each code was applied
* **Co-occurrence** — a code × code heatmap, per passage or per document
* **Code × Descriptor** — theme prevalence by subgroup, counts or % within group
* **Agreement (κ)** — per-code Cohen's κ between two human coders, with
  disagreement drill-down and adjudication

The **Search** tab searches the whole corpus (text or regex, whole-word or
substring, filtered by type / case / code), shows every hit in context grouped by
document, profiles the words around the term, and can code a whole result set
under a separate `auto_textsearch` coder. **Double-click any hit to open it in
the reader with the match selected** — `SearchHit` has always carried exact
offsets; this is the first front end with somewhere to send them. A second tab
gives word frequency across the corpus.

The **Query** tab is boolean retrieval (`AND` / `OR` / `NOT` / brackets /
`NEAR/n`) at the passage, document, or case unit — the unit is inline with the
query box because it changes the answer. Plus cross-tab matrices, a **framework
matrix** (cases × themes, each cell summarising what that case said), and case
management including bulk creation from a descriptor. Query results open in the
reader the same way search hits do.

Framework cells can be drafted by a local LLM. Every quote it offers is verified
verbatim against the source and anything altered is dropped and counted; the
draft is never saved until you save it.

The **Pipeline** tab is the survey path: load a CSV/Excel/JSON/SPSS file behind
the PII gate, map its columns (long or wide), pick the themes to code against,
choose the engine, and run. **The run happens on a worker thread with a live
progress bar**, so the window stays usable — you can read documents while it
codes. A quick preview caps the rows and never writes a project. When a full run
finishes, the `.qnw` it wrote is opened automatically, so its coding appears on
every other screen.

κ is shown beside percent agreement, prevalence, and an insufficient-N flag, and
no other coefficient is offered (invariant #5). Only raters whose id starts with
`human` are comparable (invariant #6). Resolving a disagreement writes a separate
`human_adjudicated` rater and never alters either coder's original codings.

## What is not built yet

Labeling Lab, Interview mode, Data Management, Model Manager, Results & Reports,
Help.

Human-vs-**model** κ is also absent: the Streamlit build computes it from the
pipeline's `responses_scored.csv` with training rows excluded, and no pipeline
runs here yet. Store-backed κ is human-vs-human only, which is the correct
comparison for document coding.

`services/tasks.py` exists and is used (the codebook's similarity check runs on
it), so wiring `run_pipeline` to a progress bar needs no new plumbing — the task
wrapper already hands out the `progress_callback(fraction, message)` shape the
pipeline expects.

---

## Architecture

```
qualsafe_qt/
  main.py                enforce_local_mode() FIRST, then QApplication
  text_offsets.py        source-offset <-> Qt-position mapping (pure, no Qt)
  colors.py, theme.py    the skin, generated from core/theme.py
  commands.py            QUndoCommand for coding and codebook edits
  pipeline_config.py     RunSettings -> run_pipeline config (pure, no Qt)
  services/
    project_service.py   owns the ONLY open Project; the only thing touching it
    tasks.py             QThreadPool wrapper for anything slow
  models/
    codebook_model.py    tree over Code.parent_id, with drag-to-reparent
    dataframe_model.py   one QAbstractTableModel for every analysis table
  widgets/
    document_view.py     selection -> offsets, highlights, margin stripes
    charts.py            bar chart + heatmap, painted from core/theme.py
  views/
    documents_view.py    corpus + reader + coding panel
    codebook_view.py     tree + code / health / duplicates / history
    analysis_view.py     frequency / co-occurrence / crosstab / agreement
    search_view.py       corpus search + KWIC + auto-code + word frequency
    query_view.py        boolean queries / matrices / framework matrix / cases
    pipeline_view.py     data + themes + running the pipeline on a worker
  windows/
    main_window.py       shell: tabs, menus, undo stack, status bar, preferences
```

**The engine is untouched.** No file under `core/`, `analysis/`, `engines/`,
`interview/`, `exports/`, or `privacy/` differs from upstream, and neither does
`analyze_survey.py`. Verify with:

```bash
git diff --stat 2ff7f29 -- core analysis engines interview exports privacy analyze_survey.py
```

### The one thing to know before changing the reader

A `QTextDocument` does **not** store the string you give it verbatim. Measured
on PySide6 6.11:

- `CRLF` → `LF` — **the length changes, so every later offset shifts**
- `CR`, `U+2028`, `U+2029` → `LF`, and `U+00A0` → space — 1:1, offsets unaffected

Both are ordinary in this corpus: `CRLF` from Windows `.txt` transcripts,
`U+00A0` from Word `.docx`. Assuming a 1:1 mapping silently codes the wrong
passage — and the excerpt still passes `verify_offsets()`, because the text is
re-read from the source at the (wrong) stored offsets. So every offset crossing
the widget boundary goes through `qualsafe_qt/text_offsets.OffsetMap`, which
verifies itself against what Qt actually produced and reports `is_exact = False`
when it cannot. `DocumentView.is_codeable` then disables coding for that
document rather than guessing.

`tests/test_qt_text_offsets.py` pins both the model and Qt's real behaviour, so
a future PySide6 that normalizes something new fails a test instead of corrupting
evidence.

---

## Invariants held

From the fork handoff §5, with where each is enforced:

1. **Offline first** — `enforce_local_mode()` is the first statement in
   `main.py`, above every other project import, and again in
   `qualsafe_qt/__init__.py`. The status bar shows the *actual* env state via
   `core.offline.is_offline_enforced()`, not an assumption.
2. **Model downloads in a subprocess** — `core/model_manager.py` untouched; this
   build never downloads anything.
3. **Redact at the source** — no export path added yet (the codebook YAML
   export carries names, definitions, and hierarchy only, never response text).
4. **Excerpt text comes from the source by offset** — `core.span_coding` does
   this; `DocumentView.selected_text()` deliberately reads the source string
   rather than `cursor.selectedText()`, so what the panel shows is what gets
   stored. Asserted in `test_qt_documents_view.py`.
5. **IRR kappa-only** — per-code binary Cohen's κ, always beside percent
   agreement, prevalence, and an insufficient-N flag. A test asserts no other
   coefficient appears, and that reordering the table for readability never
   drops a column.
6. **Machine coding never mistakable for human coding** — this app codes as
   `core.span_coding.HUMAN_RATER` (`kind="human"`); "Your codings" filters to
   that rater; only raters whose id starts with `human` can be compared for κ,
   and κ columns are labelled with the real coder ids rather than the engine's
   `human`/`model` parameter names. Asserted in `test_qt_documents_view.py` and
   `test_qt_analysis.py`.
7. **This fork never changes the `.qnw` schema** — it adds no tables and bumps
   no version; upstream owns the format, and a bump there arrives with a
   `core/migrations.py` entry. Asserted in `test_qt_streamlit_interop.py`, which
   checks that a Qt-written store carries the engine's own `SCHEMA_VERSION` and
   that every version has a migration, and also renders the *Streamlit*
   documents page against a Qt-written store.

   *(This read "stays schema v4" until upstream took it to v5 for `saved_charts`
   — correctly, with a migration and a test. A literal version number turned
   that into a red suite; the invariant was never about the number.)*
8. **Back up before destructive ops** — a codebook restore calls
   `core.backups.backup_store` first. Asserted in `test_qt_codebook.py`.
9. **Persistence is a whitelist** — `QSettings` writes only the five keys in
   `MainWindow._PERSISTED_KEYS`, all UI preferences.
10. **Windows first** — developed and tested on Windows 11.

---

## Tests

907 total, all passing: the 707 inherited from upstream (unchanged, still green)
plus 200 new Qt tests across ten files.

| file | covers |
|---|---|
| `test_qt_text_offsets.py` | the offset map, plus two tests pinning real Qt behaviour |
| `test_qt_documents_view.py` | coding end to end, undo, keyboard coding, the PII gate, stripe lanes |
| `test_qt_streamlit_interop.py` | schema version, engine round trip, the Streamlit page rendering a Qt-written store |
| `test_qt_app_smoke.py` | the shell starts; offline mode armed from a clean env; the settings whitelist |
| `test_qt_codebook.py` | the tree, drag-to-reparent, cycle refusal, merge/delete guarantees, health, restore-backs-up |
| `test_qt_tasks.py` | worker threading, exception capture, the discarded-task regression |
| `test_qt_analysis.py` | the four analysis views, drill-back, the κ invariants, adjudication, the DataFrame adapter |
| `test_qt_search.py` | search filters, whole-word vs substring, the jump to the reader, auto-code separation |
| `test_qt_query.py` | query units changing the answer, matrices, the framework matrix, draft verification, cases |
| `test_qt_pipeline.py` | the config contract key by key, the wide-form melt, the PII gate, running off the GUI thread |

The Qt tests `importorskip("PySide6")`, so the engine suite still runs
torch-free and Qt-free as upstream requires.
