# Release Verification Checklist

The automated suite (`pytest tests/ -q`, offline/mocked) covers the logic. This
covers what tests **can't**: real models, a live Ollama server, file-upload UI,
real documents, and other people's machines. Walk it before tagging a release or
handing the tool to a colleague.

**Rewritten for v4** (was last accurate at v3.1.1). The v4 surfaces — Documents,
manual span coding, Search, Query & Synthesis, the framework matrix, Reports —
have never been exercised by a human on a second machine; §5–§8 are where a first
real rollout will find trouble.

---

## 0. Environment

- [ ] Fresh venv: `pip install -r requirements.txt -r requirements-dev.txt` succeeds.
- [ ] `pytest tests/ -q` is green (should report 700+ passing).
- [ ] **Light path**: in a venv with `requirements-light.txt` only (no torch),
      `pytest tests/ -q` is still green. This is what CI runs on every push.
- [ ] `python tools/verify_install.py --check-models` reports **Ready**.
- [ ] `streamlit run streamlit_app.py` launches and **opens a browser tab by
      itself** (v3.9.0 made this automatic; if it doesn't, `headless` regressed).
- [ ] Every sidebar page opens without error, in **both** survey and interview mode.

## 1. Installing on someone else's machine (do this before distributing)

- [ ] On a machine with **no Python**, the README's step 1 → installer → launcher
      path works start to finish.
- [ ] On a machine with **Python 3.13 or 3.14 installed**, the installer refuses
      with the plain-language message and points at 3.12 — it does **not** attempt
      a MinGW NumPy build.
- [ ] With **both** 3.12 and a newer Python present, the installer silently picks 3.12.
- [ ] `tools/verify_install.py` on that machine reports the missing models before
      the first run, not during it.
- [ ] The Model Manager downloads the three defaults on a clean machine, and a run
      then works with the network disconnected.

## 2. Upgrading an existing project

- [ ] Open a **v3-era `.qnw`** (from v3.9.x) in this build: it opens, its codes and
      codings are intact, and it is stamped with the current schema version
      afterwards (v5 as of 0.99.0 — check `core.project.SCHEMA_VERSION` rather
      than trusting this line).
- [ ] That upgraded project is **searchable** — the FTS index was backfilled from
      text it already had.
- [ ] A `.qnw` written by this build **refuses to open** in an older QualSafe
      (expected: `SchemaTooNewError`, not a crash or silent corruption).
- [ ] Erase a respondent in an upgraded project; confirm the erased text is gone
      from **search results** as well as the tables.

## 3. Survey mode — transformer engine

- [ ] Data Setup: load a long-format CSV, map columns, designate descriptors.
- [ ] **PII gate**: the scan appears above the checkbox; column mapping stays
      blocked until confirmed; ticking it reveals mapping **on the first click**
      (the v3.9.0 deadlock).
- [ ] **Gate re-arms** when a second file is loaded.
- [ ] Wide-format file in wide mode (select the `Q*` columns).
- [ ] Theme Setup → Run Analysis completes; `output_streamlit/run_*/` contains
      `responses_scored.csv`, `run_report.md`, `run_manifest.json`, `project.qnw`.
- [ ] `run_manifest.json` records engine, model, thresholds, counts, and
      `local_mode.offline_enforced: true`.

## 4. Survey mode — local LLM engine (needs Ollama)

- [ ] `ollama pull llama3.2:3b`; Run Analysis reports it available.
- [ ] An LLM run completes and `responses_scored.csv` has `zshot_rationale`.
- [ ] With Ollama **stopped**, an LLM run falls back to the transformer engine with
      a logged warning rather than crashing.

## 5. Documents, reading, and hand coding (v4.2 / v4.3 — never human-tested)

- [ ] **Import a real folder** of `.docx` and `.pdf` transcripts. Files are read,
      scanned, and previewed, and **nothing is written until you attest**.
- [ ] Import the same folder again: already-present documents are **skipped**, not
      duplicated.
- [ ] A **scanned PDF** is reported as having no extractable text, not imported blank.
- [ ] A corrupt/unreadable file is reported per-file and does **not** abort the batch.
- [ ] **Read** tab: a long document pages correctly; coding stripes appear; code
      and coder filters work; coverage looks right.
- [ ] **Code** tab, pick-units: tick three consecutive sentences → they are stored
      as **one** passage. Verify the quote in the Read tab.
- [ ] **Code** tab, paste: copy a passage out of the Read tab, paste it, and confirm
      it is located; then paste something **not** in the document and confirm it is
      refused.
- [ ] Paste a passage with different quote marks/spacing — it still resolves, and
      the stored quote uses the **document's** characters.
- [ ] In-vivo coding creates a code named after the passage.
- [ ] Uncode one code from a passage; a colleague's coding on the same passage
      survives.

## 6. Search & queries (v4.0 / v4.3.1)

- [ ] Search finds a term with KWIC context; whole-word vs substring behave
      differently and both are correct.
- [ ] A regex with a syntax error gives a readable message, not a traceback.
- [ ] **Auto-code** a query's hits, then check the Agreement tab: the auto rater
      must **not** appear as a human coder, and κ must be unaffected.
- [ ] Undo the auto-coding; your own codings survive.
- [ ] Query & Synthesis: `A AND NOT B` and `A NEAR/200 B` return sensible passages;
      switching the unit (excerpt / source / case) changes the answer as expected.

## 7. Framework matrix & reports (v4.3.1 / v4.4 — never human-tested)

- [ ] Create cases in bulk from a descriptor; the counts look right.
- [ ] Framework grid renders; a cell's passages are the right ones.
- [ ] **Draft a cell with Ollama**: the summary is plausible, and any quote it
      invents is dropped with the warning shown.
- [ ] Edit and save a cell; reopen the project and the text is still there.
- [ ] **Reports**: build the codebook, methods appendix, and framework matrix.
      **Open all three in Word** and read them — formatting, tables, headings.
- [ ] The methods appendix states the caveats and contains **no verbatim response
      text**; the codebook without examples likewise.
- [ ] The framework `.xlsx` opens in Excel with both sheets and no response text.

## 7b. Data Charts (web page and desktop)

- [ ] Web: upload a real CSV and a real Excel workbook on the **Data Charts** page (the
      automated tests cannot drive the file uploader). Pick a sheet, choose a question,
      export PNG and the table.
- [ ] Web: **Open a chart file** and **Add a theme file** accept a file saved by the
      desktop app, and refuse a file that is not one, in words.
- [ ] The chart column stays in view while the controls scroll.

## 8. Recovery, sharing, teamwork

- [ ] **Autosave**: code cards in the Lab, kill the app, relaunch — codes survive.
- [ ] **Resume**: restart with data loaded; "Resume last session" restores file,
      mapping, and labels, and re-shows the PII gate.
- [ ] **Backups** appear before erasure/merge/codebook-restore, and restore works.
- [ ] **Project archive**: export a `.zip`, import it on a **second machine**, and
      confirm the analysis is intact. Then **Rebuild responses from active project**
      and code from the `.qnw` alone.
- [ ] **Store merge**: code a copy under a second coder, merge back; the rater is
      distinct and near-name codes are *suggested*, not merged.
- [ ] **Adjudication**: disagree on an item, resolve it, confirm `human_adjudicated`
      appears and neither coder's original coding changed.
- [ ] **Qualtrics CSV**: a real export loads with metadata rows stripped.

## 9. Privacy & release hygiene

- [ ] Watch the network during a run (firewall/monitor): **no outbound calls**.
- [ ] `.streamlit/config.toml`: `headless = false`, `runOnSave = false`,
      `gatherUsageStats = false`. (All have shipped wrong at least once.)
- [ ] Both skins render correctly, including the co-occurrence heatmap.
- [ ] `git status` clean; `.venv/`, `output*/`, `*.qnw`, caches all git-ignored.
- [ ] `python tools/build_release.py` produces a zip with **no** internal docs,
      `.venv`, caches, or `.qnw` files.
- [ ] Extract that zip somewhere fresh and install from it — the zip is what
      colleagues get, so it is what must be tested.
- [ ] Push to the remote; both CI jobs (`light`, and `full` via manual dispatch) pass.
- [ ] Tag the release (e.g. `git tag v4.4.0`).
