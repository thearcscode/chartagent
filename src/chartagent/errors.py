"""Typed errors. One flat module — ADR-0005 Decision 10."""


class ChartAgentError(Exception):
    """Base class for every public chartagent error."""
