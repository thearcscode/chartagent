"""ADR-0020: the three P1 planner errors. No raising site exists yet (the
planner is #92's), so these test the typed shape directly.
"""

from __future__ import annotations

import chartagent
from chartagent.errors import (
    ChartAgentError,
    InexpressibleRequestError,
    ModelClientUnavailableError,
    PlannerFailureError,
    UnanswerableInstructionError,
)


def test_inexpressible_request_error_carries_its_bucket() -> None:
    err = InexpressibleRequestError("no chart type fits", bucket=1)
    assert isinstance(err, ChartAgentError)
    assert err.bucket == 1


def test_unanswerable_instruction_error_missing_column() -> None:
    err = UnanswerableInstructionError(
        "sentiment is not a column",
        kind="missing_column",
        keys=("sentiment",),
    )
    assert isinstance(err, ChartAgentError)
    assert err.kind == "missing_column"
    assert err.keys == ("sentiment",)


def test_unanswerable_instruction_error_missing_role_names_buckets() -> None:
    err = UnanswerableInstructionError(
        "no temporal column to chart against",
        kind="missing_role",
        keys=("date", "timestamp", "timestamptz"),
    )
    assert err.kind == "missing_role"
    assert err.keys == ("date", "timestamp", "timestamptz")


def test_unanswerable_instruction_error_allows_empty_keys_for_an_unspecific_ask() -> (
    None
):
    err = UnanswerableInstructionError(
        "the instruction names no chart-worthy question",
        kind="missing_role",
        keys=(),
    )
    assert err.keys == ()


def test_planner_failure_error_carries_an_optional_reason() -> None:
    err = PlannerFailureError("gave up after retries", reason="retries_exhausted")
    assert err.reason == "retries_exhausted"
    bare = PlannerFailureError("no reason recorded")
    assert bare.reason is None


def test_none_of_the_three_are_exported_at_the_top_level() -> None:
    """chartagent.errors-only, matching every other error subclass (ADR-0020 D6)."""
    for name in (
        "InexpressibleRequestError",
        "UnanswerableInstructionError",
        "PlannerFailureError",
    ):
        assert name not in chartagent.__all__
        assert not hasattr(chartagent, name)


def test_model_client_unavailable_error_carries_the_extra() -> None:
    err = ModelClientUnavailableError(
        "install chartagent[anthropic]", extra="chartagent[anthropic]"
    )
    assert isinstance(err, ChartAgentError)
    assert err.extra == "chartagent[anthropic]"
    assert "ModelClientUnavailableError" not in chartagent.__all__
    assert not hasattr(chartagent, "ModelClientUnavailableError")
