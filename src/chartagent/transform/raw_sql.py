"""``raw_sql`` escape hatch — three independent locks (ADR-0008 D7)."""

from __future__ import annotations

import json
from typing import Any

import duckdb
import pyarrow as pa

from chartagent.errors import RawSqlRejectedError, SpecShapeError, TransformError
from chartagent.transform.engine import collect, open_locked_connection

_TABLE_FUNCTIONS: frozenset[str] | None = None


def run_raw_sql(
    connection: duckdb.DuckDBPyConnection,
    sql: object,
    *,
    timeout: float | None,
    memory_limit: str | None = None,
) -> tuple[pa.Table, dict[str, str]]:
    """Validate ``sql``, materialise ``source`` on A, run the SELECT on B."""
    if not isinstance(sql, str):
        raise SpecShapeError("transform.raw_sql must be a string")
    validate_raw_sql(connection, sql)
    source = collect(connection, connection.table("source"), timeout)
    locked = open_locked_connection(memory_limit=memory_limit)
    try:
        locked.register("source", source)
        relation = locked.sql(sql)
        output_types = dict(
            zip(relation.columns, (str(dtype) for dtype in relation.types))
        )
        table = collect(locked, relation, timeout)
        return table, output_types
    except (RawSqlRejectedError, SpecShapeError, TransformError):
        raise
    except duckdb.Error as exc:
        raise TransformError("transform failed", path="transform.raw_sql") from exc
    finally:
        locked.close()


def validate_raw_sql(connection: duckdb.DuckDBPyConnection, sql: str) -> None:
    """Lock 1 then Lock 2. Neither executes the query."""
    _lock_statements(connection, sql)
    _lock_relations(connection, sql)


def _lock_statements(connection: duckdb.DuckDBPyConnection, sql: str) -> None:
    try:
        statements = connection.extract_statements(sql)
    except duckdb.Error as exc:
        raise RawSqlRejectedError(
            "raw_sql could not be parsed", reason="unparseable"
        ) from exc
    if len(statements) == 0:
        raise RawSqlRejectedError("raw_sql is empty", reason="empty")
    if len(statements) > 1:
        raise RawSqlRejectedError(
            "raw_sql contains multiple statements", reason="multi_statement"
        )
    if statements[0].type.name != "SELECT":
        raise RawSqlRejectedError(
            "raw_sql is not a read-only SELECT", reason="not_read_only"
        )


def _lock_relations(connection: duckdb.DuckDBPyConnection, sql: str) -> None:
    try:
        row = connection.execute("SELECT json_serialize_sql(?)", [sql]).fetchone()
    except duckdb.Error as exc:
        raise RawSqlRejectedError(
            "raw_sql could not be parsed", reason="unparseable"
        ) from exc
    if row is None:
        raise RawSqlRejectedError(
            "raw_sql could not be parsed", reason="unparseable"
        )
    tree = json.loads(row[0])
    if not isinstance(tree, dict) or tree.get("error"):
        raise RawSqlRejectedError(
            "raw_sql could not be parsed", reason="unparseable"
        )
    allowed_tf = _table_functions(connection)
    if _has_foreign_relation(tree, allowed_ctes=set(), allowed_tf=allowed_tf):
        raise RawSqlRejectedError(
            "raw_sql names a relation other than source", reason="foreign_relation"
        )


def _table_functions(connection: duckdb.DuckDBPyConnection) -> frozenset[str]:
    global _TABLE_FUNCTIONS
    if _TABLE_FUNCTIONS is None:
        rows = connection.execute(
            "SELECT function_name FROM duckdb_functions() "
            "WHERE function_type = 'table'"
        ).fetchall()
        _TABLE_FUNCTIONS = frozenset(str(row[0]).lower() for row in rows)
    return _TABLE_FUNCTIONS


def _has_foreign_relation(
    node: Any, *, allowed_ctes: set[str], allowed_tf: frozenset[str]
) -> bool:
    if isinstance(node, list):
        return any(
            _has_foreign_relation(
                item, allowed_ctes=allowed_ctes, allowed_tf=allowed_tf
            )
            for item in node
        )
    if not isinstance(node, dict):
        return False

    local = set(allowed_ctes)
    mapping = node.get("cte_map")
    if isinstance(mapping, dict):
        for item in mapping.get("map") or []:
            if isinstance(item, dict):
                key = item.get("key")
                if isinstance(key, str):
                    local.add(key)

    if node.get("type") == "BASE_TABLE" and _base_table_is_foreign(node, local):
        return True
    if node.get("type") == "TABLE_FUNCTION":
        return True
    fname = node.get("function_name")
    if isinstance(fname, str) and fname.lower() in allowed_tf:
        return True
    return any(
        _has_foreign_relation(value, allowed_ctes=local, allowed_tf=allowed_tf)
        for value in node.values()
    )


def _base_table_is_foreign(node: dict[str, Any], allowed_ctes: set[str]) -> bool:
    name = node.get("table_name")
    if not isinstance(name, str) or not name:
        return False
    schema = node.get("schema_name") or ""
    catalog = node.get("catalog_name") or ""
    if schema or catalog:
        return True
    return name != "source" and name not in allowed_ctes
