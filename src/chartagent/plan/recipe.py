"""``generate_recipe`` — the custom rail's document seam (ADR-0030).

Internal — not in ``__all__``, not a factory kwarg. This tracer is
first-generation only, for a supplied ``transform`` and ``libraries=()``:
no resolver exists yet, so a model that names a library fails decode.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, field_validator

from chartagent.plan.emit import _EmitFailed, _with_repair
from chartagent.plan.prompt import render_document
from chartagent.profile.models import Profile
from chartagent.transform.model import Menu, RawSql

_DECODE_RETRIES = 1
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


class LibraryRequest(BaseModel):
    """The model's request for a library. It never decodes into ``LibraryPin``."""

    model_config = ConfigDict(extra="forbid")
    name: str
    version: str


class DocumentDraft(BaseModel):
    """The model's decode target for a document (ADR-0030 Decision 5)."""

    model_config = ConfigDict(extra="forbid")
    module: str
    styles: str | None = None
    libraries: tuple[LibraryRequest, ...] = ()

    @field_validator("libraries")
    @classmethod
    def _from_scratch_only(
        cls, value: tuple[LibraryRequest, ...]
    ) -> tuple[LibraryRequest, ...]:
        if value:
            raise ValueError("only libraries=() is legal this run")
        return value


class DocumentGenerationFailed(Exception):
    """The decode-retry budget is spent. What to do about it is the caller's."""


def generate_recipe(
    profile: Profile,
    instruction: str,
    escape_reason: EscapeReason,
    *,
    transform: Menu | RawSql | None,
    semantic_types: Mapping[str, str],
    invoke: Any,
) -> ChartDocument:
    """First-generation document. A supplied ``transform`` is carried over
    verbatim by the caller and never re-asked here."""
    if transform is None:
        raise NotImplementedError("authoring a transform is not built yet")
    repair: _EmitFailed | None = None
    for _ in range(_DECODE_RETRIES + 1):
        prompt = _with_repair(
            render_document(profile, instruction, escape_reason, semantic_types),
            repair,
        )
        try:
            draft, _ask = invoke(prompt.output_type, prompt)
        except _EmitFailed as exc:
            repair = exc
            continue
        return ChartDocument(module=draft.module, styles=draft.styles, libraries=())
    raise DocumentGenerationFailed("document did not decode within its retry budget")
