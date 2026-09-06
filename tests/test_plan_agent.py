"""create_chart_agent / create_chart — sequence, budgets, errors (issue #108)."""

from __future__ import annotations

import ast
import inspect
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

import chartagent
from chartagent import ChartAgent, ChartResult, create_chart_agent
from chartagent.errors import (
    BackendCapabilityError,
    ChartAgentError,
    InexpressibleRequestError,
    PlannerFailureError,
    SchemaDriftError,
    SpecShapeError,
    UnanswerableInstructionError,
)
from chartagent.frame.input import DEFAULT_BASE_SIZE
from chartagent.result import ChartResult as ResultFromStablePath

_FIXTURES = Path(__file__).with_name("data")
_SALES = _FIXTURES / "sales.csv"
_SALES_BY_REGION = _FIXTURES / "sales_by_region.csv"
_FORBIDDEN_KWARGS = (
    "sandbox",
    "outputs",
    "quality",
    "history",
    "backend",
    "default_backend",
    "timeout",
)

_TRANSFORM = {
    "group_by": ["quarter"],
    "aggregate": [{"name": "total", "op": "sum", "field": "revenue"}],
}
_FRAGMENT: dict[str, Any] = {
    "outcome": "fragment",
    "chart_type": "Bar Chart",
    "encodings": {"x": {"field": "quarter"}, "y": {"field": "total"}},
    "transform": _TRANSFORM,
    "semantic_types": {"total": "Quantity"},
    "requested_backend": None,
}
_SANKEY: dict[str, Any] = {
    "outcome": "fragment",
    "chart_type": "Sankey Diagram",
    "encodings": {
        "x": {"field": "quarter"},
        "y": {"field": "revenue"},
        "size": {"field": "revenue"},
    },
    "transform": None,
    "semantic_types": {},
    "requested_backend": "vegalite",
}


def _reply(
    kind: str, args: dict[str, Any] | None = None
) -> Callable[..., ModelResponse]:
    def fn(_messages: object, info: AgentInfo) -> ModelResponse:
        if kind == "empty":
            return ModelResponse(parts=[])
        if kind == "step2":
            name = info.output_tools[0].name
            return ModelResponse(parts=[ToolCallPart(tool_name=name, args=args or {})])
        name = next(tool.name for tool in info.output_tools if kind in tool.name)
        return ModelResponse(parts=[ToolCallPart(tool_name=name, args=args or {})])

    return fn


def _install(agent: ChartAgent, *replies: Any) -> dict[str, int]:
    queue = list(replies)
    calls = {"model": 0, "step2": 0}

    def fn(messages: object, info: AgentInfo) -> ModelResponse:
        calls["model"] += 1
        if len(info.output_tools) == 1:
            calls["step2"] += 1
        reply = queue.pop(0)
        if isinstance(reply, tuple):
            kind, args = reply
            return _reply(kind, args)(messages, info)
        return _reply(reply)(messages, info)

    agent._client._model = FunctionModel(fn)  # type: ignore[assignment]
    return calls


def _agent() -> ChartAgent:
    return create_chart_agent(model="test")


def test_public_surface_grows_by_exactly_two_and_chart_result_stays() -> None:
    assert "create_chart_agent" in chartagent.__all__
    assert "ChartAgent" in chartagent.__all__
    assert chartagent.create_chart_agent is create_chart_agent
    assert chartagent.ChartAgent is ChartAgent
    assert ResultFromStablePath is ChartResult
    assert "Fragment" not in chartagent.__all__
    assert "ModelClient" not in chartagent.__all__
    assert not hasattr(chartagent, "Fragment")
    assert not hasattr(chartagent, "ModelClient")


def test_signatures_admit_no_p1_kwargs() -> None:
    factory = inspect.signature(create_chart_agent)
    assert list(factory.parameters) == ["model"]
    assert factory.parameters["model"].kind is inspect.Parameter.KEYWORD_ONLY
    create = inspect.signature(ChartAgent.create_chart)
    assert list(create.parameters) == ["self", "data", "instruction"]
    for name in _FORBIDDEN_KWARGS:
        assert name not in factory.parameters
        assert name not in create.parameters
        assert name not in inspect.signature(ChartAgent.__init__).parameters


