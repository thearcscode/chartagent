"""The model client. pydantic-ai is imported here, inside the constructor.

One call: an output type, a system prompt, a user turn. The client's
retry budget is zero — ADR-0013 Decision 6's mean-calls-per-chart and
ADR-0019 Decision 6's per-step retry rate are only honest if one layer
counts, and that layer is not this one.

Transport, auth, and model-string errors propagate un-wrapped. They are
not :class:`~chartagent.errors.ChartAgentError` subclasses, so
``except ChartAgentError`` does not catch them.
"""

from __future__ import annotations

import json
from typing import Any, TypeVar, cast

from chartagent.errors import ModelClientUnavailableError

PRODUCT_DECODING: dict[str, float] = {"temperature": 0}

_SHIPPED_EXTRAS = frozenset({"anthropic", "openai"})
_CLIENT_RETRIES = 0

T = TypeVar("T")


def _extra_to_install(model: str) -> str:
    provider = model.split(":", 1)[0]
    if provider in _SHIPPED_EXTRAS:
        return f"chartagent[{provider}]"
    return f"pydantic-ai-slim[{provider}]"


def _unavailable(extra: str) -> ModelClientUnavailableError:
    return ModelClientUnavailableError(
        f"model client extra {extra} is not installed",
        extra=extra,
    )


class ModelClient:
    """One structured model call. Retry is zero; the caller counts.

    A missing extra raises :class:`ModelClientUnavailableError` here at
    construction, not at first use. Transport, auth, and model-string
    errors propagate un-wrapped — ``except ChartAgentError`` does not
    catch them.
    """

    def __init__(self, model: str) -> None:
        extra = _extra_to_install(model)
        try:
            from pydantic_ai import Agent
        except ModuleNotFoundError as exc:
            raise _unavailable(extra) from exc
        settings = cast(Any, dict(PRODUCT_DECODING))
        try:
            Agent(model, retries=_CLIENT_RETRIES, model_settings=settings)
        except ImportError as exc:
            raise _unavailable(extra) from exc
        self._model = model
        self._Agent = Agent
        self._settings = settings

    def run(self, output_type: type[T], system_prompt: str, user_turn: str) -> T:
        from pydantic_ai import capture_run_messages

        agent = self._Agent(
            self._model,
            output_type=output_type,
            system_prompt=system_prompt,
            retries=_CLIENT_RETRIES,
            model_settings=self._settings,
        )
        with capture_run_messages() as messages:
            try:
                result = agent.run_sync(user_turn, retries=_CLIENT_RETRIES)
            except Exception as exc:
                rejected = _rejected_emit(messages)
                if rejected is not None:
                    try:
                        setattr(exc, "rejected_emit", rejected)
                    except (AttributeError, TypeError):
                        pass
                raise
        return result.output


def _rejected_emit(messages: list[Any]) -> Any:
    from pydantic_ai.messages import ModelResponse, ToolCallPart

    for message in reversed(messages):
        if not isinstance(message, ModelResponse):
            continue
        for part in reversed(message.parts):
            if not isinstance(part, ToolCallPart):
                continue
            args: Any = part.args
            if isinstance(args, str):
                try:
                    return json.loads(args)
                except json.JSONDecodeError:
                    return args
            return args
    return None
