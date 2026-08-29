"""Generate the Pydantic façade from vocab.json. Keys mode only.

Usage: python tools/generate.py <vocab.json> <out.py>

Unknown property keys are forbidden. Declared min/max/step go in
json_schema_extra and are never Pydantic ge/le (ADR-0009).
"""

from __future__ import annotations

import json
import keyword
import re
import sys
from pathlib import Path

HEADER = '''\
# @generated from flint-chart@{version} — DO NOT EDIT.
# Regenerate: node tools/extract.mjs <bundle> src/chartagent/frame/vocab.json \\
#             && python tools/generate.py src/chartagent/frame/vocab.json <out>
from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field

FLINT_VERSION = {version!r}
BUNDLE_SHA256 = {bundle_sha256!r}
CHART_TYPES = {chart_types!r}
CHANNELS = {channels!r}
SEMANTIC_TYPES = {semantic_types!r}
THEME_PRESETS = {themes!r}

ChartType = Literal[{chart_type_literal}]
SemanticTypeName = Literal[{semantic_literal}]
ThemePresetName = Literal[{theme_literal}]


class GeneratedProperties(BaseModel):
    """Per-(backend, chart type) chartProperties model. extra='forbid', keys mode."""

    model_config = ConfigDict(extra="forbid")
    flint_version: ClassVar[str] = FLINT_VERSION
    bundle_sha256: ClassVar[str] = BUNDLE_SHA256

'''


def ident(name: str) -> str:
    s = re.sub(r"\W", "_", name)
    if s[0].isdigit() or keyword.iskeyword(s):
        s = "_" + s
    return s


def model_name(backend: str, chart: str) -> str:
    return f"{ident(backend).title()}{ident(chart)}Properties"


def annotation(prop: dict[str, object]) -> tuple[str, str]:
    kind = prop["type"]
    default = prop["default"] if prop["has_default"] else None
    constraints = [f"default={default!r}"]

    if kind == "binary":
        ann = "bool | None"
    elif kind == "continuous":
        ann = "float | None"
        bounds = {k: prop[k] for k in ("min", "max", "step") if prop[k] is not None}
        if bounds:
            constraints.append(f"json_schema_extra={bounds!r}")
    elif kind == "discrete":
        raw_options = prop["options"] or []
        vals = [
            o["value"]
            for o in raw_options  # type: ignore[union-attr]
            if isinstance(o, dict) and o.get("value") is not None
        ]
        if vals and all(isinstance(v, str) for v in vals):
            ann = "Literal[" + ", ".join(repr(v) for v in vals) + "] | None"
        else:
            ann = "list[object] | None"
    elif kind is None:
        ann = "object | None"
    else:
        raise SystemExit(f"unknown property type {kind!r} — bundle widened, regenerate deliberately")

    return ann, "Field(" + ", ".join(constraints) + ")"


def theme_names(theme_presets: object) -> list[str]:
    if isinstance(theme_presets, dict):
        return list(theme_presets)
    if isinstance(theme_presets, list):
        return [str(t) for t in theme_presets]
    return []


def main() -> None:
    vocab_path = Path(sys.argv[1])
    out_path = Path(sys.argv[2])
    vocab = json.loads(vocab_path.read_text(encoding="utf-8"))

    all_charts = sorted({c for b in vocab["backends"].values() for c in b})
    themes = theme_names(vocab["theme_presets"])
    out: list[str] = [
        HEADER.format(
            version=vocab["flint_version"],
            bundle_sha256=vocab["bundle_sha256"],
            chart_types=all_charts,
            channels=vocab["channels"],
            semantic_types=vocab["semantic_types"],
            themes=themes,
            chart_type_literal=", ".join(repr(c) for c in all_charts),
            semantic_literal=", ".join(repr(s) for s in vocab["semantic_types"]),
            theme_literal=", ".join(repr(t) for t in themes),
        )
    ]

    model_names: list[str] = []
    for backend, charts in sorted(vocab["backends"].items()):
        for chart, spec in sorted(charts.items()):
            cls = model_name(backend, chart)
            model_names.append(cls)
            channels = ", ".join(spec["channels"]) or "none"
            out.append(f"class {cls}(GeneratedProperties):")
            out.append(f'    """{backend} / {chart}. channels: {channels}"""')
            props = spec["properties"]
            if not props:
                out.append("    pass")
            for prop in props:
                ann, field = annotation(prop)
                alias = "" if ident(prop["key"]) == prop["key"] else f", alias={prop['key']!r}"
                note = (
                    "  # data-dependent: check() runs client-side" if prop["data_dependent"] else ""
                )
                out.append(f"    {ident(prop['key'])}: {ann} = {field[:-1]}{alias}){note}")
            out.append("")

    out.append("__all__ = [")
    for name in (
        "FLINT_VERSION",
        "BUNDLE_SHA256",
        "CHART_TYPES",
        "CHANNELS",
        "SEMANTIC_TYPES",
        "THEME_PRESETS",
        "ChartType",
        "SemanticTypeName",
        "ThemePresetName",
        "GeneratedProperties",
        *model_names,
    ):
        out.append(f"    {name!r},")
    out.append("]")
    out.append("")

    src = "\n".join(out)
    out_path.write_text(src, encoding="utf-8")
    print(
        f"{out_path}: {len(model_names)} models, {len(all_charts)} chart types, mode=keys",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
