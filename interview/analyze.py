#!/usr/bin/env python
"""
Per-theme LLM analysis (v3.1, I3). Handoff stage [8].

For each theme's regrouped material, a local LLM (via the shared OllamaClient)
produces a summary, emergent sub-themes, tone, and representative quotes. Every
quote the model returns is located and verified against the SOURCE TRANSCRIPT
(interview/quotes.py) before it is surfaced — unverifiable quotes are dropped and
counted, and the per-theme hallucination rate is kept as a trust statistic.

The prompt lives in prompts/theme_summary.txt (versioned, auditable). A JSON
failure for one theme degrades to an empty analysis with a note — it never kills
the run. Empty theme groups skip the LLM entirely.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from engines.ollama_client import OllamaClient, OllamaJSONError
from interview.grouping import ThemeGroup
from interview.matching import response_text
from interview.quotes import LocatedQuote, verify_quotes
from interview.template import InterviewTemplate

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"

THEME_SUMMARY_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "sub_themes": {"type": "array", "items": {"type": "string"}},
        "tone": {"type": "string", "enum": ["positive", "neutral", "negative", "mixed"]},
        "quotes": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary", "sub_themes", "tone", "quotes"],
}


@dataclass
class ThemeAnalysis:
    theme_id: str
    label: str
    n_pairs: int
    summary: str = ""
    sub_themes: List[str] = field(default_factory=list)
    tone: str = ""
    quotes: List[LocatedQuote] = field(default_factory=list)   # verified, source-verbatim
    dropped_quotes: List[str] = field(default_factory=list)    # unverifiable (hallucination signal)
    note: str = ""                                             # "", "no_matched_content", "llm_json_error"

    @property
    def hallucination_rate(self) -> float:
        n = len(self.quotes) + len(self.dropped_quotes)
        return len(self.dropped_quotes) / n if n else 0.0


def _material_block(group: ThemeGroup) -> str:
    blocks: List[str] = []
    for i, item in enumerate(group.items, start=1):
        answer = response_text(item.pair) or "(no direct response recorded)"
        blocks.append(f"[Exchange {i}]\nQ: {item.pair.question.text}\nA: {answer}")
    return "\n\n".join(blocks)


def analyze_theme_group(
    group: ThemeGroup,
    template: InterviewTemplate,
    source_text: str,
    client: OllamaClient,
    model: str,
    *,
    temperature: float = 0.2,
    seed: Optional[int] = None,
    max_quotes: int = 4,
    min_fuzzy_ratio: float = 0.90,
    prompt_path: Optional[Path] = None,
) -> ThemeAnalysis:
    """Analyze one theme's regrouped material; quotes verified against source."""
    analysis = ThemeAnalysis(theme_id=group.theme_id, label=group.label,
                             n_pairs=len(group.items))
    if not group.items:
        analysis.note = "no_matched_content"
        return analysis

    theme = next((t for t in template.themes if t.id == group.theme_id), None)
    definition = theme.definition if theme and theme.definition else "(no definition provided)"
    prompt_template = (prompt_path or (PROMPTS_DIR / "theme_summary.txt")).read_text(encoding="utf-8")
    prompt = (prompt_template
              .replace("<<THEME_LABEL>>", group.label)
              .replace("<<THEME_DEFINITION>>", definition)
              .replace("<<MATERIAL>>", _material_block(group))
              .replace("<<MAX_QUOTES>>", str(max_quotes)))

    try:
        data = client.generate_json(model, prompt, schema=THEME_SUMMARY_SCHEMA,
                                    temperature=temperature, seed=seed)
    except OllamaJSONError:
        analysis.note = "llm_json_error"
        return analysis

    analysis.summary = str(data.get("summary", "") or "")
    analysis.sub_themes = [str(s) for s in (data.get("sub_themes") or [])]
    analysis.tone = str(data.get("tone", "") or "")

    proposed = [str(q) for q in (data.get("quotes") or [])][:max_quotes]
    verification = verify_quotes(proposed, source_text, min_fuzzy_ratio=min_fuzzy_ratio)
    analysis.quotes = verification.located
    analysis.dropped_quotes = verification.dropped
    return analysis


def analyze_interview(
    groups: List[ThemeGroup],
    template: InterviewTemplate,
    source_text: str,
    client: OllamaClient,
    model: str,
    *,
    temperature: float = 0.2,
    seed: Optional[int] = None,
    max_quotes: int = 4,
    min_fuzzy_ratio: float = 0.90,
    progress_callback=None,
) -> List[ThemeAnalysis]:
    """Analyze every theme group (skipping empty ones' LLM calls), with progress."""
    analyses: List[ThemeAnalysis] = []
    total = len(groups)
    for i, group in enumerate(groups):
        analyses.append(analyze_theme_group(
            group, template, source_text, client, model,
            temperature=temperature, seed=seed, max_quotes=max_quotes,
            min_fuzzy_ratio=min_fuzzy_ratio,
        ))
        if progress_callback is not None:
            try:
                progress_callback(i + 1, total)
            except Exception:  # noqa: BLE001 — UI callback must never break analysis
                pass
    return analyses
