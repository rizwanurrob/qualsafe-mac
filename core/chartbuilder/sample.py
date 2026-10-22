"""
A small synthetic survey for trying the Chart Builder without a file of one's own,
and for the UI tests. Invented data only: no real respondents, deterministic
(seeded), and shaped like the files this program is for: a Likert matrix, a
select-all question whose choices contain commas, a single-select, a free-text
answer, and a few demographics with a little blank data.
"""

from __future__ import annotations

import datetime
import random
from typing import List

import pandas as pd

AGREE = ["Strongly disagree", "Somewhat disagree", "Neutral", "Somewhat agree",
         "Strongly agree"]
CONCERNS = ["Relationships with friends, family, partners, or roommates",
            "Getting involved or finding community",
            "Managing anxiety, stress, or feeling overwhelmed",
            "Paying for college",
            "Balancing work and classes"]
MATRIX_ITEMS = ["I feel like I belong here", "I feel safe on campus",
                "Faculty care about my success"]
COMMENTS = [
    "The advising office was helpful and friendly",
    "Financial aid was confusing and slow to respond",
    "I wish there were more places to meet other students",
    "Housing costs are too high for what we get",
    "Classes are great but I feel overwhelmed by the workload",
    "Finding community has been harder than I expected"]


def sample_frame(n: int = 240, seed: int = 7) -> pd.DataFrame:
    rng = random.Random(seed)
    weights = [1, 2, 3, 5, 4]
    rows: List[dict] = []
    for i in range(n):
        picked = rng.sample(CONCERNS, rng.choice([0, 1, 1, 2, 3]))
        row = {"Respondent": f"R{i + 1:04d}",
               "Class year": rng.choice(["First-year", "Sophomore", "Junior", "Senior"]),
               "Residence": rng.choice(["On campus", "Commuter", "Off campus", "NULL"]),
               "First generation": rng.choice(["Yes", "No", "No", "N/A"]),
               "Age": str(rng.randint(17, 34)) if rng.random() > 0.03 else "",
               "Concerns": ",".join(picked),
               "Comment": rng.choice(COMMENTS) if rng.random() > 0.35 else ""}
        for item in MATRIX_ITEMS:
            row[item] = rng.choices(AGREE + ["No opinion"], weights + [1])[0] \
                if rng.random() > 0.04 else ""
        rows.append(row)
    frame = pd.DataFrame(rows)
    # A date and a second number, drawn from their own generator so the columns
    # above are the same as they always were.
    extra = random.Random(seed + 1)
    start = datetime.date(2025, 9, 1)
    frame["Survey date"] = [(start + datetime.timedelta(days=extra.randint(0, 104))).isoformat()
                            for _ in range(n)]
    frame["Hours per week"] = [str(round(max(extra.gauss(14, 5), 0), 1)) if extra.random() > 0.05
                               else "" for _ in range(n)]
    return frame
