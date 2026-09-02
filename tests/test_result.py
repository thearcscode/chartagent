"""ChartResult.refresh() — ADR-0020 Decision 2. Zero model calls, re-binds
against new rows, strips the inline ``data`` a stored envelope already
carries (test_bind.py's ``test_round_tripping_an_envelope_fails_loud`` is
exactly the failure this strips around).
"""

from __future__ import annotations

from chartagent import ChartResult, bind

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
    assert refreshed.envelope.input["data"]["values"] == _NEW_ROWS
    assert refreshed.envelope.backend == "echarts"
    assert refreshed.envelope.row_count == 3


def test_refresh_returns_a_new_result_and_leaves_the_original_untouched() -> None:
    result = ChartResult(envelope=bind(_FRAME, _ROWS, backend="echarts"))
    refreshed = result.refresh(_NEW_ROWS)
    assert refreshed is not result
    assert result.envelope.input["data"]["values"] == _ROWS
    assert result.envelope.row_count == 2


def test_refresh_does_not_pass_the_bound_input_straight_back_to_bind() -> None:
    # If refresh forwarded envelope.input unmodified, this would raise
    # SpecShapeError exactly as test_bind.py's round-trip test does.
    result = ChartResult(envelope=bind(_FRAME, _ROWS, backend="echarts"))
    result.refresh(_NEW_ROWS)  # no raise
