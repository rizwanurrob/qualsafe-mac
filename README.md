# QualSafe

**Local-first, privacy-preserving, AI-assisted qualitative analysis for survey open-text and interview transcripts.**
*(Formerly the "Qualitative NLP Workbench"; renamed QualSafe in v3.9.0.)*

Bring the analytical rigor researchers rely on in tools like Dedoose — excerpts,
a human-owned codebook, descriptors for mixed-methods, co-occurrence, and
inter-rater reliability — together with automation (a transformer stack *or* a
local LLM) that does the first pass of coding for you. Everything runs on your
machine. No survey text ever leaves the device; the only possible network
activity is a one-time model download.

> **Positioning:** Dedoose's rigor + our NLP/LLM automation + nobody's cloud.
> Built for FERPA/IRB-sensitive institutional and social-science data.

---

## Why this exists

Automated pipelines ("text in, themes out") are useful but don't match how
qualitative researchers actually work — around a **codebook** of defined codes,
**excerpts** you can always trace back to, **descriptors** that let you ask
mixed-methods questions, and **reliability** measures you can publish. This tool
adopts that conceptual model while keeping automation and full on-device privacy.

## Key features

- **Two analysis modes.** *Survey mode* for many open-text responses; *interview
  mode* (v3.1) for one semi-structured transcript — both feed the same project
  store and analyses.
