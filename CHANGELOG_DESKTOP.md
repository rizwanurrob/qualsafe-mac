# Changelog — QualSafe Desktop

The desktop application. Versioned separately from the analysis engine it runs
on, because the two are different artefacts with different release cadences;
`CHANGELOG.md` covers the engine and the other program built on it.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versions follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

* **The analysis engine installs from inside the program (test builds 0.99.11-ux4 and later).** Models,
  **Install the analysis engine**: downloads PyTorch (the processor-only build), transformers and
  sentence-transformers once, about 1 GB, into a folder of your own outside the program (Windows
  `%LOCALAPPDATA%\QualSafe\engine`, Mac `~/Library/Application Support/QualSafe/engine`), so nothing inside
  the program changes (a signed Mac app cannot be written into) and an update keeps it. It confirms first,
  shows pip's progress, and carries on from where it stopped if interrupted. It is the second time the
  program uses the internet (the first is a model download); help and settings now say so. Uninstalling
  leaves the engine and the models in place.
* **The Codebook's coding rules** (*Use this code when*, *Leave it out when*, *Examples*) are one click
  away under *Coding rules*, keeping the screen to seven controls.
* **Saturation counts sources in the order they were added.** The saturation views (desktop and web) listed
  sources by their random ids, so the order the curve used, and described as the order of ingestion, was
  arbitrary and changed from project to project. They now use insertion order.
* **A fresh install no longer opens to someone else's saved place.** The desktop build's own start-up
  check wrote a `progress.json` into the program folder, which earlier test installers (ux1 to ux4)
  shipped, so Home showed a 'Continue' for a Surveys step nobody had visited. The check now uses a
  throwaway folder and fails the build if it leaves a file behind.

* **Deviant cases and Saturation on the Analysis screen.** Two new tabs that only
  the browser version had. *Deviant cases*: pick a code and the program lists the
  passages furthest from how you used it, as a reading order to re-read. It never
  calls a passage deviant and saves nothing; click one to read it, double-click to
  open it in the reader. A code with fewer than eight passages is refused. It reads
  on a background task, so the window stays responsive. *Saturation*: new codes
  against sources coded, people's coding only by default, with the cautions printed
  above the curve, the sentence a methods section would use, and no "saturated"
  verdict (code saturation only). Help and the beginner guide now point to both.
  The engine and the project file are unchanged.
* **A beginner's guide to qualitative research.** Help has fourteen new sections
  (*New to this · …*) after "What this is": the whole path in nine steps, codes
  versus categories versus themes, a quick outline of five approaches, a first pass
  at coding, memos and a research diary, the codebook, coding with a partner,
  using the computer's suggestions, checking your work, counting, writing up, the
  three source books with short author notes, a glossary that sets QualSafe's words
  beside the books', and one-line hints. Every section cites Saldaña (2013),
  Creswell (2013) or Silverman (2017) by page or chapter. The web Help page shows
  the same text. See `docs/BOOK_ALIGNMENT_AUDIT.md`.
* **Coding rules on a code.** Codebook → Code has *Use this code when*, *Leave it
  out when* and *Examples*. The engine already stored them; only the browser
  version could edit them. Changes are written to the project history (the example
  text is not).
* **A research diary.** Codebook → Diary keeps notes about the whole project, with
  eleven prompts (your position, your question, a problem, an ethical worry, what
  to do next…). Notes about one code stay on the Code tab, and the memo box now
  says what to write about. The audit trail includes diary text only if you tick the
  box, as it does for other memos.
* **Help wording.** The agreement section now gives the textbook benchmarks (80-90%,
  no agreed standard) and says agreement shows consistency, not correctness. The
  Analysis help warns that a count is a pointer to where to read, not a finding.

* **Help, tips, tours, speakers, interview guide and short clips (test build 0.99.11-ux2).** A short
  article for every step with a *Help for this step* button; eight "How do I...?" articles, a
  glossary and researcher troubleshooting; a small (i) beside less obvious choices; a once-only
  tour of each activity, retaken from Help. Interviews: QualSafe proposes who the interviewer is
  and you confirm it (their words show in italics), and an interview guide can suggest codes you
  read and remove. Seven short explainer clips (paused until you press Play) in Help and behind
  a *Watch* link on the steps that have them. A pre-release for testing, not a release.

