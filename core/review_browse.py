"""Browse the coded answers by theme, whichever way they were coded.

One table with a row for each answer and theme: the answer, the score when there is one, who applied the
theme, and what you decided. The scores are model scores, never probabilities. The table holds the answer
text, so a screen shows it and a file holds it only when you save one.
"""

from __future__ import annotations

from typing import Optional

import pandas as pd

COLUMNS = ["theme", "answer_id", "answer", "score", "applied_by", "you_decided"]


def browse_table(project) -> pd.DataFrame:
    """Every theme that was applied, or that the engine proposed, to an answer."""
    text = {e.excerpt_id: e.text for e in project.list_excerpts()}
    rows = []
    seen = set()

    applications = project.coding_table()
    for _, r in applications.iterrows():
        key = (r["excerpt_id"], r["code_name"])
        seen.add(key)
        rows.append({
            "theme": r["code_name"], "answer_id": r["excerpt_id"], "answer": text.get(r["excerpt_id"], ""),
            "score": None if pd.isna(r["confidence"]) else float(r["confidence"]),
            "applied_by": str(r["coder"] or r["rater_id"] or ""), "you_decided": "",
        })

    decisions = project.coding_decisions_table()
    for _, r in decisions.iterrows():
        key = (r["excerpt_id"], r["code_name"])
        human = r["human_assigned"]
        verdict = "" if pd.isna(human) else ("applies" if bool(human) else "does not apply")
        if key in seen:
            if verdict:
                for row in rows:
                    if (row["answer_id"], row["theme"]) == key:
                        row["you_decided"] = verdict
                        if row["score"] is None and not pd.isna(r["model_score"]):
                            row["score"] = float(r["model_score"])
            continue
        if not (bool(r["model_assigned"]) or verdict == "applies"):
            continue
        seen.add(key)
        rows.append({
            "theme": r["code_name"], "answer_id": r["excerpt_id"], "answer": r["excerpt_text"],
            "score": None if pd.isna(r["model_score"]) else float(r["model_score"]),
            "applied_by": "engine", "you_decided": verdict or "not checked yet",
        })
    out = pd.DataFrame(rows, columns=COLUMNS)
    return out.sort_values(["theme", "score"], ascending=[True, False], na_position="last").reset_index(drop=True)


def theme_counts(table: pd.DataFrame) -> pd.DataFrame:
    """Answers for each theme, most common first."""
    if table.empty:
        return pd.DataFrame(columns=["theme", "answers"])
    counts = table.groupby("theme")["answer_id"].nunique().rename("answers").reset_index()
    return counts.sort_values(["answers", "theme"], ascending=[False, True]).reset_index(drop=True)


def for_theme(table: pd.DataFrame, theme: Optional[str]) -> pd.DataFrame:
    return table if not theme else table[table["theme"] == theme]
