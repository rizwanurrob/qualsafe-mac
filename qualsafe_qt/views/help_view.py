"""
Help: a walkthrough, a reference, an FAQ, and what the tool refuses to do.

Written for someone who has never seen this program and is about to code
sensitive data with it. Three editorial rules:

**No internal vocabulary.** The reader has not seen any other version of this
tool, does not know what a "front end" is, and should never be told that
something "matches the Streamlit build". Design history belongs in code
comments, not in a user guide.

**Start with doing, not with concepts.** The first section is a walkthrough
against the datasets that ship with the app, so a new user reaches a real result
before reading a definition.

**Say what the tool will not do.** A qualitative researcher has to defend their
method. The sections on kappa, on machine coding, and on the limits of the
privacy guarantee exist so the answer to "how do you know?" is in the tool
rather than in a maintainer's head — including the honest note that no real
project has been through it yet.

Rendered from Markdown so the same text exports as the user guide that ships
with a release, rather than being maintained twice.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMessageBox, QPushButton, QSplitter, QTextBrowser, QVBoxLayout, QWidget,
)
from qualsafe_qt.widgets.clip_player import ClipPlayer

#: The guide, as (title, markdown) sections. Data rather than a blob so the
#: contents list, the search box, and the export all read the same source.
HELP_SECTIONS: List[Tuple[str, str]] = [
    ("Start here — your first analysis", """
# Your first analysis

Four short walkthroughs against data that ships with this app. Nothing here
touches real people, so experiment freely.

---

## A. Code a transcript by hand (about 5 minutes)

This is the heart of the tool.

1. **File → New project…**, name it `practice.qnw`, and save it anywhere.
2. Go to **Documents** and click **Import a folder…**. Choose the `data` folder
   inside the QualSafe installation. It contains
   `sample_interview_transcript.txt` — a synthetic first-year student interview.
3. Review the import gate and confirm. The transcript appears in the corpus list
   on the left; click it to open it in the reader.
4. Go to **Codebook** and click **Add code**. Add three:
   `Financial concerns`, `Sense of belonging`, `Academic difficulty`.
5. Back on **Documents**, **drag across a sentence** in the reader — try the one
   about the cost of textbooks.
6. Press **`1`**, **`2`**, or **`3`**. That applies the matching code from the
   list on the right.
7. Watch the left margin: a coloured bar appears beside the passage. Click the
   bar to jump back to it later.
8. Press **Ctrl+Z**. The coding is undone. Press **Ctrl+Y** to put it back.

Code six or seven more passages. Then open **Analysis → Frequency** and click a
bar to read the passages behind the number.

**What you just did:** every coding stored the exact character positions of what
you selected, so each count traces back to the words that produced it.

---

## B. Code a survey automatically (about 10 minutes)

This one needs the analysis engine and its models — see **Models** first. If
they are missing, do walkthrough A instead; hand coding needs neither.

1. Go to **Survey → 1 · Data** and click **Load the built-in sample**. That is
   `sample_survey_education.csv`: 40 synthetic responses to one question about a
   first year at university.
2. Read the privacy scan, then tick the confirmation box.
3. Under **Columns**, set **Text column** to `response_text` and **Question
   column** to `question_text`.
4. Go to **2 · Themes**, pick **Education / Student Experience** from the
   starter packs, and click **Use this label pack**.
5. Go to **3 · Run**. Click **Quick preview (50 rows)** first — it is fast and
   writes no project.
6. Happy with it? Click **Run the analysis**. Progress shows at the bottom; the
   window stays usable while it works.
7. When it finishes, the project it wrote opens automatically. Go to
   **Documents**, **Codebook**, and **Analysis** to see the coding.

**What you just did:** the model proposed a first pass. It is a draft. Open
**Analysis → Frequency**, click through the passages, and correct what is wrong
— that correction is the actual analysis.

---

## C. Mixed methods with subgroups (about 10 minutes)

To break themes down by respondent attributes.

1. **Survey → 1 · Data → Open a data file…** and choose
   `synthetic_entering_student_survey_wide.csv` from the `data` folder.
2. Set **Shape** to **Wide — one column per question**. Each row is one student
   and each question has its own column.
3. Tick the `Q1_success`, `Q2_barrier`, and `Q3_support` columns under **Question
   columns**.
4. Set **Respondent id** to `Response_ID`.
5. Under **Descriptors**, tick `First_Generation`, `Class_Year`, and
   `Student_Type`.
6. Set themes and run as in walkthrough B.
7. Open **Analysis → Code × Descriptor**, choose `First_Generation`, and switch
   to **% within group** — subgroups differ in size, and percentages are what
   make them comparable.

**What you just did:** wide data was reshaped so every answer got its own id
while staying linked to the student who gave it. That is what lets a theme be
reported per person rather than per answer.

---

## D. Chart a spreadsheet (about 5 minutes)

For any table of survey answers or numbers, not only open text.

