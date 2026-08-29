"""DuckDB reported-type heads → seven source-schema buckets (ADR-0010)."""

from __future__ import annotations

from chartagent.frame.input import SourceBucket

_NUMBER_HEADS = frozenset(
    {
        "TINYINT",
        "SMALLINT",
        "INTEGER",
        "BIGINT",
        "HUGEINT",
        "UTINYINT",
        "USMALLINT",
        "UINTEGER",
        "UBIGINT",
        "UHUGEINT",
        "FLOAT",
        "DOUBLE",
        "DECIMAL",
        "VARINT",
        "BIGNUM",
    }
)
_STRING_HEADS = frozenset({"VARCHAR", "ENUM", "UUID"})
_TIMESTAMP_HEADS = frozenset(
    {"TIMESTAMP", "TIMESTAMP_S", "TIMESTAMP_MS", "TIMESTAMP_NS"}
)


def bucket_for(reported: str) -> SourceBucket:
    """Map a DuckDB ``DESCRIBE`` type to a coarse bucket.

    Arrays (postfix ``]``) are ``other`` before any prefix head is read.
    Parameterised types match on the constructor head only.
    """
    if reported.endswith("]"):
        return "other"
    head = reported.split("(", 1)[0].strip().upper()
    if head == "TIMESTAMP WITH TIME ZONE":
        return "timestamptz"
    if head == "DATE":
        return "date"
    if head == "BOOLEAN":
        return "boolean"
    if head in _TIMESTAMP_HEADS:
        return "timestamp"
    if head in _NUMBER_HEADS:
        return "number"
    if head in _STRING_HEADS:
        return "string"
    return "other"
