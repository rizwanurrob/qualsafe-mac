"""
The beginner's guide to qualitative research, as data.

Written for someone who has never coded a transcript. Each section is a title and
a Markdown body, so the desktop Help screen, the web Help page and the exported
user guide all read the same text instead of three copies drifting apart.

**Where the ideas come from.** Three books, all cited by page or chapter so a
reader can check them and a methods section can name them:

* Saldaña, J. (2013). *The Coding Manual for Qualitative Researchers* (2nd ed.).
  SAGE. Cited as *Saldaña* with page numbers.
* Creswell, J. W. (2013). *Qualitative Inquiry and Research Design: Choosing
  Among Five Approaches* (3rd ed.). SAGE. Cited as *Creswell* with chapter.
* Silverman, D. (2017). *Doing Qualitative Research* (5th ed.). SAGE. Cited as
  *Silverman* with chapter.

Everything here is paraphrased. The examples are invented for this guide. Nothing
is copied from the books, and the guide says so, because a beginner should read
the books and not stop at this summary.

**Editorial rules** (the same ones as the interface, see `core/ux/words.py`):
plain words first, the book's term beside it; say what the tool does *not* do;
never describe a computer's output as a finding.

This module imports nothing, so the web app, the desktop app and the tests can
all load it without Qt, Streamlit or a model.
"""

from __future__ import annotations

from typing import List, Tuple

#: Short names used in citations, and the full references for the books page.
BOOKS = {
    "Saldaña": "Saldaña, J. (2013). The Coding Manual for Qualitative Researchers "
               "(2nd ed.). SAGE.",
    "Creswell": "Creswell, J. W. (2013). Qualitative Inquiry and Research Design: "
                "Choosing Among Five Approaches (3rd ed.). SAGE.",
    "Silverman": "Silverman, D. (2017). Doing Qualitative Research (5th ed.). SAGE.",
}

#: Prompts for a research-diary note, one per kind of thinking the books ask for.
#: (title, a question to start from). Drawn from Saldaña, pp. 43-49, reworded.
MEMO_TOPICS: List[Tuple[str, str]] = [
    ("My position",
     "How do I relate to these people or this topic? What do I bring to it, and "
     "what might I be missing?"),
    ("My research question",
     "What am I trying to find out? What does the data say so far, and what does "
     "it not say?"),
    ("A code and why",
     "Why did I name or define a code this way? What did I decide about the "
     "borderline cases?"),
    ("Patterns forming",
     "Which codes seem to belong together? What might they add up to?"),
    ("How things connect",
     "How do the codes, categories and themes link? Does one cause, follow or "
     "contradict another?"),
    ("Ideas from reading",
     "What existing theory or earlier study does this remind me of? Does my data "
     "agree with it, or push back?"),
    ("A problem with the study",
     "What is going wrong or feels unclear? Who or what is missing?"),
    ("An ethical worry",
     "What did a participant tell me that I am unsure how to handle? What should "
     "I not ask, not quote, or not share?"),
    ("What to do next",
     "Whom should I talk to, what should I read or collect next, what should I "
     "recode?"),
    ("Looking back",
     "Reading my earlier notes, what keeps coming up? What has changed in my "
     "thinking?"),
    ("The write-up",
     "What is the story I want to tell? Which quote opens it? How should it be "
     "organised?"),
]

# ---------------------------------------------------------------------------
# Sections. Titles start with "New to this ·" so they group in a contents list.
# ---------------------------------------------------------------------------