1. Go to **Data Charts** and click **Try the sample survey**.
2. Set **Field to analyse** to `Class year`. A bar chart appears straight away,
   each bar labelled like `26% (63/240)`: the percent, then how many chose it,
   then how many answered.
3. Under **Split by**, pick `First generation`.
4. Type a **Title**, then click **Save picture…** and choose PNG at 300 DPI.

**What you just did:** you made a chart for a slide without writing anything, and
the numbers behind it are in the table underneath. Your own file works the same
way: click **Open a CSV or Excel file…**. The file is never changed.
"""),

    ("What this is", """
# What QualSafe is

A **local-first qualitative analysis workbench**. A codebook you own, excerpts
that trace back to their source, descriptors for mixed methods, co-occurrence,
inter-rater reliability — plus automation that can do a first pass of coding.

**Everything runs on your machine.** Your text is never uploaded. The only steps
that touch the network are installing the analysis engine and downloading a model.
Each is deliberately separate from analysis, starts only when you press its button,
and runs in its own process.

## What it is for

Two shapes of data:

* **Documents** — interview transcripts, field notes, reports. You read them and
  code passages by hand.
* **Survey open text** — many short responses. The pipeline can code them
  against themes you define, and you check and correct it.

Most real projects use both.

## The screens

| | |
|---|---|
| **Documents** | read your corpus and code it by hand |
| **Codebook** | organise codes into a hierarchy, merge duplicates, check health |
| **Analysis** | frequency, co-occurrence, subgroups, inter-rater agreement, deviant cases, saturation |
| **Search** | find a phrase anywhere, read it in context, code every hit |
| **Query** | boolean retrieval, matrices, and the framework matrix |
| **Survey** | load a spreadsheet and code it automatically |
| **Data Charts** | chart any CSV or Excel file for a slide or a report |
| **Reports** | the methods appendix, reports, workbook, and bundle |
| **Data** | backups, a portable archive, and erasing a participant |
| **Models** | download and choose the local models |
| **Help** | this guide |

## Honest status

No real research project has been through this program end to end. It is
tested — several hundred automated checks — but tested is not the same as used.
Treat early results as something to verify, not to trust.
"""),

    ("Coding documents", """
# Reading and coding

**Documents** is a corpus list, a reader, and a coding panel.

## The one thing to learn

**Drag across text to select a passage, then press a number key.** Keys `1`–`9`
apply the first nine codes in the list. That is the whole loop, and it is meant
to be done hundreds of times without thinking about it.

| | |
|---|---|
| **Drag** | select the passage to code |
| **1**–**9** | apply that code |
| **Enter** | apply every code ticked in the list |
| **Ctrl+E** | grow the selection to whole sentences |
| **Ctrl+Z** / **Ctrl+Y** | undo / redo |

## What the colours mean

A coded passage is highlighted inline and gets a coloured bar in the left
margin. Overlapping codings get separate bars, so two codes on one paragraph
read as two bars rather than one ambiguous colour. Click a bar to jump to its
passage.

Colours come from the palette in **View → Appearance**, where you can also
choose a colour-blind-safe set. To pin one code to one colour, select it on the
**Codebook** screen and use **Choose colour…** — that choice is saved in the
project, so it travels with the file to a colleague.

## In-vivo coding

Tick **In-vivo** to name a new code after the selected text itself, when the
participant's own words are the best label.

## What gets stored

An excerpt records the **character positions** of what you selected, and its
text is read back out of the source at those positions — never from anything
typed or generated. That is what makes a quote defensible: it is the document's
own characters, or it is not stored.

If a document's characters cannot be mapped reliably to the reader, coding is
**disabled** for that document and the reader says so. Refusing is correct: a
code attached to the wrong passage is worse than no code.
"""),

    ("The codebook", """
# The codebook is yours

Nothing merges, renames, or deletes a code without you asking.

* **Drag a code onto another** to nest it; drag it to empty space to promote it.
* **Right-click** to add a code, add a child, merge, or delete.
* **Choose colour…** pins a code to a colour of your choosing.
* **Health** flags codes that are never applied, applied once, undefined,
  orphaned, or nested absurdly deep.
* **Duplicates** suggests pairs that are similar *in meaning* rather than
  spelling — "Cost worry" ≈ "Financial stress". Nothing is ever merged
  automatically. (Needs the analysis engine.)
* **History** snapshots the codebook before every merge, delete, and reparent.
* **Export / Import YAML** shares a codebook — names, definitions, and hierarchy,
  no data — with a colleague or a future project.

## Definitions matter

A code without a definition is not reproducible: nobody else can apply it the
same way, including you in six months. The health panel flags undefined codes
for exactly this reason.

## What is and is not undoable

Renaming, reparenting, and adding a code are undoable with **Ctrl+Z**.

**Merge and delete are not.** Both move or destroy *applications* — the coding
itself — and restoring a codebook snapshot brings back the code, not the coding
that was reassigned. An "undo" that only put the code back would misrepresent
what was recovered, so each asks first and says exactly what will happen.
"""),

    ("Analysis and agreement", """
# Making sense of the coding

## Frequency, co-occurrence, subgroups

