from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError

import chartagent
from chartagent import (
    InputFrame,
    VegaliteBar_TableProperties,
    VegaliteChoroplethProperties,
    VegaliteHeatmapProperties,
    VegaliteKPI_CardProperties,
    VegaliteMapProperties,
    VegaliteRadar_ChartProperties,
    VegaliteRegressionProperties,
    VegaliteRose_ChartProperties,
    VegaliteScatter_PlotProperties,
    VegaliteStacked_Bar_ChartProperties,
    VegaliteStrip_PlotProperties,
    canonical_json,
    flint_bundle,
    vocabulary,
)
from chartagent.errors import SpecShapeError, SpecVocabularyError

_CASES = json.loads(
    Path(__file__).with_name("data").joinpath("chart_properties.json").read_text()
)
_DIRTY_INPUT = {
    "rose_chart__04__donut_rose_12_months_innerradius",
    "strip_plot__02__no_jitter_aligned_strip",
}
_MODELS: dict[str, type[BaseModel]] = {
    "Bar Table": VegaliteBar_TableProperties,
    "Choropleth": VegaliteChoroplethProperties,
    "Heatmap": VegaliteHeatmapProperties,
    "KPI Card": VegaliteKPI_CardProperties,
    "Map": VegaliteMapProperties,
    "Radar Chart": VegaliteRadar_ChartProperties,
    "Regression": VegaliteRegressionProperties,
    "Rose Chart": VegaliteRose_ChartProperties,
    "Scatter Plot": VegaliteScatter_PlotProperties,
    "Stacked Bar Chart": VegaliteStacked_Bar_ChartProperties,
    "Strip Plot": VegaliteStrip_PlotProperties,
}


def test_corpus_is_the_expected_size() -> None:
    assert len(_CASES) == 30


@pytest.mark.parametrize("case", _CASES, ids=[c["name"] for c in _CASES])
def test_admits_every_real_fixture(case: dict[str, object]) -> None:
    model = _MODELS[str(case["chartType"])]
    props = case["chartProperties"]
    assert isinstance(props, dict)
    if case["name"] in _DIRTY_INPUT:
        with pytest.raises(ValidationError):
            model.model_validate(props)
        return
    model.model_validate(props)


def test_rejects_invented_property_keys() -> None:
    VegaliteScatter_PlotProperties.model_validate({"logScale_y": True})
    for typo in ("logScale", "logscale_y", "logScaleY"):
        with pytest.raises(ValidationError):
            VegaliteScatter_PlotProperties.model_validate({typo: True})


def test_rejects_invented_enum_values() -> None:
    VegaliteStacked_Bar_ChartProperties.model_validate({"stackMode": "normalize"})
    with pytest.raises(ValidationError):
        VegaliteStacked_Bar_ChartProperties.model_validate({"stackMode": "layered"})


def test_encoding_actions_are_in_the_vocabulary() -> None:
    VegaliteHeatmapProperties.model_validate({"colorScheme": "viridis"})
    with pytest.raises(ValidationError):
        VegaliteHeatmapProperties.model_validate({"colorScheme": "not-a-scheme"})
    vocab = vocabulary("vegalite", "Heatmap")
    assert any(a.key == "colorScheme" for a in vocab.encoding_actions)


def test_canonical_json_omits_nulls_and_keeps_empty_collections() -> None:
    frame = InputFrame.model_validate(
        {
            "semantic_types": {},
            "chart_spec": {
                "chartType": "Bar Chart",
                "encodings": {"x": {"field": "quarter"}, "y": {"field": "revenue"}},
                "chartProperties": {},
            },
            "x_chartagent": {
                "spec_version": "1.2",
                "transform": None,
                "annotations": [],
                "interactions": {},
            },
        }
    )
    text = canonical_json(frame)
    parsed = json.loads(text)
    assert "theme_spec" not in parsed
    assert parsed["x_chartagent"]["annotations"] == []
    assert parsed["x_chartagent"]["interactions"] == {}
    assert parsed["chart_spec"]["chartProperties"] == {}
    assert "null" not in text


def test_vocabulary_excel_has_eighteen_chart_types() -> None:
    types = vocabulary("excel")
    assert len(types) == 18


def test_slider_bounds_are_not_validation_bounds() -> None:
    vocab = vocabulary("vegalite", "Bar Table")
    max_rows = next(p for p in vocab.properties if p.key == "maxRows")
    assert max_rows.min == 5
    VegaliteBar_TableProperties.model_validate({"maxRows": 0})


def test_pin_binding_iife_vocab_and_facade_constants() -> None:
    bundle = flint_bundle()
    assert bundle.sha256 == hashlib.sha256(bundle.read_bytes()).hexdigest()
    assert bundle.version == vocabulary.flint_version
    assert bundle.sha256 == vocabulary.bundle_sha256
    assert bundle.version == VegaliteBar_TableProperties.flint_version
    assert bundle.sha256 == VegaliteBar_TableProperties.bundle_sha256


def test_shorthand_encoding_round_trips_as_field_object() -> None:
    frame = InputFrame.model_validate(
        {
            "chart_spec": {
                "chartType": "Bar Chart",
                "encodings": {"x": "revenue", "y": {"field": "amount"}},
            }
        }
    )
    parsed = json.loads(frame.canonical_json())
    assert parsed["chart_spec"]["encodings"]["x"] == {"field": "revenue"}
    assert parsed["chart_spec"]["encodings"]["y"] == {"field": "amount"}


def test_unknown_channel_is_rejected_against_the_global_export() -> None:
    with pytest.raises(SpecVocabularyError) as caught:
        InputFrame.model_validate(
            {
                "chart_spec": {
                    "chartType": "Bar Chart",
                    "encodings": {"colour": {"field": "revenue"}},
                }
            }
        )
    assert caught.value.kind == "channel"
    assert "colour" in caught.value.keys


def test_undeclared_per_type_channel_is_admitted() -> None:
    frame = InputFrame.model_validate(
        {
            "chart_spec": {
                "chartType": "Area Chart",
                "encodings": {"x": "t", "y": "v", "detail": "g"},
            }
        }
    )
    assert "detail" in frame.chart_spec.encodings


def test_aggregate_on_an_encoding_is_forbidden() -> None:
    with pytest.raises(SpecVocabularyError) as caught:
        InputFrame.model_validate(
            {
                "chart_spec": {
                    "chartType": "Bar Chart",
                    "encodings": {
                        "x": {"field": "quarter", "aggregate": "sum"},
                    },
                }
            }
        )
    assert caught.value.kind == "encoding_key"
    assert "aggregate" in caught.value.keys


def test_theme_spec_null_is_rejected() -> None:
    with pytest.raises(SpecShapeError):
        InputFrame.model_validate(
            {
                "chart_spec": {
                    "chartType": "Bar Chart",
                    "encodings": {"x": "quarter"},
                },
                "theme_spec": None,
            }
        )


def test_generated_constants_are_not_on_the_package() -> None:
    for name in ("CHANNELS", "FLINT_VERSION", "GeneratedProperties", "ChartType"):
        assert name not in chartagent.__all__
        assert not hasattr(chartagent, name)