def test_scripted_inexpressible_raises_after_exactly_one_call() -> None:
    agent = _agent()
    calls = _install(
        agent, ("Inexpressible", {"outcome": "inexpressible", "bucket": 1})
    )
    with pytest.raises(InexpressibleRequestError) as caught:
        agent.create_chart(_SALES, "a 3D holographic globe")
    assert caught.value.bucket == 1
    assert calls["model"] == 1
    assert calls["step2"] == 0


def test_scripted_unanswerable_against_a_missing_column_is_one_call() -> None:
    agent = _agent()
    calls = _install(
        agent,
        (
            "Unanswerable",
            {
                "outcome": "unanswerable",
                "kind": "missing_column",
                "keys": ["sentiment"],
            },
        ),
    )
    with pytest.raises(UnanswerableInstructionError) as caught:
        agent.create_chart(_SALES, "chart sentiment")
    assert caught.value.kind == "missing_column"
    assert caught.value.keys == ("sentiment",)
    assert calls["model"] == 1


def test_refuted_missing_column_is_retried_then_planner_failure() -> None:
    agent = _agent()
    payload = {
        "outcome": "unanswerable",
        "kind": "missing_column",
        "keys": ["quarter"],
    }
    calls = _install(agent, ("Unanswerable", payload), ("Unanswerable", payload))
    with pytest.raises(PlannerFailureError) as caught:
        agent.create_chart(_SALES, "revenue by quarter")
    assert not isinstance(caught.value, UnanswerableInstructionError)
    assert caught.value.reason == "invalid_emit"
    assert calls["model"] == 2


def test_refuted_missing_role_is_the_same_path() -> None:
    agent = _agent()
    payload = {
        "outcome": "unanswerable",
        "kind": "missing_role",
        "keys": ["string"],
    }
    calls = _install(agent, ("Unanswerable", payload), ("Unanswerable", payload))
    with pytest.raises(PlannerFailureError) as caught:
        agent.create_chart(_SALES, "chart the labels")
    assert caught.value.reason == "invalid_emit"
    assert calls["model"] == 2


def test_empty_keys_pass_through_as_the_unspecific_ask() -> None:
    agent = _agent()
    calls = _install(
        agent,
        (
            "Unanswerable",
            {"outcome": "unanswerable", "kind": "missing_role", "keys": []},
        ),
    )
    with pytest.raises(UnanswerableInstructionError) as caught:
        agent.create_chart(_SALES, "make it look nicer")
    assert caught.value.kind == "missing_role"
    assert caught.value.keys == ()
    assert calls["model"] == 1


def test_facade_failure_costs_exactly_two_step1_calls() -> None:
    agent = _agent()
    bad = {
        **_FRAGMENT,
        "encodings": {"not_a_channel": {"field": "quarter"}},
    }
    calls = _install(agent, ("Fragment", bad), ("Fragment", bad))
    with pytest.raises(PlannerFailureError) as caught:
        agent.create_chart(_SALES, "revenue by quarter")
    assert caught.value.reason == "invalid_emit"
    assert calls["model"] == 2
    assert calls["step2"] == 0


def test_fragment_tool_call_omitting_outcome_is_not_invalid_emit() -> None:
    payload = {key: value for key, value in _FRAGMENT.items() if key != "outcome"}
    agent = _agent()
    calls = _install(agent, ("Fragment", payload), ("step2", {}))
    result = agent.create_chart(_SALES, "revenue by quarter")
    assert isinstance(result, ChartResult)
    assert calls["model"] == 2
    assert calls["step2"] == 1


_MEASURED_LIVE_STEP1: dict[str, Any] = {
    "chart_type": "Bar Chart",
    "encodings": {
        "x": {"field": "region", "type": "Category"},
        "y": {"field": "revenue", "type": "Amount"},
    },
    "transform": {
        "group_by": ["region"],
        "aggregate": [{"op": "sum", "field": "revenue", "as": "revenue"}],
    },
    "semantic_types": {"region": "Category", "revenue": "Amount"},
    "requested_backend": None,
}

