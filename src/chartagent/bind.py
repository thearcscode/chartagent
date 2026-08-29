"""``bind`` — the library's one P0 entry point (ADR-0005 Decision 1)."""

from __future__ import annotations

import re
import time
from os import PathLike
from typing import Any, Protocol, TypeAlias, get_args

from pydantic import ValidationError

from chartagent._flint import flint_bundle
from chartagent.envelope import Envelope
from chartagent.errors import (
    BackendCapabilityError,
    ChartAgentError,
    SpecShapeError,
    SpecVocabularyError,
)
from chartagent.frame import _generated
from chartagent.frame._generated import FLINT_VERSION, GeneratedProperties
from chartagent.frame.input import Backend, InputFrame, _omit_nulls
from chartagent.frame.vocabulary import vocabulary
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
    frame = _validate_frame(spec, backend=backend)
    if backend not in _BACKENDS:
        raise SpecShapeError(f"backend {backend!r} is not a Flint backend")
    _check_backend_chart_type(frame, backend)
    _check_excel_facet(frame, backend)
    _check_chart_properties(frame, backend)
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


def _chart_type_of(spec: InputFrame | dict[str, Any]) -> str | None:
    if isinstance(spec, InputFrame):
        return spec.chart_spec.chart_type
    chart_spec = spec.get("chart_spec")
    if isinstance(chart_spec, dict):
        value = chart_spec.get("chartType") or chart_spec.get("chart_type")
        if isinstance(value, str):
            return value
    return None


def _validate_frame(
    spec: InputFrame | dict[str, Any], *, backend: Backend
) -> InputFrame:
    if isinstance(spec, InputFrame):
        return spec
    try:
        return InputFrame.model_validate(spec)
    except ValidationError as exc:
        raise SpecShapeError("input frame is malformed") from exc
    except SpecVocabularyError as exc:
        if exc.backend is None:
            exc.backend = backend
        if exc.chart_type is None:
            exc.chart_type = _chart_type_of(spec)
        raise
    except ChartAgentError:
        raise


def _ident(name: str) -> str:
    return re.sub(r"\W", "_", name)


def _properties_model(backend: str, chart_type: str) -> type[GeneratedProperties]:
    name = f"{_ident(backend).title()}{_ident(chart_type)}Properties"
    model = getattr(_generated, name, None)
    if not (isinstance(model, type) and issubclass(model, GeneratedProperties)):
        raise SpecShapeError(f"no property model for {(backend, chart_type)}")
    return model


def _check_backend_chart_type(frame: InputFrame, backend: Backend) -> None:
    chart_type = frame.chart_spec.chart_type
    if chart_type in vocabulary(backend):
        return
    raise BackendCapabilityError(
        f"{backend} does not declare chart type {chart_type!r}",
        kind="chart_type",
        keys=(chart_type,),
        chart_type=chart_type,
        backend=backend,
        pin=FLINT_VERSION,
    )


_FACET_CHANNELS = ("column", "row")


def _check_excel_facet(frame: InputFrame, backend: Backend) -> None:
    if backend != "excel":
        return
    facets = tuple(
        name for name in _FACET_CHANNELS if name in frame.chart_spec.encodings
    )
    if not facets:
        return
    chart_type = frame.chart_spec.chart_type
    raise BackendCapabilityError(
        f"excel does not support faceting via {facets}",
        kind="facet",
        keys=facets,
        chart_type=chart_type,
        backend=backend,
        pin=FLINT_VERSION,
    )


def _check_chart_properties(frame: InputFrame, backend: Backend) -> None:
    chart_type = frame.chart_spec.chart_type
    model = _properties_model(backend, chart_type)
    try:
        model.model_validate(frame.chart_spec.chart_properties)
    except ValidationError as exc:
        raise _map_property_error(exc, chart_type=chart_type, backend=backend) from exc


def _keys_declared_for_chart_type(chart_type: str) -> frozenset[str]:
    keys: set[str] = set()
    for name in _BACKENDS:
        try:
            vocab = vocabulary(name, chart_type)
        except ValueError:
            continue
        keys.update(item.key for item in vocab.properties)
        keys.update(item.key for item in vocab.encoding_actions)
    return frozenset(keys)


def _map_property_error(
    exc: ValidationError,
    *,
    chart_type: str,
    backend: str,
) -> ChartAgentError:
    extra = tuple(
        str(err["loc"][-1]) for err in exc.errors() if err["type"] == "extra_forbidden"
    )
    declared = _keys_declared_for_chart_type(chart_type)
    nowhere = tuple(key for key in extra if key not in declared)
    portable = tuple(key for key in extra if key in declared)
    if nowhere:
        return SpecVocabularyError(
            f"property key(s) the pin does not declare for {chart_type}: {nowhere}",
            kind="property",
            keys=nowhere,
            chart_type=chart_type,
            backend=backend,
            pin=FLINT_VERSION,
        )
    enum_keys = tuple(
        str(err.get("input")) for err in exc.errors() if err["type"] == "literal_error"
    )
    if enum_keys:
        return SpecVocabularyError(
            f"enum option(s) the pin does not declare for {chart_type}: {enum_keys}",
            kind="enum_option",
            keys=enum_keys,
            chart_type=chart_type,
            backend=backend,
            pin=FLINT_VERSION,
        )
    if portable:
        return BackendCapabilityError(
            f"{backend} does not declare property key(s) {portable} for {chart_type}",
            kind="property",
            keys=portable,
            chart_type=chart_type,
            backend=backend,
            pin=FLINT_VERSION,
        )
    return SpecShapeError("chartProperties is malformed")


def _reject_nonempty_transform(frame: InputFrame) -> None:
    transform = None if frame.x_chartagent is None else frame.x_chartagent.transform
    if not transform:
        return
    unknown = tuple(transform)
    raise SpecShapeError(f"unrecognised transform slot(s): {unknown}")
