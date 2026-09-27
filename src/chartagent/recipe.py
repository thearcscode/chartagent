"""``ChartRecipe`` and ``bind_recipe`` — the custom rail's stored result (ADR-0018).

A recipe is a sibling to the input frame, not a frame with a flag. ``bind_recipe``
runs the transform, drift-checks and attaches rows; it never reads ``module``,
``styles`` or ``libraries``, so a refresh cannot fail on the code. ``BoundRecipe``
has no wire format: nothing compiles it, and what reaches the browser is
``build_shell``'s output plus the channel payload.
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

import pyarrow as pa

from chartagent.bind import DataSource, _run_source_stage
from chartagent.envelope import Advisory
from chartagent.frame.input import SourceBucket, ThemeSpec
from chartagent.transform.drift import unchecked_source_columns
from chartagent.transform.model import Menu, RawSql, transform_mapping
from chartagent.transform.serialize import serialize_rows

_CONTRACT_VERSION = 1


@dataclass(frozen=True)
class EscapeReason:
    """Why a request left the deterministic rail (CONTEXT.md, four buckets)."""

    bucket: Literal[1, 2, 3, 4]


@dataclass(frozen=True)
class LibraryPin:
    """A library's identity, never its bytes (ADR-0017 Decision 8)."""

    name: str
    version: str
    sha256: str


@dataclass(frozen=True)
class ChartDocument:
    """What you store; the module, its CSS and the pinned libraries."""

    module: str
    styles: str | None
    libraries: tuple[LibraryPin, ...]
    contract_version: int = _CONTRACT_VERSION


@dataclass(frozen=True)
class BoundDocument:
    """A chart document plus everything it needs to paint (ADR-0017
    Decision 8) — the custom rail's paintable counterpart to
    ``ChartDocument``, the same split ``Envelope`` embodies for the
    deterministic rail, and the second member of ``Rasteriser``'s
    ``Envelope | BoundDocument`` union (ADR-0005 Decision 9's erratum).

    Reserved here so that union type-checks; nothing in the library
    constructs one yet. ``bind_recipe`` deliberately returns ``BoundRecipe``,
    not this (ADR-0018 Decision 5) — assembling a ``BoundDocument`` needs
    ``build_shell``'s verified library bytes, which is the still-unbuilt
    custom-rail rendering path (ADR-0017 Decisions 10-12), a later ticket's
    work. Not in ``__all__`` until that path, ``build_shell`` and its
    siblings land together (ADR-0005 Decision 12's erratum names them as one
    group)."""

    document: ChartDocument
    rows: pa.Table
    theme: Mapping[str, str]
    libraries: Mapping[str, bytes]


@dataclass(frozen=True)
class ChartRecipe:
    """A custom-rail result (ADR-0018 Decision 2): six fields, no ``mode``,
    ``library``, ``runtime_profile`` or annotations.

    ``theme_spec`` is ``str | ThemeSpec | None`` and is never validated against
    the pin (ADR-0018 Decision 3). ``str`` rather than ``ThemePresetName`` so a
    retired preset stays constructable and cannot make a stored recipe
    unbindable."""

    spec_version: str
    transform: Menu | RawSql
    source_schema: dict[str, SourceBucket]
    escape_reason: EscapeReason
    theme_spec: str | ThemeSpec | None
    document: ChartDocument


@dataclass(frozen=True)
class BoundRecipe:
    """A recipe's transform output plus diagnostics. Not paintable and not
    serialisable (ADR-0018 Decision 5): it carries no ``document`` and has no
    ``to_dict``."""

    rows: list[dict[str, Any]]
    theme_spec: str | ThemeSpec | None
    row_count: int
    elapsed: float
    warnings: tuple[Advisory, ...]
    source_schema: dict[str, SourceBucket] | None


def bind_recipe(
    recipe: ChartRecipe,
    data: DataSource,
    *,
    timeout: float | None = None,
    memory_limit: str | None = None,
) -> BoundRecipe:
    """Run the recipe's transform against ``data``. Touches ``transform``,
    ``source_schema`` and ``theme_spec`` only — never the document (Decision 6)."""
    transform = transform_mapping(recipe.transform)
    baseline = dict(recipe.source_schema)
    started = time.perf_counter()
    stage = _run_source_stage(
        data, transform, baseline, timeout=timeout, memory_limit=memory_limit
    )
    rows, serialize = serialize_rows(stage.table, stage.output_types)
    warnings: list[Advisory] = []
    if stage.star:
        warnings.append(
            Advisory(
                code="retype_unchecked",
                message="raw_sql uses STAR; referenced source columns are indefinite",
            )
        )
    else:
        missing = unchecked_source_columns(stage.refs, baseline)
        if missing:
            warnings.append(
                Advisory(
                    code="retype_unchecked",
                    message=(
                        "source_schema baseline is missing entries; "
                        f"columns unchecked: {', '.join(missing)}"
                    ),
                )
            )
    if transform is not None and "raw_sql" in transform:
        warnings.append(
            Advisory(
                code="raw_sql_used",
                message="transform used the raw_sql escape hatch",
            )
        )
    if not rows:
        warnings.append(
            Advisory(code="empty_result", message="transform returned zero rows")
        )
    warnings.extend(serialize)
    return BoundRecipe(
        rows=rows,
        theme_spec=recipe.theme_spec,
        row_count=len(rows),
        elapsed=time.perf_counter() - started,
        warnings=tuple(warnings),
        source_schema=stage.seen_schema,
    )
