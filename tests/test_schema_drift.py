from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, date, datetime, time
from decimal import Decimal
from typing import Any, get_args

import pyarrow as pa
import pytest

from chartagent import bind
from chartagent.bind import DataSource
from chartagent.errors import DriftKind, SchemaDriftError, SpecShapeError

_UNSET = object()

_ROWS = [
    {"quarter": "Q1", "revenue": 100},
    {"quarter": "Q2", "revenue": 200},
]


def _ref(name: str) -> dict[str, object]:
    return {"filter": {"kind": "is_not_null", "args": [{"kind": "col", "name": name}]}}


def _bind(
    rows: DataSource,
    *,
    transform: Mapping[str, object] | None = None,
    encodings: dict[str, Any] | None = None,
    source_schema: object = _UNSET,
    semantic_types: dict[str, str] | None = None,
    theme_spec: str | dict[str, object] | None = None,
    backend: str = "echarts",
) -> Any:
    frame: dict[str, Any] = {
        "chart_spec": {
            "chartType": "Bar Chart",
            "encodings": encodings
            or {"x": {"field": "quarter"}, "y": {"field": "revenue"}},
        }
    }
    extra: dict[str, Any] = {}
    if transform is not None:
        extra["transform"] = transform
    if source_schema is not _UNSET:
        extra["source_schema"] = source_schema
    if extra:
        frame["x_chartagent"] = extra
    if semantic_types is not None:
        frame["semantic_types"] = semantic_types
    if theme_spec is not None:
        frame["theme_spec"] = theme_spec
    return bind(frame, rows, backend=backend)  # type: ignore[arg-type]


def test_renamed_kind_is_a_placeholder() -> None:
    """Rename detection has no mechanism. The kind stays in the Literal.

    A missing referenced column is dropped. A raise-test cannot fail yet.
    """
    assert "renamed" in get_args(DriftKind)


def test_dropped_source_column_is_source_stage_drift() -> None:
    with pytest.raises(SchemaDriftError) as caught:
        _bind(_ROWS, transform=_ref("region"))
    err = caught.value
    assert err.stage == "source"
    assert len(err.drifted) == 1
    field = err.drifted[0]
    assert field.name == "region"
    assert field.kind == "dropped"
    assert field.expected == "region"
    assert field.found is None


def test_integer_to_bigint_is_silent() -> None:
    encodings = {"x": {"field": "quarter"}, "y": {"field": "n"}}
    planned = _bind(
        pa.table({"n": pa.array([1], type=pa.int32()), "quarter": ["Q1"]}),
        transform=_ref("n"),
        encodings=encodings,
        source_schema={"n": "number"},
    )
    assert planned.source_schema == {"n": "number"}
    refreshed = _bind(
        pa.table({"n": pa.array([1], type=pa.int64()), "quarter": ["Q1"]}),
        transform=_ref("n"),
        encodings=encodings,
        source_schema=planned.source_schema,
    )
    assert refreshed.source_schema == {"n": "number"}


def test_varchar_to_date_raises_retyped() -> None:
    with pytest.raises(SchemaDriftError) as caught:
        _bind(
            pa.table(
                {
                    "label": pa.array([date(2020, 1, 1)], type=pa.date32()),
                    "n": [1],
                }
            ),
            transform=_ref("label"),
            encodings={"x": {"field": "label"}, "y": {"field": "n"}},
            source_schema={"label": "string"},
        )
    err = caught.value
    assert err.stage == "source"
    field = err.drifted[0]
    assert field.kind == "retyped"
    assert field.name == "label"
    assert field.expected == "string"
    assert field.found == "date"


