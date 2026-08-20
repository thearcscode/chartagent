# chartagents — UI mockups

Interactive UI mockups for chartagents, built from `chartagents-prd.md` and
`prototypes/chartspec-v1/README.md`. The library ships no UI, so these define the
surface layer around it: a design system, the five places a chart lifecycle
becomes visible, and a public landing page.

Each file is a self-contained HTML document. Open it directly in a browser — no
build step, no install. `support.js` must sit alongside them. Charts render live
via ECharts (CDN), the PRD's default web target.

## Files

| File | Contents |
| --- | --- |
| `Chartagents UI.dc.html` | The mockup canvas — design system plus every product screen, grouped into numbered turns |
| `Chartagents Landing.dc.html` | Marketing landing page with interactive hero, plus sign-in and create-account screens |
| `Chartagents Landing Ideas.dc.html` | Scratch file: the three landing sections in isolation before they were folded into the page |
| `support.js` | Runtime required by the three documents |

Every screen supports a light and dark theme, toggled by the moon icon at the top
right of each turn header (or the app chrome, where a host app would put it).

## Screen index — `Chartagents UI.dc.html`

Screens are grouped by turn, newest first. Ids are stable and referenced in
review comments.

**Turn 5 — lifecycle detail screens**

- `5a` Patch mode edit review. Before/after charts, the two-hunk spec diff, and
  the light-mode review showing which 2 of 9 checks re-ran.
- `5b` Schema drift recovery, three steps: detected (spec-vs-snapshot field
  table) → remapping (`plan_tier` → `tier_name`, plus a cast for the retype) →
  refreshed (spec 1.0 → 1.1, $0.00, mapping recorded). Advance with the button.
- `5c` Escape-reason telemetry. Reason histogram, drill-down showing `pie + line`
  as 311 of 438 `E_LAYER_COMBO` runs, a proposed grammar change with estimated
  rail shift, and custom-rail share by release. Intended as a fourth tab in `1c`.

**Turn 3 — merged inspector, light mode in situ**

- `3a` Run inspector combining the rail diagram and the event log. The diagram is
  the default view; each stage's "details ›", the tier rows, and the
  Overview/Log switch open the log. Interactive.
- `3b` The embedding app pinned to light tokens, ignoring the global flip, so
  both palettes can be judged side by side.

**Turn 2 — streaming UX alternatives**

- `2a` Split-path diagram: the two-rail architecture is the picture, with the
  untaken rail dashed and the routing reason called out.
- `2b` Event log: every emitted event, nested critique findings, live caret.

**Turn 1 — foundations and the five surfaces**

- `1a` Foundations. Surfaces, ink, rail color semantics, chart series palette,
  type scale, atoms.
- `1b` Embedding app — the "describe the chart you want" feature a SaaS product
  ships, with a "How this was made" panel.
- `1c` Developer run inspector — profile → plan → rail → review, streaming.
- `1d` Playground — instruction in, spec/artifacts/review/code out.
- `1e` Spec and review report — ChartSpec JSON, capability match, T1 lints, T2
  critique rubric, repair history.
- `1f` Lifecycle console — saved specs, scheduled refreshes, `SchemaDriftError`
  row and recovery panel.

## Design system

Dark-first, neutral ink, two accent hues. All values are CSS custom properties on
`:root`, with a `body[data-theme="light"]` override; nothing else needs to change
to reskin.

**Surfaces** (dark → light)

| Token | Dark | Light |
| --- | --- | --- |
| `--bg` | `#0a0a0c` | `#e9e7e2` |
| `--app` | `#121216` | `#ffffff` |
| `--panel` | `#17171c` | `#faf9f7` |
| `--raised` | `#1d1d23` | `#f1efea` |
| `--rail` | `#0f0f13` | `#f6f5f2` |

**Ink and borders**

| Token | Dark | Light |
| --- | --- | --- |
| `--ink` | `#ecebf0` | `#191817` |
| `--muted` | `#8b8a97` | `#6b6862` |
| `--faint` | `#6a6975` | `#8f8b83` |
| `--border` | `#2a2a32` | `#dcd8d0` |
| `--border-strong` | `#3d3d47` | `#bfb9ae` |

**Semantic accents.** These carry the core product idea and are used
consistently, chart series included.

| Token | Meaning | Dark | Light |
| --- | --- | --- | --- |
| `--teal` | deterministic rail | `#57d3cb` | `#0d8f86` |
| `--violet` | custom code rail | `#a78bfa` | `#6b4de0` |
| `--amber` | needs review | `#e8b568` | `#a8730c` |
| `--red` | drift / error | `#e8737d` | `#c33f4b` |
| `--blue` | fifth series | `#7aa2f7` | `#3a6fd8` |

Chart series use teal → violet → amber → blue → red in that order, which the
Tier-1 colorblind-safe palette lint enforces.

## Type

Three families, each with one job. Never more than one in a single line.

- **Instrument Serif** — display and moments of authorship (page titles, chart
  titles, large figures). Tracking tightens as size grows.
- **IBM Plex Sans** — all chrome, labels, body copy. 400/500/600.
- **IBM Plex Mono** — anything the machine produced: specs, field names, event
  logs, metrics, error codes, section eyebrows.

All three are SIL OFL 1.1 — free for commercial use, embedding, and modification,
with no attribution required in the product.

## Notes for implementation

- Rail color is load-bearing, not decoration. Teal means no generated code ran;
  violet means the sandbox did. Don't reuse either hue for anything else.
- Every screen states cost and latency. The `$0.00` refresh claim appears
  wherever a saved spec is re-rendered.
- Errors name the drift and refuse to draw. There is no partial-render state in
  these designs on purpose — `5b` step 1 is the pattern.
- Type scale floors: chart labels 10px mono, body 12.5px sans. Nothing smaller.
