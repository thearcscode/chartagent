from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path

import pyarrow as pa
import pytest

from chartagent import bind
from chartagent.errors import DataSourceError, SpecShapeError, TransformError

_FIXTURES = Path(__file__).with_name("data")

_FRAME = {
    "chart_spec": {
        "chartType": "Bar Chart",
        "encodings": {"x": {"field": "quarter"}, "y": {"field": "revenue"}},
    }
}

_ROWS = [
    {"quarter": "Q1", "revenue": 100},
    {"quarter": "Q2", "revenue": 200},
]


def test_list_of_dicts_attaches_source_rows() -> None:
    envelope = bind(_FRAME, _ROWS, backend="echarts")
    assert envelope.input["data"]["values"] == _ROWS
    assert envelope.backend == "echarts"


def test_wire_format_is_exactly_three_keys() -> None:
    envelope = bind(_FRAME, _ROWS, backend="echarts")
    dumped = envelope.to_dict()
    assert set(dumped) == {"flint_version", "backend", "input"}
    assert dumped == envelope.model_dump()
    for key in ("row_count", "elapsed", "warnings", "source_schema"):
        assert key not in dumped["input"]
    assert envelope.row_count == 2
    assert envelope.elapsed >= 0.0
    assert envelope.warnings == ()
    assert envelope.source_schema == {"quarter": "string", "revenue": "number"}


def test_inline_data_is_a_spec_shape_error() -> None:
    with pytest.raises(SpecShapeError):
        bind({**_FRAME, "data": {"values": _ROWS}}, _ROWS, backend="echarts")


def test_round_tripping_an_envelope_fails_loud() -> None:
    envelope = bind(_FRAME, _ROWS, backend="echarts")
    with pytest.raises(SpecShapeError):
        bind(envelope.to_dict()["input"], _ROWS, backend="echarts")


def test_csv_path_attaches_source_rows() -> None:
    envelope = bind(_FRAME, _FIXTURES / "sales.csv", backend="vegalite")
    assert envelope.input["data"]["values"] == _ROWS
    assert envelope.backend == "vegalite"


def test_parquet_path_attaches_source_rows() -> None:
    envelope = bind(_FRAME, _FIXTURES / "sales.parquet", backend="plotly")
    assert envelope.input["data"]["values"] == _ROWS


def test_arrow_table_attaches_source_rows() -> None:
    table = pa.table({"quarter": ["Q1", "Q2"], "revenue": [100, 200]})
    envelope = bind(_FRAME, table, backend="chartjs")
    assert envelope.input["data"]["values"] == _ROWS


def test_unreadable_path_is_a_data_source_error() -> None:
    missing = _FIXTURES / "no-such-source.csv"
    with pytest.raises(DataSourceError):
        bind(_FRAME, missing, backend="echarts")


def test_varchar_jan_2020_is_untouched() -> None:
    frame = {
        "chart_spec": {
            "chartType": "Bar Chart",
            "encodings": {"x": {"field": "label"}, "y": {"field": "n"}},
        }
    }
    envelope = bind(
        frame,
        [{"label": "Jan 2020", "n": 1}],
        backend="echarts",
    )
    assert envelope.input["data"]["values"] == [{"label": "Jan 2020", "n": 1}]
    assert not any(item.code == "dates_normalised" for item in envelope.warnings)


@pytest.mark.parametrize("tz", ["UTC", "America/New_York", "Asia/Kolkata"])
def test_timestamptz_serialises_with_trailing_z(tz: str) -> None:
    original = os.environ.get("TZ")
    os.environ["TZ"] = tz
    if hasattr(time, "tzset"):
        time.tzset()
    try:
        frame = {
            "chart_spec": {
                "chartType": "Bar Chart",
                "encodings": {"x": {"field": "ts"}, "y": {"field": "n"}},
            }
        }
        instant = datetime(2020, 1, 15, 6, 30, tzinfo=UTC)
        table = pa.table(
            {
                "ts": pa.array([instant], type=pa.timestamp("us", tz="UTC")),
                "n": [1],
            }
        )
        envelope = bind(frame, table, backend="echarts")
        value = envelope.input["data"]["values"][0]["ts"]
        assert isinstance(value, str)
        assert value.endswith("Z")
        assert value.startswith("2020-01-15T06:30:00")
        assert any(item.code == "dates_normalised" for item in envelope.warnings)
    finally:
        if original is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = original
        if hasattr(time, "tzset"):
            time.tzset()


def test_non_finite_float_becomes_json_null() -> None:
    frame = {
        "chart_spec": {
            "chartType": "Bar Chart",
            "encodings": {"x": {"field": "x"}, "y": {"field": "y"}},
        }
    }
    envelope = bind(
        frame,
        [{"x": float("inf"), "y": 1.0}],
        backend="echarts",
    )
    assert envelope.input["data"]["values"] == [{"x": None, "y": 1.0}]
    payload = json.dumps(envelope.to_dict())
    assert "Infinity" not in payload
    json.loads(payload)
    assert any(item.code == "non_finite_nulled" for item in envelope.warnings)


def test_backend_is_a_required_keyword() -> None:
    with pytest.raises(TypeError):
        bind(_FRAME, _ROWS)  # type: ignore[call-arg]


def test_pydantic_validation_error_does_not_cross_the_seam() -> None:
    from pydantic import ValidationError

    with pytest.raises(SpecShapeError) as caught:
        bind({"not": "a frame"}, _ROWS, backend="echarts")
    assert isinstance(caught.value.__cause__, ValidationError)


def test_timeout_cancels_an_in_flight_transform() -> None:
    n = 4_000_000
    table = pa.table({"quarter": pa.array(range(n)), "revenue": pa.array(range(n))})
    with pytest.raises(TransformError, match="timed out"):
        bind(_FRAME, table, backend="echarts", timeout=0.001)
