"""``critique(png, context) -> Critique`` — the leaf call (ADR-0026 Decisions
1, 2, 7, 8, 9)."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from chartagent.critique import (
    Critique,
    CritiqueContext,
    critique,
    to_check_outcome,
)
from chartagent.plan.client import ModelClient

_PNG = b"\x89PNG\r\n\x1a\nfake-bytes"


def _client(args: dict[str, Any]) -> ModelClient:
    def fn(_messages: object, info: AgentInfo) -> ModelResponse:
        name = info.output_tools[0].name
        return ModelResponse(parts=[ToolCallPart(tool_name=name, args=args)])

    client = ModelClient("test")
    client._model = FunctionModel(fn)  # type: ignore[assignment]
    return client


def _context(*items: str) -> CritiqueContext:
    return CritiqueContext(
        instruction="bar chart of revenue by quarter",
        chart_type="Bar Chart",
        backend="vegalite",
        encodings={"x": "quarter", "y": "revenue"},
        row_count=4,
        items=items,  # type: ignore[arg-type]
    )


@pytest.mark.parametrize(
    ("verdict", "outcome"),
    [
        ("pass", "pass"),
        ("fail", "fail"),
        ("cannot_determine", "not_checked"),
        ("not_applicable", "not_checked"),
    ],
)
def test_to_check_outcome_maps_the_four_valued_verdict(
    verdict: str, outcome: str
) -> None:
    assert to_check_outcome(verdict) == outcome  # type: ignore[arg-type]


def test_critique_returns_a_verdict_for_every_applicable_item() -> None:
    context = _context("marks_present", "label_overlap")
    client = _client(
        {"marks_present": "fail", "label_overlap": "pass", "note": "no bars drawn"}
    )
    result = critique(_PNG, context, client=client)
    assert isinstance(result, Critique)
    assert result.verdicts == {"marks_present": "fail", "label_overlap": "pass"}
    assert result.note == "no bars drawn"


def test_critique_never_asks_about_an_inapplicable_item() -> None:
    context = _context("marks_present")
    client = _client({"marks_present": "pass", "note": None})
    result = critique(_PNG, context, client=client)
    assert set(result.verdicts) == {"marks_present"}


def test_note_is_collapsed_to_one_line_and_capped() -> None:
    from chartagent.critique import _NOTE_CAP

    long_note = ("word " * 100) + "\n\nextra line"
    context = _context("marks_present")
    client = _client({"marks_present": "fail", "note": long_note})
    result = critique(_PNG, context, client=client)
    assert result.note is not None
    assert "\n" not in result.note
    assert len(result.note) <= _NOTE_CAP


def test_a_null_note_stays_none() -> None:
    context = _context("marks_present")
    client = _client({"marks_present": "pass", "note": None})
    result = critique(_PNG, context, client=client)
    assert result.note is None


def test_sends_the_png_as_an_image_content_part() -> None:
    seen: dict[str, Any] = {}

    def fn(messages: object, info: AgentInfo) -> ModelResponse:
        # The user prompt is the most recent request part's content.
        assert isinstance(messages, list)
        request = messages[-1]
        seen["parts"] = getattr(request, "parts", ())
        name = info.output_tools[0].name
        return ModelResponse(parts=[ToolCallPart(tool_name=name, args={"note": None})])

    client = ModelClient("test")
    client._model = FunctionModel(fn)  # type: ignore[assignment]
    context = CritiqueContext(
        instruction="x",
        chart_type="Bar Chart",
        backend="vegalite",
        encodings={},
        row_count=1,
        items=(),
    )
    critique(_PNG, context, client=client)
    user_prompt_part = seen["parts"][-1]
    content = user_prompt_part.content
    assert isinstance(content, list)
    assert any(getattr(part, "data", None) == _PNG for part in content)