Every number drills back. Click a bar, a heatmap cell, or a crosstab cell and
read the passages behind it.

Treat a count as a pointer to where to read, not as a finding. How often a code
appears does not say how much it matters, and a rare code can be the important
one. The three books it draws on differ on whether to report counts at all; see
**New to this · Counting and numbers**.

**Co-occurrence counts every coder by default**, including a model's. In a
project with both hand and machine coding, a passage you marked *A* and the
model marked *B* registers as an A+B co-occurrence that neither of you claimed —
so the screen says when it is mixing coders, and offers a filter for a single
coder's matrix.

**Code × Descriptor** breaks themes down by a respondent attribute. Use
**% within group** when subgroups differ in size: 10 of 20 first-generation
students is a bigger finding than 15 of 200 others.

## Deviant cases: passages that may not fit

**Analysis → Deviant cases.** Pick a code and press **Find them**. The program
reads every passage you gave that code and lists the few that sit furthest from
the rest, so you know where to start re-reading. Click one to read it; double-click
to open it in the reader.

It **proposes passages to read. It does not decide that any of them is deviant.**
A passage can sit far out because it is truly unusual (the kind of case that
sharpens your account), because it was coded by mistake, because it is very
short, or because it is about something else. Only reading it tells you which.
Distance is measured from how *you* used the code, not from its definition, and
nothing on this screen is saved to your project. A code needs at least eight
passages; below that the list would mean nothing. Silverman (ch. 17) and Creswell
(ch. 10, negative case analysis) both ask you to look for the cases that do not
fit and to say what you found.

## Saturation: have new codes stopped appearing?

**Analysis → Saturation** plots how many codes you had found after each source, in
order, and writes the sentence a methods section would use. It shows **code**
saturation only: that later sources stopped producing new codes. It says nothing
about whether your codes are richly enough understood, and it never says
"saturated". Whether the curve has flattened enough is your judgement about your
design. The cautions are printed above the curve and travel with it: a codebook
written before coding began makes the curve meaningless; sources are in the
order they were added, which may not be the order you collected them (tick the
box only if it is); and a short run of sources cannot show a plateau.
**Human coding only** is on by default, because a model applying a fixed list of
labels flattens the curve at once.

## Agreement (κ)

Inter-rater reliability is **per-code binary Cohen's κ**, and nothing else. No
Krippendorff's α, no AC1. κ is always shown beside **percent agreement**,
**prevalence**, and an **insufficient-N flag**, because the kappa paradox — high
agreement and a low κ on a rare code — is only visible when they travel
together.

A rough reading: below 0.4 is poor, 0.4–0.6 moderate, 0.6–0.8 substantial, above
0.8 strong. Codes below the floor are listed as "route to human review".

**What the textbooks say about a target.** There is no agreed standard.
Saldaña gives 80–90% agreement as a common minimum for people who want a
number, and Creswell describes a team that aimed for 80%, counting a code as
agreed when both coders gave it to a passage both had coded. Cohen's κ is
optional there. None of them treats agreement as proof that the coding is
*right*: it shows that two people can reach similar results. Decide, and write
down, what you are agreeing on (the same code names, the same passages, or the
same passages given the same codes). See **New to this · Coding with a partner**.

**A coder is compared with a coder, or with the engine, never mixed up.** Under
*Survey responses*, only people are listed, so the analysis engine can never pass
for a second analyst. To see how well the engine agrees with you, choose
**Compare → Survey responses: coder vs engine**: you, against one analysis run
(the most recent first; runs are never pooled). It is the same figure the Word
report, Excel workbook and methods appendix print.

Read that κ with its caveat. It describes the responses you coded, and it stands
for the whole dataset only if those were a random sample. The project does not
record how they were chosen, so the screen checks: if the engine left far more
of your responses without a code than the rest, you coded the hard cases (a
review queue does exactly this), and κ there understates agreement across the
run. Disagreements with the engine can be read, but not reconciled: reconciling
is between two people.

Text-search auto-coding is never compared: a search is not a coder. A structured
(Laya) run is checked by calibration, on a random sample, instead.

## Reconciling

Where two coders differ, resolve the item to an agreed set. The resolution is
saved as a separate `human_adjudicated` coder and **never alters either coder's
original codings** — κ depends on them, and a resolution that rewrote history
would make the reported agreement unreproducible.
"""),

    ("Search and query", """
# Finding things

## Search

Plain text or regex, whole word or substring, filtered by document type, case,
or existing code. Hits are grouped by document and shown in context, with a
profile of the words that sit either side of your term.

**Double-click a hit to open it in the reader with the match selected**, ready
to code by hand.

**Code all hits** applies a code to the whole result set at once. It is saved
under a separate `auto_textsearch` coder, kept apart from your own work, and is
reversible.

**Word frequency** shows what the corpus actually says before any codebook
exists. The `documents` column is the useful one: it separates a word one person
repeated twenty times from a word everyone used once.

## Query

