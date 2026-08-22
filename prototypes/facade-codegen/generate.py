"""PROTOTYPE — throwaway. Generates the Pydantic facade from vocabulary.json.

    python generate.py build/vocab-0.5.1.json build/facade.py [strict|advisory]

Two modes, because the probe found properties[] is a UI-affordance registry, not
an input schema (see README "What properties[] actually is"):

  strict    what ADR-0002 Decision 7 assumed: extra='forbid', min/max as ge/le.
            Rejects 4 of the 30 real fixtures. Kept so the cost is visible.
  advisory  extra='allow', min/max as json_schema_extra. Admits all 30, still
            rejects invented enum values and wrong types.

No hand-written vocabulary anywhere in this file: every literal comes from the
bundle (ADR-0002 Decision 7). One model per (backend, chart type).
"""
import json
import keyword
import re
import sys

HEADER = '''# @generated from flint-chart@{version}, mode={mode} — DO NOT EDIT.
# Regenerate: node extract.mjs <bundle> vocab.json {version} && python generate.py vocab.json <out>
from typing import Literal, Optional
from pydantic import BaseModel, ConfigDict, Field

CHART_TYPES = {chart_types!r}
CHANNELS = {channels!r}
SEMANTIC_TYPES = {semantic_types!r}
THEME_PRESETS = {themes!r}

'''


def ident(name: str) -> str:
    s = re.sub(r"\W", "_", name)
    if s[0].isdigit() or keyword.iskeyword(s):
        s = "_" + s
    return s


def annotation(prop: dict, strict: bool) -> tuple[str, str]:
    """(type annotation, Field(...) call) for one ChartPropertyDef."""
    kind = prop["type"]
    default = prop["default"] if prop["has_default"] else None
    constraints = [f"default={default!r}"]

    if kind == "binary":
        ann = "Optional[bool]"
    elif kind == "continuous":
        ann = "Optional[float]"
        # min/max are SLIDER BOUNDS, not validation bounds: Bar Table.maxRows
        # declares min=5 yet 0 is a live "no limit" sentinel the corpus uses and
        # Flint honours. Only strict mode pretends otherwise.
        bounds = {k: prop[k] for k in ("min", "max", "step") if prop[k] is not None}
        if strict:
            if prop["min"] is not None:
                constraints.append(f"ge={prop['min']!r}")
            if prop["max"] is not None:
                constraints.append(f"le={prop['max']!r}")
            if prop["step"] is not None:
                constraints.append(f"json_schema_extra={{'step': {prop['step']!r}}}")
        elif bounds:
            constraints.append(f"json_schema_extra={bounds!r}")
    elif kind == "discrete":
        # options are canonical JSON strings; null == "leave unset".
        vals = [json.loads(o) for o in (prop["options"] or []) if o is not None]
        if vals and all(isinstance(v, str) for v in vals):
            ann = "Optional[Literal[" + ", ".join(repr(v) for v in vals) + "]]"
        else:
            # tuple-valued options (Map.projectionCenter) have no clean Literal.
            ann = "Optional[list]"
    else:
        raise SystemExit(f"unknown property type {kind!r} — bundle widened, regenerate deliberately")

    return ann, "Field(" + ", ".join(constraints) + ")"


def main() -> None:
    vocab = json.load(open(sys.argv[1]))
    mode = sys.argv[3] if len(sys.argv) > 3 else "advisory"
    if mode not in ("strict", "advisory"):
        raise SystemExit("mode must be strict or advisory")
    strict = mode == "strict"
    out = []
    all_charts = sorted({c for b in vocab["backends"].values() for c in b})
    out.append(HEADER.format(
        mode=mode,
        version=vocab["flint_version"],
        chart_types=all_charts,
        channels=vocab["channels"],
        semantic_types=vocab["semantic_types"],
        themes=vocab["theme_presets"],
    ))

    for backend, charts in sorted(vocab["backends"].items()):
        for chart, spec in sorted(charts.items()):
            cls = f"{ident(backend).title()}{ident(chart)}Properties"
            out.append(f"class {cls}(BaseModel):")
            out.append(f'    """{backend} / {chart}. channels: {", ".join(spec["channels"]) or "none"}"""')
            extra = "forbid" if strict else "allow"
            out.append(f"    model_config = ConfigDict(extra={extra!r})")
            if not spec["properties"]:
                out.append("    pass")
            for prop in spec["properties"]:
                ann, field = annotation(prop, strict)
                alias = "" if ident(prop["key"]) == prop["key"] else f", alias={prop['key']!r}"
                note = "  # data-dependent: check() runs client-side" if prop["data_dependent"] else ""
                out.append(f"    {ident(prop['key'])}: {ann} = {field[:-1]}{alias}){note}")
            out.append("")

    src = "\n".join(out)
    with open(sys.argv[2], "w") as fh:
        fh.write(src)
    n = src.count("class ")
    print(f"{sys.argv[2]}: {n} models, {len(all_charts)} chart types, mode={mode}", file=sys.stderr)


if __name__ == "__main__":
    main()