# Measured live step-1 fragment (issue #119): well-formed transform, source-bucket
# encoding types. Bind would succeed; Vega-Lite would not draw.
_MEASURED_SOURCE_BUCKET_TYPES: dict[str, Any] = {
    "outcome": "fragment",
    "chart_type": "Bar Chart",
    "encodings": {
        "x": {"field": "region", "type": "string"},
        "y": {"field": "total_revenue", "type": "number"},
    },
    "transform": {
        "group_by": ["region"],
        "aggregate": [
            {"name": "total_revenue", "op": "sum", "field": "revenue"},
        ],
    },
    "semantic_types": {"region": "Region", "total_revenue": "Amount"},
    "requested_backend": None,
}


def test_nameless_aggregate_is_not_a_bind_time_spec_shape_error() -> None:
    bad = {
        **_FRAGMENT,
        "transform": {
            "group_by": ["quarter"],
            "aggregate": [{"op": "sum", "field": "revenue", "as": "revenue"}],
        },
    }
    agent = _agent()
    calls = _install(agent, ("Fragment", bad), ("Fragment", bad))
    with pytest.raises(PlannerFailureError) as caught:
        agent.create_chart(_SALES, "revenue by quarter")
    assert not isinstance(caught.value, SpecShapeError)
    assert caught.value.reason == "invalid_emit"
    assert calls["model"] == 2
    assert calls["step2"] == 0


def test_measured_live_payload_is_invalid_emit_not_a_bind_error() -> None:
    agent = _agent()
    calls = _install(
        agent, ("Fragment", _MEASURED_LIVE_STEP1), ("Fragment", _MEASURED_LIVE_STEP1)
    )
    with pytest.raises(PlannerFailureError) as caught:
        agent.create_chart(_SALES, "Bar chart of revenue by region")
    assert not isinstance(caught.value, SpecShapeError)
    assert caught.value.reason == "invalid_emit"
    assert calls["model"] == 2
    assert calls["step2"] == 0


def test_source_bucket_encoding_types_are_invalid_emit() -> None:
    agent = _agent()
    calls = _install(
        agent,
        ("Fragment", _MEASURED_SOURCE_BUCKET_TYPES),
        ("Fragment", _MEASURED_SOURCE_BUCKET_TYPES),
    )
    with pytest.raises(PlannerFailureError) as caught:
        agent.create_chart(_SALES_BY_REGION, "Bar chart of revenue by region")
    assert caught.value.reason == "invalid_emit"
    assert calls["model"] == 2
    assert calls["step2"] == 0


def test_vega_encoding_types_still_return_a_chart_result() -> None:
    fragment = {
        **_FRAGMENT,
        "encodings": {
            "x": {"field": "quarter", "type": "nominal"},
            "y": {"field": "total", "type": "quantitative"},
        },
    }
    agent = _agent()
    calls = _install(agent, ("Fragment", fragment), ("step2", {}))
    result = agent.create_chart(_SALES, "revenue by quarter")
    assert isinstance(result, ChartResult)
    encodings = result.envelope.input["chart_spec"]["encodings"]
    assert encodings["x"]["type"] == "nominal"
    assert encodings["y"]["type"] == "quantitative"
    assert calls["model"] == 2
    assert calls["step2"] == 1


def test_unknown_transform_slot_is_not_a_bind_time_spec_shape_error() -> None:
    agent = _agent()
    bad = {**_FRAGMENT, "transform": {"pivot": []}}
    calls = _install(agent, ("Fragment", bad), ("Fragment", bad))
    with pytest.raises(PlannerFailureError) as caught:
        agent.create_chart(_SALES, "pivot the quarters")
    assert not isinstance(caught.value, SpecShapeError)
    assert caught.value.reason == "invalid_emit"
    assert calls["model"] == 2
    assert calls["step2"] == 0


def test_chart_properties_failing_their_model_cost_three_step2_calls() -> None:
    agent = _agent()
    calls = _install(
        agent,
        ("Fragment", _FRAGMENT),
        ("step2", {"notAKey": 1}),
        ("step2", {"notAKey": 1}),
        ("step2", {"notAKey": 1}),
    )
    with pytest.raises(PlannerFailureError) as caught:
        agent.create_chart(_SALES, "revenue by quarter")
    assert caught.value.reason == "invalid_emit"
    assert calls["model"] == 4
    assert calls["step2"] == 3


