"""The typed transform menu — one model for the fragment and the stored frame
(ADR-0023, issue #147). Replaces ``check_transform_shape``/``check_expr_shape``
(#137, #143) — those functions are deleted, not kept beside the model."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError

import chartagent
from chartagent.errors import SpecShapeError
from chartagent.frame.input import InputFrame
from chartagent.plan.schema import Fragment, Step1Result
from chartagent.transform.menu import TRANSFORM_SLOTS
from chartagent.transform.model import EXPR_KINDS, Menu

_STEP1: TypeAdapter[Any] = TypeAdapter(Step1Result)

_BASE_FRAGMENT: dict[str, Any] = {
    "outcome": "fragment",
    "chart_type": "Bar Chart",
    "encodings": {"x": {"field": "quarter"}, "y": {"field": "revenue"}},
    "semantic_types": {},
    "requested_backend": None,
}


def _fragment_with(transform: object) -> None:
    Fragment.model_validate({**_BASE_FRAGMENT, "transform": transform})


# ---------------------------------------------------------------------------
# The eight slots stay in sync with the canonical tuple (ADR-0023 D1).
# ---------------------------------------------------------------------------


def test_menu_fields_are_exactly_the_canonical_transform_slots_in_order() -> None:
    assert tuple(Menu.model_fields) == TRANSFORM_SLOTS
    assert len(TRANSFORM_SLOTS) == 8


# ---------------------------------------------------------------------------
# check_transform_shape/check_expr_shape are gone — the typed model is now
# the only shape truth, and it is not on the public surface.
# ---------------------------------------------------------------------------


def test_check_transform_shape_and_check_expr_shape_are_deleted() -> None:
    import chartagent.transform.expr as expr_mod
    import chartagent.transform.menu as menu_mod

    assert not hasattr(menu_mod, "check_transform_shape")
    assert not hasattr(expr_mod, "check_expr_shape")
    assert not hasattr(expr_mod, "check_no_unknown_keys")
    assert "check_transform_shape" not in chartagent.__all__


# ---------------------------------------------------------------------------
# Menu-level shape: unrecognised slots, raw_sql exclusivity.
# ---------------------------------------------------------------------------


def test_unrecognised_slot_fails_to_decode() -> None:
    with pytest.raises(ValidationError, match="unrecognised transform slot"):
        _fragment_with({"pivot": []})


def test_window_slot_fails_to_decode() -> None:
    with pytest.raises(ValidationError, match="unrecognised transform slot"):
        _fragment_with({"window": []})


def test_raw_sql_cannot_mix_with_a_menu_slot() -> None:
    with pytest.raises(ValidationError, match="raw_sql cannot mix with menu slots"):
        _fragment_with(
            {"raw_sql": "SELECT 1", "filter": {"kind": "lit", "value": True}}
        )


def test_raw_sql_mixed_with_an_unknown_slot_names_it_unrecognised() -> None:
    with pytest.raises(ValidationError, match="unrecognised transform slot"):
        _fragment_with({"raw_sql": "SELECT 1", "not_a_slot": 1})


def test_raw_sql_alone_decodes() -> None:
    _fragment_with({"raw_sql": "SELECT 1 FROM source"})


def test_absent_and_empty_transform_decode() -> None:
    _fragment_with(None)
    _fragment_with({})


# ---------------------------------------------------------------------------
# group_by + aggregate both empty (ADR-0023 D1) — the #139 measured miss.
# ---------------------------------------------------------------------------


def test_group_by_and_aggregate_both_empty_fails_to_decode() -> None:
    with pytest.raises(ValidationError, match="are empty"):
        _fragment_with({"group_by": [], "aggregate": []})
    with pytest.raises(ValidationError, match="are empty"):
        _fragment_with({"group_by": []})


def test_group_by_alone_is_legal_shape() -> None:
    _fragment_with({"group_by": ["quarter"]})


def test_aggregate_alone_is_legal_shape() -> None:
    _fragment_with({"aggregate": [{"name": "n", "op": "count"}]})


def test_a_pass_through_transform_naming_neither_is_legal() -> None:
    _fragment_with({"limit": {"count": 10}})


# ---------------------------------------------------------------------------
# aggregate item shape.
# ---------------------------------------------------------------------------


def test_count_with_a_field_fails_to_decode() -> None:
    with pytest.raises(ValidationError, match="count takes no field"):
        _fragment_with({"aggregate": [{"name": "n", "op": "count", "field": "x"}]})


def test_count_distinct_without_a_field_fails_to_decode() -> None:
    with pytest.raises(ValidationError, match="count_distinct requires a field"):
        _fragment_with({"aggregate": [{"name": "n", "op": "count_distinct"}]})


def test_sum_without_a_field_fails_to_decode() -> None:
    with pytest.raises(ValidationError):
        _fragment_with({"aggregate": [{"name": "n", "op": "sum"}]})


def test_as_is_not_accepted_as_an_aggregate_name() -> None:
    # Measured live emit (issue #118): Vega-Lite `as` instead of the menu's
    # `name`. Unlike before #147, this now fails to decode, not just to
    # assemble.
    with pytest.raises(ValidationError, match="unrecognised key"):
        _fragment_with({"aggregate": [{"as": "revenue", "op": "sum", "field": "x"}]})


def test_aggregate_item_unrecognised_key_fails_to_decode() -> None:
    with pytest.raises(ValidationError, match=r"unrecognised key\(s\) \('extra',\)"):
        _fragment_with(
            {"aggregate": [{"name": "n", "op": "sum", "field": "revenue", "extra": 1}]}
        )


def test_aggregate_item_legal_keys_decode() -> None:
    _fragment_with({"aggregate": [{"name": "n", "op": "sum", "field": "x"}]})
    _fragment_with({"aggregate": [{"name": "n", "op": "count"}]})


# ---------------------------------------------------------------------------
# sort item shape.
# ---------------------------------------------------------------------------


def test_sort_item_order_key_fails_to_decode() -> None:
    # Measured live emit: Vega-Lite `order` instead of `dir`/`nulls`
    # (ADR-0023 D4; #139's silently-drawn-ascending bug).
    with pytest.raises(ValidationError, match=r"unrecognised key\(s\) \('order',\)"):
        _fragment_with({"sort": [{"field": "revenue", "order": "descending"}]})


def test_sort_item_defaults_dir_and_nulls() -> None:
    parsed = Fragment.model_validate(
        {**_BASE_FRAGMENT, "transform": {"sort": [{"field": "revenue"}]}}
    )
    assert parsed.transform is not None
    dumped = parsed.transform.model_dump()
    assert dumped["sort"] == [{"field": "revenue", "dir": "asc", "nulls": "last"}]


# ---------------------------------------------------------------------------
# bin item shape.
# ---------------------------------------------------------------------------


def test_bin_item_unrecognised_key_fails_to_decode() -> None:
    with pytest.raises(ValidationError, match=r"unrecognised key\(s\) \('scale',\)"):
        _fragment_with(
            {"bin": [{"name": "b", "field": "revenue", "width": 10, "scale": "log"}]}
        )


def test_bin_item_needs_unit_or_width() -> None:
    with pytest.raises(ValidationError, match="needs either unit or"):
        _fragment_with({"bin": [{"name": "b", "field": "x"}]})


def test_bin_item_cannot_carry_both_unit_and_width() -> None:
    with pytest.raises(ValidationError, match="cannot carry both"):
        _fragment_with(
            {"bin": [{"name": "b", "field": "x", "unit": "month", "width": 10}]}
        )


def test_bin_item_width_zero_fails_to_decode() -> None:
    with pytest.raises(ValidationError, match="non-zero"):
        _fragment_with({"bin": [{"name": "b", "field": "x", "width": 0}]})


def test_bin_item_legal_keys_decode() -> None:
    _fragment_with({"bin": [{"name": "b", "field": "ts", "unit": "month"}]})
    _fragment_with(
        {"bin": [{"name": "b", "field": "revenue", "width": 10, "origin": 0}]}
    )


# ---------------------------------------------------------------------------
# derive / limit item shape.
# ---------------------------------------------------------------------------


def test_derive_item_unrecognised_key_fails_to_decode() -> None:
    with pytest.raises(ValidationError, match=r"unrecognised key\(s\) \('as',\)"):
        _fragment_with(
            {"derive": [{"name": "x", "expr": {"kind": "lit", "value": 1}, "as": "y"}]}
        )


def test_limit_unrecognised_key_fails_to_decode() -> None:
    with pytest.raises(ValidationError, match=r"unrecognised key\(s\) \('page',\)"):
        _fragment_with({"limit": {"count": 10, "page": 2}})


def test_limit_count_bool_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _fragment_with({"limit": {"count": True}})


def test_limit_negative_count_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _fragment_with({"limit": {"count": -1}})


# ---------------------------------------------------------------------------
# Expr shape — arity, kind, closed keys (ADR-0023 D2/D4).
# ---------------------------------------------------------------------------


def test_unknown_expr_kind_fails_to_decode() -> None:
    with pytest.raises(ValidationError, match="unknown Expr kind"):
        _fragment_with({"filter": {"kind": "bogus"}})


def test_binary_node_with_three_args_fails_to_decode() -> None:
    with pytest.raises(ValidationError):
        _fragment_with(
            {
                "filter": {
                    "kind": "eq",
                    "args": [
                        {"kind": "lit", "value": 1},
                        {"kind": "lit", "value": 1},
                        {"kind": "lit", "value": 1},
                    ],
                }
            }
        )


def test_unary_node_needs_exactly_one_arg() -> None:
    with pytest.raises(ValidationError):
        _fragment_with({"filter": {"kind": "neg", "args": []}})


def test_between_needs_exactly_three_args() -> None:
    with pytest.raises(ValidationError):
        _fragment_with(
            {
                "filter": {
                    "kind": "between",
                    "args": [{"kind": "lit", "value": 1}, {"kind": "lit", "value": 2}],
                }
            }
        )


def test_case_without_else_fails_to_decode() -> None:
    with pytest.raises(ValidationError):
        _fragment_with(
            {
                "filter": {
                    "kind": "case",
                    "whens": [
                        {
                            "when": {"kind": "lit", "value": True},
                            "then": {"kind": "lit", "value": 1},
                        }
                    ],
                }
            }
        )


def test_case_with_empty_whens_fails_to_decode() -> None:
    with pytest.raises(ValidationError):
        _fragment_with(
            {
                "filter": {
                    "kind": "case",
                    "whens": [],
                    "else": {"kind": "lit", "value": 1},
                }
            }
        )


def test_in_rhs_must_be_literals() -> None:
    with pytest.raises(ValidationError, match="in RHS is literals only"):
        _fragment_with(
            {
                "filter": {
                    "kind": "in",
                    "args": [
                        {"kind": "col", "name": "x"},
                        {"kind": "col", "name": "y"},
                    ],
                }
            }
        )


@pytest.mark.parametrize(
    "node, unknown",
    [
        pytest.param({"kind": "col", "name": "x", "alias": "y"}, "alias", id="col"),
        pytest.param({"kind": "lit", "value": 1, "label": "n"}, "label", id="lit"),
        pytest.param(
            {"kind": "neg", "args": [{"kind": "lit", "value": 1}], "note": "n"},
            "note",
            id="unary",
        ),
        pytest.param(
            {
                "kind": "add",
                "args": [{"kind": "lit", "value": 1}, {"kind": "lit", "value": 2}],
                "note": "n",
            },
            "note",
            id="binary",
        ),
        pytest.param(
            {
                "kind": "and",
                "args": [
                    {"kind": "lit", "value": True},
                    {"kind": "lit", "value": True},
                ],
                "note": "n",
            },
            "note",
            id="nary",
        ),
        pytest.param(
            {
                "kind": "between",
                "args": [
                    {"kind": "col", "name": "x"},
                    {"kind": "lit", "value": 1},
                    {"kind": "lit", "value": 2},
                ],
                "note": "n",
            },
            "note",
            id="between",
        ),
        pytest.param(
            {
                "kind": "in",
                "args": [{"kind": "col", "name": "x"}, {"kind": "lit", "value": 1}],
                "note": "n",
            },
            "note",
            id="in",
        ),
        pytest.param(
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
            "note",
            id="case",
        ),
        pytest.param(
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
            "label",
            id="case-when",
        ),
    ],
)
def test_expr_unrecognised_key_fails_to_decode(
    node: dict[str, Any], unknown: str
) -> None:
    pattern = rf"unrecognised key\(s\) \('{unknown}',\)"
    with pytest.raises(ValidationError, match=pattern):
        _fragment_with({"filter": node})


def test_null_literal_survives_the_dump_round_trip() -> None:
    # A `lit` node's `value: None` is a meaningful SQL NULL, not an absent
    # field — transform_mapping() must not drop it the way a naive
    # exclude_none dump would (regression: it silently turned {"kind":
    # "lit", "value": None} into {"kind": "lit"}, a KeyError at bind).
    from chartagent.transform.model import transform_mapping

    parsed = Fragment.model_validate(
        {
            **_BASE_FRAGMENT,
            "transform": {
                "derive": [
                    {
                        "name": "y",
                        "expr": {
                            "kind": "coalesce",
                            "args": [
                                {"kind": "col", "name": "quarter"},
                                {"kind": "lit", "value": None},
                            ],
                        },
                    }
                ]
            },
        }
    )
    mapping = transform_mapping(parsed.transform)
    assert mapping is not None
    assert mapping["derive"][0]["expr"]["args"][1] == {"kind": "lit", "value": None}


# ---------------------------------------------------------------------------
# InputFrame.model_validate maps a bad stored transform to SpecShapeError
# with its field path (ADR-0023 D5) — no raw ValidationError escapes.
# ---------------------------------------------------------------------------


def test_input_frame_transform_shape_fault_carries_its_field_path() -> None:
    frame = {
        "chart_spec": {
            "chartType": "Bar Chart",
            "encodings": {"x": {"field": "quarter"}, "y": {"field": "revenue"}},
        },
        "x_chartagent": {
            "transform": {"aggregate": [{"name": "n", "op": "count", "field": "x"}]}
        },
    }
    with pytest.raises(SpecShapeError) as caught:
        InputFrame.model_validate(frame)
    assert (
        str(caught.value) == "x_chartagent.transform.aggregate[0]: count takes no field"
    )


def test_input_frame_malformed_transform_never_leaks_a_validation_error() -> None:
    frame = {
        "chart_spec": {
            "chartType": "Bar Chart",
            "encodings": {"x": {"field": "quarter"}, "y": {"field": "revenue"}},
        },
        "x_chartagent": {"transform": {"pivot": []}},
    }
    with pytest.raises(SpecShapeError):
        InputFrame.model_validate(frame)


# ---------------------------------------------------------------------------
# A schema snapshot: step 1's tool schema is the arity-grouped form — no
# per-kind definitions, and no expansion from the callable discriminator
# (ADR-0023 D2).
# ---------------------------------------------------------------------------


def test_step1_schema_is_arity_grouped_not_expanded_per_kind() -> None:
    schema = _STEP1.json_schema()
    defs = schema.get("$defs", {})
    expr_shape_names = {
        "ColExpr",
        "LitExpr",
        "UnaryExpr",
        "BinaryExpr",
        "NaryExpr",
        "BetweenExpr",
        "InExpr",
        "CaseExpr",
    }
    assert expr_shape_names <= set(defs)
    # 26 kinds, 8 shapes — a per-kind schema would need one $def per kind.
    kind_named_defs = {name for name in defs if name.endswith("Kind")}
    assert not kind_named_defs
    for kind in EXPR_KINDS:
        assert kind not in defs
    # Menu itself: one definition, eight slots — not one per slot either.
    assert "Menu" in defs
    assert set(defs["Menu"]["properties"]) == set(TRANSFORM_SLOTS)


# ---------------------------------------------------------------------------
# ADR-0023 D6: the two schema-inexpressible prompt lines are actually true
# of the closed vocabulary (each with its own enforcement test).
# ---------------------------------------------------------------------------


def test_the_menu_vocabulary_cannot_express_window_pivot_or_json_functions() -> None:
    banned = {"unpivot", "pivot", "window", "json_extract", "row_number", "lag", "lead"}
    assert banned.isdisjoint(TRANSFORM_SLOTS)
    assert banned.isdisjoint(EXPR_KINDS)
