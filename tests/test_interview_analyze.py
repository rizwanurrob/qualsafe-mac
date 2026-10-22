"""
Tests for v3.1 I3: hardened quote verification, per-theme LLM analysis (mocked
Ollama), and interview -> .qnw store population.

The quote fixtures deliberately contain curly apostrophes (U+2019) and an
em-dash — the exact characters LLMs straighten when echoing text, and the
failure mode the Phase 0a review flagged.
"""

from __future__ import annotations

import math
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from interview.analyze import THEME_SUMMARY_SCHEMA, ThemeAnalysis, analyze_interview, analyze_theme_group
from interview.grouping import ThemeGroup, group_by_theme
from interview.matching import MatchedPair, ThemeMatch, match_qa_pairs
from interview.parse import Turn, segment_turns
from interview.populate import populate_interview_store
from interview.questions import QAPair, Question, detect_questions, pair_questions_with_responses
from interview.quotes import locate_quote, verify_quotes
from interview.speakers import apply_roles, infer_speaker_roles
from interview.template import InterviewTemplate
from engines.ollama_client import OllamaJSONError
from core.project import Project

# Source with curly apostrophe (’), em-dash, and a double space.
SOURCE = (
    "Interviewer: How was it?\n"
    "Respondent: Honestly, it wasn’t easy — I was homesick a lot.\n"
    "That said, the tutoring center helped me more than  anything else that semester."
)


# ─────────────────────────────────────────────────────────────────────────────
# Quote verification
# ─────────────────────────────────────────────────────────────────────────────

class TestLocateQuote:
    def test_exact_match(self):
        q = "the tutoring center helped me"
        loc = locate_quote(q, SOURCE)
        assert loc.match_kind == "exact" and loc.similarity == 1.0
        assert SOURCE[loc.char_start:loc.char_end] == loc.text == q

    def test_straightened_apostrophe_recovers_source_verbatim(self):
        # LLM echoes with a straight apostrophe; source has U+2019.
        loc = locate_quote("it wasn't easy", SOURCE)
        assert loc is not None and loc.match_kind == "normalized"
        assert "’" in loc.text                       # source's own characters
        assert SOURCE[loc.char_start:loc.char_end] == loc.text

    def test_dash_folding(self):
        loc = locate_quote("easy - I was homesick", SOURCE)
        assert loc is not None and loc.match_kind == "normalized"
        assert "—" in loc.text

    def test_case_folding(self):
        loc = locate_quote("HONESTLY, IT WASN'T EASY", SOURCE)
        assert loc is not None and loc.match_kind == "normalized"

    def test_whitespace_collapse(self):
        # Source has a double space in "more than  anything".
        loc = locate_quote("more than anything else", SOURCE)
        assert loc is not None and loc.match_kind == "normalized"
        assert SOURCE[loc.char_start:loc.char_end] == loc.text

    def test_fuzzy_recovers_source_words_not_paraphrase(self):
        # LLM dropped the word "else".
        q = "the tutoring center helped me more than anything that semester."
        loc = locate_quote(q, SOURCE)
        assert loc is not None and loc.match_kind == "fuzzy"
        assert loc.similarity >= 0.9
        assert SOURCE[loc.char_start:loc.char_end] == loc.text   # always source-verbatim
        assert "tutoring center" in loc.text

    def test_hallucinated_quote_rejected(self):
        assert locate_quote("I love the campus pizza and the gym", SOURCE) is None

    def test_empty_quote_rejected(self):
        assert locate_quote("", SOURCE) is None
        assert locate_quote("   ", SOURCE) is None

    def test_verify_quotes_stats(self):
        result = verify_quotes(
            ["the tutoring center helped me", "it wasn't easy", "made-up nonsense words entirely"],
            SOURCE,
        )
        assert len(result.located) == 2 and len(result.dropped) == 1
        assert abs(result.hallucination_rate - 1 / 3) < 1e-9


