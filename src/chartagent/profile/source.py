"""``profile_source`` — one artifact describing the source (ADR-0011)."""

from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Literal

import duckdb

from chartagent.bind import DataSource
from chartagent.errors import DataSourceError
from chartagent.frame.input import SourceBucket
from chartagent.profile.ladder import apply_ladder
from chartagent.profile.models import (
    SAMPLE_ROWS,
    SATURATION_CAP,
    TOP_K,
    BooleanColumn,
    Column,
    NumberColumn,
    NumberStats,
    OtherColumn,
    Profile,
    StringColumn,
    StringStats,
    TemporalColumn,
    TemporalStats,
    TopValue,
)
from chartagent.transform.engine import (
    describe_source,
    open_connection,
    register_source,
)
from chartagent.transform.schema import bucket_for

_TEMPORAL: frozenset[str] = frozenset({"date", "timestamp", "timestamptz"})
_PERCENTILES = (0.01, 0.25, 0.5, 0.75, 0.99)


def profile_source(data: DataSource) -> Profile:
    """Describe a CSV, Parquet, Arrow table, or ``list[dict]`` source."""
    connection = open_connection()
    try:
        register_source(connection, data)
        return _profile_relation(connection)
    except duckdb.Error as exc:
        raise DataSourceError("source cannot be read") from exc
    finally:
        connection.close()


def _profile_relation(connection: duckdb.DuckDBPyConnection) -> Profile:
    reported_types, source_schema = describe_source(connection)
    count_row = connection.execute("SELECT count(*) FROM source").fetchone()
    row_count = int(count_row[0]) if count_row is not None else 0

    described = [
        (name, reported, source_schema[name])
        for name, reported in reported_types.items()
    ]
    scanned = [item for item in described if item[2] != "other"]
    columns: list[Column] = []
    for name, reported, bucket in described:
        if bucket == "other":
            columns.append(OtherColumn(name=name, reported_type=reported))
            continue
        columns.append(_profile_column(connection, name, reported, bucket, row_count))
    sample_rows = _sample_rows(connection, scanned, row_count)
    columns = _attach_iso8601(columns, sample_rows)
    return apply_ladder(
        Profile(row_count=row_count, columns=columns, sample_rows=sample_rows)
    )


def _profile_column(
    connection: duckdb.DuckDBPyConnection,
    name: str,
    reported: str,
    bucket: SourceBucket,
    row_count: int,
) -> NumberColumn | TemporalColumn | StringColumn | BooleanColumn:
    null_rate = _null_rate(connection, name, row_count)
    distinct, saturated = _distinct_cap(connection, name)
    empty = row_count == 0 or null_rate == 1.0
    if bucket == "number":
        return NumberColumn(
            name=name,
            reported_type=reported,
            null_rate=null_rate,
            distinct=distinct,
            saturated=saturated,
            stats=None if empty else _number_stats(connection, name),
        )
    if bucket in _TEMPORAL:
        temporal: Literal["date", "timestamp", "timestamptz"]
        if bucket == "date":
            temporal = "date"
        elif bucket == "timestamp":
            temporal = "timestamp"
        else:
            temporal = "timestamptz"
        return TemporalColumn(
            name=name,
            reported_type=reported,
            bucket=temporal,
            null_rate=null_rate,
            distinct=distinct,
            saturated=saturated,
            stats=None if empty else _temporal_stats(connection, name, temporal),
        )
    if bucket == "boolean":
        return BooleanColumn(
            name=name,
            reported_type=reported,
            null_rate=null_rate,
            distinct=distinct,
            saturated=saturated,
            top=None if row_count == 0 else _boolean_top(connection, name),
        )
    top = None if empty else _string_top(connection, name)
    return StringColumn(
        name=name,
        reported_type=reported,
        null_rate=null_rate,
        distinct=distinct,
        saturated=saturated,
        top=top,
        stats=None if empty else _string_stats(connection, name, reported, top or []),
    )


def _sample_rows(
    connection: duckdb.DuckDBPyConnection,
    scanned: list[tuple[str, str, SourceBucket]],
    row_count: int,
) -> list[dict[str, Any]]:
    if row_count == 0 or not scanned:
        return []
    names = [name for name, _reported, _bucket in scanned]
    reported = {name: rtype for name, rtype, _bucket in scanned}
    projection = ", ".join(_quote(name) for name in names)
    table = connection.sql(
        f"SELECT {projection} FROM source ORDER BY random() LIMIT {SAMPLE_ROWS}"
    ).to_arrow_table()
    return [_plain_row(raw, reported) for raw in table.to_pylist()]


