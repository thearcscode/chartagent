from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Any

import pyarrow as pa
import pytest

from chartagent import bind
from chartagent.bind import DataSource
from chartagent.envelope import Envelope
from chartagent.errors import SpecShapeError

_ROWS = [
    {"quarter": "Q1", "revenue": 100},
    {"quarter": "Q2", "revenue": 200},
]


def _bind(
    transform: Mapping[str, object],
    rows: DataSource = _ROWS,
    *,
    encodings: dict[str, Any] | None = None,
) -> Envelope:
    frame = {
        "chart_spec": {
            "chartType": "Bar Chart",
            "encodings": encodings
            or {"x": {"field": "quarter"}, "y": {"field": "revenue"}},
        },
        "x_chartagent": {"transform": transform},
    }
    return bind(frame, rows, backend="echarts")


def test_unknown_slot_is_a_spec_shape_error() -> None:
    with pytest.raises(SpecShapeError, match="unrecognised"):
        _bind({"pivot": []})


def test_filter_keeps_rows_matching_the_predicate() -> None:
    envelope = _bind(
        {
            "filter": {
                "kind": "gt",
                "args": [
                    {"kind": "col", "name": "revenue"},
                    {"kind": "lit", "value": 100},
                ],
            }
        }
    )
    assert envelope.input["data"]["values"] == [{"quarter": "Q2", "revenue": 200}]


def test_derive_adds_a_computed_column() -> None:
    envelope = _bind(
        {
            "derive": [
                {
                    "name": "double",
                    "expr": {
                        "kind": "add",
                        "args": [
                            {"kind": "col", "name": "revenue"},
                            {"kind": "col", "name": "revenue"},
                        ],
                    },
                }
            ]
        }
    )
    assert envelope.input["data"]["values"] == [
        {"quarter": "Q1", "revenue": 100, "double": 200},
        {"quarter": "Q2", "revenue": 200, "double": 400},
    ]


def test_having_can_filter_a_derived_column() -> None:
    envelope = _bind(
        {
            "derive": [
                {
                    "name": "double",
                    "expr": {
                        "kind": "add",
                        "args": [
                            {"kind": "col", "name": "revenue"},
                            {"kind": "col", "name": "revenue"},
                        ],
                    },
                }
            ],
            "having": {
                "kind": "gt",
                "args": [
                    {"kind": "col", "name": "double"},
                    {"kind": "lit", "value": 200},
                ],
            },
        }
    )
    assert envelope.input["data"]["values"] == [
        {"quarter": "Q2", "revenue": 200, "double": 400}
    ]


def test_temporal_bin_emits_date_not_a_label() -> None:
    rows = pa.table(
        {
            "ordered_at": pa.array(
                [date(2020, 3, 15), date(2020, 3, 20), date(2020, 4, 2)],
                type=pa.date32(),
            ),
            "revenue": [10, 20, 30],
        }
    )
    envelope = _bind(
        {
            "bin": [{"name": "month", "field": "ordered_at", "unit": "month"}],
            "group_by": ["month"],
            "aggregate": [{"name": "revenue_sum", "op": "sum", "field": "revenue"}],
            "sort": [{"field": "month", "dir": "asc", "nulls": "last"}],
        },
        rows,
        encodings={"x": {"field": "month"}, "y": {"field": "revenue_sum"}},
    )
    values = envelope.input["data"]["values"]
    assert [row["month"] for row in values] == ["2020-03-01", "2020-04-01"]
    assert [row["revenue_sum"] for row in values] == [30, 30]
    assert all(isinstance(row["month"], str) for row in values)
    assert not any("Mar" in row["month"] for row in values)


def test_group_by_without_aggregate_is_distinct() -> None:
    envelope = _bind(
        {"group_by": ["quarter"]},
        [
            {"quarter": "Q1", "revenue": 100},
            {"quarter": "Q1", "revenue": 150},
            {"quarter": "Q2", "revenue": 200},
        ],
    )
    values = envelope.input["data"]["values"]
    assert sorted(row["quarter"] for row in values) == ["Q1", "Q2"]
    assert all(set(row) == {"quarter"} for row in values)


