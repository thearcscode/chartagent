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
from dataclasses import dataclass, replace
from typing import Generic, TypeVar

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


@dataclass(frozen=True)
class RepairOutcome(Generic[_A]):
    """The best artifact and its report. ``halted`` is the most recently
    reviewed artifact and its report when ``halt`` stopped the loop, else
    ``None``; ``spent`` is the asks charged."""

    artifact: _A
    review: ReviewReport
    spent: int
    halted: tuple[_A, ReviewReport] | None = None


def spend_repair_budget(
    artifact: _A,
    review: ReviewReport,
    budget: int,
    *,
    request: Callable[[_A, list[CheckName]], _A | None],
    reviewer: Callable[[_A], ReviewReport],
    repairable: frozenset[CheckName] | None = None,
    halt: Callable[[ReviewReport, int], bool] | None = None,
) -> RepairOutcome[_A]:
    """``request`` returns ``None`` for a discarded ask. ``halt`` is read on the
    most recently reviewed report with the asks spent so far, before every round
    and after the last one; when it fires the loop stops with no further ask and
    reports that artifact in ``halted``. Never raises on review."""
    failing = _repairable_failures(review, repairable)
    latest: tuple[_A, ReviewReport] = (artifact, review)
    spent = 0
    while True:
        if halt is not None and halt(latest[1], spent):
            return RepairOutcome(artifact, review, spent, halted=latest)
        if budget <= 0 or not failing:
            break
        budget -= 1
        spent += 1
        repaired = request(artifact, failing)
        if repaired is None:
            continue
        repaired_review = reviewer(repaired)
        if repaired_review.passed:
            return RepairOutcome(repaired, repaired_review, spent)
        latest = (repaired, repaired_review)
    if failing:
        review = replace(review, budget_exhausted=True)
    return RepairOutcome(artifact, review, spent)
