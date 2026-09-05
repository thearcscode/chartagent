"""The model client (issue #105, ADR-0022 Decision 9)."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import BaseModel
from pydantic_ai.exceptions import UserError

import chartagent
from chartagent.errors import ChartAgentError, ModelClientUnavailableError
from chartagent.plan.client import PRODUCT_DECODING, ModelClient


class Marker(BaseModel):
    n: int


def _block_pydantic_ai(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "pydantic_ai", None)
    for name in list(sys.modules):
        if name.startswith("pydantic_ai."):
            monkeypatch.delitem(sys.modules, name, raising=False)


def test_model_client_is_not_on_the_public_surface() -> None:
    for name in ("ModelClient", "PRODUCT_DECODING"):
        assert name not in chartagent.__all__
        assert not hasattr(chartagent, name)


def test_importing_the_client_module_does_not_load_pydantic_ai() -> None:
    script = """
import sys
import chartagent.plan.client  # noqa: F401

assert "pydantic_ai" not in sys.modules
assert "anthropic" not in sys.modules
assert "openai" not in sys.modules
"""
    subprocess.run([sys.executable, "-c", script], check=True)


def test_missing_pydantic_ai_names_the_anthropic_extra(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _block_pydantic_ai(monkeypatch)
    with pytest.raises(ModelClientUnavailableError) as caught:
        ModelClient("anthropic:claude-sonnet-4-6")
    assert caught.value.extra == "chartagent[anthropic]"


def test_missing_pydantic_ai_names_the_openai_extra(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _block_pydantic_ai(monkeypatch)
    with pytest.raises(ModelClientUnavailableError) as caught:
        ModelClient("openai:gpt-4o")
    assert caught.value.extra == "chartagent[openai]"


def test_missing_pydantic_ai_names_pydantic_ai_slim_for_an_unshipped_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _block_pydantic_ai(monkeypatch)
    with pytest.raises(ModelClientUnavailableError) as caught:
        ModelClient("groq:llama-3.3-70b-versatile")
    assert caught.value.extra == "pydantic-ai-slim[groq]"


def test_unshipped_provider_without_its_sdk_raises_at_construction() -> None:
    with pytest.raises(ModelClientUnavailableError) as caught:
        ModelClient("groq:llama-3.3-70b-versatile")
    assert caught.value.extra == "pydantic-ai-slim[groq]"


def test_unknown_model_string_propagates_unwrapped() -> None:
    with pytest.raises(UserError) as caught:
        ModelClient("not-a-provider:totally-fake")
    assert not isinstance(caught.value, ChartAgentError)


def test_product_decoding_is_temperature_zero() -> None:
    assert PRODUCT_DECODING == {"temperature": 0}


def test_score_corpus_imports_product_decoding() -> None:
    path = Path(__file__).resolve().parents[1] / "tools" / "score_corpus.py"
    spec = importlib.util.spec_from_file_location("score_corpus", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.PRODUCT_DECODING is PRODUCT_DECODING


def test_scripted_model_round_trips_one_call() -> None:
    result = ModelClient("test").run(Marker, "return a marker", "n is an integer")
    assert isinstance(result, Marker)


def test_model_requests_are_blocked_suite_wide() -> None:
    from pydantic_ai import models

    assert models.ALLOW_MODEL_REQUESTS is False
