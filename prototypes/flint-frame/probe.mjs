#!/usr/bin/env node
/**
 * Evidence probe for ADR-0002 (adopt Flint's input frame as our spec).
 *
 * MEASUREMENT ONLY — not the integration. See README.md.
 *
 *   node probe.mjs survey     what keys the frame actually has, across 705 fixtures
 *   node probe.mjs transparency  does an unknown key change the compiled output?
 *   node probe.mjs churn      which parts of the frame the changelog has broken
 *
 * Reuses ../flint-embed/build/ so there is one pinned Flint in the repo.
 */

import { readFileSync, readdirSync, existsSync } from 'fs';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';

const HERE = dirname(fileURLToPath(import.meta.url));
const BUILD = join(HERE, '..', 'flint-embed', 'build');
const DIST = join(BUILD, 'npm', 'package', 'dist', 'index.js');
const FIXTURES = join(BUILD, 'fixtures');

if (!existsSync(DIST) || !existsSync(FIXTURES)) {
  console.error('missing ../flint-embed/build — run ../flint-embed/setup.sh first');
  process.exit(1);
}

const Flint = await import(DIST);

const BACKENDS = {
  vegalite: Flint.assembleVegaLite,
  echarts: Flint.assembleECharts,
  chartjs: Flint.assembleChartjs,
  plotly: Flint.assemblePlotly,
  excel: Flint.assembleExcel,
};

function cases() {
  return readdirSync(FIXTURES)
    .sort()
    .map((name) => {
      const path = join(FIXTURES, name, 'input.json');
      if (!existsSync(path)) return null;
      try {
        return { name, input: JSON.parse(readFileSync(path, 'utf8')).input };
      } catch {
        return null;
      }
    })
    .filter(Boolean);
}

