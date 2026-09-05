"""Typed errors. One flat module — ADR-0005 Decision 10."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

RawSqlReason = Literal[
    "multi_statement",
    "not_read_only",
    "unparseable",
    "empty",
    "non_file_source",
    "foreign_relation",
]


class ChartAgentError(Exception):
    """Base class for every public chartagent error."""


class SpecShapeError(ChartAgentError):
    """The input frame is malformed.

    P0 cases include inline ``data`` and ``theme_spec: null``.
    """


class SpecVocabularyError(ChartAgentError):
    """A name the pin does not declare.

    ``kind`` is one of ``chart_type``, ``channel``, ``property``,
    ``enum_option``, ``semantic_type``, ``theme_preset``, ``encoding_key``.
    ``keys`` carries every offender of that kind.
    """

    def __init__(
        self,
        message: str,
        *,
        kind: str,
        keys: tuple[str, ...],
        chart_type: str | None = None,
        backend: str | None = None,
        pin: str | None = None,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.keys = keys
        self.chart_type = chart_type
        self.backend = backend
        self.pin = pin


class BackendCapabilityError(ChartAgentError):
    """This backend cannot carry the requested frame.

    ``kind`` is one of ``chart_type``, ``property``, ``facet``.
    ``keys`` names every offender of that kind.
    """

    def __init__(
        self,
        message: str,
        *,
        kind: str,
        keys: tuple[str, ...],
        chart_type: str | None = None,
        backend: str | None = None,
        pin: str | None = None,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.keys = keys
        self.chart_type = chart_type
        self.backend = backend
        self.pin = pin


class DataSourceError(ChartAgentError):
    """The source cannot be read."""


class TransformError(ChartAgentError):
    """The transform failed to execute, timed out, or hit a memory limit.

    ``path`` is the transform node being compiled when DuckDB raised.
    """

    def __init__(self, message: str, *, path: str | None = None) -> None:
        super().__init__(message)
        self.path = path


class RawSqlRejectedError(TransformError):
    """``raw_sql`` failed a lock. ``reason`` is a plain-string Literal."""

    def __init__(
        self, message: str, *, reason: RawSqlReason, path: str | None = None
    ) -> None:
        super().__init__(message, path=path)
        self.reason = reason


DriftStage = Literal["source", "transform_output"]
DriftKind = Literal["renamed", "dropped", "retyped"]


@dataclass(frozen=True)
class DriftedField:
    """One drifted column. ``expected`` / ``found`` are kind-polymorphic."""

    name: str
    kind: DriftKind
    expected: str | None
    found: str | None


class SchemaDriftError(ChartAgentError):
    """A referenced column was dropped or retyped.

    ``kind="renamed"`` is in the Literal with no detector — a missing
    referenced column is ``dropped``.
    """

    def __init__(
        self,
        message: str,
        *,
        stage: DriftStage,
        drifted: tuple[DriftedField, ...],
    ) -> None:
        super().__init__(message)
        self.stage = stage
        self.drifted = drifted


class InexpressibleRequestError(ChartAgentError):
    """Step 1 returned a well-formed inexpressible verdict (ADR-0019).

    ``bucket`` is 1 (no chart type in the 48) or 2 (the transform menu
    cannot express it). Never raised for a malformed response — that is
    a planner-failure miss, not a bucket (ADR-0019 Decision 7) — and
    never for a request that makes no sense against the data, which is
    :class:`UnanswerableInstructionError` instead.
    """

    def __init__(self, message: str, *, bucket: Literal[1, 2]) -> None:
        super().__init__(message)
        self.bucket = bucket


class UnanswerableInstructionError(ChartAgentError):
    """The instruction can't be answered against this data (ADR-0020).

    ``kind="missing_column"``: ``keys`` names columns the instruction
    claims that the profile does not have. ``kind="missing_role"``:
    ``keys`` names the absent source buckets (the same seven values
    :class:`~chartagent.frame.input.SourceBucket` uses) — empty for an
    unspecific ask that names no bucket in particular.

    A claim the profile already refutes (a named column that *does*
    exist) is a step-1 schema failure, never this error.
    """

    def __init__(
        self,
        message: str,
        *,
        kind: Literal["missing_column", "missing_role"],
        keys: tuple[str, ...],
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.keys = keys


class PlannerFailureError(ChartAgentError):
    """The planner broke rather than judged (ADR-0019).

    A rail-share miss carrying no escape reason: the harness records
    ``miss_kind: planner_failure`` with no ``reported_bucket``, never
    folded into bucket 3 and never a fifth bucket. Retrying the whole
    ``create_chart`` call may or may not help — retries already
    happened at the level that knows what retrying means.
    """

    def __init__(
        self,
        message: str,
        *,
        reason: Literal["retries_exhausted", "invalid_emit", "empty_response"]
        | None = None,
    ) -> None:
        super().__init__(message)
        self.reason = reason


class ModelClientUnavailableError(ChartAgentError):
    """The model-vendor extra is not installed.

    ``extra`` is the pip extra to install — ``chartagent[<provider>]``
    when we ship one, otherwise ``pydantic-ai-slim[<provider>]``.
    """

    def __init__(self, message: str, *, extra: str) -> None:
        super().__init__(message)
        self.extra = extra
