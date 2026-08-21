# PROTOTYPE — THROWAWAY

Measurement harness behind `docs/research/rasterisation-options.md`, which is research for
[issue #22](https://github.com/thearcscode/chartagent/issues/22). **Measurement only — not the
integration, and not a decision.** The decision belongs to issue #23.

The question: PRD P0.7 makes a VLM critique of every chart a P0, and a VLM critique needs a
rendered image — but ADR-0001 Decision 5 says the browser is the renderer and there is no Node
in production. So what can rasterise Flint's output without a browser and without Node?

## What each probe answers

| script | question |
| --- | --- |
| `vlconvert_probe.py` | Can `vl-convert` (Rust + embedded V8 + resvg, no Node, no browser) rasterise all 705 Flint Vega-Lite outputs, at what cost, with what font, and does it need the network? |
| `dump_echarts.py` | Compiles the 705 upstream fixtures to the ECharts backend so the SSR probe has real input. |
| `echarts_ssr_probe.py` | Does ECharts' zero-dependency SSR SVG renderer run inside the *same* embedded engine ADR-0001 already puts in the CPython process? |
| `echarts_svg_to_png.py` | Does that SSR SVG survive resvg, and is the resulting PNG stable? |
| `coload_probe.py` | Is it safe to have V8 (vl-convert) in the same interpreter as QuickJS or PythonMonkey? **Read §5 of the findings first — this probe is not demonstrably sensitive.** |

## Setup

Depends on `../flint-embed` having been built (`./setup.sh` there, which produces
`build/flint.iife.js`, `build/fixtures/` and `build/specs_node.json`).

```
# ECharts bundle for the SSR probes
mkdir -p build/npm && cd build/npm
npm pack echarts@5.6.0 && tar xzf echarts-5.6.0.tgz && cd ../..

# vl-convert into the flint-embed venv (it has quickjs and pythonmonkey already)
../flint-embed/.venv/bin/pip install vl-convert-python
```

Then run the commands listed under "Reproducing" in the findings document.

Note the two engines must never be co-loaded (ADR-0001), so `echarts_ssr_probe.py` takes the
engine name as an argument and is run once per engine.

`build/` is gitignored apart from the two comparison images the findings document embeds.
