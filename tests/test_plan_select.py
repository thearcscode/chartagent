"""Backend selection: requested_backend, then the ranking (issue #102, ADR-0021)."""

from __future__ import annotations

import ast
import inspect
from collections import Counter
from pathlib import Path
from typing import get_args

import pytest

import chartagent
from chartagent.errors import BackendCapabilityError
from chartagent.frame._generated import ChartType
from chartagent.frame.capability import declared_backends
from chartagent.plan.select import select_backend

_UNION = get_args(ChartType)
_EXCLUSIVE = {
    "Sankey Diagram": "echarts",
    "Network Graph": "echarts",
    "Tree": "echarts",
    "Parallel Coordinates": "echarts",
    "Density Contour": "plotly",
    "Bubble Chart": "chartjs",
    "Combo Chart": "chartjs",
    "Doughnut Chart": "chartjs",
}
_BAR: dict[str, object] = {
    "x": {"field": "quarter"},
    "y": {"field": "revenue"},
}


def test_tier_2_partition_matches_the_shipped_pin() -> None:
    chosen = [select_backend(chart_type, {}) for chart_type in _UNION]
    counts = Counter(chosen)
    assert len(_UNION) == 48
    assert counts["vegalite"] == 36
    assert counts["echarts"] == 8
    assert counts["plotly"] == 1
    assert counts["chartjs"] == 3
    assert counts["excel"] == 0
    exactly_one = sum(
        1 for chart_type in _UNION if len(declared_backends(chart_type, {})) == 1
    )
    assert exactly_one == 8


def test_tier_2_never_returns_excel() -> None:
    for chart_type in _UNION:
        assert select_backend(chart_type, {}) != "excel"


def test_ranking_always_has_a_candidate_after_excluding_excel() -> None:
    for chart_type in _UNION:
        survivors = declared_backends(chart_type, {})
        assert survivors, chart_type
        without_excel = tuple(name for name in survivors if name != "excel")
        assert without_excel, chart_type
        select_backend(chart_type, {})


def test_exclusive_types_reach_their_backend_through_the_filter_alone() -> None:
    for chart_type, backend in _EXCLUSIVE.items():
        survivors = declared_backends(chart_type, {})
        assert survivors == (backend,), chart_type
        assert select_backend(chart_type, {}) == backend


def test_sankey_requested_as_vegalite_raises_chart_type() -> None:
    with pytest.raises(BackendCapabilityError) as caught:
        select_backend("Sankey Diagram", {}, requested_backend="vegalite")
    assert caught.value.kind == "chart_type"
    assert caught.value.backend == "vegalite"
    assert caught.value.chart_type == "Sankey Diagram"


def test_requested_excel_is_chosen_when_the_pair_survives() -> None:
    assert select_backend("Bar Chart", _BAR, requested_backend="excel") == "excel"


def test_requested_excel_with_a_column_encoding_raises_facet() -> None:
    encodings = {**_BAR, "column": {"field": "quarter"}}
    with pytest.raises(BackendCapabilityError) as caught:
        select_backend("Bar Chart", encodings, requested_backend="excel")
    assert caught.value.kind == "facet"
    assert caught.value.backend == "excel"
    assert "column" in caught.value.keys


def test_select_backend_is_not_on_the_public_surface() -> None:
    assert "select_backend" not in chartagent.__all__
    assert not hasattr(chartagent, "select_backend")


def test_select_backend_has_no_backend_or_default_backend_parameter() -> None:
    params = inspect.signature(select_backend).parameters
    assert "backend" not in params
    assert "default_backend" not in params


def test_select_does_not_construct_a_frame_or_call_bind() -> None:
    source = Path(select_backend.__code__.co_filename).read_text(encoding="utf-8")
    names: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom | ast.Import):
            names.extend(alias.name for alias in node.names)
            if isinstance(node, ast.ImportFrom) and node.module is not None:
                names.append(node.module)
        elif isinstance(node, ast.Name):
            names.append(node.id)
        elif isinstance(node, ast.Attribute):
            names.append(node.attr)
    assert "bind" not in names
    assert "InputFrame" not in names


def test_select_has_no_per_chart_type_special_case() -> None:
    source = Path(select_backend.__code__.co_filename).read_text(encoding="utf-8")
    for chart_type in _EXCLUSIVE:
        assert chart_type not in source