SECTIONS: List[Tuple[str, str]] = [

    ("New to this · Start here: the whole path", """
# New to qualitative research? Start here

Qualitative analysis means reading what people said or wrote, working out what
it means, and showing your reasoning so someone else can follow it. It is slower
than counting, and it answers different questions: *how*, *what is it like*,
*why do people say so*.

**You are not expected to know this already.** Read this page, then dip into the
other **New to this** sections when you reach that step.

## The path in nine steps

1. **Say what you want to find out.** Write one open question, for example "What
   makes the first year hard for students who are first in their family at
   university?" It can change as you learn (Creswell, ch. 3; Silverman, ch. 8).
   *In QualSafe:* keep it in your first diary note (Codebook → Diary).
2. **Choose an approach.** Stories of one life? The shared meaning of an
   experience? A theory from the data? A culture? A single case? See **Pick an
   approach**.
3. **Plan the data and the ethics.** Who is taking part, what did they agree to,
   and how will you protect them (Silverman, ch. 4; Creswell, ch. 3)?
   *In QualSafe:* the import step scans for names and contact details; **Data**
   erases one participant on request.
4. **Read everything, and jot as you go.** Read it all before you cut it into
   parts, and write short notes in the margin (Creswell, ch. 8; Saldaña, pp.
   19-21). *In QualSafe:* **Documents**, or read the survey answers in the
   table.
5. **First pass at coding.** Give each meaningful passage a short label. See
   **Your first pass at coding**.
6. **Write memos as you go.** A memo is a note to yourself about what you think
   is happening and why. See **Memos and your research diary**.
7. **Recode, group, and name the themes.** Merge codes, sort them into
   categories, and state what the categories mean (Saldaña, ch. 4-5).
   *In QualSafe:* **Codebook** (drag codes together), **Analysis**, **Query**.
8. **Check your work.** Look for the cases that do not fit, ask someone else to
   look, and write down what you did. See **Checking your work**.
9. **Write it up.** Show your evidence, say how you got there, and say what you
   could not tell. See **Writing it up**.

You will go round steps 4 to 8 more than once. That is normal. Creswell describes
the work as a spiral rather than a line (ch. 8).

## What QualSafe is and is not

* **It is** a workbench for coding text, keeping a codebook, comparing coders,
  and tracing every number back to the words behind it.
* **It is not** an analyst. It cannot decide what your data means. Where it
  suggests codes, those are drafts for you to check (see **Using the computer's
  suggestions**).
* **It fits best** coding-based work: thematic and content analysis, case
  comparison, and the coding stages of grounded theory. It does not yet help
  with telling a life story in order, or with the fine detail of conversation
  analysis (see **Pick an approach**).
"""),

    ("New to this · Codes, categories and themes", """
# Codes, categories and themes: three different things

Beginners often use these as if they meant the same thing. The books use them
carefully, and a reviewer will notice.

| Step | What it is | Example |
|---|---|---|
| **Passage** | The bit of text you are looking at | "I almost dropped out because I couldn't pay rent." |
| **Code** | A short word or phrase that says what the passage is about or means | FINANCIAL STRAIN |
| **Category** | A group of related codes | Money pressures |
| **Theme** | A sentence that says what the pattern *means* | "For these students, money decides whether they stay, not just how they feel." |
| **Assertion or theory** | A claim that reaches beyond this study | (later, and only if the data support it) |

**The key idea:** you code the data; you do not code *for* themes. A theme is an
*outcome* of coding and thinking, not a label you stick on a passage on the
first read (Saldaña, p. 14). A code is usually a word or short phrase and says
*what is there*. A theme is a phrase or sentence and says *what it means*
(Saldaña, p. 14 and p. 267).

Creswell uses "category" and "theme" almost interchangeably, and calls a theme a
broad unit made of several codes (ch. 8). So when you read two books and they
seem to disagree, they mostly do not: Creswell is describing the *level* (broad),
Saldaña is describing the *kind of statement* (a sentence, not a label).
**Pick one way of speaking, say which, and keep to it.**

## What "theme" means in QualSafe

On the Survey screens, the short topic names you give the computer to look for
are called *themes* because that is the everyday word. In Saldaña's terms they
are **codes you decided on in advance** (his name for this is Provisional
Coding, a "start list", Saldaña, p. 266). The sentence-length theme is the one you
write yourself after reading the passages. Where QualSafe asks for "your
integration statement" or "one line per theme, in your words", that is the real
theme.

## How many?

There is no fixed number. For orientation: Creswell likes a short start list of
five or six codes that grows to no more than 25-30 categories and ends at five to
seven themes (ch. 8). Others suggest 80-100 codes for a typical education study
and a team handling 30-40 at once (Saldaña, p. 24). Saldaña's own advice is to
hold the number of major themes to a minimum and not to chase a standard figure
(p. 24). Fewer, clearer, well-defined codes are easier to apply and to defend.

## Naming a code

* Use words you can read in six months. Write them out in full; do not
  abbreviate (Saldaña, p. 21).
* Use a **participant's own words** when they say it best, in quotation marks.
  This is called In Vivo coding. In QualSafe, tick **In-vivo** before you apply
  the code.
* A **gerund** (an "-ing" word) names an action: NEGOTIATING, AVOIDING (Saldaña,
  p. 266).
* **Lumping** (one code for a big stretch) is faster; **splitting** (many small
  codes) is finer but slower. Neither is wrong. Choose on purpose (Saldaña,
  pp. 22-23).
"""),

    ("New to this · Pick an approach", """
# Pick an approach (a quick outline of five)

An *approach* is a way of asking and answering a kind of question. Creswell's
book is organised around five. You do not need to be an expert in one, but you
should know which one your study resembles and say so (Creswell, ch. 2-4; Table
4.1).

| | Narrative | Phenomenology | Grounded theory | Ethnography | Case study |
|---|---|---|---|---|---|
| **Focus** | The life of one person | What an experience is like | A theory built from the data | How a group shares culture | One case (or a few), in depth |
| **Good when** | You need to tell individual stories | You need the essence of a lived experience | You need an explanation, a process | You need to describe shared patterns | You need to understand a bounded case |
| **Unit** | One or a few people | Several people who share the experience | A process or action involving many | A group that shares a culture | An event, program, activity or person |
| **Data** | Interviews, documents | Mainly long interviews | Mainly interviews (Creswell suggests 20-60) | Mainly observation and interviews | Many sources |
| **Analysis** | Stories, turning points, a timeline | Significant statements, meanings, the "essence" | Open, axial and selective coding | Description, then themes about the group | Description of the case, then themes |
| **Result** | A story of a life | A description of the essence | A theory, often as a figure | A picture of how the group works | A detailed analysis of the case |

(Adapted in words from Creswell, Table 4.1. The table there is the authority.)

## Which parts of QualSafe fit?

* **Good fit:** coding passages, building a codebook, comparing groups, case-by-
  theme matrices. This suits thematic work, case studies, the descriptive side
  of ethnography, and phenomenological theme statements.
* **Partial fit:** grounded theory. You can code, nest codes and write memos.
  It does not walk you through axial or theoretical coding, so do that thinking
  in your memos.
* **Not covered:** narrative ordering of a life story, and conversation analysis,
  which depends on transcribing pauses and overlaps (Silverman, ch. 17).

## Is qualitative the right choice at all?

If you mainly need to count how many people did or thought something, a survey
may serve better. Qualitative methods earn their cost when your question is about
how and why, or when you do not yet know the right questions (Silverman, ch. 2;
his Tip 32). The **Charts** activity is there for the counting.

## Hint

Do not over-complicate a first study. Few cases, few methods, looked at well:
"the best research says a lot about a little" (Silverman, Tip 48).
"""),

    ("New to this · Your first pass at coding", """
# Your first pass at coding

Coding is the move from "I have a lot of text" to "I know what is in it". It is
interpretation, not measurement. Two people will code the same passage
differently and both can be reasonable (Saldaña, pp. 6-8, 38).

## Before you code

1. **Read it all through once.** Do not stop to code yet (Creswell, ch. 8).
2. **Keep your question in front of you.** Saldaña suggests one page with your
   research question and goals beside you (p. 21).
3. **Jot first thoughts** in the margin: not final codes, only ideas (Saldaña,
   pp. 19-20).
4. **Ask yourself as you read:** *What strikes me? What surprised me? What
   disturbed me?* The answers show your assumptions (Saldaña, p. 22).

## Then code

Choose a first-cycle method that fits your question. Here are the ones beginners
meet most:

| Method | It asks | Short example | In QualSafe |
|---|---|---|---|
| **Descriptive** | What topic is this about? (a noun) | HOUSING | Add a code, press its number key |
| **In Vivo** | What words did the person use? | "STOPPED CARING" | Tick **In-vivo** |
| **Process** | What action is going on? (an "-ing" word) | SEEKING HELP | Add a code in -ing form |
| **Emotion** | What feeling is here? | RELIEF, SHAME | Add a code |
| **Values** | What do they value, believe, feel about it? | VALUES INDEPENDENCE | Add a code |
| **Versus** | What two things are in conflict? | CAREER VS. FAMILY | Add a code |
| **Provisional** | What do I expect to find? (a start list) | FINANCIAL STRAIN | Survey → Themes list |
| **Structural** | What part answers my question? | one code per interview question | Survey with a question column |
| **Holistic** | What is this whole chunk about? | one code for a long answer | Select the whole answer |
| **Attribute** | Who said it? Which site? Which year? | FIRST-GENERATION | Respondent details / attributes |

You can **mix** methods in a first pass, as long as you choose them on purpose
and tidy up in a second pass (Saldaña, p. 188, "Eclectic Coding").

## First pass, second pass

The first cycle is rough and fast. The **second cycle** recodes: merge codes, drop
some, rename others, sort them into categories (Saldaña, pp. 10-12, ch. 4-5).
Data are not simply coded, they are *re*-coded. Expect to do it more than once
(Saldaña, p. 206).

## Hints

* **Begin small.** Code one interview or twenty answers thoroughly. Test your
  codes on a second, different piece of data to see if they hold (Saldaña, p.
  22; Silverman, Tip 39).
* **Code the strange bits too.** If you code only what fits, you will not notice
  what does not (Saldaña, p. 16).
* **Look at the ordinary**, not only the dramatic answers (Silverman, ch. 15).
* **Do it by hand first** if you are new. Learn the method, then learn the
  software, one at a time (Saldaña, p. 26; Silverman, Tip 40).
"""),

    ("New to this · Memos and your research diary", """
# Memos and your research diary

A **memo** is a note to yourself while you analyse. It is where the thinking
happens. A code is only a label until you write about what it means (Saldaña,
p. 41). Memos are also your **audit trail**: they show a reader how your ideas
developed (Saldaña, p. 50).

Silverman says the same thing in plainer words: keep a research diary from day
one. It will become the raw material for your methods chapter (Silverman, Tip 58).

## How

* **Write it right away** when an idea arrives. Do not trust memory (Saldaña, p. 42).
* **Do not tidy.** Write like a letter to a friend, not like a paper (Saldaña,
  p. 42).
* **Date it and give it a title** so you can find it later (Saldaña, p. 42).
* **Do not summarise the data.** Reflect on it.
* **Write about problems too.** A muddle you wrote down is a muddle you can
  explain.

## What to write about (pick one)

""" + "\n".join(f"* **{t}.** {q}" for t, q in MEMO_TOPICS) + """

*(Adapted from the eleven kinds of reflection in Saldaña, pp. 43-49. The same
prompts appear when you add a diary note in QualSafe.)*

## A short example

> **12 March · A code and why: FINANCIAL STRAIN.** I first called this MONEY but it
> swallowed everything. Two students mention cost without any hardship, so I now
> only use FINANCIAL STRAIN when someone says they cannot pay for something. Need to
> recheck the first six interviews.

## In QualSafe

* **Codebook → Code → Memos on this code** for notes about one code.
* **Codebook → Diary** for notes about the project: your position, your question,
  problems, ethics, next steps.
* **Reports → Audit trail** carries the *record* of your memos. Their *text* is only
  included if you tick the box, because a memo can quote a participant.

## A caution about drafts from a computer

A memo is meant to make *you* think. A computer-written draft skips that, so
write your own.
"""),

    ("New to this · The codebook", """
# The codebook

A **codebook** is the list of your codes with what each one means. It is how
someone else (or you, next month) applies a code the same way (Saldaña, pp.
24-25).

## What goes in an entry

Bernard and Ryan, cited by Saldaña (p. 25), suggest each entry have:

* a **short name** (the code itself);
* a **fuller description**, one to three sentences;
* **when to use it** (inclusion);
* **when to leave it out** (exclusion);
* a **typical example** and, if you can, an **unusual example** that still counts;
* a **close-but-no** example: something that looks like it but should not get it.

*In QualSafe:* **Codebook → Code** has **Definition**, **Use this code when**,
**Leave it out when** and **Examples**. Writing "leave it out when" is the single
most useful thing you can do for agreement between two coders.

## Keep it small and alive

* Review it often and reorganise it as you go (Saldaña, p. 24).
* A team needs one person who edits the master list (Saldaña, p. 34).
* A codebook is not an **index**: the codebook describes codes; an index points to
  where they were used (Saldaña, p. 25).
* **Codebook → History** takes a snapshot before every merge or delete. Add a
  note when you change the meaning of a code. That is part of your audit trail.
* **Codebook → Health** flags codes never used, used once, or without a
  definition.

## Share it

**Export** gives a file of names, definitions and hierarchy with no data in it.
Send it to a colleague so you both code the same way.
"""),

    ("New to this · Coding with a partner", """
# Coding with a partner (and what "agreement" means)

Working with another coder helps you notice what you assume, and shows whether
your codes can be used by someone else (Saldaña, pp. 34-36). It does *not* make
the analysis objective. It shows that two people can reach similar results
(Saldaña, p. 38).

## A workable routine

This follows the steps Creswell describes from a team project (ch. 10), and what
Saldaña suggests for teams (pp. 34-35):

1. **Everyone reads and codes the same few transcripts on their own.**
2. **Meet.** Compare codes and where you applied them. Write a first codebook with
   a definition for each code.
3. **Everyone codes the next few on their own** with that codebook.
4. **Compare.** Where you both coded a passage, did you give it the same code? A
   yes or a no each time.
5. **Talk about every disagreement.** Change the codebook, not just the codes.
6. **Repeat** until you agree most of the time, then write down how you did it.

## Decide what you are agreeing on

Creswell points out that this is often left vague (ch. 10). It could be
(a) the same **code names**, (b) the same **passages** picked out, or (c) the
same passages given the same codes. Choose, and say which you chose. In
QualSafe, the agreement screen compares each code, passage by passage.

## What number is good enough?

There is **no agreed standard**. For people who want a figure, Saldaña says
80-90% agreement is a common minimum (p. 35), and Creswell's team aimed for 80%
(ch. 10). Cohen's kappa corrects for agreement by chance. Creswell notes that a
plain percentage was enough for his team's report. Others skip numbers and rely
on discussion and an agreed final answer (Saldaña, p. 35).

QualSafe shows **kappa beside percent agreement, how common the code is, and a
warning when there are too few cases**. A code that almost nobody uses can have
high agreement and a low kappa at once, so never read kappa alone.

Silverman defines reliability as consistency: instances being put in the same
category by different people, or by the same person on different days (ch. 17).
He adds that you must **document your procedure** so others can judge it.

## When two coders disagree

**Reconcile** in a meeting and record the agreed answer as a separate coder.
QualSafe never changes either coder's original coding, so your agreement figure
can always be reproduced.
"""),

    ("New to this · Using the computer's suggestions", """
# Using the computer's suggestions wisely

QualSafe can suggest codes for survey answers by matching them to the themes you
listed. This can save hours. It can also tempt you to skip the part of the work
that produces understanding. Here is how to use it without losing that.

## What the books say

* Software organises your data and lets you look at it from more angles. It does
  not do the thinking. Clive Seale, who wrote the software chapter for Silverman,
  says "data management" would be a more honest name than "data analysis"
  (Silverman, ch. 16).
* Coding well means reading and rereading until you can nearly quote the data.
  Done properly it does not distance you from it (Saldaña, p. 38).
* If you are new, code a first sample by hand. Learn the method before the tool
  (Saldaña, p. 26; Silverman, Tip 40).
* Analysis begins with reading and memoing, before you cut the data into codes
  (Creswell, ch. 8).

## A safe order of work

1. **Read** a good share of the answers yourself.
2. **Write your start list** of themes and a one-line meaning for each.
3. **Code a sample by hand**, say 30 to 50 answers.
4. **Run the suggestions.** Treat them as a draft.
5. **Read the ones marked "Needs your review"**, and a random handful of the rest.
6. **Compare** your hand coding with the suggestions (Analysis → Agreement).
7. **Write a memo** on what the computer got wrong and what that taught you.
8. **Recode** where the suggestions showed you a weak code.

## Rules of thumb

* **Never report a number from suggestions you have not checked.**
* **A pile of similar answers is not a theme.** It is a place to start reading.
  You name it and say what it means.
* **If the computer and you disagree, read the passage.** It is often the most
  useful moment in the study.
* **Everything runs on your computer.** Your text is not uploaded.
"""),

    ("New to this · Checking your work", """
# Checking your work: is it believable?

Silverman uses *validity* to mean credibility: are the claims supported by the
data and sensible next to earlier research (ch. 17)? Creswell prefers the word
*validation*, a **process** of checking that your account is accurate, and asks
for **at least two** of the following strategies in any study (ch. 10).

## Eight strategies (Creswell, ch. 10) and where QualSafe helps

| Strategy | In plain words | In QualSafe |
|---|---|---|
| **Long engagement** | Spend enough time to understand the setting | (Your fieldwork) |
| **Triangulation** | Use several sources, methods or people to corroborate | Mix interviews, documents and surveys in one project; case-by-theme matrix |
| **Peer debriefing** | Someone plays devil's advocate | Share the codebook and audit trail |
| **Negative case analysis** | Look for evidence against your pattern, and report it | **Query** the passages for a code; read the ones that do not fit. **Analysis → Deviant cases** lists the passages furthest from how you used a code, as a reading order, not a verdict |
| **Clarifying bias** | Say what you bring to the study | **Codebook → Diary** → "My position" |
| **Member checking** | Take your draft findings back to participants | Share a Word table of themes (remove identifiers first) |
| **Thick description** | Describe enough that readers can judge fit | Keep quotes with their context |
| **External audit** | An outsider checks process and product | **Reports → Audit trail** |

## Silverman's five checks on your analysis (ch. 17)

He warns that triangulation and member validation are *not* a sure route to
truth, and offers five harder tests:

1. **Refutability:** try to prove yourself wrong; do not stop at the first
   explanation.
2. **Constant comparison:** keep comparing a new piece with the ones before it.
3. **Comprehensive data treatment:** account for *all* your data, not only the
   good quotes.
4. **Deviant case analysis:** study the cases that do not fit until you can
   explain them.
5. **Appropriate tabulation:** count only where counting has a reason (see
   *Counting*).

A good question to ask of any study, including yours: **did the author look at
the cases that did not fit?** (Silverman, Tip 46).

## Avoid the "few good examples" trap

Reporting only a handful of striking quotes and not saying why you chose them is
called **anecdotalism** (Silverman, ch. 17). Say how you chose each quote, show
how typical it is, and keep the original data available.

## Saturation

"We reached saturation" is a claim, not a fact. In QualSafe it means **no new
codes appeared** in the last sources you read. That is *code* saturation, not
*meaning* saturation, and it means little if your codes were all written in
advance. **Analysis → Saturation** shows the curve, with those warnings attached.

## Document what you did

Both Creswell and Silverman say the same thing: write down your procedure,
including what changed and what went wrong (Silverman, Tip 57). **Reports →
Methods appendix** drafts the technical part for you.
"""),

    ("New to this · Counting and numbers", """
# Counting, and what counts

The three books disagree here, and a beginner should know:

* **Creswell** does not usually report how many times a code appears. A count
  suggests that all codes weigh the same and can hide contradictory views (ch. 8).
  He may look at the numbers privately as a hint of interest.
* **Saldaña** warns that frequency is not always a trustworthy sign of what
  matters. Use a count as a way to explore, not as a measure (p. 201).
* **Silverman** accepts simple counts when they have a theoretical reason and,
  ideally, are based on the participants' own categories. They show a reader the
  whole of the data and guard against cherry-picking (ch. 17, Tips 44-45).

## A sensible rule

* Count to **decide where to read**, not to prove a point.
* If you report a count, say **what you counted and why**, and keep the quotes
  alongside.
* Use **% within a group** when groups differ in size.
* A rare code can be the most important one.

In QualSafe, every bar and every cell opens the passages behind it. Use that.
"""),

    ("New to this · Writing it up", """
# Writing it up

Writing is part of analysis, not the end of it. Start early. "You cannot begin
writing early enough" (Silverman quoting Wolcott, ch. 15). Even a short draft
shows you what you still do not know.

## What a reader looks for

* A **clear question** and a reason for it.
* An **approach** and an honest account of how you did it (Silverman, Tip 57; use
  active voice, say what really happened).
* **Evidence**: quotes with enough context that the reader can judge them. Silverman
  calls this **low-inference description**: give the words and the question that
  prompted them, not only your summary (ch. 17).
* **Cases that did not fit**, and what you made of them.
* **Your position** and the limits of the study (Creswell, ch. 10).
* A **few strong themes**, not a long list. "There is no whole story, only the
  story you want to tell" (Silverman, Tip 61, paraphrased).

## A simple outline for a short report

1. **Question and background** (one page)
2. **Approach and methods:** who, what data, how you coded, how you checked
3. **Findings:** one section per theme: the statement, two or three quotes,
   an account of how widespread, and the cases that do not fit
4. **What this means,** compared with earlier work
5. **Limits and next steps**

Creswell shows a typical outline for each of the five approaches (ch. 4).

## In QualSafe

* **Reports** produces the Word and Excel tables, the methods appendix and the
  audit trail.
* **Joint display** puts themes by subgroup beside a quote and your own
  statement. The statement is the part only you can write.
* Quotes are only included if you tick the box.
"""),

    ("New to this · The three books", """
# The three books behind this guide

Everything in **New to this** is a short paraphrase. The examples are invented.
Read the books themselves if you can. These are the editions used here.

## Saldaña · *The Coding Manual for Qualitative Researchers* (2nd ed., 2013, SAGE)

**Johnny Saldaña** is a professor of theatre at Arizona State University. He has
also written on longitudinal qualitative research, ethnotheatre and the
fundamentals of qualitative research.

**What it is for:** how to code. It explains what a code is, profiles 32 coding
methods with examples, and shows how to write analytic memos and move from first
to second cycle coding.

**Read first:** chapter 1, "An Introduction to Codes and Coding" (pp. 1-40) and
chapter 2, "Writing Analytic Memos" (pp. 41-57). Then look up your method in the
glossary (Appendix A, pp. 261-268).

## Creswell · *Qualitative Inquiry and Research Design: Choosing Among Five Approaches* (3rd ed., 2013, SAGE)

**John W. Creswell** is a professor of educational psychology at the University of
Nebraska-Lincoln. He is founding co-editor of the *Journal of Mixed Methods
Research* and has written widely on research design and mixed methods.

**What it is for:** designing a study. It compares five approaches (narrative,
phenomenology, grounded theory, ethnography, case study), explains the "data
analysis spiral", and sets out strategies for validation.

**Read first:** chapter 3 (designing a study), chapter 4 (the five approaches,
Table 4.1), chapter 8 (data analysis and representation) and chapter 10
(standards of validation).

## Silverman · *Doing Qualitative Research* (5th ed., 2017, SAGE)

**David Silverman** trained as a sociologist and taught at Goldsmiths, University of
London for 32 years. He is known for work on conversation and discourse analysis
and on medical consultations. Chapter 16 (on software) is by Clive Seale.

**What it is for:** carrying out a student project from start to finish, in a
straightforward voice, with 65 numbered "top tips".

**Read first:** chapter 2 (what qualitative research can and cannot do), 3
(focusing a project), 8 (research questions), 15 (developing data analysis), 17
(quality) and 18 (evaluating research).

## How to cite them in your methods section

* Saldaña, J. (2013). *The Coding Manual for Qualitative Researchers* (2nd ed.).
  SAGE.
* Creswell, J. W. (2013). *Qualitative Inquiry and Research Design: Choosing Among
  Five Approaches* (3rd ed.). SAGE.
* Silverman, D. (2017). *Doing Qualitative Research* (5th ed.). SAGE.

Cite the page or chapter for the idea you used, not just the book.
"""),

    ("New to this · Quick hints", """
# Quick hints (one line each)

**Before you start**
* Write your question on one page and keep it where you can see it (Saldaña, p. 21).
* Read about your approach, and say which one you use (Creswell, ch. 4).
* Do not defend a small sample; explain its logic (Silverman, Tip 31).

**While you code**
* Start small, then widen (Silverman, Tip 39).
* Write codes in full words (Saldaña, p. 21).
* Code a second, different participant early (Saldaña, p. 22).
* Do not over-theorise too soon (Silverman, ch. 15, after Becker).
* Notice what surprises you: that is where your assumptions sit (Saldaña, p. 22).

**While you think**
* Write a memo whenever something strikes you (Saldaña, p. 42).
* Talk it through with someone you trust ("shop talk", Saldaña, p. 206).
* Tabletop trick: write each category on a card and rearrange them until the
  structure feels right (Saldaña, p. 205).
* A code can be turned into a theme by finishing the sentence "X means..." or "X is..."
  (Saldaña, p. 205).

**While you check**
* Look for the case that does not fit (Silverman, Tip 46).
* Aim for at least two validation strategies (Creswell, ch. 10).
* Report what went wrong (Silverman, Tip 57).

**While you write**
* Keep a diary from day one (Silverman, Tip 58).
* Include only what works. There is no "whole story" (Silverman, Tip 61).
* Let quotes carry context: the question, and the reply around them.
"""),

]


