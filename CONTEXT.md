# chartagent

An embeddable agentic chart-creation library for Python, plus Chartagent Studio, the hosted application that consumes its public API.

## Language

**chartagent**:
The Python library (singular). Also the product name and the `x_chartagent` namespace.
_Avoid_: chartagents (abandoned plural), ChartSpec-as-the-stored-document

**Chartagent Studio**:
The hosted application, and its name. A separate product in a separate repo
(`thearcscode/chartagent-studio`) that consumes chartagent's public API only. In speech it
is **Studio** against **the library**. Its server binds; its browser compiles (ADR-0006).
_Avoid_: the app as a second compiler, sidecar, "the hosted product" as a name

**Input frame**:
Flint's assembler argument — the document we store and return. It is `data` (at render time), `semantic_types`, `chart_spec`, `options`, `theme_spec`, plus `x_chartagent`.
_Avoid_: ChartSpec (retired grammar), compiled spec, option object

**Envelope**:
The library's last object. Its wire format is exactly three keys: `{ flint_version, backend, input }`. `input` is the input frame. `backend` is `bind`'s required argument — the planner fills it from P1 on — and the caller may ignore it and pass the same `input` to a different assembler. Diagnostics (`row_count`, `elapsed`, `warnings`, `source_schema`) ride on the object and never serialise into `input`.
_Avoid_: compiled ECharts option, Vega-Lite spec, PNG as the library return; widening the wire format

**x_chartagent**:
The one top-level sibling on the input frame that holds our grammar (`spec_version`, `transform`, `annotations`, `interactions`, `source_schema`). Flint ignores it. **Five keys, not six**: `escape` left the set with ADR-0018 — a custom-rail result is a **chart recipe**, not a frame with a flag — taking `spec_version` to **1.2**. Nothing was migrated, because canonical JSON omits nulls and `escape: null` was never in stored bytes.
_Avoid_: putting our grammar in `chartProperties`, an `escape` key (retired), reading 1.2 as a promise anyone notices the grammar moved

**Source schema baseline**:
`x_chartagent.source_schema` — the types the spec was *planned against*, as a map of referenced source columns to coarse buckets (`number`, `string`, `boolean`, `date`, `timestamp`, `timestamptz`, `other`). It is what a retype is detected against, so it must not move when the data does. Distinct from Studio's `data_sources.schema_snapshot`, which records the **source's** schema at registration and changes whenever the source changes: the two agree on the day a chart is created and diverge immediately after. The library computes it (`Envelope.source_schema`, what *this bind* saw); the caller's save writes it into the frame.
_Avoid_: calling it a schema snapshot, `semantic_types` (that is Flint meaning on transform *output*), a whole-source-schema copy, storing DuckDB logical types

**Data profile**:
The profiler's output — `profile.json`, one artifact describing **the source**, read by the planner and by our Phase-2 checks. Internal at P1: a VFS file and a private type, not in `__all__` (ADR-0011). Machine-first — exact fields, no prose, no pre-rendered summary; the prompt-facing rendering is a separate serialisation of the same object. Four keys: `row_count`, `columns`, `sample_rows`, and `truncation` when a rung fired. Carries no source path, no timestamps, no version field.
_Avoid_: profiling the transform output (encodings bind to output; the planner infers it), a public `profile()` verb, Studio computing its own, a `stratified` sample (not deliverable before a stratum column exists)

**Degradation ladder**:
How a profile holds its 10 KB cap on a wide source: truncate `reported_type` → drop `sample_rows` → drop top-values → drop percentiles → cap `columns` and report `omitted_count`. **Rungs fire for the whole profile or not at all**, which is what keeps `stats: null` decodable — it means emptiness (`null_rate == 1.0` or `row_count == 0`) unless `truncation.rungs` says a rung took it.
_Avoid_: a per-column rung, a zeroed `truncation` object when nothing fired, a name-and-bucket stub for every column at the terminal rung

**Saturating cardinality**:
`distinct` is exact below `N = 1001` and reports `saturated: true` above it. Precision where the decision changes — *can this be a categorical axis?* — and saturation where it does not. Every Phase-2 cardinality cap stays strictly below `N`.
_Avoid_: `approx_count_distinct` (measured wrong in both directions: 36 for 39, 300,210 for 250,000), `SUMMARIZE`'s `approx_unique`, an exact full `DISTINCT` on a 10 GB source