def test_aggregate_without_group_by_is_one_row() -> None:
    envelope = _bind(
        {"aggregate": [{"name": "revenue_sum", "op": "sum", "field": "revenue"}]},
        encodings={"x": {"field": "quarter"}, "y": {"field": "revenue_sum"}},
    )
    assert envelope.input["data"]["values"] == [{"revenue_sum": 300}]


def test_having_out_of_scope_is_a_spec_shape_error() -> None:
    with pytest.raises(SpecShapeError, match="not in scope"):
        _bind(
            {
                "group_by": ["quarter"],
                "aggregate": [{"name": "revenue_sum", "op": "sum", "field": "revenue"}],
                "having": {
                    "kind": "gt",
                    "args": [
                        {"kind": "col", "name": "revenue"},
                        {"kind": "lit", "value": 0},
                    ],
                },
            }
        )


def test_sort_then_limit_is_not_limit_then_sort() -> None:
    envelope = _bind(
        {
            "sort": [{"field": "revenue", "dir": "desc", "nulls": "last"}],
            "limit": {"count": 1},
        },
        [
            {"quarter": "Q1", "revenue": 100},
            {"quarter": "Q2", "revenue": 200},
        ],
    )
    assert envelope.input["data"]["values"] == [{"quarter": "Q2", "revenue": 200}]


def test_limit_over_ties_is_stable_across_two_binds() -> None:
    transform = {"limit": {"count": 2}}
    rows = [
        {"quarter": "Q1", "revenue": 100},
        {"quarter": "Q2", "revenue": 100},
        {"quarter": "Q3", "revenue": 100},
    ]
    first = _bind(transform, rows).input["data"]["values"]
    second = _bind(transform, rows).input["data"]["values"]
    assert first == second
    assert len(first) == 2


def test_concat_skips_nulls() -> None:
    envelope = _bind(
        {
            "derive": [
                {
                    "name": "label",
                    "expr": {
                        "kind": "concat",
                        "args": [
                            {"kind": "col", "name": "quarter"},
                            {"kind": "lit", "value": None},
                            {"kind": "lit", "value": "-x"},
                        ],
                    },
                }
            ]
        }
    )
    assert [row["label"] for row in envelope.input["data"]["values"]] == [
        "Q1-x",
        "Q2-x",
    ]


def test_in_rhs_must_be_literals() -> None:
    with pytest.raises(SpecShapeError, match="literals"):
        _bind(
            {
                "filter": {
                    "kind": "in",
                    "args": [
                        {"kind": "col", "name": "revenue"},
                        {"kind": "col", "name": "revenue"},
                    ],
                }
            }
        )


def test_case_requires_else() -> None:
    with pytest.raises(SpecShapeError, match="else"):
        _bind(
            {
                "derive": [
                    {
                        "name": "bucket",
                        "expr": {
                            "kind": "case",
                            "whens": [
                                {
                                    "when": {
                                        "kind": "gt",
                                        "args": [
                                            {"kind": "col", "name": "revenue"},
                                            {"kind": "lit", "value": 100},
                                        ],
                                    },
                                    "then": {"kind": "lit", "value": "high"},
                                }
                            ],
                        },
                    }
                ]
            }
        )


def test_div_by_zero_is_null() -> None:
    envelope = _bind(
        {
            "derive": [
                {
                    "name": "ratio",
                    "expr": {
                        "kind": "div",
                        "args": [
                            {"kind": "col", "name": "revenue"},
                            {"kind": "col", "name": "revenue"},
                        ],
                    },
                }
            ]
        },
        [{"quarter": "Q1", "revenue": 0}],
    )
    assert envelope.input["data"]["values"] == [
        {"quarter": "Q1", "revenue": 0, "ratio": None}
    ]


