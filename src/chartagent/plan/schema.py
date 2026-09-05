"""Step 1's three-member tagged union (ADR-0019 D2, ADR-0020 D3, ADR-0021 D2).

Discriminated on ``outcome`` because most tool-calling schemas do not carry
a bare top-level ``anyOf`` (ADR-0022 Decision 9). Every member is
``extra='forbid'``, so a bucket-2 claim carrying a ``transform`` cannot
decode — ADR-0019 Decision 7's contradiction needs no hand-written check.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from chartagent.frame._generated import ChartType, SemanticTypeName
from chartagent.frame.input import Backend, EncodingObject


class Fragment(BaseModel):
    """Backend-free chart judgement. ``requested_backend`` is extraction only."""

    model_config = ConfigDict(extra="forbid")
    outcome: Literal["fragment"]
    chart_type: ChartType
    encodings: dict[str, EncodingObject]
    transform: dict[str, Any] | None
    semantic_types: dict[str, SemanticTypeName]
    requested_backend: Backend | None


class Inexpressible(BaseModel):
    """A well-formed inexpressible verdict.

    ``bucket`` is 1 (no chart type in the 48) or 2 (the transform menu
    cannot express it). Buckets 3 and 4 are scored and gate-written,
    never emitted.
    """

    model_config = ConfigDict(extra="forbid")
    outcome: Literal["inexpressible"]
    bucket: Literal[1, 2]


class Unanswerable(BaseModel):
    """The instruction makes no sense against the data (ADR-0020 Decision 3).

    ``keys=()`` is the unspecific ask, not a third ``kind``.
    """

    model_config = ConfigDict(extra="forbid")
    outcome: Literal["unanswerable"]
    kind: Literal["missing_column", "missing_role"]
    keys: tuple[str, ...]


Step1Result = Annotated[
    Fragment | Inexpressible | Unanswerable, Field(discriminator="outcome")
]