Boolean retrieval over codes: `AND`, `OR`, `NOT`, brackets, and `NEAR/n` (within
n characters). Quote multi-word code names.

```
Cost AND NOT FirstGen
"Cost worry" NEAR/200 dropout
(Cost OR Money) AND Belonging
```

**The unit changes the answer, so choose it deliberately.** `Cost AND Belonging`
means something different at "the same passage", "the same document", and "the
same case" — two codes on different paragraphs of one interview are a match at
document level and not at passage level. A query whose unit you have not thought
about is a finding you cannot defend.

Save a query you will run again. Double-click any result to open it in the
reader.

## Framework matrix

Cases down the side, themes across the top, each cell summarising what that case
said about that theme. Create cases on the **Cases** tab — singly, or in bulk
from a descriptor, which is the quick way to make survey data case-based.

Cells can be drafted by a local LLM if you have Ollama. Every quote it offers is
**checked verbatim against the source**, anything altered is dropped and
counted, and the draft is not saved until you save it.
"""),

    ("Running a survey analysis", """
# The survey pipeline

**Survey** loads a spreadsheet, maps its columns, takes a list of themes, and
codes every response against them.

## What it needs

* A CSV, Excel, JSON, or SPSS `.sav` file.
* The **analysis engine** and its models — see **Models**.
* At least one theme on the **Themes** tab.

## Before it will run

The screen tells you what is still missing. In short: data loaded, the text
column chosen, the dataset reviewed and confirmed, and at least one theme
written.

**The text column is never guessed.** In a long-form survey the first text-like
column is often the *question*, and an auto-pick would quietly analyse the
prompts instead of the answers — and succeed. One more click is cheaper than a
wrong analysis that looks right.

## Long or wide?

* **Long** — one row per answer, with a column saying which question it answers.
* **Wide** — one row per respondent, one column per question. This is reshaped
  before analysis, giving each answer its own id while keeping it linked to the
  person who gave it.

## The review gate

An assistive scan runs when data is loaded, and you confirm you have reviewed
it. The scan is **heuristic, not a verdict** — it misses a name written
mid-sentence and flags harmless numbers. What the gate records is your review.
It is asked again whenever you load different data, and is never remembered
between sessions.

## Preview versus a real run

A **quick preview** caps the rows and refuses to write a project file, so a fast
look can never quietly become the analysis of record.

## Engines

* **Transformer** — the default. Fast, needs no extra setup beyond the models.
* **Local LLM** — needs Ollama running on your machine. Slower, adds a rationale
  per response. Nothing leaves your computer either way.

**Strict coding** routes uncertain codings to review instead of guessing.
Thresholds are kept per engine because the two report different things: the
transformer reports entailment, the LLM reports its own confidence. The numbers
are not comparable.

## While it runs

The run happens on a background thread with a progress bar. The window stays
usable — read documents while it codes.
"""),

    ("Charting a spreadsheet", """
# Charting a spreadsheet

**Data Charts** turns any CSV or Excel file into a chart for a slide or a report,
and gives you the table of numbers behind it. It works on survey exports and on
ordinary tables. Your file is read into memory and never changed, and nothing
leaves this computer.

## Four kinds of question

* **One question.** One column of answers. A column of numbers starts as a
  histogram and a column of dates as a line chart.
* **Matrix / Likert.** Choose several related columns. Each statement is one bar,
  each response one segment, and the base is worked out per statement. Answers are
  put in scale order, with "No opinion" last. The **Top and bottom boxes** tab
  gives the top one, top two, bottom one and bottom two shares, written like
  `70% (7/10)`: the percent, how many chose those answers, then the base.
* **Select all that apply.** One column where a cell holds several answers. An
  answer can contain the separator, as in `Relationships with friends, family,
  partners, or roommates`, so paste the real list of choices (or press **Suggest
  choices from the data**) and each cell is read by finding those exact phrases.
  Anything that does not match is counted and reported, never charted as a
  fragment.
* **Free text.** The number of responses, the most common words, and a button to
  save the responses. It is not turned into categories unless you ask.

## What counts as blank

Empty cells, `NULL`, `null`, `NaN`, `None`, `N/A`, `NA`, `(blank)` and `<null>`.
Blanks are never in the base of a percentage unless you choose otherwise, and the
screen tells you how many cells matched each word, so a real answer of "None" is
visible. Answers that differ only by spacing or capitals are never merged for you.

## Refining, and undoing

Filter rows, and use the **category grid** to leave a category out, relabel it,
combine several into one, or set your own order. None of it touches the file.
**Undo**, **Redo** and **Reset chart** step back through fields, filters,
relabelling and sorting. A relabel that would give two categories the same name is
refused rather than merged.

## Look and export

Four sizes change bars and text together. Choose a shape (16:9, 4:3, square,
report or your own), a colour theme (**QualSafe default** is the default), and
set titles, labels and axes. **Save picture…** writes PNG (96 to 600 DPI), SVG or
PDF, white or transparent, and **Copy picture** puts it on the clipboard. The
table can be saved as CSV or Excel, or copied.

## Saving a chart

