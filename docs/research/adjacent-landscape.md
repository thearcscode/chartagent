# Research: Adjacent-library landscape before the development phase

AFK research. A pre-build scan of the libraries, frameworks, and research systems that
overlap with chartagent — the ones worth knowing *before* architecture locks in and major
changes get expensive. Companion to `flint-chart-leverage.md` (which covers
`microsoft/flint-chart` in depth). Surfaces facts + a "what to do about it" per entry; the
decisions graduate from here.

- **Date:** 2026-07-22
- **Trigger:** Flint surfaced late and nearly got missed. This is the deliberate sweep to
  make sure nothing else in the same class does.
- **Scope:** six categories — (1) spec-mediated / intermediate-language charting,
  (2) formal viz-design knowledge bases, (3) end-to-end agentic viz pipelines,
  (4) AI-charting products/frameworks, (5) BI-as-code / refresh-forever analogs,
  (6) evaluation methodology.

---

## TL;DR — the five that matter most

Ranked by how directly they should change a decision *before* dev starts:

1. **Draco / Draco 2 (UW)** — the rigorous, learnable form of chartagent' own thesis
   ("design knowledge in the library, not the prompt"). Hard + soft visualization-design
   constraints in Answer Set Programming, with learned weights for ranking. This is prior
   art for **both** the deterministic rail's decision logic **and** the lint gate (§7.3).
   Look at it before hand-rolling lint heuristics. **Missed-Flint-class find.**
2. **chat2plot** — the closest existing precedent to chartagent' central bet: LLM emits a
   **validated JSON/pydantic spec, not code**, then a renderer draws it. Validates the
   ChartSpec approach and shows its failure modes. Small, MIT, Python.
3. **LIDA (Microsoft)** — the closest precedent to the *whole agentic pipeline*
   (summarize → goal → generate → self-eval repair). But it's grammar-agnostic **code
   generation** — precisely the "fragile home-grown LLM chart generator" the PRD §1
   positions against. Know it cold; it's the skeptic's comparison.
4. **Data Formulator (Microsoft)** — concept-driven authoring that separates *what to see*
   from *how to transform* — the same split as ChartSpec's D2 (transform vs encodings). Its
   "data threads" is prior art for patch-mode conversational edits (§7.7). It's the product
   Flint renders for.
5. **Vizro-AI → Vizro-MCP (McKinsey)** — the closest funded *product* competitor, and a
   strategic signal: they **deprecated AI dashboard generation** and retreated to chart-only
   + an MCP server. A well-resourced team narrowing scope is a data point for chartagent'
   own scope discipline.

Bottom line: **none of these occupy chartagent' actual position** (embeddable Python API +
data-stays-in-infra profiling + deterministic-rail-first + review gate + zero-LLM refresh,
all as one product). But several own *pieces* of it well enough to steal from or to be
measured against. The USP holds; the surrounding art is richer than the PRD currently cites.

---

## Category 1 — Spec-mediated / intermediate-language charting (the "Flint layer")

The layer between "LLM intent" and "native chart." chartagent lives here via ChartSpec.

| Library | What it is | Lang / License | Relation to chartagent |
| --- | --- | --- | --- |
| **Flint** (Microsoft) | Semantic intermediate language + multi-backend compiler | TS (+ py preview) / MIT | Covered in `flint-chart-leverage.md`. The under-the-rail renderer + semantic ontology. |
| **chat2plot** (nyanp) | LLM → **JSON plot spec** (not code) → Plotly/Altair; accepts custom **pydantic** config | Python / MIT | **Closest precedent to the ChartSpec bet.** See below. |
| **GPT-Vis** (AntV) | "LLM chart protocol": 26 chart types, markdown-like syntax LLMs emit, streaming render, fault tolerance, MCP server | TS / MIT | JS-side analog of Flint + a chart vocabulary for LLM output. Relevant to streaming (P3) + output contract. |
| **Vega-Lite / Altair** | The grammar of graphics itself | JS / Python, BSD | The substrate everything above compiles to; ChartSpec is a higher-level dialect of it. |

