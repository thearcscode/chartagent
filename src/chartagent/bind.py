"""``bind`` — the library's one P0 entry point (ADR-0005 Decision 1)."""

from __future__ import annotations

import time
from os import PathLike
from typing import Any, Protocol, TypeAlias, get_args

from pydantic import ValidationError

from chartagent._flint import flint_bundle
from chartagent.envelope import Envelope
from chartagent.errors import ChartAgentError, SpecShapeError
from chartagent.frame.input import Backend, InputFrame, _omit_nulls
from chartagent.transform.engine import (
    describe_source,
    open_connection,
    pass_through,
    register_source,
)
from chartagent.transform.serialize import serialize_rows

_BACKENDS = frozenset(get_args(Backend))


class ArrowStreamable(Protocol):
    """Arrow PyCapsule stream — pyarrow, Polars, Arrow-backed frames."""

    def __arrow_c_stream__(self, *args: object, **kwargs: object) -> object: ...


DataSource: TypeAlias = str | PathLike[str] | ArrowStreamable | list[dict[str, Any]]


def bind(
    spec: InputFrame | dict[str, Any],
    data: DataSource,
    *,
    backend: Backend,
    timeout: float | None = None,
) -> Envelope:
    """Run an absent/empty transform as pass-through and return an envelope."""
    frame = _validate_frame(spec)
    if backend not in _BACKENDS:
        raise SpecShapeError(f"backend {backend!r} is not a Flint backend")
    _reject_nonempty_transform(frame)

    connection = open_connection()
    started = time.perf_counter()
    try:
        register_source(connection, data)
        reported_types, source_schema = describe_source(connection)
        table = pass_through(connection, timeout=timeout)
    finally:
        connection.close()
    rows, advisories = serialize_rows(table, reported_types)
    elapsed = time.perf_counter() - started

    dumped = frame.model_dump(mode="json", by_alias=True, exclude_none=True)
    payload = _omit_nulls(dumped)
    if not isinstance(payload, dict):
        raise SpecShapeError("input frame is malformed")
    payload["data"] = {"values": rows}

    return Envelope(
        flint_version=flint_bundle().version,
        backend=backend,
        input=payload,
        row_count=len(rows),
        elapsed=elapsed,
        warnings=advisories,
        source_schema=source_schema,
    )


def _validate_frame(spec: InputFrame | dict[str, Any]) -> InputFrame:
    if isinstance(spec, InputFrame):
        return spec
    try:
        return InputFrame.model_validate(spec)
    except ValidationError as exc:
        raise SpecShapeError("input frame is malformed") from exc
    except ChartAgentError:
        raise


def _reject_nonempty_transform(frame: InputFrame) -> None:
    transform = None if frame.x_chartagent is None else frame.x_chartagent.transform
    if not transform:
        return
    unknown = tuple(transform)
    raise SpecShapeError(f"unrecognised transform slot(s): {unknown}")
