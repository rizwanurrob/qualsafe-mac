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
never describe a computer's output as a finding. The sentences follow the
ASD-STE100 writing rules (Simplified Technical English): short sentences, one
topic in each paragraph, active voice, commands in steps.

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
     "How do I relate to these people or this topic? What do I bring to it? "
     "What can I not see?"),
    ("My research question",
     "What do I want to find out? What does the data say so far? What does "
     "it not say?"),
    ("A code and why",
     "Why did I name or define a code this way? What did I decide about the "
     "borderline cases?"),
    ("Patterns forming",
     "Which codes seem to belong together? What can they add up to?"),
    ("How things connect",
     "How do the codes, categories and themes link? Does one cause, follow or "
     "contradict another?"),
    ("Ideas from reading",
     "What theory or earlier study does this remind me of? Does my data "
     "agree with it, or push back?"),
    ("A problem with the study",
     "What is going wrong or unclear? Who or what is missing?"),
    ("An ethical worry",
     "What did a participant tell me that I do not know how to handle? What must "
     "I not ask, not quote, or not share?"),
    ("What to do next",
     "Whom must I talk to? What must I read or collect next? What must I "
     "recode?"),
    ("Looking back",
     "What comes up again and again in my earlier notes? How did my "
     "thinking change?"),
    ("The write-up",
     "What is the story that I want to tell? Which quote opens it? How do I "
     "organise it?"),
]

# ---------------------------------------------------------------------------
# Sections. Titles start with "New to this ·" so they group in a contents list.
# ---------------------------------------------------------------------------

