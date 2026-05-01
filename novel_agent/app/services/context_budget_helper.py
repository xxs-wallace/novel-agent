from __future__ import annotations

from dataclasses import dataclass

from ..utils.text_utils import clamp_text


@dataclass(slots=True)
class BudgetDecision:
    text: str
    used_chars: int
    truncated: bool = False
    omitted: bool = False


def fit_text_with_budget(*, text: str, remaining_chars: int) -> BudgetDecision:
    normalized = text.strip()
    if remaining_chars <= 0:
        return BudgetDecision(text="", used_chars=0, omitted=True)
    if not normalized:
        return BudgetDecision(text="", used_chars=0)
    if len(normalized) <= remaining_chars:
        return BudgetDecision(text=normalized, used_chars=len(normalized))
    clipped = clamp_text(normalized, remaining_chars).strip()
    if not clipped:
        return BudgetDecision(text="", used_chars=0, omitted=True)
    return BudgetDecision(
        text=clipped,
        used_chars=len(clipped),
        truncated=True,
    )
