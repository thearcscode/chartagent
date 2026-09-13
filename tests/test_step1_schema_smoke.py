"""Live smoke test: the typed step-1 tool schema is accepted, per vendor
(ADR-0023 Decision 7, issue #147).

``Expr`` is recursive and step 1 stays non-strict on every vendor (ADR-0023
Decision 3) — a ``oneOf`` inside a non-strict tool schema is accepted per
the vendor-agnostic client's contract, but that was never verified by a
live call before this. One call per shipped vendor extra (``anthropic``,
``openai``), confirming the schema decodes rather than being rejected
outright by the vendor. Skipped when the vendor's API key is unset, or
when its pydantic-ai extra is not installed.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, cast

import pytest

from chartagent.errors import ModelClientUnavailableError
from chartagent.plan.client import ModelClient
from chartagent.plan.prompt import render_step1
from chartagent.plan.schema import Fragment, Inexpressible, Step1Result, Unanswerable
from chartagent.profile.source import profile_source

_SALES = Path(__file__).with_name("data") / "sales.csv"
_INSTRUCTION = "Bar chart of revenue by quarter"


def _one_step1_call(model: str) -> None:
    from pydantic_ai.models import override_allow_model_requests

    try:
        client = ModelClient(model)
    except ModelClientUnavailableError:
        pytest.skip(f"{model} vendor extra is not installed")
    profile = profile_source(_SALES)
    prompt = render_step1(profile, _INSTRUCTION)
    with override_allow_model_requests(True):
        result = client.run(cast(type[Any], Step1Result), prompt.system, prompt.user)
    assert isinstance(result, (Fragment, Inexpressible, Unanswerable))


@pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"), reason="ANTHROPIC_API_KEY is unset"
)
def test_typed_step1_schema_is_accepted_by_anthropic() -> None:
    _one_step1_call("anthropic:claude-sonnet-4-6")


@pytest.mark.skipif(
    not os.environ.get("OPENAI_API_KEY"), reason="OPENAI_API_KEY is unset"
)
def test_typed_step1_schema_is_accepted_by_openai() -> None:
    _one_step1_call("openai:gpt-4o")