SECTIONS: List[Tuple[str, str]] = [

    ("New to this · Start here: the whole path", """
# New to qualitative research? Start here

Qualitative analysis means that you read what people said or wrote. You work out
what it means. You show your reasoning, so that another person can follow it. It
is slower than counting. It answers different questions: *how*, *what is it
like*, and *why do people say so*.

**You do not need to know this already.** Read this page. Then read the other
**New to this** sections when you reach that step.

## The path in nine steps

1. **Say what you want to find out.** Write one open question. An example is
   "What makes the first year hard for students who are first in their family
   at university?" The question can change as you learn (Creswell, ch. 3;
   Silverman, ch. 8). *In QualSafe:* keep the question in your first diary note
   (Codebook → Diary).
2. **Choose an approach.** Do you want the stories of one life? Do you want the
   shared meaning of an experience? Do you want a theory from the data? Do you
   want a culture? Do you want a single case? See **Pick an approach**.
3. **Plan the data and the ethics.** Who takes part? What did they agree to?
   How do you protect them (Silverman, ch. 4; Creswell, ch. 3)? *In QualSafe:*
   the import step scans for names and contact details. **Data** erases one
   participant when they ask.
4. **Read everything, and jot as you go.** Read all of it before you cut it into
   parts. Write short notes in the margin (Creswell, ch. 8; Saldaña, pp.
   19-21). *In QualSafe:* use **Documents**, or read the survey answers in the
   table.
5. **Make a first pass at coding.** Give each passage that matters a short
   label. See **Your first pass at coding**.
6. **Write memos as you go.** A memo is a note to yourself. It says what you
   think is happening and why. See **Memos and your research diary**.
7. **Recode, group, and name the themes.** Merge codes. Sort them into
   categories. State what the categories mean (Saldaña, ch. 4-5). *In
   QualSafe:* use **Codebook** (drag codes together), **Analysis**, and
   **Query**.
8. **Check your work.** Look for the cases that do not fit. Ask another person
   to look. Write down what you did. See **Checking your work**.
9. **Write it up.** Show your evidence. Say how you got there. Say what you
   could not find out. See **Writing it up**.

You go round steps 4 to 8 more than one time. This is normal. Creswell
describes the work as a spiral and not as a line (ch. 8).

## What QualSafe is and is not

* **QualSafe is** a workbench. You code text with it. You keep a codebook. You
  compare coders. You trace every number back to the words behind it.
* **QualSafe is not** an analyst. It cannot decide what your data means. When it
  suggests codes, the suggestions are drafts for you to check. See **Using the
  computer's suggestions**.
* **QualSafe fits best** with work that uses coding. Examples are thematic
  analysis, content analysis, case comparison, and the coding stages of grounded
  theory. It does not yet help you tell a life story in order. It does not help
  with the fine detail of conversation analysis. See **Pick an approach**.
"""),

    ("New to this · Codes, categories and themes", """
# Codes, categories and themes: three different things

Beginners often use these words as if they mean the same thing. The books use
them with care. A reviewer notices.

| Step | What it is | Example |
|---|---|---|
| **Passage** | The piece of text that you look at | "I almost dropped out because I couldn't pay rent." |
| **Code** | A short word or phrase that says what the passage is about or means | FINANCIAL STRAIN |
| **Category** | A group of related codes | Money pressures |
| **Theme** | A sentence that says what the pattern *means* | "For these students, money decides whether they stay, not just how they feel." |
| **Assertion or theory** | A claim that goes beyond this study | (later, and only if the data support it) |

**The key idea:** You code the data. You do not code *for* themes. A theme is an
*outcome* of coding and thinking. It is not a label that you put on a passage the
first time that you read it (Saldaña, p. 14). A code is usually a word or a short
phrase. It says *what is there*. A theme is a phrase or a sentence. It says *what
it means* (Saldaña, p. 14 and p. 267).

Creswell uses "category" and "theme" almost as the same word. He calls a theme a
broad unit that has several codes in it (ch. 8). So two books can seem to
disagree, but they mostly do not. Creswell describes the *level* (broad).
Saldaña describes the *kind of statement* (a sentence and not a label).
**Pick one way of speaking. Say which one you use. Keep to it.**

## What "theme" means in QualSafe

On the Survey screens, you give the computer short topic names to look for. The
screens call these names *themes*, because this is the everyday word. In the
words of Saldaña, they are **codes that you decided on in advance**. His name for
this is Provisional Coding, a "start list" (Saldaña, p. 266). The theme that is a
sentence is the theme that you write yourself, after you read the passages.
QualSafe asks for "your integration statement" or "one line per theme, in your
words". That is the real theme.

## How many?

There is no fixed number. These numbers give you an idea. Creswell likes a short
start list of five or six codes. It grows to no more than 25 to 30 categories. It
ends at five to seven themes (ch. 8). Other writers suggest 80 to 100 codes for a
typical education study. They suggest that a team handles 30 to 40 codes at one
time (Saldaña, p. 24). Saldaña advises you to keep the number of major themes to
a minimum. He advises you not to chase a standard figure (p. 24). Fewer, clearer
codes with good definitions are easier to apply and to defend.

## Name a code

* Use words that you can read in six months. Write them in full. Do not
  abbreviate them (Saldaña, p. 21).
* Use the **words of a participant** when they say it best. Put them in
  quotation marks. The name for this is In Vivo coding. In QualSafe, tick **In-vivo**
  before you apply the code.
* A **gerund** (an "-ing" word) names an action. Examples are NEGOTIATING and
  AVOIDING (Saldaña, p. 266).
* **Lumping** (one code for a big stretch) is faster. **Splitting** (many small
  codes) is finer but slower. Neither is wrong. Choose on purpose (Saldaña,
  pp. 22-23).
"""),

    ("New to this · Pick an approach", """
# Pick an approach (a quick outline of five)

An *approach* is a way to ask and answer one kind of question. The book of
Creswell has five approaches. You do not need to be an expert in one. You must
know which approach your study is most like. Say which one in your write-up
(Creswell, ch. 2-4; Table 4.1).

| | Narrative | Phenomenology | Grounded theory | Ethnography | Case study |
|---|---|---|---|---|---|
| **Focus** | The life of one person | What an experience is like | A theory built from the data | How a group shares culture | One case (or a few), in depth |
| **Good when** | You need to tell individual stories | You need the essence of a lived experience | You need an explanation, a process | You need to describe shared patterns | You need to understand a bounded case |
| **Unit** | One or a few people | Several people who share the experience | A process or action that involves many people | A group that shares a culture | An event, program, activity or person |
| **Data** | Interviews, documents | Mainly long interviews | Mainly interviews (Creswell suggests 20-60) | Mainly observation and interviews | Many sources |
| **Analysis** | Stories, turning points, a timeline | Significant statements, meanings, the "essence" | Open, axial and selective coding | Description, then themes about the group | Description of the case, then themes |
| **Result** | A story of a life | A description of the essence | A theory, often as a figure | A picture of how the group works | A detailed analysis of the case |

(These words adapt Creswell, Table 4.1. The table in the book is the
authority.)

## Which parts of QualSafe fit?

* **Good fit:** coding passages, building a codebook, comparing groups, and
  case-by-theme matrices. This suits thematic work, case studies, the
  descriptive side of ethnography, and theme statements in phenomenology.
* **Partial fit:** grounded theory. You can code, nest codes, and write memos.
  QualSafe does not guide you through axial coding or theoretical coding. Do
  that thinking in your memos.
* **Not covered:** narrative ordering of a life story. Conversation analysis is
  also not covered. It depends on a transcript of pauses and overlaps
  (Silverman, ch. 17).

## Is qualitative research the right choice?

If you mainly need to count how many people did or thought something, a survey
can be better. Qualitative methods are worth their cost when your question is
about how and why. They are also worth their cost when you do not yet know the
right questions (Silverman, ch. 2; his Tip 32). The **Charts** activity is for
counting.

## Hint

Do not make a first study too complicated. Use few cases and few methods, and
look at them well. "The best research says a lot about a little" (Silverman, Tip
48).
"""),

    ("New to this · Your first pass at coding", """
# Your first pass at coding

Coding is the move from "I have a lot of text" to "I know what is in it". It is
interpretation. It is not measurement. Two people code the same passage in
different ways, and both can be reasonable (Saldaña, pp. 6-8, 38).

## Before you code

1. **Read all of it one time.** Do not stop to code yet (Creswell, ch. 8).
2. **Keep your question in front of you.** Saldaña suggests that you keep one
   page beside you. It has your research question and your goals (p. 21).
3. **Jot your first thoughts** in the margin. They are not final codes. They are
   only ideas (Saldaña, pp. 19-20).
4. **Ask yourself as you read:** *What strikes me? What surprised me? What
   disturbed me?* The answers show your assumptions (Saldaña, p. 22).

## Then code

Choose a first-cycle method that fits your question. These are the methods that
beginners meet most:

| Method | It asks | Short example | In QualSafe |
|---|---|---|---|
| **Descriptive** | What topic is this about? (a noun) | HOUSING | Add a code. Press its number key |
| **In Vivo** | What words did the person use? | "STOPPED CARING" | Tick **In-vivo** |
| **Process** | What action is happening? (an "-ing" word) | SEEKING HELP | Add a code in -ing form |
| **Emotion** | What feeling is here? | RELIEF, SHAME | Add a code |
| **Values** | What does the person value or believe? How do they feel about it? | VALUES INDEPENDENCE | Add a code |
| **Versus** | Which two things are in conflict? | CAREER VS. FAMILY | Add a code |
| **Provisional** | What do I expect to find? (a start list) | FINANCIAL STRAIN | Survey → Themes list |
| **Structural** | Which part answers my question? | one code for each interview question | Survey with a question column |
| **Holistic** | What is this whole piece about? | one code for a long answer | Select the whole answer |
| **Attribute** | Who said it? Which site? Which year? | FIRST-GENERATION | Respondent details / attributes |

You can **mix** methods in a first pass. Choose them on purpose. Tidy them in a
second pass (Saldaña, p. 188, "Eclectic Coding").

## First pass, second pass

The first cycle is rough and fast. The **second cycle** recodes. Merge codes,
drop some, rename others, and sort them into categories (Saldaña, pp. 10-12, ch.
4-5). You do not only code data. You *re*-code it. Expect to do this more than
one time (Saldaña, p. 206).

## Hints

* **Begin small.** Code one interview or twenty answers with great care. Test
  your codes on a second, different piece of data. See if they hold (Saldaña, p.
  22; Silverman, Tip 39).
* **Code the strange parts too.** If you code only what fits, you do not see
  what does not fit (Saldaña, p. 16).
* **Look at the ordinary answers.** Do not look only at the dramatic answers
  (Silverman, ch. 15).
* **Code by hand first** if you are new. Learn the method. Then learn the
  software. Do one at a time (Saldaña, p. 26; Silverman, Tip 40).
"""),

    ("New to this · Memos and your research diary", """
# Memos and your research diary

A **memo** is a note to yourself while you analyse. This is where the thinking
happens. A code is only a label until you write about what it means (Saldaña,
p. 41). Memos are also your **audit trail**. They show a reader how your ideas
developed (Saldaña, p. 50).

Silverman says the same thing in plainer words. Keep a research diary from day
one. It becomes the raw material for your methods chapter (Silverman, Tip 58).

## How to write a memo

* **Write it at once** when an idea comes. Do not trust your memory (Saldaña, p. 42).
* **Do not tidy it.** Write as if you write a letter to a friend. Do not write
  as if you write a paper (Saldaña, p. 42).
* **Put a date and a title on it,** so that you can find it later (Saldaña, p. 42).
* **Do not summarise the data.** Reflect on it.
* **Write about problems too.** If you write down a muddle, you can explain it.

## What to write about (pick one)

""" + "\n".join(f"* **{t}.** {q}" for t, q in MEMO_TOPICS) + """

*(These prompts adapt the eleven kinds of reflection in Saldaña, pp.
43-49. The same prompts show when you add a diary note in QualSafe.)*

## A short example

> **12 March · A code and why: FINANCIAL STRAIN.** First, I called this MONEY. But
> the code took in everything. Two students mention cost with no hardship. So now I
> use FINANCIAL STRAIN only when a person says that they cannot pay for something.
> I must check the first six interviews again.

## In QualSafe

* Use **Codebook → Code → Memos on this code** for notes about one code.
* Use **Codebook → Diary** for notes about the project. Write about your
  position, your question, problems, ethics, and next steps.
* **Reports → Audit trail** has the *record* of your memos. It has the *text* of
  your memos only if you tick the box. A memo can quote a participant.

## A caution about drafts from a computer

A memo makes *you* think. A draft from a computer skips that step. Write your
own memos.
"""),

    ("New to this · The codebook", """
# The codebook

A **codebook** is the list of your codes. It says what each code means. It helps
another person (or you, next month) to apply a code in the same way (Saldaña, pp.
24-25).

## What goes in an entry

Bernard and Ryan, cited by Saldaña (p. 25), suggest that each entry has these
items:

* a **short name** (the code itself);
* a **fuller description** of one to three sentences;
* **when to use it** (inclusion);
* **when to leave it out** (exclusion);
* a **typical example** and, if you can, an **unusual example** that still counts;
* a **close-but-no** example. It looks like the code, but it must not receive the code.

*In QualSafe:* **Codebook → Code** has **Definition**, **Use this code when**,
**Leave it out when**, and **Examples**. Write "leave it out when". This is the
most useful thing that you can do for agreement between two coders.

## Keep it small and alive

* Review the codebook often. Reorganise it as you go (Saldaña, p. 24).
* A team needs one person who edits the master list (Saldaña, p. 34).
* A codebook is not an **index**. The codebook describes the codes. An index
  points to the places where you use the codes (Saldaña, p. 25).
* **Codebook → History** takes a snapshot before every merge or delete. Add a
  note when you change the meaning of a code. This is part of your audit trail.
* **Codebook → Health** flags codes that have no use, one use, or no definition.

## Share it

**Export** gives a file of names, definitions, and hierarchy. The file has no
data in it. Send it to a colleague, so that you both code in the same way.
"""),

    ("New to this · Coding with a partner", """
# Coding with a partner (and what "agreement" means)

A second coder helps you to see what you assume. A second coder also shows if
another person can use your codes (Saldaña, pp. 34-36). A second coder does *not*
make the analysis objective. A second coder shows that two people can reach
similar results (Saldaña, p. 38).

## A routine that works

This routine follows the steps that Creswell describes from a team project (ch.
10). It also follows what Saldaña suggests for teams (pp. 34-35):

1. **Each person reads and codes the same few transcripts alone.**
2. **Meet.** Compare the codes and the places where you applied them. Write a
   first codebook with a definition for each code.
3. **Each person codes the next few transcripts alone** with that codebook.
4. **Compare.** Where you both coded a passage, did you give it the same code?
   Answer yes or no each time.
5. **Talk about every disagreement.** Change the codebook. Do not only change the
   codes.
6. **Repeat** until you agree most of the time. Then write down how you did it.

## Decide what you agree on

Creswell points out that people often leave this unclear (ch. 10). You can
agree on one of three things. You can agree on (a) the same **code names**. You
can agree on (b) the same **passages** that you pick out. You can agree on (c)
the same passages with the same codes. Choose one. Say which one you chose. In
QualSafe, the agreement screen compares each code, passage by passage.

## What number is good enough?

There is **no agreed standard**. Some people want a figure. Saldaña says that
80-90% agreement is a common minimum (p. 35). The team of Creswell aimed for 80%
(ch. 10). Cohen's kappa corrects for agreement by chance. Creswell notes that a
plain percentage was enough for the report of his team. Other people do not use
numbers. They use discussion and an agreed final answer (Saldaña, p. 35).

QualSafe shows **kappa next to percent agreement, how common the code is, and a
warning when there are too few cases**. A code that almost nobody uses can have
high agreement and a low kappa at the same time. So never read kappa alone.

Silverman defines reliability as consistency. Different people put instances in
the same category. Or the same person puts instances in the same category on
different days (ch. 17). He adds that you must **document your procedure**, so
that others can judge it.

## When two coders disagree

**Reconcile** in a meeting. Record the agreed answer as a separate coder.
QualSafe never changes the original coding of either coder. So you can always
reproduce your agreement figure.
"""),

    ("New to this · Using the computer's suggestions", """
# Using the computer's suggestions wisely

QualSafe can suggest codes for survey answers. It matches the answers to the
themes that you listed. This can save hours. It can also make you skip the part
of the work that gives understanding. This page tells you how to use the
suggestions and keep that understanding.

## What the books say

* Software organises your data. It lets you look at the data from more angles.
  It does not do the thinking. Clive Seale wrote the software chapter for
  Silverman. He says that "data management" is a more honest name than "data
  analysis" (Silverman, ch. 16).
* Good coding means that you read and reread until you can nearly quote the
  data. If you do it properly, it does not put distance between you and the data
  (Saldaña, p. 38).
* If you are new, code a first sample by hand. Learn the method before you learn
  the tool (Saldaña, p. 26; Silverman, Tip 40).
* Analysis begins with reading and memoing. It begins before you cut the data
  into codes (Creswell, ch. 8).

## A safe order of work

1. **Read** a good share of the answers yourself.
2. **Write your start list** of themes. Write a one-line meaning for each theme.
3. **Code a sample by hand.** Use 30 to 50 answers.
4. **Run the suggestions.** Treat them as a draft.
5. **Read the answers marked "Needs your review".** Also read a random few of the
   other answers.
6. **Compare** your hand coding with the suggestions (Analysis → Agreement).
7. **Write a memo** about what the computer got wrong and what you learned.
8. **Recode** where the suggestions showed you a weak code.

## Rules of thumb

* **Never report a number from suggestions that you did not check.**
* **A pile of similar answers is not a theme.** It is a place to start reading.
  You name it. You say what it means.
* **If the computer and you disagree, read the passage.** This is often the most
  useful moment in the study.
* **Everything runs on your computer.** QualSafe does not upload your text.
"""),

    ("New to this · Checking your work", """
# Checking your work: is it believable?

Silverman uses *validity* to mean credibility. Does the data support the claims?
Do the claims make sense next to earlier research (ch. 17)? Creswell prefers the
word *validation*. It is a **process** to check that your account is accurate.
He asks for **at least two** of the strategies below in any study (ch. 10).

## Eight strategies (Creswell, ch. 10) and where QualSafe helps

| Strategy | In plain words | In QualSafe |
|---|---|---|
| **Long engagement** | Spend enough time to understand the setting | (Your fieldwork) |
| **Triangulation** | Use several sources, methods or people to confirm a result | Mix interviews, documents and surveys in one project. Use the case-by-theme matrix |
| **Peer debriefing** | Someone plays devil's advocate | Share the codebook and the audit trail |
| **Negative case analysis** | Look for evidence against your pattern. Report it | **Query** the passages for a code. Read the passages that do not fit. **Analysis → Deviant cases** lists the passages that are furthest from your use of a code. It gives a reading order, not a verdict |
| **Clarifying bias** | Say what you bring to the study | **Codebook → Diary** → "My position" |
| **Member checking** | Take your draft findings back to participants | Share a Word table of themes (first remove identifiers) |
| **Thick description** | Describe enough, so that readers can judge the fit | Keep quotes with their context |
| **External audit** | A person from outside checks the process and the product | **Reports → Audit trail** |

## The five checks of Silverman on your analysis (ch. 17)

He warns that triangulation and member validation are *not* a sure way to the
truth. He offers five harder tests:

1. **Refutability:** Try to prove that you are wrong. Do not stop at the first
   explanation.
2. **Constant comparison:** Compare each new piece with the pieces before it.
3. **Comprehensive data treatment:** Account for *all* your data. Do not use
   only the good quotes.
4. **Deviant case analysis:** Study the cases that do not fit. Continue until
   you can explain them.
5. **Appropriate tabulation:** Count only where you have a reason to count. See
   *Counting*.

Ask this question of any study, including yours: **did the author look at the
cases that did not fit?** (Silverman, Tip 46).

## Avoid the "few good examples" trap

Some writers report only a few striking quotes and do not say why they chose
them. The name for this is **anecdotalism** (Silverman, ch. 17). Say how you chose each
quote. Show how typical it is. Keep the original data available.

## Saturation

"We reached saturation" is a claim. It is not a fact. In QualSafe it means that
**no new codes appeared** in the last sources that you read. That is *code*
saturation. It is not *meaning* saturation. It means little if you wrote all the
codes in advance. **Analysis → Saturation** shows the curve with these warnings.

## Document what you did

Creswell and Silverman both say the same thing. Write down your procedure. Write
what changed and what went wrong (Silverman, Tip 57). **Reports → Methods
appendix** drafts the technical part for you.
"""),

    ("New to this · Counting and numbers", """
# Counting, and what counts

The three books do not agree on this subject. A beginner must know this:

* **Creswell** does not usually report how many times a code appears. A count
  suggests that all codes have the same weight. It can hide views that
  contradict each other (ch. 8). He can look at the numbers in private as a
  hint of interest.
* **Saldaña** warns that frequency is not always a reliable sign of what
  matters. Use a count to explore. Do not use it as a measure (p. 201).
* **Silverman** accepts simple counts when they have a theoretical reason. It is
  best when they use the categories of the participants. Counts show a reader
  all of the data. They guard against cherry-picking (ch. 17, Tips 44-45).

## A sensible rule

* Count to **decide where to read**. Do not count to prove a point.
* If you report a count, say **what you counted and why**. Keep the quotes next to
  it.
* Use **% within a group** when the groups have different sizes.
* A rare code can be the most important code.

In QualSafe, every bar and every cell opens the passages behind it. Use this.
"""),

    ("New to this · Writing it up", """
# Writing it up

Writing is part of analysis. It is not the end of analysis. Start early. "You
cannot begin writing early enough" (Silverman quoting Wolcott, ch. 15). Even a
short draft shows you what you do not yet know.

## What a reader looks for

* A **clear question** and a reason for it.
* An **approach** and an honest account of how you did the work (Silverman, Tip
  57). Use the active voice. Say what really happened.
* **Evidence:** quotes with enough context for the reader to judge them. Silverman
  calls this **low-inference description**. Give the words and the question that
  caused them. Do not give only your summary (ch. 17).
* **Cases that did not fit,** and what you thought about them.
* **Your position** and the limits of the study (Creswell, ch. 10).
* **A few strong themes.** Do not give a long list. "There is no whole story, only
  the story you want to tell" (Silverman, Tip 61, paraphrased).

## A simple outline for a short report

1. **Question and background** (one page)
2. **Approach and methods:** who, what data, how you coded, how you checked
3. **Findings:** one section for each theme. Give the statement, two or three
   quotes, an account of how widespread the theme is, and the cases that do not
   fit.
4. **What this means,** compared with earlier work
5. **Limits and next steps**

Creswell shows a typical outline for each of the five approaches (ch. 4).

## In QualSafe

* **Reports** makes the Word and Excel tables, the methods appendix, and the
  audit trail.
* **Joint display** puts themes by subgroup next to a quote and your own
  statement. Only you can write the statement.
* QualSafe includes quotes only if you tick the box.
"""),

    ("New to this · The three books", """
# The three books behind this guide

Everything in **New to this** is a short paraphrase. We invented the examples. Read the books themselves if you can. These are the editions that this guide uses.

## Saldaña · *The Coding Manual for Qualitative Researchers* (2nd ed., 2013, SAGE)

**Johnny Saldaña** is a professor of theatre at Arizona State University. He also
wrote about longitudinal qualitative research, ethnotheatre, and the fundamentals
of qualitative research.

**What it is for:** how to code. It explains what a code is. It profiles 32
coding methods with examples. It shows how to write analytic memos and how to move
from first-cycle coding to second-cycle coding.

**Read first:** chapter 1, "An Introduction to Codes and Coding" (pp. 1-40), and
chapter 2, "Writing Analytic Memos" (pp. 41-57). Then look up your method in the
glossary (Appendix A, pp. 261-268).

## Creswell · *Qualitative Inquiry and Research Design: Choosing Among Five Approaches* (3rd ed., 2013, SAGE)

**John W. Creswell** is a professor of educational psychology at the University of
Nebraska-Lincoln. He is a founding co-editor of the *Journal of Mixed Methods
Research*. He wrote widely on research design and mixed methods.

**What it is for:** how to design a study. It compares five approaches (narrative,
phenomenology, grounded theory, ethnography, case study). It explains the "data
analysis spiral". It gives strategies for validation.

**Read first:** chapter 3 (designing a study), chapter 4 (the five approaches,
Table 4.1), chapter 8 (data analysis and representation), and chapter 10
(standards of validation).

## Silverman · *Doing Qualitative Research* (5th ed., 2017, SAGE)

**David Silverman** trained as a sociologist. He taught at Goldsmiths, University
of London for 32 years. He is known for his work on conversation analysis,
discourse analysis, and medical consultations. Clive Seale wrote chapter 16 (on
software).

**What it is for:** how to do a student project from start to finish. It uses a
straightforward voice. It has 65 numbered "top tips".

**Read first:** chapter 2 (what qualitative research can and cannot do), chapter 3
(focusing a project), chapter 8 (research questions), chapter 15 (developing data
analysis), chapter 17 (quality), and chapter 18 (evaluating research).

## How to cite them in your methods section

* Saldaña, J. (2013). *The Coding Manual for Qualitative Researchers* (2nd ed.).
  SAGE.
* Creswell, J. W. (2013). *Qualitative Inquiry and Research Design: Choosing Among
  Five Approaches* (3rd ed.). SAGE.
* Silverman, D. (2017). *Doing Qualitative Research* (5th ed.). SAGE.

Cite the page or the chapter for the idea that you used. Do not cite only the book.
"""),

    ("New to this · Quick hints", """
# Quick hints (one line each)

**Before you start**
* Write your question on one page. Keep it where you can see it (Saldaña, p. 21).
* Read about your approach. Say which one you use (Creswell, ch. 4).
* Do not defend a small sample. Explain its logic (Silverman, Tip 31).

**While you code**
* Start small. Then widen the work (Silverman, Tip 39).
* Write codes in full words (Saldaña, p. 21).
* Code a second, different participant early (Saldaña, p. 22).
* Do not make theories too soon (Silverman, ch. 15, after Becker).
* Notice what surprises you. Your assumptions are there (Saldaña, p. 22).

**While you think**
* Write a memo each time that something strikes you (Saldaña, p. 42).
* Talk about it with a person that you trust ("shop talk", Saldaña, p. 206).
* Tabletop trick: Write each category on a card. Move the cards until the
  structure feels right (Saldaña, p. 205).
* To turn a code into a theme, finish the sentence "X means..." or "X is..."
  (Saldaña, p. 205).

**While you check**
* Look for the case that does not fit (Silverman, Tip 46).
* Use at least two validation strategies (Creswell, ch. 10).
* Report what went wrong (Silverman, Tip 57).

**While you write**
* Keep a diary from day one (Silverman, Tip 58).
* Include only what works. There is no "whole story" (Silverman, Tip 61).
* Let quotes carry their context: the question, and the reply around the quote.
"""),

]


