// Shared helpers for the fixture CI jobs. strip/canon are copied verbatim
// from prototypes/flint-frame/probe.mjs (ADR-0004 Decision 7).

import { existsSync, readFileSync, readdirSync } from "node:fs";
import path from "node:path";
import vm from "node:vm";

export const EXPECTED_FIXTURES = 705;
export const EXCEL_FACET_REFUSALS = 102;

// Current x_chartagent key list (ADR-0018): five keys, no escape.
export const X_CHARTAGENT = {
  spec_version: "1.2",
  transform: {
    group_by: ["quarter"],
    aggregate: [{ name: "revenue_sum", op: "sum", field: "revenue" }],
  },
  annotations: [{ kind: "band", from: "2026-01", to: "2026-03", label: "launch" }],
  interactions: { hover: "nearest" },
  source_schema: { quarter: "date", revenue: "number" },
};

export function loadBundle(bundlePath) {
  const ctx = { console, structuredClone: (o) => JSON.parse(JSON.stringify(o)) };
  vm.createContext(ctx);
  vm.runInContext(readFileSync(bundlePath, "utf8"), ctx);
  if (!ctx.Flint) throw new Error(`bundle did not define Flint: ${bundlePath}`);
  return ctx.Flint;
}

export function assemblers(Flint) {
  return {
    vegalite: Flint.assembleVegaLite,
    echarts: Flint.assembleECharts,
    chartjs: Flint.assembleChartjs,
    plotly: Flint.assemblePlotly,
    excel: Flint.assembleExcel,
  };
}

export function loadFixtures(root) {
  return readdirSync(root)
    .sort()
    .map((name) => {
      const file = path.join(root, name, "input.json");
      if (!existsSync(file)) return null;
      const raw = JSON.parse(readFileSync(file, "utf8"));
      if (!raw.input) return null;
      return { name, input: raw.input };
    })
    .filter(Boolean);
}

export function pinSize(input) {
  const baseSize = input.chart_spec?.baseSize;
  if (!baseSize) return input;
  return {
    ...input,
    chart_spec: { ...input.chart_spec, canvasSize: { ...baseSize } },
  };
}

// `_`-prefixed keys are compiler metadata (_width, _warnings, _transform), not
// output. Canonicalise in one language only — see prototypes/flint-embed/README.md.
export function strip(value) {
  if (Array.isArray(value)) return value.map(strip);
  if (value && typeof value === 'object') {
    return Object.fromEntries(
      Object.keys(value)
        .filter((k) => !k.startsWith('_'))
        .sort()
        .map((k) => [k, strip(value[k])]),
    );
  }
  return value;
}

export const canon = (value) => JSON.stringify(strip(value));

export function meta(spec) {
  if (!spec || typeof spec !== "object") return "";
  return JSON.stringify({
    _warnings: spec._warnings ?? [],
    _width: spec._width,
    _transform: spec._transform,
    _pivot: spec._pivot,
  });
}

export function warningsMeta(spec) {
  if (!spec || typeof spec !== "object") return "";
  return JSON.stringify(spec._warnings ?? []);
}

export function rowCount(output) {
  if (!output || typeof output !== "object") return null;
  if (typeof output._dataLength === "number") return output._dataLength;
  if (Array.isArray(output.data?.values)) return output.data.values.length;
  if (output.schema === "flint.excel.chart/v1" && Array.isArray(output.data)) {
    return Math.max(0, output.data.length - 1);
  }
  return null;
}

export function dirtyPairs(input, vocab) {
  const chartType = input.chart_spec?.chartType;
  const props = input.chart_spec?.chartProperties ?? {};
  const declared = new Set();
  for (const backend of Object.values(vocab.backends ?? {})) {
    const spec = backend[chartType];
    if (!spec) continue;
    for (const prop of spec.properties ?? []) declared.add(prop.key);
  }
  return Object.keys(props)
    .filter((key) => !declared.has(key))
    .map((key) => `${chartType}.${key}`);
}

export function classifyExcel(err) {
  if (err == null) return "accepted";
  const message = String(err?.message ?? err);
  if (/does not support chart type|Unknown .* chart type/.test(message)) {
    return "type_undeclared";
  }
  if (/faceting/.test(message)) return "facet";
  return "other";
}

export function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

export function compile(fn, input) {
  try {
    return { ok: true, value: fn(clone(input)) };
  } catch (err) {
    return { ok: false, error: String(err?.message ?? err) };
  }
}