**Untrusted subtree**:
The parts of a data profile that are attacker-influenced, under one rule: **a statistic computed *over* untrusted values is ours; a value *copied from* untrusted data is not.** So `top_k_coverage` and `iso8601_parse_rate` are ours; `columns[].name`, `reported_type`, string extrema, `top[].value` and `sample_rows` keys and values are not. Expressed as a manifest the module exports and the prompt renderer consumes, never as a field in the artifact, and enforced by a test asserting every model field is classified.
_Avoid_: per-field taint marks inside `profile.json`, tainting the whole artifact, a new field that is in neither set

**Bind**:
What the library does: take a stored input frame plus a data source, run `x_chartagent.transform`, attach the rows as `input.data`, and return the envelope. `chartagent.bind(spec, data, *, backend)`. It neither compiles nor rasterises.
_Avoid_: render (retired — the library does not render), `chartagent.render`, calling bind a compile step

**Bind cache**:
Studio's, not the library's. The last *successful* transform output for a saved chart, written to object storage as `{ revision_id, rows }` JSON by a user-initiated bind, and pointed at by one `bind_caches` row. A Library load fetches it instead of binding — the deterministic rail compiles it in the client, the custom rail renders it in the iframe — and a stale or missing pointer shows *Refresh to bind*. **Rail-independent**: nothing on the custom rail calls `assemble*`, so ADR-0016 D15's *Studio's P2 hole* is closed (ADR-0018). Rows only — never the envelope, the backend, or an advisory, because `theme_spec_ignored` is backend-dependent (ADR-0007).
_Avoid_: thumbnail, stored render, caching the envelope; treating a cache read as a refresh, or a Library load as a reason to re-read the source

**Advisory**:
A frozen `{ code, message }` object on `Envelope.warnings`, describing something the library did or ignored — not a Python warning, because the caller has to render it. Distinct from Flint's `_warnings`, which are produced at compile time in the client and never reach CPython.
_Avoid_: `warnings.warn`, conflating these with Flint `_warnings`

**Compile**:
Flint turning an input frame plus rows into a backend-native document (`assembleECharts`, `assembleVegaLite`, …). Happens in the client, not in CPython.
_Avoid_: embed, in-process engine, sidecar as the compile path

**Rasterise**:
Turning a compiled backend document into PNG or SVG bytes. A separate job from compile.
_Avoid_: treating rasterise as what the library returns

**Zero-LLM refresh**:
Re-running the stored `transform` for new rows with no model call — `bind` plus a compile on the deterministic rail, `bind_recipe` plus a re-render in the iframe on the custom rail. **The two rails have the same failure modes**, because `bind_recipe` never reads the code (ADR-0018); they diverge only at paint. Zero inference cost, **not** zero infrastructure on the custom rail — it needs a browser. On Excel, compile can still refuse when the new rows are empty or too few; `bind` succeeding is not that refusal.
_Avoid_: storing compiled output, storing rows in the spec, treating the custom rail's refresh as free of infrastructure

**Declared capability**:
What the pin says a backend can draw: `(backend, chartType)` read off `vocab.json`, plus one named rule — Excel with a `column` or `row` channel. Pin-derived, data-free, decidable in CPython, and what `bind` raises `BackendCapabilityError` on. Exact for four of five backends; on Excel it is 146 of 340 refusals plus the facet rule's 102 (ADR-0012).
_Avoid_: `CapabilityProfile`, a `supports()` predicate (that is `vocabulary(backend)` renamed), calling it a coarse form of realised capability

**Realised capability**:
Whether the assembler accepted the document and whether the output actually painted. Client-side, after compile, **reported and never predicted** — and on Excel a function of the rows, which is why the library refuses to model it. Applicability (`data_dependent`, 161 of 317 entries) lives here too.
_Avoid_: a Python mirror of `assembleExcel`, a measured `(chartType, shape)` accept-list, treating `bind` succeeding as evidence the chart compiles

**Rail routing**:
Choosing the deterministic rail or the custom-code rail for a request (PRD §7.3). What the deterministic-rail share measures.
_Avoid_: "router" unqualified, conflating it with backend selection

