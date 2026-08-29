"""The envelope — ADR-0001 Decision 5, ADR-0005 Decision 5.

The wire format is exactly three keys: ``flint_version``, ``backend``,
``input``. Diagnostics ride on the object and never serialise.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from chartagent.frame.input import Backend, SourceBucket


@dataclass(frozen=True)
class Advisory:
    """A frozen ``{code, message}`` the caller has to render."""

    code: str
    message: str


class Envelope(BaseModel):
    """Bound frame plus diagnostics that stay off the wire."""

    model_config = ConfigDict(extra="forbid")

    flint_version: str
    backend: Backend
    input: dict[str, Any]

    row_count: int = Field(exclude=True)
    elapsed: float = Field(exclude=True)
    warnings: tuple[Advisory, ...] = Field(exclude=True)
    source_schema: dict[str, SourceBucket] = Field(exclude=True)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()
