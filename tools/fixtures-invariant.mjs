#!/usr/bin/env node
// Per-commit fixture invariant (ADR-0004 Decision 1). A red build means our
// namespacing broke. Never reads expected.json.

import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import {
  EXCEL_FACET_REFUSALS,
  EXPECTED_FIXTURES,
  X_CHARTAGENT,
  assemblers,
  canon,
  classifyExcel,
  compile,
  dirtyPairs,
  loadBundle,
  loadFixtures,
  meta,
  pinSize,
} from "./flint-lib.mjs";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const bundlePath = process.argv[2] ?? path.join(ROOT, "src/chartagent/_bundle/flint.iife.js");
const fixturesDir = process.argv[3] ?? path.join(ROOT, "build/fixtures");
const vocabPath = process.argv[4] ?? path.join(ROOT, "src/chartagent/frame/vocab.json");
const dirtyPath = process.argv[5] ?? path.join(ROOT, "tools/dirty-input-count");

const Flint = loadBundle(bundlePath);
const assemble = assemblers(Flint);
const fixtures = loadFixtures(fixturesDir);
const vocab = JSON.parse(readFileSync(vocabPath, "utf8"));
const dirtyCap = Number(readFileSync(dirtyPath, "utf8").trim());

if (fixtures.length !== EXPECTED_FIXTURES) {
  console.error(`expected ${EXPECTED_FIXTURES} fixtures, found ${fixtures.length}`);
  process.exit(1);
}

let failed = false;
const dirty = new Set();
const excel = { facet: 0, facetedAccepted: 0, facetWithoutChannel: 0 };
const perBackend = {};

for (const backend of Object.keys(assemble)) {
  perBackend[backend] = { same: 0, unsupported: 0 };
}

for (const { name, input } of fixtures) {
  const frame = pinSize(input);
  const withKey = { ...frame, x_chartagent: X_CHARTAGENT };
  const { x_chartagent: _removed, ...deleted } = withKey;

  for (const pair of dirtyPairs(frame, vocab)) dirty.add(pair);

  const encodings = frame.chart_spec?.encodings ?? {};
  const hasFacet = "column" in encodings || "row" in encodings;

  for (const [backend, fn] of Object.entries(assemble)) {
    const base = compile(fn, frame);
    if (backend === "excel") {
      const kind = classifyExcel(base.ok ? null : { message: base.error });
      if (hasFacet && kind === "facet") excel.facet += 1;
      else if (hasFacet && kind === "accepted") excel.facetedAccepted += 1;
      else if (!hasFacet && kind === "facet") excel.facetWithoutChannel += 1;
    }
    if (!base.ok) {
      perBackend[backend].unsupported += 1;
      continue;
    }

    const added = compile(fn, withKey);
    const gone = compile(fn, deleted);

    if (!added.ok) {
      console.error(`${backend}/${name}: add x_chartagent threw: ${added.error}`);
      failed = true;
      continue;
    }
    if (!gone.ok) {
      console.error(`${backend}/${name}: delete x_chartagent threw: ${gone.error}`);
      failed = true;
      continue;
    }
    if (canon(added.value) !== canon(base.value)) {
      console.error(`${backend}/${name}: add x_chartagent changed compiled output`);
      failed = true;
    }
    if (canon(gone.value) !== canon(base.value)) {
      console.error(`${backend}/${name}: delete x_chartagent changed compiled output`);
      failed = true;
    }
    if (meta(added.value) !== meta(base.value)) {
      console.error(`${backend}/${name}: add x_chartagent changed _-prefixed metadata`);
      failed = true;
    }
    if (meta(gone.value) !== meta(base.value)) {
      console.error(`${backend}/${name}: delete x_chartagent changed _-prefixed metadata`);
      failed = true;
    }
    perBackend[backend].same += 1;
  }
}

console.log(`fixtures-invariant: ${fixtures.length} fixtures × 5 backends\n`);
for (const [backend, counts] of Object.entries(perBackend)) {
  console.log(
    `  ${backend.padEnd(9)} ${String(counts.same).padStart(4)} unchanged` +
      (counts.unsupported ? `, ${counts.unsupported} unsupported` : ""),
  );
}

const dirtySlugs = [...dirty].sort();
console.log(`\ndirty-input count: ${dirty.size} (cap ${dirtyCap})`);
for (const pair of dirtySlugs) console.log(`  ${pair}`);
if (dirty.size > dirtyCap) {
  console.error(`dirty-input count grew: ${dirty.size} > ${dirtyCap}`);
  failed = true;
}

console.log(
  `\nExcel facet: ${excel.facet} refusals, ${excel.facetedAccepted} accepted, ` +
    `${excel.facetWithoutChannel} without channel`,
);
if (
  excel.facet !== EXCEL_FACET_REFUSALS ||
  excel.facetedAccepted !== 0 ||
  excel.facetWithoutChannel !== 0
) {
  console.error(
    `Excel facet biconditional failed: expected ${EXCEL_FACET_REFUSALS}/0/0, ` +
      `got ${excel.facet}/${excel.facetedAccepted}/${excel.facetWithoutChannel}`,
  );
  failed = true;
}

if (failed) {
  console.error("\nFAIL — the fixture invariant, dirty-input cap, or Excel facet rule broke.");
  process.exit(1);
}
console.log("\nOK — invariant holds.");
