"""``generate_recipe`` — the custom rail's document seam (ADR-0030).

Internal — not in ``__all__``, not a factory kwarg. Returns a
``GeneratedRecipe``; the caller assembles the ``ChartRecipe``. A supplied
``transform`` is carried over; ``None`` authors one. Library identity comes
from a private resolver (ADR-0030 Decision 6): every ``LibraryRequest`` is
resolved synchronously before returning, so no unresolved pin ever leaves
this seam. With no resolver, only ``libraries=()`` is legal and a model
naming one fails decode. ``patch_document`` is the repair ask on this
same seam: one call, a full document, and ``PatchDiscarded`` rather than
a raise when the patch cannot be kept.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast

from pydantic import BaseModel, ConfigDict

from chartagent.errors import ChartAgentError
from chartagent.frame._generated import SemanticTypeName
from chartagent.frame.input import SourceBucket
from chartagent.plan.assemble import _source_refs
from chartagent.plan.emit import _EmitFailed, _with_repair
from chartagent.plan.prompt import REPAIRABLE_CHECKS, render_document, render_patch
from chartagent.profile.models import Profile
from chartagent.recipe import ChartDocument, EscapeReason, LibraryPin
from chartagent.transform.model import Menu, RawSql, TransformSpec, transform_mapping

LibraryResolver = Callable[[str, str], tuple[str, bytes]]
"""``(name, version) -> (sha256, bytes)``. The bytes are the caller's in-request
hand-off; they never land on ``ChartDocument``."""

_DECODE_RETRIES = 1


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


class RecipeDraft(BaseModel):
    """The miss path's first-generation decode target: a transform, its
    freshly authored ``semantic_types`` and its document in one ask (ADR-0030
    Decision 5). Values are the closed ``SemanticTypeName`` list, the same
    one step 1 uses. No field carries ``source_schema`` — code computes it
    (Decision 2)."""

    model_config = ConfigDict(extra="forbid")
    transform: TransformSpec
    semantic_types: dict[str, SemanticTypeName]
    document: DocumentDraft


@dataclass(frozen=True)
class GeneratedRecipe:
    """What ``generate_recipe`` hands the caller, who assembles the
    ``ChartRecipe``. ``semantic_types`` stay here; ``ChartRecipe`` does not
    gain a field for them (ADR-0030 Decision 1 erratum)."""

    document: ChartDocument
    transform: Menu | RawSql
    semantic_types: Mapping[str, SemanticTypeName]
    source_schema: dict[str, SourceBucket]


class DocumentGenerationFailed(Exception):
    """The decode-retry budget is spent. What to do about it is the caller's."""


class LibraryResolutionFailed(DocumentGenerationFailed):
    """The resolver raised. Terminal with no second model ask (ADR-0030 Decision 8)."""


@dataclass(frozen=True)
class PatchDiscarded:
    """The patch was not applied. The caller keeps best-so-far.

    Not a raise, and not the first-generation terminal ending. A malformed
    patch, a resolver failure, ``injection_pattern`` in the failing set, or
    a failing set with nothing repairable all end here. The first two follow
    one ask and no retry; the last two make no call."""


def generate_recipe(
    profile: Profile,
    instruction: str,
    escape_reason: EscapeReason,
    *,
    transform: Menu | RawSql | None,
    semantic_types: Mapping[str, SemanticTypeName] | None = None,
    resolver: LibraryResolver | None = None,
    invoke: Any,
) -> GeneratedRecipe:
    """First-generation document. A supplied ``transform`` is carried over
    verbatim and never re-asked; ``None`` means author it, in the same single
    ask (``RecipeDraft``). The authoring ask's first call goes out with
    ``counted=False``: it replaces a raise, so it is off the planner's 5-call
    cap (ADR-0030 Decision 9). Its retry is counted."""
    authoring = transform is None
    repair: _EmitFailed | None = None
    for attempt in range(_DECODE_RETRIES + 1):
        prompt = _with_repair(
            render_document(
                profile,
                instruction,
                escape_reason,
                semantic_types,
                resolver_set=resolver is not None,
                author_transform=authoring,
            ),
            repair,
        )
        try:
            draft, _ask = invoke(
                prompt.output_type,
                prompt,
                counted=not (authoring and attempt == 0),
            )
            document = draft.document if authoring else draft
            if document.libraries and resolver is None:
                raise _EmitFailed(
                    "invalid_emit",
                    rejected=draft.model_dump(mode="json", exclude_none=True),
                    checker="only libraries=() is legal this run",
                )
            chosen = (
                draft.transform
                if isinstance(draft, RecipeDraft)
                else cast(Menu | RawSql, transform)
            )
            source_schema = _check_transform(chosen, profile, draft, authored=authoring)
        except _EmitFailed as exc:
            repair = exc
            continue
        return GeneratedRecipe(
            document=ChartDocument(
                module=document.module,
                styles=document.styles,
                libraries=_resolve(document.libraries, resolver),
            ),
            transform=chosen,
            semantic_types=(
                draft.semantic_types
                if isinstance(draft, RecipeDraft)
                else dict(semantic_types or {})
            ),
            source_schema=source_schema,
        )
    raise DocumentGenerationFailed("document did not decode within its retry budget")


def patch_document(
    profile: Profile,
    instruction: str,
    document: ChartDocument,
    failures: Sequence[str],
    *,
    semantic_types: Mapping[str, SemanticTypeName] | None = None,
    resolver: LibraryResolver | None = None,
    invoke: Any,
) -> ChartDocument | PatchDiscarded:
    """One repair ask (ADR-0030 Decisions 11–14). The model rewrites the
    whole document; libraries it names are resolved the same way as a first
    generation. Off the planner's call cap — review-repair budget is the
    caller's to spend. Returns :class:`PatchDiscarded` instead of raising."""
    if "injection_pattern" in failures:
        return PatchDiscarded()
    failing = set(failures)
    names = tuple(name for name in REPAIRABLE_CHECKS if name in failing)
    if not names:
        return PatchDiscarded()
    prompt = render_patch(
        profile,
        instruction,
        document,
        names,
        semantic_types=semantic_types,
        resolver_set=resolver is not None,
    )
    try:
        draft, _ask = invoke(prompt.output_type, prompt, counted=False)
    except _EmitFailed:
        return PatchDiscarded()
    try:
        libraries = _resolve(draft.libraries, resolver)
    except DocumentGenerationFailed:
        return PatchDiscarded()
    return ChartDocument(
        module=draft.module,
        styles=draft.styles,
        libraries=libraries,
    )


def _check_transform(
    transform: Menu | RawSql,
    profile: Profile,
    draft: DocumentDraft | RecipeDraft,
    *,
    authored: bool,
) -> dict[str, SourceBucket]:
    """``source_schema``, always code's. An authored transform also goes
    through the existing machinery as a decode check: a raw_sql lock rejection
    or a column the source lacks counts against the retry."""
    rejected = draft.model_dump(mode="json", exclude_none=True)
    try:
        refs = _source_refs(transform_mapping(transform))
    except ChartAgentError as exc:
        if not authored:
            raise
        raise _EmitFailed("invalid_emit", rejected=rejected, checker=str(exc)) from exc
    buckets = {column.name: column.bucket for column in profile.columns}
    unknown = sorted(refs - buckets.keys())
    if unknown and authored:
        raise _EmitFailed(
            "invalid_emit",
            rejected=rejected,
            checker=f"transform references columns the source does not have: {unknown}",
        )
    return {name: buckets[name] for name in sorted(refs) if name in buckets}


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