def test_no_run_exceeds_five_calls_and_the_cap_cannot_bind() -> None:
    assert 1 + 1 + 1 + 2 == 5
    agent = _agent()
    calls = _install(
        agent,
        ("Fragment", {**_FRAGMENT, "transform": {"pivot": []}}),
        ("Fragment", _FRAGMENT),
        ("step2", {"notAKey": 1}),
        ("step2", {"notAKey": 1}),
        ("step2", {"notAKey": 1}),
    )
    with pytest.raises(PlannerFailureError) as caught:
        agent.create_chart(_SALES, "revenue by quarter")
    assert caught.value.reason == "invalid_emit"
    assert calls["model"] == 5
    assert calls["model"] <= 5


def test_empty_step_is_empty_response() -> None:
    agent = _agent()
    calls = _install(agent, "empty", "empty")
    with pytest.raises(PlannerFailureError) as caught:
        agent.create_chart(_SALES, "revenue by quarter")
    assert caught.value.reason == "empty_response"
    assert calls["model"] == 2


def test_happy_path_over_committed_csv_then_zero_llm_refresh() -> None:
    agent = _agent()
    calls = _install(agent, ("Fragment", _FRAGMENT), ("step2", {}))
    snapshot = dict(vars(agent))
    result = agent.create_chart(_SALES, "revenue by quarter")
    assert vars(agent) == snapshot
    assert isinstance(result, ChartResult)
    input_frame = result.envelope.input
    assert "backend" not in input_frame
    assert input_frame["x_chartagent"]["spec_version"] == "1.2"
    assert input_frame["x_chartagent"]["source_schema"] == {
        "quarter": "string",
        "revenue": "number",
    }
    assert input_frame["chart_spec"]["baseSize"] == DEFAULT_BASE_SIZE.model_dump(
        mode="json"
    )
    assert result.envelope.backend == "vegalite"
    values = input_frame["data"]["values"]
    assert {row["quarter"]: row["total"] for row in values} == {"Q1": 100, "Q2": 200}
    planned_calls = calls["model"]
    refreshed = result.refresh(
        [
            {"quarter": "Q1", "revenue": 100},
            {"quarter": "Q2", "revenue": 200},
            {"quarter": "Q3", "revenue": 300},
        ]
    )
    assert calls["model"] == planned_calls
    assert refreshed.envelope.row_count == 3
    assert refreshed is not result


def test_bind_errors_surface_unwrapped_and_are_chart_agent_errors() -> None:
    agent = _agent()
    fragment = {
        **_FRAGMENT,
        "transform": {
            "filter": {
                "kind": "is_not_null",
                "args": [{"kind": "col", "name": "missing"}],
            }
        },
        "encodings": {
            "x": {"field": "quarter"},
            "y": {"field": "revenue"},
        },
        "semantic_types": {"revenue": "Quantity"},
    }
    _install(agent, ("Fragment", fragment), ("step2", {}))
    try:
        agent.create_chart(_SALES, "drop missing")
    except ChartAgentError as caught:
        assert isinstance(caught, SchemaDriftError)
        assert caught.stage == "source"
    else:
        raise AssertionError("expected SchemaDriftError")


def test_requested_backend_capability_miss_never_calls_step2() -> None:
    agent = _agent()
    calls = _install(agent, ("Fragment", _SANKEY))
    with pytest.raises(BackendCapabilityError) as caught:
        agent.create_chart(_SALES, "sankey in vegalite")
    assert caught.value.kind == "chart_type"
    assert caught.value.backend == "vegalite"
    assert calls["model"] == 1
    assert calls["step2"] == 0


def test_no_chart_recipe_and_no_escape_reason_are_written() -> None:
    source = Path(chartagent.ChartAgent.create_chart.__code__.co_filename).read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom | ast.Import):
            names.extend(alias.name for alias in node.names)
            if isinstance(node, ast.ImportFrom) and node.module is not None:
                names.append(node.module)
        elif isinstance(node, ast.Name):
            names.append(node.id)
        elif isinstance(node, ast.Attribute):
            names.append(node.attr)
    assert "ChartRecipe" not in names
    assert "escape_reason" not in names
    assert "EscapeReason" not in names