def _null_rate(
    connection: duckdb.DuckDBPyConnection, name: str, row_count: int
) -> float:
    if row_count == 0:
        return 0.0
    col = _quote(name)
    row = connection.execute(
        f"SELECT count(*) FILTER (WHERE {col} IS NULL)::DOUBLE / count(*) FROM source"
    ).fetchone()
    if row is None or row[0] is None:
        return 0.0
    return float(row[0])


def _distinct_cap(connection: duckdb.DuckDBPyConnection, name: str) -> tuple[int, bool]:
    col = _quote(name)
    row = connection.execute(
        f"SELECT count(*) FROM ("
        f"SELECT DISTINCT {col} FROM source WHERE {col} IS NOT NULL "
        f"LIMIT {SATURATION_CAP})"
    ).fetchone()
    count = int(row[0]) if row is not None else 0
    saturated = count >= SATURATION_CAP
    return (SATURATION_CAP if saturated else count), saturated


def _number_stats(
    connection: duckdb.DuckDBPyConnection, name: str
) -> NumberStats | None:
    extrema = _footer_extrema(connection, name, as_epoch=False)
    quantiles = _approx_quantiles(connection, name, as_epoch=False)
    if extrema is None or quantiles is None:
        return None
    lo, hi = extrema
    return NumberStats(
        min=_as_float(lo),
        max=_as_float(hi),
        p01=_as_float(quantiles[0]),
        p25=_as_float(quantiles[1]),
        p50=_as_float(quantiles[2]),
        p75=_as_float(quantiles[3]),
        p99=_as_float(quantiles[4]),
    )


def _temporal_stats(
    connection: duckdb.DuckDBPyConnection, name: str, bucket: str
) -> TemporalStats | None:
    extrema = _footer_extrema(connection, name, as_epoch=True)
    quantiles = _approx_quantiles(connection, name, as_epoch=True)
    if extrema is None or quantiles is None:
        return None
    lo, hi = extrema
    return TemporalStats(
        min=_from_epoch_us(lo, bucket),
        max=_from_epoch_us(hi, bucket),
        p01=_from_epoch_us(quantiles[0], bucket),
        p25=_from_epoch_us(quantiles[1], bucket),
        p50=_from_epoch_us(quantiles[2], bucket),
        p75=_from_epoch_us(quantiles[3], bucket),
        p99=_from_epoch_us(quantiles[4], bucket),
    )


def _footer_extrema(
    connection: duckdb.DuckDBPyConnection, name: str, *, as_epoch: bool
) -> tuple[object, object] | None:
    col = _quote(name)
    if as_epoch:
        expr = f"epoch_us(min({col})), epoch_us(max({col}))"
    else:
        expr = f"min({col}), max({col})"
    row = connection.execute(f"SELECT {expr} FROM source").fetchone()
    if row is None or row[0] is None or row[1] is None:
        return None
    return row[0], row[1]


def _approx_quantiles(
    connection: duckdb.DuckDBPyConnection, name: str, *, as_epoch: bool
) -> tuple[object, ...] | None:
    col = _quote(name)
    if as_epoch:
        parts = [f"epoch_us(approx_quantile({col}, {p}))" for p in _PERCENTILES]
    else:
        parts = [f"approx_quantile({col}, {p})" for p in _PERCENTILES]
    row = connection.execute(f"SELECT {', '.join(parts)} FROM source").fetchone()
    if row is None or any(value is None for value in row):
        return None
    return row


def _from_epoch_us(value: object, bucket: str) -> str:
    instant = datetime.fromtimestamp(_as_float(value) / 1_000_000, tz=UTC)
    if bucket == "date":
        return instant.date().isoformat()
    if bucket == "timestamp":
        return instant.replace(tzinfo=None).isoformat()
    return instant.replace(tzinfo=None).isoformat() + "Z"


def _string_top(connection: duckdb.DuckDBPyConnection, name: str) -> list[TopValue]:
    col = _quote(name)
    rows = connection.execute(
        f"SELECT {col}, count(*) FROM source WHERE {col} IS NOT NULL "
        f"GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT {TOP_K}"
    ).fetchall()
    return [
        TopValue(value=_plain_copied(value), count=int(count)) for value, count in rows
    ]


