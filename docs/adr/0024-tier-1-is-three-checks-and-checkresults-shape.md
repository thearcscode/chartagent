# 24. Tier 1 is three checks, not seven, and `CheckResult`'s shape

- **Status:** Accepted
- **Date:** 2026-09-16
- **Settled on:** [#164](https://github.com/thearcscode/chartagent/issues/164)
- **Builds on:** ADR-0002 (client-compile purity — compiled output *is* `input.data`, untouched
  by any LLM-authored code), ADR-0003 (the `Rasteriser` protocol frozen at `envelope -> bytes`;
  Excel unsupported forever; unavailable vs unsupported; "could not look" vs "did not pass"),
  ADR-0005 §9 (`ReviewReport` frozen — `tiers_run`/`tiers_skipped`/`passed`/`budget_exhausted`/
  `checks: tuple[CheckResult, ...]`; `CheckResult` named, undefined), ADR-0011 (the
  untrusted-subtree manifest), ADR-0012 Decisions 10-11 (the 17 non-painting ECharts boxplots;
  Phase-2 validation's placement, distinct from the review gate), ADR-0016 Decision 10 (the
  `not_checked` precedent, for the now-superseded matplotlib custom rail), ADR-0017 Decision 15
  (paint-time failures split between `RasterisationError` and `CheckResult`; the custom rail's
  boolean paint signal)
- **Leaves open:** `data_truthfulness`'s internals on the custom rail (#165); escalation
  policy on a Tier-1 failure (#168); Phase-2 validation's actual thresholds (still fog on the
  map). *The four checks demoted to Tier-2's rubric (#167) were settled by
  [ADR-0026](0026-tier-2-is-five-defect-checks-and-the-critique-is-a-leaf-call.md) on 2026-09-18.*

## Context

ADR-0005 froze `ReviewReport`'s shape and left `CheckResult` — the element type of its `checks`
tuple — "named here and defined by the review-gate tier ticket." This is that ticket. Four
questions arrived with it: `CheckResult`'s shape including a third outcome beside pass/fail; the
Tier-1 lint set and which checks are data-free versus profile-derived; how Tier-1 relates to the
Phase-2 validation-thresholds fog entry; where Excel's permanent Tier-1-only status narrows the
PRD's "every chart passes lint + VLM + interactivity" claim; and whether the PRD §12
injection-pattern lint is Tier-1.

The PRD's original Tier-1 list (§7.3) — *code executed; artifact exists; axis labels present;
legend when >1 series; label-overlap detection; colorblind-safe palette; bar-chart y-axis
baseline; data-truthfulness; injection-pattern screen* — was written before ADR-0003 froze
`Rasteriser` at exactly `envelope -> bytes` and before ADR-0016/0017 redesigned the custom rail
twice (matplotlib, then withdrawn, then the current web/iframe document). Taking the frozen
protocol seriously — it exposes pixels and nothing else, no DOM, no compiled-option object, no
geometry — collapses that list hard. Four of the eight never had a reachable structural failure
mode once the current architecture is applied; a fifth is measurable only as pixels. What
survives is smaller and sharper than the PRD implies.

## Decision

### 1. `CheckResult` is three fields, one shape, shared across every tier

```python
class CheckResult:
    name: Literal[...]       # closed per tier; widened by whichever ticket adds a check
    outcome: Literal["pass", "fail", "not_checked"]
    detail: ...              # short structured or string payload
```

No severity field — a Tier-1 `fail` already blocks Tier-2 by PRD P0.7's own acceptance
criterion, so a second way to say "this blocks" would just be able to disagree with the first.
One shape for all three tiers, not a Tier-1-specific type: Tier-2's VLM critique (#167) and any
future Tier-3 result reuse it, with richer content — rubric text, a DOM assertion — riding in
`detail`. `ReviewReport.checks` stays one flat, tier-agnostic list to read.

### 2. `outcome` is exactly three values, forever

`Literal["pass", "fail", "not_checked"]`. A check that crashes is a defect in *our* code, not a
fact about the chart — it raises, and never becomes a `CheckResult`. `not_checked` carries a
single meaning: *we could not look*, on the precedent ADR-0016 Decision 10 set for a matplotlib
artist outside `figure_json`'s v1 set, and ADR-0003 set for Excel. It must never be read as "we
looked and it was fine" (ADR-0003) or laundered into a pass.

### 3. `not_checked` versus omission

A `CheckResult` for `name=X` with `outcome="not_checked"` asserts: *this check can, in
principle, produce pass or fail for this (rail, backend) — it just couldn't this run.* A check
is **omitted** from `checks` entirely when it can **never** be pass or fail for this (rail,
backend), full stop. The dividing line: *"holding rail and backend fixed, can this check's
precondition ever become true?"*

- Yes, this run — `pass`/`fail`.
- Yes, in principle, not this run — `not_checked` (e.g. `painted`/`colorblind_safe_palette` on a
  Flint backend when the `Rasteriser` extra isn't installed: `"unavailable"`).
- Never for this (rail, backend) — omitted (e.g. `painted`/`colorblind_safe_palette` on Excel,
  which is never a raster target; `data_truthfulness` on Flint/Excel).

A permanently-omitted check reported as forever-`not_checked` would be decoration: a reader
would see `not_checked` and wonder what would need to change for it to ever resolve, and the
honest answer is nothing.

**Erratum — 2026-09-18 ([#167](https://github.com/thearcscode/chartagent/issues/167),
[ADR-0026](0026-tier-2-is-five-defect-checks-and-the-critique-is-a-leaf-call.md)).** Three
corrections, none of which touches a Tier-1 check. **The dividing line holds fixed more than
rail and backend:** Tier-2's items vary per *chart* — a bar baseline on a line chart — so where
the host holds the chart spec (Flint) a check is omitted when it can never resolve for this
**(rail, backend, chart spec)**, decided by a hand-authored table before the call. **On the
custom rail `not_checked` also means the critic declined or judged an item not applicable** —
this run, not *never applies* — because a recipe has no chart spec and the critic must not be
able to drop a check; the *Avoid* clause on `not_checked` stands wherever the host can know.
**`passed` refuses a vacuous pass:** a tier in `tiers_run` that resolved no check is not a pass,
so `passed` is false for an inconclusive Tier 2; `not_checked` and omission still stay outside
pass/fail otherwise. Tier 1 cannot hit this, since `injection_pattern` always resolves.

### 4. The Tier-1 check list

Four names survive, against the PRD's eight:

| check | data source | Flint (non-Excel) | Excel | custom rail |
| --- | --- | --- | --- | --- |
| `injection_pattern` | profile-derived | pass/fail | pass/fail | pass/fail |
| `painted` | image-derived (coarse) | pass/fail, `not_checked` if extra missing | omitted | omitted |
| `colorblind_safe_palette` | image-derived | pass/fail, `not_checked` if extra missing | omitted | pass/fail, `not_checked` if extra missing |
| `data_truthfulness` | rows + declaration | omitted | omitted | pass/fail or `not_checked` (#165) |

`injection_pattern` screens only ADR-0011's untrusted paths — `columns[].name`, `reported_type`,
string extrema, `top[].value`, `sample_rows` — never library-computed statistics
(`top_k_coverage`, `iso8601_parse_rate`). Those are ours, not attacker-authored, and screening
them for instruction-like patterns is a category error. It runs against the already-computed
profile, rail-independent, which is why it is the one check every request gets.

`painted` is a coarse whole-canvas non-blank check — it answers "did anything render," not "did
the intended marks render." It will not catch ADR-0012 Decision 10's 17 non-painting ECharts
boxplots, where chrome (axes, gridlines, labels) draws fine and only the data marks are absent:
a plot-area-scoped ink check needs the compiled option's region boundaries, which the frozen
`Rasteriser` protocol does not expose. That gap is Tier-2's, not Tier-1's — the VLM looks at the
picture and can say "there's no boxplot here." Stated here explicitly so nobody reads `painted`
as designed to have solved it.

`colorblind_safe_palette` survives as image-derived because it doesn't need plot-area
boundaries — the k most common saturated, non-background hues in the whole image is a coarser
and more robust read than locating a region.

`data_truthfulness` is custom-rail only. On Flint and Excel, the compiled output *is*
`input.data` — no LLM-authored code sits between bound rows and the rendered chart (ADR-0002),
so re-running `bind()` and comparing reproduces the same deterministic output by construction. A
computational bug would replay identically both times; the check cannot fail on these two
rails, ever. It exists specifically because custom-rail generated code *can* silently diverge
from the transform it was handed — which is exactly why `getPlottedSeries()` (ADR-0017 Decision
13) exists. #165 designs its custom-rail mechanism; this ADR only reserves the name and the
rail scope.

### 5. Demoted to Tier-2's rubric, not built here

`axis_labels_present`, `legend_presence`, `label_overlap`, `bar_chart_y_axis_baseline` all need
either text-grade reading (OCR, fragile and not "cheap, always") or plot-area geometry the
frozen protocol doesn't expose on either rail — custom-rail documents are hand-written with no
compiled-option equivalent at all, and Flint's compiled option isn't exposed through
`Rasteriser`'s bytes-only return. PRD's Tier-2 rubric already covers "readability," which
subsumes all four. They feed #167 as VLM rubric items, not as Tier-1 lints.

**Settled — 2026-09-18 ([#167](https://github.com/thearcscode/chartagent/issues/167),
[ADR-0026](0026-tier-2-is-five-defect-checks-and-the-critique-is-a-leaf-call.md)).** Tier 2 is
these four plus `marks_present` — the answer to the non-painting boxplots Decision 4 leaves to
the VLM — one `CheckResult` each. Aesthetics and chart-type appropriateness are not judged.

### 6. `code_executed` is dropped

Every failure mode it would report — a throw inside `render()`, a hang, a missing symbol —
already raises `RasterisationError` before Tier-1 runs (ADR-0017 Decision 15 groups these with a
false paint signal under one paint-time failure surface). Flint and Excel have no LLM-authored
code to execute at all. A check that can never produce a `CheckResult` — every path to it
already exited via exception — doesn't belong in the enumeration; a reader would look for
`code_executed: fail` and never find one.

### 7. Excel's narrowing, precisely

The PRD's "every chart passes lint + VLM + interactivity" does not narrow to "Excel gets Tier-1's
list minus the image ones" — under Decisions 4/6 above, Excel's `checks` contains exactly one
entry: `injection_pattern`. `painted`, `colorblind_safe_palette`, and `data_truthfulness` are all
omitted, never `not_checked`, because none of them can ever resolve pass/fail on a backend that
structurally never produces a raster (ADR-0003) and never runs generated code (ADR-0002/0016).

### 8. Tier 1 never appears in `tiers_skipped`

`tiers_skipped: Mapping[int, Literal["unavailable", "unsupported"]]` (ADR-0005) is per-tier.
`injection_pattern` needs neither a rasteriser nor a particular backend, so Tier 1 always has at
least one runnable check — it always appears in `tiers_run`, on every request, regardless of
rasteriser availability or Excel. A missing or unsupported rasteriser is expressed entirely
through individual `CheckResult.outcome` values inside Tier 1 (Decision 3) and through Tiers 2/3
landing in `tiers_skipped`, never by pulling Tier 1 out of `tiers_run`. This is consistent with,
not a reinterpretation of, ADR-0003 Decision 7's own phrasing: "Excel receives Tier-1 lints
only," not "Excel skips Tier 1."

### 9. Tier 1 and Phase-2 validation stay distinct — no new decision

ADR-0012 Decision 11 already placed Phase-2 validation as backend-free and profile-derived,
running after the transform and before the envelope, raising typed errors (`SchemaDriftError`,
and cardinality's still-unnamed error) — structurally prior to and separate from Tier-1, which
runs after a successful `bind`, over the envelope, bound rows, and (where available) the
rasterised image. Nothing here revises that placement. Worth stating once, plainly: the two are
**temporally exclusive on any single request** — a spec that fails Phase-2 validation never
reaches `bind`'s success path, so it never reaches the review gate at all. A chart either dies at
Phase-2 or lives to be reviewed; never both.

## Consequences

- **Tier 1 is far smaller than the PRD's prose suggests** — four names, one of which
  (`data_truthfulness`) never appears on two of three rails, and one of which
  (`injection_pattern`) is the only thing Excel ever gets. "Cheap, always" turns out to mean
  *nearly nothing, on every request* plus *the same few pixel checks, when there's an image to
  check them on*.
- **Tier-2's rubric grows by design, not by accident** — four PRD-Tier-1 lints move there
  because the frozen `Rasteriser` protocol structurally can't support them as deterministic
  checks. #167 inherits axis-labels, legend, overlap, and y-axis-baseline as named rubric items,
  not a blank slate.
- **`not_checked` is a narrower promise than it sounds.** It means *this check is meaningful
  here and we lacked an input*, never *this check doesn't apply*. Reusing it for
  permanently-inapplicable checks would have made every `ReviewReport` carry dead weight that
  never resolves.
- **The `Rasteriser` protocol's frozen shape (`envelope -> bytes`) is now a hard constraint on
  what Tier-1 lints can ever exist**, not just on `painted`. Any future Tier-1 lint proposal
  needs to survive the same test this ADR applied to the PRD's original eight: can it be
  answered from pixels and the profile alone, or does it quietly need something the protocol
  doesn't give it?

## Alternatives rejected

- **A severity field on `CheckResult`.** Redundant with "Tier-1 fail blocks Tier-2" already
  being P0.7's rule; a second field that could disagree with the first is a bug waiting to
  happen, not a feature.
- **A fourth `outcome` value for a check that errors internally.** Conflates a defect in our
  code with a fact about the chart. Errors raise.
- **Reporting `not_checked` for every check a rail/backend can never satisfy** (Excel's
  `painted`, Flint's `data_truthfulness`, custom rail's `painted`), for report completeness.
  Rejected — same reasoning as dropping `code_executed`: a value that can never change isn't
  information.
- **A plot-area-scoped `painted` check, built now, to satisfy ADR-0012's inheritance clause at
  Tier-1.** Needs structural information (region boundaries) the frozen protocol doesn't expose;
  Tier-2's VLM already looks at the picture and can catch it. Building CV to approximate a
  compiled-option read is exactly the kind of implementation this ADR declines to lock in.
- **`bar_chart_y_axis_baseline` as provisional Tier-1**, geometric (bar-bottom vs.
  plot-area-bottom) without needing text. Rejected on the same missing-input grounds as
  `painted`'s plot-area problem — demoted with the other three rather than left `not_checked` on
  every real backend.
- **Keeping `code_executed` for a future Python-sandbox widening**, on the theory that
  ADR-0015's later widening might reintroduce a moment where generated code executes outside
  the paint-time failure surface. Rejected as speculative: nothing in the current P2 design
  (web-rail custom rail, ADR-0017) has such a moment, and a check reserved for an unbuilt
  widening is exactly the "promise about an unspecified check" ADR-0012 Decision 11 already
  declined to make for Phase-2's cardinality error.

## What this feeds

- **Data-truthfulness check** (#165) inherits `data_truthfulness` as a reserved,
  custom-rail-scoped name in the Tier-1 enumeration; its `not_checked` conditions and comparison
  mechanism are #165's to design.
- **Tier-2 critique** (#167) inherits four named rubric items — `axis_labels_present`,
  `legend_presence`, `label_overlap`, `bar_chart_y_axis_baseline` — demoted here for a stated
  reason, plus the shared `CheckResult` shape (Decision 1) to reuse rather than reinvent.
- **Escalation** (#168) inherits a Tier-1 `fail` on `injection_pattern`, `painted`, or
  `colorblind_safe_palette` as the trigger set for whatever "fails review, moves to custom rail"
  policy it designs.
- **`ReviewReport`'s `passed` computation** inherits the general rule that `not_checked` and
  omission both stay outside pass/fail — `passed` is computed only over checks that resolved to
  `pass` or `fail`, on the precedent ADR-0016 Decision 10 set for one check and generalised here
  to all of them.
- **Phase-2 validation thresholds** (still fog on the map) inherits nothing new here beyond the
  restated boundary (Decision 9) — the thresholds themselves remain the open question ADR-0012
  left them as.

## Related

- ADR-0005 §9 — froze `ReviewReport`, named `CheckResult`, deferred its definition here.
- ADR-0003 — froze the `Rasteriser` protocol at `envelope -> bytes`; the unavailable/unsupported
  skip vocabulary; Excel unsupported forever.
- ADR-0012 Decisions 10-11 — the 17 non-painting boxplots; Phase-2 validation's placement.
- ADR-0016 Decision 10, ADR-0017 Decisions 13/15 — the `not_checked` precedent and the paint-time
  failure split this ADR generalises from one check to the whole tier.
- `CONTEXT.md` gains **`CheckResult`** and **`ReviewReport`**.
