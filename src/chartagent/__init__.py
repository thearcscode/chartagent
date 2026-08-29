"""chartagent — embeddable agentic chart-creation library."""

from chartagent._flint import FlintBundle, flint_bundle
from chartagent.bind import DataSource, bind
from chartagent.envelope import Advisory, Envelope
from chartagent.errors import ChartAgentError
from chartagent.frame import (
    Backend,
    ChartVocabulary,
    EncodingActionDef,
    InputFrame,
    PropertyDef,
    canonical_json,
    vocabulary,
)
from chartagent.frame._generated import *  # noqa: F403
from chartagent.frame._generated import __all__ as _GENERATED_ALL

_GENERATED_MODELS = tuple(
    name
    for name in _GENERATED_ALL
    if name.endswith("Properties") and name != "GeneratedProperties"
)
for _name in _GENERATED_ALL:
    if _name not in _GENERATED_MODELS:
        del globals()[_name]
del _name

__all__ = [
    "bind",
    "Envelope",
    "DataSource",
    "Advisory",
    "flint_bundle",
    "FlintBundle",
    "ChartAgentError",
    "canonical_json",
    "vocabulary",
    "ChartVocabulary",
    "PropertyDef",
    "EncodingActionDef",
    "InputFrame",
    "Backend",
    *_GENERATED_MODELS,
]