def test_timestamp_to_timestamptz_raises_retyped() -> None:
    with pytest.raises(SchemaDriftError) as caught:
        _bind(
            pa.table(
                {
                    "ts": pa.array(
                        [datetime(2020, 1, 1, tzinfo=UTC)],
                        type=pa.timestamp("us", tz="UTC"),
                    ),
                    "n": [1],
                }
            ),
            transform=_ref("ts"),
            encodings={"x": {"field": "ts"}, "y": {"field": "n"}},
            source_schema={"ts": "timestamp"},
        )
    err = caught.value
    assert err.stage == "source"
    field = err.drifted[0]
    assert field.kind == "retyped"
    assert field.expected == "timestamp"
    assert field.found == "timestamptz"


def test_decimal_widening_is_silent() -> None:
    encodings = {"x": {"field": "quarter"}, "y": {"field": "amount"}}
    planned = _bind(
        pa.table(
            {
                "amount": pa.array([Decimal("1.20")], type=pa.decimal128(10, 2)),
                "quarter": ["Q1"],
            }
        ),
        transform=_ref("amount"),
        encodings=encodings,
        source_schema={"amount": "number"},
    )
    assert planned.source_schema == {"amount": "number"}
    refreshed = _bind(
        pa.table(
            {
                "amount": pa.array([Decimal("1.200")], type=pa.decimal128(18, 3)),
                "quarter": ["Q1"],
            }
        ),
        transform=_ref("amount"),
        encodings=encodings,
        source_schema=planned.source_schema,
    )
    assert refreshed.source_schema == {"amount": "number"}


def test_struct_to_blob_is_silent() -> None:
    encodings = {"x": {"field": "n"}, "y": {"field": "n"}}
    planned = _bind(
        pa.table(
            {
                "payload": pa.array(
                    [{"a": 1}], type=pa.struct([("a", pa.int64())])
                ),
                "n": [1],
            }
        ),
        transform=_ref("payload"),
        encodings=encodings,
        source_schema={"payload": "other"},
    )
    assert planned.source_schema == {"payload": "other"}
    refreshed = _bind(
        pa.table(
            {
                "payload": pa.array([b"hi"], type=pa.binary()),
                "n": [1],
            }
        ),
        transform=_ref("payload"),
        encodings=encodings,
        source_schema=planned.source_schema,
    )
    assert refreshed.source_schema == {"payload": "other"}


def test_array_type_is_other_not_number() -> None:
    envelope = _bind(
        pa.table(
            {
                "ids": pa.array([[1, 2]], type=pa.list_(pa.int64())),
                "n": [1],
            }
        ),
        transform=_ref("ids"),
        encodings={"x": {"field": "n"}, "y": {"field": "n"}},
        source_schema={"ids": "other"},
    )
    assert envelope.source_schema == {"ids": "other"}


@pytest.mark.parametrize(
    ("array", "bucket"),
    [
        (pa.array([1], type=pa.int32()), "number"),
        (pa.array(["Q1"], type=pa.string()), "string"),
        (pa.array([True], type=pa.bool_()), "boolean"),
        (pa.array([date(2020, 1, 1)], type=pa.date32()), "date"),
        (pa.array([datetime(2020, 1, 1)], type=pa.timestamp("us")), "timestamp"),
        (
            pa.array(
                [datetime(2020, 1, 1, tzinfo=UTC)],
                type=pa.timestamp("us", tz="UTC"),
            ),
            "timestamptz",
        ),
        (pa.array([time(12, 0)], type=pa.time64("us")), "other"),
        (pa.array([b"x"], type=pa.binary()), "other"),
    ],
)
def test_envelope_source_schema_uses_the_seven_buckets(
    array: pa.Array, bucket: str
) -> None:
    envelope = _bind(
        pa.table({"c": array, "n": [1]}),
        transform=_ref("c"),
        encodings={"x": {"field": "n"}, "y": {"field": "n"}},
    )
    assert envelope.source_schema == {"c": bucket}


def test_absent_baseline_is_retype_unchecked_not_an_error() -> None:
    envelope = _bind(_ROWS, transform=_ref("revenue"))
    assert envelope.source_schema == {"revenue": "number"}
    codes = [item.code for item in envelope.warnings]
    assert "retype_unchecked" in codes
    message = next(
        item.message for item in envelope.warnings if item.code == "retype_unchecked"
    )
    assert "revenue" in message
    assert "absent" in message


