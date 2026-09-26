"""The escalation trigger (ADR-0027 Decisions 2, 3, 6): a Flint
``marks_present`` fail at ``balanced``/``best`` yields an ``EscalationDecision``
carrying the failed frame's transform, source schema and theme spec. Reports
are hand-built here; producing a real ``marks_present`` fail is #201's."""

from __future__ import annotations

from typing import Literal

import pytest

from chartagent import InputFrame
from chartagent.plan.escalate import EscalationDecision, decide_escalation
from chartagent.recipe import ChartDocument, ChartRecipe, EscapeReason
from chartagent.review import CheckName, CheckResult, Outcome, ReviewReport
from chartagent.transform.model import Menu

_FRAME = InputFrame.model_validate(
    {
        "chart_spec": {
            "chartType": "Bar Chart",
            "encodings": {"x": {"field": "quarter"}, "y": {"field": "revenue"}},
        },
        "theme_spec": "nyt",
        "x_chartagent": {
            "transform": {"group_by": ["quarter"]},
            "source_schema": {"quarter": "string", "revenue": "number"},
        },
    }
)


def _report(
    *checks: tuple[CheckName, Outcome],
    tiers_run: tuple[int, ...] = (1, 2),
    passed: bool = False,
    budget_exhausted: bool = False,
) -> ReviewReport:
    return ReviewReport(
        tiers_run=tiers_run,
        tiers_skipped={},
        passed=passed,
        budget_exhausted=budget_exhausted,
        checks=tuple(CheckResult(name, outcome) for name, outcome in checks),
    )


_CHROME_NO_MARKS = _report(
    ("injection_pattern", "pass"),
    ("painted", "pass"),
    ("marks_present", "fail"),
)


@pytest.mark.parametrize("quality", ["balanced", "best"])
def test_marks_present_fail_escalates_above_fast(
    quality: Literal["balanced", "best"],
) -> None:
    decision = decide_escalation(_CHROME_NO_MARKS, _FRAME, quality=quality)
    assert isinstance(decision, EscalationDecision)


def test_fast_never_escalates() -> None:
    assert decide_escalation(_CHROME_NO_MARKS, _FRAME, quality="fast") is None


def test_decision_exposes_the_failed_frames_carry_over() -> None:
    decision = decide_escalation(_CHROME_NO_MARKS, _FRAME, quality="balanced")
    assert decision is not None
    assert decision.transform == Menu(group_by=["quarter"])
    assert decision.source_schema == {"quarter": "string", "revenue": "number"}
    assert decision.theme_spec == "nyt"


def test_a_frame_with_no_transform_or_baseline_carries_a_pass_through() -> None:
    bare = InputFrame.model_validate(
        {"chart_spec": {"chartType": "Bar Chart", "encodings": {}}}
    )
    decision = decide_escalation(_CHROME_NO_MARKS, bare, quality="best")
    assert decision is not None
    assert decision.transform == Menu()
    assert decision.source_schema == {}
    assert decision.theme_spec is None


@pytest.mark.parametrize(
    ("quality", "spent", "remaining"),
    [("balanced", 0, 1), ("balanced", 1, 0), ("best", 0, 2), ("best", 1, 1)],
)
def test_decision_carries_the_remaining_review_repair_budget(
    quality: Literal["balanced", "best"], spent: int, remaining: int
) -> None:
    decision = decide_escalation(
        _CHROME_NO_MARKS, _FRAME, quality=quality, repairs_spent=spent
    )
    assert decision is not None
    assert decision.remaining_repairs == remaining


def test_a_flint_marks_present_fail_consumes_no_repair() -> None:
    decision = decide_escalation(_CHROME_NO_MARKS, _FRAME, quality="balanced")
    assert decision is not None
    assert decision.remaining_repairs == 1


def test_a_blank_painted_fail_stays_on_rail() -> None:
    blank = _report(("injection_pattern", "pass"), ("painted", "fail"), tiers_run=(1,))
    assert decide_escalation(blank, _FRAME, quality="best") is None


def test_an_injection_fail_never_escalates() -> None:
    tainted = _report(
        ("injection_pattern", "fail"), ("marks_present", "fail"), tiers_run=(1, 2)
    )
    assert decide_escalation(tainted, _FRAME, quality="best") is None


def test_exhausted_presentational_repairs_stay_on_rail() -> None:
    exhausted = _report(
        ("injection_pattern", "pass"),
        ("painted", "pass"),
        ("marks_present", "pass"),
        ("axis_labels_present", "fail"),
        budget_exhausted=True,
    )
    assert decide_escalation(exhausted, _FRAME, quality="best") is None


def test_a_marks_present_not_checked_does_not_escalate() -> None:
    abstained = _report(
        ("injection_pattern", "pass"),
        ("painted", "pass"),
        ("marks_present", "not_checked"),
    )
    assert decide_escalation(abstained, _FRAME, quality="best") is None


def test_a_recipe_never_produces_a_second_escalate_decision() -> None:
    recipe = ChartRecipe(
        spec_version="1.2",
        transform=Menu(),
        source_schema={},
        escape_reason=EscapeReason(bucket=4),
        theme_spec=None,
        document=ChartDocument(module="", styles=None, libraries=()),
    )
    assert decide_escalation(_CHROME_NO_MARKS, recipe, quality="best") is None


def test_negative_repairs_spent_is_rejected() -> None:
    with pytest.raises(ValueError):
        decide_escalation(_CHROME_NO_MARKS, _FRAME, quality="best", repairs_spent=-1)
