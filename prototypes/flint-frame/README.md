# flint-frame — evidence probe for ADR-0002

Reproduces every measurement quoted in `docs/adr/0002-adopt-flint-input-frame.md`: what
Flint's input frame actually contains across all 705 fixtures, and whether a document can
carry our own grammar in a sibling key without perturbing what upstream compiles.

**This is a measurement probe, not the spec implementation.** No Pydantic façade, no
validation, no CI job. None of that is here.

## Setup

Reuses `../flint-embed/build/`, so there is exactly one pinned Flint in the repo. Run that
prototype's setup first:

```bash
cd ../flint-embed && ./setup.sh
```

Needs Node only — this probe never touches the embedded engines, because the frame is a
property of Flint, not of the JavaScript runtime we execute it in.

## Run

```bash
node probe.mjs survey        # what the frame contains, across 705 fixtures
node probe.mjs transparency  # does an unknown key change the compiled output?
node probe.mjs churn         # dependency surface and chartProperties usage
```

## What each check establishes

| Check | Establishes |
| --- | --- |
| `survey` | The frame is four keys wide (`data`, `semantic_types`, `chart_spec`, `options`), `chart_spec` is three keys plus an optional bag, and `chartType` is an open vocabulary of 33 strings rather than a closed union. |
| `transparency` | An unknown sibling key is inert on all five backends, provokes no `_warnings`, and deleting it restores the original document byte for byte. The same payload nested in `chartProperties` is *equally* inert — the placement choice is not decided by present behaviour. |
| `churn` | `flint-chart` has zero runtime dependencies; only 4% of fixtures use `chartProperties` at all, which is also where every breaking change has landed. |

## Gotchas found the hard way

- **Not every fixture compiles on every backend.** Excel rejects 340 of 705, Chart.js 110,
  ECharts 38. A parity number is meaningless without saying which backend produced it, and
  a transparency check has to compare each backend against *its own* baseline rather than
  treating a throw as a difference.
- **`_warnings` needs a separate assertion.** The comparison strips `_`-prefixed keys, so a
  key that is silently ignored and a key that provokes a complaint both read as
  "byte-identical". Check the warning set explicitly.
- **`theme_spec` and `field_display_names` appear in no fixture.** They exist on the API but
  are unexercised by upstream's own test data, so nothing here validates them.
- **Fixture inputs are wrapped:** the assembler argument is `input.json → .input`, not the
  file root — same trap as `../flint-embed`.