def test_partial_baseline_checks_named_columns_and_advises() -> None:
    envelope = _bind(
        _ROWS,
        transform={
            "filter": {
                "kind": "and",
                "args": [
                    {
                        "kind": "is_not_null",
                        "args": [{"kind": "col", "name": "revenue"}],
                    },
                    {
                        "kind": "is_not_null",
                        "args": [{"kind": "col", "name": "quarter"}],
                    },
                ],
            }
        },
        source_schema={"revenue": "number"},
    )
    assert envelope.source_schema == {"quarter": "string", "revenue": "number"}
    message = next(
        item.message for item in envelope.warnings if item.code == "retype_unchecked"
    )
    assert "quarter" in message
    assert "revenue" not in message.split(":")[-1]


def test_partial_baseline_still_raises_on_a_named_retype() -> None:
    with pytest.raises(SchemaDriftError) as caught:
        _bind(
            pa.table(
                {
                    "label": pa.array([date(2020, 1, 1)], type=pa.date32()),
                    "n": [1],
                }
            ),
            transform=_ref("label"),
            encodings={"x": {"field": "label"}, "y": {"field": "n"}},
            source_schema={"label": "string", "n": "number"},
        )
    assert caught.value.drifted[0].kind == "retyped"


def test_empty_baseline_object_is_partial() -> None:
    envelope = _bind(_ROWS, transform=_ref("revenue"), source_schema={})
    assert any(item.code == "retype_unchecked" for item in envelope.warnings)


def test_raw_sql_star_omits_source_schema() -> None:
    envelope = _bind(_ROWS, transform={"raw_sql": "SELECT * FROM source"})
    assert envelope.source_schema is None
    assert "source_schema" not in envelope.to_dict()["input"].get("x_chartagent", {})
    message = next(
        item.message for item in envelope.warnings if item.code == "retype_unchecked"
    )
    assert "STAR" in message


def test_raw_sql_named_columns_are_the_baseline() -> None:
    envelope = _bind(
        _ROWS,
        transform={"raw_sql": "SELECT quarter, revenue FROM source"},
        source_schema={"quarter": "string", "revenue": "number"},
    )
    assert envelope.source_schema == {"quarter": "string", "revenue": "number"}
    assert not any(item.code == "retype_unchecked" for item in envelope.warnings)


def test_limit_only_writes_empty_source_schema() -> None:
    envelope = _bind(_ROWS, transform={"limit": {"count": 100}})
    assert envelope.source_schema == {}
    assert not any(item.code == "retype_unchecked" for item in envelope.warnings)


def test_encoding_field_missing_from_output_is_transform_output_drift() -> None:
    with pytest.raises(SchemaDriftError) as caught:
        _bind(
            _ROWS,
            transform={"raw_sql": "SELECT quarter FROM source"},
            encodings={"x": {"field": "quarter"}, "y": {"field": "revenue"}},
        )
    err = caught.value
    assert err.stage == "transform_output"
    assert err.drifted[0].kind == "dropped"
    assert err.drifted[0].name == "revenue"


def test_semantic_types_key_missing_from_output_is_transform_output_drift() -> None:
    with pytest.raises(SchemaDriftError) as caught:
        _bind(
            _ROWS,
            transform={"raw_sql": "SELECT quarter FROM source"},
            encodings={"x": {"field": "quarter"}, "y": {"field": "quarter"}},
            semantic_types={"revenue": "Amount"},
        )
    assert caught.value.stage == "transform_output"
    assert caught.value.drifted[0].name == "revenue"


