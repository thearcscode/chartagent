"""The public planner entry point (ADR-0019/0020/0021/0022).

``create_chart_agent`` and ``ChartAgent`` are the only two names that
leave ``plan/``. Budgets are counted here and nowhere else: 1 retry at
step 1, 2 at step 2, a hard cap of 5 calls. A well-formed inexpressible
or unanswerable verdict is an answer, never a retry.
"""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any, Literal, TypeVar, cast

from chartagent.bind import DataSource, bind
from chartagent.errors import (
    ChartAgentError,
    InexpressibleRequestError,
    PlannerFailureError,
    RawSqlRejectedError,
    SchemaDriftError,
    SpecShapeError,
    SpecVocabularyError,
    UnanswerableInstructionError,
)
from chartagent.frame.input import Backend
from chartagent.plan.assemble import assemble
from chartagent.plan.client import ModelClient
from chartagent.plan.prompt import Step1Prompt, Step2Prompt, render_step1, render_step2
from chartagent.plan.schema import Fragment, Inexpressible, Step1Result, Unanswerable
from chartagent.plan.select import select_backend
from chartagent.profile.models import Profile
from chartagent.profile.source import profile_source
from chartagent.result import ChartResult

_STEP1_RETRIES = 1
_STEP2_RETRIES = 2
_CALL_CAP = 5

_Prompt = TypeVar("_Prompt", Step1Prompt, Step2Prompt)


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
    return replace(
        prompt, user=_repair_user(prompt.user, repair.rejected, repair.checker)
    )


def _dump_emit(value: Any) -> Any:
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        return dump(mode="json", exclude_none=True)
    return value


def _checker_message(exc: BaseException) -> str:
    for item in _walk_exceptions(exc):
        if type(item).__name__ in {"ValidationError", "ToolRetryError"}:
            return str(item)
    return str(exc)


def create_chart_agent(*, model: str) -> ChartAgent:
    """Factory. Raises at construction if the model-vendor extra is missing."""
    return ChartAgent(model=model)


class ChartAgent:
    """Holds the model string and one client. No per-request mutable state."""

    def __init__(self, *, model: str) -> None:
        self._model = model
        self._client = ModelClient(model)

    def create_chart(self, data: DataSource, instruction: str) -> ChartResult:
        profile = profile_source(data)
        calls = 0

        def invoke(output_type: Any, prompt: Step1Prompt | Step2Prompt) -> Any:
            nonlocal calls
            if calls >= _CALL_CAP:
                raise PlannerFailureError(
                    "planner call cap reached",
                    reason="retries_exhausted",
                )
            calls += 1
            try:
                return self._client.run(
                    cast(type[Any], output_type), prompt.system, prompt.user
                )
            except ChartAgentError:
                raise
            except Exception as exc:
                reason = _call_failure_reason(exc)
                if reason is None:
                    raise
                raise _EmitFailed(
                    reason,
                    rejected=getattr(exc, "rejected_emit", None),
                    checker=(_checker_message(exc) if reason == "invalid_emit" else ""),
                ) from exc

        last: Literal["empty_response", "invalid_emit"] | None = None
        repair: _EmitFailed | None = None
        for _ in range(_STEP1_RETRIES + 1):
            try:
                fragment = _step1_attempt(profile, instruction, invoke, repair)
            except _EmitFailed as exc:
                last = exc.reason
                repair = exc
                continue
            backend = select_backend(
                fragment.chart_type,
                fragment.encodings,
                requested_backend=fragment.requested_backend,
            )
            properties = _step2(profile, fragment, instruction, backend, invoke)
            try:
                frame = assemble(fragment, profile, chart_properties=properties)
                envelope = bind(frame, data, backend=backend)
            except (SpecShapeError, SchemaDriftError) as exc:
                # A step-1-shaped fragment can still fail deeper than
                # assemble() checks (bind-time compile) or against columns
                # the source doesn't have (#137). Either way the planner
                # emitted something unusable — never let the bind-time
                # exception type leak past create_chart.
                # ChartResult.refresh calls bind() directly and is not this
                # seam: a real drift on new rows must stay SchemaDriftError
                # there. #140: this wrap is a step-1 repair.
                last = "invalid_emit"
                repair = _EmitFailed(
                    "invalid_emit",
                    rejected={
                        "fragment": fragment.model_dump(mode="json", exclude_none=True),
                        "chartProperties": properties,
                    },
                    checker=str(exc),
                )
                continue
            return ChartResult(envelope=envelope)
        raise PlannerFailureError(
            "step 1 did not emit a usable fragment",
            reason=last or "invalid_emit",
        )


