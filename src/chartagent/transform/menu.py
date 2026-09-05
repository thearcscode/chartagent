"""Compile the eight-slot transform menu to DuckDB's relational API."""

from __future__ import annotations

from collections.abc import Mapping

import duckdb
import pyarrow as pa
from duckdb import (
    ColumnExpression,
    ConstantExpression,
    FunctionExpression,
    StarExpression,
)

from chartagent.errors import SpecShapeError
from chartagent.frame.input import SourceBucket
from chartagent.transform.engine import collect, pass_through
from chartagent.transform.expr import compile_expr
from chartagent.transform.raw_sql import run_raw_sql

_SLOTS = frozenset(
    {"filter", "derive", "bin", "group_by", "aggregate", "having", "sort", "limit"}
)


def check_transform_shape(transform: Mapping[str, object] | None) -> None:
    """Reject unrecognised slots and ``raw_sql`` mixed with the menu. Data-free."""
    if not transform:
        return
    if "raw_sql" in transform:
        others = tuple(key for key in transform if key != "raw_sql")
        menu = tuple(key for key in others if key in _SLOTS)
        if menu:
            raise SpecShapeError(f"raw_sql cannot mix with menu slots: {menu}")
        if others:
            raise SpecShapeError(f"unrecognised transform slot(s): {others}")
        return
    unknown = tuple(key for key in transform if key not in _SLOTS)
    if unknown:
        raise SpecShapeError(f"unrecognised transform slot(s): {unknown}")


def run_transform(
    connection: duckdb.DuckDBPyConnection,
    transform: Mapping[str, object] | None,
    *,
    source_types: Mapping[str, str],
    source_schema: Mapping[str, SourceBucket],
    timeout: float | None,
    memory_limit: str | None = None,
) -> tuple[pa.Table, dict[str, str]]:
    """Execute an absent/empty transform as pass-through, else the menu or raw_sql."""
    check_transform_shape(transform)
    if not transform:
        return pass_through(connection, timeout=timeout), dict(source_types)

    if "raw_sql" in transform:
        return run_raw_sql(
            connection,
            transform["raw_sql"],
            timeout=timeout,
            memory_limit=memory_limit,
        )

    relation = connection.table("source")
    scope = set(source_types)
    schema = dict(source_schema)

    if "filter" in transform:
        predicate = compile_expr(
            transform["filter"],
            path="transform.filter",
            scope=scope,
            source_schema=schema,
        )
        relation = relation.filter(predicate)

    if "derive" in transform:
        relation, scope = _apply_derive(
            relation, transform["derive"], scope=scope, schema=schema
        )

    if "bin" in transform:
        relation, scope = _apply_bin(
            relation, transform["bin"], scope=scope, schema=schema
        )

    if "group_by" in transform or "aggregate" in transform:
        relation, scope = _apply_group(
            relation,
            groups=transform.get("group_by"),
            aggregates=transform.get("aggregate"),
            scope=scope,
            schema=schema,
        )

    if "having" in transform:
        predicate = compile_expr(
            transform["having"],
            path="transform.having",
            scope=scope,
            source_schema=schema,
            stage="having",
        )
        relation = relation.filter(predicate)

    if "sort" in transform or "limit" in transform:
        relation = _apply_sort_limit(
            relation,
            sorts=transform.get("sort"),
            limit=transform.get("limit"),
            scope=scope,
        )

    output_types = dict(zip(relation.columns, (str(dtype) for dtype in relation.types)))
    return collect(connection, relation, timeout), output_types


def _apply_derive(
    relation: duckdb.DuckDBPyRelation,
    items: object,
    *,
    scope: set[str],
    schema: dict[str, SourceBucket],
) -> tuple[duckdb.DuckDBPyRelation, set[str]]:
    if not isinstance(items, list):
        raise SpecShapeError("transform.derive must be a list")
    for index, item in enumerate(items):
        path = f"transform.derive[{index}]"
        if not isinstance(item, dict):
            raise SpecShapeError(f"{path} must be an object with name and expr")
        name = item.get("name")
        if not isinstance(name, str) or not name:
            raise SpecShapeError(f"{path}.name is required")
        if name in scope:
            raise SpecShapeError(f"{path}: colliding transform output name {name!r}")
        expr = compile_expr(
            item.get("expr"),
            path=f"{path}.expr",
            scope=scope,
            source_schema=schema,
        )
        relation = relation.project(StarExpression(), expr.alias(name))
        scope.add(name)
        kind = item.get("expr")
        if isinstance(kind, dict) and kind.get("kind") in {
            "add",
            "sub",
            "mul",
            "div",
            "neg",
        }:
            schema[name] = "number"
        elif isinstance(kind, dict) and kind.get("kind") == "concat":
            schema[name] = "string"
    return relation, scope


