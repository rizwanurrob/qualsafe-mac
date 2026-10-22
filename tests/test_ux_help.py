"""core/ux/help: every step has an intro and an article, in plain words (V8_PLAN.md section 6)."""

from __future__ import annotations

import re

import pytest

from core.ux import activities, help as shared_help, words

STEPS = shared_help.steps()


def test_there_is_a_step_list_to_check():
    assert len(STEPS) == sum(len(a.steps) for a in activities.ACTIVITIES) >= 14


@pytest.mark.parametrize("activity_key,step_key", STEPS)
def test_every_step_has_a_one_line_intro(activity_key, step_key):
    intro = shared_help.intro(activity_key, step_key)
    assert intro.strip() and "\n" not in intro and len(intro) <= 160


@pytest.mark.parametrize("activity_key,step_key", STEPS)
def test_every_step_has_an_article_with_a_title(activity_key, step_key):
    text = shared_help.article(activity_key, step_key)
    assert text, f"no article for {activity_key}-{step_key}"
    assert text.startswith("# ") and shared_help.title_of(text)
    assert "**What this step is for.**" in text
    assert 60 <= len(text.split()) <= 400, "an article should be short"


def test_no_article_is_missing_and_none_is_left_over():
    assert shared_help.missing() == []
    on_disk = {p.stem for p in shared_help.STEPS_DIR.glob("*.md")}
    assert on_disk == {shared_help.article_id(a, s) for a, s in STEPS}, "a file with no step"


@pytest.mark.parametrize("activity_key,step_key", STEPS)
def test_articles_use_the_plain_words(activity_key, step_key):
    text = shared_help.article(activity_key, step_key)
    assert words.find_never(text) == []
    assert words.find_replace(text) == []


def test_articles_name_no_internal_files_or_code():
    for activity_key, step_key in STEPS:
        text = shared_help.article(activity_key, step_key)
        assert not re.search(r"\.py\b|\bcore/|\bQt\b|Streamlit|\bAPI\b|`", text), (activity_key, step_key)


def test_articles_do_not_promise_what_the_locked_rules_forbid():
    """Agreement is per code; the privacy check is asked every time; nothing is uploaded."""
    surveys_code = shared_help.article("surveys", "code")
    assert "each theme separately" in surveys_code and "never as one overall score" in surveys_code
    assert "never remembers" in shared_help.article("surveys", "load")
    assert "never remembered" in shared_help.article("interviews", "add")


def test_the_index_has_one_row_per_step():
    rows = shared_help.index()
    assert [r["id"] for r in rows] == [shared_help.article_id(a, s) for a, s in STEPS]
    assert all(r["title"] and r["intro"] for r in rows)


# -- tasks, glossary, troubleshooting (item 4.4) -------------------------------------------

TASKS = shared_help.task_ids()


def test_there_are_task_articles_and_none_is_left_over():
    assert len(TASKS) >= 8
    on_disk = {p.stem for p in shared_help.TASKS_DIR.glob("*.md")}
    assert on_disk == set(TASKS)


@pytest.mark.parametrize("task_id", TASKS)
def test_a_task_is_a_question_a_researcher_would_ask(task_id):
    text = shared_help.task(task_id)
    assert shared_help.title_of(text).startswith("How do I") and shared_help.title_of(text).endswith("?")
    assert 40 <= len(text.split()) <= 260
    assert words.find_never(text) == [] and words.find_replace(text) == []
    assert not re.search(r"\.py\b|\bcore/|\bQt\b|Streamlit|\bAPI\b|`", text)


def _outside_brackets(text: str) -> str:
    return re.sub(r"\([^)]*\)", "", text)


def test_the_glossary_puts_the_plain_word_first():
    entries = shared_help.glossary_entries()
    assert len(entries) >= 15
    terms = [t for t, _ in entries]
    assert len(terms) == len(set(terms))
    # technical terms appear only in brackets, after the plain one
    assert words.find_replace(_outside_brackets(shared_help.glossary())) == []
    assert words.find_never(shared_help.glossary()) == []
    for term, rest in entries:
        assert term and rest
    by = dict(entries)
    assert "Cohen's kappa" in by["Agreement"] and "excerpt" in by["Passage"]


def test_the_glossary_keeps_the_agreement_rule():
    agreement = dict(shared_help.glossary_entries())["Agreement"]
    assert "each code separately" in agreement


def test_troubleshooting_is_for_researchers_not_developers():
    text = shared_help.troubleshooting()
    assert len(re.findall(r"^\*\*.+\*\*$", text, re.M)) >= 12
    assert not re.search(r"ModuleNotFoundError|Traceback|\bpip\b|venv|\bAPI\b|`", text)
    assert words.find_never(text) == [] and words.find_replace(text) == []
    for problem in ("My file will not open", "The analysis is slow", "Too many answers need review"):
        assert f"**{problem}.**" in text
    assert "INSTALL_DESKTOP.md" in text                     # install errors live there


# -- what the help calls things is what the screens call them ------------------------------

#: Bold phrases that are headings or emphasis, not the name of something on screen.
_NOT_LABELS = {
    "What this step is for", "What to do", "Good to know", "The three ways", "Reviewing",
    "Next", "Done", "ERASE", "Theme", "Plain", "Contents",
}


def _screen_strings() -> set:
    from pathlib import Path

    strings = set()
    root = Path(words.ROOT) / "qualsafe_qt"
    for path in root.rglob("*.py"):
        for text in words.ui_strings(path.read_text(encoding="utf-8")):
            strings.add(text.replace("&&", "and").lower())
    for activity in activities.ACTIVITIES:
        strings.add(activity.title.lower())
        strings.update(s.title.lower() for s in activity.steps)
    return strings


def test_every_name_in_bold_in_the_guides_is_on_a_screen():
    """A task article that says to press a button that is not there is worse than no article."""
    texts = [shared_help.article(a, s) for a, s in STEPS] + [shared_help.task(t) for t in TASKS]
    texts.append(shared_help.troubleshooting())
    texts = [re.sub(r"^\*\*.+\*\*$", "", t, flags=re.M) for t in texts]   # whole-line headings are not labels
    on_screen = _screen_strings()
    missing = []
    for text in texts:
        for phrase in re.findall(r"\*\*([^*\n]+?)\*\*", text):
            name = phrase.strip().rstrip(".:?").strip()
            if name in _NOT_LABELS or name.startswith(("How do I", "Surveys,", "Charts,", "Interviews,")):
                continue
            low = name.lower()
            if any(low in s or s in low for s in on_screen):
                continue
            missing.append(name)
    assert not missing, f"names in the guides that no screen shows: {sorted(set(missing))}"
