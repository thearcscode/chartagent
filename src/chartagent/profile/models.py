"""The data profile contract (ADR-0011). Internal at P1 — not in ``__all__``."""

from __future__ import annotations

from typing import Annotated, Any, ClassVar, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    model_serializer,
)

SAMPLE_ROWS = 10
SATURATION_CAP = 1001
TOP_K = 10

Rung = Literal[
    "reported_type_head", "sample_rows", "top_values", "percentiles", "columns"
]


class _Model(BaseModel):
    """Base carrying the taint classification every subclass must complete."""

    model_config = ConfigDict(extra="forbid")
    TRUSTED: ClassVar[frozenset[str]] = frozenset()
    UNTRUSTED: ClassVar[frozenset[str]] = frozenset()


class TopValue(_Model):
    """One enumerated value and its row count. The value is data; the count is ours."""

    value: Any
    count: int
    TRUSTED = frozenset({"count"})
    UNTRUSTED = frozenset({"value"})


class NumberStats(_Model):
    """Every field required: absence of the whole object is the only signal."""

    min: float
    max: float
    p01: float
    p25: float
    p50: float
    p75: float
    p99: float
    TRUSTED = frozenset({"min", "max", "p01", "p25", "p50", "p75", "p99"})


class TemporalStats(_Model):
    """ISO-8601 strings, UTC for ``timestamptz`` (ADR-0008 D9). Computed, so ours."""

    min: str
    max: str
    p01: str
    p25: str
    p50: str
    p75: str
    p99: str
    TRUSTED = frozenset({"min", "max", "p01", "p25", "p50", "p75", "p99"})


class StringStats(_Model):
    """``min``/``max`` are values copied from the data, so they are untrusted.

    ``iso8601_parse_rate`` is absent when the reported head is not VARCHAR
    (ADR-0011 Decision 9). Inside a present ``StringStats``, ``None`` can only
    mean the head was not VARCHAR.
    """

    min: str
    max: str
    top_k_coverage: float
    iso8601_parse_rate: float | None = None
    TRUSTED = frozenset({"top_k_coverage", "iso8601_parse_rate"})
    UNTRUSTED = frozenset({"min", "max"})


class _Column(_Model):
    name: str
    reported_type: str


class NumberColumn(_Column):
    bucket: Literal["number"] = "number"
    null_rate: float
    distinct: int
    saturated: bool
    stats: NumberStats | None = None
    TRUSTED = frozenset({"bucket", "null_rate", "distinct", "saturated", "stats"})
    UNTRUSTED = frozenset({"name", "reported_type"})


class TemporalColumn(_Column):
    """One variant for three buckets: they chart differently but share a stats shape."""

    bucket: Literal["date", "timestamp", "timestamptz"]
    null_rate: float
    distinct: int
    saturated: bool
    stats: TemporalStats | None = None
    TRUSTED = frozenset({"bucket", "null_rate", "distinct", "saturated", "stats"})
    UNTRUSTED = frozenset({"name", "reported_type"})


class StringColumn(_Column):
    bucket: Literal["string"] = "string"
    null_rate: float
    distinct: int
    saturated: bool
    top: list[TopValue] | None = None
    stats: StringStats | None = None
    TRUSTED = frozenset(
        {"bucket", "null_rate", "distinct", "saturated", "top", "stats"}
    )
    UNTRUSTED = frozenset({"name", "reported_type"})


class BooleanColumn(_Column):
    """No ``stats``: ``top`` enumerates every value including null."""

    bucket: Literal["boolean"] = "boolean"
    null_rate: float
    distinct: int
    saturated: bool
    top: list[TopValue] | None = None
    TRUSTED = frozenset({"bucket", "null_rate", "distinct", "saturated", "top"})
    UNTRUSTED = frozenset({"name", "reported_type"})


class OtherColumn(_Column):
    """No statistics and no scan (ADR-0011 Decision 3)."""

    bucket: Literal["other"] = "other"
    TRUSTED = frozenset({"bucket"})
    UNTRUSTED = frozenset({"name", "reported_type"})


Column = Annotated[
    NumberColumn | TemporalColumn | StringColumn | BooleanColumn | OtherColumn,
    Field(discriminator="bucket"),
]


class Truncation(_Model):
    """Present only when a rung fired; never a zeroed object."""

    rungs: list[Rung]
    omitted_count: int | None = None
    TRUSTED = frozenset({"rungs", "omitted_count"})


class Profile(_Model):
    """No source identity, no timestamps, no version field (ADR-0011 Decision 2)."""

    row_count: int
    columns: list[Column]
    sample_rows: list[dict[str, Any]] = Field(default_factory=list)
    truncation: Truncation | None = None
    TRUSTED = frozenset({"row_count", "columns", "truncation"})
    UNTRUSTED = frozenset({"sample_rows"})

    @model_serializer(mode="wrap")
    def _omit_absent_truncation(
        self, handler: SerializerFunctionWrapHandler
    ) -> dict[str, Any]:
        payload = handler(self)
        if not isinstance(payload, dict):
            raise TypeError("profile dump is not a dict")
        if payload.get("truncation") is None:
            payload.pop("truncation", None)
        return payload


ALL_MODELS: list[type[_Model]] = [
    TopValue,
    NumberStats,
    TemporalStats,
    StringStats,
    NumberColumn,
    TemporalColumn,
    StringColumn,
    BooleanColumn,
    OtherColumn,
    Truncation,
    Profile,
]


def untrusted_paths() -> list[str]:
    """The manifest the prompt renderer consumes. Not a field in the artifact."""
    paths: list[str] = []
    for name in sorted(Profile.UNTRUSTED):
        paths.append(f"{name}[] (keys and values)" if name == "sample_rows" else name)
    for model in (
        NumberColumn,
        TemporalColumn,
        StringColumn,
        BooleanColumn,
        OtherColumn,
    ):
        for field in sorted(model.UNTRUSTED):
            path = f"columns[{model.__name__}].{field}"
            if path not in paths:
                paths.append(path)
    for field in sorted(StringStats.UNTRUSTED):
        paths.append(f"columns[StringColumn].stats.{field}")
    for field in sorted(TopValue.UNTRUSTED):
        paths.append(f"columns[*].top[].{field}")
    return paths
