"""
Code colours: the palette, and the analyst's own overrides.

Two problems this module solves, in order of severity.

**Six colours is not enough.** `core/theme.py` ships six categorical colours,
which is right for a chart legend and wrong for a codebook: a twelve-code project
got six colours and every code had an identical twin in the reader's margin
stripes — in the one place this app asks you to trust colour. Real codebooks run
to twenty or forty codes. `qualsafe_qt.theme.category_colors` extends the list,
keeping the upstream six first so a small project looks the same in both front
ends.

**An analyst has colours in their head already.** If cost is red in your writing,
it should be red here. Overrides are stored **in the project** rather than in
this machine's settings, so they travel with the `.qnw` to a colleague — using a
memo with a reserved target type, the same trick `analysis/framework.py` uses for
cell summaries, so no schema change is needed and the Streamlit build ignores
them harmlessly.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional

from PySide6.QtGui import QColor

from qualsafe_qt.theme import DEFAULT_CATEGORY_PALETTE, category_colors

#: Memo target type holding a per-code colour. Reserved, like `saved_query` and
#: the framework matrix's cell summaries — invisible to the Streamlit build's
#: memo panels, which filter on `code` / `project` / `analysis_view`.
CODE_COLOR_MEMO = "code_color"

_HEX = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


def is_valid_hex(value: str) -> bool:
    return bool(_HEX.match((value or "").strip()))


def code_colors(
    code_names: Iterable[str],
    mode: str = "dark",
    *,
    palette: str = DEFAULT_CATEGORY_PALETTE,
    overrides: Optional[Dict[str, str]] = None,
) -> Dict[str, QColor]:
    """Stable `{code_name: QColor}`.

    Keyed on the sorted name list so adding a code late in the alphabet does not
    reshuffle every colour, and so the first six match
    `app/documents_page._code_colors` exactly for a small codebook.

    `overrides` maps code name -> hex and wins over the palette.
    """
    colours: List[str] = category_colors(mode, palette)
    names = sorted({str(n) for n in code_names})
    chosen = {name: QColor(colours[i % len(colours)])
              for i, name in enumerate(names)}
    for name, value in (overrides or {}).items():
        if name in chosen and is_valid_hex(value):
            chosen[name] = QColor(value)
    return chosen


def with_alpha(color: QColor, alpha: int) -> QColor:
    """A copy of `color` at `alpha` (0-255) — for highlight fills behind text."""
    out = QColor(color)
    out.setAlpha(max(0, min(255, int(alpha))))
    return out


def load_overrides(project: Any) -> Dict[str, str]:
    """`{code_name: hex}` from the project's stored colour choices.

    Keyed by code **name** rather than id so the mapping survives a codebook
    import into a different project, which is how a research group shares a
    scheme. A colour for a code that no longer exists is simply unused.
    """
    out: Dict[str, str] = {}
    try:
        memos = project.list_memos(target_type=CODE_COLOR_MEMO)
    except Exception:  # noqa: BLE001 - a colour preference must never break a view
        return out
    for memo in memos:
        name, _sep, value = (memo.text or "").partition("\n")
        if name.strip() and is_valid_hex(value):
            out[name.strip()] = value.strip()
    return out


def set_override(project: Any, code_name: str, hex_color: Optional[str]) -> None:
    """Set (or clear, with None) one code's colour. Replaces any existing entry."""
    from core.model import Memo

    existing = [m for m in project.list_memos(target_type=CODE_COLOR_MEMO)
                if (m.text or "").partition("\n")[0].strip() == code_name]
    for memo in existing:
        project.delete_memo(memo.memo_id)
    if hex_color and is_valid_hex(hex_color):
        project.add_memo(Memo(
            memo_id="", target_type=CODE_COLOR_MEMO, target_id="",
            text=f"{code_name}\n{hex_color.strip()}", author="human"))
