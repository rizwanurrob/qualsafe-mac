# Glossary

The plain word is first. The technical term is second. QualSafe uses the plain word on the screen. This page tells you what each plain word means.

**Theme** (also called a code). A short label for something that people say. An example is "Money worries". A set of themes is your codebook.

**Codebook.** Your list of codes. Each code has a name. Ideally, each code also has a short definition of what counts.

**Passage** (technical: excerpt). A piece of text that you code. It is a sentence in an interview, or one survey answer.

**Coder** (technical: rater). A person or the computer that applies codes. Agreement needs at least two coders.

**Respondent details** (technical: descriptors or attributes). Columns that give facts about a person. An example is class year. They let you compare groups.

**Suggested code** (technical: zero-shot classification). A code that QualSafe proposes from the name of the theme only. QualSafe has no coded examples to learn from.

**Needs your review** (technical: uncertain). An answer that QualSafe was not sure about. Read these answers first.

**Agreement** (technical: Cohen's kappa, written κ). It shows how far two coders agree, after you remove the agreement that chance gives. QualSafe reports it for each code separately. A higher number is better. Many researchers look for 0.6 or more. The correct limit depends on your field and your question.

**Same answer %** (technical: percent agreement). The share of answers that two coders coded the same way for a code. For a rare code, this number looks high even when the coders disagree on every use of the code. For this reason, QualSafe also shows agreement.

**How common** (technical: prevalence). The share of answers that a code applies to.

**Quick preview.** A trial run on the first 50 answers. It writes nothing to your project.

**Written codebook** (technical: structured coding). A way of coding. For each code, you write what counts and what does not count. QualSafe reads each answer against your text. It runs on your own computer.

**Analysis engine.** The extra software that does the heavy computing. It is several gigabytes. You install it separately. Reading, hand coding, searching, and reports work without it.

**Local language model** (technical: LLM). An optional program on your own computer. QualSafe uses it for a few extra suggestions. Nothing goes to the internet.

**Offline mode.** QualSafe works without the internet. It is on when the status bar says so. Only a download that you ask for uses the internet.

**Privacy check** (technical: PII scan). A scan for names, email addresses, and numbers that can identify a person. It is a rough check and it can miss things. Also look through the file yourself.

**Decision tree.** A set of yes-or-no questions that sorts people into groups. You read it from the top to the bottom.

**Random forest.** Many decision trees that vote together. It is usually more accurate than one tree. It is harder to read.

**p-value.** A number that shows how surprising your result is if nothing is really happening. It has this meaning only if you chose what to test before you looked at the data.

**Lasso.** A way to predict an outcome. It keeps only the details that help. It shrinks the other details to nothing. It gives no p-values and no ranges. The data chose which details to keep.

**Double lasso.** A way to estimate the effect of one thing on an outcome, while it allows for many other details. It gives an estimate with a range (a confidence interval). The range stays reliable although the data picked which details to allow for. It gives no p-values.

**Folds** (technical: cross-validation). QualSafe splits the data into parts. Each part has a turn to be left out, to test the result.

**Seed.** A number that makes the chance parts of an analysis repeat in the same way.
