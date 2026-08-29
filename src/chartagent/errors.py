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