- **Two coding engines, one interface.**
  - *Transformer* (default): SentenceTransformer embeddings + KMeans theme
    discovery + zero-shot (BART-MNLI) coding + sentiment. Fast, deterministic,
    offline.
  - *Local LLM* (optional, via [Ollama](https://ollama.com)): a small
    instruction-tuned model codes each response with a short rationale. Auto-falls
    back to the transformer engine if Ollama isn't available.
- **Strict coding gate.** A confidence threshold + margin routes ambiguous
  responses to an `UNCERTAIN_REVIEW` queue — the same methodology for both engines.
- **Shared project store (`.qnw`).** Every run can save a single-file SQLite
  project: sources → excerpts → code applications → a hierarchical codebook →
  descriptors. Reopen or share it; it's portable and inspectable.
- **The analyses researchers run** (all with drill-back to the exact responses):
  code **frequency**, code **co-occurrence**, and **code × descriptor** cross-tabs
  (theme prevalence by subgroup, normalized for group size).
- **Human-vs-AI reliability.** Per-code Cohen's **kappa** between your human-coded
  sample and the model's coding — a publishable trust number, with percent
  agreement + prevalence shown alongside so rare-code paradoxes stay visible.
- **Codebook management.** Rename, define, reparent, and merge codes — the human
  owns the codebook; automation only proposes and applies.
- **Wide- and long-format ingestion**, manual question entry, descriptor designation.
- **Interview mode.** Ingest one transcript (`.txt`/`.docx`/`.pdf`), segment it into
  speaker turns, confirm speaker roles at a mandatory review checkpoint, map Q&A onto
  a template codebook, **regroup responses by theme regardless of where they occur**,
  and (optionally) get per-theme LLM summaries whose **quotes are verified verbatim
  against the transcript** (hallucinated quotes are dropped and counted).
- **Data Charts (Chart Builder).** Upload any CSV or Excel file and build a chart for a
  slide or report without code: single-choice, Likert matrix (with top/bottom-box
  summaries), select-all-that-apply (safe for answers that contain commas) and
  free-text questions; bar, stacked, pie/donut, heatmap, histogram, box, scatter, line
  and area charts; filters, relabel/combine/order, undo; the default theme
  plus custom themes; PNG/SVG/PDF export with the summary table; saved charts. Desktop
  and web share one engine (`core/chartbuilder/`). See
  [docs/CHART_BUILDER_GUIDE.md](docs/CHART_BUILDER_GUIDE.md).
- **Iterative human-in-the-loop labeling** with an in-app card interface.
- **Audit manifest on every run** (`run_manifest.json`): version, engine, model,
  thresholds, counts, timestamp, and what was exported.
- **Streamlit GUI** for analysts + a **CLI** for power users.

---

## Install

### Easiest: one-click installer

1. Install **Python 3.9 or newer** first if you don't have it
   (<https://www.python.org/downloads/> — on Windows, tick **"Add Python to PATH"**).
2. Then run the installer for your system (it creates a private environment and
   installs everything — several minutes on first run):
   - **Windows:** double-click **`install_windows.bat`**, then **`run_app_windows.bat`** to start.
   - **macOS / Linux:** in a Terminal in this folder, run `bash install_mac_linux.sh`,
     then `bash run_app_mac_linux.sh` to start.

The installer downloads the **CPU-only** build of PyTorch (smaller, no graphics card
required), so it runs on ordinary and older laptops.

### Manual (developers)

```bash
python -m venv .venv
# Windows:  .venv\Scripts\activate      macOS/Linux:  source .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-dev.txt      # to run the tests too

python tools/download_models.py          # Step 2: one-time model download
```

- **Optional (only for the local-LLM engine):** install [Ollama](https://ollama.com)
  and pull a small model, e.g. `ollama pull llama3.2:3b`. Without Ollama the tool
  works fully on the transformer engine.

### Model setup

Analysis runs with model-hub access **switched off**, so the models have to be
downloaded once, deliberately, before the first run:

```bash
python tools/download_models.py            # fetch (one-time, ~1.6 GB)
python tools/download_models.py --check    # report cache status, download nothing
```

The one-click installers do this as their step 5. In the app, the **Model status**
panel on the Run Analysis page shows what's cached and can fetch what's missing.

This split is the point: model *acquisition* is an explicit step that touches the
network, and model *use* — the part that sees your data — cannot. If a model is
missing, the tool says so and tells you how to fix it; it will not quietly reach
out mid-analysis. Run it again any time you change the embedding model.

Contributors who only want to run the tests can skip the ML stack entirely:

```bash
pip install -r requirements-light.txt && pytest tests/ -q   # no torch needed
```

## System requirements & compatibility

A **decade-old machine is fine**; a decade-old *software stack* is not. The
machine-learning libraries (PyTorch, Hugging Face Transformers) set the real floor.

| | Requirement | Notes |
|---|---|---|
| **Python** | **3.9–3.12** (3.11 / 3.12 recommended) | **3.13 and 3.14 are not yet supported** — NumPy 1.x and PyTorch have no installable packages for them, so pip falls back to a broken source build (you'll see *"Numpy built with MINGW-W64 … experimental"* and crashes). Use 3.12. 3.8 is best-effort via `requirements-compat.txt`; **below 3.8 cannot work**. |
| **CPU** | 64-bit with **AVX** (~2011+) | No GPU needed — the installer uses the CPU-only PyTorch build. Pre-2011 CPUs without AVX can't run PyTorch. |
| **RAM** | 8 GB recommended | 4 GB works for small datasets / small models. |
| **Disk** | ~3–4 GB free | For cached models (downloaded once). |
| **OS** | Windows 10/11, macOS 11+, modern Linux | An old *laptop* is fine if it runs a current OS. |
| **Internet** | Once, to download libraries + models | After that, analysis is fully offline. |

**If a library won't install on an older system**, use the looser set:
`pip install -r requirements-compat.txt` (best-effort, untested). What each floor
means if you must change it:

- **torch** — the binding constraint. If `torch>=2.2` won't install, try
  `torch>=1.13`; if that fails, the CPU is likely too old (no AVX) — there is no fix.
- **pandas / numpy** — compat set allows `pandas>=1.3` / `numpy>=1.19`; the code
  avoids pandas-3-only and pandas-2-only idioms, so 1.x is fine.
- **streamlit** — needs **≥ 1.29** (bordered result cards). On older Streamlit the
  UI may error; upgrade Streamlit rather than the analysis code.
- **sentence-transformers / transformers** — compat allows `>=2.2` / `>=4.20`; these
  still require Python 3.8+.
- **python-docx / pdfplumber** — only needed for interview mode; if you only use
  survey mode you can omit them.

## Quick start — GUI (recommended)

```bash
streamlit run streamlit_app.py
```

Then, in order:
1. **Data Setup** — confirm the FERPA/PII check, load a file, map columns
   (long or wide format), optionally designate descriptor columns.
2. **Theme Setup** — enter your theme labels; optionally enable strict coding.
3. **Run Analysis** — pick the engine (Transformer or Local LLM), keep "Also save
   a portable project file (.qnw)" on, and run.
4. **Analysis** — explore frequency / co-occurrence / code × descriptor / agreement,
   clicking any number to see the responses behind it.
5. **Codebook** — refine codes (rename / define / merge / reparent).
6. **Iterative Labeling Lab** — human-code a sample (used for the kappa in Analysis).

### Interview mode (one transcript)

Open **Interview Mode** in the sidebar — a guided wizard:
1. **Upload** the transcript (`.txt`/`.docx`/`.pdf`) behind the FERPA/IRB gate.
2. **Template** — paste or load your interview guide as YAML (each theme becomes a
   code); see `config/interview_template.example.yaml`.
3. **Review parsing (required)** — the tool proposes the speaker pattern and who is
   the interviewer vs. interviewee, with its reasoning; you confirm or correct it
   before anything runs. This checkpoint is mandatory.
4. **Run** — themes are matched by semantic similarity (with a confidence gate);
   optionally turn on local-LLM per-theme summaries.
5. **Results** — per-theme summaries with **verified verbatim quotes**, guide
   coverage, and off-template material. The run also saves a `.qnw`, so the
   **Analysis** and **Codebook** pages work on the interview too.

Only digital-text transcripts are supported (scanned/OCR PDFs are out of scope).

## Quick start — CLI

```bash
cp config/config.example.yaml config/my_project.yaml   # copy on Windows
# edit input.file_path, input.text_column, zero_shot.labels, and (optionally) the engine block
python analyze_survey.py --config config/my_project.yaml
```

Choose the engine in the config's `engine:` block (`type: transformer` or `llm`).

> **Note:** wide-format ingestion, interview mode, and the Analysis / Codebook / IRR
> features are currently GUI-first. The CLI runs the survey pipeline (either engine)
> from a long-format file and produces the CSVs, the manifest, and the optional `.qnw`.

---

## Outputs

Per run (in `output.output_dir`):

| File | Contents |
|---|---|
| `responses_scored.csv` | one row per response: cluster, sentiment, zero-shot/strict labels (+ LLM `zshot_rationale` on the LLM path) |
| `cluster_summary.csv` | per-cluster size, top terms, representative quotes |
| `run_report.md` | readable stakeholder summary |
| `run_manifest.json` | **audit trail** — version, engine, model, thresholds, counts, exports |
| `project.qnw` | portable SQLite project (when enabled) — the store the Analysis/Codebook pages read |
| `strict_review_queue_*.csv` | uncertain responses for human review (when strict coding is on) |
| `question_theme_summary.csv`, `question_label_summary.csv` | per-question analyses (when enabled) |
| `embeddings.npy` | optional |

## The models (and why)

| Role | Default model | Why |
|---|---|---|
| Embeddings | `sentence-transformers/all-MiniLM-L6-v2` | strong, fast on CPU |
| Sentiment | `distilbert-base-uncased-finetuned-sst-2-english` | light polarity baseline |
| Zero-shot themes | `facebook/bart-large-mnli` | flexible custom-label NLI |
| Local LLM (optional) | `llama3.2:3b` (Ollama) | nuanced coding + rationale, on-device |

All are configurable. The LLM model list is config-driven.

---

## Privacy, FERPA & IRB posture

- **Everything is local.** No survey/interview text is sent to any external
  service — the transformer stack and Ollama both run on-device. Streamlit usage
  stats and Hugging Face telemetry are both disabled.
- **Network access is off during analysis, not merely unused.** Since v3.1.1 the
  HF stack is pinned to the local model cache (`HF_HUB_OFFLINE`,
  `TRANSFORMERS_OFFLINE`) at every entry point. Model downloads happen only in the
  separate setup step (`tools/download_models.py`, or the Model status panel's
  button). Each run records `local_mode.offline_enforced` in its manifest, so this
  is verifiable rather than a promise. Ollama is exempt by design — it is a
  localhost service, and your text never leaves the machine to reach it.
- **A FERPA/PII confirmation gate** guards every ingestion path, per file (not per
  session), with an assistive PII scan shown before you confirm. The scan finds
  emails, phone numbers, SSNs, long numeric IDs, and suspicious columns — it is a
  prompt to review, **not** a clearance: it cannot see a name written into a
  sentence, and your judgment is what the gate records.
- **An audit manifest is written for every run** for the compliance trail,
  including the settings that change results (dedup, thresholds, engine, model).
- **Exploratory, human-reviewed, aggregate use only** — outputs are a first pass,
  not individual-level decisions about students, staff, or faculty.

## Project structure

```text
analyze_survey.py                 # survey pipeline (CLI entry)
iterative_supervised_thematic.py  # human-in-the-loop supervised workflow
streamlit_app.py                  # GUI shell: navigation + main() only
app/        one module per page (data setup, analysis, codebook, search, …)
            plus app/shared/ for the helpers pages have in common
interview_ui.py                   # Interview Mode wizard page
core/       model, project store (.qnw), migrations, populate, erasure,
            embedding_cache, sample_project, ingest, manifest, offline, theme
engines/    ThemeEngine + transformer & LLM engines, Ollama client, factory
analysis/   frequency, cooccurrence, crosstab, agreement (kappa), sampling,
            quality  — pure functions
exports/    bundle.py — store-backed, redacted-by-default shareable zip
privacy/    assistive PII scan + masking
interview/  parse, speakers, questions, template, matching, grouping, quotes, analyze, populate
prompts/    versioned LLM prompt templates
config/     example YAML configs (incl. interview_template.example.yaml)
tools/      download_models.py (the one-time model setup), packaging helpers
tests/      offline, mocked test suite (+ fixtures/ synthetic transcripts)
```

(The source repository additionally carries internal development documentation —
design notes and per-phase implementation logs — which is not included in the
end-user release package.)

## Testing

The suite is **offline and deterministic** — models and Ollama HTTP are mocked, so
no downloads, servers, or GPU are required. It also needs no torch: the heavy
imports are deferred to first model use, so the full suite runs on the light
dependency set in seconds.

```bash
pip install -r requirements-light.txt    # no torch — what CI runs on every push
pytest tests/ -q

pip install -r requirements-dev.txt      # full stack (weekly CI job)
pytest tests/ -q
```

## Status

**v3.9.0** — the tool is renamed **QualSafe** and the release package is trimmed
to end-user content. Feature history since v3.1's survey + interview modes:

- **v3.1.1** — enforced offline mode (network off during analysis; models are a
  separate setup step), pandas-3-proof CSV sanitization, a per-file PII gate with
  an assistive scan, session-input lifecycle cleanup, and a dark theme.
- **v3.2.0** — the `.qnw` project store is now the durable project of record:
  additive populate (no more wipe-per-run), human codes from the Labeling Lab
  enter the store, schema migrations, respondent erasure + project purge, and a
  shared embedding cache.
- **v3.3.0** — methodological rigor: uncertainty-ordered coding samples (with the
  bias caveats), training-row exclusion from kappa, cross-validated quality for
  tiny samples, per-engine strict thresholds, and multi-coder (human-vs-human)
  agreement.
- **v3.4.0** — sharing + onboarding: a store-backed, redacted-by-default export
  bundle; analytic memos (project / per-view / per-code); and a one-click guided
  sample project.
- **v3.5.0** — scale + method depth: LLM engine concurrency, a "possible outlier"
  review signal, versioned codebook snapshots, sentence-level units, guided Ollama
  installation, a quick 50-row preview run, and `pyproject.toml` packaging.
- **v3.6.0** — team coding distribution (partition/overlap + merge + coverage),
  wide-form respondent grouping and respondent-level co-occurrence, an
  uninstall/clean-reinstall flow, and a release packager.
- **v3.7.0–3.7.1** — UX pass: a start wizard (survey vs interview, with
  sample-data and demo-project on-ramps), mode-aware numbered navigation, guided
  "Continue" steps, a sidebar status panel, preferences that survive restarts,
  tooltips throughout, education presets by default, and better built-in samples.
- **v3.8.0–3.8.2** — live-project readiness: Labeling Lab autosave, one-click
  session resume, automatic project backups before destructive edits, codebook
  version history + JSON/YAML exchange, custom label packs, project-to-project
  merge for teams, and Word/Excel report export plus Qualtrics and optional SPSS
  ingestion.
- **v3.9.0** — rebrand to **QualSafe**; the release zip now ships only end-user
  content (app, installers, sample data, user docs, tests) without the internal
  development documentation.
- **v3.9.1** — portable projects: export a whole project as a `.zip` and import
  it on another installation, and **rebuild the working responses directly from a
  `.qnw`** so a colleague can label from the project file alone (no separate data
  file).
- **v3.9.6** — collaborative-coding rigor loop: **disagreement drill-down &
  adjudication** (resolve the items two coders coded differently into a
  gold-standard `human_adjudicated` set), **semantic merge suggestions** for
  near-duplicate codes, and a **codebook health** panel (dead / singleton /
  undefined codes).
- **v3.9.7** — **in-app Model Manager**: download and choose the local models for
  each role (embedding / sentiment / zero-shot) from inside the app — any model,
  not just the defaults — with downloads run in a subprocess so analysis stays
  offline. The standalone `download_models.py` step is no longer something you run
  by hand.
- **v3.9.8** — **light and dark skins** with a sidebar toggle (persists across
  restarts), and **high-contrast heatmaps** — the co-occurrence matrix now uses a
  blue→orange→light ramp whose low cells stay visible instead of fading to black.
- **v3.9.9** — **chart color choice and image export**: pick the heatmap color
  ramp, and export any Analysis chart as PNG / SVG (rendered offline), plus its
  Vega-Lite spec and underlying data.
- **v4.0.0** — **corpus search** (v4 Phases 0–1): schema v4 adds cases,
  span annotations, excerpt links, and a full-text index; a new **Search** page
  finds any phrase or pattern with keyword-in-context, word frequency and cloud,
  the words around a term, and one-click **auto-coding of every hit** (recorded
  under a non-human rater so it never affects reliability).
- **v4.1.0** — the GUI is split into **one module per page** under `app/` (the
  shell drops from 3,745 to 186 lines), with a strictly layered `app/shared/`.
  No behaviour change; it is what makes the remaining v4 corpus work possible.
- **v4.2.0** — a **document library and reader**: import a folder of transcripts
  or reports (behind a batch PII gate) and read them in the app with **coding
  stripes**, code/coder filters, and coverage; group documents into **cases**.
- **v4.3.0** — **manual span coding**: code a passage by picking sentences or
  paragraphs, or by pasting a passage that is located exactly in the document;
  in-vivo coding, overlapping codes, and rater-scoped uncoding.
- **v4.3.1** — **queries and the framework matrix**: boolean retrieval
  (`AND`/`OR`/`NOT`/`NEAR`, with the co-occurrence unit made explicit), matrix
  queries across codes, descriptors, and cases, and a **cases × themes framework
  matrix** whose cells the local LLM can draft with verbatim-verified quotes.
- **v4.4.0** — **reports**: a codebook report, a **methods & reliability
  appendix** (kappa with its caveats, coders, adjudications, provenance), and the
  framework matrix as Word/Excel — plus `tools/verify_install.py` and a release
  checklist rewritten for v4, for installing on colleagues' machines.

Interview mode is GUI-first; scanned/OCR PDFs are out of scope. **493 offline
tests** (torch-free light CI + weekly full-stack CI). See `CHANGELOG.md` for
detail and design rationale.

## License

MIT — see `LICENSE`.
