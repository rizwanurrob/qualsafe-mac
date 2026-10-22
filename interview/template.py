#!/usr/bin/env python
"""
Interview template (the interview guide) — schema, load, validate (v3.1, I1).

The analyst provides the guide as structured YAML: a set of themes, each with an
id, a human label, canonical guide questions, and optional keywords. Conceptually
this IS an a-priori codebook (V3_PLAN: unify the concepts) — `to_codes()` maps the
themes onto shared-model `Code` objects so interview coding lands in the same
project store as survey coding.

Example YAML (see config/interview_template.example.yaml):

    interview_template:
      title: "Student Belonging Interview Guide"
      themes:
        - id: transition
          label: "Transition to college"
          guide_questions:
            - "How was your first semester?"
          keywords: [adjustment, first year]
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Union

import yaml

from core.model import Code


class TemplateError(ValueError):
    """Raised when an interview template fails validation."""


@dataclass
class TemplateTheme:
    id: str
    label: str
    guide_questions: List[str] = field(default_factory=list)
    keywords: List[str] = field(default_factory=list)
    definition: str = ""


@dataclass
class InterviewTemplate:
    title: str
    themes: List[TemplateTheme]

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "InterviewTemplate":
        root = data.get("interview_template", data)
        if not isinstance(root, dict):
            raise TemplateError("Template must be a mapping (dict).")
        raw_themes = root.get("themes")
        if not isinstance(raw_themes, list) or not raw_themes:
            raise TemplateError("Template must define a non-empty 'themes' list.")

        themes: List[TemplateTheme] = []
        seen_ids: set = set()
        for i, item in enumerate(raw_themes):
            if not isinstance(item, dict):
                raise TemplateError(f"Theme #{i + 1} must be a mapping.")
            theme_id = str(item.get("id", "") or "").strip()
            label = str(item.get("label", "") or "").strip()
            if not theme_id:
                raise TemplateError(f"Theme #{i + 1} is missing required field 'id'.")
            if not label:
                raise TemplateError(f"Theme '{theme_id}' is missing required field 'label'.")
            if theme_id in seen_ids:
                raise TemplateError(f"Duplicate theme id: '{theme_id}'.")
            seen_ids.add(theme_id)
            themes.append(TemplateTheme(
                id=theme_id,
                label=label,
                guide_questions=[str(q) for q in (item.get("guide_questions") or [])],
                keywords=[str(k) for k in (item.get("keywords") or [])],
                definition=str(item.get("definition", "") or ""),
            ))
        return cls(title=str(root.get("title", "") or "Interview Template"), themes=themes)

    @classmethod
    def load(cls, path: Union[str, Path]) -> "InterviewTemplate":
        raw = Path(path).read_text(encoding="utf-8")
        data = yaml.safe_load(raw)
        if not isinstance(data, dict):
            raise TemplateError(f"Template file must load to a mapping: {path}")
        return cls.from_dict(data)

    def to_codes(self) -> List[Code]:
        """Map template themes onto shared-model a-priori codes (human-owned)."""
        return [
            Code(code_id=t.id, name=t.label, definition=t.definition,
                 origin="a_priori", created_by="human")
            for t in self.themes
        ]
