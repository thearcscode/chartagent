"""Compile a closed Expr AST to DuckDB's expression API (ADR-0008 D3)."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from functools import reduce
from operator import and_, or_
from typing import Any

import duckdb
from duckdb import (
    CaseExpression,
    CoalesceOperator,
    ColumnExpression,
    ConstantExpression,
    FunctionExpression,
)

from chartagent.errors import SpecShapeError, TransformError
from chartagent.frame.input import SourceBucket

_COMPARISONS = frozenset({"eq", "ne", "lt", "lte", "gt", "gte"})
_ARITHMETIC = frozenset({"add", "sub", "mul", "div"})
_STRING_TESTS = frozenset({"contains", "starts_with", "ends_with"})
_NARY = frozenset({"and", "or", "concat", "coalesce"})
EXPR_KINDS: frozenset[str] = (
    frozenset(
        {
            "col",
            "lit",
            "between",
            "in",
            "is_null",
            "is_not_null",
            "not",
            "neg",
            "case",
        }
    )
    | _COMPARISONS
    | _ARITHMETIC
    | _STRING_TESTS
    | _NARY
)
_CASE_WHEN_KEYS = frozenset({"when", "then"})


def _allowed_expr_keys(kind: str) -> frozenset[str]:
    """Closed key set per Expr node shape (#143, ADR-0023 D4)."""
    if kind == "col":
        return frozenset({"kind", "name"})
    if kind == "lit":
        return frozenset({"kind", "value"})
    if kind == "case":
        return frozenset({"kind", "whens", "else"})
    return frozenset({"kind", "args"})  # unary / binary / n-ary / between / in


def check_no_unknown_keys(
    node: Mapping[str, object], allowed: frozenset[str], *, path: str
) -> None:
    """Closed-key check shared with :mod:`chartagent.transform.menu` (#143)."""
    unknown = tuple(key for key in node if key not in allowed)
    if unknown:
        raise SpecShapeError(f"{path}: unrecognised key(s) {unknown}")


def compile_expr(
    node: object,
    *,
    path: str,
    scope: set[str],
    source_schema: dict[str, SourceBucket],
    as_bucket: SourceBucket | None = None,
    stage: str | None = None,
) -> duckdb.Expression:
    """Compile one Expr node. Unknown kinds are a shape error."""
    if not isinstance(node, dict):
        raise SpecShapeError(f"{path} is not an Expr")
    kind = node.get("kind")
    if not isinstance(kind, str):
        raise SpecShapeError(f"{path} is not an Expr")
    if kind not in EXPR_KINDS:
        raise SpecShapeError(f"{path}: unknown Expr kind {kind!r}")
    check_no_unknown_keys(node, _allowed_expr_keys(kind), path=path)
    try:
        return _compile(
            node,
            kind=kind,
            path=path,
            scope=scope,
            source_schema=source_schema,
            as_bucket=as_bucket,
            stage=stage,
        )
    except duckdb.Error as exc:
        raise TransformError("transform failed", path=path) from exc


def _compile(
    node: dict[str, Any],
    *,
    kind: str,
    path: str,
    scope: set[str],
    source_schema: dict[str, SourceBucket],
    as_bucket: SourceBucket | None,
    stage: str | None = None,
) -> duckdb.Expression:
    if kind == "col":
        return _col(node, path=path, scope=scope, stage=stage)
    if kind == "lit":
        return _lit(node, path=path, as_bucket=as_bucket)
    if kind in _COMPARISONS:
        left, right = _typed_binary(
            node,
            path=path,
            scope=scope,
            source_schema=source_schema,
            stage=stage,
        )
        return _compare(kind, left, right)
    if kind in _ARITHMETIC:
        left, right = _binary_args(
            node,
            path=path,
            scope=scope,
            source_schema=source_schema,
            stage=stage,
        )
        return _arithmetic(kind, left, right)
    if kind == "between":
        return _between(
            node,
            path=path,
            scope=scope,
            source_schema=source_schema,
            stage=stage,
        )
    if kind == "in":
        return _in_expr(
            node,
            path=path,
            scope=scope,
            source_schema=source_schema,
            stage=stage,
        )
    if kind in _STRING_TESTS:
        left, right = _binary_args(
            node,
            path=path,
            scope=scope,
            source_schema=source_schema,
            stage=stage,
        )
        return FunctionExpression(kind, left, right)
    if kind == "is_null":
        return _unary(
            node,
            path=path,
            scope=scope,
            source_schema=source_schema,
            stage=stage,
        ).isnull()
    if kind == "is_not_null":
        return _unary(
            node,
            path=path,
            scope=scope,
            source_schema=source_schema,
            stage=stage,
        ).isnotnull()
    if kind == "not":
        return ~_unary(
            node,
            path=path,
            scope=scope,
            source_schema=source_schema,
            stage=stage,
        )
    if kind == "neg":
        return -_unary(
            node,
            path=path,
            scope=scope,
            source_schema=source_schema,
            stage=stage,
        )
    if kind in _NARY:
        return _nary(
            node,
            kind=kind,
            path=path,
            scope=scope,
            source_schema=source_schema,
            stage=stage,
        )
    if kind == "case":
        return _case(
            node,
            path=path,
            scope=scope,
            source_schema=source_schema,
            stage=stage,
        )
    raise SpecShapeError(f"{path}: unknown Expr kind {kind!r}")


def check_expr_shape(node: object, *, path: str) -> None:
    """Validate an Expr node's structure with no column or type context.

    The step-1 half of what :func:`compile_expr` checks: dict-ness, a
    known ``kind``, closed node keys (#143), arg arity, and ``case``'s
    ``else``/non-empty ``whens`` with closed ``when``/``then`` keys.
    Column existence (``scope``) and literal/bucket compatibility need
    rows and stay ``compile_expr``'s.
    """
    if not isinstance(node, dict):
        raise SpecShapeError(f"{path} is not an Expr")
    kind = node.get("kind")
    if not isinstance(kind, str):
        raise SpecShapeError(f"{path} is not an Expr")
    if kind not in EXPR_KINDS:
        raise SpecShapeError(f"{path}: unknown Expr kind {kind!r}")
    check_no_unknown_keys(node, _allowed_expr_keys(kind), path=path)
    if kind == "col":
        if not isinstance(node.get("name"), str):
            raise SpecShapeError(f"{path}.name must be a string")
    elif kind == "lit":
        if "value" not in node:
            raise SpecShapeError(f"{path}.value is required")
    elif kind in {"is_null", "is_not_null", "not", "neg"}:
        _check_expr_args_shape(node, path=path, minimum=1, exact=1)
    elif kind in _COMPARISONS or kind in _ARITHMETIC or kind in _STRING_TESTS:
        _check_expr_args_shape(node, path=path, minimum=2, exact=2)
    elif kind == "between":
        _check_expr_args_shape(node, path=path, minimum=3, exact=3)
    elif kind == "in":
        _check_in_shape(node, path=path)
    elif kind in _NARY:
        _check_expr_args_shape(node, path=path, minimum=2)
    elif kind == "case":
        _check_case_shape(node, path=path)


def _check_expr_args_shape(
    node: dict[str, Any], *, path: str, minimum: int, exact: int | None = None
) -> None:
    args = node.get("args")
    if not isinstance(args, list) or len(args) < minimum:
        raise SpecShapeError(f"{path}.args must have at least {minimum} Expr node(s)")
    if exact is not None and len(args) != exact:
        raise SpecShapeError(f"{path}.args must be {exact} Expr node(s)")
    for index, arg in enumerate(args):
        check_expr_shape(arg, path=f"{path}.args[{index}]")


def _check_in_shape(node: dict[str, Any], *, path: str) -> None:
    _check_expr_args_shape(node, path=path, minimum=2)
    args = node["args"]
    for index, item in enumerate(args[1:], start=1):
        if not _is_lit(item):
            raise SpecShapeError(
                f"{path}.args[{index}] must be a literal; in RHS is literals only"
            )


def _check_case_shape(node: dict[str, Any], *, path: str) -> None:
    if "else" not in node:
        raise SpecShapeError(f"{path} requires else")
    whens = node.get("whens")
    if not isinstance(whens, list) or not whens:
        raise SpecShapeError(f"{path}.whens must be a non-empty list")
    for index, item in enumerate(whens):
        branch = f"{path}.whens[{index}]"
        if not isinstance(item, dict) or "when" not in item or "then" not in item:
            raise SpecShapeError(f"{branch} must have when and then")
        check_no_unknown_keys(item, _CASE_WHEN_KEYS, path=branch)
        check_expr_shape(item["when"], path=f"{branch}.when")
        check_expr_shape(item["then"], path=f"{branch}.then")
    check_expr_shape(node["else"], path=f"{path}.else")


def _col(
    node: dict[str, Any], *, path: str, scope: set[str], stage: str | None
) -> duckdb.Expression:
    name = node.get("name")
    if not isinstance(name, str):
        raise SpecShapeError(f"{path}.name must be a string")
    if name not in scope:
        if stage == "having":
            raise SpecShapeError(
                f"{path}: column {name!r} is not in scope at the having stage; "
                f"in scope: {sorted(scope)}"
            )
        raise SpecShapeError(f"{path}: unknown column {name!r}")
    return ColumnExpression(name)


def _lit(
    node: dict[str, Any], *, path: str, as_bucket: SourceBucket | None
) -> duckdb.Expression:
    if "value" not in node:
        raise SpecShapeError(f"{path}.value is required")
    value = node["value"]
    if as_bucket in {"date", "timestamp", "timestamptz"}:
        value = _temporal_literal(value, path=path, bucket=as_bucket)
    return ConstantExpression(value)


def _unary(
    node: dict[str, Any],
    *,
    path: str,
    scope: set[str],
    source_schema: dict[str, SourceBucket],
    stage: str | None,
) -> duckdb.Expression:
    args = node.get("args")
    if not isinstance(args, list) or len(args) != 1:
        raise SpecShapeError(f"{path}.args must be one Expr node")
    return compile_expr(
        args[0],
        path=f"{path}.args[0]",
        scope=scope,
        source_schema=source_schema,
        stage=stage,
    )


def _nary(
    node: dict[str, Any],
    *,
    kind: str,
    path: str,
    scope: set[str],
    source_schema: dict[str, SourceBucket],
    stage: str | None,
) -> duckdb.Expression:
    args = _args(node, path=path, minimum=2)
    compiled = [
        compile_expr(
            arg,
            path=f"{path}.args[{index}]",
            scope=scope,
            source_schema=source_schema,
            stage=stage,
        )
        for index, arg in enumerate(args)
    ]
    if kind == "and":
        return reduce(and_, compiled)
    if kind == "or":
        return reduce(or_, compiled)
    if kind == "concat":
        return FunctionExpression("concat", *compiled)
    return CoalesceOperator(*compiled)


def _binary_args(
    node: dict[str, Any],
    *,
    path: str,
    scope: set[str],
    source_schema: dict[str, SourceBucket],
    stage: str | None,
) -> tuple[duckdb.Expression, duckdb.Expression]:
    args = _args(node, path=path, minimum=2, exact=2)
    left = compile_expr(
        args[0],
        path=f"{path}.args[0]",
        scope=scope,
        source_schema=source_schema,
        stage=stage,
    )
    right = compile_expr(
        args[1],
        path=f"{path}.args[1]",
        scope=scope,
        source_schema=source_schema,
        stage=stage,
    )
    return left, right


def _typed_binary(
    node: dict[str, Any],
    *,
    path: str,
    scope: set[str],
    source_schema: dict[str, SourceBucket],
    stage: str | None,
) -> tuple[duckdb.Expression, duckdb.Expression]:
    args = _args(node, path=path, minimum=2, exact=2)
    return (
        _typed_arg(
            args[0],
            other=args[1],
            path=f"{path}.args[0]",
            scope=scope,
            source_schema=source_schema,
            stage=stage,
        ),
        _typed_arg(
            args[1],
            other=args[0],
            path=f"{path}.args[1]",
            scope=scope,
            source_schema=source_schema,
            stage=stage,
        ),
    )


def _typed_arg(
    node: object,
    *,
    other: object,
    path: str,
    scope: set[str],
    source_schema: dict[str, SourceBucket],
    stage: str | None,
) -> duckdb.Expression:
    bucket = _column_bucket(other, source_schema) if _is_lit(node) else None
    if bucket is not None and _is_lit(node):
        assert isinstance(node, dict)
        _check_literal(node["value"], bucket=bucket, path=path)
    return compile_expr(
        node,
        path=path,
        scope=scope,
        source_schema=source_schema,
        as_bucket=bucket,
        stage=stage,
    )


def _between(
    node: dict[str, Any],
    *,
    path: str,
    scope: set[str],
    source_schema: dict[str, SourceBucket],
    stage: str | None,
) -> duckdb.Expression:
    args = _args(node, path=path, minimum=3, exact=3)
    tested = compile_expr(
        args[0],
        path=f"{path}.args[0]",
        scope=scope,
        source_schema=source_schema,
        stage=stage,
    )
    low = _typed_arg(
        args[1],
        other=args[0],
        path=f"{path}.args[1]",
        scope=scope,
        source_schema=source_schema,
        stage=stage,
    )
    high = _typed_arg(
        args[2],
        other=args[0],
        path=f"{path}.args[2]",
        scope=scope,
        source_schema=source_schema,
        stage=stage,
    )
    return tested.between(low, high)


def _in_expr(
    node: dict[str, Any],
    *,
    path: str,
    scope: set[str],
    source_schema: dict[str, SourceBucket],
    stage: str | None,
) -> duckdb.Expression:
    args = _args(node, path=path, minimum=2)
    for index, item in enumerate(args[1:], start=1):
        if not _is_lit(item):
            raise SpecShapeError(
                f"{path}.args[{index}] must be a literal; in RHS is literals only"
            )
    tested = compile_expr(
        args[0],
        path=f"{path}.args[0]",
        scope=scope,
        source_schema=source_schema,
        stage=stage,
    )
    values = [
        _typed_arg(
            item,
            other=args[0],
            path=f"{path}.args[{index}]",
            scope=scope,
            source_schema=source_schema,
            stage=stage,
        )
        for index, item in enumerate(args[1:], start=1)
    ]
    return tested.isin(*values)


def _case(
    node: dict[str, Any],
    *,
    path: str,
    scope: set[str],
    source_schema: dict[str, SourceBucket],
    stage: str | None,
) -> duckdb.Expression:
    if "else" not in node:
        raise SpecShapeError(f"{path} requires else")
    whens = node.get("whens")
    if not isinstance(whens, list) or not whens:
        raise SpecShapeError(f"{path}.whens must be a non-empty list")
    compiled: duckdb.Expression | None = None
    branch_types: set[str] = set()
    _note_lit_type(node["else"], branch_types)
    for index, item in enumerate(whens):
        branch = f"{path}.whens[{index}]"
        if not isinstance(item, dict) or "when" not in item or "then" not in item:
            raise SpecShapeError(f"{branch} must have when and then")
        check_no_unknown_keys(item, _CASE_WHEN_KEYS, path=branch)
        _note_lit_type(item["then"], branch_types)
        if len(branch_types) > 1:
            raise SpecShapeError(f"{path}: case branches must share one result type")
        when = compile_expr(
            item["when"],
            path=f"{branch}.when",
            scope=scope,
            source_schema=source_schema,
            stage=stage,
        )
        then = compile_expr(
            item["then"],
            path=f"{branch}.then",
            scope=scope,
            source_schema=source_schema,
            stage=stage,
        )
        if compiled is None:
            compiled = CaseExpression(when, then)
        else:
            compiled = compiled.when(when, then)
    assert compiled is not None
    return compiled.otherwise(
        compile_expr(
            node["else"],
            path=f"{path}.else",
            scope=scope,
            source_schema=source_schema,
            stage=stage,
        )
    )


def _args(
    node: dict[str, Any], *, path: str, minimum: int, exact: int | None = None
) -> list[object]:
    args = node.get("args")
    if not isinstance(args, list) or len(args) < minimum:
        raise SpecShapeError(f"{path}.args must have at least {minimum} Expr node(s)")
    if exact is not None and len(args) != exact:
        raise SpecShapeError(f"{path}.args must be {exact} Expr node(s)")
    return args


def _compare(
    kind: str, left: duckdb.Expression, right: duckdb.Expression
) -> duckdb.Expression:
    if kind == "eq":
        return left == right
    if kind == "ne":
        return left != right
    if kind == "lt":
        return left < right
    if kind == "lte":
        return left <= right
    if kind == "gt":
        return left > right
    return left >= right


def _arithmetic(
    kind: str, left: duckdb.Expression, right: duckdb.Expression
) -> duckdb.Expression:
    if kind == "add":
        return left + right
    if kind == "sub":
        return left - right
    if kind == "mul":
        return left * right
    zero = right == ConstantExpression(0)
    return CaseExpression(zero, ConstantExpression(None)).otherwise(left / right)


def _is_lit(node: object) -> bool:
    return isinstance(node, dict) and node.get("kind") == "lit"


def _note_lit_type(node: object, types: set[str]) -> None:
    if not _is_lit(node):
        return
    assert isinstance(node, dict)
    value = node.get("value")
    if value is None:
        return
    if isinstance(value, bool):
        types.add("boolean")
    elif isinstance(value, (int, float)):
        types.add("number")
    elif isinstance(value, str):
        types.add("string")
    else:
        types.add("other")


def _column_bucket(
    node: object, source_schema: dict[str, SourceBucket]
) -> SourceBucket | None:
    if not isinstance(node, dict) or node.get("kind") != "col":
        return None
    name = node.get("name")
    if not isinstance(name, str):
        return None
    return source_schema.get(name)


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _check_literal(value: object, *, bucket: SourceBucket, path: str) -> None:
    if value is None:
        return
    if bucket == "number" and not _is_number(value):
        raise SpecShapeError(
            f"{path}: literal {value!r} is not compatible with a number column"
        )
    if bucket == "string" and not isinstance(value, str):
        raise SpecShapeError(
            f"{path}: literal {value!r} is not compatible with a string column"
        )
    if bucket == "boolean" and not isinstance(value, bool):
        raise SpecShapeError(
            f"{path}: literal {value!r} is not compatible with a boolean column"
        )
    if bucket in {"date", "timestamp", "timestamptz"}:
        _temporal_literal(value, path=path, bucket=bucket)


def _temporal_literal(
    value: object, *, path: str, bucket: SourceBucket
) -> date | datetime:
    if not isinstance(value, str):
        raise SpecShapeError(
            f"{path}: temporal literal must be an ISO-8601 string, not {value!r}"
        )
    try:
        if bucket == "date":
            return date.fromisoformat(value)
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise SpecShapeError(f"{path}: {value!r} is not an ISO-8601 {bucket}") from exc
    if bucket == "timestamp":
        if parsed.tzinfo is not None:
            raise SpecShapeError(f"{path}: {value!r} is not a timezone-naive timestamp")
        return parsed
    if parsed.tzinfo is None:
        raise SpecShapeError(f"{path}: {value!r} is not an ISO-8601 timestamptz")
    return parsed
