"""ChartRecipe.from_dict / to_dict / canonical_json — ADR-0018 Decisions 7, 9."""

from __future__ import annotations

import copy
import json
from typing import Any

import pytest

from chartagent import ChartRecipe, canonical_json
from chartagent.errors import SpecShapeError
from chartagent.frame.input import ThemeSpec
from chartagent.transform.model import Menu, RawSql

_MENU = {
    "group_by": ["quarter"],
    "aggregate": [{"name": "total", "op": "sum", "field": "revenue"}],
}


def _payload(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "spec_version": "1.2",
        "transform": copy.deepcopy(_MENU),
        "source_schema": {"quarter": "string", "revenue": "number"},
        "escape_reason": {"bucket": 3},
        "theme_spec": None,
        "document": {
            "module": "export default function render() {}",
            "styles": None,
            "libraries": [{"name": "echarts", "version": "5.5.0", "sha256": "0" * 64}],
        },
    }
    body.update(overrides)
    return body


def test_from_dict_builds_a_recipe() -> None:
    recipe = ChartRecipe.from_dict(_payload())
    assert isinstance(recipe.transform, Menu)
    assert recipe.escape_reason.bucket == 3
    assert recipe.document.libraries[0].name == "echarts"
    assert recipe.document.contract_version == 1
    assert recipe.theme_spec is None


def test_from_dict_accepts_raw_sql_and_theme_spec() -> None:
    recipe = ChartRecipe.from_dict(
        _payload(
            transform={"raw_sql": "SELECT 1 AS x FROM source"},
            theme_spec={"name": "mine", "colors": ["#fff"]},
        )
    )
    assert isinstance(recipe.transform, RawSql)
    assert isinstance(recipe.theme_spec, ThemeSpec)
    assert ChartRecipe.from_dict(_payload(theme_spec="retired-preset")).theme_spec == (
        "retired-preset"
    )


def test_round_trip_through_to_dict() -> None:
    recipe = ChartRecipe.from_dict(_payload())
    assert ChartRecipe.from_dict(recipe.to_dict()) == recipe
    assert ChartRecipe.from_dict(json.loads(recipe.canonical_json())) == recipe


def test_canonical_json_sorts_keys_omits_nulls_keeps_empties() -> None:
    body = _payload()
    body["document"]["libraries"] = []
    text = canonical_json(ChartRecipe.from_dict(body))
    parsed = json.loads(text)
    assert parsed["document"]["libraries"] == []
    assert "styles" not in parsed["document"]
    assert "theme_spec" not in parsed
    assert text == json.dumps(parsed, sort_keys=True, separators=(",", ":"))


def test_canonical_json_accepts_a_recipe_mapping_and_is_stable() -> None:
    a = canonical_json(_payload())
    b = canonical_json(dict(reversed(list(_payload().items()))))
    assert a == b == ChartRecipe.from_dict(_payload()).canonical_json()


@pytest.mark.parametrize(
    "bad",
    [
        {"spec_version": 1},
        {"escape_reason": {"bucket": 5}},
        {"escape_reason": {}},
        {"source_schema": {"a": "decimal"}},
        {"transform": {"bogus": 1}},
        {"transform": None},
        {"extra": 1},
        {"document": {"module": 3, "libraries": []}},
        {"document": {"module": "m"}},
        {"document": {"module": "m", "libraries": [{"name": "x"}]}},
    ],
)
def test_invalid_recipe_raises_a_typed_error(bad: dict[str, Any]) -> None:
    with pytest.raises(SpecShapeError):
        ChartRecipe.from_dict(_payload(**bad))


def test_non_mapping_raises_a_typed_error() -> None:
    with pytest.raises(SpecShapeError):
        ChartRecipe.from_dict([])  # type: ignore[arg-type]


def test_missing_field_raises() -> None:
    body = _payload()
    del body["document"]
    with pytest.raises(SpecShapeError):
        ChartRecipe.from_dict(body)