_TEMPORAL_UNITS = frozenset({"year", "quarter", "month", "week", "day", "hour"})
_AGG_OPS = frozenset({"sum", "mean", "min", "max", "count", "count_distinct", "median"})


def _apply_bin(
    relation: duckdb.DuckDBPyRelation,
    items: object,
    *,
    scope: set[str],
    schema: dict[str, SourceBucket],
) -> tuple[duckdb.DuckDBPyRelation, set[str]]:
    if not isinstance(items, list):
        raise SpecShapeError("transform.bin must be a list")
    for index, item in enumerate(items):
        path = f"transform.bin[{index}]"
        if not isinstance(item, dict):
            raise SpecShapeError(f"{path} must be a temporal or numeric bin")
        name = item.get("name")
        field = item.get("field")
        if not isinstance(name, str) or not name:
            raise SpecShapeError(f"{path}.name is required")
        if not isinstance(field, str) or not field:
            raise SpecShapeError(f"{path}.field is required")
        if name in scope:
            raise SpecShapeError(f"{path}: colliding transform output name {name!r}")
        if field not in scope:
            raise SpecShapeError(f"{path}.field: unknown column {field!r}")
        expr = _bin_expr(item, path=path, field=field)
        relation = relation.project(StarExpression(), expr.alias(name))
        scope.add(name)
        if "unit" in item:
            schema[name] = "timestamp" if item["unit"] == "hour" else "date"
        else:
            schema[name] = "number"
    return relation, scope


def _bin_expr(item: dict[str, object], *, path: str, field: str) -> duckdb.Expression:
    column = ColumnExpression(field)
    if "unit" in item:
        unit = item["unit"]
        if unit not in _TEMPORAL_UNITS:
            raise SpecShapeError(
                f"{path}.unit must be one of {sorted(_TEMPORAL_UNITS)}"
            )
        truncated = FunctionExpression("date_trunc", ConstantExpression(unit), column)
        cast_to = "TIMESTAMP" if unit == "hour" else "DATE"
        return truncated.cast(cast_to)
    width = item.get("width")
    if not isinstance(width, (int, float)) or isinstance(width, bool) or width == 0:
        raise SpecShapeError(f"{path}.width must be a non-zero number")
    origin = item.get("origin", 0)
    if not isinstance(origin, (int, float)) or isinstance(origin, bool):
        raise SpecShapeError(f"{path}.origin must be a number")
    origin_expr = ConstantExpression(origin)
    width_expr = ConstantExpression(width)
    return (
        FunctionExpression("floor", (column - origin_expr) / width_expr) * width_expr
    ) + origin_expr


def _apply_group(
    relation: duckdb.DuckDBPyRelation,
    *,
    groups: object,
    aggregates: object,
    scope: set[str],
    schema: dict[str, SourceBucket],
) -> tuple[duckdb.DuckDBPyRelation, set[str]]:
    group_names = _group_names(groups, scope=scope)
    agg_exprs, agg_names = _aggregate_exprs(
        aggregates, scope=scope, reserved=set(group_names)
    )
    for name in agg_names:
        schema[name] = "number"
    if not group_names and not agg_exprs:
        raise SpecShapeError("transform.group_by and transform.aggregate are empty")
    if group_names and not agg_exprs:
        projected = [ColumnExpression(name) for name in group_names]
        return relation.project(*projected).distinct(), set(group_names)
    if not group_names:
        return relation.aggregate(agg_exprs), set(agg_names)
    selected = [ColumnExpression(name) for name in group_names]
    selected.extend(agg_exprs)
    return relation.aggregate(selected), set(group_names) | set(agg_names)


