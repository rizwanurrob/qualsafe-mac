"""
Number and label formatting. One place decides how "93% (519/558)" is written, so
the chart, the table and the export cannot disagree.

Rules for the data label of a categorical bar, from the brief:

- the **percent** is the headline,
- the **numerator** is the number who chose the category,
- the **valid N** is the base, and is only ever shown as the *second* number of
  "n/N". It is never written as though it were the count selecting the category.

    percent + count + valid N   ->  93% (519/558)
    percent + count             ->  93% (519)
    percent only                ->  93%
    count only                  ->  519
    percent + valid N only      ->  93% of 558
    count-led (bar shows count) ->  519/558 (93%)

Rounding is half-up (12.5 -> 13), not Python's round-half-even, because a
published percentage that rounds 12.5 down to 12 and 13.5 down to 14 looks like
an error to a reader checking it by hand.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Optional


def round_half_up(value: float, decimals: int = 0) -> Decimal:
    quantum = Decimal(1).scaleb(-decimals)
    return Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP)


def format_number(value: Optional[float], decimals: int = 0,
                  thousands: bool = True) -> str:
    if value is None or value != value:
        return ""
    text = f"{round_half_up(value, decimals):,f}" if thousands \
        else f"{round_half_up(value, decimals):f}"
    return text


def format_percent(value: Optional[float], decimals: int = 0) -> str:
    if value is None or value != value:
        return ""
    return f"{format_number(value, decimals, thousands=False)}%"


def display_label(count: Optional[float], denominator: Optional[float],
                  percent: Optional[float], *, show_percent: bool = True,
                  show_count: bool = True, show_valid_n: bool = True,
                  decimals: int = 0, thousands: bool = True,
                  lead: str = "percent") -> str:
    """The data label for one bar or slice.

    ``lead="percent"`` (the bar shows a percentage) writes the percent first;
    ``lead="count"`` (the bar shows a count) writes the count first, as
    "519/558 (93%)", so the headline always matches the bar's length.
    """
    n = format_number(count, 0, thousands)
    base = format_number(denominator, 0, thousands)
    pct = format_percent(percent, decimals)
    have_base = bool(base) and show_valid_n
    if lead == "count":
        if show_count and n:
            head = f"{n}/{base}" if have_base else n
            return f"{head} ({pct})" if show_percent and pct else head
        return pct if show_percent else ""
    if show_percent and pct:
        if show_count and n and have_base:
            return f"{pct} ({n}/{base})"
        if show_count and n:
            return f"{pct} ({n})"
        if have_base:
            return f"{pct} of {base}"
        return pct
    if show_count and n:
        return f"{n}/{base}" if have_base else n
    return ""


def measure_label(value: Optional[float], decimals: int = 1,
                  thousands: bool = True) -> str:
    """Label for a sum/mean/median/min/max: the value, no base."""
    return format_number(value, decimals, thousands)
