"""Pin facts for the declared-capability filter (ADR-0012, issue #101)."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import get_args

import pytest

import chartagent
from chartagent.errors import BackendCapabilityError, SpecShapeError
from chartagent.frame._generated import ChartType, GeneratedProperties
from chartagent.frame.capability import (
    check_excel_facet,
    declared_backends,
    properties_model,
)
from chartagent.frame.input import InputFrame

_REPO = Path(__file__).resolve().parents[1]
_VOCAB = json.loads(
    (_REPO / "src" / "chartagent" / "frame" / "vocab.json").read_text(encoding="utf-8")
)
_BACKENDS = _VOCAB["backends"]
_UNION = frozenset(name for charts in _BACKENDS.values() for name in charts)
_PAIRS = tuple(
    (backend, chart_type)
    for backend, charts in _BACKENDS.items()
    for chart_type in charts
)
_BAR: dict[str, object] = {
    "x": {"field": "quarter"},
    "y": {"field": "revenue"},
}


def _frame(encodings: Mapping[str, object]) -> InputFrame:
    return InputFrame.model_validate(
        {
            "chart_spec": {
                "chartType": "Bar Chart",
                "encodings": encodings,
            }
        }
    )


def test_union_is_forty_eight_chart_types() -> None:
    assert len(_UNION) == 48
    assert _UNION == frozenset(get_args(ChartType))


def test_properties_model_resolves_every_declared_pair() -> None:
    assert len(_PAIRS) == 151
    for backend, chart_type in _PAIRS:
        model = properties_model(backend, chart_type)
        assert issubclass(model, GeneratedProperties)


def test_properties_model_rejects_an_undeclared_pair() -> None:
    with pytest.raises(SpecShapeError, match=r"no property model for"):
        properties_model("vegalite", "Sankey Diagram")


def test_declared_backends_is_non_empty_for_every_union_type() -> None:
    for chart_type in sorted(_UNION):
        survivors = declared_backends(chart_type, {})
        assert survivors, chart_type
        without_excel = tuple(name for name in survivors if name != "excel")
        assert without_excel, chart_type


def test_declared_backends_is_deterministic_and_includes_excel_without_facets() -> None:
    assert declared_backends("Bar Chart", {}) == (
        "vegalite",
        "echarts",
        "chartjs",
        "plotly",
        "excel",
    )


def test_excel_is_absent_from_declared_backends_when_a_facet_channel_is_present() -> (
    None
):
    for encodings in (
        {**_BAR, "column": {"field": "quarter"}},
        {**_BAR, "row": {"field": "quarter"}},
        {**_BAR, "column": {"field": "quarter"}, "row": {"field": "quarter"}},
    ):
        assert "excel" not in declared_backends("Bar Chart", encodings)
        with pytest.raises(BackendCapabilityError) as caught:
            check_excel_facet(_frame(encodings), "excel")
        assert caught.value.kind == "facet"


def test_excel_survives_declared_backends_without_facet_channels() -> None:
    assert "excel" in declared_backends("Bar Chart", _BAR)
    check_excel_facet(_frame(_BAR), "excel")


def test_capability_names_do_not_enter_the_public_surface() -> None:
    for name in (
        "declared_backends",
        "properties_model",
        "check_backend_chart_type",
        "check_excel_facet",
    ):
        assert name not in chartagent.__all__
        assert not hasattr(chartagent, name)
