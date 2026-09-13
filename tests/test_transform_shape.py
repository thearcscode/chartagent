"""Data-free transform shape check, extracted from ``run_transform`` (#101)."""

from __future__ import annotations

import pytest

import chartagent
from chartagent.errors import SpecShapeError
from chartagent.transform.expr import check_expr_shape
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


# --- #143: closed keys inside slot items and on Expr nodes ---------------
# ADR-0023 Decision 4; ADR-0008 Decision 13 erratum. `_apply_sort_limit`
# used to read `item.get("dir", "asc")` and silently ignore every other
# key, so a sort item shaped `{field, order}` bound and drew ascending
# regardless of `order`'s value (settled in #139).

# Measured live emit: Vega-Lite `order` instead of menu `dir`/`nulls`.
_MEASURED_SORT_ORDER = [{"field": "revenue", "order": "descending"}]


def test_sort_item_order_key_is_a_spec_shape_error() -> None:
    with pytest.raises(
        SpecShapeError,
        match=r"transform\.sort\[0\]: unrecognised key\(s\) \('order',\)",
    ):
        check_transform_shape({"sort": _MEASURED_SORT_ORDER})


def test_sort_item_legal_keys_pass() -> None:
    check_transform_shape(
        {"sort": [{"field": "revenue", "dir": "desc", "nulls": "first"}]}
    )


def test_aggregate_item_unrecognised_key_is_a_spec_shape_error() -> None:
    with pytest.raises(
        SpecShapeError,
        match=r"transform\.aggregate\[0\]: unrecognised key\(s\) \('extra',\)",
    ):
        check_transform_shape(
            {"aggregate": [{"name": "n", "op": "sum", "field": "revenue", "extra": 1}]}
        )


def test_aggregate_item_legal_keys_pass() -> None:
    check_transform_shape({"aggregate": [{"name": "n", "op": "sum", "field": "x"}]})


def test_bin_item_unrecognised_key_is_a_spec_shape_error() -> None:
    with pytest.raises(
        SpecShapeError,
        match=r"transform\.bin\[0\]: unrecognised key\(s\) \('scale',\)",
    ):
        check_transform_shape(
            {"bin": [{"name": "b", "field": "revenue", "width": 10, "scale": "log"}]}
        )


def test_bin_item_legal_keys_pass() -> None:
    check_transform_shape({"bin": [{"name": "b", "field": "ts", "unit": "month"}]})
    check_transform_shape(
        {"bin": [{"name": "b", "field": "revenue", "width": 10, "origin": 0}]}
    )


def test_derive_item_unrecognised_key_is_a_spec_shape_error() -> None:
    with pytest.raises(
        SpecShapeError,
        match=r"transform\.derive\[0\]: unrecognised key\(s\) \('as',\)",
    ):
        check_transform_shape(
            {
                "derive": [
                    {"name": "x", "expr": {"kind": "lit", "value": 1}, "as": "y"}
                ]
            }
        )


def test_derive_item_legal_keys_pass() -> None:
    check_transform_shape(
        {"derive": [{"name": "x", "expr": {"kind": "lit", "value": 1}}]}
    )


def test_limit_unrecognised_key_is_a_spec_shape_error() -> None:
    with pytest.raises(
        SpecShapeError,
        match=r"transform\.limit: unrecognised key\(s\) \('page',\)",
    ):
        check_transform_shape({"limit": {"count": 10, "page": 2}})


def test_limit_legal_keys_pass() -> None:
    check_transform_shape({"limit": {"count": 10, "offset": 5}})


# Named example from the ticket: an `alias` on a `col` inside `filter.args`.
def test_filter_arg_col_alias_is_a_spec_shape_error() -> None:
    with pytest.raises(
        SpecShapeError,
        match=r"transform\.filter\.args\[0\]: unrecognised key\(s\) \('alias',\)",
    ):
        check_transform_shape(
            {
                "filter": {
                    "kind": "eq",
                    "args": [
                        {"kind": "col", "name": "x", "alias": "y"},
                        {"kind": "lit", "value": 1},
                    ],
                }
            }
        )


def test_expr_col_unrecognised_key_is_a_spec_shape_error() -> None:
    with pytest.raises(SpecShapeError, match=r"x: unrecognised key\(s\) \('alias',\)"):
        check_expr_shape({"kind": "col", "name": "x", "alias": "y"}, path="x")


