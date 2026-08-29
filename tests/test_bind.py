from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path

import pyarrow as pa
import pytest

from chartagent import bind
from chartagent.errors import (
    BackendCapabilityError,
    DataSourceError,
    SpecShapeError,
    SpecVocabularyError,
    TransformError,
)

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


def test_type_in_the_union_but_not_this_backend_is_capability_error() -> None:
    frame = {
        "chart_spec": {
            "chartType": "Regression",
            "encodings": {"x": {"field": "quarter"}, "y": {"field": "revenue"}},
        }
    }
    with pytest.raises(BackendCapabilityError) as caught:
        bind(frame, _ROWS, backend="excel")
    assert caught.value.kind == "chart_type"
    assert "Regression" in caught.value.keys


def test_rose_chart_inner_radius_is_a_vocabulary_error() -> None:
    frame = {
        "chart_spec": {
            "chartType": "Rose Chart",
            "encodings": {"x": {"field": "quarter"}, "y": {"field": "revenue"}},
            "chartProperties": {"innerRadius": 40},
        }
    }
    with pytest.raises(SpecVocabularyError) as caught:
        bind(frame, _ROWS, backend="vegalite")
    err = caught.value
    assert err.kind == "property"
    assert "innerRadius" in err.keys
    assert err.chart_type == "Rose Chart"
    assert err.backend == "vegalite"
    assert err.pin == "0.5.1"


def test_property_declared_on_another_backend_is_capability_error() -> None:
    frame = {
        "chart_spec": {
            "chartType": "Rose Chart",
            "encodings": {"x": {"field": "quarter"}, "y": {"field": "revenue"}},
            "chartProperties": {"padAngle": 0.05},
        }
    }
    with pytest.raises(BackendCapabilityError) as caught:
        bind(frame, _ROWS, backend="echarts")
    err = caught.value
    assert err.kind == "property"
    assert "padAngle" in err.keys
    assert err.chart_type == "Rose Chart"
    assert err.backend == "echarts"


def test_excel_facet_channel_is_capability_error() -> None:
    frame = {
        "chart_spec": {
            "chartType": "Bar Chart",
            "encodings": {
                "x": {"field": "quarter"},
                "y": {"field": "revenue"},
                "column": {"field": "quarter"},
            },
        }
    }
    with pytest.raises(BackendCapabilityError) as caught:
        bind(frame, _ROWS, backend="excel")
    err = caught.value
    assert err.kind == "facet"
    assert err.keys == ("column",)
    assert err.backend == "excel"


def test_unknown_enum_option_is_a_vocabulary_error() -> None:
    frame = {
        "chart_spec": {
            "chartType": "Stacked Bar Chart",
            "encodings": {"x": {"field": "quarter"}, "y": {"field": "revenue"}},
            "chartProperties": {"stackMode": "layered"},
        }
    }
    with pytest.raises(SpecVocabularyError) as caught:
        bind(frame, _ROWS, backend="vegalite")
    assert caught.value.kind == "enum_option"
    assert "layered" in caught.value.keys


def test_hallucinated_chart_type_is_a_vocabulary_error() -> None:
    frame = {
        "chart_spec": {
            "chartType": "Bogus Chart",
            "encodings": {"x": {"field": "quarter"}, "y": {"field": "revenue"}},
        }
    }
    with pytest.raises(SpecVocabularyError) as caught:
        bind(frame, _ROWS, backend="echarts")
    assert caught.value.kind == "chart_type"
    assert "Bogus Chart" in caught.value.keys
    assert caught.value.backend == "echarts"
    assert caught.value.chart_type == "Bogus Chart"
    assert caught.value.pin == "0.5.1"


def test_misspelled_colour_channel_is_a_vocabulary_error() -> None:
    frame = {
        "chart_spec": {
            "chartType": "Bar Chart",
            "encodings": {"colour": {"field": "quarter"}, "y": {"field": "revenue"}},
        }
    }
    with pytest.raises(SpecVocabularyError) as caught:
        bind(frame, _ROWS, backend="echarts")
    assert caught.value.kind == "channel"
    assert "colour" in caught.value.keys


def test_undeclared_but_honoured_channel_still_binds() -> None:
    frame = {
        "chart_spec": {
            "chartType": "Area Chart",
            "encodings": {
                "x": {"field": "quarter"},
                "y": {"field": "revenue"},
                "detail": {"field": "quarter"},
            },
        }
    }
    envelope = bind(frame, _ROWS, backend="vegalite")
    assert "detail" in envelope.input["chart_spec"]["encodings"]


def test_encoding_aggregate_is_rejected() -> None:
    frame = {
        "chart_spec": {
            "chartType": "Bar Chart",
            "encodings": {
                "x": {"field": "quarter"},
                "y": {"field": "revenue", "aggregate": "sum"},
            },
        }
    }
    with pytest.raises(SpecVocabularyError) as caught:
        bind(frame, _ROWS, backend="echarts")
    assert caught.value.kind == "encoding_key"
    assert "aggregate" in caught.value.keys


