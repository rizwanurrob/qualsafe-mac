# Glossary

The plain word comes first and the technical term second. Where QualSafe uses the plain word on screen, this is where to find what it stands for.

**Theme** (also called a code). A short label for something people say, such as "Money worries". A set of them is your codebook.

**Codebook.** Your list of codes, each with a name and, ideally, a short definition of what counts.

**Passage** (technical: excerpt). A stretch of text that is coded: a sentence in an interview, or one survey answer.

**Coder** (technical: rater). A person, or the computer, who applies codes. Agreement needs at least two.

**Respondent details** (technical: descriptors or attributes). Columns that say something about the person, such as class year. They let you compare groups.

**Suggested code** (technical: zero-shot classification). A code QualSafe proposes from the theme's name alone, with no coded examples to learn from.

**Needs your review** (technical: uncertain). An answer where QualSafe was not confident. These are the ones to read first.

**Agreement** (technical: Cohen's kappa, written κ). How far two coders agree beyond what chance alone would give. Reported for each code separately. Higher is better. Many researchers look for 0.6 or more, but the right bar depends on your field and your question.

**Same answer %** (technical: percent agreement). The share of answers two coders coded the same way for a code. It looks high for a rare code even when coders disagree about every use of it, which is why agreement is shown as well.

**How common** (technical: prevalence). The share of answers a code applies to.

**Quick preview.** A trial run on the first 50 answers. It writes nothing to your project.

**Written codebook** (technical: structured coding). Coding where you write what counts and what does not for each code, and QualSafe reads each answer against it. It runs on your own computer.

**Analysis engine.** The extra software that does the heavy computing. It is several gigabytes and is installed separately. Reading, hand coding, searching and reports work without it.

**Local language model** (technical: LLM). An optional program on your own computer, used for a few extra suggestions. Nothing is sent to the internet.

**Offline mode.** QualSafe working without the internet. It is on whenever the status bar says so. The only thing that ever uses the internet is a download you ask for.

**Privacy check** (technical: PII scan). A scan for names, email addresses and numbers that could identify someone. It is a rough check and can miss things, so look through the file yourself too.

**Decision tree.** A set of yes-or-no questions that sorts people into groups, which you can read from top to bottom.

**Random forest.** Many decision trees voting together. Usually more accurate than one tree, and harder to read.

**p-value.** A number for how surprising your result would be if there were really nothing going on. It only means what it says if you chose what to test before you looked at the data.

**Lasso.** A way to predict an outcome that keeps only the details that help and shrinks the rest to nothing. It reports no p-values and no ranges, because the data chose which details to keep.

**Double lasso.** A way to estimate the effect of one thing on an outcome while allowing for many other details. It gives an estimate with a range (a confidence interval) that stays trustworthy even though the data picked which details to allow for. It does not report p-values.

**Folds** (technical: cross-validation). The data is split into parts, and each part takes a turn at being left out to test the result.

**Seed.** A number that makes the chance parts of an analysis repeatable.
