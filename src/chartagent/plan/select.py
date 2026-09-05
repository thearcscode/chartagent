"""Backend selection: ``requested_backend``, then the ranking (ADR-0021).

No model call. Code picks one of the filter's survivors so step 2 can
be checked against one of the 151 generated models. ``requested_backend``
is consumed here and discarded — it never reaches an emitted frame.
"""

from __future__ import annotations

from collections.abc import Mapping

from chartagent.errors import BackendCapabilityError
from chartagent.frame._generated import FLINT_VERSION
from chartagent.frame.capability import declared_backends
from chartagent.frame.input import BACKEND_RANKING, Backend


def select_backend(
    chart_type: str,
    encodings: Mapping[str, object],
    requested_backend: Backend | None = None,
) -> Backend:
    survivors = declared_backends(chart_type, encodings)
    if requested_backend is not None:
        if requested_backend in survivors:
            return requested_backend
        unconstrained = declared_backends(chart_type, {})
        if requested_backend in unconstrained:
            keys = tuple(
                name
                for name in encodings
                if requested_backend
                not in declared_backends(chart_type, {name: encodings[name]})
            )
            raise BackendCapabilityError(
                f"excel does not support faceting via {keys}",
                kind="facet",
                keys=keys,
                chart_type=chart_type,
                backend=requested_backend,
                pin=FLINT_VERSION,
            )
        raise BackendCapabilityError(
            f"{requested_backend} does not declare chart type {chart_type!r}",
            kind="chart_type",
            keys=(chart_type,),
            chart_type=chart_type,
            backend=requested_backend,
            pin=FLINT_VERSION,
        )
    return next(
        name for name in BACKEND_RANKING if name != "excel" and name in survivors
    )
