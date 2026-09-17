# 25. Data-truthfulness is a multiset match against already-bound rows, not a second profile

- **Status:** Accepted
- **Date:** 2026-09-17
- **Settled on:** [#165](https://github.com/thearcscode/chartagent/issues/165)
- **Builds on:** ADR-0002 (encodings bind to transform *output*, never the source), ADR-0005
  (`bind` is the public seam; `CheckResult` named inside `ReviewReport`), ADR-0008 (the
  transform pipeline order `filter → derive → bin → group_by/aggregate → having → sort →
  limit` — what `BoundRecipe.rows` actually is), ADR-0011 (the profile contract; the reason
  it does not fit this job), ADR-0016 Decision 10 (the `not_checked` precedent, for the
  now-superseded matplotlib rail), ADR-0017 Decisions 7/9/13/15 (`getPlottedSeries()`; the
  JSON wire's serialisation rules; "compared outside the document, against transform output
  we already have"; the `RasterisationError`/`CheckResult` paint-time split), ADR-0018
  Decision 5 (`bind_recipe`; `BoundRecipe` carries rows and has no wire format), ADR-0024
  (`CheckResult`'s three-field shape; `not_checked` versus omission; `data_truthfulness`
  reserved as a custom-rail-only name)
- **Amends:** ADR-0011's *Consequences* — recorded as a dated erratum in place and listed
  under *What this amends*
- **Leaves open:** escalation policy on a `data_truthfulness` fail ([#168](https://github.com/thearcscode/chartagent/issues/168)); `CheckResult.detail`'s exact payload for this check, which is an implementation choice and not an architectural one

## Context

ADR-0024 narrowed the eight-item PRD Tier-1 list to four checks and reserved
`data_truthfulness` as **custom-rail only** — on Flint and Excel the compiled output *is*
`input.data` (ADR-0002), so the check cannot fail there by construction and is `omitted`,
never evaluated. That closes two of this ticket's four original questions before this ADR
opens: there is no Flint-envelope input to define, and how `not_checked`/omission fold into
`ReviewReport.passed` is already the general rule ADR-0024 generalised from this exact
check's own ADR-0016 Decision 10 precedent. What remains is narrower than the ticket's
framing: given `getPlottedSeries()`'s self-reported declaration (ADR-0017 Decision 13) and
`BoundRecipe.rows` as ground truth (ADR-0018 Decision 5), what does the comparison mechanism
actually do?

Two premises in the ticket and in ADR-0011 do not survive contact with the architecture that
has since landed.

**"Reuse ADR-0011's models, or a smaller thing" assumes the answer is some kind of profile.**
It is not. `Profile` exists to keep a *planner* from hallucinating over an unrepresentative
sample — cardinality, null rates, percentiles, a capped `sample_rows`. None of that answers
"did the chart show what the row said." A truthfulness check needs the literal values a point
was drawn from, not a statistical summary of the column they came from. Reusing `Profile`
would force this check to defend against a wall of optional fields — the exact objection
ADR-0011 Decision 3 raised against a flat model with every statistic optional — none of which
it reads.

**"The gate re-runs the transform" is stale.** ADR-0011's own *Consequences* said the derived
checks "wait for an output-side profile, which belongs to the review gate — it already
re-runs the transform for the data-truthfulness check," written before `bind_recipe` and
`BoundRecipe` existed. ADR-0017 Decision 13 already says the comparison runs "against
transform output we **already have**" — present tense, not re-derived. Nothing sits between
`bind_recipe`'s output and the iframe that could corrupt it: the `postMessage` channel carries
rows *into* the iframe; `getPlottedSeries()` is the only thing that crosses back out. A second
`bind_recipe` call would recompute a bit-identical, deterministic result at the cost of a
second bind, buying nothing.

## Decision

### 1. No output-side profile. The check reads `BoundRecipe.rows` directly, once, reused

`data_truthfulness` holds no artifact of its own. It compares `getPlottedSeries()`'s
declaration against the same `BoundRecipe.rows` that `bind_recipe` already produced to
populate the `postMessage` channel and that `BoundDocument` already carries for painting
(ADR-0017 Decision 8, ADR-0018 Decision 5). The review gate does not re-run the transform for
this check. This corrects ADR-0011's *Consequences* — see *What this amends*.

### 2. The only inputs are the declaration and rows already held; `figure_json` and sandbox
   bytes are both dead ends here

`figure_json`-as-matplotlib-artists was already retired by ADR-0016 Decision 1 (withdrawn)
and ADR-0017 Decision 13 (`getPlottedSeries()` in its place). ADR-0015's *"a tier reads
artifact bytes it was handed as `Mapping[Format, bytes]`, never a sandbox path"* constraint
the ticket asked about does not apply on this rail at all: phase P2 implements no
`SandboxBackend` (ADR-0017 Decision 3), so there is no sandbox artifact-bytes handoff to
constrain. Named here so nobody goes looking for one.

### 3. Four outcomes, split by where the failure is detectable, not by what the values say

```
missing symbol, or a throw from getPlottedSeries()      → RasterisationError (ADR-0017 D15)
paint succeeded; return is non-array, contains an
  invalid point (Decision 4), or is an empty array []   → CheckResult(outcome="not_checked")
shape-valid, non-empty array; every point matches a
  distinct row within tolerance (Decision 5)             → CheckResult(outcome="pass")
shape-valid, non-empty array; some point fails to match
  (wrong value, unknown column, or its row was already
  consumed by an earlier point)                          → CheckResult(outcome="fail")
```

A throw from `getPlottedSeries()` is a paint-time defect in the same family ADR-0017 Decision
15 already put `render()` throws and missing symbols in — it never reaches a `CheckResult` at
all. `not_checked` means exactly *paint succeeded and we have nothing comparable*: an empty
array is not_checked, deliberately not read as "zero points, so every declared point
trivially matched." Vacuous truth is not a pass.

### 4. A valid point is a non-empty flat mapping of real column names to JSON scalars

`getPlottedSeries()` returns a **flat array** of points — no `{seriesName, points: […]}`
wrapper. Series identity, where it exists, rides as just another echoed column (e.g.
`category`); it plays no role in matching, so a second, parallel identity axis would only add
a place for the declaration to be wrong that the check does not read.

Each point echoes the **real column names and values it drew from** — the same names
`render(data, el)` already received in `data` (ADR-0017 Decision 9). No invented `x`/`y` role
vocabulary: asking the agent to also declare which of its own encodings map to which of ours
adds a translation step that can be wrong independently of whether the chart is truthful, and
the module already has the real names in hand.

A **valid point** is a non-empty object whose keys are non-empty strings and whose values are
JSON scalars — string, number, bool, or null. `{}`, a non-object array entry, or a
nested/non-scalar value each make the **whole declaration malformed** (`not_checked`), not a
per-point failure: an empty point has no fields to disagree on, so it would vacuously match
any row, and the shape gate exists precisely to keep that from happening. A well-formed point
naming a column that does not exist in `BoundRecipe.rows` is not a shape failure — it fails at
matching (Decision 5), because it is comparable, and no row can ever equal it.

### 5. Matching is multiset containment, not full coverage

Every declared point must match some row in `BoundRecipe.rows` — a row exists whose named
fields equal the declared point's fields, within tolerance for numbers and exactly for
everything else (Decision 6). Matching is **multiset**, not set: each declared point consumes
one occurrence of a matching row, so a real row can justify at most as many declared points as
there are identical real rows. A module that draws five bars by echoing one real row's values
five times fails four of them — closing the loophole plain set-membership would leave open.

This is **containment, not full coverage** in the other direction too: `BoundRecipe.rows` not
represented in the declaration are simply outside the check, and so are columns a point does
not mention. A client-side top-N, a sample, or a paginated view is not a truthfulness fail —
it is a drawing choice this check was never asked about. The asymmetry is deliberate: omission
is silent by design, fabrication is not.

**The accepted weakness stays named, not solved.** A module can still hide a fabricated mark
by simply never declaring it — omission from the declaration is indistinguishable from
legitimate under-drawing, because both read the same way to a containment check. This is
exactly the gap ADR-0017 Decision 13 recorded — *"this catches an honest bug, not a determined
lie"* — and the Tier-2 VLM, which looks at the rendered picture rather than trusting a
self-report, is the only thing standing behind it.

### 6. Numeric comparison is a frozen tolerance; every other scalar is exact

Declared values are **logical, unformatted values, in the same JSON types as the wire rows**
(ADR-0017 Decision 9) — not display strings. A point drawn as `"45.7%"` on screen must declare
the number it was computed from, not the label; formatting is a readability question for
Tier-2's rubric, not this check's.

Numbers compare with a combined absolute/relative tolerance:

```
abs(declared - real) <= max(rel_tol * max(abs(declared), abs(real)), abs_tol)
rel_tol = 1e-9
abs_tol = 1e-12
```

Frozen **in library code, not configuration** — the same posture ADR-0011 took with `k = 10`
and `N = 1001`, and deliberately not the posture ADR-0015 took with sandbox byte caps.
Tolerance defines what `pass` *means* for this check; letting an operator loosen it would let
`data_truthfulness: pass` mean a different thing on different deployments, which is the one
outcome a truthfulness check cannot survive. The numbers are tight on purpose: since
declarations are expected to **echo** row values rather than recompute them, legitimate
divergence should only ever be float64/JSON round-trip noise, several orders of magnitude
below `1e-9`. A looser tolerance such as `1e-6` was rejected because it would let a genuine
data error — `1_000_000` declared against a real `1_000_001` — read as float noise instead of
what it is. Everything that is not a JSON number — string, bool, null — compares exactly;
`null` matches `null` as its own value, and non-finite numbers never reach this comparison
because ADR-0008 Decision 9 already collapses them to `null` on the wire before either side of
the check sees them.

## What this amends

- **ADR-0011's *Consequences*.** *"Those derived checks wait for an output-side profile, which
  belongs to the review gate — it already re-runs the transform for the data-truthfulness
  check"* is corrected on two points: no output-side profile is built (Decision 1 — the check
  reads rows directly, not a `Profile`-shaped summary), and the gate does not re-run the
  transform (Decision 1 — it reuses `BoundRecipe.rows`, already produced for painting). Written
  before `bind_recipe`/`BoundRecipe` existed; superseded now that they do.

## Consequences

- **The check's guarantee is exactly as strong as containment plus multiset, no stronger.** A
  determined author can still fabricate a mark by omitting it from the declaration; this is
  recorded as accepted, not engineered around, and is why P0.8's guarantee stays rail-dependent
  and the Tier-2 VLM keeps looking at the picture.
- **No new artifact, no new storage.** The mechanism is a pure comparison over two things the
  system already produces — `BoundRecipe.rows` and the declaration — so nothing here widens
  `spec_revisions`, `bind_caches`, or `__all__` beyond `data_truthfulness` as a `CheckResult`
  name, which ADR-0024 already reserved.
- **The tolerance is part of the check's meaning.** Changing `rel_tol`/`abs_tol` later is a
  library-behaviour change with the same weight as moving ADR-0011's `N = 1001`, not a config
  tweak — it redefines what "true" means for every custom-rail chart reviewed under it.
- **Shape validity gates before any row-matching runs.** A malformed or empty declaration can
  never slip through as an accidental pass, because "every declared point matched" is only
  evaluated once there is at least one valid point to evaluate.

## Alternatives rejected

- **Reusing ADR-0011's `Profile` models for the transform output** — Decision 1. Wrong shape:
  statistics for a planner, not literal values for a comparison; would force the check to
  defend against fields it never reads.
- **An independent re-run of `bind_recipe` for the check** — Decision 1. Nothing untrusted
  touches server-side rows before they cross into the iframe, so a second bind produces a
  bit-identical result at a second cost.
- **An encoding-role vocabulary (`x`/`y`/`color`) in the declaration** — Decision 4. Adds a
  translation surface the agent can get wrong independently of truthfulness; direct column
  echo needs no translation because the module already has the real names.
- **A series-grouped return, `[{seriesName, points: […]}]`** — Decision 4. A second identity
  axis matching never reads.
- **Full-coverage matching (every row must appear in the declaration)** — Decision 5. Would
  fail a legitimate client-side top-N, sample, or paginated view for a reason unrelated to
  truthfulness.
- **Set, rather than multiset, containment** — Decision 5. Lets one real row justify any number
  of fabricated duplicate marks.
- **A configurable tolerance** — Decision 6. Would make `pass` mean different things per
  deployment for the one check whose entire job is a fixed promise.
- **`rel_tol = 1e-6`** — Decision 6. Permits digit-level data errors to read as float noise.
- **Vacuous matching on an empty point (`{}`)** — Decision 4. A free pass with no fields to
  disagree on.
- **An empty declared array reading as an automatic pass** — Decision 3. "Zero points, so every
  declared point matched" is not evidence of truthfulness; it is evidence of nothing.

## What this feeds

- **Escalation** ([#168](https://github.com/thearcscode/chartagent/issues/168)) inherits
  `data_truthfulness: fail` as one of the Tier-1 trigger signals, alongside
  `injection_pattern`, `painted`, and `colorblind_safe_palette` (ADR-0024).
- **Tier-2 critique** ([#166](https://github.com/thearcscode/chartagent/issues/166),
  [#167](https://github.com/thearcscode/chartagent/issues/167)) inherits the named, accepted
  weakness: a self-reported declaration can omit a fabricated mark entirely, and the VLM
  looking at the rendered picture is the only check standing behind that gap.
- **The custom-rail authoring prompt** inherits a hard contract for `getPlottedSeries()`, not
  just a convention: a flat array, real column names, logical unformatted values, and
  non-empty valid points — a declaration that violates it is `not_checked`, not a warning.

## Related

- ADR-0002 — encodings bind to transform output, never the source.
- ADR-0008 — the transform pipeline order that makes `BoundRecipe.rows` the final, already
  filtered/sorted/limited plotted set.
- ADR-0011 — the profile contract this check deliberately does not reuse; amended above.
- ADR-0016 Decision 10 — the `not_checked` precedent this check's shape gate inherits.
- ADR-0017 Decisions 7, 9, 13, 15 — `getPlottedSeries()`'s contract, the JSON wire rules, "we
  already have," and the `RasterisationError`/`CheckResult` split.
- ADR-0018 Decision 5 — `bind_recipe` and `BoundRecipe`, the source of the rows this check
  reads.
- ADR-0024 — `CheckResult`'s shape, the `not_checked`-versus-omission rule, and
  `data_truthfulness` reserved as a custom-rail-only name.
- [#165](https://github.com/thearcscode/chartagent/issues/165) — the ticket.
