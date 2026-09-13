"""The typed transform menu — one model for the fragment and the stored frame.

ADR-0023. Eight slots plus ``raw_sql`` (mutually exclusive, ``extra='forbid'``
throughout), and ``Expr`` grouped by arity into eight shapes (``col``, ``lit``,
unary, binary, n-ary, ``between``, ``in``, ``case``), each carrying a ``kind``
enum. ``Menu`` versus ``RawSql``, and the Expr shape for a given ``kind``, are
both picked by a callable discriminator (Decision 2) — so a decode failure
names one path, not a fan-out of ``anyOf`` branches.

This is the one place the data-free shape rules ``check_transform_shape`` and
``check_expr_shape`` used to enforce now live: closed slots and item keys,
``count`` takes no ``field``, ``count_distinct`` requires one, ``case``
requires ``else`` and a non-empty ``whens``, arity, ``in``'s literal-only
right-hand side, ``raw_sql`` exclusive-or with every slot, and a
present-but-empty ``group_by`` plus ``aggregate``. Column existence, stage
scope, and literal-versus-column bucket compatibility need the source and
stay in :mod:`chartagent.transform.expr` / :mod:`chartagent.transform.menu`.

Not on the public surface — imported by :mod:`chartagent.plan.schema` and
:mod:`chartagent.frame.input`, never by ``chartagent.__all__``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Discriminator,
    Field,
    StrictInt,
    Tag,
    field_validator,
    model_validator,
)
from pydantic_core import PydanticCustomError

# --- Expr kind groups — the single source; expr.py's compiler imports these
# rather than re-listing kind names for its own branching.

COMPARISON_KINDS: frozenset[str] = frozenset({"eq", "ne", "lt", "lte", "gt", "gte"})
ARITHMETIC_KINDS: frozenset[str] = frozenset({"add", "sub", "mul", "div"})
STRING_TEST_KINDS: frozenset[str] = frozenset({"contains", "starts_with", "ends_with"})
UNARY_KINDS: frozenset[str] = frozenset({"is_null", "is_not_null", "not", "neg"})
NARY_KINDS: frozenset[str] = frozenset({"and", "or", "concat", "coalesce"})
BINARY_KINDS: frozenset[str] = COMPARISON_KINDS | ARITHMETIC_KINDS | STRING_TEST_KINDS
_LEAF_AND_VARIADIC_KINDS: frozenset[str] = frozenset(
    {"col", "lit", "between", "in", "case"}
)
EXPR_KINDS: frozenset[str] = (
    UNARY_KINDS | BINARY_KINDS | NARY_KINDS | _LEAF_AND_VARIADIC_KINDS
)

# The eight slots, in the fragment/stored-frame's canonical order. Menu's
# fields below must list exactly these, in this order — a test pins the two
# together so they cannot drift apart.
TRANSFORM_SLOTS: tuple[str, ...] = (
    "filter",
    "derive",
    "bin",
    "group_by",
    "aggregate",
    "having",
    "sort",
    "limit",
)
_TRANSFORM_SLOTS_SET = frozenset(TRANSFORM_SLOTS)

# Loc segments a callable discriminator inserts that are never a real field
# or slot name in this grammar — stripped when rendering a human-readable
# field path (chartagent.frame.input._map_validation_error).
DISCRIMINATOR_TAGS: frozenset[str] = frozenset(
    {"menu", "raw_sql", "unary", "binary", "nary"} | _LEAF_AND_VARIADIC_KINDS
)


def _unrecognised_keys(cls: type[BaseModel], data: Any) -> Any:
    """Shared closed-key check: every allowed name is a field name or alias."""
    if isinstance(data, dict):
        allowed = {(info.alias or name) for name, info in cls.model_fields.items()}
        unknown = tuple(key for key in data if key not in allowed)
        if unknown:
            raise PydanticCustomError(
                "unrecognised_keys",
                "unrecognised key(s) {unknown}",
                {"unknown": unknown},
            )
    return data


class _Closed(BaseModel):
    """``extra='forbid'`` plus the shared ``unrecognised key(s) (...)`` wording."""

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def _reject_unknown_keys(cls, data: Any) -> Any:
        return _unrecognised_keys(cls, data)


# ---------------------------------------------------------------------------
# Expr: arity-grouped, callable discriminator (ADR-0023 Decision 2)
# ---------------------------------------------------------------------------


class ColExpr(_Closed):
    kind: Literal["col"]
    name: str


class LitExpr(_Closed):
    kind: Literal["lit"]
    value: Any


class UnaryExpr(_Closed):
    kind: Literal["is_null", "is_not_null", "not", "neg"]
    args: list[Expr] = Field(min_length=1, max_length=1)


class BinaryExpr(_Closed):
    kind: Literal[
        "eq",
        "ne",
        "lt",
        "lte",
        "gt",
        "gte",
        "add",
        "sub",
        "mul",
        "div",
        "contains",
        "starts_with",
        "ends_with",
    ]
    args: list[Expr] = Field(min_length=2, max_length=2)


class NaryExpr(_Closed):
    kind: Literal["and", "or", "concat", "coalesce"]
    args: list[Expr] = Field(min_length=2)


class BetweenExpr(_Closed):
    kind: Literal["between"]
    args: list[Expr] = Field(min_length=3, max_length=3)


class InExpr(_Closed):
    kind: Literal["in"]
    args: list[Expr] = Field(min_length=2)

    @model_validator(mode="after")
    def _rhs_is_literals(self) -> InExpr:
        for item in self.args[1:]:
            if not isinstance(item, LitExpr):
                raise PydanticCustomError(
                    "in_rhs_not_literal",
                    "in RHS is literals only",
                    {},
                )
        return self


class WhenClause(_Closed):
    when: Expr
    then: Expr


class CaseExpr(_Closed):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    kind: Literal["case"]
    whens: list[WhenClause] = Field(min_length=1)
    else_: Expr = Field(alias="else")

    @model_validator(mode="before")
    @classmethod
    def _reject_unknown_keys(cls, data: Any) -> Any:
        return _unrecognised_keys(cls, data)


def _expr_tag(data: Any) -> str:
    kind = (
        data.get("kind") if isinstance(data, Mapping) else getattr(data, "kind", None)
    )
    if kind in UNARY_KINDS:
        return "unary"
    if kind in BINARY_KINDS:
        return "binary"
    if kind in NARY_KINDS:
        return "nary"
    if kind in _LEAF_AND_VARIADIC_KINDS:
        return str(kind)
    return "unknown"


Expr = Annotated[
    Annotated[ColExpr, Tag("col")]
    | Annotated[LitExpr, Tag("lit")]
    | Annotated[UnaryExpr, Tag("unary")]
    | Annotated[BinaryExpr, Tag("binary")]
    | Annotated[NaryExpr, Tag("nary")]
    | Annotated[BetweenExpr, Tag("between")]
    | Annotated[InExpr, Tag("in")]
    | Annotated[CaseExpr, Tag("case")],
    Discriminator(
        _expr_tag,
        custom_error_type="unknown_expr_kind",
        custom_error_message="unknown Expr kind",
    ),
]

for _model in (
    UnaryExpr,
    BinaryExpr,
    NaryExpr,
    BetweenExpr,
    InExpr,
    WhenClause,
    CaseExpr,
):
    _model.model_rebuild()
del _model


# ---------------------------------------------------------------------------
# Slot item shapes
# ---------------------------------------------------------------------------


class SortItem(_Closed):
    field: str
    dir: Literal["asc", "desc"] = "asc"
    nulls: Literal["first", "last"] = "last"


_AGG_OPS = (
    "sum",
    "mean",
    "min",
    "max",
    "count",
    "count_distinct",
    "median",
)


class AggregateItem(_Closed):
    name: str = Field(min_length=1)
    op: Literal["sum", "mean", "min", "max", "count", "count_distinct", "median"]
    field: str | None = None

    @model_validator(mode="after")
    def _field_matches_op(self) -> AggregateItem:
        if self.op == "count" and self.field is not None:
            raise PydanticCustomError(
                "count_takes_no_field", "count takes no field", {}
            )
        if self.op == "count_distinct" and self.field is None:
            raise PydanticCustomError(
                "count_distinct_requires_field",
                "count_distinct requires a field",
                {},
            )
        if self.op not in {"count", "count_distinct"} and self.field is None:
            raise PydanticCustomError(
                "aggregate_requires_field", "{op} requires a field", {"op": self.op}
            )
        return self


class BinItem(_Closed):
    name: str = Field(min_length=1)
    field: str = Field(min_length=1)
    unit: Literal["year", "quarter", "month", "week", "day", "hour"] | None = None
    width: float | None = None
    origin: float = 0

    @field_validator("width", "origin", mode="before")
    @classmethod
    def _no_bool(cls, value: Any) -> Any:
        if isinstance(value, bool):
            raise PydanticCustomError(
                "not_a_number", "must be a number, not a boolean", {}
            )
        return value

    @model_validator(mode="after")
    def _unit_xor_width(self) -> BinItem:
        if self.unit is None and self.width is None:
            raise PydanticCustomError(
                "bin_needs_unit_or_width",
                "bin item needs either unit or a non-zero width",
                {},
            )
        if self.unit is not None and self.width is not None:
            raise PydanticCustomError(
                "bin_unit_and_width",
                "bin item cannot carry both unit and width",
                {},
            )
        if self.width is not None and self.width == 0:
            raise PydanticCustomError(
                "bin_width_zero", "width must be a non-zero number", {}
            )
        return self


class DeriveItem(_Closed):
    name: str = Field(min_length=1)
    expr: Expr


class LimitItem(_Closed):
    count: StrictInt = Field(ge=0)
    offset: StrictInt = Field(ge=0, default=0)


DeriveItem.model_rebuild()


# ---------------------------------------------------------------------------
# Menu / RawSql — mutually exclusive, callable discriminator on Transform
# ---------------------------------------------------------------------------


class Menu(BaseModel):
    """The eight-slot menu. Every slot is optional; ``extra='forbid'``."""

    model_config = ConfigDict(extra="forbid")
    filter: Expr | None = None
    derive: list[DeriveItem] | None = None
    bin: list[BinItem] | None = None
    group_by: list[str] | None = None
    aggregate: list[AggregateItem] | None = None
    having: Expr | None = None
    sort: list[SortItem] | None = None
    limit: LimitItem | None = None

    @model_validator(mode="before")
    @classmethod
    def _closed_slots(cls, data: Any) -> Any:
        if isinstance(data, dict):
            unknown = tuple(key for key in data if key not in _TRANSFORM_SLOTS_SET)
            if unknown:
                raise PydanticCustomError(
                    "unknown_transform_slots",
                    "unrecognised transform slot(s): {unknown}",
                    {"unknown": unknown},
                )
        return data

    @model_validator(mode="before")
    @classmethod
    def _group_and_aggregate_not_both_empty(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        if "group_by" not in data and "aggregate" not in data:
            return data
        groups = data.get("group_by")
        aggregates = data.get("aggregate")
        groups_empty = groups is None or (isinstance(groups, list) and not groups)
        aggregates_empty = aggregates is None or (
            isinstance(aggregates, list) and not aggregates
        )
        if groups_empty and aggregates_empty:
            raise PydanticCustomError(
                "group_by_and_aggregate_empty",
                "transform.group_by and transform.aggregate are empty",
                {},
            )
        return data


Menu.model_rebuild()


class RawSql(BaseModel):
    """The ``raw_sql`` escape hatch — mutually exclusive with every slot."""

    model_config = ConfigDict(extra="forbid")
    raw_sql: str

    @model_validator(mode="before")
    @classmethod
    def _only_raw_sql(cls, data: Any) -> Any:
        if isinstance(data, dict):
            others = tuple(key for key in data if key != "raw_sql")
            menu_keys = tuple(key for key in others if key in _TRANSFORM_SLOTS_SET)
            if menu_keys:
                raise PydanticCustomError(
                    "raw_sql_mixed",
                    "raw_sql cannot mix with menu slots: {menu_keys}",
                    {"menu_keys": menu_keys},
                )
            if others:
                raise PydanticCustomError(
                    "unknown_transform_slots",
                    "unrecognised transform slot(s): {others}",
                    {"others": others},
                )
        return data


def _transform_tag(data: Any) -> str:
    if isinstance(data, Mapping):
        return "raw_sql" if "raw_sql" in data else "menu"
    return "raw_sql" if isinstance(data, RawSql) else "menu"


TransformSpec = Annotated[
    Annotated[Menu, Tag("menu")] | Annotated[RawSql, Tag("raw_sql")],
    Discriminator(_transform_tag),
]


def transform_mapping(transform: object) -> dict[str, Any] | None:
    """A plain dict for the dict-based compilers in ``menu``/``expr``/``drift``.

    Accepts ``None``, a validated :class:`Menu`/:class:`RawSql` instance, or
    a bare ``Mapping`` (``Fragment.model_copy(update=...)`` does not
    revalidate, so a test fixture can still assign a raw dict directly).
    Never re-validates — the model already did that, once, at parse time.

    Only the *top-level* slot keys are dropped when unset (``None`` there
    only ever means "not provided" — the eight slots are all optional).
    Nested dicts dump every field, ``None`` included: an ``Expr`` ``lit``
    node's ``value: None`` is a meaningful SQL ``NULL``, not an absence, and
    ``exclude_none`` at every level would silently drop it.
    """
    if transform is None:
        return None
    if isinstance(transform, BaseModel):
        dumped = transform.model_dump(by_alias=True)
        return {key: value for key, value in dumped.items() if value is not None}
    if isinstance(transform, Mapping):
        return dict(transform)
    return None
