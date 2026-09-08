// Shared helpers for the fixture CI jobs.

import { existsSync, readFileSync, readdirSync } from "node:fs";
import path from "node:path";
import vm from "node:vm";

// rowCount, pinSize, strip, canon and clone are browser-safe (no `node:`
// imports, no filesystem access) and live in flint-predicates.mjs so the
// corpus recorder's paint leg (#122) can load the same definitions in a
// browser. Re-exported here so every existing caller of flint-lib.mjs is
// untouched (#123).
import { canon, clone, pinSize, rowCount, strip } from "./flint-predicates.mjs";
export { canon, clone, pinSize, rowCount, strip };

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

export function compile(fn, input) {
  try {
    return { ok: true, value: fn(clone(input)) };
  } catch (err) {
    return { ok: false, error: String(err?.message ?? err) };
  }
}
