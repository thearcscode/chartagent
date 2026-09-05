"""Hand-written input frame. The one part of the façade that cannot be generated."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
)
from pydantic_core import ErrorDetails, PydanticCustomError

from chartagent.errors import ChartAgentError, SpecShapeError, SpecVocabularyError
from chartagent.frame._generated import (
    CHANNELS,
    FLINT_VERSION,
    ChartType,
    SemanticTypeName,
    ThemePresetName,
)

Backend = Literal["vegalite", "echarts", "chartjs", "plotly", "excel"]

# ADR-0019 Decision 3 / ADR-0021 Decision 1: the default ranking among
# backends that survive the declared-capability filter. Not applied when
# a request names a backend (ADR-0021's requested_backend, checked first
# and separately) — this tuple is the fallback order alone. The single
# citable source; tools/score_corpus.py and the planner (#92) both import
# it rather than hand-copying the order.
BACKEND_RANKING: tuple[Backend, ...] = (
    "vegalite",
    "echarts",
    "plotly",
    "chartjs",
    "excel",
)

SourceBucket = Literal[
    "number", "string", "boolean", "date", "timestamp", "timestamptz", "other"
]


class EncodingObject(BaseModel):
    """A channel value after shorthand normalisation. extras forbidden."""

    model_config = ConfigDict(extra="forbid")
    field: str
    type: str | None = None


def _as_encoding(value: object) -> object:
    if isinstance(value, str):
        return {"field": value}
    if isinstance(value, list):
        raise PydanticCustomError(
            "array_channel",
            "array-valued channels are not admitted",
        )
    return value


Encoding = Annotated[EncodingObject, BeforeValidator(_as_encoding)]


class BaseSize(BaseModel):
    model_config = ConfigDict(extra="allow")
    width: float
    height: float


# ADR-0002 Decision 6: a spec that does not pin its size is not a spec that
# refreshes reproducibly. The planner fills every planned frame from this
# constant (issue #107). Importable by path; not in chartagent.__all__.
DEFAULT_BASE_SIZE = BaseSize(width=640, height=400)


class ChartSpec(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)
    chart_type: ChartType = Field(alias="chartType")
    encodings: dict[str, Encoding]
    chart_properties: dict[str, Any] = Field(
        default_factory=dict, alias="chartProperties"
    )
    base_size: BaseSize | None = Field(default=None, alias="baseSize")

    @field_validator("encodings")
    @classmethod
    def _closed_global_channels(
        cls, value: dict[str, EncodingObject]
    ) -> dict[str, EncodingObject]:
        unknown = tuple(key for key in value if key not in CHANNELS)
        if unknown:
            raise PydanticCustomError(
                "unknown_channel",
                "channel name(s) outside the pin export: {keys}",
                {"keys": unknown},
            )
        return value


class Options(BaseModel):
    """Top-level options bag. extra='allow' — the pin declares no vocabulary here."""

    model_config = ConfigDict(extra="allow")


class ThemeSpec(BaseModel):
    """A custom theme object. extra='allow' — its shape is in no metadata array."""

    model_config = ConfigDict(extra="allow")
    name: str | None = None
    colors: list[str] | None = None


class XChartagent(BaseModel):
    """Our grammar sibling. Unrecognised keys stay extra='allow' — policy is parked."""

    model_config = ConfigDict(extra="allow")
    spec_version: str = "1.2"
    transform: dict[str, Any] | None = None
    annotations: list[object] | None = None
    interactions: dict[str, object] | None = None
    source_schema: dict[str, SourceBucket] | None = None


class InputFrame(BaseModel):
    """The stored input frame. ``chartProperties`` is an open mapping."""

    model_config = ConfigDict(extra="forbid")
    semantic_types: dict[str, SemanticTypeName] = Field(default_factory=dict)
    chart_spec: ChartSpec
    options: Options | None = None
    theme_spec: ThemePresetName | ThemeSpec | None = None
    x_chartagent: XChartagent | None = None

    @field_validator("theme_spec", mode="before")
    @classmethod
    def _theme_spec_not_null(cls, value: object) -> object:
        if value is None:
            raise PydanticCustomError(
                "theme_spec_null",
                "theme_spec must be omitted, not null",
            )
        return value

    def __init__(self, **data: Any) -> None:
        try:
            super().__init__(**data)
        except ValidationError as exc:
            raise _map_validation_error(exc) from exc

    @classmethod
    def model_validate(cls, obj: Any, **kwargs: Any) -> InputFrame:
        try:
            return super().model_validate(obj, **kwargs)
        except ValidationError as exc:
            raise _map_validation_error(exc) from exc

    def canonical_json(self) -> str:
        return canonical_json(self)


def _omit_nulls(value: object) -> object:
    if isinstance(value, dict):
        return {
            key: _omit_nulls(item) for key, item in value.items() if item is not None
        }
    if isinstance(value, list):
        return [_omit_nulls(item) for item in value]
    return value


def canonical_json(spec: InputFrame | Mapping[str, Any]) -> str:
    """Nulls omitted; empty collections preserved."""
    frame = spec if isinstance(spec, InputFrame) else InputFrame.model_validate(spec)
    dumped = frame.model_dump(mode="json", by_alias=True, exclude_none=True)
    return json.dumps(
        _omit_nulls(dumped),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _locs_end_with(err: ErrorDetails, *names: str) -> bool:
    loc = err["loc"]
    return bool(loc) and loc[-1] in names


def _map_validation_error(exc: ValidationError) -> ChartAgentError:
    """First failing site wins — ADR-0009 Decision 11, backend-free steps."""
    errors = exc.errors()
    pin = FLINT_VERSION

    if any(err["type"] == "theme_spec_null" for err in errors):
        return SpecShapeError("theme_spec must be omitted, not null")
    if any(err["type"] == "array_channel" for err in errors):
        return SpecShapeError("array-valued channels are not admitted")
    if any(
        err["loc"] == ("data",) and err["type"] == "extra_forbidden" for err in errors
    ):
        return SpecShapeError("input frame must not carry inline data")
    if any(err["type"] == "extra_forbidden" and len(err["loc"]) == 1 for err in errors):
        return SpecShapeError("input frame is malformed")
    if any(
        err["loc"] == ("semantic_types",) and err["type"] != "literal_error"
        for err in errors
    ):
        return SpecShapeError("semantic_types must be a mapping")

    chart_type_keys = tuple(
        str(err.get("input"))
        for err in errors
        if _locs_end_with(err, "chartType", "chart_type")
    )
    if chart_type_keys:
        return SpecVocabularyError(
            f"chart type(s) outside the pin union: {chart_type_keys}",
            kind="chart_type",
            keys=chart_type_keys,
            pin=pin,
        )

    channel_keys: list[str] = []
    for err in errors:
        if err["type"] == "unknown_channel":
            keys = err.get("ctx", {}).get("keys", ())
            channel_keys.extend(str(k) for k in keys)
    if channel_keys:
        return SpecVocabularyError(
            f"channel name(s) outside the pin export: {tuple(channel_keys)}",
            kind="channel",
            keys=tuple(channel_keys),
            pin=pin,
        )

    encoding_keys = tuple(
        str(err["loc"][-1])
        for err in errors
        if err["type"] == "extra_forbidden"
        and len(err["loc"]) >= 4
        and err["loc"][0] == "chart_spec"
        and err["loc"][1] == "encodings"
    )
    if encoding_keys:
        return SpecVocabularyError(
            f"encoding key(s) forbidden: {encoding_keys}",
            kind="encoding_key",
            keys=encoding_keys,
            pin=pin,
        )

    semantic_keys = tuple(
        str(err.get("input"))
        for err in errors
        if len(err["loc"]) >= 2 and err["loc"][0] == "semantic_types"
    )
    if semantic_keys:
        return SpecVocabularyError(
            f"semantic type(s) the pin does not declare: {semantic_keys}",
            kind="semantic_type",
            keys=semantic_keys,
            pin=pin,
        )

    theme_errs = [err for err in errors if err["loc"][:1] == ("theme_spec",)]
    if theme_errs:
        bad = tuple(
            str(err.get("input"))
            for err in theme_errs
            if isinstance(err.get("input"), str)
        )
        if bad:
            return SpecVocabularyError(
                f"theme preset(s) the pin does not declare: {bad}",
                kind="theme_preset",
                keys=bad,
                pin=pin,
            )

    return SpecShapeError(str(exc))
