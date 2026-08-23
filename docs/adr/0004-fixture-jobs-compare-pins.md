# 4. Fixture jobs compare pins, not upstream recorded output

- **Status:** Accepted
- **Date:** 2026-08-23
- **Resolves:** the CI obligation in ADR-0001 Consequences ("a pinned-fixture CI job …
  Node is the oracle") and the "fails on any unexplained diff" wording that ticket
  [Fixture-CI contract](https://github.com/thearcscode/chartagent/issues/24) found
  unbuildable as written. ADR-0001 and ADR-0002 Decision 2 are amended in place with
  dated pointers; the pin, the envelope, and the delete-`x_chartagent` *invariant*
  still hold — only the job shape and the reference move here.
- **Settled on:** [#24](https://github.com/thearcscode/chartagent/issues/24)

## Context

ADR-0001 obliged a pinned-fixture CI job that re-runs all 705 cases on every Flint bump
and every engine change, and fails on any unexplained diff, with Node as the oracle.
ADR-0002 Decision 2 added the namespacing invariant: deleting `x_chartagent` must leave
a document Flint compiles byte-for-byte identically, on that same job.

Every load-bearing noun in that sentence has moved. There is no engine to change
(ADR-0001, amended 2026-08-22). There is no reference that is both trustworthy and
complete. And "unexplained" was borrowed from engine-parity, where a diff meant *our*
engine was wrong.

Two candidate references fail:

- **Upstream `expected.json` is Vega-Lite only.** The 705 fixtures record Vega-Lite
  output. There is no recorded ECharts, Chart.js, Plotly, or Excel output anywhere
  upstream. Node-as-reference is what used to give the other four backends something
  to compare against, and Node was the *engine* under test, not Flint.
- **Upstream `expected.json` is not reproducible from upstream's own release.**
  ADR-0001's churn run already put npm 0.5.1 against fixtures at the same commit at
  51.8% match once `config` is set aside. #24 found the mechanism in one fixture:
  `rose_chart__04` records `innerRadius: 40` that `rose.ts` at tag `0.5.1` no longer
  declares and no longer emits. Compiled with npm `flint-chart@0.5.1`: expected has
  `innerRadius`, live output does not. The recorded photo shipped inside the tag
  unregenerated.

So the job cannot ask "is this output correct?" We did not write the compiler. It asks
**what changed between the pin we shipped and the pin we are about to ship.** That
question needs no external truth. Both sides are compiled by us, which also gives all
five backends a side-by-side where upstream recorded only Vega-Lite.

This ticket **never reads `expected.json`.** It consumes 705 `input.json` and ignores
705 `expected.json`.

## Decision

**Two jobs. Neither reads upstream recorded output. The bump gate's reference is the
IIFE we already shipped, taken from git, not from npm.**

1. **`fixtures-invariant` — every commit and PR.** Self-relative, so it needs no
   reference output. Failure means *our* architecture broke:

   - Add `x_chartagent` to all 705 inputs, all 5 backends: compiled output
     byte-identical.
   - Delete it again, all 705 × 5: byte-identical (ADR-0002 Decision 2 as worded;
     `probe.mjs transparency` currently checks delete on one fixture and compares
     the *input* document).
   - `_`-prefixed metadata (`_warnings`, `_width`, `_transform`, `_pivot`) unchanged
     in both directions. `canon()` strips these, so a Flint that starts *complaining*
     about `x_chartagent` without changing output would pass a stripped compare.
   - Zero throws attributable to the key.
   - Dirty-input count unchanged (Decision 4).
   - Pin pairing: `FIXTURE_COMMIT` resolves to the git tag named by `FLINT_VERSION`.

2. **`flint-bump` — automatic on a PR that moves `FLINT_VERSION` or
   `FIXTURE_COMMIT`.** Not `workflow_dispatch`. Not triggered on `frame/vocab.json`
   (that is the packaging ticket's regen-and-diff). Not on the Python/OS matrix —
   one runner, one pinned Node. The job:

   - Compiles 705 × 5 on the old pin and the new pin, classified per Decision 5.
   - Runs `check_bump.py` (old vocab vs new vocab). That tool is inherently
     differential and lives only here. Per-commit "does the committed vocab still
     describe the committed bundle?" is the packaging ticket's bind test and
     regen-and-diff, not this.

3. **The old pin is the vendored IIFE on the PR's base** — the file on `main`, the
   artifact we already shipped. Not `HEAD~` on the branch (that commit may already
   be the new file). Not a re-fetch of the old version from npm. The IIFE carries
   no version string; npm can serve a bundle that differs from what we vendored,
   which is the failure the packaging ticket already priced. First pin: report
   "initial pin, no differential" — do not invent a comparison.

4. **Corpus is fetched at job time, never vendored.** Both hazards in
   `prototypes/flint-embed/setup.sh` are removed: do not skip when `build/fixtures`
   exists, and do not end the checkout in `|| true`.

   A **dirty input** is a fixture whose `input.json` names a `chartProperties` key
   the pinned vocabulary does not declare. Today that count is **2**
   (`Rose Chart.innerRadius`, `Strip Plot.jitterWidth`). The committed artifact is
   the **number**; slugs appear in the CI log only. The gate fails when the number
   *grows*. Existence of dirt is upstream's; a rising count on a bump is ours.

   The two current dirties are different kinds, and one gate must not conflate
   them: `rose_chart__04` has unreproducible recorded output; `strip_plot__02`
   has a dead input key whose recorded output matches 0.5.1 exactly. We never
   read either `expected.json`, so only the dead keys enter the count.

5. **Six diff classes, reported per backend. Only (1) and (2) fail.**

   | # | Class | Verdict |
   |---|---|---|
   | 1 | Row count changed | **FAIL** |
   | 2 | Supported → unsupported | **FAIL** |
   | 3 | Unsupported → supported | report |
   | 4 | Threw → threw differently | report |
   | 5 | Output differs, same rows | report |
   | 6 | `_warnings` changed (between pins) | report |

   (1) and (2) change what a stored frame renders — the zero-LLM-refresh promise.
   (5) is expected compiler churn (~48% of fixtures on 0.2.1 → 0.5.1); failing on
   it makes the gate a rubber stamp. Unsupported at both pins is no diff; the
   per-backend split stays in the report. Class (6) on the *bump* is "Flint got
   chattier about this fixture." It is not the commit gate's `_warnings`
   assertion, which stays a failure.

6. **The only override is a diff manifest committed in the bump PR:** the full
   list of class-(1) and class-(2) diffs, overwritten wholesale each bump,
   compared as a whole set. Stale entries fail as loudly as new ones. Rejected:
   no override at all (a Flint release will drop a chart type; a gate with no
   path forward gets deleted), and a `--accept` flag in the PR description (an
   allowlist wearing a flag).

7. **Hygiene, ratified from `prototypes/flint-frame/probe.mjs` `strip`/`canon`,
   used verbatim.** Ignore `_`-prefixed keys when comparing compiled output, and
   assert them separately (Decision 1). Canonicalise key order in JavaScript only
   (JS sorts by UTF-16 code unit, Python by code point). Pin compile-time size:
   every fixture records `chart_spec.baseSize` (656 at 400×300, 49 at 560×360) —
   use that fixture's own size on both sides; supply `canvasSize` as the same
   value (`canvasSize = baseSize` is the bundle default) rather than leaving it
   implicit.

## Consequences

**What we gain.** A commit gate whose red means our namespacing broke. A bump gate
that asks a question we can answer without Microsoft's photos, on every backend.
A pairing rule that makes `FLINT_VERSION` and `FIXTURE_COMMIT` the same git object
by construction. An override that cannot silently pile up.

**What we accept.** We do not certify that Flint's output is "correct." We certify
that *this* pin did not change what data or which chart types a stored frame
produces, unless a human recorded that change in the bump PR. Config churn is
reported and not blocking. Upstream's cookbook can stay dirty; we only refuse a
bump that makes it dirtier.

**What this restates.** ADR-0001's "fails on any unexplained diff" is unbuildable —
roughly half of all fixtures differ legitimately on a real bump. The honest form
is: fail on any diff that changes what data or which chart types a stored frame
produces, and report the rest. There is no CI oracle.

**What this does not own.** The bind test and regen-and-diff stay with the
packaging ticket. The public API surface is the seam ticket. The natural-language
pressure-test corpus is a different corpus for a different purpose.

## Alternatives rejected

**A committed 705×5 snapshot of compiled output, asserted on every commit.**
Rejected. That is Microsoft's output re-committed into our history to prove a
file we vendored did not change — which the IIFE's SHA-256 in `vocab.json`
already proves in one line.

**Read `expected.json` as the reference, even only for Vega-Lite.** Rejected.
It is stale inside the 0.5.1 tag itself (`rose_chart__04`), and it does not
exist for four of five backends.

**Re-fetch the old (or both) pins from npm.** Rejected. The comparison must be
the artifact we shipped versus the artifact we are about to ship. npm is not
that artifact, and the IIFE cannot name itself.

**`workflow_dispatch` for the bump gate.** Rejected. A manual trigger is a gate
someone forgets under deadline.

**Fail on class (5), or fail with no override.** Rejected. The first makes every
real bump red; the second gets the job deleted the first time Flint drops a
chart type.

**A named exception list of dirty fixtures, or an advisory gate until the pins
are "paired."** Rejected. The pins were already the same object
(`refs/tags/0.5.1` is `34ef451…`). Teaching exceptions on day one is the
allowlist failure mode. Dirt is a count.

**Vendoring the fixture corpus.** Rejected. The IIFE ships to users; this
cookbook ships to nobody.

## Related

- ADR-0001 — pin, envelope, client compile. The CI-oracle and "unexplained diff"
  lines are withdrawn here; the pin and the invariant remain.
- ADR-0002 Decision 2 — the delete-`x_chartagent` invariant, now the commit gate
  in Decision 1, not "on every Flint bump."
- [#24](https://github.com/thearcscode/chartagent/issues/24) — the grilling that
  settled this; Findings record the rose/strip measurements.
- [#19](https://github.com/thearcscode/chartagent/issues/19) — bind test,
  regen-and-diff, vendored IIFE. §9's "only regen-and-diff needs Node" is stale;
  this ADR adds two Node jobs. The matrix is unaffected.
- `prototypes/flint-frame/probe.mjs` — `strip`/`canon` and the transparency
  probe this job must not rewrite.
- `prototypes/facade-codegen/check_bump.py` — the narrowing gate, bump only.
