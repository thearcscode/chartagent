"""``profile_source`` — one artifact describing a small source (ADR-0011)."""

from __future__ import annotations

import math
import random
from collections import Counter
from collections.abc import Mapping
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Literal

import duckdb

from chartagent.bind import DataSource
from chartagent.errors import DataSourceError
from chartagent.frame.input import SourceBucket
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
    stats_by_name = {name: _ColumnStats(bucket) for name, _reported, bucket in scanned}
    sample_rows: list[dict[str, Any]] = []
    if scanned:
        sample_rows = _scan(
            connection,
            scanned=scanned,
            accs=stats_by_name,
            row_count=row_count,
        )

    columns: list[Column] = []
    for name, reported, bucket in described:
        if bucket == "other":
            columns.append(OtherColumn(name=name, reported_type=reported))
            continue
        columns.append(
            _column_from_acc(
                name=name,
                reported=reported,
                bucket=bucket,
                acc=stats_by_name[name],
                row_count=row_count,
                sample_rows=sample_rows,
            )
        )
    return Profile(row_count=row_count, columns=columns, sample_rows=sample_rows)


def _scan(
    connection: duckdb.DuckDBPyConnection,
    *,
    scanned: list[tuple[str, str, SourceBucket]],
    accs: Mapping[str, _ColumnStats],
    row_count: int,
) -> list[dict[str, Any]]:
    if row_count == 0:
        return []
    names = [name for name, _reported, _bucket in scanned]
    reported = {name: rtype for name, rtype, _bucket in scanned}
    projection = ", ".join(_quote(name) for name in names)
    reader = connection.sql(f"SELECT {projection} FROM source").to_arrow_reader(1024)
    reservoir: list[dict[str, Any]] = []
    seen = 0
    for batch in reader:
        for raw in batch.to_pylist():
            record = {name: raw[name] for name in names}
            seen += 1
            if seen <= SAMPLE_ROWS:
                reservoir.append(record)
            else:
                slot = random.randrange(seen)
                if slot < SAMPLE_ROWS:
                    reservoir[slot] = record
            for name, acc in accs.items():
                acc.observe(record[name])
    return [_plain_row(row, reported) for row in reservoir]


def _column_from_acc(
    *,
    name: str,
    reported: str,
    bucket: SourceBucket,
    acc: _ColumnStats,
    row_count: int,
    sample_rows: list[dict[str, Any]],
) -> NumberColumn | TemporalColumn | StringColumn | BooleanColumn:
    null_rate = 0.0 if row_count == 0 else acc.nulls / row_count
    distinct = SATURATION_CAP if acc.saturated else len(acc.distinct)
    empty = row_count == 0 or null_rate == 1.0
    if bucket == "number":
        return NumberColumn(
            name=name,
            reported_type=reported,
            null_rate=null_rate,
            distinct=distinct,
            saturated=acc.saturated,
            stats=None if empty else _number_stats(acc),
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
            saturated=acc.saturated,
            stats=None if empty else _temporal_stats(acc, temporal),
        )
    if bucket == "boolean":
        return BooleanColumn(
            name=name,
            reported_type=reported,
            null_rate=null_rate,
            distinct=distinct,
            saturated=acc.saturated,
            top=None if row_count == 0 else _boolean_top(acc),
        )
    top = None if empty else _string_top(acc)
    return StringColumn(
        name=name,
        reported_type=reported,
        null_rate=null_rate,
        distinct=distinct,
        saturated=acc.saturated,
        top=top,
        stats=(
            None
            if empty
            else _string_stats(
                acc,
                reported=reported,
                top=top or [],
                sample_rows=sample_rows,
                name=name,
            )
        ),
    )


def _number_stats(acc: _ColumnStats) -> NumberStats:
    values = sorted(_as_float(v) for v in acc.values)
    lo, hi = values[0], values[-1]
    qs = [_quantile(values, p) for p in _PERCENTILES]
    return NumberStats(
        min=lo,
        max=hi,
        p01=qs[0],
        p25=qs[1],
        p50=qs[2],
        p75=qs[3],
        p99=qs[4],
    )


