"""In-process DuckDB execution for ``bind`` — connection, source, collect."""

from __future__ import annotations

import os
import threading
from collections.abc import Mapping
from os import PathLike

import duckdb
import pyarrow as pa

from chartagent.errors import DataSourceError, TransformError
from chartagent.frame.input import SourceBucket
from chartagent.transform.schema import bucket_for

_REMOTE_PREFIXES = ("s3://", "https://")
_PARQUET_SUFFIXES = (".parquet", ".pq")


def open_connection() -> duckdb.DuckDBPyConnection:
    """Open an in-memory connection with the reproducibility pins."""
    connection = duckdb.connect(":memory:")
    _load_extension(connection, "icu")
    connection.execute("SET TimeZone = 'UTC'")
    connection.execute("SET default_null_order = 'NULLS_LAST'")
    connection.execute("SET default_order = 'ASCENDING'")
    # DuckDB already sets memory_limit (host default). OOM is TransformError.
    return connection


def register_source(connection: duckdb.DuckDBPyConnection, data: object) -> None:
    """Attach ``data`` as the reserved relation ``source``."""
    if isinstance(data, list):
        _register_arrow(connection, _table_from_rows(data))
        return
    table = _as_arrow_table(data)
    if table is not None:
        _register_arrow(connection, table)
        return
    path = _as_path(data)
    if path is None:
        raise DataSourceError("unsupported data source")
    _register_path(connection, path)


def describe_source(
    connection: duckdb.DuckDBPyConnection,
) -> tuple[dict[str, str], dict[str, SourceBucket]]:
    """Return DuckDB reported types and their coarse buckets for ``source``."""
    reported: dict[str, str] = {}
    schema: dict[str, SourceBucket] = {}
    for row in connection.execute("DESCRIBE source").fetchall():
        name = str(row[0])
        duckdb_type = str(row[1])
        reported[name] = duckdb_type
        schema[name] = bucket_for(duckdb_type)
    return reported, schema


def pass_through(
    connection: duckdb.DuckDBPyConnection,
    *,
    timeout: float | None,
) -> pa.Table:
    """Return every source column. Absent/empty transform is this path.

    Pass-through has no ``limit``, so the connection pins alone make this
    result stable. The menu path appends output-column tiebreaks when
    ``limit`` is present (ADR-0008 D11).
    """
    relation = connection.table("source")
    return collect(connection, relation, timeout)


def collect(
    connection: duckdb.DuckDBPyConnection,
    relation: duckdb.DuckDBPyRelation,
    timeout: float | None,
) -> pa.Table:
    timer: threading.Timer | None = None
    if timeout is not None:
        timer = threading.Timer(timeout, connection.interrupt)
        timer.start()
    try:
        return relation.to_arrow_table()
    except duckdb.InterruptException as exc:
        raise TransformError("transform timed out") from exc
    except duckdb.OutOfMemoryException as exc:
        raise TransformError("transform exceeded the memory limit") from exc
    except duckdb.Error as exc:
        raise TransformError("transform failed", path="transform") from exc
    finally:
        if timer is not None:
            timer.cancel()


def _register_arrow(connection: duckdb.DuckDBPyConnection, table: pa.Table) -> None:
    try:
        connection.register("source", table)
    except duckdb.Error as exc:
        raise DataSourceError("source cannot be read") from exc


def _register_path(connection: duckdb.DuckDBPyConnection, path: str) -> None:
    if _is_remote(path):
        _load_extension(connection, "httpfs")
    elif not os.path.isfile(path):
        raise DataSourceError(f"source is not readable: {path}")
    try:
        if path.lower().endswith(_PARQUET_SUFFIXES):
            relation = connection.read_parquet(path)
        else:
            relation = connection.read_csv(path)
        relation.create_view("source")
    except duckdb.Error as exc:
        raise DataSourceError(f"source is not readable: {path}") from exc


def _table_from_rows(rows: list[object]) -> pa.Table:
    mappings: list[dict[str, object]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise DataSourceError("list sources must be a list of mappings")
        mappings.append({str(key): value for key, value in row.items()})
    try:
        return pa.Table.from_pylist(mappings)
    except (TypeError, ValueError) as exc:
        raise DataSourceError("source cannot be read") from exc


def _as_arrow_table(data: object) -> pa.Table | None:
    if isinstance(data, pa.Table):
        return data
    if hasattr(data, "__arrow_c_stream__"):
        try:
            reader = pa.RecordBatchReader.from_stream(data)
            return reader.read_all()
        except (pa.ArrowInvalid, pa.ArrowTypeError, TypeError, ValueError) as exc:
            raise DataSourceError("source cannot be read") from exc
    return None


def _as_path(data: object) -> str | None:
    if isinstance(data, (str, PathLike)):
        return os.fspath(data)
    return None


def _is_remote(path: str) -> bool:
    return path.startswith(_REMOTE_PREFIXES)


def _load_extension(connection: duckdb.DuckDBPyConnection, name: str) -> None:
    try:
        connection.execute(f"LOAD {name}")
    except duckdb.Error:
        try:
            connection.execute(f"INSTALL {name}")
            connection.execute(f"LOAD {name}")
        except duckdb.Error as exc:
            raise TransformError(f"failed to load DuckDB extension {name}") from exc
