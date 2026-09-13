from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Any

import pyarrow as pa
import pytest

from chartagent import bind
from chartagent.bind import DataSource
from chartagent.envelope import Envelope
from chartagent.errors import SchemaDriftError, SpecShapeError

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
        encodings={"x": {"field": "quarter"}, "y": {"field": "quarter"}},
    )
    values = envelope.input["data"]["values"]
    assert sorted(row["quarter"] for row in values) == ["Q1", "Q2"]
    assert all(set(row) == {"quarter"} for row in values)


def test_aggregate_without_group_by_is_one_row() -> None:
    envelope = _bind(
        {"aggregate": [{"name": "revenue_sum", "op": "sum", "field": "revenue"}]},
        encodings={"x": {"field": "revenue_sum"}, "y": {"field": "revenue_sum"}},
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
    with pytest.raises(SchemaDriftError) as caught:
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
    assert caught.value.stage == "source"
    assert caught.value.drifted[0].kind == "dropped"
    assert caught.value.drifted[0].name == 'ev"il'


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


# --- #143: closed keys inside slot items and on Expr nodes, at bind too --
# Frozen envelopes carried sort items shaped `{field, order}`; the compiler
# read only `dir`/`nulls` and ignored `order`, drawing rows ascending no
# matter what `order` said (settled in #139, ADR-0023 D4;
# corpus/report-notes.md). A stored frame carrying that shape must now
# raise on `bind`/`ChartResult.refresh` instead of drawing ascending.
def test_sort_order_key_is_rejected_at_bind_not_silently_ignored() -> None:
    with pytest.raises(SpecShapeError, match=r"unrecognised key\(s\) \('order',\)"):
        _bind(
            {"sort": [{"field": "revenue", "order": "descending"}]},
            [
                {"quarter": "Q1", "revenue": 200},
                {"quarter": "Q2", "revenue": 100},
            ],
        )


def test_expr_col_alias_key_is_rejected_at_bind() -> None:
    with pytest.raises(SpecShapeError, match=r"unrecognised key\(s\) \('alias',\)"):
        _bind(
            {
                "filter": {
                    "kind": "eq",
                    "args": [
                        {"kind": "col", "name": "revenue", "alias": "y"},
                        {"kind": "lit", "value": 100},
                    ],
                }
            }
        )


# The rest of the closed-key table (#143), one case per slot item kind and
# per Expr node shape, exercised through the same bind() call the two
# named cases above use.
@pytest.mark.parametrize(
    "transform, unknown",
    [
        pytest.param(
            {"aggregate": [{"name": "n", "op": "sum", "field": "revenue", "extra": 1}]},
            "extra",
            id="aggregate",
        ),
        pytest.param(
            {"bin": [{"name": "b", "field": "revenue", "width": 10, "scale": "log"}]},
            "scale",
            id="bin",
        ),
        pytest.param(
            {"derive": [{"name": "x", "expr": {"kind": "lit", "value": 1}, "as": "y"}]},
            "as",
            id="derive",
        ),
        pytest.param({"limit": {"count": 10, "page": 2}}, "page", id="limit"),
        pytest.param(
            {"filter": {"kind": "lit", "value": True, "label": "n"}},
            "label",
            id="expr-lit",
        ),
        pytest.param(
            {
                "filter": {
                    "kind": "not",
                    "args": [{"kind": "lit", "value": True}],
                    "note": "n",
                }
            },
            "note",
            id="expr-unary",
        ),
        pytest.param(
            {
                "filter": {
                    "kind": "eq",
                    "args": [
                        {"kind": "col", "name": "revenue"},
                        {"kind": "lit", "value": 1},
                    ],
                    "note": "n",
                }
            },
            "note",
            id="expr-binary",
        ),
        pytest.param(
            {
                "filter": {
                    "kind": "and",
                    "args": [
                        {"kind": "lit", "value": True},
                        {"kind": "lit", "value": True},
                    ],
                    "note": "n",
                }
            },
            "note",
            id="expr-nary",
        ),
        pytest.param(
            {
                "filter": {
                    "kind": "between",
                    "args": [
                        {"kind": "col", "name": "revenue"},
                        {"kind": "lit", "value": 0},
                        {"kind": "lit", "value": 1000},
                    ],
                    "note": "n",
                }
            },
            "note",
            id="expr-between",
        ),
        pytest.param(
            {
                "filter": {
                    "kind": "in",
                    "args": [
                        {"kind": "col", "name": "revenue"},
                        {"kind": "lit", "value": 100},
                    ],
                    "note": "n",
                }
            },
            "note",
            id="expr-in",
        ),
        pytest.param(
            {
                "filter": {
                    "kind": "case",
                    "whens": [
                        {
                            "when": {"kind": "lit", "value": True},
                            "then": {"kind": "lit", "value": True},
                        }
                    ],
                    "else": {"kind": "lit", "value": False},
                    "note": "n",
                }
            },
            "note",
            id="expr-case",
        ),
        pytest.param(
            {
                "filter": {
                    "kind": "case",
                    "whens": [
                        {
                            "when": {"kind": "lit", "value": True},
                            "then": {"kind": "lit", "value": True},
                            "label": "hi",
                        }
                    ],
                    "else": {"kind": "lit", "value": False},
                }
            },
            "label",
            id="expr-case-when",
        ),
    ],
)
def test_unrecognised_key_is_rejected_at_bind(
    transform: dict[str, Any], unknown: str
) -> None:
    with pytest.raises(
        SpecShapeError, match=rf"unrecognised key\(s\) \('{unknown}',\)"
    ):
        _bind(transform)
