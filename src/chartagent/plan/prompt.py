"""Nonce-fenced planner prompts (ADR-0022). Internal — not in ``__all__``."""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from functools import cache
from importlib.resources import files
from pathlib import Path
from string import Template
from typing import Any

from chartagent.errors import RawSqlRejectedError
from chartagent.frame._generated import CHANNELS, SEMANTIC_TYPES, GeneratedProperties
from chartagent.frame.capability import properties_model
from chartagent.frame.input import Backend
from chartagent.plan.schema import Fragment
from chartagent.profile.models import Profile, untrusted_paths
from chartagent.transform.drift import referenced_source_columns
from chartagent.transform.engine import open_connection
from chartagent.transform.model import EXPR_KINDS, TRANSFORM_SLOTS, transform_mapping
from chartagent.transform.raw_sql import sql_source_refs


@dataclass(frozen=True)
class Step1Prompt:
    system: str
    user: str


@dataclass(frozen=True)
class Step2Prompt:
    system: str
    user: str
    output_type: type[GeneratedProperties]


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