def test_menu_sort_key_missing_from_output_is_transform_output_drift() -> None:
    with pytest.raises(SchemaDriftError) as caught:
        _bind(
            _ROWS,
            transform={
                "group_by": ["quarter"],
                "aggregate": [{"name": "total", "op": "sum", "field": "revenue"}],
                "sort": [{"field": "revenue", "dir": "desc"}],
            },
            encodings={"x": {"field": "quarter"}, "y": {"field": "total"}},
        )
    err = caught.value
    assert err.stage == "transform_output"
    assert err.drifted[0].name == "revenue"
    assert err.drifted[0].kind == "dropped"


def test_bind_does_not_copy_source_schema_onto_the_input() -> None:
    envelope = _bind(_ROWS, transform=_ref("revenue"))
    xa = envelope.to_dict()["input"].get("x_chartagent", {})
    assert "source_schema" not in xa
    assert envelope.source_schema == {"revenue": "number"}


def test_invalid_source_schema_value_is_spec_shape_error() -> None:
    with pytest.raises(SpecShapeError):
        _bind(
            _ROWS,
            transform=_ref("revenue"),
            source_schema={"revenue": "integer"},
        )


def test_theme_spec_ignored_on_echarts() -> None:
    envelope = _bind(_ROWS, theme_spec="nyt")
    assert any(item.code == "theme_spec_ignored" for item in envelope.warnings)


def test_theme_spec_ignored_on_chartjs() -> None:
    envelope = _bind(_ROWS, theme_spec="nyt", backend="chartjs")
    assert any(item.code == "theme_spec_ignored" for item in envelope.warnings)


def test_theme_spec_is_kept_on_vegalite() -> None:
    envelope = _bind(_ROWS, theme_spec="nyt", backend="vegalite")
    assert not any(item.code == "theme_spec_ignored" for item in envelope.warnings)


def test_empty_result_advisory() -> None:
    envelope = _bind(
        _ROWS,
        transform={
            "filter": {
                "kind": "eq",
                "args": [
                    {"kind": "col", "name": "quarter"},
                    {"kind": "lit", "value": "none"},
                ],
            }
        },
    )
    assert envelope.row_count == 0
    assert any(item.code == "empty_result" for item in envelope.warnings)


def test_additive_drift_ignored_on_unreferenced_output() -> None:
    envelope = _bind(
        [{"quarter": "Q1", "revenue": 100, "extra": 1}],
        transform=_ref("revenue"),
    )
    assert any(item.code == "additive_drift_ignored" for item in envelope.warnings)


def test_dates_normalised_names_columns() -> None:
    envelope = _bind(
        pa.table(
            {
                "ts": pa.array(
                    [datetime(2020, 1, 1, tzinfo=UTC)],
                    type=pa.timestamp("us", tz="UTC"),
                ),
                "n": [1],
            }
        ),
        encodings={"x": {"field": "ts"}, "y": {"field": "n"}},
    )
    message = next(
        item.message for item in envelope.warnings if item.code == "dates_normalised"
    )
    assert "ts" in message


def test_non_finite_nulled_advisory() -> None:
    envelope = _bind(
        [{"x": float("inf"), "y": 1.0}],
        encodings={"x": {"field": "x"}, "y": {"field": "y"}},
    )
    assert any(item.code == "non_finite_nulled" for item in envelope.warnings)


def test_raw_sql_used_advisory() -> None:
    envelope = _bind(
        _ROWS,
        transform={"raw_sql": "SELECT quarter, revenue FROM source"},
        source_schema={"quarter": "string", "revenue": "number"},
    )
    assert any(item.code == "raw_sql_used" for item in envelope.warnings)


def test_no_predictive_layout_row_drop_warning() -> None:
    frame = {
        "chart_spec": {
            "chartType": "Bar Chart",
            "encodings": {"x": {"field": "quarter"}, "y": {"field": "revenue"}},
            "baseSize": {"width": 10, "height": 10},
        }
    }
    envelope = bind(frame, _ROWS * 50, backend="echarts")
    assert not any(
        "row" in item.code and "drop" in item.code for item in envelope.warnings
    )
    assert not any(item.code == "layout_row_drop" for item in envelope.warnings)
