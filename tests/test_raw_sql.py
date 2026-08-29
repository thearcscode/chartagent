from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, get_args

import duckdb
import pyarrow as pa
import pytest

from chartagent import bind
from chartagent.bind import DataSource
from chartagent.envelope import Envelope
from chartagent.errors import (
    RawSqlReason,
    RawSqlRejectedError,
    SpecShapeError,
    TransformError,
)
from chartagent.transform.engine import open_connection, open_locked_connection

_FIXTURES = Path(__file__).with_name("data")

_ROWS = [
    {"quarter": "Q1", "revenue": 100},
    {"quarter": "Q2", "revenue": 200},
]


def _bind(
    transform: Mapping[str, object],
    rows: DataSource = _ROWS,
    *,
    encodings: dict[str, Any] | None = None,
    memory_limit: str | None = None,
) -> Envelope:
    frame = {
        "chart_spec": {
            "chartType": "Bar Chart",
            "encodings": encodings
            or {"x": {"field": "quarter"}, "y": {"field": "revenue"}},
        },
        "x_chartagent": {"transform": transform},
    }
    return bind(frame, rows, backend="echarts", memory_limit=memory_limit)


def test_raw_sql_select_from_source_binds() -> None:
    envelope = _bind({"raw_sql": "SELECT quarter, revenue FROM source"})
    assert envelope.input["data"]["values"] == _ROWS
    assert any(item.code == "raw_sql_used" for item in envelope.warnings)


def test_bind_applies_memory_limit_on_a_raw_sql_path() -> None:
    envelope = _bind(
        {"raw_sql": "SELECT quarter, revenue FROM source"},
        memory_limit="128MB",
    )
    assert envelope.input["data"]["values"] == _ROWS


def test_raw_sql_on_a_csv_path_binds() -> None:
    envelope = _bind(
        {"raw_sql": "SELECT quarter, revenue FROM source"},
        _FIXTURES / "sales.csv",
    )
    assert envelope.input["data"]["values"] == _ROWS
    assert any(item.code == "raw_sql_used" for item in envelope.warnings)


def test_raw_sql_on_an_arrow_table_binds() -> None:
    table = pa.table({"quarter": ["Q1", "Q2"], "revenue": [100, 200]})
    envelope = _bind({"raw_sql": "SELECT quarter, revenue FROM source"}, table)
    assert envelope.input["data"]["values"] == _ROWS


def test_menu_slot_with_raw_sql_is_spec_shape_error_before_sql_is_examined() -> None:
    with pytest.raises(SpecShapeError, match="cannot mix"):
        _bind(
            {
                "raw_sql": "INSERT INTO t VALUES (1)",
                "filter": {
                    "kind": "gt",
                    "args": [
                        {"kind": "col", "name": "revenue"},
                        {"kind": "lit", "value": 0},
                    ],
                },
            }
        )


def test_cte_wrapped_insert_is_not_read_only() -> None:
    with pytest.raises(RawSqlRejectedError) as caught:
        _bind({"raw_sql": ("WITH x AS (SELECT 1) INSERT INTO t SELECT * FROM x")})
    assert isinstance(caught.value, TransformError)
    assert caught.value.reason == "not_read_only"


def test_multi_statement_is_rejected() -> None:
    with pytest.raises(RawSqlRejectedError) as caught:
        _bind({"raw_sql": "SELECT 1; SELECT 2"})
    assert caught.value.reason == "multi_statement"


def test_empty_raw_sql_is_rejected() -> None:
    with pytest.raises(RawSqlRejectedError) as caught:
        _bind({"raw_sql": ""})
    assert caught.value.reason == "empty"


def test_unparseable_raw_sql_is_rejected() -> None:
    with pytest.raises(RawSqlRejectedError) as caught:
        _bind({"raw_sql": "NOT SQL AT ALL {{"})
    assert caught.value.reason == "unparseable"


def test_bare_file_path_is_a_foreign_relation() -> None:
    with pytest.raises(RawSqlRejectedError) as caught:
        _bind({"raw_sql": "SELECT * FROM '/etc/passwd'"})
    assert caught.value.reason == "foreign_relation"


def test_read_csv_in_a_subquery_is_a_foreign_relation() -> None:
    with pytest.raises(RawSqlRejectedError) as caught:
        _bind({"raw_sql": ("SELECT (SELECT count(*) FROM read_csv('/etc/passwd'))")})
    assert caught.value.reason == "foreign_relation"


def test_cte_name_does_not_allow_a_qualified_catalog_table() -> None:
    with pytest.raises(RawSqlRejectedError) as caught:
        _bind(
            {
                "raw_sql": (
                    "WITH tables AS (SELECT 1 AS quarter, 1 AS revenue) "
                    "SELECT * FROM information_schema.tables"
                )
            }
        )
    assert caught.value.reason == "foreign_relation"


def test_locked_connection_refuses_read_csv() -> None:
    connection = open_locked_connection()
    try:
        with pytest.raises(duckdb.Error, match="file system"):
            connection.execute("SELECT * FROM read_csv('/etc/passwd')")
    finally:
        connection.close()


def test_locked_connection_refuses_copy_to() -> None:
    connection = open_locked_connection()
    try:
        with pytest.raises(duckdb.Error, match="file system"):
            connection.execute("COPY (SELECT 1) TO 'x.csv'")
    finally:
        connection.close()


def test_locked_connection_refuses_attach() -> None:
    connection = open_locked_connection()
    try:
        with pytest.raises(duckdb.Error, match="file system"):
            connection.execute("ATTACH 'x.db'")
    finally:
        connection.close()


def test_locked_connection_refuses_unlocking() -> None:
    connection = open_locked_connection()
    try:
        with pytest.raises(duckdb.Error, match="locked"):
            connection.execute("SET enable_external_access = true")
    finally:
        connection.close()


def test_memory_limit_is_set_on_both_connections() -> None:
    ordinary = open_connection(memory_limit="128MB")
    locked = open_locked_connection(memory_limit="128MB")
    other = open_connection(memory_limit="64MB")
    try:
        ordinary_limit = ordinary.execute(
            "SELECT current_setting('memory_limit')"
        ).fetchone()
        locked_limit = locked.execute(
            "SELECT current_setting('memory_limit')"
        ).fetchone()
        other_limit = other.execute("SELECT current_setting('memory_limit')").fetchone()
        assert ordinary_limit == locked_limit
        assert ordinary_limit != other_limit
    finally:
        ordinary.close()
        locked.close()
        other.close()


def test_non_file_source_reason_is_unreachable_at_p0() -> None:
    """Flavour 2 does not exist until P1, so this reason cannot be raised.

    ADR-0008 reads PRD §8's "file-like only" as "no foreign dialect". Arrow
    and list[dict] may use raw_sql. ``non_file_source`` stays in the union
    so a P1 widening is not a break. A raise-test cannot fail yet.
    """
    assert "non_file_source" in get_args(RawSqlReason)
