# /// script
# requires-python = ">=3.11"
# dependencies = ["pydantic>=2.9"]
# ///
"""
PROTOTYPE — THROWAWAY. ChartSpec v1 core grammar draft (issue #3).

This is a draft-to-react-to, not production code. It covers the *core* grammar only:
mark, encodings, layers, annotations, interactions, style, spec_version, escape.

Deliberately out of scope (owned by other frontier tickets):
  - the transform block internals            -> issue #4  (kept here as an opaque stub)
  - CapabilityProfile / adapter negotiation   -> issue #9  (only the version-compat helper)
  - profile.json shape                        -> issue #5  (a fake profile is used in phase-2 demo)

Numbered decisions D1..D9 are the things to argue with. See README.md.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# The grammar version. D7: MAJOR.MINOR only — a patch release cannot change grammar,
# so a patch component would be a number nothing is ever allowed to depend on.
SPEC_VERSION = "1.0"


# --------------------------------------------------------------------------------------
# Typed error codes (P0.9). The full taxonomy graduates from this ticket; these are the
# codes the core grammar actually needs. Validators raise ValueError carrying a code so
# pydantic's ValidationError stays the single transport.
# --------------------------------------------------------------------------------------
class SpecError(StrEnum):
    MARK_CHANNEL_REQUIRED = "E_MARK_CHANNEL_REQUIRED"
    MARK_CHANNEL_UNSUPPORTED = "E_MARK_CHANNEL_UNSUPPORTED"
    CHANNEL_TYPE_MISMATCH = "E_CHANNEL_TYPE_MISMATCH"
    LAYER_COMBO_UNSUPPORTED = "E_LAYER_COMBO_UNSUPPORTED"
    LAYER_BUDGET_EXCEEDED = "E_LAYER_BUDGET_EXCEEDED"
    SPEC_VERSION_UNSUPPORTED = "E_SPEC_VERSION_UNSUPPORTED"
    ANNOTATION_TARGET_INVALID = "E_ANNOTATION_TARGET_INVALID"
    ESCAPE_CONFLICT = "E_ESCAPE_CONFLICT"
    # Phase-2 (needs profile.json), not raised at construction time:
    COLOR_CARDINALITY_EXCEEDED = "E_COLOR_CARDINALITY_EXCEEDED"
    FIELD_NOT_IN_PROFILE = "E_FIELD_NOT_IN_PROFILE"


def _err(code: SpecError, msg: str) -> ValueError:
    return ValueError(f"[{code}] {msg}")


class DataType(StrEnum):
    QUANTITATIVE = "quantitative"
    TEMPORAL = "temporal"
    ORDINAL = "ordinal"
    NOMINAL = "nominal"


CATEGORICAL = {DataType.ORDINAL, DataType.NOMINAL}


# --------------------------------------------------------------------------------------
# D1: mark is a discriminated union of small objects, not a bare enum.
# Every mark has params that belong nowhere else (stacking, bin count, donut hole,
# whisker rule). A bare enum pushes those into `style`, which is where library-specific
# junk drawers are born. `pie` + inner_radius_ratio > 0 IS donut — one mark, not two.
# --------------------------------------------------------------------------------------
class _MarkBase(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BarMark(_MarkBase):
    type: Literal["bar"] = "bar"
    orientation: Literal["vertical", "horizontal"] = "vertical"
    stack: Literal["none", "stacked", "normalized"] = "none"


class LineMark(_MarkBase):
    type: Literal["line"] = "line"
    interpolate: Literal["linear", "monotone", "step"] = "linear"
    show_points: bool = False


class AreaMark(_MarkBase):
    type: Literal["area"] = "area"
    stack: Literal["none", "stacked", "normalized"] = "stacked"
    interpolate: Literal["linear", "monotone", "step"] = "linear"


class ScatterMark(_MarkBase):
    type: Literal["scatter"] = "scatter"
    opacity: float | None = Field(default=None, ge=0.0, le=1.0)


class PieMark(_MarkBase):
    type: Literal["pie"] = "pie"
    inner_radius_ratio: float = Field(default=0.0, ge=0.0, lt=1.0)  # > 0 => donut


class HeatmapMark(_MarkBase):
    type: Literal["heatmap"] = "heatmap"


class HistogramMark(_MarkBase):
    type: Literal["histogram"] = "histogram"
    bins: int | None = Field(default=None, ge=2, le=200)  # None => adapter auto-binning


class BoxplotMark(_MarkBase):
    type: Literal["boxplot"] = "boxplot"
    whisker: Literal["tukey", "minmax"] = "tukey"


Mark = Annotated[
    BarMark | LineMark | AreaMark | ScatterMark | PieMark | HeatmapMark | HistogramMark | BoxplotMark,
    Field(discriminator="type"),
]


# --------------------------------------------------------------------------------------
# Channels
# --------------------------------------------------------------------------------------
class ScaleSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["linear", "log", "sqrt", "time", "point", "band"] | None = None
    domain: tuple[float, float] | None = None
    zero: bool | None = None  # bar-baseline lint (§7.3 T1) reads this
    nice: bool | None = None
    reverse: bool | None = None


class AxisSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = None
    format: str | None = None  # d3-format / strftime string
    label_angle: float | None = None
    grid: bool | None = None


class Channel(BaseModel):
    """
    D2: NO `aggregate` on the channel — unlike Vega-Lite.

    Encodings reference *output columns of the transform block*. Aggregation lives in
    `data.transform` (issue #4) because (a) pushdown compiles the transform to the
    source's SQL and cannot reach into encodings, and (b) zero-cost refresh (§7.7)
    re-runs the transform alone. Encoding-level aggregate would fork that boundary.
    Cost: the planner must name derived columns explicitly (e.g. `revenue_sum`).
    """

    model_config = ConfigDict(extra="forbid")
    field: str = Field(min_length=1)
    type: DataType
    title: str | None = None
    scale: ScaleSpec | None = None
    axis: AxisSpec | None = None
    sort: Literal["ascending", "descending", "none"] | str | None = None
    legend: bool | None = None  # color/size only; None => adapter default


class FacetChannel(Channel):
    columns: int | None = Field(default=None, ge=1, le=12)


class Encodings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    x: Channel | None = None
    y: Channel | None = None
    color: Channel | None = None
    size: Channel | None = None
    facet: FacetChannel | None = None
    # D3: tooltip is a LIST of fields, not one channel. Everything else is one field
    # per visual channel; tooltip is the only genuinely many-valued one, so modelling
    # it as a single Channel would force an artificial "extra fields" side-list.
    tooltip: list[Channel] = Field(default_factory=list, max_length=12)

    def present(self) -> set[str]:
        names = {n for n in ("x", "y", "color", "size", "facet") if getattr(self, n) is not None}
        if self.tooltip:
            names.add("tooltip")
        return names


# --------------------------------------------------------------------------------------
# D4: per-mark channel contract, as data rather than branching code.
# `pie` reuses color=category / y=value rather than introducing a `theta` channel —
# keeps the channel vocabulary at the six §8 names.
# --------------------------------------------------------------------------------------
class MarkRule(BaseModel):
    required: frozenset[str]
    allowed: frozenset[str]
    # channels whose DataType is constrained by the mark
    type_constraints: dict[str, frozenset[DataType]] = Field(default_factory=dict)


_Q = frozenset({DataType.QUANTITATIVE})
_CAT = frozenset(CATEGORICAL)

MARK_RULES: dict[str, MarkRule] = {
    "bar": MarkRule(
        required=frozenset({"x", "y"}),
        allowed=frozenset({"x", "y", "color", "facet", "tooltip"}),
    ),
    "line": MarkRule(
        required=frozenset({"x", "y"}),
        allowed=frozenset({"x", "y", "color", "facet", "tooltip"}),
        type_constraints={"y": _Q},
    ),
    "area": MarkRule(
        required=frozenset({"x", "y"}),
        allowed=frozenset({"x", "y", "color", "facet", "tooltip"}),
        type_constraints={"y": _Q},
    ),
    # x/y admit temporal as well as quantitative: a scatter over dates is legitimate on
    # its own, and it is REQUIRED for the line+scatter overlay (the commonest layered
    # chart there is) to survive layer validation. Categorical x/y stays excluded — that
    # request is a bar or a boxplot, and catching it is the rule's whole value.
    "scatter": MarkRule(
        required=frozenset({"x", "y"}),
        allowed=frozenset({"x", "y", "color", "size", "facet", "tooltip"}),
        type_constraints={
            "x": frozenset({DataType.QUANTITATIVE, DataType.TEMPORAL}),
            "y": frozenset({DataType.QUANTITATIVE, DataType.TEMPORAL}),
            "size": _Q,
        },
    ),
    "pie": MarkRule(
        required=frozenset({"color", "y"}),
        allowed=frozenset({"color", "y", "tooltip"}),
        type_constraints={"color": _CAT, "y": _Q},
    ),
    "heatmap": MarkRule(
        required=frozenset({"x", "y", "color"}),
        allowed=frozenset({"x", "y", "color", "facet", "tooltip"}),
        type_constraints={"color": _Q},
    ),
    # y is COMPUTED (count/density) — supplying it is an error, not an override.
    "histogram": MarkRule(
        required=frozenset({"x"}),
        allowed=frozenset({"x", "color", "facet", "tooltip"}),
        type_constraints={"x": _Q},
    ),
    "boxplot": MarkRule(
        required=frozenset({"y"}),
        allowed=frozenset({"x", "y", "color", "facet", "tooltip"}),
        type_constraints={"y": _Q, "x": _CAT},
    ),
}


def _check_mark_channels(mark_type: str, enc: Encodings, where: str) -> None:
    rule = MARK_RULES[mark_type]
    present = enc.present()

    missing = rule.required - present
    if missing:
        raise _err(
            SpecError.MARK_CHANNEL_REQUIRED,
            f"{where}: mark '{mark_type}' requires channel(s) {sorted(missing)}; got {sorted(present) or 'none'}",
        )

    extra = present - rule.allowed
    if extra:
        hint = ""
        if mark_type == "histogram" and "y" in extra:
            hint = " (histogram computes y itself — put the binned field on x)"
        raise _err(
            SpecError.MARK_CHANNEL_UNSUPPORTED,
            f"{where}: mark '{mark_type}' does not support channel(s) {sorted(extra)}{hint}",
        )

    for channel_name, allowed_types in rule.type_constraints.items():
        ch = getattr(enc, channel_name, None)
        if ch is not None and ch.type not in allowed_types:
            raise _err(
                SpecError.CHANNEL_TYPE_MISMATCH,
                f"{where}: mark '{mark_type}' channel '{channel_name}' must be one of "
                f"{sorted(t.value for t in allowed_types)}; got '{ch.type.value}'",
            )


# --------------------------------------------------------------------------------------
# D5: layers are OVERLAYS on a base mark, not a list the base lives inside.
# The single-mark case (the overwhelming majority) stays flat; composition is opt-in.
# Bounded three ways: budget, an explicit combo allowlist, and one shared transform.
# --------------------------------------------------------------------------------------
MAX_OVERLAY_LAYERS = 2  # PROVISIONAL — candidate to graduate to a follow-on ticket

ALLOWED_LAYER_COMBOS: frozenset[tuple[str, str]] = frozenset(
    {
        ("line", "scatter"),  # line + point markers
        ("line", "line"),  # actual vs. trend
        ("bar", "line"),  # bar + running average
        ("bar", "scatter"),  # bar + target markers
        ("area", "line"),  # band + centre line
        ("scatter", "line"),  # points + fitted line
    }
)


class Layer(BaseModel):
    """An overlay drawn on the base chart's axes, over the base chart's transform output."""

    model_config = ConfigDict(extra="forbid")
    mark: Mark
    # Partial override. Unset channels inherit from the base encodings at render time.
    encodings: Encodings | None = None


# --------------------------------------------------------------------------------------
# Annotations
# --------------------------------------------------------------------------------------
class _AnnotationBase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str | None = None


# D6: a reference line's value may be a literal OR a named summary statistic computed
# from the transform output. Without the stat form the planner has to bake a number into
# the spec, which zero-cost refresh (§7.7) would then silently falsify on new data.
RefValue = float | str | Literal["mean", "median", "min", "max", "p90", "p95"]


class ReferenceLine(_AnnotationBase):
    type: Literal["reference_line"] = "reference_line"
    axis: Literal["x", "y"]
    value: RefValue
    field: str | None = None  # required when value is a statistic
    style: Literal["solid", "dashed", "dotted"] = "dashed"

    @model_validator(mode="after")
    def _stat_needs_field(self) -> ReferenceLine:
        if isinstance(self.value, str) and self.value in {"mean", "median", "min", "max", "p90", "p95"}:
            if not self.field:
                raise _err(
                    SpecError.ANNOTATION_TARGET_INVALID,
                    f"reference_line value='{self.value}' is a computed statistic and requires `field`",
                )
        return self


class ReferenceBand(_AnnotationBase):
    type: Literal["reference_band"] = "reference_band"
    axis: Literal["x", "y"]
    start: RefValue
    end: RefValue
    field: str | None = None


class PointLabel(_AnnotationBase):
    type: Literal["point_label"] = "point_label"
    field: str  # label text comes from this transform-output column
    select: Literal["all", "max", "min", "first", "last", "extremes"] = "all"


class TextCallout(_AnnotationBase):
    type: Literal["text_callout"] = "text_callout"
    text: str
    x: float | str | None = None
    y: float | str | None = None
    anchor: Literal["top-left", "top-right", "bottom-left", "bottom-right", "data"] = "top-left"

    @model_validator(mode="after")
    def _data_anchor_needs_coords(self) -> TextCallout:
        if self.anchor == "data" and (self.x is None or self.y is None):
            raise _err(
                SpecError.ANNOTATION_TARGET_INVALID,
                "text_callout anchor='data' requires both x and y",
            )
        return self


Annotation = Annotated[
    ReferenceLine | ReferenceBand | PointLabel | TextCallout,
    Field(discriminator="type"),
]


# --------------------------------------------------------------------------------------
# Interactions / style / escape / data
# --------------------------------------------------------------------------------------
class Interactions(BaseModel):
    """
    Adapter-capability-gated (issue #9). Spec validation deliberately does NOT reject
    these: the spec is adapter-agnostic, and a Matplotlib target must not make a
    zoom_pan spec *invalid* — the rail router downgrades or diverts. Requesting an
    unsupported interaction is a routing input, not a grammar error.
    """

    model_config = ConfigDict(extra="forbid")
    tooltip: bool = True
    zoom_pan: bool = False
    legend_toggle: bool = False
    crossfilter: bool = False


class Style(BaseModel):
    """
    D8: every field is Optional and None means INHERIT, never "off".
    Precedence at render time: explicit spec value > org skill > theme > adapter default.
    Org-convention skills (§7.3) therefore need no separate slot in the spec — they are
    one layer of the resolver, and a spec that sets nothing inherits the whole house style.
    """

    model_config = ConfigDict(extra="forbid")
    theme: str | None = None
    palette: str | list[str] | None = None  # named palette or explicit hex list
    title: str | None = None
    subtitle: str | None = None
    caption: str | None = None
    width: int | None = Field(default=None, ge=64, le=8192)
    height: int | None = Field(default=None, ge=64, le=8192)
    colorblind_safe: bool | None = None


class Escape(BaseModel):
    """Custom-rail marker (§8). Present => the deterministic rail must not claim this spec."""

    model_config = ConfigDict(extra="forbid")
    mode: Literal["custom_code"] = "custom_code"
    reason: str = Field(min_length=1)  # machine-recorded; drives grammar growth (§7.3)
    library: str | None = None
    runtime_profile: Literal["python", "web"] = "python"


class DataRef(BaseModel):
    """STUB — the transform block is issue #4. Kept opaque so #3 can be judged alone."""

    model_config = ConfigDict(extra="forbid")
    source: str = Field(min_length=1)
    transform: dict[str, Any] = Field(default_factory=dict)


# --------------------------------------------------------------------------------------
# ChartSpec
# --------------------------------------------------------------------------------------
class ChartSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    spec_version: str = Field(default=SPEC_VERSION, pattern=r"^\d+\.\d+$")
    data: DataRef
    mark: Mark
    encodings: Encodings
    layers: list[Layer] = Field(default_factory=list)
    annotations: list[Annotation] = Field(default_factory=list)
    interactions: Interactions = Field(default_factory=Interactions)
    style: Style = Field(default_factory=Style)
    escape: Escape | None = None

    @model_validator(mode="after")
    def _validate_grammar(self) -> ChartSpec:
        _check_mark_channels(self.mark.type, self.encodings, where="base")

        if len(self.layers) > MAX_OVERLAY_LAYERS:
            raise _err(
                SpecError.LAYER_BUDGET_EXCEEDED,
                f"{len(self.layers)} overlay layers exceeds the v1 budget of {MAX_OVERLAY_LAYERS}; "
                "compositions beyond this belong on the custom rail",
            )

        for i, layer in enumerate(self.layers):
            combo = (self.mark.type, layer.mark.type)
            if combo not in ALLOWED_LAYER_COMBOS:
                raise _err(
                    SpecError.LAYER_COMBO_UNSUPPORTED,
                    f"layer[{i}]: '{combo[0]}' + '{combo[1]}' is not in the v1 composition allowlist "
                    f"({sorted('+'.join(c) for c in ALLOWED_LAYER_COMBOS)})",
                )
            # A layer's effective encodings are base overlaid with its own overrides.
            # This runs even when the layer overrides nothing: an overlay that inherits
            # everything still has to satisfy its OWN mark's channel contract. Silently
            # dropping an inherited channel the overlay can't draw is the "spec says one
            # thing, picture shows another" failure the whole design exists to prevent.
            overrides = layer.encodings.model_dump(exclude_none=True) if layer.encodings else {}
            merged = Encodings.model_validate({**self.encodings.model_dump(exclude_none=True), **overrides})
            _check_mark_channels(layer.mark.type, merged, where=f"layer[{i}]")

        if self.escape is not None and self.layers:
            raise _err(
                SpecError.ESCAPE_CONFLICT,
                "escape.mode='custom_code' with layers: the custom rail owns composition; "
                "drop the layers or drop the escape",
            )
        return self

    # ---- JSON <-> Pydantic lossless round-trip (P0.3) ---------------------------------
    def to_json_obj(self) -> dict[str, Any]:
        """
        D9: canonical form excludes None. None means "inherit/absent" everywhere in this
        grammar (see Style), so absent and null are the same statement — emitting both
        would give two encodings of one spec and break spec-diffing for patch mode (§7.7).
        """
        return self.model_dump(mode="json", exclude_none=True)

    @classmethod
    def from_json_obj(cls, obj: dict[str, Any]) -> ChartSpec:
        return cls.model_validate(obj)


# --------------------------------------------------------------------------------------
# D7: version compatibility. Adapters declare max_spec_version; compat is
# "same MAJOR and spec.MINOR <= adapter.MINOR" — additive grammar growth bumps MINOR,
# and a breaking change bumps MAJOR and orphans old adapters loudly.
# --------------------------------------------------------------------------------------
def adapter_supports(spec_version: str, adapter_max: str) -> tuple[bool, str]:
    s_major, s_minor = (int(p) for p in spec_version.split("."))
    a_major, a_minor = (int(p) for p in adapter_max.split("."))
    if s_major != a_major:
        return False, f"[{SpecError.SPEC_VERSION_UNSUPPORTED}] spec major {s_major} != adapter major {a_major}"
    if s_minor > a_minor:
        return False, (
            f"[{SpecError.SPEC_VERSION_UNSUPPORTED}] spec {spec_version} newer than adapter max {adapter_max}"
        )
    return True, f"ok: spec {spec_version} <= adapter {adapter_max}"


# --------------------------------------------------------------------------------------
# Phase-2 validation: the rules that need data, not just the spec.
# FINDING: cardinality caps (§8 "deterministic encoding rules") CANNOT run at spec
# construction — cardinality is a property of profile.json (issue #5), which the spec
# never carries. Validation is therefore two-phase, and only phase 1 is a grammar concern.
# --------------------------------------------------------------------------------------
MAX_COLOR_CARDINALITY = 12  # PROVISIONAL
MAX_FACET_CARDINALITY = 16  # PROVISIONAL


def validate_against_profile(spec: ChartSpec, profile: dict[str, Any]) -> list[str]:
    """Phase 2. Returns error strings; empty list == passes. `profile` is a #5 stand-in."""
    errors: list[str] = []
    columns: dict[str, dict[str, Any]] = profile.get("columns", {})

    referenced: list[tuple[str, Channel]] = []
    for name in ("x", "y", "color", "size", "facet"):
        ch = getattr(spec.encodings, name, None)
        if ch is not None:
            referenced.append((name, ch))
    for layer in spec.layers:
        if layer.encodings:
            for name in ("x", "y", "color", "size", "facet"):
                ch = getattr(layer.encodings, name, None)
                if ch is not None:
                    referenced.append((f"layer.{name}", ch))

    for name, ch in referenced:
        col = columns.get(ch.field)
        if col is None:
            errors.append(
                f"[{SpecError.FIELD_NOT_IN_PROFILE}] channel '{name}' references '{ch.field}', "
                f"absent from the transform output {sorted(columns)}"
            )
            continue
        cap = MAX_COLOR_CARDINALITY if name.endswith("color") else (MAX_FACET_CARDINALITY if name.endswith("facet") else None)
        if cap is not None and ch.type in CATEGORICAL:
            n = col.get("cardinality")
            if n is not None and n > cap:
                errors.append(
                    f"[{SpecError.COLOR_CARDINALITY_EXCEEDED}] channel '{name}' field '{ch.field}' has "
                    f"cardinality {n} > cap {cap}"
                )
    return errors
