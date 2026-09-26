"""ChartRecipe / bind_recipe — ADR-0018 Decisions 2, 3, 5, 6."""

from __future__ import annotations

from typing import Any

import pytest

import chartagent
from chartagent import (
    ChartDocument,
    ChartRecipe,
    EscapeReason,
    LibraryPin,
    bind_recipe,
)
from chartagent.errors import SchemaDriftError
from chartagent.recipe import BoundRecipe
from chartagent.transform.model import Menu, RawSql

_ROWS = [
    {"quarter": "Q1", "revenue": 100},
    {"quarter": "Q1", "revenue": 50},
    {"quarter": "Q2", "revenue": 200},
]
_MENU = Menu.model_validate(
    {
        "group_by": ["quarter"],
        "aggregate": [{"name": "total", "op": "sum", "field": "revenue"}],
    }
)
_DOCUMENT = ChartDocument(
    module="export default function render() {}",
    styles=None,
    libraries=(LibraryPin("echarts", "5.5.0", "0" * 64),),
)


def _recipe(**overrides: Any) -> ChartRecipe:
    fields: dict[str, Any] = {
        "spec_version": "1.2",
        "transform": _MENU,
        "source_schema": {"quarter": "string", "revenue": "number"},
        "escape_reason": EscapeReason(bucket=3),
        "theme_spec": None,
        "document": _DOCUMENT,
    }
    fields.update(overrides)
    return ChartRecipe(**fields)


class _Untouchable:
    """Any read of the document's code is a failure (ADR-0018 Decision 6)."""

    def __getattribute__(self, name: str) -> Any:
        raise AssertionError(f"bind_recipe read document.{name}")


def test_bind_recipe_runs_the_transform_and_attaches_rows() -> None:
    bound = bind_recipe(_recipe(), _ROWS)
    assert isinstance(bound, BoundRecipe)
    assert sorted(bound.rows, key=lambda r: r["quarter"]) == [
        {"quarter": "Q1", "total": 150},
        {"quarter": "Q2", "total": 200},
    ]
    assert bound.row_count == 2
    assert bound.elapsed >= 0
    assert bound.source_schema == {"quarter": "string", "revenue": "number"}
    assert bound.warnings == ()


def test_bind_recipe_never_reads_the_document() -> None:
    bind_recipe(_recipe(document=_Untouchable()), _ROWS)


def test_bind_recipe_fails_on_drift_like_bind() -> None:
    with pytest.raises(SchemaDriftError) as caught:
        bind_recipe(_recipe(), [{"quarter": "Q3"}])
    assert caught.value.stage == "source"


def test_bind_recipe_flags_a_retype_against_the_baseline() -> None:
    with pytest.raises(SchemaDriftError):
        bind_recipe(_recipe(), [{"quarter": "Q1", "revenue": "lots"}])


def test_bind_recipe_reports_missing_baseline_as_retype_unchecked() -> None:
    bound = bind_recipe(_recipe(source_schema={}), _ROWS)
    assert [a.code for a in bound.warnings] == ["retype_unchecked"]


def test_bind_recipe_reports_raw_sql_and_empty_result() -> None:
    raw = RawSql(raw_sql="SELECT quarter, revenue FROM source WHERE revenue > 1000")
    bound = bind_recipe(_recipe(transform=raw), _ROWS)
    codes = {a.code for a in bound.warnings}
    assert {"raw_sql_used", "empty_result"} <= codes
    assert bound.rows == []


def test_bind_recipe_never_validates_theme_spec_against_the_pin() -> None:
    bound = bind_recipe(_recipe(theme_spec="preset-a-later-pin-retired"), _ROWS)
    assert bound.theme_spec == "preset-a-later-pin-retired"


def test_bound_recipe_has_no_wire_format() -> None:
    bound = bind_recipe(_recipe(), _ROWS)
    for name in ("to_dict", "model_dump", "model_dump_json", "canonical_json"):
        assert not hasattr(bound, name)


def test_the_recipe_has_six_fields_and_no_dropped_ones() -> None:
    fields = set(ChartRecipe.__dataclass_fields__)
    assert fields == {
        "spec_version",
        "transform",
        "source_schema",
        "escape_reason",
        "theme_spec",
        "document",
    }


def test_recipe_carrier_names_are_exported_together() -> None:
    for name in (
        "LibraryPin",
        "ChartDocument",
        "ChartRecipe",
        "bind_recipe",
        "EscapeReason",
    ):
        assert name in chartagent.__all__
        assert hasattr(chartagent, name)
