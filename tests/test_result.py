"""ChartResult.refresh() — ADR-0020 Decision 2. Zero model calls, re-binds
against new rows, strips the inline ``data`` a stored envelope already
carries (test_bind.py's ``test_round_tripping_an_envelope_fails_loud`` is
exactly the failure this strips around).
"""

from __future__ import annotations

import pytest

from chartagent import ChartResult, bind
from chartagent.errors import SchemaDriftError

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

_NEW_ROWS = [
    {"quarter": "Q1", "revenue": 100},
    {"quarter": "Q2", "revenue": 200},
    {"quarter": "Q3", "revenue": 300},
]


def test_refresh_rebinds_against_new_rows_with_the_same_backend() -> None:
    result = ChartResult(envelope=bind(_FRAME, _ROWS, backend="echarts"))
    refreshed = result.refresh(_NEW_ROWS)
    assert refreshed.envelope is not None
    assert refreshed.envelope.input["data"]["values"] == _NEW_ROWS
    assert refreshed.envelope.backend == "echarts"
    assert refreshed.envelope.row_count == 3


def test_refresh_returns_a_new_result_and_leaves_the_original_untouched() -> None:
    result = ChartResult(envelope=bind(_FRAME, _ROWS, backend="echarts"))
    refreshed = result.refresh(_NEW_ROWS)
    assert refreshed is not result
    assert result.envelope is not None
    assert result.envelope.input["data"]["values"] == _ROWS
    assert result.envelope.row_count == 2


def test_refresh_does_not_pass_the_bound_input_straight_back_to_bind() -> None:
    # If refresh forwarded envelope.input unmodified, this would raise
    # SpecShapeError exactly as test_bind.py's round-trip test does.
    result = ChartResult(envelope=bind(_FRAME, _ROWS, backend="echarts"))
    result.refresh(_NEW_ROWS)  # no raise


def test_refresh_still_raises_schema_drift_on_genuinely_new_rows() -> None:
    # #137's belt fix catches SpecShapeError/SchemaDriftError inside
    # create_chart, not inside bind() itself. refresh() calls bind()
    # directly and is not that seam: rows that later drop a column the
    # stored transform names must still raise SchemaDriftError, unwrapped.
    frame = {
        "chart_spec": {
            "chartType": "Bar Chart",
            "encodings": {"x": {"field": "quarter"}, "y": {"field": "revenue"}},
        },
        "x_chartagent": {
            "transform": {
                "filter": {
                    "kind": "is_not_null",
                    "args": [{"kind": "col", "name": "revenue"}],
                }
            }
        },
    }
    result = ChartResult(envelope=bind(frame, _ROWS, backend="echarts"))
    dropped_column = [{"quarter": "Q3"}, {"quarter": "Q4"}]
    with pytest.raises(SchemaDriftError) as caught:
        result.refresh(dropped_column)
    assert caught.value.stage == "source"


# --- XOR payload, review, and the recipe rail (ADR-0027 Decision 9) ---------

from chartagent import (  # noqa: E402
    ChartDocument,
    ChartRecipe,
    EscapeReason,
    ReviewReport,
)
from chartagent.transform.model import Menu  # noqa: E402

_RECIPE = ChartRecipe(
    spec_version="1.2",
    transform=Menu.model_validate(
        {
            "group_by": ["quarter"],
            "aggregate": [{"name": "total", "op": "sum", "field": "revenue"}],
        }
    ),
    source_schema={"quarter": "string", "revenue": "number"},
    escape_reason=EscapeReason(bucket=4),
    theme_spec=None,
    document=ChartDocument(module="export default () => {}", styles=None, libraries=()),
)
_REPORT = ReviewReport(
    tiers_run=(1,),
    tiers_skipped={2: "unavailable"},
    passed=True,
    budget_exhausted=False,
    checks=(),
)


def test_a_result_with_both_payloads_is_impossible() -> None:
    envelope = bind(_FRAME, _ROWS, backend="echarts")
    with pytest.raises(ValueError):
        ChartResult(envelope=envelope, recipe=_RECIPE)


def test_a_result_with_neither_payload_is_impossible() -> None:
    with pytest.raises(ValueError):
        ChartResult()


def test_refresh_on_an_envelope_result_sets_review_to_none() -> None:
    result = ChartResult(
        envelope=bind(_FRAME, _ROWS, backend="echarts"), review=_REPORT
    )
    refreshed = result.refresh(_NEW_ROWS)
    assert result.review is _REPORT
    assert refreshed.review is None


def test_refresh_on_a_recipe_result_rebinds_and_sets_review_to_none() -> None:
    result = ChartResult(recipe=_RECIPE, review=_REPORT)
    refreshed = result.refresh(_NEW_ROWS)
    assert refreshed is not result
    assert refreshed.review is None
    assert refreshed.envelope is None
    assert refreshed.recipe is _RECIPE
    assert refreshed.bound is not None
    assert refreshed.bound.row_count == 3


def test_recipe_refresh_fails_on_drift_like_bind() -> None:
    result = ChartResult(recipe=_RECIPE, review=_REPORT)
    with pytest.raises(SchemaDriftError):
        result.refresh([{"quarter": "Q3"}])
