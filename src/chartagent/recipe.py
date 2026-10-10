"""``ChartRecipe`` and ``bind_recipe`` — the custom rail's stored result (ADR-0018).

A recipe is a sibling to the input frame, not a frame with a flag. ``bind_recipe``
runs the transform, drift-checks and attaches rows; it never reads ``module``,
``styles`` or ``libraries``, so a refresh cannot fail on the code. ``BoundRecipe``
has no wire format: nothing compiles it, and what reaches the browser is
``build_shell``'s output plus the channel payload.
"""

from __future__ import annotations

import json
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

import pyarrow as pa
from pydantic import BaseModel, ConfigDict, StrictInt, StrictStr, ValidationError

from chartagent.bind import DataSource, _run_source_stage
from chartagent.envelope import Advisory
from chartagent.errors import SpecShapeError
from chartagent.frame.input import (
    SourceBucket,
    ThemeSpec,
    _format_field_path,
    _omit_nulls,
)
from chartagent.transform.drift import unchecked_source_columns
from chartagent.transform.model import Menu, RawSql, TransformSpec, transform_mapping
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

    ``bind_recipe`` deliberately returns ``BoundRecipe``, not this
    (ADR-0018 Decision 5) — assembling a ``BoundDocument`` composes
    ``build_shell``'s verified library bytes with rows and theme, which is
    the ``Rasteriser``'s job for a custom-rail chart, a later ticket's work
    (ADR-0017 Decisions 10-12). Exported alongside ``build_shell`` and its
    siblings, as ADR-0005 Decision 12's erratum names them as one group."""

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

    @classmethod
    def from_dict(cls, obj: Mapping[str, Any]) -> ChartRecipe:
        """Validate posted or stored JSON into a recipe (ADR-0018 Decisions 7, 9).

        Raises :class:`SpecShapeError` on any invalid input; the library, not
        Studio, owns the grammar. The inverse of :meth:`to_dict`."""
        if not isinstance(obj, Mapping):
            raise SpecShapeError("recipe must be a JSON object")
        try:
            model = _RecipeModel.model_validate(obj)
        except ValidationError as exc:
            first = exc.errors()[0]
            path = _format_field_path(first["loc"])
            raise SpecShapeError(
                f"invalid recipe: {path}: {first['msg']}"
                if path
                else f"invalid recipe: {first['msg']}"
            ) from exc
        doc = model.document
        return cls(
            spec_version=model.spec_version,
            transform=model.transform,
            source_schema=dict(model.source_schema),
            escape_reason=EscapeReason(bucket=model.escape_reason.bucket),
            theme_spec=model.theme_spec,
            document=ChartDocument(
                module=doc.module,
                styles=doc.styles,
                libraries=tuple(
                    LibraryPin(p.name, p.version, p.sha256) for p in doc.libraries
                ),
                contract_version=doc.contract_version,
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        """A JSON-ready mapping; nulls omitted, empty collections kept."""
        theme: str | dict[str, Any] | None = None
        if isinstance(self.theme_spec, ThemeSpec):
            theme = self.theme_spec.model_dump(mode="json", exclude_none=True)
        else:
            theme = self.theme_spec
        doc = self.document
        out: dict[str, Any] = {
            "spec_version": self.spec_version,
            "source_schema": dict(self.source_schema),
            "escape_reason": {"bucket": self.escape_reason.bucket},
            "theme_spec": theme,
            "document": {
                "module": doc.module,
                "styles": doc.styles,
                "libraries": [
                    {"name": p.name, "version": p.version, "sha256": p.sha256}
                    for p in doc.libraries
                ],
                "contract_version": doc.contract_version,
            },
        }
        result = _omit_nulls(out)
        assert isinstance(result, dict)
        # A ``lit`` node's null is a SQL NULL, not an absence (see
        # ``transform_mapping``), so the transform is not null-stripped.
        result["transform"] = transform_mapping(self.transform)
        return result

    def canonical_json(self) -> str:
        return json.dumps(
            self.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )


class _PinModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: StrictStr
    version: StrictStr
    sha256: StrictStr


class _DocumentModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    module: StrictStr
    styles: StrictStr | None = None
    libraries: list[_PinModel]
    contract_version: StrictInt = _CONTRACT_VERSION


class _EscapeModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bucket: Literal[1, 2, 3, 4]


class _RecipeModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    spec_version: StrictStr
    transform: TransformSpec
    source_schema: dict[str, SourceBucket]
    escape_reason: _EscapeModel
    theme_spec: StrictStr | ThemeSpec | None = None
    document: _DocumentModel


@dataclass(frozen=True)
class BoundRecipe:
    """A recipe's transform output plus diagnostics. Not paintable and not
    serialisable (ADR-0018 Decision 5): it carries no ``document`` and has no
    ``to_dict``. The paintable form is :class:`BoundDocument`, which the
    review composes at paint time."""

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