# ─────────────────────────────────────────────────────────────────────────────
# Per-theme LLM analysis (mocked client)
# ─────────────────────────────────────────────────────────────────────────────

def _template():
    return InterviewTemplate.from_dict({"interview_template": {"themes": [
        {"id": "transition", "label": "Transition to college",
         "definition": "Adjustment to college life.", "guide_questions": ["How was it?"]},
    ]}})


def _group_with_content() -> ThemeGroup:
    turn = Turn(index=1, speaker_raw="Respondent",
                text="Honestly, it wasn’t easy — I was homesick a lot.",
                char_start=25, char_end=78, speaker_role="interviewee")
    pair = QAPair(question=Question("q001", 0, "How was it?"), response_turns=[turn])
    mp = MatchedPair(pair=pair,
                     matches=[ThemeMatch("transition", 0.9, True, "embedding_question")],
                     scores={"transition": 0.9})
    return ThemeGroup(theme_id="transition", label="Transition to college", items=[mp])


class TestAnalyzeTheme:
    def _client(self, payload):
        client = MagicMock()
        if isinstance(payload, Exception):
            client.generate_json.side_effect = payload
        else:
            client.generate_json.return_value = payload
        return client

    def test_summary_and_verified_quotes(self):
        payload = {"summary": "The start was hard and marked by homesickness.",
                   "sub_themes": ["homesickness"], "tone": "mixed",
                   "quotes": ["it wasn't easy", "completely invented quote here"]}
        client = self._client(payload)
        a = analyze_theme_group(_group_with_content(), _template(), SOURCE, client, "llama3.2:3b")
        assert a.summary.startswith("The start was hard")
        assert a.sub_themes == ["homesickness"] and a.tone == "mixed"
        assert len(a.quotes) == 1 and "’" in a.quotes[0].text   # verified, source-verbatim
        assert a.dropped_quotes == ["completely invented quote here"]
        assert abs(a.hallucination_rate - 0.5) < 1e-9

    def test_empty_group_skips_llm(self):
        client = self._client({})
        empty = ThemeGroup(theme_id="transition", label="T", items=[])
        a = analyze_theme_group(empty, _template(), SOURCE, client, "m")
        assert a.note == "no_matched_content" and a.n_pairs == 0
        client.generate_json.assert_not_called()

    def test_json_error_degrades_gracefully(self):
        client = self._client(OllamaJSONError("bad"))
        a = analyze_theme_group(_group_with_content(), _template(), SOURCE, client, "m")
        assert a.note == "llm_json_error" and a.summary == "" and a.quotes == []

    def test_schema_and_knobs_passed(self):
        payload = {"summary": "s", "sub_themes": [], "tone": "neutral", "quotes": []}
        client = self._client(payload)
        analyze_theme_group(_group_with_content(), _template(), SOURCE, client, "m",
                            temperature=0.3, seed=7)
        kwargs = client.generate_json.call_args.kwargs
        assert kwargs["schema"] is THEME_SUMMARY_SCHEMA
        assert kwargs["temperature"] == 0.3 and kwargs["seed"] == 7

    def test_analyze_interview_progress(self):
        payload = {"summary": "s", "sub_themes": [], "tone": "neutral", "quotes": []}
        client = self._client(payload)
        groups = [_group_with_content(), ThemeGroup("transition", "T", items=[])]
        seen = []
        analyze_interview(groups, _template(), SOURCE, client, "m",
                          progress_callback=lambda d, t: seen.append((d, t)))
        assert seen == [(1, 2), (2, 2)]


# ─────────────────────────────────────────────────────────────────────────────
# Interview -> .qnw store population (end-to-end from a tiny transcript)
# ─────────────────────────────────────────────────────────────────────────────

E1 = np.array([1.0, 0.0, 0.0, 0.0])
E3 = np.array([0.0, 0.0, 1.0, 0.0])
E4 = np.array([0.0, 0.0, 0.0, 1.0])
VEC = {
    "How was the start of the year for you?": E1,   # guide question
    "Tell me about the start of the year.": E1,     # asked question
    "Any final thoughts?": E3,
}


