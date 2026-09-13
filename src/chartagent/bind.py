"""``bind`` — the library's one P0 entry point (ADR-0005 Decision 1)."""

from __future__ import annotations

import time
from os import PathLike
from typing import Any, Protocol, TypeAlias, get_args

from pydantic import ValidationError

from chartagent._flint import flint_bundle
from chartagent.envelope import Advisory, Envelope
from chartagent.errors import (
    BackendCapabilityError,
    ChartAgentError,
    SpecShapeError,
    SpecVocabularyError,
)
from chartagent.frame._generated import FLINT_VERSION
from chartagent.frame.capability import (
    check_backend_chart_type,
    check_excel_facet,
    declared_backends,  # noqa: F401 — imported so bind defines none of the four
    properties_model,
)
from chartagent.frame.input import Backend, InputFrame, _omit_nulls
from chartagent.frame.vocabulary import vocabulary
from chartagent.transform.drift import (
    check_output_stage,
    check_source_stage,
    output_references,
    referenced_source_columns,
    unchecked_source_columns,
)
from chartagent.transform.engine import (
    describe_source,
    open_connection,
    register_source,
)
from chartagent.transform.menu import run_transform
from chartagent.transform.model import transform_mapping
from chartagent.transform.raw_sql import sql_source_refs, validate_raw_sql
from chartagent.transform.serialize import serialize_rows

_THEME_IGNORED = frozenset({"echarts", "chartjs"})

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
    memory_limit: str | None = None,
) -> Envelope:
    """Run an absent/empty transform as pass-through and return an envelope."""
    frame = _validate_frame(spec, backend=backend)
    if backend not in _BACKENDS:
        raise SpecShapeError(f"backend {backend!r} is not a Flint backend")
    check_backend_chart_type(frame, backend)
    check_excel_facet(frame, backend)
    _check_chart_properties(frame, backend)

    transform = (
        None
        if frame.x_chartagent is None
        else transform_mapping(frame.x_chartagent.transform)
    )
    baseline = None if frame.x_chartagent is None else frame.x_chartagent.source_schema
    connection = open_connection(memory_limit=memory_limit)
    started = time.perf_counter()
    try:
        register_source(connection, data)
        reported_types, source_schema = describe_source(connection)
        refs, star = _source_refs(connection, transform)
        if star:
            seen_schema = None
        else:
            seen_schema = check_source_stage(
                refs, source_schema, reported_types, baseline
            )
        table, output_types = run_transform(
            connection,
            transform,
            source_types=reported_types,
            source_schema=source_schema,
            timeout=timeout,
            memory_limit=memory_limit,
        )
    finally:
        connection.close()
    needed = output_references(
        frame.chart_spec.encodings, frame.semantic_types, transform
    )
    check_output_stage(needed, set(table.column_names))
    rows, advisories = serialize_rows(table, output_types)
    warnings = _advisories(
        frame=frame,
        backend=backend,
        transform=transform,
        refs=refs,
        star=star,
        baseline=baseline,
        output_columns=set(table.column_names),
        needed=needed,
        rows=rows,
        serialize=advisories,
    )
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
        warnings=warnings,
        source_schema=seen_schema,
    )


def _source_refs(
    connection: Any,
    transform: dict[str, Any] | None,
) -> tuple[frozenset[str], bool]:
    if transform is not None and "raw_sql" in transform:
        if any(key != "raw_sql" for key in transform):
            return frozenset(), False
        sql = transform["raw_sql"]
        if not isinstance(sql, str):
            return frozenset(), False
        validate_raw_sql(connection, sql)
        parsed = sql_source_refs(connection, sql)
        if parsed is None:
            return frozenset(), True
        return parsed, False
    return referenced_source_columns(transform), False


def _advisories(
    *,
    frame: InputFrame,
    backend: Backend,
    transform: dict[str, Any] | None,
    refs: frozenset[str],
    star: bool,
    baseline: dict[str, Any] | None,
    output_columns: set[str],
    needed: frozenset[str],
    rows: list[dict[str, Any]],
    serialize: tuple[Advisory, ...],
) -> tuple[Advisory, ...]:
    items: list[Advisory] = []
    if frame.theme_spec is not None and backend in _THEME_IGNORED:
        items.append(
            Advisory(
                code="theme_spec_ignored",
                message=f"theme_spec is set and {backend} discards it",
            )
        )
    if star:
        items.append(
            Advisory(
                code="retype_unchecked",
                message=("raw_sql uses STAR; referenced source columns are indefinite"),
            )
        )
    else:
        missing = unchecked_source_columns(refs, baseline)
        if missing:
            reason = (
                "source_schema baseline is absent"
                if baseline is None
                else "source_schema baseline is missing entries"
            )
            items.append(
                Advisory(
                    code="retype_unchecked",
                    message=f"{reason}; columns unchecked: {', '.join(missing)}",
                )
            )
    if transform is not None and "raw_sql" in transform:
        items.append(
            Advisory(
                code="raw_sql_used",
                message="transform used the raw_sql escape hatch",
            )
        )
    if not rows:
        items.append(
            Advisory(code="empty_result", message="transform returned zero rows")
        )
    items.extend(serialize)
    extra = sorted(name for name in output_columns if name not in needed)
    if extra:
        items.append(
            Advisory(
                code="additive_drift_ignored",
                message=(
                    "transform produced unreferenced column(s): " + ", ".join(extra)
                ),
            )
        )
    return tuple(items)


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


def _check_chart_properties(frame: InputFrame, backend: Backend) -> None:
    chart_type = frame.chart_spec.chart_type
    model = properties_model(backend, chart_type)
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
