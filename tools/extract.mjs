// Build-time only. Reads the pinned Flint IIFE and writes vocab.json.
// Node never runs at install or import (ADR-0001).
//
// Usage: node tools/extract.mjs <bundle.iife.js> <out.json> [version]
//
// Decisions lifted from prototypes/facade-codegen/extract.mjs:
//   - read properties[] AND encodingActions[] (317 entries together)
//   - defaultValue: undefined is present-but-unset; coerce with ?? null
//   - options keep {value, label}; value may be an array
//   - check() / isApplicable() become data_dependent, never ported

import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import vm from "node:vm";

const [, , bundlePath, outPath, versionArg] = process.argv;
if (!bundlePath || !outPath) {
  console.error("usage: node tools/extract.mjs <bundle.iife.js> <out.json> [version]");
  process.exit(2);
}

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const version =
  versionArg ??
  fs.readFileSync(path.join(repoRoot, "prototypes/flint-embed/FLINT_VERSION"), "utf8").trim();

const bundleBytes = fs.readFileSync(bundlePath);
const bundle_sha256 = crypto.createHash("sha256").update(bundleBytes).digest("hex");

const ctx = { console, structuredClone: (o) => JSON.parse(JSON.stringify(o)) };
vm.createContext(ctx);
vm.runInContext(bundleBytes.toString("utf8"), ctx);
const F = ctx.Flint;
if (!F) throw new Error("bundle did not define the Flint global");

const BACKENDS = {
  vegalite: "vlAllTemplateDefs",
  echarts: "ecAllTemplateDefs",
  chartjs: "cjsAllTemplateDefs",
  plotly: "plAllTemplateDefs",
  excel: "excelAllTemplateDefs",
};

const missing = [];
const backends = {};

for (const [name, exportName] of Object.entries(BACKENDS)) {
  const defs = F[exportName];
  if (!defs) {
    missing.push(exportName);
    continue;
  }
  const charts = {};
  for (const d of defs) {
    const actions = (d.encodingActions ?? []).map((a) => ({
      key: a.key,
      label: a.label ?? null,
      type: a.control?.type ?? null,
      defaultValue: undefined,
      min: a.control?.min,
      max: a.control?.max,
      step: a.control?.step,
      options: a.control?.options,
      check: a.isApplicable,
      source: "encodingActions",
      dependencies: a.dependencies ?? [],
    }));
    charts[d.chart] = {
      channels: d.channels ?? [],
      mark_cognitive_channel: d.markCognitiveChannel ?? null,
      properties: [...(d.properties ?? []), ...actions].map((p) => ({
        key: p.key,
        type: p.type,
        label: p.label ?? null,
        default: p.defaultValue ?? null,
        has_default: p.defaultValue !== undefined,
        min: p.min ?? null,
        max: p.max ?? null,
        step: p.step ?? null,
        options: p.options
          ? p.options.map((o) => ({
              value: o && typeof o === "object" && "value" in o ? o.value : null,
              label: o?.label ?? null,
            }))
          : null,
        source: p.source ?? "properties",
        dependencies: p.dependencies ?? [],
        data_dependent: Boolean(p.check),
      })),
    };
  }
  backends[name] = charts;
}

const vocabulary = {
  flint_version: version,
  bundle_sha256,
  missing_exports: missing,
  channels: F.channels ?? [],
  channel_groups: F.channelGroups ?? {},
  semantic_types: Object.keys(F.SemanticTypes ?? {}),
  theme_presets: F.THEME_PRESETS ?? {},
  backends,
};

fs.writeFileSync(outPath, JSON.stringify(vocabulary, null, 2) + "\n");

const nCharts = new Set(Object.values(backends).flatMap((c) => Object.keys(c))).size;
const nProps = Object.values(backends).reduce(
  (a, c) => a + Object.values(c).reduce((b, x) => b + x.properties.length, 0),
  0,
);
console.error(
  `${outPath}: ${Object.keys(backends).length} backends, ${nCharts} distinct chart types, ${nProps} properties` +
    (missing.length ? `, MISSING ${missing.join(",")}` : ""),
);
