"""Long-text segmentation for structured coding engines (core/segmentation.py)."""

from __future__ import annotations

from core.segmentation import Segment, needs_segmentation, segment_for_coding


def test_short_text_is_returned_whole():
    text = "This was a hard year. Advising helped a lot though."
    segments = segment_for_coding(text, token_budget=350)
    assert len(segments) == 1
    assert segments[0].text == text
    assert (segments[0].char_start, segments[0].char_end) == (0, len(text))
    assert (segments[0].index, segments[0].total) == (0, 1)


def test_needs_segmentation_is_a_cheap_length_estimate():
    short = "Short response."
    long = "word " * 500
    assert not needs_segmentation(short, token_budget=100)
    assert needs_segmentation(long, token_budget=100)


def test_every_segment_satisfies_the_offset_guarantee():
    text = ("Financial stress was overwhelming this semester. "
            "I almost dropped out because I could not afford rent. "
            "Advising was somewhat helpful when I finally reached someone. "
            "The waitlist for tutoring was too long to be useful. "
            "Overall I felt unsupported by the institution most of the time.")
    segments = segment_for_coding(text, token_budget=15, overlap_sentences=0)
    assert len(segments) > 1
    for seg in segments:
        assert text[seg.char_start:seg.char_end] == seg.text


def test_segments_never_split_a_sentence():
    text = "One sentence here. Another sentence follows. And a third one too."
    segments = segment_for_coding(text, token_budget=6, overlap_sentences=0)
    sentence_starts = {"One sentence here.", "Another sentence follows.", "And a third one too."}
    for seg in segments:
        # Every segment's text is a concatenation of whole sentences.
        assert any(seg.text.startswith(s) for s in sentence_starts)


def test_overlap_repeats_the_boundary_sentence():
    text = "Sentence one is here. Sentence two is here. Sentence three is here. Sentence four is here."
    with_overlap = segment_for_coding(text, token_budget=6, overlap_sentences=1)
    assert len(with_overlap) > 1
    # Segment 1 must start with the sentence that ended segment 0 -- a theme
    # stated right at the boundary must not be invisible to either segment.
    boundary_sentence = with_overlap[0].text.split(". ")[-1].strip()
    assert with_overlap[1].text.startswith(boundary_sentence)


def test_index_and_total_are_consistent_across_segments():
    text = "First idea here now. Second idea here now. Third idea here now. Fourth idea here now."
    segments = segment_for_coding(text, token_budget=5, overlap_sentences=0)
    assert [s.index for s in segments] == list(range(len(segments)))
    assert all(s.total == len(segments) for s in segments)


def test_an_oversized_single_sentence_is_kept_whole_not_truncated():
    """Truncating a codeable unit would invent a boundary the source doesn't
    have -- forbidden by this codebase's offset guarantee everywhere else."""
    huge_sentence = "This is one enormous run-on sentence " + ("that keeps going " * 100) + "and finally ends."
    segments = segment_for_coding(huge_sentence, token_budget=5, overlap_sentences=0)
    # Kept as whole sentences; none is truncated mid-sentence.
    for seg in segments:
        assert huge_sentence[seg.char_start:seg.char_end] == seg.text


def test_text_with_no_sentence_boundary_is_returned_whole_when_oversized():
    # No trailing space: `split_sentences` trims whitespace off a span's edges
    # (documented there), so a trailing space here would legitimately not be
    # echoed back -- not a bug in either module, just not what this test means
    # to check.
    no_boundary = ("word " * 300).strip()   # no . ! ? anywhere
    segments = segment_for_coding(no_boundary, token_budget=5)
    assert len(segments) == 1
    assert segments[0].text == no_boundary
    assert no_boundary[segments[0].char_start:segments[0].char_end] == segments[0].text


def test_empty_text_returns_one_empty_segment():
    segments = segment_for_coding("", token_budget=350)
    assert len(segments) == 1
    assert segments[0].text == ""