def _temporal_stats(acc: _ColumnStats, bucket: str) -> TemporalStats:
    numeric = sorted(_temporal_numeric(v, bucket) for v in acc.values)
    qs = [_from_temporal_numeric(_quantile(numeric, p), bucket) for p in _PERCENTILES]
    return TemporalStats(
        min=_format_temporal(acc.min, bucket),
        max=_format_temporal(acc.max, bucket),
        p01=qs[0],
        p25=qs[1],
        p50=qs[2],
        p75=qs[3],
        p99=qs[4],
    )


def _string_top(acc: _ColumnStats) -> list[TopValue]:
    items = sorted(acc.counts.items(), key=lambda item: (-item[1], _tie_key(item[0])))
    return [
        TopValue(value=_plain_copied(value), count=count)
        for value, count in items[:TOP_K]
    ]


def _boolean_top(acc: _ColumnStats) -> list[TopValue]:
    items = sorted(acc.counts.items(), key=lambda item: -item[1])
    return [TopValue(value=_plain_copied(value), count=count) for value, count in items]


def _string_stats(
    acc: _ColumnStats,
    *,
    reported: str,
    top: list[TopValue],
    sample_rows: list[dict[str, Any]],
    name: str,
) -> StringStats:
    non_null = acc.n
    coverage = (sum(item.count for item in top) / non_null) if non_null else 0.0
    rate: float | None = None
    if _is_varchar(reported):
        sampled = [row[name] for row in sample_rows if row.get(name) is not None]
        rate = _iso8601_rate(sampled)
    return StringStats(
        min=str(acc.min),
        max=str(acc.max),
        top_k_coverage=coverage,
        iso8601_parse_rate=rate,
    )


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


def _quantile(sorted_vals: list[float], p: float) -> float:
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    rank = (len(sorted_vals) - 1) * p
    lo = int(math.floor(rank))
    hi = int(math.ceil(rank))
    if lo == hi:
        return sorted_vals[lo]
    weight = rank - lo
    return sorted_vals[lo] * (1.0 - weight) + sorted_vals[hi] * weight


def _as_float(value: object) -> float:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, bool):
        return float(int(value))
    if isinstance(value, (int, float)):
        return float(value)
    return float(value)  # type: ignore[arg-type]


def _temporal_numeric(value: object, bucket: str) -> float:
    if bucket == "date":
        if isinstance(value, datetime):
            value = value.date()
        if isinstance(value, date):
            return float(value.toordinal())
        return 0.0
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.timestamp()
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=UTC).timestamp()
    return 0.0


def _from_temporal_numeric(value: float, bucket: str) -> str:
    if bucket == "date":
        return date.fromordinal(int(round(value))).isoformat()
    instant = datetime.fromtimestamp(value, tz=UTC)
    if bucket == "timestamp":
        return instant.replace(tzinfo=None).isoformat()
    return instant.replace(tzinfo=None).isoformat() + "Z"


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


def _tie_key(value: object) -> str:
    return "" if value is None else str(value)


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _distinct_key(value: object) -> object:
    if isinstance(value, float) and math.isnan(value):
        return ("nan",)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    try:
        hash(value)
    except TypeError:
        return str(value)
    return value


class _ColumnStats:
    def __init__(self, bucket: SourceBucket) -> None:
        self.bucket = bucket
        self.nulls = 0
        self.n = 0
        self.distinct: set[object] = set()
        self.saturated = False
        self.min: object | None = None
        self.max: object | None = None
        self.values: list[object] = []
        self.counts: Counter[object] = Counter()

    def observe(self, value: object) -> None:
        if value is None:
            self.nulls += 1
            if self.bucket == "boolean":
                self.counts[None] += 1
            return
        self.n += 1
        if not self.saturated:
            self.distinct.add(_distinct_key(value))
            if len(self.distinct) >= SATURATION_CAP:
                self.saturated = True
                self.distinct.clear()
        if self.bucket in {"number", *_TEMPORAL, "string"}:
            if self.min is None or _less(value, self.min):
                self.min = value
            if self.max is None or _less(self.max, value):
                self.max = value
        if self.bucket in {"number", *_TEMPORAL}:
            self.values.append(value)
        if self.bucket in {"string", "boolean"}:
            self.counts[value] += 1


def _less(left: object, right: object) -> bool:
    try:
        return bool(left < right)  # type: ignore[operator]
    except TypeError:
        return str(left) < str(right)