**Rail share**:
The fraction of corpus requests served by the deterministic rail. Denominator is every request; custom rail, refusal, planner failure and *nothing in the 48 fits* all count against. A `raw_sql` chart is **in** the numerator (no codegen, no sandbox, `$0.00` refresh); the `raw_sql_used` rate is published beside it. Gated once at P1 exit on the pooled 50-request corpus, when the Wilson 95% lower bound falls below 60% (ADR-0013).
_Avoid_: measuring it against the chosen backend rather than the union, a rubric or human-labelled share before the planner exists, folding `raw_sql_used` or delivery rate into it

**Delivery rate**:
Whether a chart actually painted **and** the compiled row count equals the bound row count — the second number beside rail share, never merged with it. Where realised-capability failures land: Excel refusing on empty rows, the pyramid two-groups rule, the 17 non-painting ECharts boxplots, and Flint's silent layout row-drop (ADR-0014). The rail is chosen before anything compiles, so none of these is a rail-share miss. Its denominator is requests that emitted a compilable artefact, and the excluded count is published beside it.
_Avoid_: charging realised capability to the rail share, or dropping it and letting the share stand for what users received; treating a painted chart missing rows as delivered; minting a combined end-to-end figure

**Common-path stratum**:
The 30 requests of the pressure corpus that carry the common-majority *story* — not an unstressed set. Twenty-two are unstressed (cell 0); the other eight are pre-registered stress that belongs on the common path, because ordinary traffic contains it: four menu-miss/`raw_sql`-hit, two silent-row-drop, and two ambiguity (ADR-0014 D2). Reported beside the pooled 50, never gated on its own. It is where the `raw_sql_used` figure that carries menu-coverage meaning is measured.
_Avoid_: **representative** (it claims an external population no available request corpus supplies), gating on it alone, reading its `raw_sql_used` quota as the measured rate

**Adversarial stratum**:
The 20 requests of the pressure corpus that carry a pre-registered stress, budgeted across four cells: *no intent in the 48*, *menu-miss and `raw_sql`-hit*, *realised-capability risk*, and *expressible but hostile* (ADR-0014). Its difficulty is frozen with the ratio, because on the gate's arithmetic difficulty is what decides the outcome.
_Avoid_: **nasty** as a single undifferentiated bucket, tuning difficulty after seeing scores, putting a shape `raw_sql` cannot carry in the menu-miss cell

**Backend selection**:
Choosing which of Flint's five backends a frame is bound for — the planner filling `bind`'s required `backend` kwarg. A **filter** over declared capability, never a runtime fallback. Two tiers (ADR-0021): **`requested_backend`** first — an extraction-only field on step 1's output, closed-enum typed, filled iff the instruction names a backend (never a chart judgement, never stored on the frame) — checked against the declared-capability filter on its own; if it fails, `BackendCapabilityError` raises right there, between step 1 and step 2, no retry and no fall-through to the ranking. Otherwise the **fixed default ranking** among filter survivors decides: `vegalite > echarts > plotly > chartjs > excel`. **Excel is never chosen by the ranking**, only by `requested_backend`. **Studio carries no standing target** — it is a plain caller like every other, and gets the same ranking a script would (ADR-0021; corrects the PRD's "ECharts remains the default web target", never an ADR decision). Exclusive types need no special case — the filter leaves one candidate and the ranking never runs (ADR-0019). The order lives once, as `BACKEND_RANKING` beside `Backend` in `frame/input.py` — never hand-copied.
_Avoid_: "router" unqualified, silent re-routing on `BackendCapabilityError`, a `backend` field stored on the frame, treating the ranking as a fallback, a per-chart-type special case, falling `requested_backend` through to the ranking on a capability miss, treating Studio's ECharts preference as real

**Flint pin**:
The exact `flint-chart` version the façade, the fixture jobs, and client `assemble*` must share. Paired with a fixture commit: `FIXTURE_COMMIT` must resolve to the git tag named by `FLINT_VERSION`.
_Avoid_: unpinned npm resolve, a Python port as the compiler, "CI oracle" (there is none — see **Bump gate**)

**Fixture invariant**:
The per-commit assertion that adding and then deleting `x_chartagent` leaves compiled output and `_`-prefixed metadata unchanged across the fixture corpus. Self-relative, so it needs no reference output. Its failure means our architecture broke.
_Avoid_: calling it a parity or regression test

**Bump gate**:
The differential job that runs when the Flint pin moves: the same fixture inputs compiled by the IIFE we shipped and the IIFE we are about to ship. It asks what changed between two pins, never whether output is correct.
_Avoid_: an oracle, upstream `expected.json` as a reference, an allowlist of forgiven diffs, re-fetching the old pin from npm