def _step1_attempt(
    profile: Profile,
    instruction: str,
    invoke: Any,
    repair: _EmitFailed | None,
) -> Fragment:
    prompt = _with_repair(render_step1(profile, instruction), repair)
    result = invoke(Step1Result, prompt)
    if isinstance(result, Inexpressible):
        raise InexpressibleRequestError(
            f"request is inexpressible (bucket {result.bucket})",
            bucket=result.bucket,
        )
    if isinstance(result, Unanswerable):
        if _claim_refuted(result, profile):
            raise _EmitFailed(
                "invalid_emit",
                rejected=result.model_dump(mode="json", exclude_none=True),
                checker=(
                    f"unanswerable {result.kind} is refuted: "
                    f"keys {result.keys!r} are in the profile"
                ),
            )
        raise UnanswerableInstructionError(
            f"instruction is unanswerable ({result.kind})",
            kind=result.kind,
            keys=result.keys,
        )
    if not isinstance(result, Fragment):
        raise _EmitFailed(
            "invalid_emit",
            rejected=_dump_emit(result),
            checker="step 1 did not return a fragment",
        )
    try:
        assemble(result, profile)
    except (SpecShapeError, SpecVocabularyError, RawSqlRejectedError) as exc:
        raise _EmitFailed(
            "invalid_emit",
            rejected=result.model_dump(mode="json", exclude_none=True),
            checker=str(exc),
        ) from exc
    return result


def _step2(
    profile: Profile,
    fragment: Fragment,
    instruction: str,
    backend: Backend,
    invoke: Any,
) -> dict[str, Any]:
    last: Literal["empty_response", "invalid_emit"] | None = None
    repair: _EmitFailed | None = None
    for _ in range(_STEP2_RETRIES + 1):
        prompt = _with_repair(
            render_step2(profile, fragment, instruction, backend), repair
        )
        try:
            result = invoke(prompt.output_type, prompt)
        except _EmitFailed as exc:
            last = exc.reason
            repair = exc
            continue
        dumped = result.model_dump(exclude_unset=True, exclude_none=True)
        if not isinstance(dumped, dict):
            last = "invalid_emit"
            repair = _EmitFailed(
                "invalid_emit",
                rejected=_dump_emit(result),
                checker="step 2 did not return chartProperties",
            )
            continue
        return dumped
    raise PlannerFailureError(
        "step 2 did not emit usable chartProperties",
        reason=last or "invalid_emit",
    )


def _claim_refuted(verdict: Unanswerable, profile: Profile) -> bool:
    if not verdict.keys:
        return False
    if verdict.kind == "missing_column":
        names = {column.name for column in profile.columns}
        return any(key in names for key in verdict.keys)
    supplied = {column.bucket for column in profile.columns}
    return any(key in supplied for key in verdict.keys)


def _call_failure_reason(
    exc: BaseException,
) -> Literal["empty_response", "invalid_emit"] | None:
    names = {type(item).__name__ for item in _walk_exceptions(exc)}
    if "ValidationError" in names:
        return "invalid_emit"
    if "ToolRetryError" in names:
        return "empty_response"
    if "UnexpectedModelBehavior" in names:
        return "invalid_emit"
    return None


def _walk_exceptions(exc: BaseException | None) -> list[BaseException]:
    found: list[BaseException] = []
    seen: set[int] = set()

    def walk(current: BaseException | None) -> None:
        if current is None:
            return
        ident = id(current)
        if ident in seen:
            return
        seen.add(ident)
        found.append(current)
        if isinstance(current, BaseExceptionGroup):
            for inner in current.exceptions:
                walk(inner)
        walk(current.__cause__)
        walk(current.__context__)

    walk(exc)
    return found
