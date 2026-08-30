"""The 10 KB degradation ladder (ADR-0011 Decision 5)."""

from __future__ import annotations

import json

from chartagent.profile.models import (
    BUDGET_BYTES,
    REPORTED_TYPE_BUDGET,
    BooleanColumn,
    Column,
    NumberColumn,
    Profile,
    Rung,
    StringColumn,
    TemporalColumn,
    Truncation,
)


def artifact_bytes(profile: Profile) -> int:
    """Prompt-budget size of a profile. Matches the Decision 5 measurements."""
    return len(json.dumps(profile.model_dump(exclude_none=True), default=str).encode())


def apply_ladder(profile: Profile) -> Profile:
    """Fire rungs globally until the artifact holds ``BUDGET_BYTES``."""
    if artifact_bytes(profile) <= BUDGET_BYTES:
        return profile

    fired: list[Rung] = []
    columns = list(profile.columns)
    sample_rows = list(profile.sample_rows)
    row_count = profile.row_count

    columns = [
        (
            column.model_copy(
                update={"reported_type": _reported_head(column.reported_type)}
            )
            if len(column.reported_type) > REPORTED_TYPE_BUDGET
            else column
        )
        for column in columns
    ]
    fired.append("reported_type_head")
    current = Profile(row_count=row_count, columns=columns, sample_rows=sample_rows)
    stamped = _stamp(current, fired)
    if artifact_bytes(stamped) <= BUDGET_BYTES:
        return stamped

    sample_rows = []
    fired.append("sample_rows")
    current = Profile(row_count=row_count, columns=columns, sample_rows=sample_rows)
    stamped = _stamp(current, fired)
    if artifact_bytes(stamped) <= BUDGET_BYTES:
        return stamped

    columns = _shrink_top(columns)
    current = Profile(row_count=row_count, columns=columns, sample_rows=sample_rows)
    stamped = _stamp(current, fired + ["top_values"])
    if artifact_bytes(stamped) <= BUDGET_BYTES:
        return stamped
    columns = _drop_top(columns)
    fired.append("top_values")
    current = Profile(row_count=row_count, columns=columns, sample_rows=sample_rows)
    stamped = _stamp(current, fired)
    if artifact_bytes(stamped) <= BUDGET_BYTES:
        return stamped

    columns = _drop_stats(columns)
    fired.append("percentiles")
    current = Profile(row_count=row_count, columns=columns, sample_rows=sample_rows)
    stamped = _stamp(current, fired)
    if artifact_bytes(stamped) <= BUDGET_BYTES:
        return stamped

    kept = _cap_columns(row_count, columns, fired)
    omitted = len(columns) - kept
    current = Profile(
        row_count=row_count,
        columns=columns[:kept],
        sample_rows=sample_rows,
    )
    fired.append("columns")
    return _stamp(current, fired, omitted)


def _reported_head(reported: str) -> str:
    return reported.split("(", 1)[0].strip()


def _shrink_top(columns: list[Column]) -> list[Column]:
    """Halve each enumeration; the rung then drops what still does not fit."""
    shrunk: list[Column] = []
    for column in columns:
        if not isinstance(column, (StringColumn, BooleanColumn)) or not column.top:
            shrunk.append(column)
            continue
        kept = column.top[: max(len(column.top) // 2, 1)]
        shrunk.append(column.model_copy(update={"top": kept}))
    return shrunk


def _drop_top(columns: list[Column]) -> list[Column]:
    dropped: list[Column] = []
    for column in columns:
        if isinstance(column, (StringColumn, BooleanColumn)) and column.top is not None:
            dropped.append(column.model_copy(update={"top": None}))
        else:
            dropped.append(column)
    return dropped


def _drop_stats(columns: list[Column]) -> list[Column]:
    dropped: list[Column] = []
    for column in columns:
        if (
            isinstance(column, (NumberColumn, TemporalColumn, StringColumn))
            and column.stats is not None
        ):
            dropped.append(column.model_copy(update={"stats": None}))
        else:
            dropped.append(column)
    return dropped


def _cap_columns(row_count: int, columns: list[Column], fired: list[Rung]) -> int:
    kept = len(columns)
    while kept > 1:
        kept -= 1
        omitted = len(columns) - kept
        trial = Profile(
            row_count=row_count,
            columns=columns[:kept],
            sample_rows=[],
            truncation=Truncation(rungs=[*fired, "columns"], omitted_count=omitted),
        )
        if artifact_bytes(trial) <= BUDGET_BYTES:
            return kept
    return 1


def _stamp(profile: Profile, fired: list[Rung], omitted: int | None = None) -> Profile:
    return profile.model_copy(
        update={"truncation": Truncation(rungs=fired, omitted_count=omitted)}
    )
