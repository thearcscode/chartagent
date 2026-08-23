# 6. The server binds, the browser compiles

- **Status:** Accepted
- **Date:** 2026-08-24
- **Settled on:** [#26](https://github.com/thearcscode/chartagent/issues/26)
- **Builds on:** ADR-0001 (compile in the client), ADR-0002 (the input frame *is* the
  spec), ADR-0003 (rasterise in a browser — deferred out of v0 here), ADR-0005 (`bind` is
  the seam this app consumes)
- **Governs code that lives elsewhere.** Studio is
  [`thearcscode/chartagent-studio`](https://github.com/thearcscode/chartagent-studio) —
  private, and empty as of this date. The ADR lands in the library repo because the
  wayfinder map carries both tracks and the ADR sequence should not fork before the second
  repo holds a single file. Studio adopts this ADR by reference when it starts.
- **Decides nothing about:** the host vendor, the object-store vendor, the storage schema
  ([#28](https://github.com/thearcscode/chartagent/issues/28)), or the editor surface
  ([#27](https://github.com/thearcscode/chartagent/issues/27)).

## Context

Studio v0 is a spec editor and renderer: open a stored Flint frame, see it render, save
it, refresh it against new data at `$0.00`. No planner, no LLM, no agent. It exercises
exactly what P0 builds, which makes the zero-cost refresh pillar demonstrable before a
planner exists.

**Three of the ticket's six questions arrived already answered, and one arrived void.**
The sync/async question asked what `async` means for *"the compile call, which is
sub-millisecond but sits behind a GIL-holding C extension and a context pool that forbids
cross-thread sharing."* There is no C extension, no context pool, and no compile call in
Python at all — ADR-0001's 2026-08-22 amendment deleted the engine. What `bind` does is
DuckDB and Pydantic. Rendering location was confirmed by ADR-0005 rather than decided
here. And whether the deployment choice constrains rasterisation is answered by Decision
12: v0 does not rasterise.

**Two findings changed what the remaining questions could mean.**

*`design/` is not liftable.* The three canvases contain no stylesheet and no class layer —
every visual is an inline `style=` attribute — and they are not written in HTML: `<helmet>`,
`{{ binding }}`, `style-hover=` and `x-import` are a bespoke runtime implemented in
`support.js` (69 KB), with 63 such constructs in the UI canvas alone. Nothing in them can
be ported. What crosses into an application is a token block, and Decision 14 is the whole
of "how `design/` becomes real."

*`assembleExcel` does not produce a file.* Its own type declaration: *"The Excel 'native
spec' is a declarative description of an Office.js chart… A host renders it imperatively
via the Office.js Excel API."* It returns an `ExcelChartSpec`, and `generateOfficeJs()`
emits Office.js source. ADR-0001 Decision 6 said as much — Excel *"needs an Office.js host,
not a general web framework"* — but the consequence had never been priced. Decision 8 pays
it.

## Decision

**The server binds and serves bytes it can pin. The browser compiles and draws. Studio is
a plain public-API consumer with no exception, and v0 owns no runtime the library does not
already imply.**

### 1. The server binds; the browser compiles; there is no public API in v0

The SPA calls `POST /specs/{id}/bind {backend}`, the server calls
`bind(spec, data, *, backend)`, and the **envelope** comes back as JSON. The client loads
the pinned Flint IIFE, calls `assemble*`, and hands the result to the renderer. **The
server never sees a compiled option object**, which is ADR-0001 Decision 5 expressed as a
request flow rather than a claim.

`Envelope.warnings` crosses in the response body — `theme_spec_ignored` included —
and `row_count` and `elapsed` feed the cost-and-latency line every screen in `design/`
carries.

Routes are **SPA-private behind a Clerk session**: no API keys, no OpenAPI promise, no
versioned paths. The library is the public contract; a second one would cost stability
guarantees v0 has no business making.

### 2. One Docker web service on `python:3.12-slim`, and no host vendor is chosen here

The shape is locked, the vendor is a later ticket. **glibc is forced twice over** — duckdb
ships no musllinux wheels (#19) and Playwright ships no musl browsers (ADR-0003) — so
Alpine and musl are out with no remaining argument on either side.

Postgres and, at P2, a Playwright-image background worker are **separate services added
later**, so the ~0.98 GB browser image never enters the web service's image or its cold
start. Fly.io's process-per-tenant advantage is not weighed here because it no longer
exists as an advantage: it was an argument about the JavaScript context pool, and
[#21](https://github.com/thearcscode/chartagent/issues/21) closed with the engine.

### 3. FastAPI, one uvicorn process, `def` for anything that binds

Sync `def` endpoints for routes that call `bind`, so Starlette runs them in its threadpool
and DuckDB never blocks the event loop; `async def` for pure I/O. `abind` arrives at P1
(ADR-0005), and this decision is what changes when it does.

### 4. Vite + React + TypeScript, styled with plain CSS custom properties

No UI component library, no CSS framework, **no Tailwind, no CSS-in-JS**. Styling is the
same mechanism `design/` uses, which is what keeps Decision 14 enforceable.

TypeScript earns its place because the browser is where compile lives: `assemble*` and a
317-entry vocabulary are worth typing. Server-rendered HTML with htmx was rejected outright
— the compiler runs in the client, so the server has nothing to render.

### 5. One repo, two languages, and no Node in the runtime image

`app/` (FastAPI, `pyproject.toml`, `[tool.uv.sources]` per #20) beside `web/` (Vite). A
two-stage Dockerfile: `node:22` builds the SPA, `python:3.12-slim` copies only `web/dist/`.
Node stays what it is in the library — a build-time tool for a human, never a deployment
dependency.

### 6. Nothing is fetched that cannot be pinned

- **Flint is never installed from npm.** The pin is the IIFE's bytes and `vocab.json`'s
  SHA-256, not a semver range, so `npm i flint-chart` would silently break it. The client
  loads the bundle **the server hands it** from `chartagent.flint_bundle()`, served at a
  SHA-256-stamped, immutably-cached URL, and compares the served `.sha256` against the
  value the app was built against — a mismatched pin fails loudly instead of compiling
  against the wrong vocabulary. `flint-chart` may sit in `devDependencies` **for its
  TypeScript types only**, at the exact pinned version.
- **Renderers come from npm at exact versions**, lockfile committed, each behind a
  per-backend dynamic `import()` so a renderer is fetched the first time its backend is
  chosen. Flint declares them as optional peers with ranges (`echarts ^5||^6`,
  `vega ^5||^6`, `vega-lite ^5||^6`, `chart.js ^4`, `plotly.js ^2||^3`); Studio pins inside
  those ranges. Measure the four chunks before assuming the split earns itself; pin
  regardless.
- **Fonts are self-hosted** — Instrument Serif, IBM Plex Sans (400/500/600), IBM Plex Mono
  (400/500) as woff2 under `web/public/fonts/`, `font-display: swap`, real fallback stacks.
  All three are SIL OFL 1.1. The mockups use Google Fonts; the application does not.
- **No CDN split for statics.** FastAPI serves the SPA, the bundle and the fonts via
  `StaticFiles`. Fetching at a version string is not fetching bytes, which is the hazard
  ADR-0001 measured.

### 7. All five backends, never hardcoded

`echarts`, `vegalite`, `chartjs`, `plotly`, `excel` are on the v0 allowlist. `backend` is a
**validated request field**, never a constant in the app — ADR-0005 made it a required
kwarg with no default precisely so the choice stays explicit.

The house palette reaches the web backends through **our own option defaults applied after
`assemble*`**, never through `theme_spec`, which ECharts discards. The
`theme_spec_ignored` advisory is surfaced, not swallowed: it is the project's most-cited
silent failure, and v0 is where it stops being silent.

Whether backend-switching is a *visible affordance* is #27's call. This decision only fixes
that all five are reachable.

### 8. Excel is a workbook, not a canvas — and not a native chart

Given the finding above, v0's Excel deliverable is **one `.xlsx` written server-side by a
plain writer (`xlsxwriter`)**: the bound rows as a table, plus a second sheet carrying the
generated Office.js. One file, opens in Excel, contains exactly what Flint produced, and
claims no chart it did not draw.

Mapping `ExcelChartSpec`'s Office.js `ChartType` enums onto `openpyxl`'s chart writer is
**rejected**: it is a Python port of a Flint backend, which is a second compiler and sits
on `CONTEXT.md`'s *Avoid* list. A bare `.js` download is rejected for the simpler reason
that it is not a workbook.

**340 of 705 fixtures are unsupported by Excel**, so `BackendCapabilityError` is the
*common* Excel outcome rather than an edge case. `isExcelSupported()` gates the affordance
before the request is made.

### 9. Refusals, not degradation

**`baseSize` is pinned in every compiled option.** After `assemble*`, the client compares
the compiled series' point count against `envelope.row_count`; on a mismatch it **refuses
to draw and names the drop**. ADR-0005 refused a predictive row-drop warning on the grounds
that the drop is Flint's decision, at compile, in the client — which makes this client the
only party that can ever see it happen.

Four caps, **all as configuration, none as literals**: a 50 MB upload limit, a row cap that
**raises rather than truncates**, a DuckDB statement timeout, and a server request timeout.

Truncation-as-a-feature is rejected. A chart quietly showing 8 of 12 quarters is the exact
failure this design system was built to refuse, and `design/`'s screen `5b` is the pattern:
name the drift, refuse to draw, offer the repair.

### 10. Uploads and URLs, no warehouse connectors, and the container filesystem is not a store

v0 accepts **CSV/Parquet uploads and DuckDB-readable HTTPS URLs**. No Postgres, Snowflake
or BigQuery connectors — which keeps **customer warehouse credentials out of the
application entirely**, the single largest cut available to #28's security surface, at no
cost to the demo: refresh-against-new-data is a re-upload or a changed URL.

Bytes go to **object storage behind a narrow app-side interface, with a local-filesystem
implementation in dev**; the vendor is deferred exactly as the host vendor is. The web
service's filesystem is ephemeral and is not a store. Postgres `bytea` is rejected —
columnar files are what it is worst at, and the P2 worker would be pulling multi-MB blobs
through the database to reach them.

### 11. Real accounts from day one, via Clerk, and `owner_id` is not deferred

Sign-in and create-account are real in v0. **Clerk's prebuilt `<SignIn/>` and `<SignUp/>`,
restyled through its `appearance` API against our tokens** — Decision 4's no-component-library
rule protects the product surface, and auth chrome is not it; prebuilt also carries email
verification, reset and error states v0 would otherwise own. No house key, no env-var
password, no user table of ours.

FastAPI **verifies the session JWT locally against cached JWKS**. No Clerk API call per
request: the app exists to demonstrate a sub-millisecond claim and will not put a network
round-trip in front of it.

**#28 stores `owner_id` — the Clerk user id — on every saved record from the first
schema**: specs, data-source pointers, credentials. Not deferred, not added later. This is
identity only; multi-tenancy and metering stay in the map's fog.

### 12. No rasterisation and no stored thumbnails in v0

ADR-0003 left thumbnails to the app and recorded that no bit-stable PNG is promised. v0
takes neither. Saved-spec cards **re-render live in a small canvas** — the client already
holds the IIFE, the renderer chunk and the envelope, so a card costs one more `assemble*`
and nothing on the server.

This keeps the ~0.98 GB image, the hundreds of MB per concurrent render, and
`--ipc=host`'s weakened isolation out of v0 entirely. It is also the better demonstration:
every card on the page is itself an instance of the `$0.00` refresh claim.

### 13. Failure is typed and legible; logs are structured and local

One **error-mapping table** in `app/`: each `ChartAgentError` subclass → status code →
user-facing message, with the error's own fields carried in the response body, so the UI
can name a `SchemaDriftError`'s `DriftedField` list rather than say something went wrong.
An unmapped exception is a 500 with a request id and nothing else. `pydantic.ValidationError`
never crosses the seam (ADR-0005), so it never reaches this table.

**Structured JSON logs to stdout, no third-party APM in v0.** Every `bind` logs backend,
`row_count`, `elapsed` and any advisory codes — which is also the audit trail behind the
cost-and-latency line, at no extra cost.

### 14. The design system crosses as one file, and a check binds every copy

**`design/tokens.css` is canonical**: the `:root` block and the `body[data-theme="light"]`
override, extracted verbatim from `Chartagent UI.dc.html`, which declares the superset.

`palette-check.py` **keeps its literals** — a check that read its subject as its own
reference would prove nothing — and now asserts **literals ≡ `tokens.css` ≡ every canvas**.
The assertion is one-directional: `tokens.css` is the superset, a canvas declares whatever
subset it uses, and every token a file *does* declare must match. Not every file must
declare every token — the two landing canvases carry no `--series-*`, and no light block
redeclares them, because one data palette serves both themes.

**Studio vendors the file byte-identically at `web/src/tokens.css`** with the source SHA
recorded beside it, and its CI fetches `design/tokens.css` at the same pinned library SHA
it already resolves (#20) and diffs. Drift fails red on the app side, where the copy is.

Rejected: **tokens in the wheel** (the library ships no UI, and ADR-0005 froze `__all__` —
a token accessor would widen the seam for a CSS file); **an npm package** (a publish
pipeline and a second version space for thirty lines of CSS); **a component library**
(Decision 4).

Studio is **dark by default**, with the toggle persisted in `localStorage` — not Clerk
`publicMetadata`, not a database column. It is a per-device convenience, and #28's schema
should not carry a UI preference before it carries a spec.

### 15. Studio's CI, and one test that proves the architecture

On every PR: `ruff` and `mypy --strict` on `app/`; `tsc`, `eslint` and `vitest` on `web/`;
the Decision 14 tokens diff; the library resolved via its pinned git SHA (#20); a Docker
build; and **one Playwright smoke test that loads a saved spec and asserts a canvas
rendered with the expected series count**.

That last one is not optional garnish. Nothing else in the pipeline proves the claim the
whole architecture rests on — that the served IIFE plus a lazily-imported renderer actually
compiles and draws in a real browser — and a green Python suite beside a broken client is
precisely the failure five ADRs have been spent avoiding. The heavy image lands in CI only,
never in the runtime image (Decision 5).

**Node 22, Python 3.12, npm with a committed lockfile.** The library's matrix is 3.11–3.14
with 3.14 blocking (#19); an application pins one runtime, and it is the one its base image
carries.

### 16. The hosted product is named Chartagent Studio

The repo already committed to the word. `CONTEXT.md`'s Language section is amended to name
it, so the glossary carries a name where it carried a placeholder: the library is
`chartagent`, the application is **Studio**.

## Consequences

**What we gain.** A v0 with no runtime the library does not already imply: one glibc
container, one process, and a browser that was always going to be the compiler. Every byte
the client executes is one we pinned and served. And the `$0.00` claim is demonstrable on
day one without a planner, a model call, or a rasteriser.

**The seam held.** This ticket was the second dogfooding pass over ADR-0005, and unlike the
first it found **no new gaps**: `flint_bundle().sha256`, `vocabulary()`, `canonical_json`,
`Envelope.row_count` / `.elapsed` / `.warnings` and the nine typed errors covered all
sixteen decisions above. Nothing goes back to the seam ticket, and the P0 public surface
stands as ADR-0005 froze it.

**What it costs.** Excel's download is honest but not a chart, and for 340 of 705 shapes
there is no download at all. A saved-spec list compiles once per card in the client, which
is fine at v0 scale and is a real cost to revisit when a list gets long. `design/`'s mocked
sign-in and create-account screens are superseded by Clerk's components before they were
ever built — two screens to revisit if the auth chrome ever matters enough. And the
one-service shape means the P2 browser arrives as new infrastructure rather than a config
change, which is the trade made deliberately in Decision 2.

**What this cancels.** A hosted-app skeleton is not part of this decision — the map's
*plan, don't do* rule holds, and nothing in `chartagent-studio` is scaffolded by it.
Deployment-target speculation in the ticket about isolation and process-per-tenant is
closed rather than deferred: with no JS realm there is no isolation seam to place.

## Alternatives rejected

**A buildless vanilla client, continuous with `design/`.** Rejected. The mockups are
buildless because they are mockups; the real client holds the frame document, runs the
compiler, generates a form from `vocabulary()`, renders a canonical-JSON diff and juggles
valid / unrenderable / drifted states. That is application state, and hand-rolled
reactivity over it is a cost paid every week to save a toolchain once.

**A single deployment secret instead of accounts.** Rejected in favour of Clerk on the
grounds that retrofitting identity means migrating every stored record, and #28 writes its
first schema next. Recorded because it was the recommendation: v0 is a demonstrator, and a
shared secret would have been defensible.

**One backend (ECharts) in v0.** Rejected. *One spec, five backends* is one of the
product's better arguments and the app is where it becomes visible; an allowlist of one
would have made it a claim rather than a demonstration.

**Google Fonts and a CDN for renderers.** Rejected by the same rule that keeps Flint off
npm: the app should not execute a byte it cannot pin. A self-hosted instance also renders
identically with no external network, which matters the first time it is demonstrated on
someone else's wifi.

## Related

- ADR-0001 — the pin, the compile path, and Decision 6's Office.js note, which Decision 8
  turns into a product consequence.
- ADR-0003 — the browser rasteriser and its deployment facts; Decision 12 declines them for
  v0 without contesting them.
- ADR-0005 — the seam Studio consumes; `flint_bundle()`, `vocabulary()` and `canonical_json`
  exist because this ticket and #27 needed them.
- [#27](https://github.com/thearcscode/chartagent/issues/27) — the editor surface; owns
  backend-switching as an affordance, and styles from `design/tokens.css`.
- [#28](https://github.com/thearcscode/chartagent/issues/28) — storage; unblocked by
  Decision 11, and bound by it to `owner_id` from the first schema.
- `design/README.md` — the design system's reasoning; `design/tokens.css` is now the
  artifact that crosses.