def _group_names(groups: object, *, scope: set[str]) -> list[str]:
    if groups is None:
        return []
    if not isinstance(groups, list) or not all(
        isinstance(name, str) for name in groups
    ):
        raise SpecShapeError("transform.group_by must be a list of column names")
    names = [str(name) for name in groups]
    unknown = [name for name in names if name not in scope]
    if unknown:
        raise SpecShapeError(f"transform.group_by names unknown column(s): {unknown}")
    return names


def _aggregate_exprs(
    aggregates: object, *, scope: set[str], reserved: set[str]
) -> tuple[list[duckdb.Expression], list[str]]:
    if aggregates is None:
        return [], []
    if not isinstance(aggregates, list):
        raise SpecShapeError("transform.aggregate must be a list")
    exprs: list[duckdb.Expression] = []
    names: list[str] = []
    seen = set(reserved)
    for index, item in enumerate(aggregates):
        path = f"transform.aggregate[{index}]"
        if not isinstance(item, dict):
            raise SpecShapeError(f"{path} must be an object")
        name = item.get("name")
        op = item.get("op")
        if not isinstance(name, str) or not name:
            raise SpecShapeError(f"{path}.name is required")
        if op not in _AGG_OPS:
            raise SpecShapeError(f"{path}.op must be one of {sorted(_AGG_OPS)}")
        if name in seen:
            raise SpecShapeError(f"{path}: colliding transform output name {name!r}")
        exprs.append(
            _aggregate_expr(item, path=path, op=str(op), scope=scope).alias(name)
        )
        names.append(name)
        seen.add(name)
    return exprs, names


def _aggregate_expr(
    item: dict[str, object], *, path: str, op: str, scope: set[str]
) -> duckdb.Expression:
    field = item.get("field")
    if op == "count":
        if field is not None:
            raise SpecShapeError(f"{path}: count takes no field")
        return FunctionExpression("count")
    if not isinstance(field, str) or not field:
        raise SpecShapeError(f"{path}.field is required")
    if field not in scope:
        raise SpecShapeError(f"{path}.field: unknown column {field!r}")
    column = ColumnExpression(field)
    if op == "count_distinct":
        return FunctionExpression(
            "len",
            FunctionExpression("list_distinct", FunctionExpression("list", column)),
        )
    return FunctionExpression(op, column)


def _apply_sort_limit(
    relation: duckdb.DuckDBPyRelation,
    *,
    sorts: object,
    limit: object,
    scope: set[str],
) -> duckdb.DuckDBPyRelation:
    keys: list[duckdb.Expression] = []
    used: set[str] = set()
    if sorts is not None:
        if not isinstance(sorts, list):
            raise SpecShapeError("transform.sort must be a list")
        for index, item in enumerate(sorts):
            path = f"transform.sort[{index}]"
            if not isinstance(item, dict):
                raise SpecShapeError(f"{path} must be an object")
            field = item.get("field")
            if not isinstance(field, str):
                raise SpecShapeError(f"{path}.field must be an output column")
            if field not in scope:
                continue
            direction = item.get("dir", "asc")
            nulls = item.get("nulls", "last")
            if direction not in {"asc", "desc"}:
                raise SpecShapeError(f"{path}.dir must be 'asc' or 'desc'")
            if nulls not in {"first", "last"}:
                raise SpecShapeError(f"{path}.nulls must be 'first' or 'last'")
            expr = ColumnExpression(field)
            expr = expr.desc() if direction == "desc" else expr.asc()
            expr = expr.nulls_first() if nulls == "first" else expr.nulls_last()
            keys.append(expr)
            used.add(field)
    if limit is not None:
        for name in relation.columns:
            if name not in used:
                keys.append(ColumnExpression(name).asc().nulls_last())
    if keys:
        relation = relation.sort(*keys)
    if limit is None:
        return relation
    if not isinstance(limit, dict):
        raise SpecShapeError("transform.limit must be an object")
    count = limit.get("count")
    offset = limit.get("offset", 0)
    if not isinstance(count, int) or isinstance(count, bool) or count < 0:
        raise SpecShapeError("transform.limit.count must be a non-negative integer")
    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
        raise SpecShapeError("transform.limit.offset must be a non-negative integer")
    return relation.limit(count, offset)
