# VLM candidates for the Tier-2 critique and the benchmark judge

- **Status:** Research notes for [issue #166](https://github.com/thearcscode/chartagent/issues/166). **Facts and trade-offs only — no model is chosen.** The choice is a later grilling.
- **Date:** 2026-09-15 (all prices and model lists are as fetched on this date)
- **Feeds:** P2 review gate (Tier-2 critique, ADR-0003) and the eval benchmark judge (PRD Goal 2, §10, §13, §14)
- **Branch:** `research/vlm-candidates` (throwaway, from `main`)

## The constraints being researched

1. Tier-2 critiques a PNG rasterised in a browser from the delivered backend (ADR-0003) and must return a **typed result**.
2. The benchmark judge must be a model **distinct from both the planner and the critique VLM** (PRD Goal 2, §13).
3. PRD §10 / Goal 3: **median cost per chart ≤ $0.05 at `quality="balanced"`**, provisional, "assuming a Sonnet-class planner and small critique model".
4. The planner today runs `anthropic:claude-sonnet-4-6` through pydantic-ai. `pyproject.toml` ships two model-vendor extras, `anthropic` and `openai`. For any other provider prefix, `plan/client.py::_extra_to_install` already points the user at `pydantic-ai-slim[<provider>]`. The installed `pydantic-ai-slim` 2.40.0 declares a `google` extra, so Gemini is reachable without new client code, but it is not a shipped chartagent extra.

## Summary of what was established

1. **All three vendors have current vision models with native structured output, spanning ~50× in price.** Cheapest listed: `gpt-5.6-luna` ($0.20 / $1.20 per MTok). Mid: Haiku 4.5, Gemini 3.8 Flash, `gpt-5.4-mini`. Sonnet-class: Sonnet 5 at $2 / $10, and Sonnet 4.6, the current planner, at $3 / $15.
2. **One critique call costs about $0.001–$0.025** at a ~1200×750 chart PNG, ~1.5k prompt tokens and ~400 output tokens (table in §4). The image itself is ~1.1k tokens on every vendor at that size, so **output and thinking tokens, not the image, dominate** the cost of a critique.
3. **The $0.05 budget is decided by the planner, not the VLM.** Planner token counts have never been measured: the 2026-09-14 retest records call counts only. An illustrative Sonnet 4.6 planner at 3k in / 800 out per call and 1.78 calls per chart already costs ~$0.037. That leaves ~$0.013 for critique and any revise loop.
4. **Published chart-understanding numbers exist, but vendor numbers are not comparable across vendors.** Each vendor uses a different harness, effort setting, split, and even grader model. Independent benchmarks show large gaps on realistic charts: ChartQAPro, a 35 pp drop from ChartQA. On *visualization quality judgement* specifically, the closest task to Tier-2 critique, VisJudge-Bench reports GPT-5 correlating only 0.428 with human experts.
5. **Self-preference extends to the model family, not just the exact model.** The ICLR 2026 preference-leakage paper finds judge bias toward same-model, inheritance-related and *same-family* generators. If that finding holds here, "distinct model" in PRD Goal 2 may need to mean "distinct family/vendor" for the judge.
6. **Lifecycle risks inside the window:** Claude Haiku 4.5's retirement is "not sooner than October 15, 2026" (one month out). Gemini 3.8 Flash's introductory price **doubles on 2027-01-01**. OpenAI's GPT-5.6 launch blog is 403 to automated fetch, and a search snippet of it quotes prices that do not match the live pricing page (see §1.2).
7. **No vendor publishes p50 latency.** Anthropic gives only a qualitative "comparative latency" column. OpenAI and Google give none on the pages fetched. Latency must be measured in the benchmark harness (PRD §10 already requires p50/p95).

---

## 1. Candidate vision models

### 1.1 Anthropic (shipped extra: `anthropic`)

Source: [Pricing](https://platform.claude.com/docs/en/about-claude/pricing), [Models overview](https://platform.claude.com/docs/en/models/overview), [Vision](https://platform.claude.com/docs/en/build-with-claude/vision).

| Model (API ID) | Input $/MTok | Output $/MTok | Batch in / out | Comparative latency (vendor) | Image tier | Retirement (not sooner than) |
|---|---|---|---|---|---|---|
| `claude-haiku-4-5` (`-20251001`) | 1 | 5 | 0.50 / 2.50 | Fastest | Standard | **2026-10-15** |
| `claude-sonnet-5` | 2 | 10 | 1 / 5 | Fast | High-res | 2027-06-30 |
| `claude-sonnet-4-6` (current planner; legacy) | 3 | 15 | 1.50 / 7.50 | — | Standard | — |
| `claude-opus-5` | 5 | 25 | 2.50 / 12.50 | Moderate | High-res | 2027-07-24 |
| `claude-fable-5-1` | 10 | 50 | 5 / 25 | Slower | High-res | 2027-09-01 |

- Sonnet 5's $2 / $10 was introductory. The pricing page now states it "is now the standard price. The previously scheduled increase to $3/$15 … will not occur."
- Claude 4.7 and later models use a newer tokenizer that "produces approximately 30% more tokens for the same text". Per-token prices are therefore not directly comparable with Sonnet 4.6 and Haiku 4.5.
- **Image limits:** 8000×8000 px max. 10 MB per image (base64) on the direct API, 5 MB on Bedrock and Google Cloud. 100 images per request for 200k-context models, 600 for others. A stricter per-image dimension limit applies above 20 images, and 32 MB is the standard request size cap. Formats: JPEG, PNG, GIF, WebP.
- **Image token cost:** `⌈width/28⌉ × ⌈height/28⌉` visual tokens. The standard tier caps at 1568 px long edge and 1568 tokens. The high-resolution tier ("Claude 4.7 and later models") caps at 2576 px and 4784 tokens, and "can use up to roughly three times more visual tokens". Vendor example: "at Claude Haiku 4.5's $1 … the 1000×1000 image costs about $1.30 USD per thousand images."
- Batch is 50% off; prompt-cache reads cost 0.1× input.

### 1.2 OpenAI (shipped extra: `openai`)

Source: [Pricing](https://developers.openai.com/api/docs/pricing), [Models](https://developers.openai.com/api/docs/models), [Images and vision](https://developers.openai.com/api/docs/guides/images-vision).

| Model | Input $/MTok | Cached in | Output $/MTok | Image tokens |
|---|---|---|---|---|
| `gpt-5.6-luna` | 0.20 | 0.02 | 1.20 | patches × 1.2 |
| `gpt-5.4-nano` | 0.20 | 0.02 | 1.25 | patches × 1.2 |
| `gpt-5.4-mini` | 0.75 | 0.075 | 4.50 | patches × 1.2 |
| `gpt-5-mini` | 0.25 | 0.025 | 2.00 | (multiplier not shown on page as fetched) |
| `gpt-5.6-terra` | 2.00 | 0.20 | 12.00 | patches × 1.2 |
| `gpt-5.6-sol` | 4.00 | 0.40 | 20.00 | patches × 1.2 |
| `gpt-6-astra` | 10.00 | 1.00 | 50.00 | patches × 1.2 |

- These are standard-tier, short-context prices. Long-context rows are higher: Luna $0.40 / $1.80, Terra $4 / $18, Sol $8 / $30. The page states batch and flex at 50% of standard for most models.
- The models page describes all four flagship-list models (Astra, Sol, Terra, Luna) as taking text and image input. Luna is "optimized for cost-sensitive workloads".
- **Price conflict, unresolved:** a search-engine snippet of the GPT-5.6 launch post (`openai.com/index/gpt-5-6/`, HTTP 403 to fetch) quotes Sol $5 / $30, Terra $2.50 / $15 and Luna $1 / $6. Those do not match the live pricing page above. This doc uses the pricing page; confirm by hand before a cost decision.
- **Image limits:** "Up to 512 MB total payload per request", "up to 1,500 images per request". Formats: PNG, JPEG, WEBP, non-animated GIF. `detail`: `low` | `high` | `original` | `auto` (default `auto`).
- **Image token cost (patch models):** `ceil(w/32) × ceil(h/32)` patches × a per-model multiplier (1.2 for the GPT-5.2 and later models listed above; 1.62 for `gpt-4.1-mini`). Requests over 30,000 patches after resize are rejected. Tile-based legacy models: `gpt-5` / `gpt-5.1` cost 70 base + 140 per 512 px tile, `gpt-4o` / `gpt-4.1` cost 85 + 170, and `gpt-4o-mini` costs 2833 + 5667 (prices it like `gpt-4o`).

### 1.3 Google Gemini (not a shipped extra; reachable via `pydantic-ai-slim[google]`)

Source: [Pricing](https://ai.google.dev/gemini-api/docs/pricing), [Models](https://ai.google.dev/gemini-api/docs/models), [Gemini 3.8 Flash](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash), [Image understanding](https://ai.google.dev/gemini-api/docs/image-understanding), [Media resolution](https://ai.google.dev/gemini-api/docs/media-resolution).

| Model | Input $/MTok (text/image) | Output $/MTok | Notes |
|---|---|---|---|
| `gemini-2.5-flash-lite` | 0.10 | 0.40 | Older generation |
| `gemini-3.1-flash-lite` | 0.25 | 1.50 | Stable |
| `gemini-3.5-flash-lite` | 0.30 | 2.50 | Stable; "high-volume, latency-sensitive tasks like … classification" (model card) |
| `gemini-3.8-flash` | **0.75 → 1.50 from 2027-01-01** | **3.75 → 7.50 from 2027-01-01** | Stable; thinking `low`/`medium`/`high` — "minimal thinking is not supported" |
| `gemini-3.1-pro-preview` | 2.00 (≤200k) | 12.00 (≤200k) | Preview |

- The pricing page lists a free tier, and batch and Flex at ~50% of standard.
- **Image limits:** up to 3,600 image files per request. Inline data is capped at a 20 MB total request. Formats: PNG, JPEG, WEBP, HEIC, HEIF.
- **Image token cost, Gemini 3:** fixed per image by `media_resolution`: `low` 280, `medium` 560, `high` 1120, `ultra_high` 2240. The default (unspecified) is 1120. Docs recommend `high` "for most image analysis tasks" and `medium` for documents ("quality typically saturates at `medium`"). Older models use 258 tokens if both dimensions are ≤384 px, else 768×768 tiles at 258 each.

### 1.4 Other vendors

Nothing else was surveyed in depth. pydantic-ai 2.40 also declares `bedrock`, `mistral`, `xai`, `groq`, `huggingface` and `openrouter` extras. Bedrock and Google Cloud (Vertex) re-host Claude with a 5 MB per-image cap and base64-only image sources (Anthropic Vision doc). Open-weight VLMs are out of scope for this ticket.

## 2. Published evidence

### 2.1 Chart understanding

| Benchmark | What it measures | Relevant published numbers |
|---|---|---|
| **CharXiv Reasoning** ([arXiv 2406.18521](https://arxiv.org/abs/2406.18521)) | Multi-step QA over 2,323 real arXiv charts | Sonnet 5 **77.0%** no tools / 88.3% with tools; Sonnet 4.6 71.6 / 85.3; Opus 4.8 80.5 / 89.9 (Sonnet 5 System Card §8.10.5). Gemini 3.8 Flash **86.2%** no tools ([model card](https://deepmind.google/models/model-cards/gemini-3-8-flash/)). Gemini 3.5 Flash-Lite **74.5%** no tools / 76.5% with tools ([model card](https://deepmind.google/models/model-cards/gemini-3-5-flash-lite/)). |
| **ChartMuseum** | Scientific chart reasoning | Sonnet 5 70.1% no tools / 86.7% with tools; Sonnet 4.6 59.3 / 80.9; Opus 4.8 75.8 / 89.7 (Sonnet 5 System Card §8.10.4) |
| **ChartQAPro** ([arXiv 2504.05506](https://arxiv.org/abs/2504.05506)) | 1,341 diverse real-world charts incl. dashboards/infographics | Claude 3.5 Sonnet: 90.5% on ChartQA vs **55.81%** on ChartQAPro — saturated benchmarks overstate real-chart competence |
| **ChartMimic** ([arXiv 2406.09961](https://arxiv.org/abs/2406.09961), ICLR 2025) | Chart→code from 4,800 curated triplets | GPT-4o 82.2 (Direct Mimic); already cited in PRD §14 |
| **VisJudge-Bench** ([arXiv 2510.22373](https://arxiv.org/abs/2510.22373), ICLR 2026) | **Aesthetics and quality assessment of visualizations** — the closest public task to Tier-2 critique; 3,090 expert-annotated samples, 32 chart types | "even the most advanced MLLMs (such as GPT-5) … MAE of 0.553 and a correlation with human ratings of only 0.428"; a fine-tuned VisJudge model reaches MAE 0.421 / correlation 0.687 |

**Comparability caveats (facts, from the sources):**

- Anthropic runs CharXiv at "adaptive thinking and max effort", averaged over five runs on 1,000 validation questions. It grades with **Claude Sonnet 4.6 instead of GPT-4o** as the reference grader. A critique call at low or no thinking will not see these numbers.
- Google's [Gemini 3.8 Flash evaluation methodology](https://storage.googleapis.com/deepmind-media/gemini/gemini_3-8_flash_model_evaluation.pdf) states "CharXiv Reasoning results for Gemini models, GPT-5.6 Terra and Sol, and Opus 5 are self computed". Its comparison table is published only as an image and is not transcribed here.
- No CharXiv number was found in a fetchable primary source for Haiku 4.5, `gpt-5.6-luna` or `gpt-5.4-mini`. The OpenAI launch pages returned HTTP 403.
- None of these benchmarks measures *critique of a chart against a spec and intent*. That is chartagent's actual Tier-2 task, and VisJudge-Bench is the nearest proxy. Model rank on Tier-2 has to come from our own benchmark.

### 2.2 LLM-judge self-preference

- **Panickssery, Bowman, Feng — "LLM Evaluators Recognize and Favor Their Own Generations"** ([arXiv 2404.13076](https://arxiv.org/abs/2404.13076), NeurIPS 2024; already PRD §14). LLMs "have non-trivial accuracy at distinguishing themselves from other LLMs and humans". Self-recognition is linked causally to self-preference.
- **Wataoka, Takahashi, Ri — "Self-Preference Bias in LLM-as-a-Judge"** ([arXiv 2410.21819](https://arxiv.org/abs/2410.21819), NeurIPS 2024 SafeGenAI workshop). LLMs "assign significantly higher evaluations to outputs with lower perplexity than human evaluators, regardless of whether the outputs were self-generated". The bias tracks *familiarity*, not authorship alone.
- **Li et al. — "Preference Leakage: A Contamination Problem in LLM-as-a-judge"** ([arXiv 2502.01534](https://arxiv.org/abs/2502.01534), ICLR 2026). The paper confirms "the bias of judges towards their related student models". It names three relatedness types: **same model, inheritance relationship, and same model family**.

**Implications for the judge constraint:**
- Taken together, these suggest that a judge from the same vendor family as the planner or critique model is exposed to the bias PRD Goal 2 is guarding against. Example: a Claude Haiku critique scored by a Claude Opus judge.
- The PRD's ≥ 20% human double-scoring is the calibration backstop either way.
- The planner is Anthropic, and the two shipped extras are Anthropic and OpenAI. A three-way family separation (planner, critique VLM, judge) therefore needs either a third vendor, for example Google via `pydantic-ai-slim[google]`, or the critique and planner sharing a family.

## 3. Structured output with image input, per vendor

| Vendor | Native structured output | Image + schema in the same request | Schema limits (documented) |
|---|---|---|---|
| Anthropic | **GA** — `output_config.format`; the old beta header "no longer required" ([docs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)). Listed models include `claude-haiku-4-5-20251001`, `claude-sonnet-4-6`, `claude-sonnet-5`, `claude-opus-5` and the Fable models. | Docs list "Extract data from images or text" as a use case | No recursive schemas, no external `$ref`, no numeric (`minimum`/`maximum`) or string length constraints; array `minItems` only 0 or 1; `additionalProperties` must be `false` |
| OpenAI | Structured Outputs (`json_schema`, strict), "starting with GPT-4o"; Responses API `text.format` | Not addressed on the structured-outputs page as fetched; image input and structured output are separately documented for the same models | "some features are unavailable"; examples consistently use `additionalProperties: false` with every property in `required` (full list not captured in this fetch) |
| Google | Structured outputs "Yes" for every listed Gemini 2.5/3.x text model ([models](https://ai.google.dev/gemini-api/docs/models)) | Not addressed on the structured-output page as fetched | "Not all JSON Schema features are supported"; "very large or deeply nested schemas may be rejected"; combining schema output with tools is Gemini 3-only |

**pydantic-ai (the client chartagent already uses):**
- Images go in as `BinaryContent` / `BinaryImage` or `ImageUrl` message parts (`pydantic_ai/messages.py`).
- A typed result can come from the default tool-call output, or from `NativeOutput` for vendor-native schema mode (`pydantic_ai/output.py`).
- Native JSON-schema support per profile: Anthropic's profile hard-codes a prefix list that includes `claude-haiku-4-5`, `claude-sonnet-4-6`, `claude-sonnet-5` and `claude-opus-5`. Google's profile enables it for Gemini 3+ (`profiles/google.py`). OpenAI's Responses profile enables it (`profiles/openai.py`).
- **Code fact:** `ModelClient.run(output_type, system_prompt, user_turn: str)` accepts only a string user turn today. A Tier-2 call through the same client would need that seam widened to carry an image part.

## 4. What a VLM pass implies for ≤ $0.05 median per chart at `balanced`

### 4.1 What is measured and what is not

- **Measured:** planner *calls* per chart. The no-retry floor is 2.0 on a rail hit, 1.0 on a miss, and 1.78 weighted at the 2026-09-14 retest's rail share (`docs/research/rail-share-retest-2026-09-14-report.md`, "Call cost (floor, not a live measurement)").
- **Not measured:** planner token counts, critique prompt size, critique rounds at `balanced`, thinking-token usage. PRD Goal 3 itself says the target is "finalized from measured token counts in Phase 2". **Every dollar figure below is an illustrative model, not a measurement.**
- ADR-0003 does not fix a raster size or device pixel ratio, so image token cost is shown at three sizes.

### 4.2 Image tokens per chart PNG (from the vendor formulas in §1)

| PNG size | Claude standard tier (Haiku 4.5, Sonnet 4.6) | Claude high-res tier (Sonnet 5, Opus 5) | OpenAI patch × 1.2 | Gemini 3 (`medium` / default `high`) |
|---|---|---|---|---|
| 800×500 | 522 | 522 | 480 | 560 / 1120 |
| 1200×750 | 1161 | 1161 | 1094 | 560 / 1120 |
| 1600×1000 (800×500 @2×) | ≈1568 (downscaled to cap) | 2088 | 1920 | 560 / 1120 |

At chart sizes the image is roughly 500–2,000 tokens on every vendor, the same order as a short text prompt.

### 4.3 One critique call, illustrative

Assumptions: 1200×750 PNG, 1,500 text input tokens (rubric plus spec summary), 400 output tokens (typed result), **no thinking tokens**, standard (non-batch) pricing.

| Critique model | Input tokens | Cost / call |
|---|---|---|
| `gpt-5.6-luna` | 2,594 | **≈ $0.0010** |
| `gemini-3.5-flash-lite` (default `high`) | 2,620 | ≈ $0.0018 |
| `gemini-3.8-flash` (default `high`) | 2,620 | ≈ $0.0035 now; ≈ $0.0069 from 2027-01-01 |
| `gpt-5.4-mini` | 2,594 | ≈ $0.0037 |
| `claude-haiku-4-5` | 2,661 | ≈ $0.0047 |
| `claude-sonnet-5` | 2,661 | ≈ $0.0093 |
| `gpt-5.6-terra` | 2,594 | ≈ $0.0100 |
| `claude-sonnet-4-6` | 2,661 | ≈ $0.0140 |
| `claude-opus-5` | 2,661 | ≈ $0.0233 |

**Sensitivities:**
- Output tokens cost 5–6× input on every vendor. 1,000 thinking tokens billed as output add $0.001 (Luna) to $0.025 (Opus 5) per call.
- Gemini 3.8 Flash has no "minimal" thinking level, so some thinking spend is unavoidable there.
- Anthropic's CharXiv numbers are reported at *max effort*. The cheap no-thinking rows above do not inherit them.
- Claude 4.7+ tokenizers inflate text counts by ~30% versus the counts assumed here.
- Batch pricing (50% off) is available for the **benchmark judge**, which is offline. It is not usable for the in-loop critique.

### 4.4 Budget arithmetic

Per chart: `planner_calls × planner_cost_per_call + critique_rounds × (critique_call + revise_planner_call_if_any)`.

- **Illustrative planner cost** (Sonnet 4.6, $3 / $15, 3,000 in / 800 out per call): $0.021 per call × 1.78 calls ≈ **$0.037**. Headroom under $0.05 is ≈ **$0.013**.
  - The step prompts' system text alone is ~3 kB (≈750 tokens: `plan/prompts/step1.system.md` 2,391 B, `step2.system.md` 636 B). The rendered user turn (profile, menu) is the unmeasured bulk.
- **One critique round, no revise:** any model up to the Sonnet 4.6 row (≈ $0.014) roughly fits at this illustrative planner size. Opus-class does not.
- **One critique round plus one revise:** a revise re-runs at least one planner call (≈ $0.021). That alone exceeds the headroom, **regardless of which critique VLM is chosen**. Only a critique that passes on the first round keeps a `balanced` chart under $0.05 at this planner size.
- **Planner model switch, fact only:** Sonnet 5 is $2 / $10, a third below Sonnet 4.6 per token, but its tokenizer yields ~30% more tokens for the same text. The net effect has to be measured.
- **Median vs mean:** the target is a *median*. If most charts pass Tier-1 and Tier-2 on the first round, revise costs sit in the tail and do not move the median. The median is then planner + one critique.
- **The judge is outside this budget.** The benchmark judge runs in CI, not per user chart, so its cost does not count against the $0.05 target. Batch pricing applies to it.

## 5. Trade-offs to carry into the grilling (no recommendation)

- **Cheapest critique vs published chart evidence.** `gpt-5.6-luna` is ~5× cheaper than Haiku 4.5, but no primary-source chart benchmark was found for Luna or Haiku 4.5. Gemini 3.5 Flash-Lite (74.5% CharXiv, $0.30 / $2.50) and Gemini 3.8 Flash (86.2%) have published CharXiv numbers but need a new vendor extra.
- **Critique vendor vs judge independence.** Critique, planner and judge from three different families avoids the preference-leakage relatedness the ICLR 2026 paper documents. That requires a third vendor. With only the two shipped extras, some pair shares a family.
- **Lifecycle.** Haiku 4.5 may retire from 2026-10-15. Gemini 3.8 Flash doubles in price on 2027-01-01. The GPT-5.6 price conflict in §1.2 is unresolved.
- **Image resolution.** Claude's high-res tier and Gemini's `high`/`ultra_high` spend more tokens for legibility of small chart text. Google's own guidance says documents saturate at `medium`. The raster size is not yet fixed by ADR-0003.
- **Proxy validity.** CharXiv, ChartQAPro and ChartMuseum measure chart *reading*. VisJudge-Bench measures quality *judgement*, where GPT-5 reaches only 0.428 correlation with experts. Neither measures spec-vs-render critique. The ≥ 150-case benchmark and human double-scoring are the only evidence that will rank candidates on chartagent's task.

## Sources

- Anthropic: [Pricing](https://platform.claude.com/docs/en/about-claude/pricing) · [Models overview](https://platform.claude.com/docs/en/models/overview) · [Vision](https://platform.claude.com/docs/en/build-with-claude/vision) · [Structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs) · [Claude Sonnet 5 System Card (PDF)](https://www-cdn.anthropic.com/283ef97c476cf442c91d9a37d5b214242a55bb92/Claude%20Sonnet%205%20System%20Card.pdf), §8.10.4–8.10.5
- OpenAI: [Pricing](https://developers.openai.com/api/docs/pricing) · [Models](https://developers.openai.com/api/docs/models) · [Images and vision](https://developers.openai.com/api/docs/guides/images-vision) · [Structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs) · GPT-5.6 launch post `openai.com/index/gpt-5-6/` (HTTP 403 to automated fetch; not relied on)
- Google: [Pricing](https://ai.google.dev/gemini-api/docs/pricing) · [Models](https://ai.google.dev/gemini-api/docs/models) · [Gemini 3.8 Flash](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash) · [Image understanding](https://ai.google.dev/gemini-api/docs/image-understanding) · [Media resolution](https://ai.google.dev/gemini-api/docs/media-resolution) · [Structured output](https://ai.google.dev/gemini-api/docs/structured-output) · [Gemini 3.8 Flash model card](https://deepmind.google/models/model-cards/gemini-3-8-flash/) · [Gemini 3.8 Flash evaluation methodology (PDF)](https://storage.googleapis.com/deepmind-media/gemini/gemini_3-8_flash_model_evaluation.pdf) · [Gemini 3.5 Flash-Lite model card](https://deepmind.google/models/model-cards/gemini-3-5-flash-lite/) · [Gemini 3.8 Flash launch blog](https://blog.google/innovation-and-ai/models-and-research/gemini-models/3-8-flash-and-3-8-flash-cyber/)
- Papers: [CharXiv, arXiv 2406.18521](https://arxiv.org/abs/2406.18521) · [ChartQAPro, arXiv 2504.05506](https://arxiv.org/abs/2504.05506) · [ChartMimic, arXiv 2406.09961](https://arxiv.org/abs/2406.09961) · [VisJudge-Bench, arXiv 2510.22373](https://arxiv.org/abs/2510.22373) · [Panickssery et al., arXiv 2404.13076](https://arxiv.org/abs/2404.13076) · [Wataoka et al., arXiv 2410.21819](https://arxiv.org/abs/2410.21819) · [Li et al., Preference Leakage, arXiv 2502.01534](https://arxiv.org/abs/2502.01534)
- Repo: `pyproject.toml` (extras) · `src/chartagent/plan/client.py` (`_extra_to_install`, `ModelClient.run`) · `.venv/.../pydantic_ai/profiles/{anthropic,google,openai}.py` and `output.py`, `messages.py` (pydantic-ai-slim 2.40.0) · `docs/research/rail-share-retest-2026-09-14-report.md` · `chartagent-prd.md` §5, §10, §13, §14