**Save chart** keeps your choices, not your data, so the same kind of file later
gives the same chart. If a new file lacks a field the chart used, that choice is
cleared and the screen says which. Saved charts and your own colour themes are kept
in your user folder and survive an uninstall.
"""),

    ("Reports", """
# Reports

**Reports** turns the project into documents other people can read. Everything
is generated from the project exactly as it stands when you click the button.

## Which one you want

| | |
|---|---|
| **Methods & reliability appendix** | The one a reviewer or an ethics board asks for |
| **Codebook report** | The codebook as a document, with definitions and counts |
| **Analysis report** | A narrative over the whole project |
| **Analysis workbook** | Every table as a spreadsheet, for pivoting or handing on |
| **Shareable bundle** | A zip for a collaborator who does not have this program |

## Start with the methods appendix

It records which engine and models did the coding, the thresholds in force, who
the coders were, per-code agreement for every comparable pair, how many
disagreements were adjudicated, and which codebook version was in use.

It also carries the caveats **beside** the numbers rather than in a footnote:
which codes had too few items to be reliable, where the kappa paradox applies,
and — when no agreement is reportable at all — it says so plainly instead of
printing a blank table. That is what makes a result answerable when someone
asks "how do you know?".

## What ends up in the file

Redaction is decided per report, and each one says what it contains directly
above its button. In short:

* the **workbook** never contains response text;
* the **bundle** is redacted unless you tick the box — quotes are replaced as
  they are read from the project, so even the written summary is regenerated
  from redacted tables;
* the **analysis report** and the **codebook report** include verbatim quotes
  only if you ask for them.

Anything that would put participants' words into a file asks you to confirm
first. That warning is the last point at which the decision is reversible: once
the file exists you cannot know where it goes.

## Where the file goes

Wherever you choose — every button opens a save dialog first. **Show the last
file** opens the folder containing whatever you produced most recently.
"""),

    ("Data and participants", """
# Data management

**Data** is where the project file itself lives: its backups, a portable copy,
and the removal of a participant who has withdrawn.

## Your analyst name

Set it here before you start coding. It is stamped on every coding you make,
and it is what lets agreement analysis tell your codings from a colleague's.
Setting it afterwards does not relabel work you have already done.

## Backups

A snapshot is taken automatically before anything destructive — restoring a
codebook version, merging codes, erasing a participant. The newest five are
kept, and **Back up now** adds one whenever you want.

Restoring replaces the project with the snapshot. Anything coded since then is
gone from the project — but the current state is backed up first, so a restore
is itself undoable.

## Portable archive

One zip holding the project file, its run output, and its reports. Use it to
move a project between machines or hand it to a colleague who has this program.

**It contains your source text.** Treat it like the transcripts that went into
it.

## Erasing a participant

If someone withdraws their consent, this removes their response from the
project file, from the run output, from quotes in any generated report, and
from the caches. It also writes a hashed audit entry recording *that* an
erasure happened, never who.

You type `ERASE` to confirm. It cannot be undone.

### Leave "also delete this project's backups" ticked

Erasure takes a backup first. That backup still contains the response. Leaving
it in place means the data has been moved, not erased — so for a genuine
withdrawal-of-consent request the backups must go too.

Untick it only when you are correcting your own mistake and might need to undo.

### What this can and cannot promise

The response is removed from the project file, and the file is rebuilt so no
readable trace of it remains inside.

It cannot reach copies that have already left: an archive you emailed, a report
you exported, a backup you moved elsewhere, a drive backup your institution
takes. And deleting a file is not the same as shredding it — on most modern
storage a determined recovery attempt is not excluded.

If a participant's withdrawal has to be complete, track down the copies as well.
This program can only act on what is in front of it, and it would rather say so
than let you believe otherwise.
"""),

    ("Sharing your work", """
# Sharing and collaborating

## The project file

A project is a single `.qnw` file. It holds your documents, codebook, codings,
memos, cases, and colour choices. Copy it, email it, put it in a shared drive —
it is one file and it is self-contained.

**It contains your source text.** Treat it with the same care as the transcripts
that went into it.

## Working with a second coder

The usual shape of an inter-rater exercise:

1. Build the codebook and export it (**Codebook → Export YAML…**).
2. Send your colleague the YAML **and the documents** — not your project file,
   so their coding is genuinely independent.
3. They import the codebook, code the same material, and send back their `.qnw`.
4. Merge their codings into your project, then use **Analysis → Agreement (κ)**
   to compare and reconcile.

Project merging is not in this program yet. Until it is, two coders can work in
one file by taking turns rather than in parallel.

## Sharing a codebook without data

**Codebook → Export YAML…** writes names, definitions, and hierarchy only. No
responses, no codings, no participants. This is the file to attach to a methods
appendix or share with another team.

## Exports

* **Codebook YAML** — the scheme, no data.
* **Query results** and **matrices** — CSV, from the Query screen.
* **Framework grid** — CSV.
* **This guide** — Markdown, from the button below the contents list.

## Reporting your method

