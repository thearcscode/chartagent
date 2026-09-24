"""generate_recipe tracer: first-generation ChartDocument (#184, ADR-0030)."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any, Literal

import pytest
from pydantic_ai.messages import (
    ModelResponse,
    SystemPromptPart,
    ToolCallPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel

from chartagent.plan.agent import _call_failure_reason
from chartagent.plan.client import ModelClient
from chartagent.plan.emit import _EmitFailed
from chartagent.plan.prompt import render_document
from chartagent.plan.recipe import (
    ChartDocument,
    DocumentDraft,
    DocumentGenerationFailed,
    EscapeReason,
    LibraryPin,
    LibraryRequest,
    LibraryResolutionFailed,
    generate_recipe,
)
from chartagent.profile.models import (
    NumberColumn,
    NumberStats,
    Profile,
    StringColumn,
    StringStats,
    TopValue,
    untrusted_paths,
)
from chartagent.transform.model import Menu

_NONCE = "aaaabbbbccccdddd"
_SECRET_CELL = "Q1-SECRET-CELL"
_INSTRUCTION = "Draw revenue by quarter as a bullet chart"
_SEMANTIC = {"total": "Quantity"}
_TRANSFORM = Menu.model_validate(
    {
        "group_by": ["quarter"],
        "aggregate": [{"name": "total", "op": "sum", "field": "revenue"}],
    }
)
_PROFILE = Profile(
    row_count=2,
    columns=[
        StringColumn(
            name="quarter",
            reported_type="VARCHAR",
            null_rate=0.0,
            distinct=2,
            saturated=False,
            top=[TopValue(value=_SECRET_CELL, count=1)],
            stats=StringStats(min=_SECRET_CELL, max="Q2", top_k_coverage=1.0),
        ),
        NumberColumn(
            name="revenue",
            reported_type="BIGINT",
            null_rate=0.0,
            distinct=2,
            saturated=False,
            stats=NumberStats(min=1, max=2, p01=1, p25=1, p50=1, p75=2, p99=2),
        ),
    ],
    sample_rows=[{"quarter": _SECRET_CELL, "revenue": 4242}],
)
_MODULE = "function render(data, el) {}\nfunction getPlottedSeries() { return []; }"


def _client(*replies: dict[str, Any] | str) -> tuple[ModelClient, dict[str, list[Any]]]:
    queue = list(replies)
    seen: dict[str, list[Any]] = {"system": [], "user": []}

    def fn(messages: Any, info: AgentInfo) -> ModelResponse:
        for message in messages:
            for part in getattr(message, "parts", ()):
                if isinstance(part, SystemPromptPart):
                    seen["system"].append(part.content)
                if isinstance(part, UserPromptPart):
                    seen["user"].append(part.content)
        reply = queue.pop(0)
        if isinstance(reply, str):
            return ModelResponse(parts=[])
        name = info.output_tools[0].name
        return ModelResponse(parts=[ToolCallPart(tool_name=name, args=reply)])

    client = ModelClient("test")
    client._model = FunctionModel(fn)  # type: ignore[assignment]
    return client, seen


def _invoke(client: ModelClient) -> Callable[[Any, Any], tuple[Any, int]]:
    asks = 0

    def invoke(output_type: Any, prompt: Any) -> tuple[Any, int]:
        nonlocal asks
        asks += 1
        try:
            return client.run(output_type, prompt.system, prompt.user), asks
        except Exception as exc:
            reason = _call_failure_reason(exc)
            if reason is None:
                raise
            raise _EmitFailed(
                reason, rejected=getattr(exc, "rejected_emit", None), checker=str(exc)
            ) from exc

    return invoke


def _generate(client: ModelClient, **overrides: Any) -> ChartDocument:
    kwargs: dict[str, Any] = {
        "transform": _TRANSFORM,
        "semantic_types": _SEMANTIC,
        "invoke": _invoke(client),
    }
    kwargs.update(overrides)
    return generate_recipe(_PROFILE, _INSTRUCTION, EscapeReason(bucket=4), **kwargs)


def test_valid_emit_returns_storable_document() -> None:
    client, _ = _client({"module": _MODULE, "libraries": []})
    document = _generate(client)
    assert document == ChartDocument(
        module=_MODULE, styles=None, libraries=(), contract_version=1
    )


def test_styles_carried_when_present() -> None:
    client, _ = _client({"module": _MODULE, "styles": ".a{}", "libraries": []})
    assert _generate(client).styles == ".a{}"


def test_malformed_first_emit_is_retried_once() -> None:
    client, seen = _client({"module": 3}, {"module": _MODULE, "libraries": []})
    assert _generate(client).module == _MODULE
    assert len(seen["user"]) == 2
    assert "Rejected emit" in seen["user"][1]


def test_second_malformed_emit_is_terminal() -> None:
    client, seen = _client({"module": 3}, "empty")
    with pytest.raises(DocumentGenerationFailed):
        _generate(client)
    assert len(seen["user"]) == 2


def test_named_library_without_a_resolver_is_a_decode_failure() -> None:
    named = {"module": _MODULE, "libraries": [{"name": "d3", "version": "7.9.0"}]}
    client, _ = _client(named, {"module": _MODULE, "libraries": []})
    assert _generate(client).libraries == ()
    client, _ = _client(named, named)
    with pytest.raises(DocumentGenerationFailed):
        _generate(client)


def test_supplied_transform_is_never_reasked() -> None:
    client, _ = _client({"module": _MODULE, "libraries": []})
    assert "transform" not in DocumentDraft.model_fields
    assert _prompt().output_type is DocumentDraft
    _generate(client)


def test_absent_transform_is_not_this_tracer() -> None:
    client, _ = _client()
    with pytest.raises(NotImplementedError):
        _generate(client, transform=None)


def _prompt(bucket: Literal[1, 2, 3, 4] = 4) -> Any:
    return render_document(
        _PROFILE,
        _INSTRUCTION,
        EscapeReason(bucket=bucket),
        _SEMANTIC,
        nonce=_NONCE,
    )


def _fenced(prompt: Any) -> str:
    match = re.search(
        rf"<data_profile_{_NONCE}>\n(.*?)\n</data_profile_{_NONCE}>",
        prompt.user,
        re.S,
    )
    assert match
    return match.group(1)


def test_prompt_carries_no_cell_values() -> None:
    prompt = _prompt()
    text = prompt.system + prompt.user
    assert _SECRET_CELL not in text
    assert "4242" not in text
    assert "sample_rows" not in prompt.user


def test_prompt_carries_names_and_semantic_types_in_the_fence() -> None:
    fenced = _fenced(_prompt())
    assert "quarter" in fenced and "revenue" in fenced
    assert '"total":"Quantity"' in fenced


def test_prompt_states_the_two_symbol_contract() -> None:
    system = _prompt().system
    for needle in ("render(data, el)", "getPlottedSeries()", "scoped to `el`"):
        assert needle in system
    assert "window" in system and "document" in system


def test_prompt_delivers_theme_through_css_custom_properties() -> None:
    system = _prompt().system
    assert "CSS custom properties" in system
    assert "never hardcode" in system.lower()


def test_prompt_lists_untrusted_paths_from_the_manifest() -> None:
    for path in untrusted_paths():
        assert path in _prompt().system


def test_prompt_states_the_library_constraint() -> None:
    assert "libraries=()" in _prompt().system


def test_hop_and_miss_context_sit_outside_the_fence() -> None:
    hop = _prompt(4)
    assert "chrome" in hop.user and "marks" in hop.user
    assert "chrome" not in _fenced(hop)
    miss = _prompt(2)
    assert "bucket 2" in miss.user
    assert "bucket 2" not in _fenced(miss)


def test_pin_carries_identity_only() -> None:
    assert LibraryPin.__dataclass_fields__.keys() == {"name", "version", "sha256"}
    assert set(LibraryRequest.model_fields) == {"name", "version"}


_D3 = {"name": "d3", "version": "7.9.0"}
_TOPO = {"name": "topojson", "version": "3.0.2"}


def _resolver(calls: list[tuple[str, str]]) -> Callable[[str, str], tuple[str, bytes]]:
    def resolve(name: str, version: str) -> tuple[str, bytes]:
        calls.append((name, version))
        return f"sha-{name}", b"BYTES"

    return resolve


def test_resolver_yields_resolved_pins_in_load_order() -> None:
    calls: list[tuple[str, str]] = []
    client, _ = _client({"module": _MODULE, "libraries": [_TOPO, _D3]})
    document = _generate(client, resolver=_resolver(calls))
    assert document.libraries == (
        LibraryPin("topojson", "3.0.2", "sha-topojson"),
        LibraryPin("d3", "7.9.0", "sha-d3"),
    )
    assert calls == [("topojson", "3.0.2"), ("d3", "7.9.0")]


def test_no_bytes_on_the_returned_document() -> None:
    client, _ = _client({"module": _MODULE, "libraries": [_D3]})
    document = _generate(client, resolver=_resolver([]))
    assert "BYTES" not in repr(document)
    assert not any(isinstance(v, bytes) for v in vars(document).values())
    assert not any(
        isinstance(v, bytes) for pin in document.libraries for v in vars(pin).values()
    )


def test_empty_libraries_make_zero_resolver_calls() -> None:
    calls: list[tuple[str, str]] = []
    client, _ = _client({"module": _MODULE, "libraries": []})
    assert _generate(client, resolver=_resolver(calls)).libraries == ()
    assert calls == []


def test_resolver_failure_is_terminal_with_no_second_ask() -> None:
    def broken(name: str, version: str) -> tuple[str, bytes]:
        raise TimeoutError("registry down")

    client, seen = _client(
        {"module": _MODULE, "libraries": [_D3]},
        {"module": _MODULE, "libraries": []},
    )
    with pytest.raises(LibraryResolutionFailed):
        _generate(client, resolver=broken)
    assert len(seen["user"]) == 1


def test_prompt_offers_libraries_only_when_a_resolver_is_set() -> None:
    def system(resolver_set: bool) -> str:
        return render_document(
            _PROFILE,
            _INSTRUCTION,
            EscapeReason(bucket=4),
            _SEMANTIC,
            resolver_set=resolver_set,
            nonce=_NONCE,
        ).system

    assert "Only `libraries=()` is legal" in system(False)
    assert "Only `libraries=()` is legal" not in system(True)
    assert "exact version" in system(True)


def test_agent_resolver_is_private_and_unset_by_default() -> None:
    import inspect

    from chartagent.plan.agent import ChartAgent, create_chart_agent

    assert list(inspect.signature(create_chart_agent).parameters) == ["model"]
    agent = ChartAgent.__new__(ChartAgent)
    ChartAgent.__init__(agent, model="test")
    assert agent._library_resolver is None
