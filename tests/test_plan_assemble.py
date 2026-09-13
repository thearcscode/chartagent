"""Assemble a backend-free frame from a fragment (issue #106, ADR-0019 D2/D6)."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

import chartagent
from chartagent import InputFrame, bind
from chartagent.errors import (
    RawSqlRejectedError,
    SchemaDriftError,
    SpecShapeError,
    SpecVocabularyError,
)
from chartagent.frame.input import DEFAULT_BASE_SIZE, XChartagent
from chartagent.plan.assemble import assemble
from chartagent.plan.schema import Fragment
from chartagent.profile.models import Column, NumberColumn, Profile, StringColumn
from chartagent.profile.source import profile_source
from chartagent.transform.engine import (
    describe_source,
    open_connection,
    register_source,
)

_ROWS = [
    {"quarter": "Q1", "revenue": 100, "region": "west"},
    {"quarter": "Q2", "revenue": 200, "region": "east"},
]

_THREE = {
    "group_by": ["quarter", "region"],
    "aggregate": [{"name": "total", "op": "sum", "field": "revenue"}],
}

_PROFILE = Profile(
    row_count=2,
    columns=[
        StringColumn(
            name="quarter",
            reported_type="VARCHAR",
            null_rate=0.0,
            distinct=2,
            saturated=False,
        ),
        NumberColumn(
            name="revenue",
            reported_type="BIGINT",
            null_rate=0.0,
            distinct=2,
            saturated=False,
        ),
        StringColumn(
            name="region",
            reported_type="VARCHAR",
            null_rate=0.0,
            distinct=2,
            saturated=False,
        ),
        NumberColumn(
            name="cost",
            reported_type="BIGINT",
            null_rate=0.0,
            distinct=2,
            saturated=False,
        ),
    ],
)


def _fragment(**overrides: Any) -> Fragment:
    payload: dict[str, Any] = {
        "outcome": "fragment",
        "chart_type": "Bar Chart",
        "encodings": {
            "x": {"field": "quarter"},
            "y": {"field": "revenue"},
        },
        "transform": None,
        "semantic_types": {"revenue": "Quantity"},
        "requested_backend": None,
    }
    payload.update(overrides)
    return Fragment.model_validate(payload)


def _dump(frame: InputFrame) -> dict[str, Any]:
    dumped = frame.model_dump(mode="json", by_alias=True, exclude_none=True)
    assert isinstance(dumped, dict)
    return dumped


def test_assembled_frame_is_a_backend_free_input_frame() -> None:
    frame = assemble(_fragment(transform=_THREE), _PROFILE)
    dumped = _dump(frame)
    assert dumped["x_chartagent"]["spec_version"] == "1.2"
    assert dumped["x_chartagent"]["annotations"] == []
    assert dumped["x_chartagent"]["interactions"] == {}
    assert "theme_spec" not in dumped
    assert "options" not in dumped
    assert "data" not in dumped
    assert "backend" not in dumped
    InputFrame.model_validate(dumped)


def test_chart_properties_pass_through_when_supplied() -> None:
    frame = assemble(
        _fragment(transform=_THREE),
        _PROFILE,
        chart_properties={"innerRadius": 40},
    )
    assert frame.chart_spec.chart_properties == {"innerRadius": 40}
    assert frame.chart_spec.base_size == DEFAULT_BASE_SIZE


def test_source_schema_covers_exactly_the_transform_source_columns() -> None:
    frame = assemble(_fragment(transform=_THREE), _PROFILE)
    assert frame.x_chartagent is not None
    assert frame.x_chartagent.source_schema == {
        "quarter": "string",
        "region": "string",
        "revenue": "number",
    }


def test_raw_sql_star_yields_empty_source_schema() -> None:
    frame = assemble(_fragment(transform={"raw_sql": "SELECT * FROM source"}), _PROFILE)
    assert frame.x_chartagent is not None
    assert frame.x_chartagent.source_schema == {}


def test_raw_sql_named_columns_are_the_source_schema_keys() -> None:
    frame = assemble(
        _fragment(transform={"raw_sql": "SELECT quarter, revenue FROM source"}),
        _PROFILE,
    )
    assert frame.x_chartagent is not None
    assert frame.x_chartagent.source_schema == {
        "quarter": "string",
        "revenue": "number",
    }


def test_transform_naming_no_source_column_yields_empty_source_schema() -> None:
    frame = assemble(
        _fragment(transform={"limit": {"count": 10, "offset": 0}}), _PROFILE
    )
    assert frame.x_chartagent is not None
    assert frame.x_chartagent.source_schema == {}


def test_absent_transform_yields_empty_source_schema() -> None:
    frame = assemble(_fragment(transform=None), _PROFILE)
    assert frame.x_chartagent is not None
    assert frame.x_chartagent.source_schema == {}


def test_source_schema_buckets_come_from_the_profile_not_a_fresh_describe() -> None:
    profile = profile_source(_ROWS)
    connection = open_connection()
    try:
        register_source(connection, _ROWS)
        _reported, live = describe_source(connection)
    finally:
        connection.close()
    assert live["revenue"] == "number"

    mutated: list[Column] = []
    for column in profile.columns:
        if column.name == "revenue":
            assert isinstance(column, NumberColumn)
            mutated.append(
                StringColumn(
                    name="revenue",
                    reported_type=column.reported_type,
                    null_rate=column.null_rate,
                    distinct=column.distinct,
                    saturated=column.saturated,
                )
            )
        else:
            mutated.append(column)
    profile_with_string_revenue = profile.model_copy(update={"columns": mutated})
    frame = assemble(_fragment(transform=_THREE), profile_with_string_revenue)
    assert frame.x_chartagent is not None
    assert frame.x_chartagent.source_schema is not None
    assert frame.x_chartagent.source_schema["revenue"] == "string"
    assert live["revenue"] == "number"


def test_semantic_types_come_from_the_fragment_never_the_profile() -> None:
    profile = Profile(
        row_count=1,
        columns=[
            NumberColumn(
                name="Quantity",
                reported_type="DOUBLE",
                null_rate=0.0,
                distinct=1,
                saturated=False,
            ),
            StringColumn(
                name="Category",
                reported_type="VARCHAR",
                null_rate=0.0,
                distinct=1,
                saturated=False,
            ),
            NumberColumn(
                name="Number",
                reported_type="INTEGER",
                null_rate=0.0,
                distinct=1,
                saturated=False,
            ),
            StringColumn(
                name="quarter",
                reported_type="VARCHAR",
                null_rate=0.0,
                distinct=1,
                saturated=False,
            ),
            NumberColumn(
                name="revenue",
                reported_type="DOUBLE",
                null_rate=0.0,
                distinct=1,
                saturated=False,
            ),
        ],
    )
    fragment = _fragment(
        transform=_THREE,
        semantic_types={"revenue": "Amount"},
    )
    frame = assemble(fragment, profile)
    assert frame.semantic_types == {"revenue": "Amount"}
    assert frame.semantic_types != {
        column.name: column.reported_type for column in profile.columns
    }
    assert "Quantity" not in frame.semantic_types
    assert "Category" not in frame.semantic_types
    assert "Number" not in frame.semantic_types


def test_step1_accepts_a_well_formed_fragment() -> None:
    frame = assemble(_fragment(transform=_THREE), _PROFILE)
    assert frame.chart_spec.chart_type == "Bar Chart"


def test_encoding_outside_the_global_channels_is_a_schema_failure() -> None:
    fragment = _fragment(encodings={"not_a_channel": {"field": "quarter"}})
    with pytest.raises(SpecVocabularyError) as caught:
        assemble(fragment, _PROFILE)
    assert caught.value.kind == "channel"
    assert "not_a_channel" in caught.value.keys


@pytest.mark.parametrize(
    "bucket",
    ("number", "string", "boolean", "date", "timestamp", "timestamptz", "other"),
)
def test_source_bucket_encoding_type_is_a_schema_failure(bucket: str) -> None:
    fragment = _fragment(
        encodings={
            "x": {"field": "quarter", "type": bucket},
            "y": {"field": "revenue"},
        }
    )
    with pytest.raises(SpecShapeError, match="source bucket"):
        assemble(fragment, _PROFILE)


def test_omitted_encoding_type_still_assembles_and_binds() -> None:
    frame = assemble(_fragment(), _PROFILE)
    assert frame.chart_spec.encodings["x"].type is None
    assert frame.chart_spec.encodings["y"].type is None
    envelope = bind(frame, _ROWS, backend="vegalite")
    assert envelope.row_count == 2


def test_vega_encoding_types_still_assemble_and_bind() -> None:
    fragment = _fragment(
        encodings={
            "x": {"field": "quarter", "type": "nominal"},
            "y": {"field": "revenue", "type": "quantitative"},
        }
    )
    frame = assemble(fragment, _PROFILE)
    assert frame.chart_spec.encodings["x"].type == "nominal"
    assert frame.chart_spec.encodings["y"].type == "quantitative"
    envelope = bind(frame, _ROWS, backend="vegalite")
    assert envelope.row_count == 2


def test_chart_type_outside_the_48_is_a_schema_failure() -> None:
    fragment = Fragment.model_construct(
        outcome="fragment",
        chart_type="Not A Chart",
        encodings=_fragment().encodings,
        transform=None,
        semantic_types={},
        requested_backend=None,
    )
    with pytest.raises(SpecVocabularyError) as caught:
        assemble(fragment, _PROFILE)
    assert caught.value.kind == "chart_type"


def test_unrecognised_transform_slot_is_a_schema_failure() -> None:
    # ADR-0023: the typed menu decodes this, so the failure is now at
    # Fragment construction (a decode failure), never reaching assemble().
    with pytest.raises(ValidationError, match="unrecognised transform slot"):
        _fragment(transform={"pivot": []})


def test_raw_sql_mixed_with_a_menu_slot_is_a_schema_failure() -> None:
    with pytest.raises(ValidationError, match="raw_sql cannot mix with menu slots"):
        _fragment(
            transform={
                "raw_sql": "SELECT 1 FROM source",
                "filter": {"kind": "lit", "value": True},
            }
        )


def test_raw_sql_failing_lock_1_is_a_schema_failure() -> None:
    with pytest.raises(RawSqlRejectedError) as caught:
        assemble(
            _fragment(transform={"raw_sql": "SELECT 1; SELECT 2"}),
            _PROFILE,
        )
    assert caught.value.reason == "multi_statement"


def test_raw_sql_failing_lock_2_is_a_schema_failure() -> None:
    with pytest.raises(RawSqlRejectedError) as caught:
        assemble(
            _fragment(transform={"raw_sql": "SELECT * FROM '/etc/passwd'"}),
            _PROFILE,
        )
    assert caught.value.reason == "foreign_relation"


def test_unknown_source_column_is_bind_not_assemble() -> None:
    """A transform naming a column the data does not have is bind's.

    The fence is shape versus data: unknown columns need rows. Assemble
    is data-free and must not reject them.
    """
    fragment = _fragment(
        transform={
            "filter": {
                "kind": "is_not_null",
                "args": [{"kind": "col", "name": "missing"}],
            }
        }
    )
    frame = assemble(fragment, _PROFILE)
    assert frame.x_chartagent is not None
    with pytest.raises(SchemaDriftError) as caught:
        bind(frame, _ROWS, backend="echarts")
    assert caught.value.stage == "source"


def test_x_chartagent_keeps_its_five_keys_and_spec_version_does_not_move() -> None:
    assert set(XChartagent.model_fields) == {
        "spec_version",
        "transform",
        "annotations",
        "interactions",
        "source_schema",
    }
    frame = assemble(_fragment(transform=_THREE), _PROFILE)
    dumped = _dump(frame)["x_chartagent"]
    assert set(dumped) == {
        "spec_version",
        "transform",
        "annotations",
        "interactions",
        "source_schema",
    }
    assert dumped["spec_version"] == "1.2"
    assert "escape" not in dumped


def test_assemble_is_not_on_the_public_surface() -> None:
    assert "assemble" not in chartagent.__all__
    assert not hasattr(chartagent, "assemble")


def test_default_base_size_is_not_on_the_public_surface() -> None:
    assert "DEFAULT_BASE_SIZE" not in chartagent.__all__
    assert not hasattr(chartagent, "DEFAULT_BASE_SIZE")


def test_assembled_frame_pins_default_base_size() -> None:
    frame = assemble(_fragment(transform=_THREE), _PROFILE)
    assert frame.chart_spec.base_size == DEFAULT_BASE_SIZE
    dumped = _dump(frame)
    assert dumped["chart_spec"]["baseSize"] == DEFAULT_BASE_SIZE.model_dump(mode="json")
