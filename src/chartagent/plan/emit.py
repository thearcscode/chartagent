"""Decode-failure carrier and repair-turn rendering, shared by every planner call.

Internal — not in ``__all__``.
"""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any, Literal, Protocol, TypeVar, cast


class _HasUser(Protocol):
    @property
    def user(self) -> str: ...


_Prompt = TypeVar("_Prompt", bound=_HasUser)


class _EmitFailed(Exception):
    """The model returned nothing, or output that failed a step check."""

    def __init__(
        self,
        reason: Literal["empty_response", "invalid_emit"],
        *,
        rejected: Any = None,
        checker: str = "",
    ) -> None:
        super().__init__(reason)
        self.reason = reason
        self.rejected = rejected
        self.checker = checker


def _repair_user(user: str, rejected: Any, checker: str) -> str:
    parts = [user]
    if rejected is not None:
        parts.append(
            "Rejected emit:\n"
            + json.dumps(rejected, separators=(",", ":"), default=str)
        )
    if checker:
        parts.append(f"Checker:\n{checker}")
    return "\n\n".join(parts)


def _with_repair(prompt: _Prompt, repair: _EmitFailed | None) -> _Prompt:
    if repair is None or (repair.rejected is None and not repair.checker):
        return prompt
    return cast(
        _Prompt,
        replace(
            cast(Any, prompt),
            user=_repair_user(prompt.user, repair.rejected, repair.checker),
        ),
    )
