"""Public vocabulary accessor over the committed vocab.json."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, overload

from chartagent.frame._generated import (
    BUNDLE_SHA256,
    CHANNELS,
    FLINT_VERSION,
    SEMANTIC_TYPES,
    THEME_PRESETS,
)
from chartagent.frame.input import Backend

_VOCAB_PATH = Path(__file__).with_name("vocab.json")


@dataclass(frozen=True)
class PropertyOption:
    value: object
    label: str | None


@dataclass(frozen=True)
class PropertyDef:
    """A property the pin declares.

    ``min``, ``max`` and ``step`` are UI slider bounds, not validation
    bounds. ``Bar Table.maxRows: 0`` is valid under a declared ``min`` of 5.
    """

    key: str
    type: str | None
    label: str | None
    default: object
    has_default: bool
    min: float | None
    max: float | None
    step: float | None
    options: tuple[PropertyOption, ...] | None
    source: Literal["properties"]
    dependencies: tuple[str, ...]
    data_dependent: bool


@dataclass(frozen=True)
class EncodingActionDef:
    """An encodingAction the pin declares. Same slider-bound rule as PropertyDef."""

    key: str
    type: str | None
    label: str | None
    default: object
    has_default: bool
    min: float | None
    max: float | None
    step: float | None
    options: tuple[PropertyOption, ...] | None
    source: Literal["encodingActions"]
    dependencies: tuple[str, ...]
    data_dependent: bool


@dataclass(frozen=True)
class ChartVocabulary:
    """Per-(backend, chart type) affordances.

    ``channels`` is the per-type list the pin advertises. It under-declares
    by 19 measured pairs Flint honours, so it must never gate validation.
    ``dependencies`` is an enablement hint, not a validity rule.
    """

    backend: Backend
    chart_type: str
    channels: tuple[str, ...]
    properties: tuple[PropertyDef, ...]
    encoding_actions: tuple[EncodingActionDef, ...]


def _options(raw: object) -> tuple[PropertyOption, ...] | None:
    if not raw:
        return None
    if not isinstance(raw, list):
        return None
    out: list[PropertyOption] = []
    for item in raw:
        if isinstance(item, dict):
            out.append(PropertyOption(value=item.get("value"), label=item.get("label")))
    return tuple(out)


def _str_or_none(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _float_or_none(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _deps(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, str))


def _entry(raw: dict[str, object]) -> PropertyDef | EncodingActionDef:
    key = raw["key"]
    assert isinstance(key, str)
    kind = _str_or_none(raw.get("type"))
    label = _str_or_none(raw.get("label"))
    default = raw.get("default")
    has_default = bool(raw.get("has_default"))
    lo = _float_or_none(raw.get("min"))
    hi = _float_or_none(raw.get("max"))
    step = _float_or_none(raw.get("step"))
    options = _options(raw.get("options"))
    dependencies = _deps(raw.get("dependencies"))
    data_dependent = bool(raw.get("data_dependent"))
    if raw.get("source") == "encodingActions":
        return EncodingActionDef(
            key=key,
            type=kind,
            label=label,
            default=default,
            has_default=has_default,
            min=lo,
            max=hi,
            step=step,
            options=options,
            source="encodingActions",
            dependencies=dependencies,
            data_dependent=data_dependent,
        )
    return PropertyDef(
        key=key,
        type=kind,
        label=label,
        default=default,
        has_default=has_default,
        min=lo,
        max=hi,
        step=step,
        options=options,
        source="properties",
        dependencies=dependencies,
        data_dependent=data_dependent,
    )


class _Vocabulary:
    """``vocabulary(backend)`` / ``vocabulary(backend, chart_type)``.

    Also exposes the closed global lists the façade *does* reject on:
    ``channels``, ``theme_presets``, ``semantic_types``.
    """

    def __init__(self) -> None:
        self.channels: tuple[str, ...] = tuple(CHANNELS)
        self.theme_presets: tuple[str, ...] = tuple(THEME_PRESETS)
        self.semantic_types: tuple[str, ...] = tuple(SEMANTIC_TYPES)
        self.flint_version: str = FLINT_VERSION
        self.bundle_sha256: str = BUNDLE_SHA256
        self._raw: dict[str, object] = json.loads(
            _VOCAB_PATH.read_text(encoding="utf-8")
        )

    @overload
    def __call__(self, backend: Backend) -> tuple[str, ...]: ...

    @overload
    def __call__(self, backend: Backend, chart_type: str) -> ChartVocabulary: ...

    def __call__(
        self,
        backend: Backend,
        chart_type: str | None = None,
    ) -> tuple[str, ...] | ChartVocabulary:
        backends = self._raw["backends"]
        assert isinstance(backends, dict)
        charts = backends.get(backend)
        if not isinstance(charts, dict):
            raise ValueError(f"unknown backend: {backend!r}")
        if chart_type is None:
            return tuple(sorted(charts))
        spec = charts.get(chart_type)
        if not isinstance(spec, dict):
            raise ValueError(
                f"unknown chart type {chart_type!r} for backend {backend!r}"
            )
        raw_props = spec["properties"]
        assert isinstance(raw_props, list)
        entries = [_entry(p) for p in raw_props if isinstance(p, dict)]
        raw_channels = spec.get("channels") or ()
        channels = tuple(c for c in raw_channels if isinstance(c, str))
        return ChartVocabulary(
            backend=backend,
            chart_type=chart_type,
            channels=channels,
            properties=tuple(e for e in entries if isinstance(e, PropertyDef)),
            encoding_actions=tuple(
                e for e in entries if isinstance(e, EncodingActionDef)
            ),
        )


vocabulary = _Vocabulary()
