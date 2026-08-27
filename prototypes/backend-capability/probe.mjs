// PROTOTYPE — throwaway. Answers ticket #9, nothing more.
//
// Every number in ADR-0012 comes from this file. It compiles the 705-fixture corpus
// through all five pinned Flint assemblers and asks three questions:
//
//   1. Which refusals does the pin's per-backend chart-type list predict?
//   2. Which refusals survive a change to the rows alone, with the spec untouched?
//   3. Is `excel + (column|row)` exactly the faceting refusal, in both directions?
//
// Node runs here at probe time only. It is never on the compile path (ADR-0001,
// amended 2026-08-22) and never at install time (#19 §9 — the bundle is vendored).
//
// Usage, from prototypes/flint-embed (which owns the corpus and the bundle):
//   node ../backend-capability/probe.mjs

import fs from "node:fs";
import vm from "node:vm";
import path from "node:path";

const BUNDLE = "build/flint.iife.js";
const ROOT = "build/fixtures";
const VOCAB = "../facade-codegen/build/vocab-0.5.1.json";

// structuredClone is the only global the bundle misses (flint-embed README).
const ctx = { console, structuredClone: (o) => JSON.parse(JSON.stringify(o)) };
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(BUNDLE, "utf8"), ctx);
const F = ctx.Flint;

const ASSEMBLE = {
  vegalite: F.assembleVegaLite, echarts: F.assembleECharts,
  chartjs: F.assembleChartjs, plotly: F.assemblePlotly, excel: F.assembleExcel,
};
const DECLARED = Object.fromEntries(
  Object.entries(JSON.parse(fs.readFileSync(VOCAB, "utf8")).backends)
    .map(([b, charts]) => [b, new Set(Object.keys(charts))]),
);

const clone = (o) => JSON.parse(JSON.stringify(o));
const run = (fn, frame) => {
  try { fn(clone(frame)); return null; } catch (e) { return String(e?.message ?? e); }
};

const dirs = fs.readdirSync(ROOT)
  .filter((d) => fs.existsSync(path.join(ROOT, d, "input.json")))
  .sort();
const corpus = dirs.map((d) => {
  const raw = JSON.parse(fs.readFileSync(path.join(ROOT, d, "input.json"), "utf8"));
  return { name: d, chartType: raw.chartType, frame: raw.input };
});

// ── 1. What does the declared chart-type list predict? ───────────────────────
// Excel's refusals are classified by the message, because it is the one backend
// that refuses for more than one reason.
const classify = (m) =>
  m === null ? "accepted"
  : /does not support chart type|Unknown .* chart type/.test(m) ? "type_undeclared"
  : /faceting/.test(m) ? "facet"
  : "other";

const predicted = {};
for (const [backend, fn] of Object.entries(ASSEMBLE)) {
  const c = { accepted: 0, type_undeclared: 0, facet: 0, other: 0, undeclared_and_accepted: 0 };
  for (const { chartType, frame } of corpus) {
    const kind = classify(run(fn, frame));
    c[kind]++;
    if (kind === "accepted" && !DECLARED[backend].has(chartType)) c.undeclared_and_accepted++;
  }
  predicted[backend] = c;
}

// ── 2. Does a change to the rows alone change the verdict? ───────────────────
// The dangerous direction is accepted -> refused: that is a saved chart breaking
// on a zero-LLM refresh, with nobody having touched the spec.
const mutations = {
  zero_rows: (f) => { const c = clone(f); if (c.data?.values) c.data.values = []; return c; },
  one_row: (f) => { const c = clone(f); if (c.data?.values) c.data.values = c.data.values.slice(0, 1); return c; },
  reversed: (f) => { const c = clone(f); if (c.data?.values) c.data.values = c.data.values.slice().reverse(); return c; },
};
const rowSensitivity = {};
for (const [backend, fn] of Object.entries(ASSEMBLE)) {
  const c = Object.fromEntries(Object.keys(mutations).map((m) => [m, 0]));
  for (const { frame } of corpus) {
    if (run(fn, frame) !== null) continue;            // only the accepted set
    for (const [m, mutate] of Object.entries(mutations)) {
      if (run(fn, mutate(frame)) !== null) c[m]++;
    }
  }
  rowSensitivity[backend] = { accepted_today: predicted[backend].accepted, refuse_after: c };
}

// ── 3. Is `excel + (column|row)` exactly the faceting refusal? ───────────────
// This is the biconditional ADR-0012 Decision 4 puts on fixtures-invariant.
const facet = { rule_holds: 0, faceted_refused_earlier: 0, faceted_accepted: 0,
                facet_refusal_without_facet_channel: 0, unfaceted: 0 };
for (const { frame } of corpus) {
  const enc = frame.chart_spec?.encodings ?? {};
  const hasFacetChannel = "column" in enc || "row" in enc;
  const kind = classify(run(ASSEMBLE.excel, frame));
  if (hasFacetChannel && kind === "facet") facet.rule_holds++;
  else if (hasFacetChannel && kind === "accepted") facet.faceted_accepted++;
  else if (hasFacetChannel) facet.faceted_refused_earlier++;
  else if (kind === "facet") facet.facet_refusal_without_facet_channel++;
  else facet.unfaceted++;
}

// The rule must also read nothing but the encoding key set. If deleting
// semantic_types or rewriting every row changes one verdict, it is type inference
// wearing a channel name, and Decision 3 does not hold.
const facetStability = { checked: 0, stable: 0 };
for (const { frame } of corpus) {
  const enc = frame.chart_spec?.encodings ?? {};
  if (!("column" in enc || "row" in enc)) continue;
  const base = run(ASSEMBLE.excel, frame);
  if (!/faceting/.test(base ?? "")) continue;
  facetStability.checked++;
  const variants = [
    ...Object.values(mutations).map((m) => m(frame)),
    (() => { const c = clone(frame); delete c.semantic_types; return c; })(),
    (() => {                                          // every value to a string
      const c = clone(frame);
      if (c.data?.values) c.data.values = c.data.values.map((r) =>
        Object.fromEntries(Object.entries(r).map(([k, v]) => [k, String(v)])));
      return c;
    })(),
  ];
  if (variants.every((v) => run(ASSEMBLE.excel, v) === base)) facetStability.stable++;
}

console.log(JSON.stringify(
  { flint: "0.5.1", fixtures: corpus.length, predicted, rowSensitivity, facet, facetStability },
  null, 2));
