#!/usr/bin/env node
// Differential bump gate (ADR-0004 Decision 5). Compares the IIFE we shipped
// against the IIFE we are about to ship. Never reads expected.json.
//
//   node tools/flint-bump.mjs <old.iife.js> <new.iife.js> <fixtures> <manifest.json>

import { readFileSync } from "node:fs";

import {
  assemblers,
  canon,
  compile,
  loadBundle,
  loadFixtures,
  pinSize,
  rowCount,
  warningsMeta,
} from "./flint-lib.mjs";

const [, , oldBundle, newBundle, fixturesDir, manifestPath] = process.argv;
if (!oldBundle || !newBundle || !fixturesDir || !manifestPath) {
  console.error(
    "usage: node tools/flint-bump.mjs <old.iife.js> <new.iife.js> <fixtures> <manifest.json>",
  );
  process.exit(2);
}

const oldAssemble = assemblers(loadBundle(oldBundle));
const newAssemble = assemblers(loadBundle(newBundle));
const fixtures = loadFixtures(fixturesDir);
const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));

const measured = {
  row_count_changed: new Set(),
  supported_to_unsupported: new Set(),
};
const report = {
  unsupported_to_supported: [],
  threw_differently: [],
  output_differs: [],
  warnings_changed: [],
};
const perBackend = {};

function keyOf(backend, name) {
  return `${backend}/${name}`;
}

for (const backend of Object.keys(newAssemble)) {
  perBackend[backend] = {
    row_count_changed: 0,
    supported_to_unsupported: 0,
    unsupported_to_supported: 0,
    threw_differently: 0,
    output_differs: 0,
    warnings_changed: 0,
    unchanged: 0,
  };
}

for (const { name, input } of fixtures) {
  const frame = pinSize(input);
  for (const backend of Object.keys(newAssemble)) {
    const before = compile(oldAssemble[backend], frame);
    const after = compile(newAssemble[backend], frame);
    const id = keyOf(backend, name);
    const counts = perBackend[backend];

    if (before.ok && after.ok) {
      const rowsBefore = rowCount(before.value);
      const rowsAfter = rowCount(after.value);
      if (rowsBefore !== rowsAfter) {
        measured.row_count_changed.add(id);
        counts.row_count_changed += 1;
      } else if (canon(before.value) !== canon(after.value)) {
        report.output_differs.push(id);
        counts.output_differs += 1;
      } else {
        counts.unchanged += 1;
      }
      if (warningsMeta(before.value) !== warningsMeta(after.value)) {
        report.warnings_changed.push(id);
        counts.warnings_changed += 1;
      }
      continue;
    }
    if (before.ok && !after.ok) {
      measured.supported_to_unsupported.add(id);
      counts.supported_to_unsupported += 1;
      continue;
    }
    if (!before.ok && after.ok) {
      report.unsupported_to_supported.push(id);
      counts.unsupported_to_supported += 1;
      continue;
    }
    if (before.error !== after.error) {
      report.threw_differently.push(id);
      counts.threw_differently += 1;
    } else {
      counts.unchanged += 1;
    }
  }
}

function asSet(list) {
  return new Set(list ?? []);
}

function setDiff(measuredSet, expectedSet) {
  return {
    extra: [...measuredSet].filter((id) => !expectedSet.has(id)).sort(),
    stale: [...expectedSet].filter((id) => !measuredSet.has(id)).sort(),
  };
}

const expectedRows = asSet(manifest.row_count_changed);
const expectedDrop = asSet(manifest.supported_to_unsupported);
const rowDiff = setDiff(measured.row_count_changed, expectedRows);
const dropDiff = setDiff(measured.supported_to_unsupported, expectedDrop);
const newRows = rowDiff.extra;
const staleRows = rowDiff.stale;
const newDrops = dropDiff.extra;
const staleDrops = dropDiff.stale;

console.log(`flint-bump: ${fixtures.length} fixtures × 5 backends\n`);
for (const [backend, counts] of Object.entries(perBackend)) {
  console.log(`  ${backend}`);
  console.log(`    (1) row count changed          ${counts.row_count_changed}`);
  console.log(`    (2) supported → unsupported    ${counts.supported_to_unsupported}`);
  console.log(`    (3) unsupported → supported    ${counts.unsupported_to_supported}`);
  console.log(`    (4) threw differently          ${counts.threw_differently}`);
  console.log(`    (5) output differs, same rows  ${counts.output_differs}`);
  console.log(`    (6) _warnings changed          ${counts.warnings_changed}`);
  console.log(`        unchanged                  ${counts.unchanged}`);
}

function dump(title, items) {
  if (!items.length) return;
  console.log(`\n${title} (${items.length})`);
  for (const item of items.slice(0, 20)) console.log(`  ${item}`);
  if (items.length > 20) console.log(`  … ${items.length - 20} more`);
}

dump("REPORT unsupported → supported", report.unsupported_to_supported);
dump("REPORT threw differently", report.threw_differently);
dump("REPORT output differs, same rows", report.output_differs);
dump("REPORT _warnings changed", report.warnings_changed);

let failed = false;
if (newRows.length || staleRows.length || newDrops.length || staleDrops.length) {
  failed = true;
  dump("FAIL new row-count changes", newRows);
  dump("FAIL stale row-count manifest entries", staleRows);
  dump("FAIL new supported → unsupported", newDrops);
  dump("FAIL stale supported → unsupported manifest entries", staleDrops);
  console.error(
    "\nFAIL — class (1) and (2) must match tools/flint-bump-manifest.json as a whole set.",
  );
}

if (failed) process.exit(1);
console.log("\nOK — no unexplained class (1) or (2) diffs.");
