"""Data-free transform shape check, extracted from ``run_transform`` (#101)."""

from __future__ import annotations

import pytest

import chartagent
from chartagent.errors import SpecShapeError
from chartagent.transform.menu import check_transform_shape


def test_absent_and_empty_transforms_pass_through() -> None:
    check_transform_shape(None)
    check_transform_shape({})


def test_unrecognised_slot_is_a_spec_shape_error() -> None:
    with pytest.raises(SpecShapeError, match="unrecognised transform slot"):
        check_transform_shape({"pivot": []})


def test_raw_sql_cannot_mix_with_a_menu_slot() -> None:
    with pytest.raises(SpecShapeError, match="raw_sql cannot mix with menu slots"):
        check_transform_shape({"raw_sql": "SELECT 1", "filter": {"kind": "lit"}})


def test_raw_sql_alone_is_shape_ok() -> None:
    check_transform_shape({"raw_sql": "SELECT 1 FROM source"})


def test_check_transform_shape_is_not_on_the_public_surface() -> None:
    assert "check_transform_shape" not in chartagent.__all__
    assert not hasattr(chartagent, "check_transform_shape")


# Measured live emit (issue #118): Vega-Lite `as` instead of menu `name`.
_MEASURED_AGGREGATE_AS = [{"op": "sum", "field": "revenue", "as": "revenue"}]


def test_aggregate_item_without_name_is_a_spec_shape_error() -> None:
    with pytest.raises(
        SpecShapeError, match=r"transform\.aggregate\[0\]\.name is required"
    ):
        check_transform_shape(
            {"group_by": ["region"], "aggregate": _MEASURED_AGGREGATE_AS}
        )


def test_as_is_not_accepted_as_an_aggregate_name() -> None:
    check_transform_shape(
        {
            "group_by": ["region"],
            "aggregate": [{"name": "revenue", "op": "sum", "field": "revenue"}],
        }
    )
    with pytest.raises(
        SpecShapeError, match=r"transform\.aggregate\[0\]\.name is required"
    ):
        check_transform_shape({"aggregate": [{"as": "revenue", "op": "sum"}]})
