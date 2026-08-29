"""Typed errors. One flat module — ADR-0005 Decision 10."""

from __future__ import annotations


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