Say which engine coded what, that a human reviewed it, how agreement was
computed (per-code Cohen's κ with percent agreement and prevalence), and what
was excluded and why. The tool records the model, thresholds, and counts for
every run so those numbers are recoverable rather than remembered.
"""),

    ("Privacy and what it guarantees", """
# Privacy

## What is guaranteed

* **Analysis runs with the model hub pinned to your local cache.** The offline
  flags are set before anything that could reach the network is loaded, and the
  status bar reports the *actual* state of the program rather than an intention.
* **Your text is never uploaded**, by this tool, anywhere.
* **Model downloads run in a separate process**, so the running program never
  has offline mode lifted out from under it.
* **Preferences are a short whitelist** — window size, theme, text size, your
  name, the last project path, the chosen models. Nothing derived from a
  response, a document, or a code is ever written to settings.
* **Destructive operations back up the project first.**

## What is *not* guaranteed

* **The PII scan is not a compliance check.** It is a set of patterns for
  emails, phone numbers, and name-shaped columns. Treat a clean result as
  "nothing obvious", never as "safe to share".
* **A local LLM is still a program on your machine** reading your data. It does
  not phone home, but treat it like any other program that can read your files.
* **A `.qnw` file is not encrypted.** It is as protected as the disk it sits on.
* **This tool does not manage your IRB obligations**, consent, retention
  schedules, or the security of the machine it runs on.

## Erasing a participant

Removing a respondent removes their sources, excerpts, codings, and descriptors,
along with their cached embeddings. The project is backed up first.
"""),

    ("Keyboard shortcuts", """
# Shortcuts

## Documents

| | |
|---|---|
| **Drag** | select a passage |
| **1**–**9** | apply that code from the list |
| **Enter** | apply every ticked code |
| **Ctrl+E** | grow the selection to whole sentences |
| **Ctrl+Z** | undo |
| **Ctrl+Y** | redo |

## Anywhere

| | |
|---|---|
| **Ctrl+O** | open a project |
| **Ctrl+N** | new project |
| **F1** | this guide |
| **Ctrl+Q** | quit |

## Codebook

Drag a code onto another to nest it, onto blank space to promote it.
Right-click for add / merge / delete.
"""),

    ("Frequently asked questions", """
# FAQ

### Does any of my data leave this computer?

No. Analysis runs with the model hub pinned to your local cache, and the status
bar shows whether that is actually armed. The only network activity this program
ever performs is installing the analysis engine (software, from pypi.org and
download.pytorch.org) and downloading a model (weights, from huggingface.co). Each
happens in a separate process, only when you press its button, and sends none of
your text. The status bar describes analysis; it does not cover those two steps.

### Do I need Ollama?

No. It is optional. The transformer engine is the default and needs no Ollama.
Ollama only powers two things, both alternatives to something that already
works: the LLM coding engine, and drafting framework-matrix cells.

### Do I need an internet connection?

Only once, to download the models. After that the program works entirely
offline.

### How much disk space do I need?

The program itself is modest. The models are the bulk: roughly 2 GB for the
default three. **Models** shows exactly what is on your machine and what each
one costs, and lets you remove any of them.

### Can I use my own model?

Yes. **Models** lets you point any role at a different Hugging Face model.
Embedding roles want a sentence-transformers model; the zero-shot role wants an
NLI model.

### Is the automatic coding any good?

It is a first pass, not an answer. Treat it as a research assistant who has read
everything quickly and understood some of it. The workflow this tool is built
for is: let it propose, then read and correct. The agreement screen exists so
you can say how much you corrected.

### Can I use this for a published paper?

The methods are conventional — per-code Cohen's κ, prevalence, drill-back to
verbatim excerpts — and the tool records the model, thresholds, and counts for
every run so your methods section can be specific. But no real project has been
through this program yet, so verify results you intend to publish.

### What is a "case"?

The person, site, or group that a document belongs to. One interviewee may have
three transcripts; a focus group is one conversation with several speakers. Cases
let you report findings per person rather than per file, and they are the rows of
the framework matrix.

### Why can't I compare my coding to the model's with κ?

Because the model was fitted on some of the items it coded, and the project does
not record which ones. Including them would overstate agreement. See **Analysis
and agreement**.

### My codebook has 30 codes and some colours look alike.

**View → Appearance** offers a larger palette and a colour-blind-safe set, and
you can pin any individual code to a colour on the **Codebook** screen.

### Can two people work on the same project at once?

Not in the same file at the same time. Share the codebook as YAML, code
separately, and compare. Merging two coders' projects is not in this program
yet.

### Where are my files?

Projects go wherever you saved them. Survey runs write to an `output_qt`
folder next to the program, one folder per run, containing the outputs and a
`run_config.json` recording exactly what was asked for.

### Can I undo everything?

Coding, renaming, reparenting, and adding a code — yes, with **Ctrl+Z**. Merging
and deleting a code — no, because they move or destroy coding that a codebook
snapshot cannot restore. Both warn first.

### Is my project file encrypted?

No. It is as protected as the disk it sits on. If your data requires encryption
at rest, use full-disk encryption.
"""),

    ("Troubleshooting", """
# When something goes wrong

**"The model … is not in your local cache."**
Go to **Models** and download it. This is expected on a fresh install — getting
models is deliberately a separate step from analysis.

**Models says the analysis engine is not installed.**
Press **Install the analysis engine** on the Models screen. It downloads about
1 GB once, needs the internet that one time, and carries on from where it stopped
if it is interrupted. Only the pipeline and the codebook's similarity check need
it. Everything else — reading, coding, the
codebook, analysis, search, query — works without it.

**Coding is disabled for one document.**
Its characters could not be mapped to the reader reliably, so the tool refuses to
attach codes rather than risk attaching them to the wrong passage. Please report
the document; it is a bug worth fixing.

**The PDF imported with no text.**
It is probably a scan — an image of a page, with no text layer. Run it through
OCR first.

**A framework cell will not draft.**
Drafting needs Ollama running locally. It is optional; everything else works
without it.

**Agreement says it needs two human coders.**
κ is only defined on items two people both coded. A second coder arrives by
importing their work, or by reconciling disagreements — an adjudicated set is
itself a coder.

**A run failed part-way.**
The output folder for that run holds `run_config.json`, recording exactly what
was asked for. Nothing is written to your project until a run completes.

**The window is too small / the text is too small.**
**View → Appearance** sets the text size for the whole program. Panels can be
resized by dragging the dividers between them.

**Something looks wrong and none of the above fits.**
The status bar carries the last message, and the run folder carries the config.
Both are useful in a bug report.
"""),
]


class HelpView(QWidget):
    """The user guide: contents, a filter box, the text, and an export button."""

    status = Signal(str)
    #: An activity key: the person asked to see its tour again.
    tour_requested = Signal(str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._build_ui()
        self.contents.setCurrentRow(0)

    def _build_ui(self) -> None:
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Filter topics…")
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.setToolTip(
            "Type a word to narrow the topic list — it searches the whole guide, "
            "not just the titles.")
        self.filter_edit.textChanged.connect(self._filter)

        self.contents = QListWidget()
        self.contents.setMaximumWidth(380)
        self.contents.setToolTip("Pick a topic to read.")
        self.contents.currentRowChanged.connect(self._show_section)

        self.body = QTextBrowser()
        self.body.setOpenExternalLinks(False)
        self.body.setToolTip(
            "The user guide. Everything here is also available as a Markdown "
            "file via the button below.")

        export_button = QPushButton("Save the whole guide…")
        export_button.clicked.connect(self._export)
        export_button.setToolTip(
            "Write this guide to a Markdown file you can print, share, or attach "
            "to a methods appendix.")

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(self.filter_edit)
        left_layout.addWidget(self.contents, 1)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        self.player = ClipPlayer()
        self.player.setVisible(False)
        right_layout.addWidget(self.player, 3)
        right_layout.addWidget(self.body, 2)
        tour_row = QHBoxLayout()
        tour_row.addWidget(QLabel("Take the tour again:"))
        self.tour_buttons = {}
        from core.ux import activities as _activities
        for activity in _activities.ACTIVITIES:
            button = QPushButton(activity.title)
            button.setToolTip(f"A short tour of {activity.title}.")
            button.clicked.connect(lambda _=False, key=activity.key: self.tour_requested.emit(key))
            self.tour_buttons[activity.key] = button
            tour_row.addWidget(button)
        tour_row.addStretch(1)
        right_layout.addLayout(tour_row)
        right_layout.addWidget(export_button)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setSizes([370, 1010])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addWidget(splitter)
        self._populate(HELP_SECTIONS)

    def show_step(self, activity_key: str, step_key: str) -> bool:
        """Open the article for one step. False if there is none."""
        title = step_section_title(activity_key, step_key)
        if not title:
            return False
        self.filter_edit.clear()                       # a filter could hide it
        for row in range(self.contents.count()):
            if self.contents.item(row).data(Qt.ItemDataRole.UserRole) == title:
                self.contents.setCurrentRow(row)
                return True
        return False

    def _populate(self, sections) -> None:
        self.contents.blockSignals(True)
        self.contents.clear()
        for title, _body in sections:
            item = QListWidgetItem(title)
            item.setData(Qt.ItemDataRole.UserRole, title)
            self.contents.addItem(item)
        self.contents.blockSignals(False)

    def _filter(self, text: str) -> None:
        """Filter on the whole section text, not just its title.

        Someone looking for "kappa" should find the agreement section even
        though the word is not in its name.
        """
        needle = (text or "").strip().lower()
        matches = [s for s in HELP_SECTIONS
                   if not needle or needle in s[0].lower() or needle in s[1].lower()]
        self._populate(matches or HELP_SECTIONS)
        if self.contents.count():
            self.contents.setCurrentRow(0)

    def _show_section(self, row: int) -> None:
        if row < 0:
            return
        item = self.contents.item(row)
        if item is None:
            return
        title = item.data(Qt.ItemDataRole.UserRole)
        clip_id = CLIP_TITLES.get(title)
        self.player.setVisible(bool(clip_id))
        if clip_id:
            self.player.load(clip_id)
        else:
            self.player.pause()
        for section_title, body in HELP_SECTIONS:
            if section_title == title:
                self.body.setMarkdown(body)
                return

    def _export(self) -> None:
        path, _filter = QFileDialog.getSaveFileName(
            self, "Save the user guide", "QualSafe_user_guide.md",
            "Markdown (*.md)")
        if not path:
            return
        try:
            from pathlib import Path

            Path(path).write_text(full_guide(), encoding="utf-8")
        except OSError as exc:
            QMessageBox.critical(self, "Could not write the file", str(exc))
            return
        self.status.emit(f"User guide saved to {path}.")


def _where_things_are_now() -> str:
    """Old tab name -> where it lives now, from the same map the app uses.

    The walkthroughs were written for a row of tabs. Until the guide is rewritten
    by activity (Update 3, phase 4) this list keeps their directions usable.
    """
    from core.ux import activities

    lines = [
        "**The screens now live inside three activities: Surveys, Charts and "
        "Interviews.** The walkthroughs below were written when each screen was "
        "a tab. Where one says to go to a tab, use this list:",
        "",
    ]
    for screen in activities.DESKTOP_SCREENS:
        where = activities.locations(activities.DESKTOP, screen)
        lines.append(f"- **{screen}** → " + ";  ".join(where))
    return "\n".join(lines) + "\n"


_first_title, _first_body = HELP_SECTIONS[0]
HELP_SECTIONS[0] = (_first_title, _first_body.replace(
    "\n---\n", "\n" + _where_things_are_now() + "\n---\n", 1))

# The beginner's guide sits right after the two opening sections, so someone new
# to qualitative research meets it before the screen-by-screen reference. It is
# shared with the web Help page (core/ux/guide.py), so there is one text.
from core.ux import guide as _guide  # noqa: E402

HELP_SECTIONS[2:2] = _guide.all_sections()


def _step_sections() -> List[Tuple[str, str]]:
    """One short article per step of each activity, from `core/ux/help/`."""
    from core.ux import help as shared_help

    rows = []
    for activity_key, step_key in shared_help.steps():
        text = shared_help.article(activity_key, step_key)
        if text:
            rows.append((shared_help.title_of(text), text))
    return rows


def _task_sections() -> List[Tuple[str, str]]:
    """The task articles ("How do I compare two groups?"), the short clips, then the glossary."""
    from core.ux import help as shared_help

    rows = []
    for task_id in shared_help.task_ids():
        text = shared_help.task(task_id)
        if text:
            rows.append((shared_help.title_of(text), text))
    rows.extend(_clip_sections())
    rows.append((shared_help.title_of(shared_help.glossary()), shared_help.glossary()))
    return rows


#: Help section title -> clip id, for the sections that show a player above their text.
CLIP_TITLES: dict = {}


def _clip_sections() -> List[Tuple[str, str]]:
    from core.ux.help import media as shared_media
    from qualsafe_qt.widgets.clip_player import media_description

    rows = []
    for clip in shared_media.CLIPS:
        title = f"Watch: {clip.title}"
        CLIP_TITLES[title] = clip.clip_id
        said = media_description(shared_media.read(clip.clip_id) or "<svg xmlns='http://www.w3.org/2000/svg'/>")
        rows.append((title, f"# {title}\n\n{clip.summary}\n\nPress **Play**, or use **Next** and **Back** "
                            f"to go one caption at a time.\n\n**In words.** {said}\n"))
    return rows


#: Right after the first-analysis walkthroughs, before the long reference sections.
STEP_SECTIONS = _step_sections()
TASK_SECTIONS = _task_sections()
HELP_SECTIONS[1:1] = STEP_SECTIONS + TASK_SECTIONS

# The old Troubleshooting is replaced by the shared one, which is written for researchers
# and matches the three-activity screens (core/ux/help/troubleshooting.md).
def _troubleshooting_section() -> Tuple[str, str]:
    from core.ux import help as shared_help

    return ("Troubleshooting", shared_help.troubleshooting())


HELP_SECTIONS[:] = [s for s in HELP_SECTIONS if s[0] != "Troubleshooting"] + [_troubleshooting_section()]


def step_section_title(activity_key: str, step_key: str) -> str:
    from core.ux import help as shared_help

    return shared_help.title_of(shared_help.article(activity_key, step_key) or "")


def full_guide() -> str:
    """Every section as one Markdown document — what a release ships."""
    from qualsafe_qt.version import version_line

    parts = [
        "# QualSafe — user guide",
        "",
        f"Version {version_line()}. Everything in this program runs on your own "
        "machine.",
        "",
        "---",
        "",
    ]
    for _title, body in HELP_SECTIONS:
        parts.append(body.strip())
        parts.append("")
        parts.append("---")
        parts.append("")
    return "\n".join(parts)
