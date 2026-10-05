"""The public planner entry point (ADR-0019/0020/0021/0022).

``create_chart_agent`` and ``ChartAgent`` are the only two names that
leave ``plan/``. Budgets are counted here and nowhere else: 1 retry at
step 1, 2 at step 2, a hard cap of 5 calls. A well-formed inexpressible
or unanswerable verdict is an answer, never a retry.

``Attempt`` / ``AttemptObserver`` (ADR-0023 Decision 8, issue #144) are an
internal seam, not public surface: ``assemble`` and refuted-unanswerable
failures happen in here, not in ``ModelClient``, so a caller that wants a
per-ask journal (the corpus recorder) installs an observer at
``ChartAgent._attempt_observer`` — the same private-seam convention as
``agent._client``. Left unset, behaviour is unchanged.
``ChartAgent._library_resolver`` (ADR-0030 Decision 6) follows the same
convention: unset by default, not in ``__all__``, not a factory kwarg.
``ChartAgent._reviewer`` (ADR-0027 Decision 6, issue #192) is the review seam
the hop reads. It runs ``flint_review`` (#201): Tier 1, then — only when
both ``rasteriser=`` and ``critique_model=`` were supplied at construction —
a Flint critique that can actually fail ``marks_present`` and wake the hop.
Neither kwarg has a default; unset, Tier 2 stays ``unavailable`` and the hop
stays dormant, exactly as before #201.
``ChartAgent._recipe_reviewer`` (issue #226) is the same seam for a custom-rail
recipe: ``(profile, recipe, instruction) -> ReviewReport``. Its default is
Tier 1 only, so a recipe is never repaired in production until real
custom-rail scoring replaces it.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from typing import Any, Literal, cast, get_args

from chartagent.bind import DataSource, bind
from chartagent.envelope import Envelope
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
from chartagent.frame._generated import SemanticTypeName
from chartagent.frame.input import Backend, InputFrame
from chartagent.plan.assemble import _SPEC_VERSION, assemble
from chartagent.plan.client import ModelClient
from chartagent.plan.emit import _EmitFailed, _with_repair
from chartagent.plan.escalate import (
    _REVIEW_REPAIRS,
    EscalationDecision,
    Quality,
    decide_escalation,
)
from chartagent.plan.prompt import (
    FLINT_REPAIRABLE_CHECKS,
    DocumentPrompt,
    Step1Prompt,
    Step2Prompt,
    render_review_repair,
    render_step1,
    render_step2,
)
from chartagent.plan.recipe import (
    DocumentGenerationFailed,
    LibraryResolver,
    PatchDiscarded,
    generate_recipe,
    patch_document,
)
from chartagent.plan.repair import spend_repair_budget
from chartagent.plan.schema import Fragment, Inexpressible, Step1Result, Unanswerable
from chartagent.plan.select import select_backend
from chartagent.profile.models import Profile
from chartagent.profile.source import profile_source
from chartagent.rasterise import Rasteriser
from chartagent.recipe import ChartRecipe, EscapeReason
from chartagent.result import ChartResult
from chartagent.review import CheckName, ReviewReport, flint_review, tier1_review

_FLINT_REPAIRABLE = frozenset(FLINT_REPAIRABLE_CHECKS)
_STEP1_RETRIES = 1
_STEP2_RETRIES = 2
_CALL_CAP = 5


@dataclass(frozen=True)
class Attempt:
    """One resolved ask inside a single ``create_chart`` call.

    ``step``/``ask`` are 1-based; ``ask`` counts asks within its step across
    the whole call — a schema decode failure counts exactly like a decoded
    one, matching ``step1_calls``/``step2_calls`` (issue #144). ``outcome``
    is one of four values, never a fifth: ``decode`` (the emit failed its
    step's schema), ``assemble`` (a decoded step-1 fragment, or a decoded
    step-2 ``chartProperties``, that ``assemble``/``bind`` then rejected),
    ``refuted`` (a step-1 unanswerable claim the profile contradicts), or
    ``ok``. ``emit`` is set only on an ``ok`` step-1 attempt, naming which
    of ``fragment | inexpressible | unanswerable`` decoded.
    ``rejected_emit``/``checker`` are set on every non-``ok`` outcome that
    has one; both are ``None`` on ``ok``.
    """

    step: Literal[1, 2]
    ask: int
    outcome: Literal["decode", "assemble", "refuted", "ok"]
    emit: Literal["fragment", "inexpressible", "unanswerable"] | None = None
    rejected_emit: Any = None
    checker: str | None = None


AttemptObserver = Callable[[Attempt], None]
Reviewer = Callable[[Profile, InputFrame, Envelope, Backend, str], ReviewReport]
RecipeReviewer = Callable[[Profile, ChartRecipe, str], ReviewReport]


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


def _reject(
    observe: Any,
    step: Literal[1, 2],
    ask: int,
    outcome: Literal["decode", "assemble", "refuted"],
    reason: Literal["empty_response", "invalid_emit"],
    rejected: Any,
    checker: str,
) -> _EmitFailed:
    """Journal one non-``ok`` outcome and build the ``_EmitFailed`` to raise
    or store as the next ask's repair — the one shape every non-``ok`` row
    shares (issue #144)."""
    observe(step, ask, outcome, rejected_emit=rejected, checker=checker or None)
    return _EmitFailed(reason, rejected=rejected, checker=checker)


_QUALITIES: tuple[str, ...] = get_args(Quality)


def _check_quality(quality: object) -> Quality:
    if quality not in _QUALITIES:
        raise ValueError(f"quality must be one of {_QUALITIES}, got {quality!r}")
    return cast(Quality, quality)


def create_chart_agent(
    *,
    model: str,
    quality: Quality = "balanced",
    rasteriser: Rasteriser | None = None,
    critique_model: str | None = None,
) -> ChartAgent:
    """Factory. Raises at construction if the model-vendor extra is missing.

    ``quality`` is the default for requests that omit it (ADR-0027
    Decision 8); ``create_chart(quality=...)`` overrides it per request.
    ``rasteriser=`` and ``critique_model=`` are factory-only and
    construction-checked (ADR-0027 Decision 8, ADR-0026 Decision 9): a
    ``critique_model`` naming an extra that is not installed raises
    :class:`~chartagent.errors.ModelClientUnavailableError` here, exactly
    like ``model``. Left unset, Tier 2 stays ``unavailable`` — a
    ``rasteriser`` alone still serves Tier 1's image checks (#201 does not
    build those; see ``chartagent.review``'s module docstring).
    """
    return ChartAgent(
        model=model,
        quality=quality,
        rasteriser=rasteriser,
        critique_model=critique_model,
    )


class ChartAgent:
    """Holds the model string and one client. No per-request mutable state."""

    def __init__(
        self,
        *,
        model: str,
        quality: Quality = "balanced",
        rasteriser: Rasteriser | None = None,
        critique_model: str | None = None,
    ) -> None:
        self._model = model
        self._quality = _check_quality(quality)
        self._client = ModelClient(model)
        self._attempt_observer: AttemptObserver | None = None
        self._library_resolver: LibraryResolver | None = None
        self._rasteriser = rasteriser
        self._critique_client = (
            None if critique_model is None else ModelClient(critique_model)
        )
        self._reviewer: Reviewer = self._flint_review
        self._recipe_reviewer: RecipeReviewer = _tier1_recipe_review

    def _flint_review(
        self,
        profile: Profile,
        frame: InputFrame,
        envelope: Envelope,
        backend: Backend,
        instruction: str,
    ) -> ReviewReport:
        return flint_review(
            profile,
            frame,
            envelope,
            backend,
            instruction,
            rasteriser=self._rasteriser,
            critique_client=self._critique_client,
        )

    def _resolve_quality(self, quality: Quality | None) -> Quality:
        return self._quality if quality is None else _check_quality(quality)

    def create_chart(
        self,
        data: DataSource,
        instruction: str,
        *,
        quality: Quality | None = None,
    ) -> ChartResult:
        resolved_quality = self._resolve_quality(quality)
        profile = profile_source(data)
        calls = 0
        step1_asks = 0
        step2_asks = 0
        observer = self._attempt_observer

        def observe(
            step: Literal[1, 2],
            ask: int,
            outcome: Literal["decode", "assemble", "refuted", "ok"],
            *,
            emit: Literal["fragment", "inexpressible", "unanswerable"] | None = None,
            rejected_emit: Any = None,
            checker: str | None = None,
        ) -> None:
            if observer is None:
                return
            observer(
                Attempt(
                    step=step,
                    ask=ask,
                    outcome=outcome,
                    emit=emit,
                    rejected_emit=rejected_emit,
                    checker=checker,
                )
            )

        def invoke(
            output_type: Any,
            prompt: Step1Prompt | Step2Prompt | DocumentPrompt,
            *,
            counted: bool = True,
        ) -> tuple[Any, int]:
            nonlocal calls, step1_asks, step2_asks
            # A miss's authoring ask replaces a raise: off the 5-call cap and
            # off the step 1/2 ask counts (ADR-0030 Decision 9).
            step: Literal[1, 2] = 1 if output_type is Step1Result else 2
            ask = 0
            if counted:
                if calls >= _CALL_CAP:
                    raise PlannerFailureError(
                        "planner call cap reached",
                        reason="retries_exhausted",
                    )
                calls += 1
                if step == 1:
                    step1_asks += 1
                    ask = step1_asks
                else:
                    step2_asks += 1
                    ask = step2_asks
            try:
                result = self._client.run(
                    cast(type[Any], output_type), prompt.system, prompt.user
                )
            except ChartAgentError:
                raise
            except Exception as exc:
                reason = _call_failure_reason(exc)
                if reason is None:
                    raise
                rejected = getattr(exc, "rejected_emit", None)
                checker = _checker_message(exc) if reason == "invalid_emit" else ""
                if not counted:
                    raise _EmitFailed(
                        reason, rejected=rejected, checker=checker
                    ) from exc
                raise _reject(
                    observe, step, ask, "decode", reason, rejected, checker
                ) from exc
            return result, ask

        last: Literal["empty_response", "invalid_emit"] | None = None
        repair: _EmitFailed | None = None
        for _ in range(_STEP1_RETRIES + 1):
            try:
                fragment = _step1_attempt(profile, instruction, invoke, repair, observe)
            except InexpressibleRequestError as miss:
                # Bucket 1/2 is an answer, not a retry. At ``fast`` it stays a
                # raise; above it the miss is authored into a recipe (ADR-0030).
                if resolved_quality == "fast":
                    raise
                return self._author_miss(
                    profile, instruction, miss, invoke, resolved_quality
                )
            except _EmitFailed as exc:
                last = exc.reason
                repair = exc
                continue
            backend = select_backend(
                fragment.chart_type,
                fragment.encodings,
                requested_backend=fragment.requested_backend,
            )
            properties, step2_ask = _step2(
                profile, fragment, instruction, backend, invoke
            )
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
                rejected = {
                    "fragment": fragment.model_dump(mode="json", exclude_none=True),
                    "chartProperties": properties,
                }
                checker = str(exc)
                repair = _reject(
                    observe, 2, step2_ask, "assemble", "invalid_emit", rejected, checker
                )
                continue
            observe(2, step2_ask, "ok")
            review = self._reviewer(profile, frame, envelope, backend, instruction)
            return self._repair_flint(
                profile,
                data,
                instruction,
                fragment,
                backend,
                (frame, envelope),
                review,
                resolved_quality,
                invoke,
            )
        raise PlannerFailureError(
            "step 1 did not emit a usable fragment",
            reason=last or "invalid_emit",
        )

    def _repair_flint(
        self,
        profile: Profile,
        data: DataSource,
        instruction: str,
        fragment: Fragment,
        backend: Backend,
        first: tuple[InputFrame, Envelope],
        review: ReviewReport,
        quality: Quality,
        invoke: Any,
    ) -> ChartResult:
        """Spend the budget on step-2 re-asks for a presentational failure.

        Each round is one uncounted ``chartProperties`` ask carrying every
        failing repairable name; chart type, encodings, transform and backend
        are the carried ones and step 1 is not re-run. A response that fails to
        decode, assemble or bind is a discard that still spends a unit. A
        repaired chart is reviewed in full. The hop trigger is read from the
        latest review, so a ``marks_present`` failure revealed by a repair still
        hops, with only what the repairs left; a terminal hop failure returns
        best-so-far with its own report. Never raises on review."""

        def request(
            _current: tuple[InputFrame, Envelope], failing: list[CheckName]
        ) -> tuple[InputFrame, Envelope] | None:
            prompt = render_review_repair(
                profile, fragment, instruction, backend, failing
            )
            try:
                result, _ = invoke(prompt.output_type, prompt, counted=False)
            except _EmitFailed:
                return None
            properties = result.model_dump(exclude_unset=True, exclude_none=True)
            try:
                frame = assemble(fragment, profile, chart_properties=properties)
                return frame, bind(frame, data, backend=backend)
            except (SpecShapeError, SchemaDriftError):
                return None

        total = _REVIEW_REPAIRS[quality]

        def decide(report: ReviewReport, spent: int) -> EscalationDecision | None:
            return decide_escalation(
                report, first[0], quality=quality, repairs_spent=spent
            )

        outcome = spend_repair_budget(
            first,
            review,
            total,
            request=request,
            reviewer=lambda candidate: self._reviewer(
                profile, candidate[0], candidate[1], backend, instruction
            ),
            repairable=_FLINT_REPAIRABLE,
            halt=lambda report, spent: decide(report, spent) is not None,
        )
        if outcome.halted is not None:
            (latest_frame, _), latest_review = outcome.halted
            decision = decide(latest_review, outcome.spent)
            if decision is not None:
                hopped = self._hop(profile, instruction, decision, latest_frame, invoke)
                if hopped is not None:
                    return hopped
        return ChartResult(envelope=outcome.artifact[1], review=outcome.review)

    def _hop(
        self,
        profile: Profile,
        instruction: str,
        decision: EscalationDecision,
        frame: InputFrame,
        invoke: Any,
    ) -> ChartResult | None:
        """Bucket 4: the failed frame's transform goes to ``generate_recipe``;
        step 1 is not re-run. The recipe enters the review-repair loop with only
        the budget the decision left, and ``frame.semantic_types`` go to the
        patch ask since a recipe stores none. There is no second hop: the recipe
        loop never calls ``decide_escalation``. ``None`` means the seam
        failed terminally and the caller returns best-so-far.
        """
        reason = EscapeReason(bucket=4)
        try:
            generated = generate_recipe(
                profile,
                instruction,
                reason,
                transform=decision.transform,
                semantic_types=frame.semantic_types,
                resolver=self._library_resolver,
                invoke=invoke,
            )
        except (DocumentGenerationFailed, PlannerFailureError):
            # Codegen and resolution exhausted are DocumentGenerationFailed
            # (LibraryResolutionFailed is that type). A counted retry that
            # hits the 5-call cap is PlannerFailureError. Anything else,
            # including a transport error, is not this fallback.
            return None
        recipe = ChartRecipe(
            spec_version=_SPEC_VERSION,
            transform=generated.transform,
            source_schema=decision.source_schema,
            escape_reason=reason,
            theme_spec=decision.theme_spec,
            document=generated.document,
        )
        return self._review_and_repair(
            profile,
            instruction,
            recipe,
            frame.semantic_types,
            decision.remaining_repairs,
            invoke,
        )

    def _author_miss(
        self,
        profile: Profile,
        instruction: str,
        miss: InexpressibleRequestError,
        invoke: Any,
        quality: Quality,
    ) -> ChartResult:
        """Bucket 1/2 at balanced/best: author a recipe instead of raising.

        ``theme_spec`` is absent — ``create_chart`` takes no theme. ``review``
        comes from the recipe reviewer via the review-repair loop. A
        terminal authoring or resolution failure re-raises the original bucket.
        """
        reason = EscapeReason(bucket=miss.bucket)
        try:
            generated = generate_recipe(
                profile,
                instruction,
                reason,
                transform=None,
                resolver=self._library_resolver,
                invoke=invoke,
            )
        except DocumentGenerationFailed as exc:
            raise InexpressibleRequestError(
                f"request is inexpressible (bucket {miss.bucket})",
                bucket=miss.bucket,
            ) from exc
        recipe = ChartRecipe(
            spec_version=_SPEC_VERSION,
            transform=generated.transform,
            source_schema=generated.source_schema,
            escape_reason=reason,
            theme_spec=None,
            document=generated.document,
        )
        return self._review_and_repair(
            profile,
            instruction,
            recipe,
            generated.semantic_types,
            _REVIEW_REPAIRS[quality],
            invoke,
        )

    def _review_and_repair(
        self,
        profile: Profile,
        instruction: str,
        recipe: ChartRecipe,
        semantic_types: Mapping[str, SemanticTypeName],
        budget: int,
        invoke: Any,
    ) -> ChartResult:
        """Review a custom-rail recipe and spend the budget on patch rounds.

        Each round is one ``patch_document`` call for every repairable failing
        name (ADR-0030 Decisions 11-14), charged one unit whether or not the
        patch is kept. A patch that decodes is reviewed in full: if it passes
        it is the answer, otherwise it is dropped and the next round patches the
        recipe as it was. A discarded patch changes nothing. Best-so-far is the
        recipe that passed, else the first one emitted; the returned report is
        always that recipe's (ADR-0027 Decision 7). Never raises on review."""

        def request(
            current: ChartRecipe, failing: list[CheckName]
        ) -> ChartRecipe | None:
            patched = patch_document(
                profile,
                instruction,
                current.document,
                failing,
                semantic_types=semantic_types,
                resolver=self._library_resolver,
                invoke=invoke,
            )
            if isinstance(patched, PatchDiscarded):
                return None
            return replace(current, document=patched)

        outcome = spend_repair_budget(
            recipe,
            self._recipe_reviewer(profile, recipe, instruction),
            budget,
            request=request,
            reviewer=lambda candidate: self._recipe_reviewer(
                profile, candidate, instruction
            ),
        )
        return ChartResult(recipe=outcome.artifact, review=outcome.review)


def _tier1_recipe_review(
    profile: Profile, recipe: ChartRecipe, instruction: str
) -> ReviewReport:
    return tier1_review(profile, backend=None)


def _step1_attempt(
    profile: Profile,
    instruction: str,
    invoke: Any,
    repair: _EmitFailed | None,
    observe: Any,
) -> Fragment:
    prompt = _with_repair(render_step1(profile, instruction), repair)
    result, ask = invoke(Step1Result, prompt)
    if isinstance(result, Inexpressible):
        observe(1, ask, "ok", emit="inexpressible")
        raise InexpressibleRequestError(
            f"request is inexpressible (bucket {result.bucket})",
            bucket=result.bucket,
        )
    if isinstance(result, Unanswerable):
        if _claim_refuted(result, profile):
            rejected = result.model_dump(mode="json", exclude_none=True)
            checker = (
                f"unanswerable {result.kind} is refuted: "
                f"keys {result.keys!r} are in the profile"
            )
            raise _reject(observe, 1, ask, "refuted", "invalid_emit", rejected, checker)
        observe(1, ask, "ok", emit="unanswerable")
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
        rejected = result.model_dump(mode="json", exclude_none=True)
        raise _reject(
            observe, 1, ask, "assemble", "invalid_emit", rejected, str(exc)
        ) from exc
    observe(1, ask, "ok", emit="fragment")
    return result


def _step2(
    profile: Profile,
    fragment: Fragment,
    instruction: str,
    backend: Backend,
    invoke: Any,
) -> tuple[dict[str, Any], int]:
    last: Literal["empty_response", "invalid_emit"] | None = None
    repair: _EmitFailed | None = None
    for _ in range(_STEP2_RETRIES + 1):
        prompt = _with_repair(
            render_step2(profile, fragment, instruction, backend), repair
        )
        try:
            result, ask = invoke(prompt.output_type, prompt)
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
        return dumped, ask
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