def test_theme_spec_null_is_a_spec_shape_error() -> None:
    with pytest.raises(SpecShapeError):
        bind({**_FRAME, "theme_spec": None}, _ROWS, backend="echarts")


def test_unknown_theme_preset_is_a_vocabulary_error() -> None:
    with pytest.raises(SpecVocabularyError) as caught:
        bind({**_FRAME, "theme_spec": "notatheme"}, _ROWS, backend="vegalite")
    assert caught.value.kind == "theme_preset"
    assert "notatheme" in caught.value.keys


def test_unknown_semantic_type_is_a_vocabulary_error() -> None:
    with pytest.raises(SpecVocabularyError) as caught:
        bind(
            {**_FRAME, "semantic_types": {"quarter": "NotAType"}},
            _ROWS,
            backend="echarts",
        )
    assert caught.value.kind == "semantic_type"
    assert "NotAType" in caught.value.keys


def test_three_bad_property_keys_are_one_error() -> None:
    frame = {
        "chart_spec": {
            "chartType": "Rose Chart",
            "encodings": {"x": {"field": "quarter"}, "y": {"field": "revenue"}},
            "chartProperties": {
                "innerRadius": 40,
                "jitterWidth": 12,
                "notARealKey": True,
            },
        }
    }
    with pytest.raises(SpecVocabularyError) as caught:
        bind(frame, _ROWS, backend="vegalite")
    assert caught.value.kind == "property"
    assert set(caught.value.keys) == {"innerRadius", "jitterWidth", "notARealKey"}


def test_excel_undeclared_type_wins_over_facet() -> None:
    frame = {
        "chart_spec": {
            "chartType": "Regression",
            "encodings": {
                "x": {"field": "quarter"},
                "y": {"field": "revenue"},
                "column": {"field": "quarter"},
            },
        }
    }
    with pytest.raises(BackendCapabilityError) as caught:
        bind(frame, _ROWS, backend="excel")
    assert caught.value.kind == "chart_type"


def test_bogus_channel_is_not_hidden_by_backend_chart_type() -> None:
    frame = {
        "chart_spec": {
            "chartType": "Regression",
            "encodings": {"colour": {"field": "quarter"}, "y": {"field": "revenue"}},
        }
    }
    with pytest.raises(SpecVocabularyError) as caught:
        bind(frame, _ROWS, backend="excel")
    assert caught.value.kind == "channel"
    assert "colour" in caught.value.keys


def test_kpi_card_binds_on_vegalite() -> None:
    frame = {
        "chart_spec": {
            "chartType": "KPI Card",
            "encodings": {"metric": {"field": "revenue"}},
        }
    }
    envelope = bind(frame, _ROWS, backend="vegalite")
    assert envelope.input["chart_spec"]["chartType"] == "KPI Card"


def test_bar_table_max_rows_zero_binds() -> None:
    frame = {
        "chart_spec": {
            "chartType": "Bar Table",
            "encodings": {"x": {"field": "quarter"}, "y": {"field": "revenue"}},
            "chartProperties": {"maxRows": 0},
        }
    }
    envelope = bind(frame, _ROWS, backend="vegalite")
    assert envelope.input["chart_spec"]["chartProperties"]["maxRows"] == 0


def test_options_extra_keys_still_bind() -> None:
    envelope = bind(
        {**_FRAME, "options": {"defaultBandSize": 20, "addTooltip": True}},
        _ROWS,
        backend="echarts",
    )
    assert envelope.input["options"]["defaultBandSize"] == 20


def test_excel_without_facet_channels_binds() -> None:
    envelope = bind(_FRAME, _ROWS, backend="excel")
    assert envelope.backend == "excel"


def test_excel_column_and_row_are_one_facet_error() -> None:
    frame = {
        "chart_spec": {
            "chartType": "Bar Chart",
            "encodings": {
                "x": {"field": "quarter"},
                "y": {"field": "revenue"},
                "column": {"field": "quarter"},
                "row": {"field": "quarter"},
            },
        }
    }
    with pytest.raises(BackendCapabilityError) as caught:
        bind(frame, _ROWS, backend="excel")
    assert caught.value.kind == "facet"
    assert caught.value.keys == ("column", "row")


def test_property_validation_error_does_not_cross_the_seam() -> None:
    from pydantic import ValidationError

    frame = {
        "chart_spec": {
            "chartType": "Rose Chart",
            "encodings": {"x": {"field": "quarter"}, "y": {"field": "revenue"}},
            "chartProperties": {"innerRadius": 40},
        }
    }
    with pytest.raises(SpecVocabularyError) as caught:
        bind(frame, _ROWS, backend="vegalite")
    assert isinstance(caught.value.__cause__, ValidationError)