def test_ne_drops_nulls_and_group_by_keeps_them() -> None:
    rows: list[dict[str, Any]] = [
        {"quarter": "Q1", "revenue": 1},
        {"quarter": "Q2", "revenue": None},
        {"quarter": "Q3", "revenue": 2},
    ]
    filtered = _bind(
        {
            "filter": {
                "kind": "ne",
                "args": [
                    {"kind": "col", "name": "revenue"},
                    {"kind": "lit", "value": 1},
                ],
            }
        },
        rows,
    )
    assert filtered.input["data"]["values"] == [{"quarter": "Q3", "revenue": 2}]

    grouped = _bind(
        {
            "group_by": ["revenue"],
            "aggregate": [{"name": "n", "op": "count"}],
            "sort": [{"field": "revenue", "dir": "asc", "nulls": "last"}],
        },
        rows,
        encodings={"x": {"field": "revenue"}, "y": {"field": "n"}},
    )
    values = grouped.input["data"]["values"]
    assert {"revenue": None, "n": 1} in values
    assert {"revenue": 1, "n": 1} in values
    assert {"revenue": 2, "n": 1} in values


def test_every_expr_kind_compiles() -> None:
    rows = [
        {
            "quarter": "Q1",
            "revenue": 100,
            "cost": 40,
            "flag": True,
            "note": "alpha",
        },
        {
            "quarter": "Q2",
            "revenue": 200,
            "cost": 80,
            "flag": False,
            "note": "beta",
        },
    ]
    envelope = _bind(
        {
            "filter": {
                "kind": "and",
                "args": [
                    {
                        "kind": "or",
                        "args": [
                            {
                                "kind": "eq",
                                "args": [
                                    {"kind": "col", "name": "quarter"},
                                    {"kind": "lit", "value": "Q1"},
                                ],
                            },
                            {
                                "kind": "eq",
                                "args": [
                                    {"kind": "col", "name": "quarter"},
                                    {"kind": "lit", "value": "Q2"},
                                ],
                            },
                        ],
                    },
                    {
                        "kind": "not",
                        "args": [
                            {
                                "kind": "is_null",
                                "args": [{"kind": "col", "name": "revenue"}],
                            }
                        ],
                    },
                    {
                        "kind": "is_not_null",
                        "args": [{"kind": "col", "name": "cost"}],
                    },
                    {
                        "kind": "gte",
                        "args": [
                            {"kind": "col", "name": "revenue"},
                            {"kind": "lit", "value": 100},
                        ],
                    },
                    {
                        "kind": "lte",
                        "args": [
                            {"kind": "col", "name": "revenue"},
                            {"kind": "lit", "value": 200},
                        ],
                    },
                    {
                        "kind": "lt",
                        "args": [
                            {"kind": "col", "name": "cost"},
                            {"kind": "lit", "value": 100},
                        ],
                    },
                    {
                        "kind": "between",
                        "args": [
                            {"kind": "col", "name": "revenue"},
                            {"kind": "lit", "value": 50},
                            {"kind": "lit", "value": 250},
                        ],
                    },
                    {
                        "kind": "in",
                        "args": [
                            {"kind": "col", "name": "quarter"},
                            {"kind": "lit", "value": "Q1"},
                            {"kind": "lit", "value": "Q2"},
                        ],
                    },
                    {
                        "kind": "contains",
                        "args": [
                            {"kind": "col", "name": "note"},
                            {"kind": "lit", "value": "a"},
                        ],
                    },
                    {
                        "kind": "starts_with",
                        "args": [
                            {"kind": "col", "name": "note"},
                            {"kind": "lit", "value": "a"},
                        ],
                    },
                    {
                        "kind": "ends_with",
                        "args": [
                            {"kind": "col", "name": "note"},
                            {"kind": "lit", "value": "a"},
                        ],
                    },
                ],
            },
            "derive": [
                {
                    "name": "margin",
                    "expr": {
                        "kind": "sub",
                        "args": [
                            {"kind": "col", "name": "revenue"},
                            {"kind": "col", "name": "cost"},
                        ],
                    },
                },
                {
                    "name": "twice",
                    "expr": {
                        "kind": "mul",
                        "args": [
                            {"kind": "col", "name": "revenue"},
                            {"kind": "lit", "value": 2},
                        ],
                    },
                },
                {
                    "name": "neg_cost",
                    "expr": {
                        "kind": "neg",
                        "args": [{"kind": "col", "name": "cost"}],
                    },
                },
                {
                    "name": "note_or",
                    "expr": {
                        "kind": "coalesce",
                        "args": [
                            {"kind": "col", "name": "note"},
                            {"kind": "lit", "value": "missing"},
                        ],
                    },
                },
                {
                    "name": "tier",
                    "expr": {
                        "kind": "case",
                        "whens": [
                            {
                                "when": {
                                    "kind": "gt",
                                    "args": [
                                        {"kind": "col", "name": "revenue"},
                                        {"kind": "lit", "value": 150},
                                    ],
                                },
                                "then": {"kind": "lit", "value": "high"},
                            }
                        ],
                        "else": {"kind": "lit", "value": "low"},
                    },
                },
            ],
        },
        rows,
    )
    values = envelope.input["data"]["values"]
    assert len(values) == 1
    assert values[0]["quarter"] == "Q1"
    assert values[0]["margin"] == 60
    assert values[0]["twice"] == 200
    assert values[0]["neg_cost"] == -40
    assert values[0]["note_or"] == "alpha"
    assert values[0]["tier"] == "low"


