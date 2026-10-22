"""
The beginner's guide (core/ux/guide.py): structure, wording, and citations.

The guide is teaching material with page references to three books. The tests
cannot check the books, but they can catch the failures that matter: a section
that cites nothing, a page number that cannot exist, a banned word in text a new
user reads first, or a glossary that has lost the terms the books define.

No Qt, no Streamlit, no model.
"""

from __future__ import annotations

import re

import pytest

from core.ux import guide, words

BOOK_NAMES = ("Saldaña", "Creswell", "Silverman")


def _sections():
    return guide.all_sections()


def test_every_section_has_a_title_a_body_and_a_shared_prefix():
    titles = [t for t, _ in _sections()]
    assert len(titles) == len(set(titles)), "section titles must be unique"
    for title, body in _sections():
        assert title.startswith("New to this · "), title
        assert len(body.strip()) > 200, f"{title!r} is too thin to help anyone"


def test_every_teaching_section_names_a_book():
    """A section about method that cites nothing is an opinion. The books page and
    the glossary name them by design; every other section must cite one."""
    for title, body in _sections():
        if any(name in body for name in BOOK_NAMES):
            continue
        pytest.fail(f"{title!r} cites none of {BOOK_NAMES}")


def test_saldana_page_numbers_are_real_pages():
    """The book has 299 numbered pages in the index; 'p. 0' or 'p. 900' is a typo."""
    text = "\n".join(body for _, body in _sections())
    for match in re.finditer(r"Saldaña[^.\n]{0,60}?pp?\. (\d+)", text):
        assert 1 <= int(match.group(1)) <= 299, match.group(0)


def test_silverman_tip_numbers_exist():
    """Silverman's fifth edition numbers its tips 1 to 65."""
    text = "\n".join(body for _, body in _sections())
    for match in re.finditer(r"Tips? (\d+)", text):
        assert 1 <= int(match.group(1)) <= 65, match.group(0)


def test_no_hype_words_anywhere():
    for title, body in _sections():
        assert words.find_never(body) == [], title
        assert words.find_never(title) == [], title


def test_no_internal_jargon_outside_the_glossary_and_books_page():
    """The glossary names the books' terms on purpose, and the books page names
    the books. Everywhere else, plain words (V8_PLAN.md section 2.1)."""
    skip = ("Words and what they mean", "The three books")
    for title, body in _sections():
        if any(s in title for s in skip):
            continue
        assert words.find_replace(body) == [], (title, words.find_replace(body))


def test_the_code_theme_distinction_is_taught():
    """The one point where beginners most often go wrong, and where Saldaña (p. 14)
    and Creswell (ch. 8) can look as if they disagree."""
    body = dict(_sections())["New to this · Codes, categories and themes"]
    for needle in ("outcome", "sentence", "Provisional", "Creswell", "Saldaña, p. 14"):
        assert needle in body, needle


def test_memo_topics_cover_saldanas_eleven():
    assert len(guide.MEMO_TOPICS) == 11
    titles = [t for t, _ in guide.MEMO_TOPICS]
    assert len(titles) == len(set(titles))
    for _title, prompt in guide.MEMO_TOPICS:
        assert prompt.strip().endswith(("?", "."))


def test_memo_topics_appear_in_the_memo_section():
    body = dict(_sections())["New to this · Memos and your research diary"]
    for title, _prompt in guide.MEMO_TOPICS:
        assert f"**{title}.**" in body


def test_glossary_keeps_the_terms_the_books_define():
    terms = {row[0] for row in guide.GLOSSARY}
    for needed in ("Code", "Category", "Theme", "Memo", "Codebook", "Agreement",
                   "Audit trail", "Deviant case", "Saturation", "Suggested code"):
        assert needed in terms, needed
    assert all(len(row) == 4 and all(cell.strip() for cell in row)
               for row in guide.GLOSSARY)
    assert "| **Theme** |" in guide.glossary_markdown()


def test_the_three_books_are_listed_with_full_references():
    assert set(guide.BOOKS) == set(BOOK_NAMES)
    # The page italicises titles; the stored references do not.
    body = dict(_sections())["New to this · The three books"].replace("*", "")
    body = " ".join(body.split())       # the page wraps lines; the references do not
    for ref in guide.BOOKS.values():
        assert ref in body, ref


def test_agreement_guidance_matches_the_books():
    """Saldaña (p. 35) and Creswell (ch. 10) both give 80 percent as a benchmark and
    neither treats agreement as proof of correctness."""
    body = dict(_sections())["New to this · Coding with a partner"]
    assert "80-90%" in body and "80%" in body
    assert "no agreed standard" in body.lower()
    assert "objective" in body.lower()


def test_the_validity_section_offers_both_authors_lists():
    body = dict(_sections())["New to this · Checking your work"]
    for strategy in ("Triangulation", "Negative case analysis", "Member checking",
                     "External audit", "Refutability", "Comprehensive data treatment",
                     "Deviant case analysis"):
        assert strategy in body, strategy


def test_the_validity_section_points_to_the_desktop_screens():
    """Audit F1: the desktop has Deviant cases and Saturation, so the guide says where."""
    body = dict(_sections())["New to this · Checking your work"]
    assert "Analysis → Deviant cases" in body
    assert "Analysis → Saturation" in body
    assert "browser version" not in body
    assert "reading order, not a verdict" in body
