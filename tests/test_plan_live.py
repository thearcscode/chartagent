"""Live create_chart calls against Anthropic (issue #118, #119).

Skipped when ``ANTHROPIC_API_KEY`` is unset. Scripted-model tests never
omit ``outcome``; these replay the measured instructions on a real client.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import get_args

import pytest

from chartagent import ChartResult, create_chart_agent
from chartagent.frame.input import SourceBucket

_SALES = Path(__file__).with_name("data") / "sales_by_region.csv"
_MODEL = "anthropic:claude-sonnet-4-6"
_SOURCE_BUCKETS: frozenset[str] = frozenset(get_args(SourceBucket))
_VEGA_FIELD_TYPES = frozenset({"nominal", "quantitative", "temporal", "ordinal"})

pytestmark = pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY is unset",
)


@pytest.mark.parametrize(
    "instruction",
    (
        "Scatter plot of units versus revenue",
        "Bar chart of revenue by region",
    ),
)
def test_live_create_chart_returns_a_chart_result(instruction: str) -> None:
    from pydantic_ai.models import override_allow_model_requests

    agent = create_chart_agent(model=_MODEL)
    with override_allow_model_requests(True):
        result = agent.create_chart(_SALES, instruction)
    assert isinstance(result, ChartResult)
    envelope = result.envelope
    assert envelope.backend
    assert envelope.row_count > 0
    assert envelope.input["data"]["values"]
    if instruction == "Bar chart of revenue by region":
        encodings = envelope.input["chart_spec"]["encodings"]
        for encoding in encodings.values():
            assert isinstance(encoding, dict)
            field_type = encoding.get("type")
            assert field_type not in _SOURCE_BUCKETS
            if field_type is not None:
                assert field_type in _VEGA_FIELD_TYPES
