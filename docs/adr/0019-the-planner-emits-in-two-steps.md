# 19. The planner emits in two steps, and the frame stays backend-free

- **Status:** Accepted
- **Date:** 2026-09-01
- **Settled on:** [#79](https://github.com/thearcscode/chartagent/issues/79)
- **Builds on:** ADR-0005 (`bind` is the public seam; the backend is a kwarg, not a field;
  the flat error taxonomy), ADR-0009 (validation is two-phase because the frame has no
  backend; 151 generated per-`(backend, chartType)` models), ADR-0010 (`source_schema` as a
  baseline), ADR-0011 (the profile contract; the taint manifest), ADR-0012 (selection is a
  filter over declared capability, never a fallback; ranking left open), ADR-0013 (the
  escape-reason vocabulary; rail is decided at plan time; retries are cost, not share),
  ADR-0014 (three runs per request; the bucket confusion table; bucket 2 reads zero by
  construction), ADR-0018 (`ChartRecipe.escape_reason` is the settled home)
- **Amends:** ADR-0012 Decision 7's open ranking question (**closed**, Decision 3);
  ADR-0014 Decision 12's cost line (**150 runs, not 150 calls**, Decision 6); ADR-0013
  Decision 6's *mean planner calls per chart* (its floor moves, Decision 6). Errata on
  PRD §7.9 and §9 P1.
- **Leaves open:** the prompt renderer itself, the planner's public surface, and
  `UnanswerableInstructionError` — all ticketed, none decided here.

## Context

Phase P1's planner sits between two settled surfaces and inherits a loop from them. Its
**input** is a typed **data profile** (ADR-0011). Its **output surface** is the generated
façade (ADR-0009). Its **envelope** is ADR-0001's and its **signature** is ADR-0005's.

The loop: `chartProperties` is typed by a model selected on **`(backend, chartType)`**, and
there are 151 of them, because key sets are not shared across backends — `Scatter Plot` is 6
properties on vegalite, 1 on echarts, 0 on excel. But the **input frame** has no backend, by
ADR-0005 Decision 2. So the planner must have chosen a backend before its own output can be
typed, and the planner is the thing that chooses the backend.

Three further things were carved out of P1's build specs because no ADR ratified them: what
a request the planner cannot express *does* at P1 (there is no custom rail until P2, so
ADR-0018's `escape_reason` has no instance to live on), which qualifying backend to prefer,
and the retry policy behind a number ADR-0013 Decision 6 already publishes.

## Decision

### 1. Two model calls, and the frame stays backend-free

Step 1 asks for the judgement. Step 2 asks for the settings. Between them, **code** picks
the backend — no second judgement, because Decision 3's ranking is a fixed list.

```
profile ──▶ step 1 (model) ──▶ backend-free fragment │ inexpressible
                                      │
                              code: filter + rank ──▶ backend
                                      │
                              step 2 (model) ──▶ chartProperties
                                      │                (checked against 1 of 151)
                              code: assemble ──▶ InputFrame  (no backend field)
                                                 + backend   (returned alongside)
```

**The emitted frame stays backend-free.** The backend is a *return value beside* the frame,
never a field on it — ADR-0005 Decision 2 is not weakened, and "one stored frame, five
backends" survives. The backend is chosen so that step 2 can be *checked*, not so that it
can be *stored*.

Rejected: emitting a backend-free frame and letting `bind` refuse (a bad property key is
caught after the planner has finished, so every repair becomes a full retry); and taking
structured output against a hand-written schema narrower than the generated models (a third
grammar beside the frame and the recipe, which is the widening ADR-0010 Decision 6 refused).

### 2. Step 1 returns a tagged union, and what code fills

Step 1's structured output is **either** a backend-free fragment **or** an inexpressible
verdict carrying a bucket. The miss path is a first-class outcome of step 1, not an
exception thrown from inside it.

```
Step1Result = Fragment | Inexpressible{ bucket: 1 | 2 }
```

| part | filled by | note |
| --- | --- | --- |
| `chart_spec.chartType`, encodings | **model, step 1** | the judgement |
| `x_chartagent.transform` | **model, step 1** | ADR-0008's eight slots, or `raw_sql` |
| `semantic_types` | **model, step 1** | generated values — **never copied from the profile** |
| `x_chartagent.source_schema` | **code** | profile buckets, transform source columns only |
| `x_chartagent.spec_version` | **code** | the constant `1.2` |
| `x_chartagent.annotations` / `interactions` | **code**, empty at P1 | nothing authors them yet |
| `theme_spec` | **caller**, or omitted | not a chart judgement |
| `options` | omitted | |
| `data` | **never stored** | ADR-0005 Decision 3's second refusal |
| backend | **code**, after step 1 | Decision 3 |
| `chartProperties` | **model, step 2** | checked against 1 of 151 |

Two of these are load-bearing rather than tidy.

**`source_schema` is code's, and it reads the profile.** It is the baseline that makes retype
drift detectable (ADR-0010), so a model that authors it can paper over the exact mismatch it
exists to catch. Scope is **the transform's source columns only** — a `SELECT *` contributes
nothing, and a transform with no source column yields `{}`.

**`semantic_types` is the model's, and it is never a copy of the profile.** The profile's
`reported_type`, column names and `top[].value` are in ADR-0011 Decision 10's **untrusted
subtree**. Copying an attacker-influenced value into a closed generated vocabulary is how
that vocabulary stops being closed.

### 3. The default ranking, and Excel is never a default

Selection stays ADR-0012 Decision 7's **filter** over declared capability. Among the
backends that survive it, a **fixed list** decides:

```
vegalite  >  echarts  >  plotly  >  chartjs  >  excel
```

**A backend named in the instruction wins over the list.** The list is the default, not a
policy that overrides a caller.

No special cases, and none are needed: the filter already routes every exclusive type. Sankey
Diagram, Network Graph, Tree and Parallel Coordinates are ECharts-only, so the filter leaves
one candidate and ranking never runs. Density Contour reaches Plotly the same way; Bubble,
Combo and Doughnut reach Chart.js.

**Excel is never chosen by default.** It declares 18 of the 48 types and carries every large
known realised-capability failure — refusal on empty-after-filter (353 of 365 measured), the
pyramid two-groups rule, candlestick ordering. It is reached by an instruction or by Studio's
target, never by the list.

Vega-Lite leads on 36 types, zero exclusives (so it never *has* to lead), a grammar closest
to our own frame, and a spec dialect that has not moved under us. ECharts follows on 37 types
and four exclusives, 5.1M weekly downloads, Apache-2.0 under ASF governance, matching
ADR-0006's Studio target. Plotly is third despite the widest coverage (38) and the most
release activity (12 in 12 months): **plotly.js 4.0.0 shipped 2026-08-24, three days after
our Flint 0.5.1 fixture pin was measured.** We store a frame and promise a zero-LLM refresh
years later; defaulting to the backend whose ecosystem just took a major break is the wrong
bet for a stored artifact. Chart.js is fourth on 22 types and one release in 12 months.

### 4. The ranking silences four of cell 3's six slots, and the report says so

ADR-0014 Decision 11 warned that delivery rate is partly a function of this policy. Measured
against the list above:

| cell-3 slot | fires under this ranking |
| --- | --- |
| discrete-channel overflow / silent row drop ×2 | **yes** — any backend |
| Excel empty-after-filter | no — Excel is never default |
| Excel pyramid two-groups | no — routes to vegalite |
| Excel candlestick order | no — routes to vegalite |
| ECharts non-painting boxplot | no — `Boxplot` routes to vegalite |

**Four of six silenced; the two row-drop slots remain.** Those two are exactly the floor
ADR-0014 Decision 11 built to be ranking-proof, so this is the anticipated case and not a
finding. **No boxplot special case is added** to make the fifth slot fire — engineering the
product to walk into a known hole so a stress cell reports is the mirror image of the
tuning ADR-0014 Decision 13 exists to prevent.

The gate is **not** reopened. The report names the ranking and lists the silenced slots.
Delivery rate rising because we stopped choosing the backends that fail is a true fact about
the product and a disclosed fact about the measurement.

### 5. At P1 the library writes no escape reason, and raises two errors

`ChartRecipe.escape_reason` stays the settled home (ADR-0018 Decision 11). **No
`ChartRecipe` is constructed at P1** — the custom rail is P2 — so the field has no instance
and needs none. No P1-only type is minted to hold it.

The bucket is carried by the **recorded planner output**, a harness artifact outside the
wheel. This is already how it works: ADR-0013 Decision 12 puts the histogram on the corpus
scorer's records, ADR-0014 Decision 16 has the scorer consume the reason *without depending
on where it is written*, and `tools/score_corpus.py` implements exactly that.

Two new errors, both under `ChartAgentError` in flat `errors.py` (ADR-0005 Decision 10):

- **`InexpressibleRequestError`**, carrying `bucket: 1 | 2` — step 1 returned a well-formed
  inexpressible verdict. Not `SpecVocabularyError`: nothing is malformed. Not
  `UnanswerableInstructionError`, which is a *different fault with a different lever* — a
  request that makes no sense against the data — and stays a separate P1 error decided on
  the public-surface ticket. Keeping them apart stops bucket 1 silently absorbing bad
  instructions.
- **`PlannerFailureError`**, with an optional closed `reason` of
  `retries_exhausted | invalid_emit | empty_response` — the planner broke rather than
  judged. Caller-facing semantics are the public-surface ticket's.

Buckets 3 and 4 are never raised here. Bucket 3 is scored, not self-reported; bucket 4 is
the gate's, at escalation, in P2.

### 6. Retry budgets, and the published number's floor moves

Separate budgets, because the two faults differ. A step-2 failure knows the backend and the
chart type and has the offending key in hand, so its repair is narrow; a step-1 failure is a
re-judgement and rarely improves twice.

| | budget |
| --- | --- |
| step 1 (fragment fails the backend-free façade check) | **1 retry** |
| step 2 (`chartProperties` fails its generated model) | **2 retries** |
| hard cap per chart | **5 calls** |

**A well-formed `{ inexpressible, bucket }` is never retried.** It is an answer, not a
failure.

**ADR-0014 Decision 12 says "150 planner calls" where it means 150 _runs_** — 50 requests ×
3 runs, at one call per run. Under Decision 1 a run is two calls, so:

- the scoring **floor is 300 calls**, and the **worst case is 750** at the 5-call cap;
- ADR-0013 Decision 6's *mean planner calls per chart* has a floor of **2.0 on a hit and
  1.0 on a miss** — at 70% rail share the no-retry baseline is ≈1.7, not 1.0.

Both are published. A reader who compares 1.7 against the old floor of 1.0 would conclude
the planner retries constantly, which is why the floor is stated beside the mean. **Retry
rate is published per step**, since the two point at different levers — the same argument
ADR-0013 Decision 10 makes for the histogram. Retries remain **cost, not share**
(ADR-0013 Decision 6). The gate is not reopened.

### 7. Buckets are trusted at run time; one contradiction is a schema failure

Verifying a claimed bucket in general needs the judgement we just paid a model for. So the
run time trusts it, and ADR-0014 Decision 16's expected-versus-reported diagnostic stays the
only check — which is what it was built to be.

**One case is not a bucket at all.** If step 1 claims bucket 2 — *the transform menu cannot
express it* — while the same response carries a valid `transform`, that is a
self-contradiction, and it is a **step-1 schema failure**: retried under Decision 6, and a
**planner-failure miss** if it survives the retry. It does **not** raise
`InexpressibleRequestError` and it is **not recorded as bucket 2**.

The reason is ADR-0014 Decision 15. Bucket 2 reads zero **by construction** on this corpus,
and a non-zero reading is *news* — a pre-registered `raw_sql` refused at scoring. Letting
malformed output land there would destroy that signal permanently, and it is the one signal
that distinguishes a design artefact from a finding.

### 8. A planner-failure miss carries no bucket, and the histogram reconciles

The four-bucket vocabulary stays closed. Planner failure is **not** folded into bucket 3 and
**no fifth bucket is minted**.

Bucket 3 means *an expressible frame was escaped anyway* — a wrong **decision**. A planner
failure is **no decision at all**; the planner never reached a judgement. They share a lever
and nothing else, and merging them would hide instability inside a quality number.

So the harness records `miss_kind: planner_failure` with `reported_bucket` **empty**, and the
scorer publishes **"planner-failure misses (no bucket)"** beside the histogram, asserting:

```
hits + buckets 1–4 + planner-failure misses + unattributed = n
```

**A miss with no `miss_kind` is a harness bug.** It is counted separately as *unattributed*
and **never guessed** as a planner failure — an unattributed count above zero is a named
check failure, not a rounding line. Without this the buckets sum to fewer than the misses
with nothing saying why.

## Consequences

- **A run is two calls, and every cost line in ADR-0013 and ADR-0014 moves with it.** The
  floor doubles to 300 and the cap is 750. This is the ADR's largest unglamorous effect.
- **`__all__` grows by two** — `InexpressibleRequestError` and `PlannerFailureError`.
  `UnanswerableInstructionError` is a third, decided elsewhere.
- **The scorer needs a small change it does not have**: the planner-failure count, the
  unattributed count, and the reconciliation assertion. `escape_reason_histogram` currently
  spans buckets 1–4 only, so a planner-failure miss would land in the denominator and vanish
  from the histogram.
- **Delivery rate will read higher than a ranking-blind planner's would**, and four of six
  cell-3 slots will report zero. Both are disclosed; neither reopens the gate.
- **ADR-0012 Decision 7's open question is closed** without needing the three inputs it named
  — instruction, quality dial, Studio's target — two of which are still P2. A fixed list plus
  an instruction override does not need them.
- **`ChartRecipe` is untouched and unconstructed at P1.** ADR-0018 needed no amendment, which
  was the point of putting the bucket in the harness rather than in a new type.
- **The prompt is still unwritten**, and ADR-0014 Decision 13's order still holds:
  `corpus-prereg-v1` was tagged at `b9b97f3` on 2026-08-30, before this ADR and before any
  prompt commit. The report names both dates.

## Alternatives rejected

- **One call, backend-free, `bind` refuses later.** Cheapest per chart and it matches
  ADR-0009 Decision 2's split exactly — but it converts every bad property key into a full
  re-judgement instead of a narrow repair, and the retry cost lands on step 1 where it helps
  least.
- **A narrower hand-written structured-output schema.** Small prompts, and a third grammar to
  keep in step with the frame and the recipe. ADR-0010 Decision 6 refused a smaller version
  of this.
- **Ranking by release activity.** Plotly leads on cadence (12 releases in 12 months against
  ECharts' 3) and on coverage (38 types). It is third, because a major version landed three
  days after our pin and we promise refreshes years out.
- **ECharts first.** One more cell-3 slot fires, which is a genuine measurement gain. Rejected
  for Vega-Lite's dialect stability and its closeness to our own grammar; the boxplot slot is
  disclosed as silenced rather than bought back.
- **Folding planner failure into bucket 3**, or minting a fifth bucket. The first hides
  instability in a quality number; the second reopens a vocabulary ADR-0013 Decision 11 and
  ADR-0016 Decision 3 both closed.

## Evidence

- 151 generated `(backend, chartType)` property models in `src/chartagent/frame/_generated.py`.
- Declared capability from `src/chartagent/frame/vocab.json` at Flint `0.5.1`: union 48;
  plotly 38, echarts 37, vegalite 36, chartjs 22, excel 18. Exclusives — echarts 4 (Sankey
  Diagram, Network Graph, Tree, Parallel Coordinates), chartjs 3, plotly 1, vegalite 0,
  excel 0. `Boxplot`, `Pyramid Chart` and `Candlestick Chart` are each declared by vegalite,
  echarts, plotly and excel.
- npm registry, retrieved 2026-09-01: plotly.js 4.0.0 (2026-08-24), 12 releases in 12 months,
  772K weekly downloads; echarts 6.1.0 (2026-05-19), 3 releases, 5.1M; vega-lite 6.4.3
  (2026-04-24), 6 releases, 969K; chart.js 4.5.1 (2025-10-13), 1 release, 12.9M.

## Related

- [#79](https://github.com/thearcscode/chartagent/issues/79) — the grilling this settles.
- ADR-0014 Decision 13 — the pre-registration order, still intact.
