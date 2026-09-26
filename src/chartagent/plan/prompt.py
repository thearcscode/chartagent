"""Nonce-fenced planner prompts (ADR-0022). Internal — not in ``__all__``."""

from __future__ import annotations

import json
import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from functools import cache
from importlib.resources import files
from pathlib import Path
from string import Template
from typing import TYPE_CHECKING, Any

from chartagent.errors import RawSqlRejectedError
from chartagent.frame._generated import (
    CHANNELS,
    SEMANTIC_TYPES,
    GeneratedProperties,
    SemanticTypeName,
)
from chartagent.frame.capability import properties_model
from chartagent.frame.input import Backend
from chartagent.plan.schema import Fragment
from chartagent.profile.models import Profile, untrusted_paths
from chartagent.transform.drift import referenced_source_columns
from chartagent.transform.engine import open_connection
from chartagent.transform.model import EXPR_KINDS, TRANSFORM_SLOTS, transform_mapping
from chartagent.transform.raw_sql import sql_source_refs

if TYPE_CHECKING:
    from chartagent.plan.recipe import DocumentDraft, RecipeDraft
    from chartagent.recipe import EscapeReason


@dataclass(frozen=True)
class Step1Prompt:
    system: str
    user: str


@dataclass(frozen=True)
class Step2Prompt:
    system: str
    user: str
    output_type: type[GeneratedProperties]


@dataclass(frozen=True)
class DocumentPrompt:
    system: str
    user: str
    output_type: type[DocumentDraft] | type[RecipeDraft]


def _read_template(name: str) -> str:
    return (
        files("chartagent.plan").joinpath("prompts", name).read_text(encoding="utf-8")
    )


_VOCAB_PATH = Path(__file__).resolve().parents[1] / "frame" / "vocab.json"


def _chart_types() -> tuple[str, ...]:
    raw = json.loads(_VOCAB_PATH.read_text(encoding="utf-8"))
    backends = raw["backends"]
    names: set[str] = set()
    if isinstance(backends, dict):
        for charts in backends.values():
            if isinstance(charts, dict):
                names.update(str(name) for name in charts)
    return tuple(sorted(names))


@cache
def _step1_system() -> str:
    return Template(_read_template("step1.system.md")).substitute(
        CHART_TYPES=", ".join(_chart_types()),
        CHANNELS=", ".join(CHANNELS),
        SEMANTIC_TYPES=", ".join(SEMANTIC_TYPES),
        TRANSFORM_SLOTS=", ".join(TRANSFORM_SLOTS),
        EXPR_KINDS=", ".join(sorted(EXPR_KINDS)),
        UNTRUSTED_PATHS=", ".join(untrusted_paths()),
    )


@cache
def _step2_system() -> str:
    return Template(_read_template("step2.system.md")).substitute(
        UNTRUSTED_PATHS=", ".join(untrusted_paths()),
    )


def _nonce(nonce: str | None) -> str:
    return nonce if nonce is not None else secrets.token_hex(8)


def _dump(payload: dict[str, Any]) -> str:
    return json.dumps(payload, separators=(",", ":"))


def _fence(nonce: str, payload: dict[str, Any]) -> str:
    return f"<data_profile_{nonce}>\n{_dump(payload)}\n</data_profile_{nonce}>"


def _source_scope(transform: dict[str, Any] | None) -> frozenset[str] | None:
    """Referenced source columns, or ``None`` when the full remaining set is sent."""
    if transform is not None and "raw_sql" in transform:
        sql = transform.get("raw_sql")
        if not isinstance(sql, str):
            return None
        connection = open_connection()
        try:
            parsed = sql_source_refs(connection, sql)
        except RawSqlRejectedError:
            return None
        finally:
            connection.close()
        return parsed
    refs = referenced_source_columns(transform)
    return refs or None


def _scoped_payload(
    profile: Profile, transform: dict[str, Any] | None
) -> dict[str, Any]:
    payload = profile.model_dump(exclude_none=True)
    payload.pop("sample_rows", None)
    scope = _source_scope(transform)
    if scope:
        payload["columns"] = [
            column for column in payload["columns"] if column["name"] in scope
        ]
    return payload


def _user_turn(nonce: str, payload: dict[str, Any], instruction: str) -> str:
    return f"{_fence(nonce, payload)}\n\nInstruction: {instruction}"


def render_step1(
    profile: Profile,
    instruction: str,
    *,
    nonce: str | None = None,
) -> Step1Prompt:
    nonce_value = _nonce(nonce)
    payload = profile.model_dump(exclude_none=True)
    return Step1Prompt(
        system=_step1_system(),
        user=_user_turn(nonce_value, payload, instruction),
    )


