# backend-capability

Throwaway probe behind **ADR-0012** and [#9](https://github.com/thearcscode/chartagent/issues/9).
Every number in that ADR comes from `probe.mjs`.

## Running it

The corpus and the pinned bundle live in `prototypes/flint-embed/build/`, so run from there:

```sh
cd ../flint-embed
./setup.sh                       # if build/ is not already populated
node ../backend-capability/probe.mjs
```

Node runs at probe time only — never on the compile path (ADR-0001, amended 2026-08-22),
never at install time ([#19](https://github.com/thearcscode/chartagent/issues/19) §9).

## What it asks

**1. What does the pin's declared chart-type list predict?** Compile all 705 fixtures
through all five assemblers and classify every throw.

**2. Does a change to the rows alone change the verdict?** Take each backend's *accepted*
set and empty, shrink and reverse the rows with the spec untouched. This is the direction
that matters: a chart that binds today and refuses tomorrow is a zero-LLM refresh breaking
with nobody having edited anything.

**3. Is `excel + (column|row)` exactly the faceting refusal?** Both directions, plus a
stability check that the rule reads the encoding key set and nothing else.

## Results at Flint 0.5.1 / fixture commit `34ef451`

| backend | accepted | type undeclared | faceting | everything else |
| --- | --- | --- | --- | --- |
| vegalite | 705 | 0 | 0 | 0 |
| plotly | 705 | 0 | 0 | 0 |
| echarts | 667 | 38 | 0 | 0 |
| chartjs | 595 | 110 | 0 | 0 |
| excel | 365 | 146 | 102 | 92 |

The declared list is **exact** for ECharts (38/38) and Chart.js (110/110), and no fixture
with an undeclared chart type was accepted on any backend. Excel's 340 are three different
kinds of refusal and only the first is visible to the vocabulary.

Row mutation, spec untouched, over each accepted set:

| backend | accepted | zero rows | one row | reversed |
| --- | --- | --- | --- | --- |
| vegalite, echarts, chartjs, plotly | 2672 | 0 | 0 | 0 |
| excel | 365 | **353** | **19** | **2** |

The facet biconditional: 102 faceted frames refuse for faceting, **0** faceted frames are
accepted, **0** faceting refusals occur without a facet channel. The other 12 faceted frames
refuse earlier for an undeclared chart type. All 102 verdicts are stable across every row
mutation, with every value rewritten as a string, and with `semantic_types` deleted.

## Two gotchas, so they are not rediscovered

**Testing row-sensitivity on the *refused* set is biased.** A fixture that already throws
keeps throwing under mutation, and the message rarely changes, so it reads as "stable" when
nothing was established. The informative direction is *accepted → refused*, which is what
`rowSensitivity` measures.

**Removing `data` entirely is degenerate.** Every assembler throws without it, so "can this
be decided without rows?" cannot be asked that way. It is also the wrong question: `bind`
*has* the rows — it runs the transform and attaches them. The real constraint is that `bind`
has no Flint and may not grow a copy of one.