def test_date_literal_must_be_iso8601() -> None:
    rows = pa.table(
        {
            "ordered_at": pa.array([date(2020, 1, 15)], type=pa.date32()),
            "revenue": [10],
        }
    )
    with pytest.raises(SpecShapeError, match="transform.filter") as caught:
        _bind(
            {
                "filter": {
                    "kind": "gt",
                    "args": [
                        {"kind": "col", "name": "ordered_at"},
                        {"kind": "lit", "value": "01/05/2020"},
                    ],
                }
            },
            rows,
            encodings={"x": {"field": "ordered_at"}, "y": {"field": "revenue"}},
        )
    assert "01/05/2020" in str(caught.value)


def test_quoted_identifier_cannot_bind_via_escaping() -> None:
    rows = [{"evil": "hit", "other": "safe", "revenue": 1, "quarter": "Q1"}]
    with pytest.raises(SpecShapeError, match="unknown column"):
        _bind(
            {
                "filter": {
                    "kind": "eq",
                    "args": [
                        {"kind": "col", "name": 'ev"il'},
                        {"kind": "lit", "value": "hit"},
                    ],
                }
            },
            rows,
        )


def test_duplicate_output_name_is_a_spec_shape_error() -> None:
    with pytest.raises(SpecShapeError, match="colliding"):
        _bind(
            {
                "derive": [
                    {
                        "name": "revenue",
                        "expr": {
                            "kind": "add",
                            "args": [
                                {"kind": "col", "name": "revenue"},
                                {"kind": "lit", "value": 1},
                            ],
                        },
                    }
                ]
            }
        )


def test_numeric_bin_emits_the_lower_edge() -> None:
    envelope = _bind(
        {"bin": [{"name": "bucket", "field": "revenue", "width": 75, "origin": 0}]},
        [{"quarter": "Q1", "revenue": 100}, {"quarter": "Q2", "revenue": 200}],
        encodings={"x": {"field": "bucket"}, "y": {"field": "revenue"}},
    )
    assert [row["bucket"] for row in envelope.input["data"]["values"]] == [75, 150]


def test_window_slot_is_a_spec_shape_error() -> None:
    with pytest.raises(SpecShapeError, match="unrecognised"):
        _bind({"window": []})
