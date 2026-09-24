"""``generate_recipe`` — the custom rail's document seam (ADR-0030).

Internal — not in ``__all__``, not a factory kwarg. First-generation only,
for a supplied ``transform``. Library identity comes from a private resolver
(ADR-0030 Decision 6): every ``LibraryRequest`` is resolved synchronously
before returning, so no unresolved pin ever leaves this seam. With no
resolver, only ``libraries=()`` is legal and a model naming one fails decode.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from chartagent.plan.emit import _EmitFailed, _with_repair
from chartagent.plan.prompt import render_document
from chartagent.profile.models import Profile
from chartagent.transform.model import Menu, RawSql

LibraryResolver = Callable[[str, str], tuple[str, bytes]]
"""``(name, version) -> (sha256, bytes)``. The bytes are the caller's in-request
hand-off; they never land on ``ChartDocument``."""

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


class DocumentGenerationFailed(Exception):
    """The decode-retry budget is spent. What to do about it is the caller's."""


class LibraryResolutionFailed(DocumentGenerationFailed):
    """The resolver raised. Terminal with no second model ask (ADR-0030 Decision 8)."""


def generate_recipe(
    profile: Profile,
    instruction: str,
    escape_reason: EscapeReason,
    *,
    transform: Menu | RawSql | None,
    semantic_types: Mapping[str, str],
    resolver: LibraryResolver | None = None,
    invoke: Any,
) -> ChartDocument:
    """First-generation document. A supplied ``transform`` is carried over
    verbatim by the caller and never re-asked here."""
    if transform is None:
        raise NotImplementedError("authoring a transform is not built yet")
    repair: _EmitFailed | None = None
    for _ in range(_DECODE_RETRIES + 1):
        prompt = _with_repair(
            render_document(
                profile,
                instruction,
                escape_reason,
                semantic_types,
                resolver_set=resolver is not None,
            ),
            repair,
        )
        try:
            draft, _ask = invoke(prompt.output_type, prompt)
            if draft.libraries and resolver is None:
                raise _EmitFailed(
                    "invalid_emit",
                    rejected=draft.model_dump(mode="json", exclude_none=True),
                    checker="only libraries=() is legal this run",
                )
        except _EmitFailed as exc:
            repair = exc
            continue
        return ChartDocument(
            module=draft.module,
            styles=draft.styles,
            libraries=_resolve(draft.libraries, resolver),
        )
    raise DocumentGenerationFailed("document did not decode within its retry budget")


def _resolve(
    requests: tuple[LibraryRequest, ...], resolver: LibraryResolver | None
) -> tuple[LibraryPin, ...]:
    if not requests:
        return ()
    if resolver is None:
        raise DocumentGenerationFailed("libraries named with no resolver set")
    pins: list[LibraryPin] = []
    for request in requests:
        try:
            sha256, _bytes = resolver(request.name, request.version)
        except Exception as exc:
            raise LibraryResolutionFailed(
                f"could not resolve {request.name}@{request.version}"
            ) from exc
        pins.append(LibraryPin(request.name, request.version, sha256))
    return tuple(pins)
