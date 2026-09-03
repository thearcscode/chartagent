# 3. Rasterise in a browser, for the review gate only

- **Status:** Accepted
- **Date:** 2026-08-23
- **Resolves:** the deferral in ADR-0001 Decision 5 ("server-side rasterisation … is a separate
  decision"). ADR-0001 is amended in place with a dated pointer; its compile-path claim is
  untouched and still holds.
- **Feeds on:** `docs/research/rasterisation-options.md` (facts only, measured 2026-08-21)

## Context

The review gate needs a picture. PRD §7.3 puts a Tier-2 VLM critique inside the library's
pipeline, and a critique structurally cannot happen without a rendered image. ADR-0001
Decision 5 said the browser is the renderer and pushed rasterisation out as "a separate,
later" decision. This is that decision.

Two corrections to the framing this question arrived with, because both change the answer.

**Rasterisation is not Phase 0.** The ticket read PRD `P0.7` as "phase 0". It is a *priority
label*: PRD §11's own phase table puts the VLM review loop in **Phase 2** ("P0.5, P0.7, P0.8
green") and Playwright Tier-3 in Phase 4. The wayfinder map agrees. Nothing in Phase 0 renders
an image, so this decision is taken early — while the research is fresh and while it blocks
other map entries — not under schedule pressure.

**The non-browser options were costed against an architecture we no longer have.** The
2026-08-22 amendment of ADR-0001 removed the JavaScript engine from CPython. That makes
`vl-convert`'s headline property — "no browser, no Node" — misleading in our setting.
`vl-convert` rasterises a *Vega-Lite spec*; obtaining one means running Flint, which needs a
JavaScript runtime. Its API surface is fixed (`vegalite_to_*`, `svg_to_png`); it is not an
arbitrary-JS host, so it cannot compile Flint. ECharts SSR was measured *inside the embedded
engine*, and there is no embedded engine. Reaching for either would mean re-admitting a JS
engine to the Python process by the back door, which ADR-0001 has just rejected on its merits.

So **every rasterisation path now needs a JavaScript runtime we control.** The question is not
"browser or no browser" but *which runtime*, and where it is allowed to live.

The third constraint is fidelity, and it is the sharpest fact the research produced. A request
can be delivered on any of the five backends — ADR-0019 picks among them per request, it does
not fix one. Rasterising a different backend than the one actually delivered produces a
visibly different chart from the same input document: measured between ECharts and Vega-Lite
specifically, a different palette, a different series-to-colour assignment, y-axis to 2,500
versus 3,000, and rotated tick labels colliding with the axis title in one render and not the
other. A Tier-1 overlap lint reaches **opposite verdicts** on the two images. `theme_spec`
compounds it — ECharts silently ignores it, so a stand-in on that backend inherits a theme the
delivered chart never had.

**Erratum — 2026-09-03 ([#93](https://github.com/thearcscode/chartagent/issues/93),
ADR-0021).** This paragraph originally opened *"ECharts is the default web target"* —
rewritten above. No ADR ever decided that, and ADR-0021 confirms no backend is privileged
that way; the measured mismatch is the same regardless of which backend a given request
delivers on, which is the actual argument for **rasterise the delivered backend, always**
(Decision 3) rather than a fixed stand-in.

## Decision

**Rasterise the delivered backend in a browser running our own pinned client harness, behind a
public protocol, in an optional extra, for the review gate.**

1. **A P2 capability, decided now.** Nothing is built at Phase 0. The decision is taken early
   because three map entries hang off it; the code lands with the review gate in Phase 2.

2. **A public `Rasteriser` protocol; the library never hard-depends on a rasteriser.** The
   library defines the review gate and the protocol. The caller supplies an implementation; we
   ship a reference one in an optional extra. The compile path keeps its ADR-0001 promise
   exactly: no JavaScript engine and no browser is mandated in anyone's Python process.

   The **shape** is fixed here and the **signature** is not. Python holds only the envelope and
   cannot compile, so the protocol takes an **envelope** and returns **image bytes**, and the
   implementer owns compile-then-render. PNG is the v1 format. The protocol is public, because
   both the hosted app and CI implement against it. Parameter names, sync/async, and error
   types belong to the seam ticket, following the precedent that the layout decision settled
   boundaries, not signatures.

3. **The gate rasterises the backend it will deliver, or it does not run.** No stand-ins, ever.
   A gate that critiques a different backend is not less accurate — it can invert, as the
   opposite-verdict lint above shows. This is the load-bearing clause: everything expensive in
   this ADR is paid to keep it.

4. **The reference implementation is a browser running our pinned client harness.** The harness
   is a local page that loads the vendored Flint bundle, calls `assemble*`, hands the result to
   that backend's renderer, and screenshots.

   The decisive property is not fidelity but identity: **a browser *is* the client.** It runs
   the same bundle through the same assembler into the same renderer the user receives, so
   Decision 3 is satisfied *by construction, for every rasterisable backend, with no
   backend-specific code*. Any other route re-implements a rasterisation path per backend and
   hopes each one tracks upstream.

   **Playwright is named as the reference tool, not as the decision.** Replacing it needs no new
   ADR. What needs a new ADR is abandoning "a browser running our pinned harness."

5. **The harness is bound to the pin the envelope declares.** It loads the vendored IIFE at the
   recorded version and SHA-256 — the same artifact the wheel ships and the façade was
   generated from — never a CDN or an npm resolve. A gate that critiques a chart compiled by a
   different Flint build than the envelope names is Decision 3's problem in another costume, and
   the research shows Flint's compiled output moves between builds at the same version number
   (51.8% match once `config` is set aside). This extends the existing IIFE-hash ↔ `vocab.json`
   ↔ façade-constants test by one link, and is a **testable clause**, not an intention.

6. **What rasterisation is allowed to serve: the review gate.** That is the library's whole
   allowance. It exists so the gate can look at the delivered backend.

   Others may reuse the same public seam without widening the library's promise. The hosted
   product may rasterise for thumbnails — that is the app's call and lands on its own tickets,
   not here. CI may reuse it too.

   **No bit-stable PNG is promised.** A browser screenshot is not byte-stable, and Decision 4
   chose a browser knowingly. Golden tests therefore bind to the **compiled option object** —
   did Flint's output change? — never to pixels. That is cheaper and a truer statement of what
   the test is actually asserting. A user-facing PNG-export product remains out of scope.

7. **A skipped tier is reported, and "could not" is not "did not pass".** The review result
   records which tiers ran and which were skipped. `passed` is scoped to the tiers that
   actually ran. Budget exhaustion keeps its PRD P0.7 meaning — *we looked and it was not good
   enough*, best-so-far with `passed = False`. An absent rasteriser is a different fact — *we
   could not look* — and collapsing the two makes the gate's headline claim unfalsifiable: a
   critiqued-and-rejected chart would be indistinguishable from an uninspected one.

   Skips carry two **distinct** states, because they differ in what the reader should do:

   - **unavailable** — environmental, and an install instruction: the extra is not present.
   - **unsupported** — structural, and permanent: this backend can never be rasterised.

   **Excel is unsupported, forever.** It is not a raster target at all, and no browser changes
   that. Chart.js and Plotly are rasterisable *by a browser* and by nothing else available to
   us, which is a further consequence of Decision 4 rather than a limit.

   Stated plainly, because the PRD currently implies otherwise: the claim that **every** chart
   passes lint + VLM critique + interactivity review **does not hold for the Excel backend**,
   which receives Tier-1 lints only. Tier-1 is pure Python and always runs, image or no image.

8. **The Node-sidecar rejection still holds for compile.** ADR-0001 rejected `flint-chart-mcp`
   as a library runtime because it adds a second runtime to *every* deployment. Decision 2
   keeps that intact: a caller who never runs the review gate never installs a browser, and the
   compile path still ships zero runtimes. What is conceded is narrower than it looks, and is
   worth stating exactly — *"no second runtime"* was never absolute; it was **not on the compile
   path, and not for every install**.

   This is a **review** runtime for the library's own gate. It is not a compile service, and
   letting it drift into compile would reverse ADR-0001 by the back door.

## Consequences

**What we gain.** The gate critiques the artifact the user actually receives, for every
rasterisable backend, without a line of per-backend rasterisation code. Tier-3's infrastructure
cost is paid by this decision — `page.screenshot()` is one method call from a loaded page — so
interactivity checks become a scope question rather than an infrastructure one. Chart.js and
Plotly become reviewable at all, which no non-browser route offered.

**What we accept.** A ~1 GB image and a browser process for anyone who installs the review
extra. Screenshots are not byte-stable, so no pixel-level regression suite. Rasterisation
dominates the cost — the compiler is sub-millisecond; rasterisation is two to three orders of
magnitude more — so the gate, not compile, sets the latency of a reviewed chart. Excel charts
are permanently Tier-1.

**What this obliges us to build.** The `Rasteriser` protocol and the reference browser
implementation as an optional extra. The pinned harness page, plus the test binding it to the
recorded IIFE hash. A review result type carrying run / skipped, with unavailable and
unsupported distinguished. Golden tests over compiled option objects.

**What this hands downstream, deciding neither.** *Review-gate tier design* inherits the fact
that Tier-3's infrastructure is already paid; whether Tier-3 therefore moves earlier than the
PRD's Phase 4 is that work's call, not this ADR's. *The hosted app* inherits the deployment
facts: the gate runs during generation, so at Phase 2 a browser sits in the app's request path,
at ~0.98 GB compressed image (roughly 23× a `python:3.12-slim` base), hundreds of MB resident
per concurrent render, with Playwright recommending `--ipc=host` for Chromium — which weakens
container isolation in a multi-tenant setting. Sizing, pooling, and whether the gate runs
inline or queued are the app's decisions.

**A hazard to carry into the gate's implementation** *(closed for the custom rail by
[ADR-0017](0017-the-custom-rail-produces-an-interactive-web-document.md) Decision 15 — the
bootstrap reports a boolean paint signal on the channel, the rasteriser raises when it is
false, and an empty-container PNG is never success. It stands as written for the Flint path,
which has no symbol to call.)* A rasteriser that returns bytes without
raising has not necessarily rendered anything: `vl-convert` produces a blank chart and no
exception when a `data.url` is unreachable. Whatever the implementation, the gate must not treat
"no exception" as "rendered". Flint inlines rows in 700 of 705 fixtures, so this is a narrow
path — and narrow paths are where a gate quietly hands a VLM an empty canvas.

## Evidence

From `docs/research/rasterisation-options.md`, measured 2026-08-21 on macOS 15 / arm64 against
`flint-chart` 0.5.1, reproducible from `prototypes/rasterisation-probe/`:

- **Backend mismatch is the real fidelity risk**, and it was rendered rather than argued:
  `build/cmp_vegalite.png` and `build/cmp_echarts.png` are the same input document at the same
  canvas size, differing in palette, series assignment, y-axis extent (2,500 vs 3,000), legend
  placement, and label collision.
- **Non-browser paths do not cover the delivered backend.** Chart.js needs a native Canvas
  implementation; Plotly's Kaleido v1 is a headless Chrome; Excel is not a raster target.
  `vl-convert` is Vega-Lite only (705/705, p50 27 ms). ECharts SSR reached 650/667 at p50
  1.8 ms — inside the embedded engine that no longer exists.
- **Browser footprint**: `mcr.microsoft.com/playwright/python:v1.61.0-noble` linux/amd64 is
  0.98 GB compressed across 4 layers (largest 807 MB), versus 43 MB for `python:3.12-slim`.
  Uncompressed size, cold start, and per-render memory were not measured and are not guessed at
  here.
- **Static rasters are blind to interaction.** Flint sets `options.addTooltips` in 656 of 705
  fixtures (93%); ECharts' own SSR documentation lists tooltips and legend toggling as
  unsupported. A non-browser raster cannot show a VLM the chart's dominant interaction.
- **Determinism is what a browser costs.** Non-browser rasterisation was byte-stable (30/30
  identical PNGs); a browser screenshot is not. Decision 6 moves golden tests off pixels rather
  than pretending otherwise.

**Licence, verified 2026-08-23.** The research left "Chrome for Testing / Chrome binary licence
terms for a commercial hosted service" open. It does not bite: `playwright install chromium`
fetches **open-source Chromium**, and Playwright's documentation states that for Chromium-based
browsers it "uses open source Chromium builds" by default. Google's branded binaries arrive only
through the opt-in `chrome` / `msedge` channels, which point at a locally installed browser. We
do not opt in. ([Playwright browsers](https://playwright.dev/python/docs/browsers))

**Facts still unmeasured, and now mostly moot.** Linux font resolution was the research's
highest-value gap; it mattered for `vl-convert`-versus-browser fidelity, and Decision 4 removes
that comparison from the design. Browser cold start and per-render memory remain unmeasured and
are the hosted app's to measure against its own deployment.

## Alternatives rejected

**`vl-convert` as the default rasteriser.** Rejected. Its advantage was "no Node, no browser",
which was true when we embedded an engine and is not true now: it cannot compile Flint, so it
needs a JavaScript runtime in front of it regardless. It is Vega-Lite only, which under
Decision 3's *rasterise the delivered backend* rule means the gate would not run at all
whenever a request delivers on ECharts, Chart.js, Plotly or Excel — four of the five backends
a real request can land on, regardless of how often each one does (ADR-0021: it's Vega-Lite
that leads the ranking, not ECharts). It remains a perfectly legitimate *caller-supplied*
implementation for a Vega-Lite-only deployment — the protocol exists so that choice stays
available.

**Node plus per-backend SSR** (ECharts SSR → SVG → resvg, Vega-Lite → `vl-convert`). Rejected as
the default. It is lighter and byte-stable, and it structurally cannot cover Chart.js or Plotly
— which under Decision 3 means the gate silently never runs for two of five backends. It also
buys a per-backend rasterisation surface we would have to keep tracking upstream. Available to
anyone who wants the footprint, via the protocol.

**A stand-in backend** — rasterise Vega-Lite, deliver ECharts. Rejected outright; see Decision 3.
This is the cheapest option on the table and the only one that would make the gate actively
misleading.

**Rasterisation outside the library entirely**, with the review gate as an app feature.
Rejected. It would keep ADR-0001 pure at the cost of demoting "every chart passes a review gate"
from a library promise to a product feature — a far larger amendment than this ADR, contradicting
PRD §7.3, and one that would leave every non-hosted caller with no gate at all.

**A browser as a compile runtime.** Not rejected on cost — rejected on scope. Once a browser is
present it is tempting to let it compile too, which would reverse ADR-0001's client-compile
decision without arguing against it. The browser here runs the gate's harness and nothing else.

**Erratum — 2026-08-28 ([#57](https://github.com/thearcscode/chartagent/issues/57),
ADR-0017).** *"The gate's harness and nothing else"* was written to stop the review browser
drifting onto the **compile** path, and that intent is intact. It now also loads the custom
rail's generated document — **inside an inner sandboxed iframe** at an opaque origin, with our
harness as the outer page. Playwright must **not** navigate to the generated HTML as the
top-level page: that would hand the document the harness's own origin and make the review
render a different thing from the user's. **No Flint IIFE is loaded on that path at all.**

## Related

- ADR-0001 — the compile path, the pin, and Decision 5, amended 2026-08-23 with a pointer here.
- ADR-0002 — the input frame; `theme_spec` precedence, which the ECharts stand-in problem depends
  on.
- `docs/research/rasterisation-options.md` — every measured number above; facts only, no decision.
- Review-gate tier design — inherits Tier-3's paid infrastructure cost and the run/skipped
  result contract; owns the phasing.
- The seam ticket — owns the `Rasteriser` protocol's signature.
- The hosted app ticket — owns deployment shape under the browser-in-request-path facts.
