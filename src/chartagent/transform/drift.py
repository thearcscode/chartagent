"""Two-stage schema drift — ADR-0005 Decision 7, ADR-0010."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from chartagent.errors import DriftedField, SchemaDriftError
from chartagent.frame.input import SourceBucket


def referenced_source_columns(transform: Mapping[str, object] | None) -> frozenset[str]:
    """Source columns the menu names. ``raw_sql`` is handled separately."""
    if not transform or "raw_sql" in transform:
        return frozenset()
    refs: set[str] = set()
    produced: set[str] = set()
    _collect_cols(transform.get("filter"), refs, produced)
    for item in _objects(transform.get("derive")):
        _collect_cols(item.get("expr"), refs, produced)
        _note_produced(item.get("name"), produced)
    for item in _objects(transform.get("bin")):
        _note_source_field(item.get("field"), refs, produced)
        _note_produced(item.get("name"), produced)
    groups = transform.get("group_by")
    if isinstance(groups, list):
        for name in groups:
            if isinstance(name, str):
                _note_source_field(name, refs, produced)
    for item in _objects(transform.get("aggregate")):
        _note_source_field(item.get("field"), refs, produced)
        _note_produced(item.get("name"), produced)
    return frozenset(refs)


def check_source_stage(
    referenced: frozenset[str],
    source_columns: Mapping[str, SourceBucket],
    reported_types: Mapping[str, str],
    baseline: Mapping[str, SourceBucket] | None,
) -> dict[str, SourceBucket]:
    """Compare referenced source columns. Missing baseline is not an error."""
    dropped = [
        DriftedField(name=name, kind="dropped", expected=name, found=None)
        for name in sorted(referenced)
        if name not in source_columns
    ]
    retyped: list[DriftedField] = []
    if baseline:
        for name in sorted(referenced):
            expected = baseline.get(name)
            found = source_columns.get(name)
            if expected is None or found is None or expected == found:
                continue
            retyped.append(
                DriftedField(name=name, kind="retyped", expected=expected, found=found)
            )
    drifted = tuple(dropped + retyped)
    if drifted:
        raise SchemaDriftError(
            _source_message(dropped, retyped, reported_types),
            stage="source",
            drifted=drifted,
        )
    return {
        name: source_columns[name]
        for name in sorted(referenced)
        if name in source_columns
    }


def unchecked_source_columns(
    referenced: frozenset[str],
    baseline: Mapping[str, SourceBucket] | None,
) -> tuple[str, ...]:
    """Referenced columns with no baseline entry. Absent and ``{}`` match."""
    if baseline is None:
        return tuple(sorted(referenced))
    return tuple(sorted(name for name in referenced if name not in baseline))


def output_references(
    encodings: Mapping[str, Any],
    semantic_types: Mapping[str, Any],
    transform: Mapping[str, object] | None,
) -> frozenset[str]:
    """Encoding fields, sort keys, and semantic_types keys."""
    names: set[str] = set()
    for encoding in encodings.values():
        field = getattr(encoding, "field", None)
        if isinstance(field, str):
            names.add(field)
    names.update(str(key) for key in semantic_types)
    if transform:
        for item in _objects(transform.get("sort")):
            field = item.get("field")
            if isinstance(field, str):
                names.add(field)
    return frozenset(names)


def check_output_stage(
    referenced: frozenset[str],
    output_columns: set[str] | frozenset[str],
) -> None:
    """Raise when an encoding, sort, or semantic_types key is missing after execute."""
    dropped = tuple(
        DriftedField(name=name, kind="dropped", expected=name, found=None)
        for name in sorted(referenced)
        if name not in output_columns
    )
    if dropped:
        names = ", ".join(field.name for field in dropped)
        raise SchemaDriftError(
            f"transform output column(s) dropped: {names}",
            stage="transform_output",
            drifted=dropped,
        )


def _source_message(
    dropped: list[DriftedField],
    retyped: list[DriftedField],
    reported_types: Mapping[str, str],
) -> str:
    parts: list[str] = []
    if dropped:
        parts.append(
            "source column(s) dropped: " + ", ".join(field.name for field in dropped)
        )
    for field in retyped:
        reported = reported_types.get(field.name, field.found or "")
        parts.append(
            f"bucket `{field.expected}` → `{field.found}` "
            f"(DuckDB {reported}) on {field.name}"
        )
    return "; ".join(parts)


def _objects(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _note_produced(name: object, produced: set[str]) -> None:
    if isinstance(name, str) and name:
        produced.add(name)


def _note_source_field(name: object, refs: set[str], produced: set[str]) -> None:
    if isinstance(name, str) and name and name not in produced:
        refs.add(name)


def _collect_cols(node: object, refs: set[str], produced: set[str]) -> None:
    if isinstance(node, list):
        for item in node:
            _collect_cols(item, refs, produced)
        return
    if not isinstance(node, dict):
        return
    if node.get("kind") == "col":
        _note_source_field(node.get("name"), refs, produced)
        return
    for value in node.values():
        _collect_cols(value, refs, produced)