def test_expr_lit_unrecognised_key_is_a_spec_shape_error() -> None:
    with pytest.raises(SpecShapeError, match=r"x: unrecognised key\(s\) \('label',\)"):
        check_expr_shape({"kind": "lit", "value": 1, "label": "n"}, path="x")


def test_expr_unary_unrecognised_key_is_a_spec_shape_error() -> None:
    with pytest.raises(SpecShapeError, match=r"x: unrecognised key\(s\) \('note',\)"):
        check_expr_shape(
            {"kind": "neg", "args": [{"kind": "lit", "value": 1}], "note": "n"},
            path="x",
        )


def test_expr_binary_unrecognised_key_is_a_spec_shape_error() -> None:
    with pytest.raises(SpecShapeError, match=r"x: unrecognised key\(s\) \('note',\)"):
        check_expr_shape(
            {
                "kind": "add",
                "args": [{"kind": "lit", "value": 1}, {"kind": "lit", "value": 2}],
                "note": "n",
            },
            path="x",
        )


def test_expr_nary_unrecognised_key_is_a_spec_shape_error() -> None:
    with pytest.raises(SpecShapeError, match=r"x: unrecognised key\(s\) \('note',\)"):
        check_expr_shape(
            {
                "kind": "and",
                "args": [
                    {"kind": "lit", "value": True},
                    {"kind": "lit", "value": False},
                ],
                "note": "n",
            },
            path="x",
        )


def test_expr_between_unrecognised_key_is_a_spec_shape_error() -> None:
    with pytest.raises(SpecShapeError, match=r"x: unrecognised key\(s\) \('note',\)"):
        check_expr_shape(
            {
                "kind": "between",
                "args": [
                    {"kind": "col", "name": "x"},
                    {"kind": "lit", "value": 1},
                    {"kind": "lit", "value": 2},
                ],
                "note": "n",
            },
            path="x",
        )


def test_expr_in_unrecognised_key_is_a_spec_shape_error() -> None:
    with pytest.raises(SpecShapeError, match=r"x: unrecognised key\(s\) \('note',\)"):
        check_expr_shape(
            {
                "kind": "in",
                "args": [{"kind": "col", "name": "x"}, {"kind": "lit", "value": 1}],
                "note": "n",
            },
            path="x",
        )


def test_expr_case_unrecognised_key_is_a_spec_shape_error() -> None:
    with pytest.raises(SpecShapeError, match=r"x: unrecognised key\(s\) \('note',\)"):
        check_expr_shape(
            {
                "kind": "case",
                "whens": [
                    {
                        "when": {"kind": "lit", "value": True},
                        "then": {"kind": "lit", "value": 1},
                    }
                ],
                "else": {"kind": "lit", "value": 0},
                "note": "n",
            },
            path="x",
        )


def test_expr_case_when_item_unrecognised_key_is_a_spec_shape_error() -> None:
    with pytest.raises(
        SpecShapeError, match=r"x\.whens\[0\]: unrecognised key\(s\) \('label',\)"
    ):
        check_expr_shape(
            {
                "kind": "case",
                "whens": [
                    {
                        "when": {"kind": "lit", "value": True},
                        "then": {"kind": "lit", "value": 1},
                        "label": "hi",
                    }
                ],
                "else": {"kind": "lit", "value": 0},
            },
            path="x",
        )


def test_expr_legal_keys_pass_for_every_kind() -> None:
    check_expr_shape({"kind": "col", "name": "x"}, path="x")
    check_expr_shape({"kind": "lit", "value": 1}, path="x")
    check_expr_shape({"kind": "neg", "args": [{"kind": "lit", "value": 1}]}, path="x")
    check_expr_shape(
        {
            "kind": "eq",
            "args": [{"kind": "lit", "value": 1}, {"kind": "lit", "value": 1}],
        },
        path="x",
    )
    check_expr_shape(
        {
            "kind": "between",
            "args": [
                {"kind": "col", "name": "x"},
                {"kind": "lit", "value": 1},
                {"kind": "lit", "value": 2},
            ],
        },
        path="x",
    )
    check_expr_shape(
        {
            "kind": "in",
            "args": [{"kind": "col", "name": "x"}, {"kind": "lit", "value": 1}],
        },
        path="x",
    )
    check_expr_shape(
        {
            "kind": "case",
            "whens": [
                {
                    "when": {"kind": "lit", "value": True},
                    "then": {"kind": "lit", "value": 1},
                }
            ],
            "else": {"kind": "lit", "value": 0},
        },
        path="x",
    )