**chat2plot — study this closely.** Its architecture *is* the deterministic-rail thesis in
miniature: "LLM does not generate Python code, but generates plot specifications in JSON …
transformed into actual charts using plotly or altair," and it "can accept custom chart
configurations using Pydantic BaseModel." That's ChartSpec-mediated rendering, already
shipped and validated in the wild. **What to do:** read its spec schema and, more usefully,
its *failure taxonomy* — where the LLM produces valid-but-wrong specs is exactly what the
ChartSpec grammar validators (issue #3) and the phase-2 profile validation must catch. It's
a free source of adversarial cases for the §11 benchmark.

**GPT-Vis — the JS-side competitor for "give the LLM a chart vocabulary."** Its selling
points (markdown-like syntax the model emits with high accuracy; graceful handling of
malformed/incomplete data; streaming) map onto chartagent' P3 streaming-events and the
"LLM emits less, library decides more" philosophy. It's web-component-first, so not a
Python competitor — but it's the reference for *fault-tolerant partial-spec rendering*, a
problem chartagent will hit on streaming.

---

## Category 2 — Formal viz-design knowledge bases (the rigorous "design knowledge in the library")

This is the category the PRD gestures at (pillar 3, the lint gate) but doesn't name.

**Draco / Draco 2 / DracoGPT (University of Washington).** Draco formalizes visualization
design guidelines as **constraints**: *hard* constraints prune ill-formed or non-expressive
encodings; *soft* constraints (with **learned weights**, originally RankSVM) rank the
remainder. It's implemented in Answer Set Programming (Clingo) and recommends over
Vega-Lite. Draco 2 is an extensible platform for modeling design knowledge; DracoGPT studies
extracting design *preferences* from LLMs and comparing them to Draco's.

Why this matters more than it looks:

- **chartagent' grammar validators ≈ Draco's hard constraints.** The `MARK_RULES` /
  channel-contract logic in `chartspec_draft.py` (which channels a mark requires/allows,
  type constraints) is a hand-rolled subset of what Draco encodes formally. Draco is prior
  art for *how far* that catalog can go and how to keep it declarative.
- **chartagent' lint gate (§7.3) ≈ Draco's soft constraints + weights.** The bar-baseline
  rule (`zero`), cardinality caps, colorblind-safety — these are soft-constraint territory.
  Draco already has a catalog of them, learnable and testable.
- **Underspecified instructions → recommendation.** When the user says "chart this" without
  saying *how*, the deterministic rail needs to *choose* an encoding. Draco is literally a
  recommender for that choice. chartagent could seed the planner or a fallback recommender
  from Draco's constraint set rather than relying on the LLM alone.

**What to do:** an ADR-level look before writing lint rules by hand. Even if chartagent
doesn't embed Clingo (ASP is a heavy runtime dep for an embeddable library), the
*constraint catalog* and the hard/soft split are directly adaptable, and DracoGPT is
relevant to the "does the LLM already know good design?" question underlying the ~80%
deterministic-rail hypothesis (§11, Phase 0).

---

## Category 3 — End-to-end agentic viz pipelines (closest to the whole chartagent flow)

| System | Shape | Note |
| --- | --- | --- |
| **LIDA** (Microsoft) | Summarizer → Goal Explorer → VisGenerator (generate/refine/execute/filter **code**) → Infographer; self-eval + repair | Grammar-agnostic **code gen**. The well-executed version of the "home-grown LLM chart generator" PRD §1 positions against. |
| **Data Formulator** (Microsoft) | Concept-driven UI: separate *what to see* from *how to transform*; "data threads" for iteration; ~30 chart library | Mirrors D2 (transform vs encoding) and patch-mode edits. The product Flint renders for. |
| **nvAgent** (research) | Processor → Composer (VQL via sketch-and-fill) → Validator (execution-guided repair) | Agent workflow over a **Visualization Query Language** intermediate. |
| **V-RECS** (2026, research) | Processor → Composer (NL→VQL) → Validator (VQL→Python, checks errors); adds explanations/captions/suggestions | Same 3-agent shape; VQL-mediated, not code-mediated. |

**LIDA is the one to internalize.** It has a Python API, multi-provider LLM support, and —
critically — a **self-evaluation feedback + repair loop**, which is prior art for
chartagent' review gate (lint + VLM critique). The key *difference* to articulate: LIDA
generates library code and filters it; chartagent runs a **deterministic rail first** and
only escapes to generated code for the minority. That difference is the entire reliability
pillar — and a reviewer *will* ask "how is this not just LIDA?", so the answer needs to be
crisp in the PRD (it currently isn't named there at all).

**Data Formulator validates two chartagent decisions.** Its explicit separation of "what
you want to see" from "how to transform the data" is the same boundary as ChartSpec's D2
(aggregation lives in the transform, not on the channel). And "data threads" — iterating on
prior chart state — is the UX precedent for chartagent' token-cheap **patch-mode edits**
(§7.7). Good news: two of chartagent' more contested design choices have an independent
Microsoft product converging on them.

**nvAgent / V-RECS** are research, not dependencies, but they confirm a pattern chartagent
should note: the field is standardizing on a **compose-to-an-intermediate-language →
validate/repair** loop (VQL for them, ChartSpec for chartagent). The intermediate-language
bet is now the consensus architecture, not a risk.

---

## Category 4 — AI-charting products / frameworks (the competitive set)

| Product | What it is | Signal for chartagent |
| --- | --- | --- |
| **Vizro-AI → Vizro-MCP** (McKinsey) | Low-code viz/dashboard toolkit; AI layer built on Pydantic-AI. **Dashboard generation deprecated**, superseded by **Vizro-MCP**; chart-gen only since 0.4.0 | The closest funded competitor **narrowed its scope** and went MCP-first. Two strategic reads below. |
| **PyGWalker / Graphic Walker** (Kanaries) | Turns a dataframe into a Tableau-like drag-drop UI in notebooks; NL queries | Exploration-analyst tool — chartagent' explicit **non-goal** persona. Not a competitor; a boundary marker. |
| **PandasAI** | Conversational dataframe analysis incl. plotting | Chat-over-dataframe; generates plotting code. Same "home-grown generator" class as LIDA. |

**Two strategic reads on Vizro's retreat:**

1. **Scope discipline is validated.** A well-resourced team found full AI *dashboard*
   generation not worth sustaining and fell back to chart-gen + MCP. chartagent' PRD scoping
   (charts, not dashboards; deterministic rail carrying the majority) looks prudent, not
   timid.
2. **The MCP-first vs API-first fork is now a live positioning question.** Vizro, Flint, and
   GPT-Vis all ship **MCP servers** as their primary agent surface. chartagent is
   deliberately **embeddable-API-first** and lists the chat/MCP analyst as a non-goal. That's
   a defensible, differentiated choice — but the PRD should now *argue* it explicitly, because
   the rest of the field went the other way. (An MCP server could still be a thin P2 wrapper
   over the API for the agent-composition persona P3, without becoming the primary surface.)

---

## Category 5 — BI-as-code / "generate once, refresh forever" analogs

chartagent' pillar 6 (a chart is a saved spec; refresh at $0 inference) is, structurally,
**BI-as-code applied to agent-generated charts**. Worth knowing the incumbents of that idea:

- **Evidence.dev** — dashboards as Markdown + SQL; **pre-caches data** to keep refresh cheap
  at high traffic. This is the human-authored twin of chartagent' zero-LLM refresh.
- **Rill** — metrics as YAML; explicitly pitches **"BI-as-code" + "GenBI"** (LLMs generate
  the SQL/YAML spec because they're trained on code). Closest to chartagent' "LLM authors a
  durable, versionable spec once" model.
- **Malloy** — a modeling/semantic language for data + lightweight viz.

**The positioning takeaway:** these prove the market believes in *durable, versionable,
cheap-to-refresh specs* — chartagent' pillar 6 is not a novel gamble, it's a validated
pattern. The chartagent delta to state plainly: BI-as-code specs are **human-authored**;
chartagent' specs are **agent-authored from NL + profiled data and quality-gated**, then
inherit the same refresh durability. "Rill for the spec you write; chartagent for the spec
the agent writes for you." This is a stronger pillar-6 framing than the PRD currently uses.

---

## Category 6 — Evaluation methodology (feeds §11 benchmark)

The PRD's v0.3 changelog already worries about LLM-judge self-preference. The field has
named metrics chartagent should adopt rather than reinvent:

- **Spec Score** — similarity between generated spec and a reference spec. **Judge-free**,
  deterministic — a direct antidote to the self-preference concern, and cheap to compute
  against ChartSpec (spec-diffing already exists for patch mode).
- **Vision Score** — a multimodal LLM compares the rendered *image* to a reference. This is
  chartagent' VLM-critique gate repurposed as an eval metric.
- **Chart-QA-style evaluation** — ask questions about the chart and check answers; scalable
  evaluation of whether a chart is *readable*, not just well-formed.
- **DracoGPT** — a principled way to check whether an LLM's design preferences match a
  formal knowledge base; relevant to validating the ~80% deterministic hypothesis.

**What to do:** fold **Spec Score** (judge-free) + **Vision Score** (VLM) into the §11
benchmark as a named, defensible pair, and cite Chart-QA for the readability dimension. This
hardens the benchmark against exactly the self-preference critique the PRD flags.

---

## What this changes before dev locks in

Concrete, in priority order:

| # | Action | Why now (hard-to-change-later) |
| --- | --- | --- |
| 1 | **Evaluate Draco's constraint model** before hand-authoring the lint gate + grammar validators. Decide: adopt the hard/soft catalog as prior art (likely), embed Clingo (likely not — dep weight), or borrow the taxonomy only. | Lint rules and grammar validators are foundational; retrofitting a principled constraint model later means rewriting the deterministic rail's core. |
| 2 | **Read chat2plot's spec + failure modes**; mine them as adversarial cases for ChartSpec validators and the benchmark. | Grammar shape (issue #3) is being frozen now; a free corpus of real failure cases should inform it before it sets. |
| 3 | **Name the LIDA / Data Formulator / Vizro/chat2plot set in PRD §2** (as the flint-leverage doc recommends for Flint). Add the crisp "not just LIDA" answer. | Positioning written after launch is defensive; written into the PRD it shapes the API. The "deterministic rail first vs code-gen" distinction is the whole pitch. |
| 4 | **Decide the MCP question explicitly**: API-first stays primary; is a thin MCP server a P2/P3 wrapper or out of scope? | Flint/Vizro/GPT-Vis all went MCP-first. Silence reads as an oversight; an explicit "API-first, MCP as optional wrapper" is a stance. |
| 5 | **Adopt Spec Score + Vision Score** as the named §11 metrics. | Benchmark design (≥150 cases, independent judge) is being specced now; naming judge-free + VLM metrics up front answers the self-preference risk structurally. |
| 6 | **Reframe pillar 6 against BI-as-code** (Evidence/Rill): "agent-authored, quality-gated, refresh-durable spec." | Cheap wording change now; strengthens the most defensible pillar. |

**Non-actions (deliberately):** don't add Draco's Clingo runtime as a hard dep (too heavy
for an embeddable lib — borrow the model, not the solver); don't pivot to MCP-first; don't
treat PyGWalker/Data Formulator as competitors (they serve the non-goal analyst persona).

### Suggested tickets

1. Spike: Draco constraint catalog → chartagent lint-rule mapping (hard vs soft; which
   translate; ASP-vs-Python decision).
2. Research: chat2plot spec grammar + failure taxonomy → adversarial cases for issue #3.
3. PRD edit: §2 adjacent-competitor expansion (Flint, LIDA, Data Formulator, Vizro,
   chat2plot, GPT-Vis) + the "not just LIDA" positioning paragraph.
4. Decision (ADR): MCP surface — API-first primary, MCP wrapper scope.
5. Benchmark design: adopt Spec Score + Vision Score + Chart-QA framing in §11.

---

## Sources

**Category 1:** [Flint](https://github.com/microsoft/flint-chart) ·
[chat2plot](https://github.com/nyanp/chat2plot) ·
[GPT-Vis (AntV)](https://github.com/antvis/GPT-Vis)
**Category 2:** [Draco (uwdata)](https://github.com/uwdata/draco) ·
[Draco: Formalizing Visualization Design Knowledge as Constraints (UW IDL)](https://idl.uw.edu/draco) ·
[Draco 2 (arXiv)](https://arxiv.org/pdf/2308.14247) ·
[DracoGPT (arXiv)](https://arxiv.org/pdf/2408.06845)
**Category 3:** [LIDA (Microsoft)](https://github.com/microsoft/lida) ·
[LIDA site](https://microsoft.github.io/lida/) ·
[Data Formulator (MSR blog)](https://www.microsoft.com/en-us/research/blog/data-formulator-a-concept-driven-ai-powered-approach-to-data-visualization/) ·
[nvAgent](https://github.com/geliang0114/nvagent) ·
[V-RECS (AVI 2026)](https://dl.acm.org/doi/10.1145/3811427.3811457)
**Category 4:** [Vizro / Vizro-AI (McKinsey)](https://github.com/mckinsey/vizro) ·
[vizro-ai (PyPI)](https://pypi.org/project/vizro-ai) ·
[PyGWalker (Kanaries)](https://github.com/Kanaries/pygwalker)
**Category 5:** [Evidence discovery writeup](https://opensourcedisc.substack.com/p/opensourcediscovery-89-evidence) ·
[Rill — BI-as-Code and the New Era of GenBI](https://www.rilldata.com/blog/bi-as-code-and-the-new-era-of-genbi)
**Category 6:** [DracoGPT (arXiv)](https://arxiv.org/pdf/2408.06845) ·
[Chart-QA for scalable LLM-viz evaluation (arXiv)](https://arxiv.org/pdf/2409.18764)
**Internal:** `chartagent-prd.md`; `prototypes/chartspec-v1/chartspec_draft.py`;
`docs/research/flint-chart-leverage.md`.
