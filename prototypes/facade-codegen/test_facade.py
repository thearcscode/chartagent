"""PROTOTYPE — the assertion ticket #17 asks for:

    the generated facade admits EXACTLY what the pinned bundle admits.

    .venv/bin/pytest test_facade.py -q

Two directions, because only both together are load-bearing:
  admits   — every real fixture using chartProperties validates
  rejects  — invented keys, invented enum values, out-of-range numbers do not
"""
import importlib.util
import json
import pathlib
import re

import pytest
from pydantic import ValidationError

HERE = pathlib.Path(__file__).parent
FIXTURES = HERE.parent / "flint-embed" / "build" / "fixtures"
VOCAB = json.load(open(HERE / "build" / "vocab-0.5.1.json"))


def _load(path):
    spec = importlib.util.spec_from_file_location("facade", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


STRICT = _load(HERE / "build" / "facade_strict.py")
ADVISORY = _load(HERE / "build" / "facade_advisory.py")
facade = ADVISORY  # the mode the evidence supports; STRICT is kept to price it


def model_for(chart_type, backend="Vegalite", mod=None):
    mod = mod or facade
    return getattr(mod, backend + re.sub(r"\W", "_", chart_type) + "Properties", None)


def fixtures_with_properties():
    out = []
    for input_json in sorted(FIXTURES.glob("*/input.json")):
        doc = json.loads(input_json.read_text())
        props = doc.get("input", {}).get("chart_spec", {}).get("chartProperties")
        if props:
            out.append((input_json.parent.name, doc["chartType"], props))
    return out


CASES = fixtures_with_properties()


def test_corpus_is_the_expected_size():
    # 30 of 705 — thin evidence, which is why the rejects tests below matter more.
    assert len(CASES) == 30, f"expected 30 fixtures with chartProperties, found {len(CASES)}"


@pytest.mark.parametrize("name,chart_type,props", CASES, ids=[c[0] for c in CASES])
def test_admits_every_real_fixture(name, chart_type, props):
    model = model_for(chart_type)
    assert model is not None, f"no generated model for chartType {chart_type!r}"
    model.model_validate(props)


def test_every_chart_type_in_the_bundle_has_a_model():
    for chart in VOCAB["backends"]["vegalite"]:
        assert model_for(chart) is not None, f"vegalite/{chart} has no model"


def test_strict_mode_rejects_four_real_fixtures():
    """The price of extra='forbid' + min/max, measured rather than assumed.

    properties[] is a UI-affordance registry: it under-declares (Heatmap.colorScheme
    is honoured but undeclared), its min/max are slider bounds (Bar Table.maxRows
    declares min=5, yet 0 is a live sentinel), and removed keys linger in the corpus.
    """
    rejected = []
    for name, chart_type, props in CASES:
        model = model_for(chart_type, mod=STRICT)
        try:
            model.model_validate(props)
        except ValidationError:
            rejected.append((name, props))
    assert len(rejected) == 4, [r[0] for r in rejected]


def test_advisory_mode_admits_every_fixture_but_still_rejects_invented_enums():
    # Flint itself never rejects an unknown key — it silently ignores it. So a
    # facade cannot be "exactly as permissive as Flint" without admitting
    # everything. Advisory keeps the enum and type checks, which Flint lacks.
    model_for("Heatmap").model_validate({"colorScheme": "viridis"})  # undeclared, honoured
    with pytest.raises(ValidationError):
        model_for("Stacked Bar Chart").model_validate({"stackMode": "layered"})


def test_rejects_an_invented_enum_value():
    model = model_for("Stacked Bar Chart")
    model.model_validate({"stackMode": "normalize"})       # real in 0.5.1
    with pytest.raises(ValidationError):
        model.model_validate({"stackMode": "layered"})     # removed after 0.2.1


def test_wrong_type_is_still_rejected_in_advisory_mode():
    with pytest.raises(ValidationError):
        model_for("Scatter Plot").model_validate({"opacity": "very"})


def test_declared_bounds_are_advisory_not_enforced():
    model = model_for("Bar Table")
    model.model_validate({"maxRows": 0})   # below declared min=5, honoured by Flint
    assert model_for("Bar Table", mod=STRICT) is not None
    with pytest.raises(ValidationError):
        model_for("Bar Table", mod=STRICT).model_validate({"maxRows": 0})


def test_data_dependent_properties_are_not_enforced_here():
    # check() needs encodings, channelSemantics and the DATA ROWS. It cannot
    # cross into Python — so the facade must ADMIT what it cannot judge, and
    # leave applicability to the client where Flint already runs (ADR-0001).
    model = model_for("Scatter Plot")
    model.model_validate({"logScale_x": True})  # inapplicable without a quantitative x
    n = sum(p["data_dependent"] for c in VOCAB["backends"]["vegalite"].values()
            for p in c["properties"])
    total = sum(len(c["properties"]) for c in VOCAB["backends"]["vegalite"].values())
    assert n / total > 0.3, "if check() coverage collapsed, revisit the residue argument"
