"""Tests for lexical exploration — tokenizing, word frequency, KWIC, contexts."""

from __future__ import annotations

from analysis.lexical import (
    DEFAULT_STOPWORDS, context_profile, kwic_line, tokenize, word_frequency,
)


def test_tokenize_keeps_offsets_and_internal_punctuation():
    text = "Don't worry: first-year cost"
    toks = tokenize(text)
    words = [t for t, _s, _e in toks]
    assert words == ["don't", "worry", "first-year", "cost"]
    # Offsets must point back at the exact source characters.
    for tok, start, end in toks:
        assert text[start:end].lower() == tok


def test_word_frequency_counts_and_document_spread():
    texts = ["cost cost worry", "cost of books", "no mention here"]
    df = word_frequency(texts, min_length=3, top_n=None)
    row = df[df["term"] == "cost"].iloc[0]
    assert row["count"] == 3          # 2 + 1
    assert row["documents"] == 2      # only two texts contain it


def test_word_frequency_removes_stopwords_by_default():
    df = word_frequency(["the cost and the worry"], min_length=1, top_n=None)
    terms = set(df["term"])
    assert "the" not in terms and "and" not in terms
    assert {"cost", "worry"} <= terms


def test_word_frequency_stopwords_can_be_disabled():
    df = word_frequency(["the cost"], stopwords=[], min_length=1, top_n=None)
    assert "the" in set(df["term"])


def test_word_frequency_respects_min_length_and_top_n():
    df = word_frequency(["aa bbb cccc ddddd"], stopwords=[], min_length=4, top_n=1)
    assert list(df["term"]) == ["cccc"] or list(df["term"]) == ["ddddd"]
    assert len(df) == 1
    all_terms = set(word_frequency(["aa bbb cccc"], stopwords=[], min_length=4, top_n=None)["term"])
    assert "aa" not in all_terms and "bbb" not in all_terms


def test_word_frequency_is_deterministic_on_ties():
    a = word_frequency(["zebra apple", "apple zebra"], stopwords=[], top_n=None)
    b = word_frequency(["zebra apple", "apple zebra"], stopwords=[], top_n=None)
    assert list(a["term"]) == list(b["term"])
    assert list(a["term"])[0] == "apple"    # equal counts -> alphabetical


def test_word_frequency_empty_corpus():
    assert word_frequency([]).empty
    assert word_frequency(["the and is"]).empty     # all stopwords


def test_kwic_takes_the_match_from_the_source():
    text = "Tuition cost is a worry"
    left, match, right = kwic_line(text, 8, 12, width=5)
    assert match == "cost" == text[8:12]
    assert left.endswith("on ") or left.endswith("n ")
    assert "…" in left            # truncated on the left
    assert right.startswith(" is")


def test_kwic_at_document_edges_has_no_ellipsis():
    text = "cost matters"
    left, match, right = kwic_line(text, 0, 4, width=50)
    assert left == "" and match == "cost"
    assert not right.endswith("…")


def test_kwic_flattens_newlines():
    left, _m, right = kwic_line("a\nb cost d\ne", 4, 8, width=10)
    assert "\n" not in left and "\n" not in right


def test_context_profile_counts_adjacent_words():
    contexts = [("tuition ", " worry"), ("rising ", " barrier"), ("tuition ", " worry")]
    prof = context_profile(contexts)
    before = dict(zip(prof["before"]["term"], prof["before"]["count"]))
    after = dict(zip(prof["after"]["term"], prof["after"]["count"]))
    assert before["tuition"] == 2 and before["rising"] == 1
    assert after["worry"] == 2


def test_context_profile_handles_empty_sides():
    prof = context_profile([("", ""), ("cost ", "")])
    assert prof["after"].empty
    assert list(prof["before"]["term"]) == ["cost"]


def test_stopword_list_is_a_frozenset_of_lowercase():
    assert isinstance(DEFAULT_STOPWORDS, frozenset)
    assert all(w == w.lower() for w in DEFAULT_STOPWORDS)
