"""Step 1's three-member tagged union (ADR-0019 D2, ADR-0020 D3, ADR-0021 D2).

Discriminated on ``outcome`` because most tool-calling schemas do not carry
a bare top-level ``anyOf`` (ADR-0022 Decision 9). Every member is
``extra='forbid'``, so a bucket-2 claim carrying a ``transform`` cannot
decode — ADR-0019 Decision 7's contradiction needs no hand-written check.

A vendor that omits ``outcome`` still decodes when the rest of the dict is
exactly one member: fill the tag before ``model_validate``. The JSON schema
keeps ``outcome`` required — this is a decode-time repair, not a schema
widening.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    GetCoreSchemaHandler,
    GetJsonSchemaHandler,
    ValidationError,
    model_validator,
)
from pydantic_core import CoreSchema, core_schema

from chartagent.frame._generated import ChartType, SemanticTypeName
from chartagent.frame.input import Backend, EncodingObject


def _default_outcome(data: Any, tag: str) -> Any:
    if isinstance(data, dict) and "outcome" not in data:
        return {**data, "outcome": tag}
    return data


class Fragment(BaseModel):
    """Backend-free chart judgement. ``requested_backend`` is extraction only."""

    model_config = ConfigDict(extra="forbid")
    outcome: Literal["fragment"]
    chart_type: ChartType
    encodings: dict[str, EncodingObject]
    transform: dict[str, Any] | None
    semantic_types: dict[str, SemanticTypeName]
    requested_backend: Backend | None

    @model_validator(mode="before")
    @classmethod
    def _fill_omitted_outcome(cls, data: Any) -> Any:
        return _default_outcome(data, "fragment")


class Inexpressible(BaseModel):
    """A well-formed inexpressible verdict.

    ``bucket`` is 1 (no chart type in the 48) or 2 (the transform menu
    cannot express it). Buckets 3 and 4 are scored and gate-written,
    never emitted.
    """

    model_config = ConfigDict(extra="forbid")
    outcome: Literal["inexpressible"]
    bucket: Literal[1, 2]

    @model_validator(mode="before")
    @classmethod
    def _fill_omitted_outcome(cls, data: Any) -> Any:
        return _default_outcome(data, "inexpressible")


class Unanswerable(BaseModel):
    """The instruction makes no sense against the data (ADR-0020 Decision 3).

    ``keys=()`` is the unspecific ask, not a third ``kind``.
    """

    model_config = ConfigDict(extra="forbid")
    outcome: Literal["unanswerable"]
    kind: Literal["missing_column", "missing_role"]
    keys: tuple[str, ...]

    @model_validator(mode="before")
    @classmethod
    def _fill_omitted_outcome(cls, data: Any) -> Any:
        return _default_outcome(data, "unanswerable")


def _fill_missing_outcome(value: Any) -> Any:
    """If ``outcome`` is omitted, fill it when exactly one member validates."""
    if not isinstance(value, dict) or "outcome" in value:
        return value
    matches: list[str] = []
    for model, tag in (
        (Fragment, "fragment"),
        (Inexpressible, "inexpressible"),
        (Unanswerable, "unanswerable"),
    ):
        try:
            model.model_validate(value)
        except ValidationError:
            continue
        matches.append(tag)
    if len(matches) == 1:
        return {**value, "outcome": matches[0]}
    return value


class _FillMissingOutcome:
    """Python-only wrap. JSON schema stays the discriminated ``oneOf``."""

    def __get_pydantic_core_schema__(
        self, source_type: Any, handler: GetCoreSchemaHandler
    ) -> CoreSchema:
        inner = handler(source_type)
        return core_schema.no_info_before_validator_function(
            _fill_missing_outcome, inner
        )

    def __get_pydantic_json_schema__(
        self, schema: CoreSchema, handler: GetJsonSchemaHandler
    ) -> dict[str, Any]:
        return handler(schema)


Step1Result = Annotated[
    Fragment | Inexpressible | Unanswerable,
    Field(discriminator="outcome"),
    _FillMissingOutcome(),
]
