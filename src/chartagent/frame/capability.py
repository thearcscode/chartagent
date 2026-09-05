"""Declared-capability filter. Pin-derived, data-free, importable by path.

Not in ``chartagent.__all__`` — the same treatment ``BACKEND_RANKING`` and
``SourceBucket`` already get in this package. Selection *policy* stays out:
no ranking, no Excel-never-default, no tier logic. The filter answers a
set-membership question (ADR-0012 Decision 7, issue #101).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import get_args

from chartagent.errors import BackendCapabilityError, SpecShapeError
from chartagent.frame import _generated
from chartagent.frame._generated import FLINT_VERSION, GeneratedProperties
from chartagent.frame.input import Backend, InputFrame
from chartagent.frame.vocabulary import vocabulary

_FACET_CHANNELS = ("column", "row")
_BACKENDS: tuple[Backend, ...] = get_args(Backend)


def _ident(name: str) -> str:
    return re.sub(r"\W", "_", name)


def properties_model(backend: str, chart_type: str) -> type[GeneratedProperties]:
    name = f"{_ident(backend).title()}{_ident(chart_type)}Properties"
    model = getattr(_generated, name, None)
    if not (isinstance(model, type) and issubclass(model, GeneratedProperties)):
        raise SpecShapeError(f"no property model for {(backend, chart_type)}")
    return model


def check_backend_chart_type(frame: InputFrame, backend: Backend) -> None:
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


def check_excel_facet(frame: InputFrame, backend: Backend) -> None:
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


def declared_backends(
    chart_type: str,
    encodings: Mapping[str, object],
) -> tuple[Backend, ...]:
    """Backends that declare ``(chart_type, encodings)``. Deterministic, unranked."""
    faceted = any(name in encodings for name in _FACET_CHANNELS)
    return tuple(
        name
        for name in _BACKENDS
        if chart_type in vocabulary(name) and not (name == "excel" and faceted)
    )
