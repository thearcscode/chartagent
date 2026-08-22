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
KEYS = _load(HERE / "build" / "facade_keys.py")
facade = KEYS  # the mode the evidence supports; the other two price the extremes


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


# These two fixtures set keys the pinned 0.5.1 bundle does not declare and
# does not honour — the corpus pin (34ef451) is older than the Flint pin.
# They are drift, not a facade defect. See the #24 hazard note.
CORPUS_DRIFT = {
    "rose_chart__04__donut_rose_12_months_innerradius",   # innerRadius, removed in 0.5.1
    "strip_plot__02__no_jitter_aligned_strip",            # jitterWidth, never declared
}


@pytest.mark.parametrize("name,chart_type,props", CASES, ids=[c[0] for c in CASES])
def test_admits_every_real_fixture(name, chart_type, props):
    model = model_for(chart_type)
    assert model is not None, f"no generated model for chartType {chart_type!r}"
    if name in CORPUS_DRIFT:
        with pytest.raises(ValidationError):
            model.model_validate(props)
        pytest.skip("corpus pin predates the Flint pin — key is dead at 0.5.1")
    model.model_validate(props)


def test_every_chart_type_in_the_bundle_has_a_model():
    for chart in VOCAB["backends"]["vegalite"]:
        assert model_for(chart) is not None, f"vegalite/{chart} has no model"


def _rejected_by(mod):
    out = []
    for name, chart_type, props in CASES:
        try:
            model_for(chart_type, mod=mod).model_validate(props)
        except ValidationError:
            out.append(name)
    return out


def test_the_three_modes_are_priced_against_the_corpus():
    """Where each mode's strictness actually costs something.

    strict    27/30 — also enforces min/max, which kills the maxRows sentinel
    keys      28/30 — forbids unknown NAMES only; the 2 losses are stale corpus
    advisory  30/30 — forbids nothing, so it catches no misspelling either
    """
    assert len(_rejected_by(STRICT)) == 3
    assert len(_rejected_by(ADVISORY)) == 0
    assert _rejected_by(KEYS) == [
        "rose_chart__04__donut_rose_12_months_innerradius",   # removed in 0.5.1
        "strip_plot__02__no_jitter_aligned_strip",            # never declared
    ]


def test_the_two_keys_mode_rejects_are_both_ignored_by_flint_anyway():
    # Neither key changes the compiled output at the pin (measured in the
    # probe), so rejecting them loses no capability — it reports corpus drift.
    # This is the #24 pin-drift hazard, not a facade design cost.
    for chart, key in [("Rose Chart", "innerRadius"), ("Strip Plot", "jitterWidth")]:
        vocab_keys = {p["key"] for p in VOCAB["backends"]["vegalite"][chart]["properties"]}
        assert key not in vocab_keys


def test_encoding_actions_are_part_of_the_vocabulary():
    # The vocabulary lives in TWO arrays. Reading only properties[] misses 21
    # entries and makes colorScheme look undeclared when it is not.
    model_for("Heatmap").model_validate({"colorScheme": "viridis"})
    with pytest.raises(ValidationError):
        model_for("Heatmap").model_validate({"colorScheme": "not-a-scheme"})
    from_actions = [p for c in VOCAB["backends"]["vegalite"].values()
                    for p in c["properties"] if p["source"] == "encodingActions"]
    assert {p["key"] for p in from_actions} == {"colorScheme", "sort"}


def test_keys_mode_catches_a_misspelled_property():
    model_for("Scatter Plot").model_validate({"logScale_y": True})
    for typo in ("logScale", "logscale_y", "logScaleY"):
        with pytest.raises(ValidationError):
            model_for("Scatter Plot").model_validate({typo: True})


def test_rejects_an_invented_enum_value():
    model = model_for("Stacked Bar Chart")
    model.model_validate({"stackMode": "normalize"})       # real in 0.5.1
    with pytest.raises(ValidationError):
        model.model_validate({"stackMode": "layered"})     # removed after 0.2.1


def test_wrong_type_is_still_rejected_in_advisory_mode():
    with pytest.raises(ValidationError):
        model_for("Scatter Plot").model_validate({"opacity": "very"})


def test_declared_bounds_are_ui_bounds_not_validation_bounds():
    # min/max drive a slider. Bar Table.maxRows declares min=5, but 0 is a live
    # "no limit" sentinel that Flint honours — the compiled spec differs from
    # both 5 and 20. Only `strict` mode pretends the bound is a rule.
    model_for("Bar Table").model_validate({"maxRows": 0})
    with pytest.raises(ValidationError):
        model_for("Bar Table", mod=STRICT).model_validate({"maxRows": 0})


def test_data_dependent_properties_are_not_enforced_here():
    # check() needs encodings, channelSemantics and the DATA ROWS. It cannot
    # cross into Python — so the facade must ADMIT what it cannot judge, and
    # leave applicability to the client where Flint already runs (ADR-0001).
    model = model_for("Scatter Plot")
    model.model_validate({"logScale_x": True})  # inapplicable without a quantitative x
    n = sum(bool(p["data_dependent"]) for c in VOCAB["backends"]["vegalite"].values()
            for p in c["properties"])
    total = sum(len(c["properties"]) for c in VOCAB["backends"]["vegalite"].values())
    assert n / total > 0.3, "if check() coverage collapsed, revisit the residue argument"
