"""Step 1's three-member tagged union (issue #103, ADR-0019/0020/0021/0022)."""

from __future__ import annotations

from typing import Any, get_args

import pytest
from pydantic import TypeAdapter, ValidationError

import chartagent
from chartagent.frame._generated import ChartType, SemanticTypeName
from chartagent.frame.input import Backend, EncodingObject
from chartagent.plan.schema import (
    Fragment,
    Inexpressible,
    Step1Result,
    Unanswerable,
)

_STEP1: TypeAdapter[Fragment | Inexpressible | Unanswerable] = TypeAdapter(Step1Result)

_FRAGMENT: dict[str, Any] = {
    "outcome": "fragment",
    "chart_type": "Bar Chart",
    "encodings": {
        "x": {"field": "quarter"},
        "y": {"field": "revenue"},
    },
    "transform": {
        "derive": [{"name": "quarter2", "expr": {"kind": "col", "name": "quarter"}}]
    },
    "semantic_types": {"revenue": "Quantity"},
    "requested_backend": None,
}


def test_fragment_round_trips() -> None:
    parsed = Fragment.model_validate(_FRAGMENT)
    assert parsed.chart_type == "Bar Chart"
    assert parsed.encodings["x"].field == "quarter"
    assert parsed.transform is not None
    assert parsed.transform.model_dump(exclude_none=True) == {
        "derive": [{"name": "quarter2", "expr": {"kind": "col", "name": "quarter"}}]
    }
    assert parsed.semantic_types == {"revenue": "Quantity"}
    assert parsed.requested_backend is None
    # exclude_none — every real caller dumps Fragment/InputFrame this way
    # (plan/agent.py, plan/assemble.py); a bare model_dump() would carry
    # every unset Menu slot as an explicit `null`, which round-trips back
    # through Menu's own present-but-empty group_by+aggregate check
    # differently than an untrusted emit ever could (that check reads
    # whether the *original* dict named the key at all). requested_backend
    # is nullable-but-required, so it is re-added — exclude_none would
    # drop it too, and it carries no Menu round-trip risk of its own.
    dumped = parsed.model_dump(exclude_none=True)
    dumped["requested_backend"] = None
    assert Fragment.model_validate(dumped) == parsed
    assert isinstance(_STEP1.validate_python(_FRAGMENT), Fragment)


def test_inexpressible_round_trips() -> None:
    payload = {"outcome": "inexpressible", "bucket": 1}
    parsed = Inexpressible.model_validate(payload)
    assert parsed.bucket == 1
    assert Inexpressible.model_validate(parsed.model_dump()) == parsed
    assert isinstance(_STEP1.validate_python(payload), Inexpressible)


def test_unanswerable_round_trips() -> None:
    payload = {
        "outcome": "unanswerable",
        "kind": "missing_column",
        "keys": ("sentiment",),
    }
    parsed = Unanswerable.model_validate(payload)
    assert parsed.kind == "missing_column"
    assert parsed.keys == ("sentiment",)
    assert Unanswerable.model_validate(parsed.model_dump()) == parsed
    assert isinstance(_STEP1.validate_python(payload), Unanswerable)


def test_union_discriminates_on_outcome_without_bare_top_level_anyof() -> None:
    schema = _STEP1.json_schema()
    assert "anyOf" not in schema
    assert schema["discriminator"] == {
        "propertyName": "outcome",
        "mapping": {
            "fragment": "#/$defs/Fragment",
            "inexpressible": "#/$defs/Inexpressible",
            "unanswerable": "#/$defs/Unanswerable",
        },
    }
    assert schema["oneOf"] == [
        {"$ref": "#/$defs/Fragment"},
        {"$ref": "#/$defs/Inexpressible"},
        {"$ref": "#/$defs/Unanswerable"},
    ]


def test_inexpressible_carrying_transform_fails_as_adr_0019_decision_7() -> None:
    """A bucket-2 claim carrying a valid transform cannot decode.

    ADR-0019 Decision 7: this is a step-1 schema failure, not a bucket.
    Inexpressible has no transform field and forbids extras, so the
    contradiction needs no hand-written check.
    """
    payload = {
        "outcome": "inexpressible",
        "bucket": 2,
        "transform": {"select": [{"kind": "column", "name": "revenue"}]},
    }
    with pytest.raises(ValidationError):
        _STEP1.validate_python(payload)


def test_extra_forbid_holds_on_all_three_members() -> None:
    with pytest.raises(ValidationError):
        Fragment.model_validate({**_FRAGMENT, "rationale": "because bar charts"})
    with pytest.raises(ValidationError):
        Inexpressible.model_validate(
            {"outcome": "inexpressible", "bucket": 1, "retryable": False}
        )
    with pytest.raises(ValidationError):
        Unanswerable.model_validate(
            {
                "outcome": "unanswerable",
                "kind": "missing_role",
                "keys": (),
                "escape_reason": 1,
            }
        )