def render_step2(
    profile: Profile,
    fragment: Fragment,
    instruction: str,
    backend: Backend,
    *,
    nonce: str | None = None,
) -> Step2Prompt:
    nonce_value = _nonce(nonce)
    fragment_json = _dump(fragment.model_dump(mode="json", exclude_none=True))
    scoped = _user_turn(
        nonce_value,
        _scoped_payload(profile, transform_mapping(fragment.transform)),
        instruction,
    )
    return Step2Prompt(
        system=_step2_system(),
        user=f"{fragment_json}\n\n{scoped}",
        output_type=properties_model(backend, fragment.chart_type),
    )


_LIBRARY_RULE = (
    "Only `libraries=()` is legal this run: write the module from scratch, "
    "with no library, and emit `libraries` as an empty list."
)

_LIBRARY_RULE_RESOLVER = (
    "You may either write the module from scratch and emit `libraries` as an "
    "empty list (`libraries=()`), or name packages. To name a package, add "
    '`{"name": ..., "version": ...}` to `libraries` with an exact version; '
    "the host resolves and pins each one, and loads them in the order you list "
    "them, before your module runs. Name a package only when it earns its weight."
)

_ESCAPE_CONTEXT = {
    1: "Why this document exists: the request named a chart type that "
    "the deterministic rail does not have (bucket 1).",
    2: "Why this document exists: the deterministic rail's transform menu "
    "cannot express the request (bucket 2).",
    3: "Why this document exists: the request was expressible on the "
    "deterministic rail but was escaped anyway (bucket 3).",
    4: "Why this document exists: the deterministic rail painted the "
    "chart's chrome (axes, titles, legend) but its marks did not paint "
    "(bucket 4).",
}


_EMIT_DOCUMENT = (
    "Emit a JSON object with `module` (JavaScript source), `styles` (CSS source, "
    "or null when you write none) and `libraries`."
)

_EMIT_RECIPE = (
    "Emit a JSON object with three keys: `transform`, `semantic_types` and "
    "`document`. `semantic_types` maps each output column to one name from the "
    "closed list in the transform section. `document` is a JSON object with "
    "`module` (JavaScript source), `styles` (CSS source, or null when you write "
    "none) and `libraries`."
)

_RAW_SQL_FRAMING = (
    "This request already failed the eight-slot menu, so the menu cannot state "
    "its shape. `raw_sql` is the escape valve for exactly that: expect to use "
    "`raw_sql` for the transform rather than straining the slots a second time."
)


@cache
def _transform_section(bucket: int | None) -> str:
    if bucket is None:
        return ""
    section = Template(_read_template("transform.section.md")).substitute(
        SLOTS=", ".join(TRANSFORM_SLOTS),
        EXPR_KINDS=", ".join(sorted(EXPR_KINDS)),
        SEMANTIC_TYPES=", ".join(SEMANTIC_TYPES),
    )
    return f"{section}\n{_RAW_SQL_FRAMING}\n" if bucket == 2 else section


@cache
def _document_system(resolver_set: bool, author_bucket: int | None) -> str:
    return Template(_read_template("document.system.md")).substitute(
        EMIT_SHAPE=_EMIT_DOCUMENT if author_bucket is None else _EMIT_RECIPE,
        TRANSFORM_SECTION=_transform_section(author_bucket),
        LIBRARY_RULE=_LIBRARY_RULE_RESOLVER if resolver_set else _LIBRARY_RULE,
        UNTRUSTED_PATHS=", ".join(untrusted_paths()),
    )


def render_document(
    profile: Profile,
    instruction: str,
    escape_reason: EscapeReason,
    semantic_types: Mapping[str, SemanticTypeName] | None,
    *,
    resolver_set: bool = False,
    author_transform: bool = False,
    nonce: str | None = None,
) -> DocumentPrompt:
    """First-generation document prompt. Column names and ``semantic_types``
    only — never ``sample_rows`` or any cell value (ADR-0030 Decision 4).
    ``author_transform`` widens the emit to a ``RecipeDraft`` (the miss path);
    bucket 2 alone gets the ``raw_sql`` framing (Decision 3)."""
    from chartagent.plan.recipe import DocumentDraft, RecipeDraft

    payload: dict[str, Any] = {"columns": [column.name for column in profile.columns]}
    if not author_transform:
        payload["semantic_types"] = dict(semantic_types or {})
    author_bucket = escape_reason.bucket if author_transform else None
    user = "\n\n".join(
        (
            _ESCAPE_CONTEXT[escape_reason.bucket],
            _user_turn(_nonce(nonce), payload, instruction),
        )
    )
    return DocumentPrompt(
        system=_document_system(resolver_set, author_bucket),
        user=user,
        output_type=RecipeDraft if author_transform else DocumentDraft,
    )