def _boolean_top(connection: duckdb.DuckDBPyConnection, name: str) -> list[TopValue]:
    col = _quote(name)
    rows = connection.execute(
        f"SELECT {col}, count(*) FROM source GROUP BY 1 ORDER BY 2 DESC"
    ).fetchall()
    return [
        TopValue(value=_plain_copied(value), count=int(count)) for value, count in rows
    ]


def _string_stats(
    connection: duckdb.DuckDBPyConnection,
    name: str,
    reported: str,
    top: list[TopValue],
) -> StringStats:
    col = _quote(name)
    extrema = connection.execute(
        f"SELECT min({col}), max({col}) FROM source"
    ).fetchone()
    lo = "" if extrema is None or extrema[0] is None else str(extrema[0])
    hi = "" if extrema is None or extrema[1] is None else str(extrema[1])
    counted = connection.execute(
        f"SELECT count(*) FROM source WHERE {col} IS NOT NULL"
    ).fetchone()
    non_null = int(counted[0]) if counted is not None else 0
    coverage = (sum(item.count for item in top) / non_null) if non_null else 0.0
    return StringStats(
        min=lo,
        max=hi,
        top_k_coverage=coverage,
        iso8601_parse_rate=None if not _is_varchar(reported) else 0.0,
    )


def _attach_iso8601(
    columns: list[Column], sample_rows: list[dict[str, Any]]
) -> list[Column]:
    attached: list[Column] = []
    for column in columns:
        if not isinstance(column, StringColumn) or column.stats is None:
            attached.append(column)
            continue
        if not _is_varchar(column.reported_type):
            attached.append(column)
            continue
        sampled = [
            row[column.name] for row in sample_rows if row.get(column.name) is not None
        ]
        stats = column.stats.model_copy(
            update={"iso8601_parse_rate": _iso8601_rate(sampled)}
        )
        attached.append(column.model_copy(update={"stats": stats}))
    return attached


def _iso8601_rate(values: list[object]) -> float:
    if not values:
        return 0.0
    parsed = sum(1 for value in values if _parses_iso8601(value))
    return parsed / len(values)


def _parses_iso8601(value: object) -> bool:
    if not isinstance(value, str):
        return False
    text = value.replace("Z", "+00:00")
    try:
        datetime.fromisoformat(text)
        return True
    except ValueError:
        try:
            date.fromisoformat(value)
            return True
        except ValueError:
            return False


def _is_varchar(reported: str) -> bool:
    if reported.endswith("]"):
        return False
    return reported.split("(", 1)[0].strip().upper() == "VARCHAR"


def _as_float(value: object) -> float:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, bool):
        return float(int(value))
    if isinstance(value, (int, float)):
        return float(value)
    return float(value)  # type: ignore[arg-type]


def _format_temporal(value: object, bucket: str) -> str:
    if value is None:
        return ""
    if bucket == "date":
        if isinstance(value, datetime):
            value = value.date()
        if isinstance(value, date):
            return date(value.year, value.month, value.day).isoformat()
        return str(value)
    if isinstance(value, datetime):
        if bucket == "timestamp":
            return value.replace(tzinfo=None).isoformat()
        if value.tzinfo is None:
            utc = value
        else:
            utc = value.astimezone(UTC).replace(tzinfo=None)
        return utc.isoformat() + "Z"
    if isinstance(value, date):
        return _format_temporal(datetime(value.year, value.month, value.day), bucket)
    return str(value)


def _plain_row(row: Mapping[str, Any], reported: Mapping[str, str]) -> dict[str, Any]:
    return {key: _sample_value(value, reported[key]) for key, value in row.items()}


def _sample_value(value: object, reported: str) -> object:
    if value is None:
        return None
    bucket = bucket_for(reported)
    if bucket == "date" and isinstance(value, date):
        return date(value.year, value.month, value.day).isoformat()
    if bucket == "timestamp" and isinstance(value, datetime):
        return value.replace(tzinfo=None).isoformat()
    if bucket == "timestamptz" and isinstance(value, datetime):
        utc = (
            value.replace(tzinfo=None)
            if value.tzinfo is None
            else value.astimezone(UTC).replace(tzinfo=None)
        )
        return utc.isoformat() + "Z"
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return int(value)
        return float(value)
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return _format_temporal(value, bucket if bucket in _TEMPORAL else "timestamp")
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _plain_copied(value: object) -> object:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return int(value)
        return float(value)
    return value


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'