// `_`-prefixed keys are compiler metadata (_width, _warnings, _transform), not
// output. Canonicalise in one language only — see ../flint-embed/README.md.
function strip(value) {
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

const canon = (value) => JSON.stringify(strip(value));

function tally(rows, pick) {
  const counts = new Map();
  for (const row of rows) for (const key of pick(row)) counts.set(key, (counts.get(key) ?? 0) + 1);
  return [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
}

function table(title, entries, total) {
  console.log(`\n${title}`);
  for (const [key, n] of entries) {
    const pct = ((n / total) * 100).toFixed(0).padStart(3);
    console.log(`  ${String(n).padStart(4)} ${pct}%  ${key}`);
  }
}

// ---------------------------------------------------------------------------

function survey() {
  const all = cases();
  console.log(`${all.length} fixtures`);

  table('top-level keys of the assembler argument', tally(all, (c) => Object.keys(c.input)), all.length);
  table(
    'chart_spec keys',
    tally(all, (c) => Object.keys(c.input.chart_spec ?? {})),
    all.length,
  );
  table(
    'chartProperties keys',
    tally(all, (c) => Object.keys(c.input.chart_spec?.chartProperties ?? {})),
    all.length,
  );
  table(
    'encoding channels',
    tally(all, (c) => Object.keys(c.input.chart_spec?.encodings ?? {})),
    all.length,
  );

  // What a channel is allowed to say matters more than how many there are: if a
  // channel could aggregate, the transform boundary this project depends on
  // would not survive adoption.
  const channelObjects = all.flatMap((c) =>
    Object.values(c.input.chart_spec?.encodings ?? {})
      .flatMap((ch) => (Array.isArray(ch) ? ch : [ch]))
      .filter((ch) => ch && typeof ch === 'object'),
  );
  table(
    `keys inside an encoding channel (of ${channelObjects.length} channels)`,
    tally(channelObjects, Object.keys),
    channelObjects.length,
  );
  table(
    'options keys',
    tally(all, (c) => Object.keys(c.input.options ?? {})),
    all.length,
  );

  const types = new Set();
  for (const c of all) if (c.input.chart_spec?.chartType) types.add(c.input.chart_spec.chartType);
  console.log(`\n${types.size} distinct chartType strings — an open vocabulary, not a closed union`);

  const hasNull = (v) =>
    v === null ||
    (Array.isArray(v) ? v.some(hasNull) : v && typeof v === 'object' ? Object.values(v).some(hasNull) : false);
  const nulls = all.filter((c) => hasNull(c.input)).length;
  const arrays = all.filter((c) =>
    Object.values(c.input.chart_spec?.encodings ?? {}).some(Array.isArray),
  ).length;
  console.log(`${nulls} fixtures contain an explicit null anywhere in the document`);
  console.log(`${arrays} fixtures use an array-valued encoding channel`);
}

// ---------------------------------------------------------------------------
// The load-bearing question: can we carry our own grammar in this document
// without perturbing what Flint compiles?

const PROBE = {
  spec_version: '2.0',
  transform: { group_by: ['quarter'], aggregate: [{ op: 'sum', field: 'revenue' }] },
  annotations: [{ kind: 'band', from: '2026-01', to: '2026-03', label: 'launch' }],
  interactions: { hover: 'nearest' },
  escape: null,
};

function transparency() {
  const all = cases();
  const results = {};

  for (const [backend, assemble] of Object.entries(BACKENDS)) {
    const r = { same: 0, differs: [], errored: 0, baseFailed: 0 };
    for (const { name, input } of all) {
      let base;
      try {
        base = canon(assemble(input));
      } catch {
        r.baseFailed += 1;
        continue;
      }
      try {
        const withKey = canon(assemble({ ...input, x_chartagent: PROBE }));
        if (withKey === base) r.same += 1;
        else r.differs.push(name);
      } catch {
        r.errored += 1;
      }
    }
    results[backend] = r;
  }

  console.log(`sibling key \`x_chartagent\` added to ${all.length} fixtures, per backend:\n`);
  for (const [backend, r] of Object.entries(results)) {
    const note = [
      r.differs.length ? `${r.differs.length} DIFFER (${r.differs.slice(0, 3).join(', ')})` : 'byte-identical',
      r.errored ? `${r.errored} threw` : null,
      r.baseFailed ? `${r.baseFailed} unsupported by this backend` : null,
    ]
      .filter(Boolean)
      .join(', ');
    console.log(`  ${backend.padEnd(9)} ${String(r.same).padStart(4)} unchanged  ${note}`);
  }

  // Contrast: the same payload inside chartProperties, the "sanctioned open bag".
  console.log('\nsame payload nested in chart_spec.chartProperties instead:\n');
  for (const [backend, assemble] of Object.entries(BACKENDS)) {
    let same = 0;
    let differs = 0;
    let threw = 0;
    let baseFailed = 0;
    for (const { input } of all) {
      let base;
      try {
        base = canon(assemble(input));
      } catch {
        baseFailed += 1;
        continue;
      }
      const nested = {
        ...input,
        chart_spec: {
          ...input.chart_spec,
          chartProperties: { ...(input.chart_spec?.chartProperties ?? {}), x_chartagent: PROBE },
        },
      };
      try {
        canon(assemble(nested)) === base ? (same += 1) : (differs += 1);
      } catch {
        threw += 1;
      }
    }
    console.log(
      `  ${backend.padEnd(9)} ${String(same).padStart(4)} unchanged, ${differs} differ, ${threw} threw` +
        (baseFailed ? `, ${baseFailed} unsupported` : ''),
    );
  }

  // `_warnings` is stripped by canon(), so silence there has to be checked
  // separately: an ignored key and a key that provokes a complaint would both
  // read as "byte-identical" above.
  const warnings = (spec) => JSON.stringify(spec?._warnings ?? []);
  let baseline = 0;
  let changedBySibling = 0;
  let changedByNesting = 0;
  for (const { input } of all) {
    let base;
    try {
      base = warnings(Flint.assembleVegaLite(input));
    } catch {
      continue;
    }
    if (base !== '[]') baseline += 1;
    const sibling = warnings(Flint.assembleVegaLite({ ...input, x_chartagent: PROBE }));
    const nested = warnings(
      Flint.assembleVegaLite({
        ...input,
        chart_spec: {
          ...input.chart_spec,
          chartProperties: { ...(input.chart_spec?.chartProperties ?? {}), x_chartagent: PROBE },
        },
      }),
    );
    if (sibling !== base) changedBySibling += 1;
    if (nested !== base) changedByNesting += 1;
  }
  console.log(`\n_warnings (Vega-Lite): ${baseline}/${all.length} fixtures warn about something already;`);
  console.log(`  sibling key changes that set on ${changedBySibling}, chartProperties on ${changedByNesting}`);

  // Deleting the key must return the document to something upstream compiles.
  const { input } = all[0];
  const carried = { ...input, x_chartagent: PROBE };
  const { x_chartagent, ...stripped } = carried;
  console.log(
    `\ndelete x_chartagent -> identical to the original document: ${canon(stripped) === canon(input)}`,
  );
}

// ---------------------------------------------------------------------------

function churn() {
  const pkg = JSON.parse(readFileSync(join(BUILD, 'npm', 'package', 'package.json'), 'utf8'));
  console.log(`flint-chart ${pkg.version}`);
  console.log(`runtime dependencies: ${Object.keys(pkg.dependencies ?? {}).length}`);
  console.log(`peer (render-only)  : ${Object.keys(pkg.peerDependencies ?? {}).join(', ')}`);

  const all = cases();
  const withProps = all.filter((c) => c.input.chart_spec?.chartProperties);
  console.log(
    `\nfixtures carrying chartProperties: ${withProps.length}/${all.length} ` +
      `(${((withProps.length / all.length) * 100).toFixed(0)}%)`,
  );
  console.log('Every breaking change in the 0.2.1 -> 0.5.1 changelog is a chartProperties');
  console.log('key removal. The typed frame around it has only ever grown.');
}

const COMMANDS = { survey, transparency, churn };
const command = COMMANDS[process.argv[2]];
if (!command) {
  console.error('usage: node probe.mjs survey | transparency | churn');
  process.exit(1);
}
command();