**Dirty input**:
A fixture `input.json` that names a property the pin's vocabulary does not declare. Tracked as a count: existence is upstream dirt, a rising count on a bump is a failure.
_Avoid_: an exceptions file, treating any dirty input as a failure by itself

**Sandbox** *(python widening only — not phase P2)*:
Where **programs we did not write** run **in the later python widening** — generated `make_chart` code, and nothing else. It does not contain the data vector (hostile file bytes are a named, unsolved gap) and it does not contain the transform (in-process, held by ADR-0008's three `raw_sql` locks). It receives the transform's **output** rows and never the source: no path, no credentials, no raw bytes. Reached through `SandboxBackend`, ours, adapted from deepagents' rather than inherited (ADR-0015). **Phase P2 builds none of it** — its custom rail is the web profile, whose untrusted code is contained by the sandboxed iframe and the `Rasteriser`'s browser instead (ADR-0017 D3).
_Avoid_: "the sandbox is where data lives", sandboxing the profiler or the transform, `upload`/`run`/`download` as its shape, deepagents' `SandboxBackendProtocol` in our public contract, treating it as the phase-P2 custom rail's containment

**Boundary kind**:
How strong a sandbox's wall is, as one of three values on a public `backend.boundary`: `none` (subprocess — rlimits only), `os` (bwrap, docker — kernel-sharing namespaces), `vm` (Firecracker-class). `require_isolation=True` means *not `none`* and raises at construction rather than falling back. **The boundary is the wall, not the rlimits** — absent cgroup v2 does not make bwrap into `none` if namespaces work. A third party can misdeclare its own kind; that is accepted and unverifiable.
_Avoid_: the four-tier ladder and tier numbers (bwrap-versus-docker is not a sound ordering), reading it as "has memory limits", a capability set, inferring it from `PATH`

**Sandbox runner** *(python widening only — not phase P2)*:
The harness *we* inject around generated **Python** code. Phase P2 is the web rail and implements no `SandboxBackend` at all; this describes the later widening. It **owns the environment**: it applies the house palette through `rcParams` and seeds `random` and `numpy.random` to a named constant, both *before* the module is imported, then calls `make_chart(data)`, serialises what comes back, and returns `Mapping[Format, bytes]` — so the job **requests formats** and the model never declares or names an artifact. The pattern is ADR-0006's one layer down: we establish the environment rather than asking the model to remember it. `figure_json` is how the data-truthfulness check reads numbers, so a reviewed chart always requests it. Returned bytes are capped.
_Avoid_: third-party backends reimplementing `Figure` serialisation, the model naming a path, artifacts crossing via the deepagents VFS, treating `plt.savefig` output as a returnable artifact

**Runtime profile** *(python widening only — not phase P2)*:
Which image a sandbox session runs — chosen at `__enter__`, because the image is chosen there. It belongs to the **python widening**, which comes later: **phase P2's custom rail is the web profile, and it runs in a browser rather than a sandbox image** (ADR-0017 D2/D3). A backend asked for a profile it lacks is *unsupported*, not a crash.
_Avoid_: putting it on `ChartJob`, calling `python` the phase-P2 profile or `web` a §9 P1 fast-follow (ADR-0015 D7 is **reversed**), conflating the web rail's sandboxed iframe with ADR-0003's rasterisation harness — the harness page is ours, the document inside it is not

**Custom rail**:
The path taken when a request cannot be served by the deterministic rail. The agent writes an **interactive web document** — a JS module defining `render(data, el)` and `getPlottedSeries()`, plus optional CSS scoped to `el` — which runs in a **sandboxed iframe at an opaque origin** in Studio's browser, with rows and theme arriving by `postMessage`. **Library choice is open**: the agent names a package and version, or writes from scratch (`libraries=()`). The escape must not be a downgrade from the rail it escapes, which is why it is not a static image. Refresh re-renders the stored document against new rows: zero inference cost, **not** zero infrastructure — it needs a browser.
_Avoid_: `make_chart(data) -> Figure` and the matplotlib closure (ADR-0016 D1, withdrawn), a library allowlist or per-library catalogue, running the document on Studio's own origin, `python` as the phase-P2 profile (it is the later widening)

**Escape reason**:
Why a request left the deterministic rail — one of **four** buckets, each naming a different lever: *no chart type in the 48* (upstream, not ours), *the transform menu cannot express it* (grow the menu), *an expressible frame was escaped anyway* (planner quality), and *expressible, produced, failed review* (the gate's own numbers). The planner writes the first three at plan time; the **gate** writes the fourth at escalation. Buckets 1 and 2 carry one closed lever-naming field; 3 and 4 carry none. **Where it is written is settled**: `ChartRecipe.escape_reason`, required on every recipe and carried forward by a patch that does not change why the chart escaped (ADR-0018). The histogram reads the corpus scorer's records, never `spec_revisions`. **At P1 the library writes no escape reason at all** — no chart recipe is constructed, so the field has no instance; the bucket rides on the recorded planner output and the library raises instead (ADR-0019).
_Avoid_: three buckets, calling the field `reason` or `escape`, a field on `x_chartagent`, folding an escalation into *planner quality*, a free-text rationale, reading bucket 2's field as the menu-coverage signal (that is `raw_sql_used`), treating bucket 4 as a stress cell or a grammar-change button

**Planner step 1 / step 2**:
The planner's two model calls (ADR-0019). **Step 1** returns a tagged union — a backend-free fragment (`chartType`, encodings, `transform`, `semantic_types`) or an inexpressible verdict carrying bucket 1 or 2. **Code** then runs backend selection. **Step 2** fills `chartProperties` against one of the 151 generated models, and does not resend `sample_rows`. The emitted input frame stays **backend-free**; the backend is returned beside it, never stored on it. Budgets are 1 retry at step 1, 2 at step 2, a 5-call cap; a well-formed inexpressible verdict is never retried.
_Avoid_: a `backend` field on the frame, one call with the check deferred to `bind`, a hand-written schema narrower than the generated models, the model authoring `source_schema`, `semantic_types` copied from the data profile, retrying an inexpressible verdict

**Inexpressible request**:
A request the planner cannot express as an input frame at P1, raised as `InexpressibleRequestError` carrying `bucket: 1 | 2`. Distinct from `UnanswerableInstructionError`, which is a request that makes no sense against the data — a different fault with a different lever, fenced on **column existence**: every referenced concept maps to a real column but the grammar can't shape it (inexpressible), versus a named or implied column that genuinely isn't there (unanswerable). There is no custom rail at P1, so the library raises rather than escapes (ADR-0019).
_Avoid_: `SpecVocabularyError` (nothing is malformed), folding it into `UnanswerableInstructionError`, constructing a chart recipe at P1, buckets 3 or 4 (scored and gate-written, never raised)

**Unanswerable instruction**:
A request that makes no sense **against the data**, even though the grammar could express the chart it's asking for — raised as `UnanswerableInstructionError` with `kind: "missing_column" | "missing_role"` and `keys: tuple[str, ...]`. `missing_column` names columns the instruction claims that the profile doesn't have; `missing_role` names the **absent source buckets** — the same seven-value vocabulary `source_schema` uses, not a new role taxonomy — with `keys=()` for an unspecific ask that names no bucket in particular. A claim the profile already refutes (a named column that *does* exist) is a **step-1 schema failure**, not this error — the same treatment ADR-0019 gives a self-contradictory bucket-2 claim (ADR-0020).
_Avoid_: `InexpressibleRequestError` (see the fence above), a `role: str` field naming a semantic role the profiler doesn't speak, a third `kind` for an unspecific ask (it's `missing_role` with `keys=()`), a `reference` field beyond `keys`

**Planner failure**:
The planner broke rather than judged — `PlannerFailureError`, with an optional closed `reason` of `retries_exhausted | invalid_emit | empty_response`. It is a **rail-share miss carrying no escape reason**: the harness records `miss_kind: planner_failure` with `reported_bucket` empty, and the scorer publishes the count beside the histogram so that hits + buckets 1–4 + planner-failure + unanswerable-instruction + unattributed = n (ADR-0020 adds the fourth term). A step-1 response claiming bucket 2 while carrying a valid `transform` is a schema failure and lands here, never in bucket 2 (ADR-0019).
_Avoid_: folding it into bucket 3 (that is a wrong *decision*; this is no decision), a fifth bucket, guessing an absent `miss_kind` as planner failure, letting a contradiction pollute bucket 2's expected-empty reading

**Plotted-series declaration**:
What `getPlottedSeries()` returns — the custom rail's data-truthfulness input, compared **outside the document** against transform output we already hold. A **declaration, not an extraction**: general extraction is impossible on a web rail because ECharts and Chart.js paint to `<canvas>` and D3's SVG is per-author. Its weakness is deliberate and recorded — **it catches an honest bug, not a determined lie** — so P0.8's guarantee is rail-dependent, and the Tier-2 VLM is the only thing that looks at the picture.
_Avoid_: `figure_json` as matplotlib artists (retired with ADR-0016 D1), DOM extraction as a general answer, reading it as equal in strength to the deterministic rail's guarantee

**Chart recipe**:
The custom rail's stored artifact and the input frame's **sibling** — not a frame with a flag, because a frame must name a `chartType` Flint never draws. `ChartRecipe` is `spec_version` + `transform` + `source_schema` + `escape_reason` + `theme_spec` + a `ChartDocument`. `bind_recipe(recipe, data) -> BoundRecipe` runs the transform, drift-checks, and attaches rows — **it never reads `module`, `styles` or `libraries`**, so a refresh cannot fail on the code. **`BoundRecipe` cannot paint and `BoundDocument` can**: the bound recipe has rows but no theme and no library bytes, which are paint-time inputs Studio and the `Rasteriser` supply. It has no wire format, because nothing compiles it. Stored beside frames in `spec_revisions.content` under `kind = 'recipe'` (ADR-0018).
_Avoid_: an escape field on `x_chartagent`, `ChartDocument` as the stored artifact, `bind_recipe` returning `BoundDocument`, a wire format for `BoundRecipe`, a sixth table, calling it a frame or a spec

**Chart document**:
What the custom rail **stores**: `module` + optional `styles` + a tuple of `LibraryPin`s (name, version, sha256, in **script load order**) + `contract_version`. It **cannot paint** — it has no rows, no theme and no library bytes. Its paintable counterpart is the **bound document** (`BoundDocument`), which adds all three, exactly as `Envelope` is a bound frame. `build_shell` turns a chart document plus verified bytes into the iframe shell. It is **never stored bare** — a **chart recipe** contains it (ADR-0018).
_Avoid_: unioning `ChartDocument` where a paintable type is required, storing it as the whole custom-rail artifact (it has no `transform`, so refresh has no rows), putting bytes on a `LibraryPin`, calling the stored triple an HTML document, inlining libraries into the stored artifact

**Shell**:
The host-owned iframe page: HTML, CSP, container element, hashed `<script>` tags, and the `postMessage` bootstrap that calls the agent's two symbols. **The agent never writes it** — in particular never the `event.source` check, which is the one line whose omission lets any opaque iframe drive the chart. `build_shell` is public and in the base wheel because Studio and the `Rasteriser` are two callers of one builder. It is **rows-free and theme-free**, so the review picture is the thing the user sees.
_Avoid_: a second shell implementation, `assemble` in its name (Flint's word), returning bare HTML without the iframe sandbox tokens, letting the iframe fetch anything

**Chart agent**:
The public planner entry point: `create_chart_agent(model=...) -> ChartAgent`, then `agent.create_chart(data, instruction) -> ChartResult` — one call, profiling, both planner steps, and `bind` all run internally. Sync only; single-shot only, with no `history=` (needs a VFS, P2) and no `quality=` (needs the review gate, P2). **Signature only at P1** — `plan/` and the prompt don't exist yet (ADR-0020; #92 builds them).
_Avoid_: `sandbox=`/`outputs=`/`quality=`/`backend=` kwargs at P1 (nothing to configure, or the answer belongs to a later ticket), a reserved no-op kwarg for anything P2-only, treating this as implemented before #92 lands

**Chart result**:
What `create_chart` returns — a thin wrapper over `Envelope`, never itself a wire type: `ChartResult.envelope` plus `refresh(data) -> ChartResult`. `refresh` re-binds against new rows with zero model calls (this is **zero-LLM refresh**, spelled out as a method), strips the inline `data` a stored envelope already carries before re-binding, and returns a **new** `ChartResult` — the original is untouched, and there is no `instruction=` because refresh never re-plans. `bind`'s own errors surface un-wrapped from `create_chart`, already `ChartAgentError` subclasses (ADR-0020).
_Avoid_: flattening `Envelope`'s fields onto `ChartResult` (duplicates or drifts from the frozen three-key wire format), mutating `refresh`'s receiver in place, passing `envelope.input` straight back into `bind` (guaranteed `SpecShapeError` — the inline-`data` rejection test_bind.py already covers)
