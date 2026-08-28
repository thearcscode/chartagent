# 16. The custom rail is matplotlib, and the runner owns the environment

- **Status:** Accepted
- **Date:** 2026-08-28
- **Settled on:** [#55](https://github.com/thearcscode/chartagent/issues/55)
- **Builds on:** ADR-0005 (`bind` is the public seam; `ReviewReport` frozen),
  ADR-0006 (house palette applied by us, after `assemble*`),
  ADR-0008 (the transform menu and its named cuts),
  ADR-0011 (the profile contract; the untrusted-subtree manifest),
  ADR-0013 (rail share; the escape-reason vocabulary),
  ADR-0014 (the pressure corpus; the intent axis),
  ADR-0015 (the sandbox runs programs we did not write; the runner is ours)
- **Amends:** ADR-0013 Decisions 10 and 11, ADR-0015 Decisions 9 and 10 — recorded as dated
  errata in place and listed under *What this amends*. Errata also on PRD §7.3, §7.7 and
  §9 P0.8, and a note on ADR-0002's open `escape` question.

## Context

ADR-0015 settled what the sandbox is and what it is handed. This ADR settles what we put
into it: the shape of the generated code, the prompt that produces it, and what is recorded
when a request leaves the deterministic rail.

Four things were found by reading rather than argued, and each changed a decision.

### The escalation had no bucket

ADR-0013 Decision 6 says *"a review failure that escalates onto the custom rail scores
custom, because the escalation is the escape."* Decision 10's three buckets are all about
**expressibility** — no chart type in the 48, the transform menu cannot express the shape, an
expressible frame was escaped anyway. An escalation fits none of them: the frame *was*
expressible and the planner *did* produce it. The chart failed **review**.

The closest fit is bucket 3, and it is wrong in a way that costs something. Decision 12
commits an escape-reason histogram, and Decision 10's procedure reads that histogram to pick
a lever. Escalations landing in bucket 3 would send us to *prompt, model, structured output*
when the actual lever is the gate's own numbers.

### "Legal but unserialisable" was doing suspicious work

ADR-0015 Decision 10 shipped a runner serialising `matplotlib.figure.Figure` and said
*"plotly and bokeh stay legal on this runtime."* If the runner cannot serialise them, a chart
written in plotly cannot come back. At phase P2, PRD §7.3's *"the agent may choose any
charting library"* is in practice matplotlib only, and the "bias" was a hard constraint
wearing a soft word.

### Generated code has nowhere to live

Nothing in any ADR stores it. ADR-0007's five tables have no code column and
`spec_revisions` holds the frame as opaque `jsonb`; ADR-0002's `x_chartagent` key set
(`spec_version`, `transform`, `annotations`, `interactions`, `escape`, `source_schema`) has
no slot for it. So a custom-rail chart today cannot be saved by Studio and cannot be
refreshed — which blocks P0.5's own acceptance criterion, *"re-invoking with new data
requires no LLM call."* You cannot re-invoke what was never stored.

### matplotlib has declined to serialise figures

`figure_json` is the data-truthfulness check's input (PRD §7.3, P0.8). Closing the library
question gives it a single **owner**, not a single **shape**: matplotlib ships no
figure→JSON API, and [MEP25](https://matplotlib.org/stable/devel/MEP/MEP25.html) — the
proposal that would have added one — carries **Status: Rejected**, *"This work is important,
but this particular effort has stalled."* Its own statement of the problem is the reason we
cannot lean on the figure object generically: it is *"difficult/impossible … to get a
complete figure description, output raw data from the figure object as the user has provided
it, understand the semantics of the figure objects without heuristics."*

Pickle is the only whole-figure serialisation, it is version-fragile, and it is not our
artifact. So `figure_json` is ours to define, extraction is **per-artist**, and coverage is
therefore per-artist-type.

## Decision

### 1. The rail is closed on the return type, not on an import name

Phase P2 `make_chart` **must return `matplotlib.figure.Figure`**. That admits matplotlib and
**seaborn**, whose figures are matplotlib's. plotly and bokeh are **out** until a runner
widening.

Closing it is not a preference. The benchmark's ≥95% executable-output rate (P0.10) is
measured on this rail's output, and the one measurement we have moves that number by an order
of magnitude — 1.8% incorrect code for Matplotlib against 22% for Plotly (PandasPlotBench).
*"Choose any library"* spends the headline metric to buy an option nobody has asked for.

Closing on the **return type** rather than an import list is what makes seaborn free without
enumerating it.

### 2. The prompt states the constraint; it is not discovered by failing

A generated chart in an unsupported library is a prompt defect, not a review finding.
Rediscovering the constraint through the review loop would burn budget the gate holds for
quality, and three serialisation formats would give the truthfulness check three ways to be
subtly wrong.

### 3. A fourth escape bucket, with two fences

| bucket | recorded by | lever | ours? |
| --- | --- | --- | --- |
| 1 · no chart type in the 48 carries the request | planner, at plan time | upstream feature request | no |
| 2 · the transform menu cannot express the shape | planner, at plan time | grow the menu | yes |
| 3 · an expressible frame was escaped anyway | planner, at plan time | planner quality | yes |
| 4 · **expressible, produced, failed review** | **the gate, at escalation** | the gate's own numbers | yes |

Two fences, because bucket 4 is the one that will be misread:

1. **It does not touch the gated 50.** That quiz is P1 exit, before this rail and the review
   gate exist (ADR-0013 Decision 7). Escalations are operating telemetry for Decision 12's
   histogram, **not a fifth stress cell**. ADR-0014 stays closed.
2. **It is not a grammar-change button.** ADR-0013 Decision 11's two-button UI stays buckets
   1 against 2. Bucket 4 is a review-gate number that happens to score custom.

ADR-0013 Decision 6 stands unchanged: a review failure that does **not** escalate stays
deterministic.

### 4. The record carries an extra field only where it names the lever

| bucket | extra | drawn from |
| --- | --- | --- |
| 1 | intent sought | ADR-0014's nine carryable intents plus the three uncarryable — set overlap, compositional simplex, origin–destination flow. **No new intent names.** |
| 2 | slot sought | ADR-0008's eight slots plus `window` and `pivot`, the named cuts — without those two the field cannot name the actual lever |
| 3 | none | the bucket is the signal |
| 4 | none | **do not invent `CheckResult` codes here** — that type is still fog (ADR-0005 D9) |

Both vocabularies already exist, which is ADR-0013 Decision 11's whole anxiety: this
reconciles, it does not mint a third list. **No free-text rationale** — a prose field feeding
a histogram invites text nobody reads, against ADR-0011's machine-first precedent.

**Bucket 2's field is not how the menu lever is fed.** ADR-0014 Decision 15 already
establishes that bucket reads empty on the corpus by construction, and the menu lever is
`raw_sql_used`. This field is for the rare *operating* custom-rail miss that is genuinely a
transform hole. The report must not put the menu diagnosis back on the histogram.

### 5. `make_chart(data) -> Figure` stays; the runner owns the environment

The signature does not widen. The runner establishes the environment and then calls —
**house style through `rcParams`, applied before invocation**, the exact analogue of ADR-0006's
option defaults applied after `assemble*`, one layer down. The palette rides on the job we
inject; it is never a second argument and never a value the model is asked to reproduce.

A palette change is therefore a sandbox re-call with new `rcParams` — still `$0.00` in LLM
cost. Had the prompt carried hex values, a rebrand would mean regenerating every custom-rail
chart with a model call, which is the `$0.00` pillar inverted.

**The prompt must forbid everything that beats `rcParams`**: `color=`, `cmap=`, face and edge
colours, `plt.style.use`, `seaborn.set_palette`, `seaborn.set_theme`. One explicit hex and the
runner's style context is theatre.

### 6. One module, one required symbol

The payload is a Python module defining `make_chart(data)`, imported and called by the runner,
with **no module-level side effects**. Third-party imports are `pandas`, `matplotlib`,
`seaborn`, `numpy`. Standard library is allowed **except network, process and
filesystem-write**.

ADR-0015 Decision 10's refusal stands: the model never writes files and never names a path, so
a script-that-emits-artifacts shape was never available.

### 7. The prompt says the network is unavailable; it never describes tiers

Network access is a property of the **boundary**, not the rail: ADR-0015's `none` is
subprocess plus rlimits with no network namespace, so generated code on that tier **can reach
the network**, while `os` and `vm` cannot.

The model cannot know the caller's boundary, and a prompt that says *"network may work"*
invites code that tries. So the prompt states network access is unavailable, flatly. The
`none` tier's reachable network is a **stated containment gap, not a capability we offer**,
and `require_isolation=True` is how a production caller avoids it.

### 8. Storing the generated code is required, and placing it is not this ADR's

**P0.5 cannot be met unless generated code is stored** — re-invoking with new data and no LLM
call requires the code to survive the request.

Placing it is **not decided here**. The reason and the code share one question — *does a
custom-rail result have an input frame at all, or is it a sibling result type?* — which is
exactly why `escape` placement is fog (ADR-0002, *Related*). Placing one places the other.

What changes is that entry's **standing**: it carries **two payloads**, not one; the code
needs a runtime and a version story the reason does not; and it now **blocks P0.5 and
ADR-0007's schema**. That is a fact for whoever reads the map next, not a ticket minted here.

### 9. `figure_json` is a closed per-artist extraction, and v1 names its set

Not a generic dump — matplotlib's own MEP25 says the semantics are not recoverable from the
figure without heuristics, so a generic dump would be large and meaningless.

**v1 covers `Line2D`, bar `Rectangle`s, and `PathCollection`.** Extending is additive. Named
here because otherwise two tickets invent two lists.

Not checked at v1: heatmaps, contours, filled areas, pie wedges.

### 10. Unreadable is *not checked*, never a pass and never a fail

An artist outside Decision 9's set yields an explicit **not checked**, reported. What that
does to `ReviewReport.passed` is the gate's (Decision 12), on the precedent ADR-0003 and
ADR-0005 already set for *unsupported* against *unavailable* — Excel's permanent Tier-1
status is a gate skip, not a rasteriser error.

The outcome this refuses is the dangerous one: *"we could not look"* reading as *"we looked
and it was fine."*

**Erratum on P0.8:** a chart fails when plotted values **mismatch**, not when they are
unreadable. P0.8's tolerance survives as float comparison on extracted values — it is not a
licence to leave jitter on.

### 11. The runner seeds; the prompt forbids the rest

The runner seeds `random` and `numpy.random` to a **named constant in the runner** — not a
`ChartJob` field, not configuration — **before the module is imported**.

`numpy.random.seed` does **not** seed `default_rng()`, so the prompt additionally forbids an
unseeded `default_rng` or `Generator`, along with `time`, `uuid`, `secrets` and `os.urandom`.

Same move as Decision 5: **we establish the environment rather than asking the model to
remember**. Recorded explicitly — seeding makes fabricated data *consistently* fabricated, so
it does not replace the truthfulness check; it makes that check's comparison meaningful.

### 12. The gate owns policy; this rail owns both prompts

The gate owns whether to repair, the budget, when to escalate, and light-mode review —
`ReviewReport.budget_exhausted` is already its (ADR-0005 Decision 9). This work owns the
**first-generation and repair prompt shapes**, because they are one competence and both must
restate Decision 1's return-type rule and Decision 5's no-override-colours rule, or they
drift. Splitting them by tier would split one prompt across two owners on a boundary the model
never sees.

### 13. One delimited-block renderer, consumed and not built

Both this prompt and the planner's render the same attacker-influenced profile content, and
ADR-0011 exports the taint manifest precisely so the rendering is mechanical.

There is **one** renderer, owned by the planner-output work (still fog). This rail **consumes**
it and does not build a second — committed now, while it is cheap, because a Tier-1 injection
lint that screens one renderer's output while a second feeds a different prompt is a gate with
a hole in it. The block's shape is not this ADR's; the extra content this prompt carries on top
of it is.

### 14. Fixed prompt at P2; skills are the widening path and nothing ships

P0.10's benchmark measures **this prompt**, and shipping a skills layer in the same phase would
make the ≥95% executable-output rate measure prompt-plus-skills with no way to attribute a
movement. Ship fixed, measure, then add skills as a measurable delta.

**One collision recorded while it is cheap: an org-convention skill must not carry the brand
palette.** Decision 5 puts the palette on the runner, and PRD §7.3 names "brand palette" as its
example org convention — so this will otherwise be built twice, with the skill silently losing
to `rcParams` or silently beating it. Fiscal-year annotations and the like remain good later
skills.

### 15. Custom-rail refresh runs in the sandbox

Re-calling `make_chart` is running code we did not write, and ADR-0015 Decision 1 admits no
*"we ran it before"* exception. So refresh is **zero inference cost and not zero
infrastructure**: a custom-rail chart cannot refresh without a boundary provisioned.

**Refreshing without the sandbox is unavailable**, recorded as such rather than left as an
aspiration.

**No figure caching on the refresh path.** Unchanged rows are a *Library load*, not a refresh —
ADR-0007 already caches rows for Flint cards, and that a custom-rail card cannot `assemble*`
those rows is **Studio's P2 hole, not a library licence to skip the sandbox**. A real refresh
has new rows and must re-run.

### 16. `__all__` is unchanged by this ADR

Nothing here is a new public type. `make_chart` is a convention the prompt states and the
runner enforces; `figure_json` is a `Format` value on ADR-0015's `ChartRun`; the escape
record's publicness rides on Decision 8's deferred placement, and will be settled with it.

## What this amends

- **ADR-0013 Decision 10's table and Decision 11's "three buckets"** — a **fourth** bucket,
  written by the gate at escalation (Decision 3). Decision 6 is untouched.
- **ADR-0015 Decision 10** — *"plotly and bokeh stay legal on this runtime"* is **withdrawn**.
  The runtime is still `python`; the **runner is `matplotlib.figure.Figure`-only** (Decision 1).
  The same decision's implication that closing the library gives `figure_json` a settled shape
  is corrected by Decision 9: it gives it a settled **owner**.
- **ADR-0015 Decision 9** — the image stack widens by **seaborn** and **numpy**. Still not the
  base wheel, still nothing on `[docker]`.
- **PRD §7.3** — *"the agent may choose any charting library"* is closed to a
  `matplotlib.figure.Figure` return at phase P2 (Decision 1); the *"brand palette"* skill
  example collides with Decision 5 and must not be built (Decision 14).
- **PRD §7.7** — the refresh box still names `chartagent.render`, retired by ADR-0005
  Decision 1; and custom-rail refresh requires a provisioned sandbox (Decision 15).
- **PRD §9 P0.8** — the chart fails on **mismatch**, not on unreadable values (Decision 10).
- **ADR-0002, *Related*** — the open `escape` question carries **two payloads**, reason and
  code (Decision 8).

## Consequences

- **The custom rail is narrower and more honest than the PRD's.** One library family, one
  return type, one prompt-stated constraint. The published executable-output rate has one
  variable.
- **The runner is where the environment lives** — style, seed, and the call itself. Three
  things the model would otherwise have to remember, and would sometimes forget.
- **The truthfulness check guards exactly what Decision 9 covers**, and says so where it does
  not. The review-gate work inherits that boundary rather than discovering it.
- **P0.5 is blocked until the code has a home**, and that home is the `escape`-placement fog
  entry, whose standing this ADR raises from tidy-up to blocker.
- **Custom-rail charts cost infrastructure to refresh**, which is a real argument for keeping
  rail share high, and a real deployment note for Studio and for embedders.

## Alternatives rejected

- **Open library choice with a soft prompt bias** — Decision 1. The metric it spends is
  published.
- **Open choice with a typed failure the review loop retries** — Decision 2. Burns quality
  budget rediscovering a constraint the prompt could state.
- **Folding escalations into bucket 3** — Decision 3. Sends the diagnosis to the wrong lever.
- **Escalations recording no reason at all** — Decision 3. Leaves ADR-0013 asserting an escape
  happened while recording nothing for it; the second-best option, and rejected only because
  the histogram is what Decision 10's procedure reads.
- **A free-text escape rationale** — Decision 4.
- **Palette in the prompt, or a second `make_chart` argument** — Decision 5. A rebrand would
  cost an LLM call per chart.
- **A generic matplotlib figure dump, or pickle** — Decision 9. MEP25 is Rejected and says why.
- **Failing charts whose values cannot be extracted** — Decision 10.
- **Caching figures to skip the sandbox on refresh** — Decision 15.
- **Splitting first-generation and repair prompts by tier** — Decision 12.

## What this feeds

- **Review-gate tier design** (fog) inherits: `figure_json`'s v1 artist set as the exact
  boundary of what truthfulness guards; *not checked* as a third outcome it must handle;
  bucket 4 as a number it produces; and policy ownership of repair, budget and escalation.
- **`escape` placement** (fog) inherits two payloads, a blocker on P0.5 and ADR-0007's schema,
  and the fact that the escape record's publicness is decided with it.
- **Planner output contract** (fog) owns the one delimited-block renderer this rail consumes.
- **Runner widening to plotly and bokeh** is a later, evidence-driven change — it needs a
  `figure_json` extraction per library, so it is not merely an import-list edit.
- **Skills** are the designed widening path for this prompt, minus the brand palette.

## Related

- PandasPlotBench — 1.8% incorrect code for Matplotlib against 22% for Plotly (PRD §7.3, §14)
- [MEP25: Serialization](https://matplotlib.org/stable/devel/MEP/MEP25.html) — **Status:
  Rejected**, *"this particular effort has stalled"*
- PRD §7.3, §7.5, §7.7, §9 P0.5 / P0.8 / P0.10, §11, §12