# ---------------------------------------------------------------------------
# Glossary: the tool's word, the books' word, and what to watch for.
# ---------------------------------------------------------------------------

#: (term as you see it in QualSafe, what it means, the books' word, a note).
GLOSSARY: List[Tuple[str, str, str, str]] = [
    ("Code", "A short word or phrase that names what a passage is about or means.",
     "Code (all three).", "Saldaña p. 3."),
    ("Category", "A group of related codes.",
     'Category (Saldaña). Creswell uses it like "theme".',
     "Saldaña pp. 9-12; Creswell ch. 8."),
    ("Theme", "On the Survey screens: a topic name that you give the computer to look "
     "for. In the books: a sentence that states what a pattern means.",
     "Provisional code or start list (Saldaña); theme (Creswell).",
     "You write the theme that is a sentence yourself. Saldaña p. 14."),
    ("Passage", "The piece of text that you code.",
     "Datum, unit or excerpt (Saldaña).", "Saldaña p. 15."),
    ("Codebook", "Your list of codes with the meaning of each code.",
     "Codebook or code list.", "Saldaña pp. 24-25."),
    ("Memo", "A dated note to yourself about your thinking.",
     "Analytic memo (Saldaña); memoing (Creswell); research diary (Silverman).",
     "Saldaña ch. 2; Creswell ch. 8; Silverman Tip 58."),
    ("Diary", "A memo for the whole project: your position, question, problems, next steps.",
     "Memo or research diary.", "Silverman Tip 58."),
    ("Coder", "A person (or the computer) that applies codes.",
     "Coder (all three).", "Saldaña p. 34."),
    ("Agreement", "How often two coders give the same code to the same passage.",
     "Intercoder agreement (Saldaña, Creswell); reliability (Silverman).",
     "Saldaña p. 35; Creswell ch. 10; Silverman ch. 17."),
    ("Respondent details / attributes", "Facts about who said it: year, program, "
     "site.", "Attribute (Saldaña). The By group screen uses these.",
     "Saldaña p. 261 (Attribute Coding)."),
    ("Case", "A person, site, or group that you treat as one unit.",
     "Case (Creswell, Silverman).", "Creswell ch. 4; Silverman ch. 13."),
    ("Suggested code", "A code that the computer proposes. You accept it or change it.",
     "No book term. The closest is Provisional or Hypothesis coding by a person.",
     "A draft, not a finding."),
    ("Needs your review", "A suggestion that the computer was not sure about.",
     "No book term.", "Read all of them."),
    ("Group of similar answers", "A pile of answers that the computer found similar.",
     "No book term. When you make sense of the pile, you do Focused or Pattern coding.",
     "A place to start reading, not a theme."),
    ("Audit trail", "A record of what you did and why, in order.",
     "Audit trail (Lincoln and Guba, via Creswell ch. 10); memos as audit trail "
     "(Saldaña p. 50).", "Reports → Audit trail."),
    ("Deviant case", "A case that does not fit your pattern.",
     "Deviant case (Silverman); negative case (Creswell).",
     "Silverman ch. 17; Creswell ch. 10."),
    ("Saturation", "No new codes appear as you add sources.",
     "Saturation (Silverman warns about it).",
     "Code saturation is not meaning saturation."),
    ("Matrix / Joint display", "A grid of cases against themes with quotes in it.",
     "Matrix or display (Creswell ch. 8, after Miles and Huberman).",
     "The cells hold words, not numbers."),
    ("In-vivo", "A code that uses the exact words of the participant.",
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
        "Sometimes a book and QualSafe use a word in different ways. The books are "
        "right about the *method*. Say which meaning you use when you write.",
    ]
    return "\n".join(lines)


#: Every guide section, in reading order, with the glossary slotted in.
def all_sections() -> List[Tuple[str, str]]:
    out = list(SECTIONS)
    # The glossary reads best just before the hints.
    out.insert(len(out) - 1, ("New to this · Words and what they mean",
                              glossary_markdown()))
    return out