def test_requested_backend_is_on_fragment_only_and_closed_to_backend() -> None:
    assert "requested_backend" not in Inexpressible.model_fields
    assert "requested_backend" not in Unanswerable.model_fields

    for backend in get_args(Backend):
        parsed = Fragment.model_validate({**_FRAGMENT, "requested_backend": backend})
        assert parsed.requested_backend == backend
    with pytest.raises(ValidationError):
        Fragment.model_validate({**_FRAGMENT, "requested_backend": "matplotlib"})
    with pytest.raises(ValidationError):
        Inexpressible.model_validate(
            {"outcome": "inexpressible", "bucket": 1, "requested_backend": "vegalite"}
        )
    with pytest.raises(ValidationError):
        Unanswerable.model_validate(
            {
                "outcome": "unanswerable",
                "kind": "missing_role",
                "keys": (),
                "requested_backend": "vegalite",
            }
        )


def test_bucket_accepts_only_one_and_two() -> None:
    parsed = Inexpressible.model_validate({"outcome": "inexpressible", "bucket": 2})
    assert parsed.bucket == 2
    for bucket in (3, 4, 0):
        with pytest.raises(ValidationError):
            Inexpressible.model_validate({"outcome": "inexpressible", "bucket": bucket})


def test_kind_is_closed_and_empty_keys_are_the_unspecific_ask() -> None:
    parsed = Unanswerable.model_validate(
        {"outcome": "unanswerable", "kind": "missing_role", "keys": ()}
    )
    assert parsed.kind == "missing_role"
    assert parsed.keys == ()
    with pytest.raises(ValidationError):
        Unanswerable.model_validate(
            {"outcome": "unanswerable", "kind": "vibes", "keys": ()}
        )


def test_chart_type_and_semantic_types_use_generated_literals() -> None:
    for chart_type in get_args(ChartType):
        parsed = Fragment.model_validate({**_FRAGMENT, "chart_type": chart_type})
        assert parsed.chart_type == chart_type
    for name in get_args(SemanticTypeName):
        parsed = Fragment.model_validate({**_FRAGMENT, "semantic_types": {"col": name}})
        assert parsed.semantic_types == {"col": name}
    with pytest.raises(ValidationError):
        Fragment.model_validate({**_FRAGMENT, "chart_type": "Not A Chart"})
    with pytest.raises(ValidationError):
        Fragment.model_validate(
            {**_FRAGMENT, "semantic_types": {"revenue": "NotAType"}}
        )


def test_encodings_reuse_the_facade_encoding_shape() -> None:
    parsed = Fragment.model_validate(_FRAGMENT)
    assert isinstance(parsed.encodings["y"], EncodingObject)
    with pytest.raises(ValidationError):
        Fragment.model_validate(
            {
                **_FRAGMENT,
                "encodings": {"x": {"field": "quarter", "aggregate": "sum"}},
            }
        )


def test_no_member_carries_rationale_retryable_or_an_escape_reason() -> None:
    forbidden = {"rationale", "retryable", "escape_reason", "reason"}
    for model in (Fragment, Inexpressible, Unanswerable):
        assert forbidden.isdisjoint(model.model_fields)


def test_step1_schema_is_not_on_the_public_surface() -> None:
    for name in ("Fragment", "Inexpressible", "Unanswerable", "Step1Result"):
        assert name not in chartagent.__all__
        assert not hasattr(chartagent, name)


# Measured live omit of the discriminator (issue #118). ADR-0023: the typed
# menu now decodes `aggregate` shape too, so the item must carry the real
# `name` key (Vega-Lite `as` no longer merely defers to assemble — it fails
# to decode, tests/test_transform_model.py).
_MEASURED_FRAGMENT_OMIT_OUTCOME: dict[str, Any] = {
    "chart_type": "Bar Chart",
    "encodings": {
        "x": {"field": "region", "type": "Category"},
        "y": {"field": "revenue", "type": "Amount"},
    },
    "transform": {
        "group_by": ["region"],
        "aggregate": [{"name": "revenue", "op": "sum", "field": "revenue"}],
    },
    "semantic_types": {"region": "Category", "revenue": "Amount"},
    "requested_backend": None,
}


def test_fragment_omitting_outcome_decodes_as_fragment() -> None:
    parsed = _STEP1.validate_python(_MEASURED_FRAGMENT_OMIT_OUTCOME)
    assert isinstance(parsed, Fragment)
    assert parsed.outcome == "fragment"
    assert parsed.chart_type == "Bar Chart"


def test_inexpressible_omitting_outcome_decodes_as_inexpressible() -> None:
    parsed = _STEP1.validate_python({"bucket": 2})
    assert isinstance(parsed, Inexpressible)
    assert parsed.outcome == "inexpressible"
    assert parsed.bucket == 2


def test_unanswerable_omitting_outcome_decodes_as_unanswerable() -> None:
    parsed = _STEP1.validate_python({"kind": "missing_column", "keys": ["sentiment"]})
    assert isinstance(parsed, Unanswerable)
    assert parsed.outcome == "unanswerable"
    assert parsed.kind == "missing_column"
    assert parsed.keys == ("sentiment",)


def test_filling_outcome_does_not_reopen_inexpressible_carrying_transform() -> None:
    payload = {
        "bucket": 2,
        "transform": {"group_by": ["region"]},
    }
    with pytest.raises(ValidationError):
        _STEP1.validate_python(payload)
    with pytest.raises(ValidationError):
        _STEP1.validate_python(
            {
                "outcome": "inexpressible",
                "bucket": 2,
                "transform": {"group_by": ["region"]},
            }
        )