def fake_embed(texts):
    return np.array([VEC.get(t, E4) for t in texts], dtype=float)


RAW = ("Q: Tell me about the start of the year.\n"
       "A: It was rough at first, honestly.\n"
       "Q: Any final thoughts?\n"
       "A: The dining hall pizza is underrated.\n")


def _matched_from_raw():
    turns, _, _ = segment_turns(RAW)
    inference = infer_speaker_roles(turns)
    roled = apply_roles(turns, inference.role_by_label)
    questions = detect_questions(roled)
    pairs = pair_questions_with_responses(roled, questions)
    template = InterviewTemplate.from_dict({"interview_template": {
        "title": "Guide v1",
        "themes": [{"id": "transition", "label": "Transition",
                    "guide_questions": ["How was the start of the year for you?"]}],
    }})
    matched = match_qa_pairs(pairs, template, fake_embed)
    return template, matched


class TestPopulateInterviewStore:
    def test_store_contents_and_offsets(self, tmp_path):
        template, matched = _matched_from_raw()
        path = populate_interview_store(
            tmp_path / "iv.qnw", raw_text=RAW, doc_label="interview_01.txt",
            matched=matched, template=template, embedding_model="all-MiniLM-L6-v2")
        with Project.open(path) as p:
            sources = p.list_sources()
            assert len(sources) == 1 and sources[0].type == "interview"
            codes = {c.code_id: c for c in p.get_codebook()}
            assert codes["transition"].origin == "a_priori"
            excerpts = p.list_excerpts()
            assert len(excerpts) == 1                       # only the matched pair
            assert excerpts[0].verify_offsets(sources[0].raw_text)
            apps = p.list_applications()
            assert len(apps) == 1 and apps[0].confidence == 1.0
            assert apps[0].coder == "transformer" and "template match" in apps[0].rationale
            run = p.list_runs()[0]
            assert run.mode == "interview"
            assert run.counts == {"qa_pairs": 2, "matched_pairs": 1,
                                  "unclassified_pairs": 1, "themes": 1}

    def test_analyses_add_quote_excerpts_and_memos(self, tmp_path):
        template, matched = _matched_from_raw()
        quote = locate_quote("It was rough at first", RAW)
        analysis = ThemeAnalysis(theme_id="transition", label="Transition", n_pairs=1,
                                 summary="The start was rough.", tone="negative",
                                 quotes=[quote])
        path = populate_interview_store(
            tmp_path / "iv2.qnw", raw_text=RAW, doc_label="interview_01.txt",
            matched=matched, template=template, analyses=[analysis],
            embedding_model="all-MiniLM-L6-v2", llm_model="llama3.2:3b")
        with Project.open(path) as p:
            memos = p.list_memos()
            assert len(memos) == 1 and memos[0].author == "llm_draft"
            assert memos[0].target_id == "transition"
            apps = p.list_applications()
            llm_apps = [a for a in apps if a.coder == "llm"]
            assert len(llm_apps) == 1 and "verified quote (exact)" in llm_apps[0].rationale
            # The quote excerpt verifies against the source too.
            src = p.list_sources()[0]
            quote_exc = p.get_excerpt(llm_apps[0].excerpt_id)
            assert quote_exc.verify_offsets(src.raw_text)
            assert {r.kind for r in p.list_raters()} == {"transformer", "llm"}
            assert p.list_runs()[0].engine == "llm"

    def test_unclassified_pairs_get_no_applications(self, tmp_path):
        template, matched = _matched_from_raw()
        path = populate_interview_store(
            tmp_path / "iv3.qnw", raw_text=RAW, doc_label="x", matched=matched,
            template=template)
        with Project.open(path) as p:
            freq = p.code_frequency()
            assert list(freq.values()) == [1]     # only the matched pair's theme
