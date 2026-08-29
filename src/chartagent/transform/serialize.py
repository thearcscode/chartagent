"""Envelope row serialisation — ADR-0008 Decision 9."""

from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pyarrow as pa

from chartagent.envelope import Advisory
from chartagent.transform.schema import bucket_for

_FLOAT_HEADS = frozenset({"FLOAT", "DOUBLE"})


def serialize_rows(
    table: pa.Table,
    duckdb_types: Mapping[str, str],
) -> tuple[list[dict[str, Any]], tuple[Advisory, ...]]:
    """Apply the three wire rules, keyed on DuckDB reported types."""
    columns = list(table.column_names)
    date_columns = [name for name in columns if _is_temporal(duckdb_types[name])]
    non_finite = 0
    rows: list[dict[str, Any]] = []
    for raw in table.to_pylist():
        row: dict[str, Any] = {}
        for name in columns:
            value, converted = _serialise_value(raw[name], duckdb_types[name])
            row[name] = value
            non_finite += converted
        rows.append(row)

    advisories: list[Advisory] = []
    if date_columns:
        noun = "column" if len(date_columns) == 1 else "columns"
        advisories.append(
            Advisory(
                code="dates_normalised",
                message=(
                    f"{len(date_columns)} {noun} normalised to ISO-8601 (UTC): "
                    + ", ".join(date_columns)
                ),
            )
        )
    if non_finite:
        noun = "float" if non_finite == 1 else "floats"
        advisories.append(
            Advisory(
                code="non_finite_nulled",
                message=f"{non_finite} non-finite {noun} converted to null",
            )
        )
    return rows, tuple(advisories)


def _is_temporal(reported: str) -> bool:
    return bucket_for(reported) in {"date", "timestamp", "timestamptz"}


def _serialise_value(value: object, reported: str) -> tuple[object, int]:
    if value is None:
        return None, 0
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return int(value), 0
        return float(value), 0
    bucket = bucket_for(reported)
    if bucket == "date" and isinstance(value, date):
        return date(value.year, value.month, value.day).isoformat(), 0
    if bucket == "timestamp" and isinstance(value, datetime):
        return value.replace(tzinfo=None).isoformat(), 0
    if bucket == "timestamptz" and isinstance(value, datetime):
        utc = value.astimezone(UTC).replace(tzinfo=None)
        return utc.isoformat() + "Z", 0
    head = reported.split("(", 1)[0].strip().upper()
    if head in _FLOAT_HEADS and isinstance(value, float) and not math.isfinite(value):
        return None, 1
    return value, 0
