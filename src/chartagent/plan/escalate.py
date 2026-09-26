"""The escalation trigger (ADR-0027 Decisions 2, 3 and 6) — the review-side
half of the hop. It decides; it does not call ``generate_recipe``.

The only trigger is a Flint ``marks_present`` fail at ``balanced``/``best``.
A blank ``painted``, an ``injection_pattern`` fail, exhausted presentational
repairs and every ``fast`` request stay on-rail. A recipe is never a frame, so
it can never produce a second decision.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from chartagent.frame.input import InputFrame, SourceBucket, ThemeSpec
from chartagent.recipe import ChartRecipe
from chartagent.review import ReviewReport
from chartagent.transform.model import Menu, RawSql

Quality = Literal["fast", "balanced", "best"]

# Review-repair budget, separate from the planner's 1/2/5 emit cap (Decision 3).
_REVIEW_REPAIRS: dict[Quality, int] = {"fast": 0, "balanced": 1, "best": 2}


@dataclass(frozen=True)
class EscalationDecision:
    """The bucket-4 verdict: what the failed frame hands ``generate_recipe``.

    ``remaining_repairs`` is what is left of the ``quality=`` budget; the
    recipe re-enters the review loop with it and gets no fresh budget."""

    transform: Menu | RawSql
    source_schema: dict[str, SourceBucket]
    theme_spec: str | ThemeSpec | None
    remaining_repairs: int


def decide_escalation(
    report: ReviewReport,
    artifact: InputFrame | ChartRecipe,
    *,
    quality: Quality,
    repairs_spent: int = 0,
) -> EscalationDecision | None:
    """``None`` means stay on-rail. ``repairs_spent`` counts review repairs
    already used this call; the trigger itself consumes none (Decision 3)."""
    if repairs_spent < 0:
        raise ValueError("repairs_spent cannot be negative")
    if quality == "fast" or isinstance(artifact, ChartRecipe):
        return None
    outcomes = {check.name: check.outcome for check in report.checks}
    if outcomes.get("marks_present") != "fail":
        return None
    if "fail" in (outcomes.get("injection_pattern"), outcomes.get("painted")):
        return None
    carried = artifact.x_chartagent
    return EscalationDecision(
        transform=(carried.transform if carried and carried.transform else Menu()),
        source_schema=dict(carried.source_schema or {}) if carried else {},
        theme_spec=artifact.theme_spec,
        remaining_repairs=max(0, _REVIEW_REPAIRS[quality] - repairs_spent),
    )
