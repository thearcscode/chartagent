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

from chartagent.frame._generated import SemanticTypeName
from chartagent.plan.agent import _call_failure_reason
from chartagent.plan.client import ModelClient
from chartagent.plan.emit import _EmitFailed
from chartagent.plan.prompt import render_document
from chartagent.plan.recipe import (
    ChartDocument,
    DocumentDraft,
    DocumentGenerationFailed,
    EscapeReason,
    GeneratedRecipe,
    LibraryPin,
    LibraryRequest,
    LibraryResolutionFailed,
    RecipeDraft,
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
_SEMANTIC: dict[str, SemanticTypeName] = {"total": "Quantity"}
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


def _invoke(
    client: ModelClient, uncounted: list[Any] | None = None
) -> Callable[..., tuple[Any, int]]:
    asks = 0

    def invoke(
        output_type: Any, prompt: Any, *, counted: bool = True
    ) -> tuple[Any, int]:
        nonlocal asks
        asks += 1
        if not counted and uncounted is not None:
            uncounted.append(output_type)
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
    return _generated(client, **overrides).document


def _generated(client: ModelClient, **overrides: Any) -> GeneratedRecipe:
    kwargs: dict[str, Any] = {
        "transform": _TRANSFORM,
        "semantic_types": _SEMANTIC,
        "invoke": _invoke(client),
    }
    kwargs.update(overrides)
    bucket = kwargs.pop("bucket", 4)
    return generate_recipe(
        _PROFILE, _INSTRUCTION, EscapeReason(bucket=bucket), **kwargs
    )


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


# --- miss path: transform=None (#186) ---

_AUTHORED = {
    "group_by": ["quarter"],
    "aggregate": [{"name": "total", "op": "sum", "field": "revenue"}],
}
_DOC = {"module": _MODULE, "libraries": []}
_MISS = {
    "transform": _AUTHORED,
    "semantic_types": {"total": "Quantity"},
    "document": _DOC,
}


def _author(client: ModelClient, bucket: int = 1, **kw: Any) -> GeneratedRecipe:
    return _generated(client, transform=None, semantic_types=None, bucket=bucket, **kw)


def test_miss_returns_authored_transform_and_document_from_one_ask() -> None:
    client, seen = _client(_MISS)
    recipe = _author(client)
    assert recipe.transform == _TRANSFORM
    assert recipe.document.module == _MODULE
    assert len(seen["user"]) == 1


def test_miss_decodes_into_recipe_draft() -> None:
    prompt = _miss_prompt(1)
    assert prompt.output_type is RecipeDraft
    assert set(RecipeDraft.model_fields) == {
        "transform",
        "semantic_types",
        "document",
    }
    assert "three keys" in prompt.system
    assert "`semantic_types`" in prompt.system
    assert "Quantity" in prompt.system


def _miss_prompt(bucket: Literal[1, 2, 3, 4]) -> Any:
    return render_document(
        _PROFILE,
        _INSTRUCTION,
        EscapeReason(bucket=bucket),
        None,
        author_transform=True,
        nonce=_NONCE,
    )


def test_bucket_two_prompt_frames_raw_sql_and_bucket_one_does_not() -> None:
    assert "raw_sql" in _miss_prompt(2).system
    assert "already failed the eight-slot menu" in _miss_prompt(2).system
    assert "already failed" not in _miss_prompt(1).system
    assert "expect to use" not in _miss_prompt(1).system
    assert "escape valve" not in _miss_prompt(1).system


def test_miss_prompt_never_copies_semantic_types_from_the_profile() -> None:
    prompt = _miss_prompt(1)
    assert "semantic_types" not in _fenced(prompt)
    assert "never copy" in prompt.system


def test_source_schema_is_computed_by_code_for_authored_and_supplied() -> None:
    client, _ = _client(_MISS)
    assert _author(client).source_schema == {"quarter": "string", "revenue": "number"}
    client, _ = _client(_DOC)
    assert _generated(client).source_schema == {
        "quarter": "string",
        "revenue": "number",
    }
    assert "source_schema" not in RecipeDraft.model_fields
    assert "source_schema" not in DocumentDraft.model_fields


def test_authored_raw_sql_violating_the_locks_is_retried_once_then_terminal() -> None:
    bad = {**_MISS, "transform": {"raw_sql": "DROP TABLE source"}}
    client, seen = _client(bad, _MISS)
    assert _author(client, 2).transform == _TRANSFORM
    assert "Rejected emit" in seen["user"][1]
    client, seen = _client(bad, bad)
    with pytest.raises(DocumentGenerationFailed):
        _author(client, 2)
    assert len(seen["user"]) == 2


def test_authored_raw_sql_reading_a_foreign_relation_is_rejected() -> None:
    bad = {**_MISS, "transform": {"raw_sql": "SELECT * FROM read_csv('/etc/passwd')"}}
    client, _ = _client(bad, bad)
    with pytest.raises(DocumentGenerationFailed):
        _author(client, 2)


def test_authored_semantic_types_are_returned_from_the_draft() -> None:
    client, _ = _client({**_MISS, "semantic_types": {"total": "Amount"}})
    assert _author(client).semantic_types == {"total": "Amount"}


def test_authored_semantic_type_outside_the_closed_list_is_a_decode_failure() -> None:
    bad = {**_MISS, "semantic_types": {"total": "Currency"}}
    client, seen = _client(bad, _MISS)
    assert _author(client).semantic_types == {"total": "Quantity"}
    assert "Rejected emit" in seen["user"][1]
    client, _ = _client(bad, bad)
    with pytest.raises(DocumentGenerationFailed):
        _author(client)


def test_authored_transform_naming_a_missing_column_counts_as_decode_failure() -> None:
    bad = {**_MISS, "transform": {"raw_sql": "SELECT nope FROM source"}}
    client, _ = _client(bad, bad)
    with pytest.raises(DocumentGenerationFailed):
        _author(client, 2)


def test_valid_raw_sql_is_accepted() -> None:
    sql = "SELECT quarter, sum(revenue) AS total FROM source GROUP BY quarter"
    client, _ = _client({**_MISS, "transform": {"raw_sql": sql}})
    assert _author(client, 2).source_schema == {
        "quarter": "string",
        "revenue": "number",
    }


def test_miss_first_call_is_uncounted_and_the_retry_is_counted() -> None:
    uncounted: list[Any] = []
    client, _ = _client({"transform": 3}, _MISS)
    _author(client, invoke=_invoke(client, uncounted))
    assert uncounted == [RecipeDraft]


def test_supplied_transform_asks_are_all_counted() -> None:
    uncounted: list[Any] = []
    client, _ = _client(_DOC)
    _generated(client, invoke=_invoke(client, uncounted))
    assert uncounted == []