* **Code with a written codebook, on the desktop (a preview).** Surveys, step 3: write
  each code with a rule for what counts, install the local coding engine (Laya, a
  separate download of about 0.85 GB, done once and then fully offline; it uses the app's own libraries and adds only a small package), run it, and
  review what it was unsure about. It works as the web page does and shares its code.
  First run on a real install: the engine, its model download and its question wording
  were all corrected (see `docs/ALT_SURVEY_FLOW_PLAN.md`). Still a preview: scores are
  model scores, not probabilities, and nothing yet shows how often it agrees with a
  person.

* **Compare yourself with the analysis engine.** Analysis → Agreement has a new
  choice, *Survey responses: coder vs engine*: a coder against one analysis run,
  the same figure the Word report, Excel workbook and methods appendix already
  print. It says what that κ covers (the responses you coded) and checks whether
  you coded the hard cases, as a review queue does; if so, κ understates
  agreement across the run. Disagreements with the engine can be read but not
  reconciled. The old note, which said the engine couldn't be compared because
  it was trained on some of what it coded, was wrong: nothing that writes to
  the project is trained on your coding.

## [0.99.10] — September 2026: the audit trail

Runs on analysis engine **4.13.0**; projects are **format v9** (older projects
open and are upgraded on open; a v9 project does not open in 0.99.9).

* **Prevalence with 95% intervals.** On the Analysis screen, Code × Descriptor
  has a new view, *% with 95% intervals*: each group's share with a
  Wilson interval, one coder or all, and small groups flagged. Pick two groups
  (or two survey waves) to compare them, with an interval for the difference,
  in one sentence you can quote.
* **A dated record of every analytic decision.** Creating, renaming,
  redefining (old and new definition), moving, merging and deleting codes;
  memos; reconciliation; imports; merges; auto-coding; erasure. Each carries
  the analyst name (Edit → Set your analyst name…). It never holds response text. Memos now
  have dates. History from before this version is not reconstructed.
* **Audit trail report** (Word and Excel) on the Results screen: that record
  plus everything already dated — analysis runs, codebook snapshots, coding
  sessions, backups, erasures — oldest first. No response text, response ids or
  document titles; memo text only if you tick the box.

## [0.99.9] — September 2026: agreement you can defend

Runs on analysis engine **4.12.0**; projects are **format v8** (older projects
open and are upgraded on open; a v8 project does not open in 0.99.8).

* **Agreement counts "no code applies".** A response a coder read and left
  uncoded used to vanish from the comparison, taking the disagreements with it,
  so agreement read higher than it was. It is now recorded. Coding done before
  this version is marked, under the table, as *likely overstated*.
* **Two coders' highlights can be compared.** On the Analysis screen, choose
  *Document sentences* or *Document paragraphs*, pick the two coders (yours, and
  a colleague's imported from NVivo, MAXQDA or ATLAS.ti), and tick the documents
  both have finished. In the reader, **I've finished coding this document**
  records your own.
* **Every report compares the same two coders.** The Word report, Excel workbook,
  shareable bundle and methods appendix choose by role, not by name: they no
  longer compare against the reconciled set after an adjudication, and they find
  the analysis engine on real projects (they only found it on the sample
  project before). A code seen fewer than five times gets no κ, in every file.
* **The reconciled set is still there to check yourself against**, listed last,
  and now says it is a check against the resolution, not a reliability figure.
* **The privacy check finds more.** Names after a title or a relationship ("my
  advisor …"), street addresses and room numbers inside answers, with the
  sentence left readable ("My advisor [NAME] has been great."). It also says
  what it cannot find.
* **Importing a colleague's coding keeps their ids exact**, so `000123` is no
  longer read as `123`, and a file saved from Excel imports.

## [0.99.8] — September 2026: Data Charts

A new **Data Charts** tab charts any CSV or Excel file for a slide or a report. It is
not tied to a project: open a file, choose a question, and the chart redraws as you
change things. The file is never changed.

* **Four kinds of question.** A single choice; a Likert matrix with top and bottom
  boxes written like `70% (7/10)`; select-all-that-apply, where an answer that
  contains a comma stays one answer; and free text.
* **Every chart.** Bar, grouped, stacked, 100% stacked, pie, donut, heatmap, histogram,
  box, scatter, line and area. A column of numbers starts as a histogram and a column of
  dates as a line, and a pie is never suggested just because a field is categorical.
* **Cleaning you can see.** Blanks (empty cells, `NULL`, `NA`, `None` and the like) never
  enter a percentage's base unless you say so, and answers that differ only by spacing or
  capitals are shown, never merged.
* **Make it yours.** Leave categories out, relabel, combine, reorder, filter, and undo any
  of it. Four sizes, the default theme by default, your own themes, and a colour
  for any single category.
* **Get it out.** PNG (96 to 600 DPI), SVG or PDF, white or transparent; **Copy picture**
  for PowerPoint; the numbers behind every chart as CSV or Excel.
* **Save a chart** and open it on the same kind of file later. Charts and themes are kept in
  `%APPDATA%\QualSafe\chartbuilder` and survive an uninstall. A saved chart holds your
  choices and category labels, never rows of your data.

The installer is about 19 MB larger (123 MB, up from 104 MB) because the charts are drawn
with `vl-convert`, which is now included, and old `.xls` files are read with `xlrd`.

Engine v4.11.0.

## [0.99.7] — August 2026: a shared project file stops carrying your folders

Project format v5 → v6; projects you already have are updated when you open them.

A `.qnw` is offered as a file you can share, and every document you imported
recorded the full path it came from — which meant your Windows username, your
institution's OneDrive, and whatever your folders are called travelled with it.
Now only the file's name is kept, and opening an older project strips the rest
and rebuilds the file so the old text is not left in it.

The document's title still comes from the filename, so a filename with a
participant's name in it is still visible in the project. That one is yours to
decide about; the program will not rename your documents behind your back.

Engine v4.11.0.

## [0.99.6] — August 2026: the first run explains itself

The language models are downloaded once, from the Models tab, and are not in the
installer. If you press Run before doing that, the program used to get part way
— through embeddings and cluster discovery — and then stop with an error naming
one missing model. Fixing that one and running again got you further, and
stopped again. Three attempts, each after more waiting.

Now the Survey screen lists it with the other things standing between you and a
run, before you press anything, and names every model that is missing at once.
If a run does start without them it stops immediately, having written nothing.

The advice is also the right advice for this build. It used to tell you to run a
Python command and open a page called "Run Analysis" — neither of which exists
here. It now says to open the Models tab.

Engine v4.10.0.

## [0.99.5] — August 2026: re-running is nearly free

A run now remembers what it coded. Repeating a run over the same responses
serves everything from a per-response cache without loading the models at all;
adding a label to the codebook costs that label rather than the whole codebook;
and a run interrupted by a sleeping laptop keeps everything it had finished.

Measured on 45 responses with six labels, each run started fresh: 106.9 s cold,
**4.4 s warm** with no model loaded at all, and 41.4 s to add a seventh label —
with results identical to a cache-off control.

The cache lives in the run's output folder and is deleted by the erasure tool
along with the rest of the derived data.

Engine v4.9.0.

## [0.99.4] — August 2026: an honest runtime estimate

The setup screen's "rough estimate" was optimistic by roughly twelve times on a
six-label run: it charged a flat cost per response for zero-shot, when the real
cost is per response **per label**. At 5,000 responses it said "about 9–26
minutes" for a run of over two hours.

It now uses measured constants, reads the label count out of the labels box,
counts model-loading time, and quotes long runs in hours rather than in three
digits of minutes. The GPU figure says on screen that it is an assumption rather
than a measurement, because no GPU was available to measure.

Engine v4.8.2.

## [0.99.3] — August 2026: Excel's CSVs open

### Fixed

- **A CSV exported from Excel on Windows no longer fails to open.** It is
  cp1252 unless the user picked "CSV UTF-8", and a curly apostrophe raised
  `UnicodeDecodeError`. Engine 4.8.1 carries the fallback; this build also
  **shows the note**, which it previously did not — the web app warned about a
  fallback and the desktop app stayed quiet, on the build most likely to be
  installed.

## [0.99.2] — August 2026: the model leaves the screen

### Added

- **Export report…** on the Modelling screen. Writes the Word report — the
  table with its specification and its caveats, ready for a chapter — and puts
  the design matrix beside it as CSV for anyone who wants R or Stata. Both from
  one action, because an analyst who wants one usually finds a week later that
  they wanted the other.

- The engine underneath is **4.8.0**; see `CHANGELOG.md`.

### Fixed

- **A refused model can no longer be exported.** The button is disabled when the
  program has declined to fit, because a document that looks like a report and
  contains nothing still gets circulated — and a refusal on screen does not
  travel with it.

## [0.99.1] — August 2026: the Modelling screen

### Added

- **A Modelling screen.** Shelves for a statistical model, the way the Charts
  screen is shelves for a figure — Outcome, Treatment, Predictors, Controls,
  with the chart builder's field palette dragged onto real drop targets. Lasso,
  ridge, elastic net, random forest, gradient boosting, an SGD-fitted linear
  model, and **double lasso** for an effect estimate on one named variable.

  Called *Modelling*, not *Models*: the Models tab is the model **manager**,
  which downloads language models. Two tabs with the same name meaning different
  things is a support ticket waiting to happen.

  The Treatment shelf is enabled only for a method that estimates an effect, so
  a predictive method cannot silently accept one and leave the analyst believing
  they asked for a number they did not get. Problems appear above the button and
  blocking ones disable it. The caveats are not collapsible.

  Fits run on a worker thread: a boosting run on a few hundred cases is fast but
  not instant, and a frozen window is the kind of thing that only shows up when
  somebody actually uses the program.

- The engine underneath is **4.7.0**; see `CHANGELOG.md` for what it does and
  what it refuses to do.

- The two items below shipped in this build too; they had been sitting
  under *Unreleased* since the 0.99.0 tag.

- **The About box now names the project format, not just the two versions.**
  It reported the app version and the engine version, which are what a bug
  report needs — but neither answers the question a user handed a `.qnw` by a
  colleague actually has: *will this open on my machine?* A store written by a
  newer schema raises rather than degrading, so the format number is the one
  that answers it. The box now reads all three and says plainly that a newer
  project will not open here.

- **The installer build refuses to ship a stale payload.** `build_payload.py`
  reads the app, engine and store-format numbers out of the source tree, has
  the built payload report what it thinks they are, and fails the build on any
  disagreement. A `core/` left behind by an earlier build would otherwise ship
  an installer whose provenance names the wrong engine, and nothing would catch
  it: the app runs, the screens render, every other assertion in `verify()`
  passes. Six tests cover the agreeing case, both kinds of staleness, and the
  case where the verification script and the check that parses it drift apart.

- **A welcome screen, so the program says what to do.** With no project open,
  Documents used to render its three-pane layout empty: an empty corpus list, an
  empty reader, an empty code list, an empty codebook. Five blank boxes and no
  instruction, and that was the first thing every new user saw.

  It now offers the three things a person can usefully do with no project:
  **Try the sample project**, **Open a project…**, **Create a new project…**, and
  a link to the guide. The sample comes first and builds a real project on
  demand, forty responses with five codes and fifty-three codings, which is the
  project the Help walkthroughs are written against. One click takes a new user
  from nothing to something they can follow along with.

  A panel rather than a dialog. A modal has to be dismissed before the program
  can be looked at, which teaches a new user that the first thing this software
  does is get in the way.

### Fixed

- Two layout defects on the new screen, visible only by rendering it and
  with the tests green: the two single-field shelves were stretched to the
  height of the multi-field ones and became large empty boxes, and the Fit
  button spanned the full window width, reading as a banner rather than a
  button.

## [0.99.0] — 2026-08-28

**Still deliberately pre-1.0.** The version jumps from 0.9.0 to 0.99.0 to mark
that the feature work is essentially complete: what stands between here and
1.0.0 is not code, it is `RELEASE_READINESS.md` §1.1 — one real research project
carried through the program by someone other than its maintainer.

### Added

- **A Charts screen.** Pick a chart type, drag fields from the palette onto the
  X, Y, Colour and Split-by shelves, and read the figure. Eleven chart types,
  seven aggregates, one-click suggestions, and a click on any bar, slice or cell
  reports what it holds.

  Drag-and-drop is the reason this screen is worth having here and not in the
  web build: Qt does it natively, so a field goes where you drop it instead of
  being chosen from a list. `V5_PLAN.md` §B1a records why the web build keeps
  dropdowns.

- **A figure you can put in a report.** Save the chart as a PNG at 1–4× screen
  resolution, and save the numbers behind it as a CSV. The image is opaque —
  a transparent PNG pasted into Word loses light text against white — and the
  CSV is the file a reviewer checks and a co-author re-plots, which is why it
  is a button of its own rather than an afterthought.

- **Joint displays on the Reports screen.** The mixed-methods table: each theme
  against a subgroup, an illustrative quote, and the integration statement
  written on the Analysis screen. Word for a findings chapter with the caveats
  printed beneath it; Excel as a working file that never carries response text.
  Both come from the same project memos as the web build, so a project carries
  its inferences between the two programs.

### Fixed

- **The build script could not clean up after itself.** A second
  `build_payload.py` run failed before it started with `PermissionError:
  [WinError 5]` on a directory inside the previous payload. `RELEASE_READINESS.md`
  §3.3 records this as a known Windows trap and says any new build script must
  handle it; this one did not. Cleanup now clears the read-only bit and retries
  with a backoff, the same shape `tools/build_release.py` already used.

- **Every chart suggestion was over an internal identifier.** Fixed in the
  shared engine, so both builds get it — see `CHANGELOG.md`. Found by rendering
  this screen and looking at it, which is also how the heatmap's missing colour
  scale and the light skin's inverted ramp were found.

## [0.9.0] — 2026-08-22

First packaged release. **Pre-1.0 on purpose:** the program now works and has
been used, but not yet by anyone other than its maintainer, and not yet on a
real research project. 1.0.0 is for when that is no longer true.

### Added

- **Windows installer.** One signed-when-a-certificate-exists `.exe`, 103 MB,
  containing its own Python. No prerequisites, no admin rights, no network at
  install time. Per-user install; the uninstaller removes the program and
  leaves projects, saved output, and the model cache alone.
- **Reports screen.** The methods and reliability appendix, a codebook report,
  a narrative analysis report, an analysis workbook, and a shareable bundle.
  Each states what it will contain before you write it; anything that would put
  participants' words in a file asks for confirmation first.
- **Data screen.** Project details, the analyst name, backups with restore, a
  portable project archive, and erasure of a participant who has withdrawn.
- **Application identity** — its own version, an application icon, and a
  console-less launch, so no terminal window trails the program.

### Fixed

- **Erasing a participant left their words readable in the project file.**
  Deleting a row in SQLite frees the page without overwriting it, so the erased
  response stayed legible in the file's bytes — `strings project.qnw` printed
  it back — while being correctly absent from every query. The store is now
  rebuilt after an erasure. Anyone who has performed an erasure with an earlier
  build should assume the data is still recoverable from that project file.
- **Erasure left the data in the backup it had just taken.** The pre-erasure
  snapshot contains the un-erased response, so an erasure that kept it had
  moved the data rather than removed it. Purging the backups is now offered in
  the same confirmation, ticked by default.
- **The application icon never appeared.** Every frame was PNG-compressed, which
  Windows accepts only at 256×256; below that the shell renders nothing.
- **The taskbar showed Python's icon, and pinning did not work.** The process
  and its shortcut now declare the same AppUserModelID.

### Changed

- **Pipeline is now Survey** — named for what a researcher is doing rather than
  for the machinery behind it.
- **PySide6-Essentials** replaces the full Qt package. The application imports
  three Qt modules; the rest was 435 MB of nothing.

### Known limitations

- **Windows only.** The installer ships a Windows interpreter. The application
  itself has no Windows-specific code beyond the taskbar identity, but it has
  never been run on macOS or Linux.
- **Unsigned.** Until a code-signing certificate exists, Windows shows
  "Windows protected your PC" on first run — **More info → Run anyway**.
- **The analysis engine is a separate step.** Reading, coding, the codebook,
  analysis, search, query, and reports all work without it; automatic survey
  coding and the codebook's similarity check need it, and it is not yet
  installable from inside the application.
- **No real research project has been carried through this program.** Both
  shipped walkthroughs have been performed and the survey pipeline has run for
  real, but that is not the same as a project.

[0.99.0]: https://github.com/
[0.9.0]: https://github.com/