# ---------------------------------------------------------------------------
# Glossary: the tool's word, the books' word, and what to watch for.
# ---------------------------------------------------------------------------

#: (term as you see it in QualSafe, what it means, the books' word, a note).
GLOSSARY: List[Tuple[str, str, str, str]] = [
    ("Code", "A short word or phrase naming what a passage is about or means.",
     "Code (all three).", "Saldaña p. 3."),
    ("Category", "A group of related codes.",
     "Category (Saldaña); Creswell uses it like \"theme\".",
     "Saldaña pp. 9-12; Creswell ch. 8."),
    ("Theme", "On the Survey screens: a topic name you give the computer to look "
     "for. In the books: a sentence stating what a pattern means.",
     "Provisional code or start list (Saldaña); theme (Creswell).",
     "The sentence-length theme is what you write yourself. Saldaña p. 14."),
    ("Passage", "The stretch of text you code.",
     "Datum, unit or excerpt (Saldaña).", "Saldaña p. 15."),
    ("Codebook", "Your list of codes with what each means.",
     "Codebook or code list.", "Saldaña pp. 24-25."),
    ("Memo", "A dated note to yourself about your thinking.",
     "Analytic memo (Saldaña); memoing (Creswell); research diary (Silverman).",
     "Saldaña ch. 2; Creswell ch. 8; Silverman Tip 58."),
    ("Diary", "A project-level memo: your position, question, problems, next steps.",
     "Memo or research diary.", "Silverman Tip 58."),
    ("Coder", "A person (or the computer) applying codes.",
     "Coder (all three).", "Saldaña p. 34."),
    ("Agreement", "How often two coders give the same passage the same code.",
     "Intercoder agreement (Saldaña, Creswell); reliability (Silverman).",
     "Saldaña p. 35; Creswell ch. 10; Silverman ch. 17."),
    ("Respondent details / attributes", "Facts about who said it: year, program, "
     "site.", "Attribute (Saldaña); the Code × Descriptor screen uses these.",
     "Saldaña p. 261 (Attribute Coding)."),
    ("Case", "A person, site or group treated as one unit.",
     "Case (Creswell, Silverman).", "Creswell ch. 4; Silverman ch. 13."),
    ("Suggested code", "A code the computer proposes for you to accept or change.",
     "No book term. The closest is Provisional or Hypothesis coding done by a person.",
     "A draft, not a finding."),
    ("Needs your review", "A suggestion the computer was not sure about.",
     "No book term.", "Read all of them."),
    ("Group of similar answers", "A pile of answers the computer found similar.",
     "No book term. Making sense of the pile is your Focused or Pattern coding.",
     "A place to start reading, not a theme."),
    ("Audit trail", "A record of what you did and why, in order.",
     "Audit trail (Lincoln and Guba, via Creswell ch. 10); memos as audit trail "
     "(Saldaña p. 50).", "Reports → Audit trail."),
    ("Deviant case", "A case that does not fit your pattern.",
     "Deviant case (Silverman); negative case (Creswell).",
     "Silverman ch. 17; Creswell ch. 10."),
    ("Saturation", "No new codes appearing as you add sources.",
     "Saturation (Silverman cautions).",
     "Code saturation is not meaning saturation."),
    ("Matrix / Joint display", "A grid of cases against themes with quotes in it.",
     "Matrix or display (Creswell ch. 8, after Miles and Huberman).",
     "Cells hold words, not numbers."),
    ("In-vivo", "A code that uses the participant's exact words.",
     "In Vivo Coding (Saldaña).", "Saldaña p. 264."),
]


def glossary_markdown() -> str:
    """The glossary as one Markdown table."""
    lines = ["# Words used here, and in the books", "",
             "| In QualSafe | What it means | The books' word | Note |",
             "|---|---|---|---|"]
    for term, meaning, books, note in GLOSSARY:
        lines.append(f"| **{term}** | {meaning} | {books} | {note} |")
    lines += [
        "",
        "Where a book and QualSafe use a word differently, the books are "
        "right about the *method*. Say which you mean when you write.",
    ]
    return "\n".join(lines)


#: Every guide section, in reading order, with the glossary slotted in.
def all_sections() -> List[Tuple[str, str]]:
    out = list(SECTIONS)
    # The glossary reads best just before the hints.
    out.insert(len(out) - 1, ("New to this · Words and what they mean",
                              glossary_markdown()))
    return out
