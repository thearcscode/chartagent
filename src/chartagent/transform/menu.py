"""Compile the eight-slot transform menu to DuckDB's relational API.

Shape is :mod:`chartagent.transform.model`'s (ADR-0023): by the time
``run_transform`` is called, ``transform`` has already decoded through that
model, so this module only executes it — plus the data-dependent checks the
model cannot make (column existence, scope per stage).
"""

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
from chartagent.transform.model import TRANSFORM_SLOTS
from chartagent.transform.raw_sql import run_raw_sql

__all__ = ["TRANSFORM_SLOTS", "run_transform"]


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
    assert isinstance(items, list)
    for index, item in enumerate(items):
        path = f"transform.derive[{index}]"
        name = item["name"]
        assert isinstance(name, str)
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


def _apply_bin(
    relation: duckdb.DuckDBPyRelation,
    items: object,
    *,
    scope: set[str],
    schema: dict[str, SourceBucket],
) -> tuple[duckdb.DuckDBPyRelation, set[str]]:
    assert isinstance(items, list)
    for index, item in enumerate(items):
        path = f"transform.bin[{index}]"
        name = item["name"]
        field = item["field"]
        assert isinstance(name, str) and isinstance(field, str)
        if name in scope:
            raise SpecShapeError(f"{path}: colliding transform output name {name!r}")
        if field not in scope:
            raise SpecShapeError(f"{path}.field: unknown column {field!r}")
        expr = _bin_expr(item, field=field)
        relation = relation.project(StarExpression(), expr.alias(name))
        scope.add(name)
        if item.get("unit") is not None:
            schema[name] = "timestamp" if item["unit"] == "hour" else "date"
        else:
            schema[name] = "number"
    return relation, scope


def _bin_expr(item: dict[str, object], *, field: str) -> duckdb.Expression:
    column = ColumnExpression(field)
    unit = item.get("unit")
    if unit is not None:
        assert isinstance(unit, str)
        truncated = FunctionExpression("date_trunc", ConstantExpression(unit), column)
        cast_to = "TIMESTAMP" if unit == "hour" else "DATE"
        return truncated.cast(cast_to)
    origin = item.get("origin", 0)
    width = item["width"]
    assert isinstance(origin, (int, float)) and isinstance(width, (int, float))
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
    assert isinstance(groups, list)
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
    assert isinstance(aggregates, list)
    exprs: list[duckdb.Expression] = []
    names: list[str] = []
    seen = set(reserved)
    for index, item in enumerate(aggregates):
        path = f"transform.aggregate[{index}]"
        name = item["name"]
        op = item["op"]
        assert isinstance(name, str) and isinstance(op, str)
        if name in seen:
            raise SpecShapeError(f"{path}: colliding transform output name {name!r}")
        exprs.append(_aggregate_expr(item, path=path, op=op, scope=scope).alias(name))
        names.append(name)
        seen.add(name)
    return exprs, names


def _aggregate_expr(
    item: dict[str, object], *, path: str, op: str, scope: set[str]
) -> duckdb.Expression:
    if op == "count":
        return FunctionExpression("count")
    field = item["field"]
    assert isinstance(field, str)
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
        assert isinstance(sorts, list)
        for item in sorts:
            field = item["field"]
            assert isinstance(field, str)
            # A sort.field naming a column not in output scope is silently
            # skipped, unchanged (ADR-0023 Decision 4 — bind-time scope
            # needs rows; the typed model cannot make this refusal; its own
            # later ticket).
            if field not in scope:
                continue
            direction = item["dir"]
            nulls = item["nulls"]
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
    assert isinstance(limit, dict)
    count = limit["count"]
    offset = limit["offset"]
    assert isinstance(count, int) and isinstance(offset, int)
    return relation.limit(count, offset)
