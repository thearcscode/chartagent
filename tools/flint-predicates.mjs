// Browser-safe compile predicates, shared between the fixture CI jobs
// (flint-lib.mjs re-exports these) and anything that needs to answer the
// same questions in a browser — e.g. the corpus recorder's paint leg (#122).
//
// No `node:` imports, no filesystem access. Loadable as a plain ES module
// from a browser page with no bundler step.
//
// strip/canon are copied verbatim from prototypes/flint-frame/probe.mjs
// (ADR-0004 Decision 7) — that copy stays; this is the only other one.

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

export function rowCount(output) {
  if (!output || typeof output !== "object") return null;
  if (typeof output._dataLength === "number") return output._dataLength;
  if (Array.isArray(output.data?.values)) return output.data.values.length;
  if (output.schema === "flint.excel.chart/v1" && Array.isArray(output.data)) {
    return Math.max(0, output.data.length - 1);
  }
  return null;
}

export function clone(value) {
  return JSON.parse(JSON.stringify(value));
}
