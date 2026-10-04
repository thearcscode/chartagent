"""Review-repair accounting, rail-agnostic (ADR-0027 Decision 7). The recipe
loop uses it today; Flint's loop (#240) reuses it.

One unit of budget per repair ask, charged whether or not the repair is kept;
a discarded ask spends a unit; a repair that does not pass re-review is
dropped; best-so-far is the last artifact that passed review, else the first
one emitted; ``budget_exhausted`` is set iff the returned report carries a
repairable failure and no budget remains. What differs per rail — how a repair
is requested and what a replaced artifact is — comes in as callables."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import TypeVar

from chartagent.review import CheckName, ReviewReport

_A = TypeVar("_A")


def _repairable_failures(
    review: ReviewReport, names: frozenset[CheckName] | None
) -> list[CheckName]:
    """injection_pattern is never repaired and must not veto the other names.
    ``names`` narrows a rail to the checks it can repair; ``None`` is all."""
    return [
        check.name
        for check in review.checks
        if check.outcome == "fail"
        and check.name != "injection_pattern"
        and (names is None or check.name in names)
    ]


def spend_repair_budget(
    artifact: _A,
    review: ReviewReport,
    budget: int,
    *,
    request: Callable[[_A, list[CheckName]], _A | None],
    reviewer: Callable[[_A], ReviewReport],
    repairable: frozenset[CheckName] | None = None,
) -> tuple[_A, ReviewReport]:
    """Returns the best artifact and its report. ``request`` returns ``None``
    for a discarded ask. Never raises on review."""
    failing = _repairable_failures(review, repairable)
    while budget > 0 and failing:
        budget -= 1
        repaired = request(artifact, failing)
        if repaired is None:
            continue
        repaired_review = reviewer(repaired)
        if repaired_review.passed:
            return repaired, repaired_review
    if failing:
        review = replace(review, budget_exhausted=True)
    return artifact, review
