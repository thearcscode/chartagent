// PROTOTYPE — throwaway. Answers ticket #17, nothing more.
//
// Reads a pinned Flint IIFE bundle and writes the machine-readable vocabulary
// the Python facade is generated from. Node runs here, at BUILD time only —
// never at install time, never at runtime (ADR-0001, amended 2026-08-22).
//
// Usage: node extract.mjs <bundle.iife.js> <out.json> [version]

import fs from "node:fs";
import vm from "node:vm";

const [, , bundlePath, outPath, version] = process.argv;
if (!bundlePath || !outPath) {
  console.error("usage: node extract.mjs <bundle.iife.js> <out.json> [version]");
  process.exit(2);
}

// structuredClone is the only global the bundle misses (flint-embed README).
const ctx = { console, structuredClone: (o) => JSON.parse(JSON.stringify(o)) };
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(bundlePath, "utf8"), ctx);
const F = ctx.Flint;
if (!F) throw new Error("bundle did not define the Flint global");

const BACKENDS = {
  vegalite: "vlAllTemplateDefs",
  echarts: "ecAllTemplateDefs",
  chartjs: "cjsAllTemplateDefs",
  plotly: "plAllTemplateDefs",
  excel: "excelAllTemplateDefs",
};

// An option is {value?, label}. `value` absent == "leave unset / template default".
// Canonicalise to a JSON string so ["105",35] and "105,35" can never collide —
// flattening these with join() produced phantom diffs (see README, gotcha 2).
const canonOption = (o) =>
  o && typeof o === "object" && "value" in o ? JSON.stringify(o.value) : null;

const missing = [];
const backends = {};

for (const [name, exportName] of Object.entries(BACKENDS)) {
  const defs = F[exportName];
  if (!defs) {
    missing.push(exportName); // a whole backend absent == breaking, see check_bump
    continue;
  }
  const charts = {};
  for (const d of defs) {
    charts[d.chart] = {
      channels: d.channels ?? [],
      mark_cognitive_channel: d.markCognitiveChannel ?? null,
      properties: (d.properties ?? []).map((p) => ({
        key: p.key,
        type: p.type, // continuous | binary | discrete
        label: p.label ?? null,
        // `defaultValue: undefined` is present-but-unset, and JSON.stringify
        // DROPS undefined-valued keys — coerce, or the key vanishes downstream.
        default: p.defaultValue ?? null,
        has_default: p.defaultValue !== undefined,
        min: p.min ?? null,
        max: p.max ?? null,
        step: p.step ?? null,
        options: p.options ? p.options.map(canonOption) : null,
        // check() is a JS closure over encodings, channelSemantics AND the data
        // rows. It cannot cross into Python. We record only that it exists.
        data_dependent: Boolean(p.check),
      })),
    };
  }
  backends[name] = charts;
}

const vocabulary = {
  flint_version: version ?? null,
  missing_exports: missing,
  channels: F.channels ?? [],
  channel_groups: F.channelGroups ?? {},
  semantic_types: Object.keys(F.SemanticTypes ?? {}),
  theme_presets: F.THEME_PRESETS ?? [],
  backends,
};

fs.writeFileSync(outPath, JSON.stringify(vocabulary, null, 2));

const nCharts = new Set(Object.values(backends).flatMap((c) => Object.keys(c))).size;
const nProps = Object.values(backends).reduce(
  (a, c) => a + Object.values(c).reduce((b, x) => b + x.properties.length, 0), 0);
console.error(
  `${outPath}: ${Object.keys(backends).length} backends, ${nCharts} distinct chart types, ${nProps} properties` +
  (missing.length ? `, MISSING ${missing.join(",")}` : "")
);
