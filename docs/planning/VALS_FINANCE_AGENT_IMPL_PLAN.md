# Vals AI Finance Agent — Implementation Plan

**Created:** 2026-04-20
**Revised:** 2026-04-20 (r2) — expanded Config A per `docs/research/hank-capabilities-inventory.md`.
**Revised:** 2026-04-20 (r3) — first Codex-review round; introduced three-adapter split, softened triggers, narrowed tool list.
**Revised:** 2026-04-20 (r4) — second Codex-review round. Four new blockers fixed: (1) FMP tools are in `fmp.server`, NOT registry — added 4th adapter source; (2) modeling studio **DEFERRED from v1** pending `ModelBuildContext` implementation (22.5-day engineering plan, in-flight on another track) — v1 benchmark uses `hank_code_execution` for financial_modeling questions instead; (3) code-execution uses `build_code_execution` factory, not `execute_code`; (4) tool specs fixed against actual source (e.g., `analyze_stock` is a risk/factor tool, NOT profile/fundamentals — replaced with `fmp_profile` + `get_stock_fundamentals` for the profile role).
**Revised:** 2026-04-20 (r5) — cleanup passes addressing Codex residual findings. `hank_compare_peers` `peers` typed correctly (`string`, comma-separated, not array). Duplicate model-adapter construction block deleted. Q3/Q8 resolutions updated. Stale "22-25 tools", "~30 tools", "one-week sprint" framing scrubbed. Week-1 day-by-day checklist aligned with r4 v1 scope (20 Hank + 5 native = 25 tool classes, modeling deferred). Tool-name drift fixed (`get_quote` real registry name, not `get_quotes`). Attribution text no longer claims modeling studio in v1.
**Status:** ✅ **CODEX PASS (r5, 2026-04-20)** — ready for implementation per CLAUDE.md plan-first workflow
**Supersedes / implements:** `docs/planning/VALS_FINANCE_AGENT_RUN_PLAN.md` (sprint envelope)
**Owner:** Benchmarks sprint (1-2 engineers, 8-week arc per §7 — Week 1 sprint + Weeks 2-8 architectural iteration + Week 8 decision gate)
**Upstream:**
- Sprint shape: `docs/planning/VALS_FINANCE_AGENT_RUN_PLAN.md`
- Landscape: `docs/research/fintool/agent-benchmarks-landscape.md`
- **Hank capability inventory (drives r2 revision):** `docs/research/hank-capabilities-inventory.md`
- Beta gap audit: `docs/planning/BETA_RELEASE_GAP_AUDIT.md` (T1.1, T2.1 are 🟦 Platform; this work is 🟦 Platform too — benchmark harness is audience-agnostic)

**r2 changes summary (HISTORICAL — all superseded by r3/r4/r5 below; do not implement from r2 descriptions):**
- §3.2.3 Tool selection expanded from 6 to ~25 (r4 revised: 25 tool classes with modeling deferred).
- §3.2.4 Tool wrappers shifted to registry pattern (r3 corrected: registry only covers risk_module; r4 added FMP direct-import adapter).
- §3.2.8 Modeling studio integrated (r4 DEFERRED v1 pending MBC — use code_execution instead).
- §3.2.9 Code execution added (r4 corrected: local subprocess default via `build_code_execution` factory).

**r3 changes summary (in response to Codex r2 review — FAIL-with-specific-fixes):**

Codex verdict: strategy is sound; implementation spec diverged from code in 3 core places. r3 fixes:

1. **Wrapper architecture (§3.2.4):** the plan used `get_registered_function` which doesn't exist; correct API is `get_registry()` returning `dict[str, AgentFunction]`. `_unwrap()` is a one-level `__wrapped__` peel, not a full unwrap. Registry covers `risk_module` tools only — NOT `Edgar_updater`, `fmp-mcp`, or `model-engine`. **r3: split tool adapters by source** — registry-backed for risk_module only, direct-import shims for Edgar / FMP / model-engine with explicit arg sanitation using `BLOCKED_PARAMS` pattern.
2. **Modeling studio integration (§3.2.8):** `build_model()` requires `company_name`, `fiscal_year_end`, `most_recent_fy`; `BuildResult` is a **dataclass** (not Pydantic); MCP wrapper requires `output_path` + returns **build stats**, not valuation outputs like WACC or terminal value. **r3: wrap `AI-excel-addin/api/research/build_model_orchestrator.py`** which derives company metadata + fetches FMP financials. Expose modeling as **two-step workflow**: `hank_model_build` → artifact; `hank_model_summarize`/`hank_model_find`/`hank_model_values`/`hank_model_scenario` → extract insights.
3. **Code execution default (§3.2.9):** hosted Anthropic beta is **"not wired"** per inventory; AI-excel-addin explicitly replaced hosted `code_execution_20260120` with local `code_execute`. **r3: local subprocess is the default.** Hosted beta deferred to later optional spike.
4. **Tool list pruned (§3.2.3):** dropped `get_factor_analysis` (not ticker-scoped — factor-intelligence surface), `analyze_option_chain` (requires live IBKR client); corrected `get_quote` signature (takes `tickers` plural, not single); removed `hank_fmp_fetch`, `model_clear_cache`, `annotate_model_with_research` from initial v1 surface (low-yield / admin). (r3 count was ~22-25; **r4 locks at 25 tool classes after dropping model-engine**.)
5. **Publish triggers softened (sprint plan §3.4):** re-framed from "pre-commits" to "goals/targets" — floor remains at 80% for delta-only publish.
6. **Config B fidelity (§5.2):** ±3pp softened from "halt" to "rerun signal." Brittle on n=50.
7. **Citation discipline (§4.2.3):** `HankSubmitFinalResult` changed from **hard-block** → **warn + accept** in v1 per Q8.
8. **Week 1 narrowed (§7):** Day 2 scope reduced; tool-description authoring + wrapper construction split across Days 2-3.
9. **§4.2.2 prompt rewritten** for ~22-25-tool set (was stuck on r1 6-tool version).
10. **Open questions Q3/Q12/Q13/Q15/Q16 resolved in plan body** per Codex; Q6/Q10/Q11/Q14 remain deferrable.
11. **§4.2.3 wrappers** now include `BLOCKED_PARAMS` handling + explicit parameter schemas (were forwarding `**args` raw).

> **⚠️ Read order for reviewers.** (1) Purpose § 1 to know what this plan produces. (2) Architecture § 3 for the five topics. (3) File-by-file § 4 for the concrete shape. (4) Open questions § 6 — that is where Codex attention is most needed. Flag anything in §§ 3–4 that needs to move to § 6.

---

## 1. Purpose

Produce a reproducible, defensible Hank score on the Vals AI Finance Agent v1.1 **public 50** benchmark, alongside an apples-to-apples raw-Opus 4.7 baseline on the same harness, with enough logging to support failure-mode analysis and a publish/hold decision.

**Concrete artifacts this plan produces when executed:**

1. `evals/vals-finance-agent/` — pinned clone of the Vals harness + Hank wrapper + Config B baseline + scripts to run both
2. `evals/vals-finance-agent/results/{timestamp}/` — per-run JSON: answers, traces, tool-call logs, scores
3. `docs/research/vals-finance-agent-result.md` — scored writeup with methodology + failure-mode breakdown + delta narrative
4. Decision memo (internal) — go/no-go per `VALS_FINANCE_AGENT_RUN_PLAN.md` §3.4 threshold tiers

**Non-goals:**

- Not modifying any Hank source code (`risk_module/` core). The wrapper is additive-only, in its own directory.
- Not running the 337-question private test (requires licensing).
- Not building a leaderboard submission pipeline — that is phase 4.
- Not score-hacking the wrapper. Per §3.6 iteration hygiene, Weeks 2-8 iterate architecturally (tool gaps, prompt structure, corpus backfill) — NOT score-targeted tweaks to specific test questions.

---

## 2. Prerequisites

### 2.1 Software

- Python 3.12 (harness `pyproject.toml` line 10: `requires-python = ">=3.12"`). Hank runs on 3.11 in most repos but the Vals harness venv is isolated — use 3.12 there.
- `uv` for Vals harness dependency management (`make install` wants it).
- Hank repo already cloned at `/Users/henrychien/Documents/Jupyter/risk_module/`.
- Git — we create a sibling checkout of `vals-ai/finance-agent` inside `evals/`.

### 2.2 API keys (all required)

| Key | Source | Purpose |
|---|---|---|
| `VALS_API_KEY` | `platform.vals.ai` (gated — registration may take days) | Scoring via Vals platform + loading test suite |
| `ANTHROPIC_API_KEY` | Anthropic console | Model calls (Opus 4.7) |
| `TAVILY_API_KEY` | `tavily.com` | Web search tool |
| `SEC_EDGAR_API_KEY` | `sec-api.io` | EDGAR full-text search (supports `;`-separated list for rotation) |
| `FMP_API_KEY` | FMP (for Hank wrapper only) | Hank's fundamentals tools |

**Day-0 action:** kick off Vals platform registration immediately (§5 of sprint plan — could take days). Do not block Day 1 on it; we can dry-run with local-only scoring stubs (see §4.5) and switch to real judge once access lands.

### 2.3 Test Suite ID

Per harness README: "add the 'Test Suite IDs' to `suites.json`. These should have generally been provided to you via email."

**This is an open question** — see § 6 Q1. The harness `README` implies you get an ID after approval; the current repo does **not** contain a `suites.json` file (verified via `ls /tmp/vals-research/finance-agent/` in research step). We may need to either:
- (a) Receive a suite ID from Vals and wire it in.
- (b) Create our own test suite from `data/public.csv` via `platform.vals.ai` web UI.
- (c) Run the harness CLI with `--question-file data/public.txt` (which does **not** score — only runs the agent). Scoring requires a suite ID + `suite.run()` path.

Until resolved, the default assumption in this plan is (a). If blocked, fallback to (b) — create a suite from the 50 public rows in `public.csv` (columns: `Question, Answer, Question Type, Expert time (mins), Rubric`) which already contains the rubric judges need.

### 2.4 Budget

Per sprint shape §5, original estimate was $50-150. Revised upward for r4/r5 (larger tool catalog, code execution):

| Item | Qty | Unit cost (est) | Subtotal |
|---|---|---|---|
| Opus 4.7 calls, Config A (Hank v1 curated) | ~50 q × ~30 turns × ~8K in / 1.5K out | $0.15 avg | $260 |
| Opus 4.7 calls, Config B (raw) | ~50 q × ~15 turns × ~5K in / 1K out | $0.06 avg | $50 |
| Tavily | ~50 q × ~8 searches × 2 configs | ~$0.01/search | $10 |
| SEC-API (sec-api.io) | ~50 q × ~15 searches × 2 configs | ~$0.01/search | $15 |
| FMP API (Hank tools) | covered by existing Hank quota | — | $0 |
| Code execution (local subprocess per r4) | ~20 q × 2 exec per q | local — no API cost | $0 |
| `model_build` invocations | DEFERRED per r4 §3.2.8 | — | $0 |
| Judge (GPT-5.2 via Vals hosted) | 50 × 3 (mode of 3) × 2 configs | ~$0.05 | $15 |
| **Total** | | | **~$350 upper bound** |

Actual will likely be lower (many questions won't max turns). Non-blocking.

---

## 3. Architecture — the five topics

### 3.1 Vals harness internals

The harness is small: 5 files, ~700 LOC total, plus the `model-library` dependency for the `Agent`/`LLM`/`Tool` base classes. This section documents what the harness actually does based on reading the source (`/tmp/vals-research/finance-agent/finance_agent/`).

#### 3.1.1 Dataset format

- **File:** `data/public.txt` (one question per line, 50 lines) and `data/public.csv` (5 columns: `Question`, `Answer`, `Question Type`, `Expert time (mins)`, `Rubric`).
- **Rubric column** is a JSON list of criteria objects, each with `operator` (`correctness` or `contradiction`) and `criteria` (text). Example from question 1 (US Steel): 8 correctness criteria + 1 contradiction criterion. The judge evaluates each independently and aggregates.
- **Question types** present in `public.csv`: matches the 9 categories in `VALS_FINANCE_AGENT_RUN_PLAN.md` §2 (Quantitative retrieval, Qualitative retrieval, Numerical reasoning, Complex retrieval, Adjustments, Beat-or-miss, Trends, Financial modeling, Market analysis).
- **Date anchor:** `prompt.py` line 5 hard-codes *"You should answer all questions as if the current date is April 07, 2025."* Tool responses also enforce `MAX_END_DATE = "2025-04-07"` (see `tools.py:16`).

#### 3.1.2 Scoring pipeline

- **Two distinct paths** exist in the harness:
  - **`finance-agent` CLI** (`run_agent.py:main`) — runs the agent but does NOT score. Writes `results.json` locally in `logs/…/results.json` (see `run_agent.py:53-61`). This is what the README's primary example uses.
  - **`get_custom_model`** (`custom_model.py:18`) — the Vals SDK integration entry point. When called by `suite.run(model=custom_call, ...)` the Vals platform iterates its test cases, calls our `custom_call` per question, receives an `OutputObject`, and performs scoring on its side.
- **Judge model:** per Vals docs (web-fetched), judge is configurable via `RunParameters(eval_model=...)`. The benchmark published baselines use **GPT-5.2** per `VALS_FINANCE_AGENT_RUN_PLAN.md` §2.6.
- **Mode of 3** = in Vals SDK terms, `heavyweight_factor=3` or `eval_models=[...]` jury pattern (docs line: *"repeated evaluations… or jury-based evaluation with 3-5 independent judges"*). Confirmed this is platform-side; we do not implement it locally.
- **Locality:** scoring is **remote** (hits Vals platform). This means our wrapper only has to produce the right output shape; judging is outside our harness.

#### 3.1.3 `get_custom_model` extension point (the only wiring point)

Reading `custom_model.py:18-49` verbatim:

```python
async def get_custom_model(
    model_name: str,
    parameters: dict[str, Any],
    *_args: object,
    **_kwargs: object,
):
    from vals.sdk.types import OutputObject  # pyright: ignore

    params = Parameters(model_name=model_name, llm_config=create_override_config(**parameters))
    llm = get_registry_model(model_name, params.llm_config)
    token_retry_params = parameters.get("token_retry_params", None)
    if token_retry_params:
        await llm.init_token_retry(token_retry_params=TokenRetryParams.model_validate(token_retry_params))

    async def custom_call(test_input: str, files: dict, context: dict, question_id: str, run_id: str):
        prompt = INSTRUCTIONS_PROMPT.format(question=test_input)
        agent = get_agent(params, llm=llm)
        result = await agent.run([TextInput(text=prompt)], question_id=question_id, run_id=run_id)
        if not result.success and result.final_error:
            print(f"\nFAIL {question_id} failed: ...")
        return OutputObject.from_agent_result(result, count_tool_metadata=True)

    return custom_call
```

**What we learn:**

- The Vals SDK calls `get_custom_model` once per run, gets back a `custom_call` async closure, then calls `custom_call(test_input, files, context, question_id, run_id)` per question.
- The closure is free to do whatever it wants as long as it returns an `OutputObject`.
- `OutputObject.from_agent_result(result, count_tool_metadata=True)` is a convenience constructor from the `model_library.agent.AgentResult` type. `AgentResult.final_answer` (string) is what the judge ends up scoring (see `model_library/agent/agent.py:56`).
- We can **fully replace** the `get_agent(...)`/`agent.run(...)` block with a Hank-specific implementation — as long as we return an `OutputObject`, the Vals SDK is happy.

#### 3.1.4 Tool wiring — how default tools are injected

- Tools are instantiated in `get_agent.py:33-51` as concrete `Tool` subclasses (see `tools.py`): `TavilyWebSearch`, `EDGARSearch`, `ParseHtmlPage`, `RetrieveInformation`, `SubmitFinalResult`.
- These are **not MCP tools**; they are Python classes inheriting from `model_library.agent.Tool` (source: `/tmp/vals-research/model-library/model_library/agent/tool.py`). Each has `name`, `description`, `parameters`, `required` attrs + an async `execute(args, state, logger) -> ToolOutput` method.
- They are passed into `Agent(... tools=selected_tools, ...)`; the `Agent` turns them into `ToolDefinition` schemas for the LLM (see `tool.py:82-98` `definition` property).
- **`submit_final_result` is the only way the agent returns an answer.** Reading `get_agent.py:63-87`: `_should_stop` returns False on text-only responses, so the loop only exits on `ToolOutput(done=True)` (which `SubmitFinalResult` alone produces) OR `max_turns=50` (emits `final_error = MaxTurnsExceeded`, `final_answer=""`). This means if we do not emit a submit call, we score 0.
- **The agent loop is harness-controlled** (answer to a key question): `Agent.run` in `model_library/agent/agent.py:316-499` owns the conversation loop. Our tools are called per-turn from inside that loop.

**Implication for Hank wrapper:** we have two options (see §3.2) — (1) conform to the harness loop, implementing Hank functionality as additional `Tool` subclasses; or (2) short-circuit the harness loop and drive our own loop from inside `custom_call`, returning a synthesized `AgentResult`. Plan chooses **Option 1** by default (see §3.2 for why, and §6 Q2 for risks).

#### 3.1.5 Environment + dependency wiring

- `uv sync --dev` installs everything into `.venv/`.
- `.env` is loaded by `run_agent.py:115-116` (via `dotenv.load_dotenv`).
- `suites.json` (not in repo) stores test suite IDs.
- Logs land in `logs/<agent_name>/<model_name>/<timestamp>_<id>/turns/turn_NNN/`. Agent run writes `init/`, then per-turn `result.json`, `state.json`, `history.bin`. This is **rich structured data we can use for failure analysis without building our own tracer**.

### 3.2 Hank-as-agent wrapper architecture

#### 3.2.1 Directory layout

Everything Hank-side lives under `evals/vals-finance-agent/` in the Hank repo (NOT in the cloned harness — isolation discipline):

```
risk_module/evals/vals-finance-agent/
├── README.md                       # How to run
├── .env.example                    # Required env vars (no secrets)
├── vendor/
│   └── finance-agent/              # Pinned clone of vals-ai/finance-agent @ commit SHA
│       └── (untouched upstream code)
├── configs/
│   ├── config_a_hank.py            # Hank wrapper configuration
│   ├── config_b_raw_opus.py        # Raw Opus 4.7 baseline (harness defaults only)
│   └── suites.json                 # Test suite IDs (gitignored if contains secrets)
├── harness/
│   ├── __init__.py
│   ├── hank_model.py               # Config A custom_call entry point
│   ├── hank_tools.py               # Hank-flavored Tool subclasses (wraps MCP tools)
│   ├── raw_opus_model.py           # Config B custom_call entry point (harness stock)
│   ├── trace_logger.py             # Per-question JSONL trace sidecar
│   └── scoring_stub.py             # Local dry-run judge for testing without Vals access
├── scripts/
│   ├── run_config_a.sh             # Launch full Config A run
│   ├── run_config_b.sh             # Launch full Config B run
│   ├── dry_run.sh                  # 3-question smoke test (both configs)
│   └── aggregate_results.py        # Slice scores by category / filing type
└── results/
    └── <timestamp>/
        ├── config_a/
        │   ├── run.json            # Vals-provided run result
        │   ├── traces.jsonl        # Per-question trace (one JSON per line)
        │   └── agent_logs/         # Symlink or copy of vendor/finance-agent/logs
        └── config_b/               # Same shape
```

**Why vendor the clone instead of git-submodule:** submodule pins us to the public repo state; we want a hard-pinned local copy we can checksum for reproducibility. The `vendor/` dir is gitignored except for a `VERSION` file that records the pinned commit SHA + upstream URL.

#### 3.2.2 Who drives the loop — harness or Hank?

**Decision: harness drives the loop.** We do NOT build a second loop inside `custom_call`.

Rationale:
- Harness loop already handles retries, context-window truncation, max-turns, error reporting, per-turn logging, and `AgentResult` construction. Rebuilding that is scope creep and a source of bugs.
- The Vals SDK expects `OutputObject.from_agent_result(AgentResult, ...)`. If we run our own loop we'd have to synthesize a fake `AgentResult`, re-implementing its contract (~150 fields, see `agent.py:38-146`).
- If Hank's MCP tools are exposed as harness `Tool` subclasses, the harness loop naturally interleaves them with `edgar_search`/`web_search`/`retrieve_information` — which is exactly the behavior we want to test.

**What "conforming to the harness loop" means in code:**

- `hank_model.py::get_custom_model` returns a closure shaped identically to `custom_model.py::get_custom_model` in the vendor.
- Inside `custom_call`, we call a Hank-specific `get_agent(...)` that uses the same `Agent` class from `model_library.agent` but passes in a **different tool set** (harness defaults + Hank wrappers).
- The system prompt we inject is **Hank's system prompt** (per `BRAND.md`), not `INSTRUCTIONS_PROMPT` — but we keep `INSTRUCTIONS_PROMPT`'s citation requirement appended. This is the critical behavioral delta between Config A and Config B.

#### 3.2.3 How Hank's MCP tools map to harness tools — REVISED r3

**r4/r5 framing:** test Hank's full production architecture, but via a **curated v1 core of 25 tool classes (20 Hank + 5 native)** — modeling studio deferred per r4 §3.2.8. r3 tried to include modeling; r4 removed pending MBC track.

**Rationale:**
- Hank's agent in production has access to many tools; broad filtering misrepresents capability.
- Config A tells a stronger commercial story than a stripped-down one.
- 25 is still 5× Config B's 5 tools — meaningful wrapper surface.
- Dropping broken/admin/low-yield tools reduces tool-selection confusion and schema bloat.
- Local evidence (AI-excel-addin's `lazy-load-mcps-task.md`) confirms that larger catalogs had real cost at production scale.
- Reserve capacity to ADD tools during 8-week iteration as failure analysis dictates, rather than starting saturated.

**Proposed Config A v1 tool list (r4/r5):** 25 tool classes total (20 Hank + 4 native + HankSubmit), split by source (registry applies only to risk_module; FMP is direct-import per §3.2.4.C).

##### A. Edgar-financials server (9 tools, all included) — the primary filing data path

**Source:** `Edgar_updater/mcp_server.py` (9 tools). Direct Python import (not via risk_module registry — Codex blocker #1). Wrappers import from `Edgar_updater` package directly.

| Hank MCP tool | Wrapper name | Why included |
|---|---|---|
| `get_filings` | `hank_get_filings` | Filing metadata (type, period, URL) — find the right filing |
| `get_financials` | `hank_get_financials` | Full structured XBRL extract (income / balance / cash flow) |
| `get_metric` | `hank_get_metric` | Specific XBRL fact with YoY comparison |
| `get_metric_series` | `hank_get_metric_series` | Multi-period metric time series — trends questions |
| `list_metrics` | `hank_list_metrics` | Discover available metrics for a filing period |
| `search_metrics` | `hank_search_metrics` | NL metric search — bridges user phrasing to XBRL tags |
| `get_filing_sections` | `hank_get_filing_sections` | Parsed narrative + tables (MD&A, Risk Factors, etc.) |
| `extract_filing_file` | `hank_extract_filing_file` | Custom-schema extraction for structured fact pulls |
| `list_extraction_schemas` | `hank_list_extraction_schemas` | Discover available extraction schemas |

##### B. FMP analytical tools (8 tools) — REVISED r4

**Source (r4 correction):** `risk_module/fmp/server.py` — NOT the agent registry. Registry only exposes 2 FMP-adjacent tools (`analyze_stock`, `get_quote`). The 8 analytical tools below are direct-import from `fmp.server` using the NEW r4 §3.2.4.C adapter.

**r4 swap:** `analyze_stock` was mischaracterized as profile/fundamentals — it's actually a risk/volatility/factor-exposure tool (`mcp_tools/stock.py:64`: *"Analyze a single stock or ETF for volatility, beta, and factor exposures"*). For the benchmark's profile-and-fundamentals role, use **`fmp_profile` + `get_stock_fundamentals`** instead. `analyze_stock` is marginally benchmark-relevant (some Vals questions involve beta/volatility) — keep it as a secondary tool via registry adapter.

| Function in `fmp.server` | Wrapper name | Why included |
|---|---|---|
| `fmp_profile(symbol)` | `hank_company_profile` | Company profile — industry, CEO, description, market cap, share count |
| `get_stock_fundamentals` | `hank_stock_fundamentals` | Fundamentals + valuation + quality signals — replaces mischaracterized `analyze_stock` for profile role |
| `get_earnings_transcript` | `hank_earnings_transcript` | Transcript parsing per-speaker — required evidence for qualitative questions |
| `compare_peers` | `hank_compare_peers` | Peer comparison for relative-value questions |
| `get_market_context` | `hank_market_context` | Market snapshot for macro context |
| `get_events_calendar` | `hank_events_calendar` | Earnings dates, splits, IPOs |
| `get_news` | `hank_get_news` | News flow for trend + catalyst questions |
| `get_sector_overview` | `hank_sector_overview` | Sector P/E / performance context |

**Deferred from v1:**
- `get_insider_trades`, `get_institutional_ownership` — low-yield for filing Q&A
- `get_technical_analysis` — rarely relevant per Codex
- `fmp_fetch` / `fmp_describe` / `fmp_list_endpoints` — escape hatch deferred
- `analyze_stock` (registry-backed) — add in iteration if volatility/beta questions surface as a gap

##### C. Model-engine tools — **DEFERRED from v1**

**r4 decision:** the orchestrator is `BuildModelOrchestrator.build_and_annotate(handoff_id, user_id)` — requires a finalized handoff + user context. The `ModelBuildContext` (MBC) work that would enable a cleaner ticker-only path is in-flight on another track (`docs/planning/MODEL_BUILD_CONTEXT_PLAN.md`, Codex PASS R8, ~22.5 working days of engineering ahead).

For v1 benchmark sprint, **financial_modeling questions route to `hank_code_execution` instead**. System prompt (§4.2.2) guides the agent to build DCFs / projections via Python in the sandbox for the baseline run.

**When to re-add:** after MBC ships, revise this section (§3.2.8) to wrap `build_model_from_mbc(mbc)`. Expected: weeks 4-6 of iteration if MBC track delivers, else v1.5 deliverable.

**The 4 model-engine tools planned in r3 are removed from v1 Config A.** See §3.2.8 for full context.

##### D. Registry-backed tools from risk_module (2 tools)

**Source:** `risk_module.agent.registry.get_registry()` (§3.2.4.A). Only 2 tools here — Codex confirmed the registry doesn't cover FMP tools.

| Hank MCP tool | Wrapper name | Why included |
|---|---|---|
| `get_quote` | `hank_get_quotes` | Multi-ticker quote. Takes `tickers: list[str]` (plural) per `mcp_tools/quote.py:21`. |
| `analyze_stock` | `hank_stock_risk_analysis` | Risk/volatility/factor-exposure analysis per real docstring. Secondary tool for the few Vals questions about beta/volatility. |

**r3 tools dropped per Codex blocker #4:**
- `get_factor_analysis` — factor-intelligence surface with basket lookup (`mcp_tools/factor_intelligence.py:607`), not ticker-scoped as claimed.
- `analyze_option_chain`, `analyze_option_strategy` — require live IBKR client + expiry-specific market plumbing (`mcp_tools/chain_analysis.py:313`).

##### E. Code execution (1 tool) — NEW r2, r3 defaults local

One tool: `hank_code_execution`. **r3 default: local subprocess** via AI-excel-addin's `agent_gateway/code_execution/` — same stack as production. **Hosted Anthropic beta (`code_execution_20260120`)**: deferred — was "not wired" per inventory + explicitly replaced by AI-excel-addin. See §3.2.9.

##### F. Harness-native tools retained (4) + submit (1)

| Tool | Retention rationale |
|---|---|
| `edgar_search` | Harness-native snippet search via sec-api.io — complements structured edgar-financials. Agent picks the right one. |
| `parse_html_page` | Generic HTML fetcher — useful for press releases, IR pages |
| `retrieve_information` | Keyword search over retrieved text |
| `web_search` (Tavily) | Web fallback for non-SEC sources |
| `HankSubmitFinalResult` | Overrides native submit; **warns (not blocks)** on missing citations per Codex + Q8 |

##### Total tool counts (r4)

| Config | Hank tools | Native | Total | Breakdown |
|---|---|---|---|---|
| **Config A (Hank v1 curated)** | **20** | 4 | **25** | 9 edgar-financials + 8 FMP analytical + 2 registry-backed (`get_quote`, `analyze_stock`) + 1 code-exec + 4 harness-native + HankSubmit |
| **Config B (raw Opus baseline)** | 0 | 4 | **5** | edgar_search + parse_html_page + retrieve_information + web_search + submit_final_result. Unchanged from vendor defaults. |

**r4 v1 lock: 20 Hank tools + 4 native + HankSubmit = 25 tool classes.** Model-engine tools deferred. Add model tools in Week 4-6 if MBC track delivers, else v1.5.

##### Explicit exclusion list (portfolio-state tools)

These require `user_email` + connected portfolio + transaction history and will hard-error or return empty in benchmark context. Excluded from Config A:

- `get_positions`, `list_accounts`, `get_portfolio_events_calendar`, `get_portfolio_news`
- `get_risk_analysis`, `get_risk_score`, `get_leverage_capacity`, `get_target_allocation`, `get_allocation_presets`
- `get_performance`, `get_trading_analysis`
- `run_whatif`, `run_optimization`, `run_monte_carlo`, `run_stress_test`, `run_backtest`, `get_efficient_frontier`, `run_stress_test`
- `get_income_projection`, `list_income_events`, `list_flow_events`
- `suggest_tax_loss_harvest`, `generate_rebalance_trades`
- `preview_trade`, `execute_trade`, `preview_option_trade`, `execute_option_trade`, `preview_basket_trade`, `execute_basket_trade`, `preview_futures_roll`, `execute_futures_roll`, `cancel_order`, `get_orders`
- `monitor_hedge_positions`, `check_exit_signals`
- `create_portfolio`, `update_portfolio_accounts`, `delete_portfolio`, `list_portfolios`, `import_portfolio`, `import_transaction_file`, `list_transactions`, `refresh_transactions`
- Brokerage management: `initiate_brokerage_connection`, `complete_brokerage_connection`, `list_connections`, `manage_brokerage_routing`, etc.
- Workflow/diligence: `activate_diligence`, `prepopulate_diligence`, `get_handoff`, `list_research_files`, etc. (all research workspace tools — designed for the interactive workspace, not Q&A)
- Baskets, ticker config, instrument config: `create_basket`, `manage_ticker_config`, `manage_instrument_config`, etc.

**Rationale for exclusion:** these tools are designed around user portfolio context. Without it, they either error out (`user_email=None` hits assertion/DB lookup) or return empty (`{positions: []}`). Either way they add noise, not signal. The agent would waste turns discovering they're useless.

**However,** see §6 Q14 — a legitimate alternative is to include them with "no portfolio context" safeguards (let them return empty gracefully) and trust the agent to not call them on filing Q&A. Worth Codex opinion.

##### Why 25 tool classes is OK for tool-selection

- Vals harness's `Agent` class handles arbitrary tool counts; no architectural limit.
- Claude Opus 4.7 is trained on large tool catalogs (Claude Code itself has ~15 tools; production MCP users routinely expose 20-50).
- Schema bloat bounded: 25 tools × ~200 tokens each ≈ 5K tokens. Fits inside prompt caching prefix.
- Tool-selection confusion risk mitigated by (a) naming convention (`hank_*` prefix segments Hank tools from natives), (b) system prompt category hints (§3.2.5), (c) good tool descriptions.

#### 3.2.4 Tool wrapper shape — REVISED r3

**Codex caught the critical bug:** `risk_module.agent.registry.get_registered_function` does not exist. The correct API is `get_registry()` returning `dict[str, AgentFunction]`. **Crucially, that registry covers `risk_module` tools only — NOT `Edgar_updater`, `fmp-mcp`, or `model-engine`.**

**r3 solution: three adapter sources.** We split wrapper construction by tool origin.

##### 3.2.4.A Registry-backed adapter (risk_module tools only)

For registry-backed tools (`get_quote` and `analyze_stock` per §3.2.3.D) — tools that live in `risk_module/mcp_tools/` and are registered in the agent allowlist.

**Actual registry API (verified against `risk_module/agent/registry.py:35-90`):**

```python
# Verified — these are the real exports.
from risk_module.agent.registry import get_registry, BLOCKED_PARAMS
from dataclasses import dataclass

# @dataclass(frozen=True)
# class AgentFunction:
#     callable: Callable       # already unwrapped (see _unwrap at line 70)
#     tier: Literal["tool", "building_block"]
#     read_only: bool
#     category: str
#     has_user_email: bool

registry = get_registry()              # dict[str, AgentFunction]
entry = registry["analyze_stock"]      # AgentFunction
fn = entry.callable                    # already unwrapped; raw callable
has_user_email = entry.has_user_email  # True for analyze_stock
```

**Adapter factory (registry-backed):**

```python
# evals/vals-finance-agent/harness/hank_tools_registry.py
import asyncio, json, inspect
from model_library.agent import Tool, ToolOutput
from risk_module.agent.registry import get_registry, BLOCKED_PARAMS

_registry = get_registry()

def _build_registry_adapter(
    registered_name: str,
    display_name: str,
    description: str,
    parameters: dict,
    required: list[str],
) -> type[Tool]:
    """Adapter for tools living in risk_module/mcp_tools/ and registered in the allowlist."""
    entry = _registry[registered_name]  # KeyError caught at module-load time = fail fast
    raw_fn = entry.callable

    # user_email handling: registry flags which tools expect it. For benchmark, pass None.
    # If the tool truly requires a DB-backed user (inventory §2.B flags some), wrapper fails.
    auto_user_email = {"user_email": None} if entry.has_user_email else {}

    class _HankTool(Tool):
        name = display_name
        __doc__ = description

    _HankTool.description = description
    _HankTool.parameters = parameters
    _HankTool.required = required

    async def execute(self, args, state, logger):
        try:
            # Merge args: caller args + user_email default + BLOCKED_PARAMS safe overrides.
            # BLOCKED_PARAMS (registry.py:35) = {"backfill_path": None, "output": "inline", "debug_inference": False}
            merged = {**args, **auto_user_email, **BLOCKED_PARAMS}
            # Only pass params the function actually accepts (avoid unexpected-kwarg errors).
            sig = inspect.signature(raw_fn)
            filtered = {k: v for k, v in merged.items() if k in sig.parameters}
            if inspect.iscoroutinefunction(raw_fn):
                result = await raw_fn(**filtered)
            else:
                result = await asyncio.to_thread(raw_fn, **filtered)
            return ToolOutput(output=json.dumps(result, default=str))
        except Exception as e:
            return ToolOutput(output=f"{type(e).__name__}: {e}", error=str(e))

    _HankTool.execute = execute
    _HankTool.__name__ = f"Hank_{registered_name}"
    return _HankTool
```

**Design notes:**
- Registry lookup at adapter construction time. KeyError if the tool isn't in the allowlist — fail-fast during `HANK_TOOLS` module import, not during agent run.
- `entry.callable` is already unwrapped per `_register` in `registry.py:75-90`. No additional `_unwrap()` needed.
- `BLOCKED_PARAMS` enforced — prevents the model from requesting file outputs or debug-dump modes.
- `inspect.signature(raw_fn)` filters to accepted kwargs so extra BLOCKED_PARAMS keys don't raise.
- `entry.has_user_email` drives auto-injection. Benchmark mode = `None`.

##### 3.2.4.B Edgar_updater direct-import adapter

For all 9 edgar-financials tools (§3.2.3.A). These are NOT in risk_module's agent registry.

**Source:** `Edgar_updater/mcp_server.py` defines MCP tools via `@mcp.tool` decorators. Direct import:

```python
# evals/vals-finance-agent/harness/hank_tools_edgar.py
import asyncio, json, inspect
from model_library.agent import Tool, ToolOutput

# Direct import — NOT via registry. These are Edgar_updater's own tools.
from Edgar_updater.mcp_server import (
    get_filings as _edgar_get_filings,
    get_financials as _edgar_get_financials,
    get_metric as _edgar_get_metric,
    get_metric_series as _edgar_get_metric_series,
    list_metrics as _edgar_list_metrics,
    search_metrics as _edgar_search_metrics,
    get_filing_sections as _edgar_get_filing_sections,
    extract_filing_file as _edgar_extract_filing_file,
    list_extraction_schemas as _edgar_list_extraction_schemas,
)

def _unwrap_edgar(fn):
    """Edgar tools may be @mcp.tool-wrapped; peel if so."""
    return getattr(fn, "__wrapped__", fn)

def _build_edgar_adapter(
    edgar_fn,
    display_name: str,
    description: str,
    parameters: dict,
    required: list[str],
) -> type[Tool]:
    """Adapter for Edgar_updater tools. NO registry, NO BLOCKED_PARAMS — Edgar lacks that convention."""
    raw_fn = _unwrap_edgar(edgar_fn)

    class _HankTool(Tool):
        name = display_name

    _HankTool.description = description
    _HankTool.parameters = parameters
    _HankTool.required = required

    async def execute(self, args, state, logger):
        try:
            sig = inspect.signature(raw_fn)
            filtered = {k: v for k, v in args.items() if k in sig.parameters}
            if inspect.iscoroutinefunction(raw_fn):
                result = await raw_fn(**filtered)
            else:
                result = await asyncio.to_thread(raw_fn, **filtered)
            return ToolOutput(output=json.dumps(result, default=str))
        except Exception as e:
            return ToolOutput(output=f"{type(e).__name__}: {e}", error=str(e))

    _HankTool.execute = execute
    _HankTool.__name__ = f"Hank_edgar_{display_name}"
    return _HankTool
```

**Day 1 verification:** confirm `Edgar_updater/mcp_server.py` exports these names as-is, or document the correct import path. If exports differ, update here and commit.

##### 3.2.4.C FMP direct-import adapter — NEW r4

For 8 FMP analytical tools (§3.2.3.B). These are top-level functions in `risk_module/fmp/server.py` — Codex confirmed the agent registry does NOT cover them.

```python
# evals/vals-finance-agent/harness/hank_tools_fmp.py
import asyncio, json, inspect
from model_library.agent import Tool, ToolOutput

# Direct import — NOT via registry.
from fmp.server import (
    fmp_profile as _fmp_profile,
    get_stock_fundamentals as _fmp_fundamentals,
    get_earnings_transcript as _fmp_transcript,
    compare_peers as _fmp_compare_peers,
    get_market_context as _fmp_market_context,
    get_events_calendar as _fmp_events,
    get_news as _fmp_news,
    get_sector_overview as _fmp_sector,
)

def _build_fmp_adapter(
    fmp_fn,
    display_name: str,
    description: str,
    parameters: dict,
    required: list[str],
) -> type[Tool]:
    """Adapter for fmp.server tools. NOT registry-backed."""

    class _HankTool(Tool):
        name = display_name

    _HankTool.description = description
    _HankTool.parameters = parameters
    _HankTool.required = required

    async def execute(self, args, state, logger):
        try:
            sig = inspect.signature(fmp_fn)
            filtered = {k: v for k, v in args.items() if k in sig.parameters}
            if inspect.iscoroutinefunction(fmp_fn):
                result = await fmp_fn(**filtered)
            else:
                result = await asyncio.to_thread(fmp_fn, **filtered)
            return ToolOutput(output=json.dumps(result, default=str))
        except Exception as e:
            return ToolOutput(output=f"{type(e).__name__}: {e}", error=str(e))

    _HankTool.execute = execute
    _HankTool.__name__ = f"Hank_fmp_{display_name}"
    return _HankTool
```

**Day 1 verification:** run each `fmp.server` function standalone to confirm signature + return shape. Some (`compare_peers`, `get_earnings_transcript`) may require specific args that the benchmark agent won't get right without good descriptions.

##### 3.2.4.D Model-engine adapter — **DEFERRED from v1 per r4**

Was planned for r2/r3. Deferred to v1.5 or later pending `ModelBuildContext` track (see §3.2.8). v1 sprint uses `hank_code_execution` for financial_modeling questions instead.

When MBC ships, this adapter will wrap `build_model_from_mbc(mbc)` + the downstream model tools (which take `file_path` + `item_ids` per Codex's source-verified signatures, not `output_path` + `line_item_id`).

##### 3.2.4.D Shared concerns

**`user_email` handling:**
- Registry adapters (§3.2.4.A): auto-inject `user_email=None` per `entry.has_user_email`.
- Edgar/FMP adapters (§3.2.4.B/C): those tools don't use `user_email` — no-op.

**DB mode:**
- Run with `DATABASE_URL` unset per `mcp_server.py:80-85`.
- Registry loads in no-DB mode; Edgar/model tools are DB-agnostic (file + API only).

**Agent-format envelope:**
- Many risk_module tools return `{"status", "format": "agent", "snapshot", "flags", "file_path"}`.
- Judge sees only `final_answer`, not tool outputs — envelope shape doesn't affect scoring directly.
- BUT: envelope is what the agent reasons over. `json.dumps(result, default=str)` full-dump for v1. Measure context usage on dry-run; tighten via `_summarize_agent_envelope()` if context bloats.

**Special wrappers:**
- **`HankSubmitFinalResult`** — subclass of native `SubmitFinalResult`. **Warns (not blocks)** on missing citations per Codex + Q8 (changed from r2 hard-block).
- **Code execution wrapper** — see §3.2.9. Local subprocess default.
- **Modeling studio** — deferred from v1 per r4 (§3.2.8). Financial-modeling questions route to `hank_code_execution` instead.

#### 3.2.5 Hank system prompt injection (Config A) — r4

The actual prompt text is in §4.2.2 — this section is structural intent only. With 25 tools in Config A vs 5 in Config B, tool-category guidance matters.

Config A replaces `INSTRUCTIONS_PROMPT` with a Hank-specific prompt that:

- **Voice** — condensed from `BRAND.md`: *"Hank doesn't hedge. Hank says the thing."*
- **Retained from vendor prompt:** date anchor (April 07, 2025), citation dict format, precision rules (two decimal places, no rounding intermediates).
- **Citation discipline:** refuse if no supporting evidence; never fabricate citations.
- **Tool-category guidance** — see §4.2.2 for the full-text prompt. Summary: structured XBRL (`hank_get_financials`) for quant questions, `hank_get_filing_sections` for narrative, `hank_earnings_transcript` for transcripts, `hank_company_profile`+`hank_stock_fundamentals` for profile/fundamentals, `hank_compare_peers` for comparisons, `hank_stock_risk_analysis` for beta/volatility, `hank_code_execution` for financial-modeling (modeling studio deferred per r4).
- **"No portfolio" hint:** session has no connected portfolio.

**Critical: the prompt is a live lever on benchmark score.** Too prescriptive → robs the model of reasoning flexibility. Too loose → tool-selection confusion. Codex review: please critique §4.2.2.

#### 3.2.6 Response + citation format

- **What `submit` expects:** `submit_final_result(final_result: string)` — a plain string. No structured field for citations; convention is to include a `{"sources": [...]}` dict at the end of the final string, per `prompt.py` lines 17-27.
- **Hank's existing source-chip format** uses `[S1]`, `[S2]` inline + a bottom `Sources:` block (per F25 handoff, `MEMORY.md`). For this benchmark we conform to Vals's dict-at-end format, not Hank's UI format — the judge parses what it expects.
- **What the judge sees:** `AgentResult.final_answer` string, which is the arg passed to `submit_final_result`. The rubric (from `public.csv`) evaluates on (a) correctness of factual claims, (b) presence/absence of contradictions vs the gold answer.
- **Citation discipline as-implemented (Config A only):** we add a final-turn validation inside the Hank wrapper — if the model emits `submit_final_result` but the `final_result` string lacks a `"sources"` dict, we intercept via a wrapper tool (not `SubmitFinalResult` but `HankSubmitFinalResult` that subclasses it and runs the check before marking `done=True`). See §4.2.4.

#### 3.2.7 Trace capture

Per sprint plan Day 2 checklist: "Per-question trace logging: question ID, config used, all tool calls made, raw responses, parsed answer, cited passages, judge score, failure category."

**Key architectural point:** the harness already writes extremely rich per-turn logs (see §3.1.5). We do NOT duplicate that. Instead:

- `trace_logger.py` writes a **single JSONL summary line per question** (one row = one `question_id`) with the shape documented in §3.4.3.
- The raw per-turn data stays in `vendor/finance-agent/logs/` and is symlinked into `results/<ts>/config_{a,b}/agent_logs/` at run completion.
- Judge score + failure category are added post-hoc once the Vals run completes, by joining `traces.jsonl` with `run.json` on `question_id`.

**Separation-of-concerns critical check:** the harness-driven per-turn logs must NOT be read by the judge. They aren't — the Vals SDK only sees `OutputObject.final_answer` (the `submit` string). So adding verbose traces doesn't pollute scoring. Confirmed by reading `custom_model.py:39-47`: `OutputObject.from_agent_result(result, count_tool_metadata=True)` — `count_tool_metadata` is about *counting* tool calls for statistics, not passing them to the judge.

#### 3.2.8 Financial modeling studio integration — DEFERRED r4

**r4 decision (2026-04-20):** deferred from v1 sprint. Will be added in iteration (Week 4-6+) once `ModelBuildContext` ships on its track.

**Why deferred:**

- **r3 plan wrapped `build_model_from_ticker` — that function doesn't exist.** The real orchestrator is `BuildModelOrchestrator.build_and_annotate(handoff_id, user_id)` (`AI-excel-addin/api/research/build_model_orchestrator.py:62`) which requires a **finalized handoff** in the repo + user_id — not a ticker.
- Building a "synthetic handoff shim" for the benchmark would be 2-3 engineering days. The cleaner path is the typed `ModelBuildContext` (MBC) bridge being built on the schema-unification track (`docs/planning/MODEL_BUILD_CONTEXT_PLAN.md`, Codex PASS R8, ~22.5 engineering days of sub-phases A-J).
- MBC is actively in-flight on `feat/thesis-living-artifact-plan-1` (Plan #1 prereq). When MBC ships, `build_model_from_mbc(mbc)` gives us a clean ticker-style entry point.
- Coupling v1 benchmark sprint to MBC implementation = coupling two risky projects. Better to defer and iterate in.

**What replaces it in v1:**

For financial_modeling questions (the 1-in-9 category Vals tests), the agent routes to `hank_code_execution` (§3.2.9 local subprocess). System prompt (§4.2.2) guides:

- *"For DCF / projection / model questions, use `hank_code_execution` to build the calculation step-by-step with auditable Python. Include numpy/pandas computations, cite line items from `hank_get_financials`, and report the resulting values in your final answer."*

This is WEAKER than a full modeling studio — the agent builds models from scratch each time instead of using the SIA template — but it's honest for v1 measurement.

**Calibration context (verified against actual public 50 on 2026-04-21):**

The "Financial Modeling / Projections" category is **4 of 50 questions** (8% of the benchmark), not a dominant share:
- Q12 (TSM): apply 3-year-average March growth rate → project Q1 revenue → compare to guidance. 60-min expert task.
- Q30 (Snapchat): max dilutive share count from outstanding converts as of 12/31/2024. 30-min.
- Q31 (BROS): apply 30% revenue CAGR + 500bps margin compression → 2026 gross profit. 10-min.
- Q43 (Uber): decompose 2024 revenue growth into take-rate vs volume. 15-min.

**None of these require a full SIA DCF template.** All four are "retrieve specific inputs from filings + apply a formula the question names explicitly." Code execution (§3.2.9 `hank_code_execution`) is a strong fit for all four without the modeling studio — verified upside from adding model_build is at most ~4-8pp on these 4 questions, more likely 2-4pp.

**Week N integration hook (see §7):**

When MBC ships on its separate track, we integrate as a specific iteration milestone rather than baking into Day 1. Clean attribution: Week-N run with model_build vs. baseline shows the delta directly. Also decouples benchmark sprint risk from MBC implementation risk.

**Tracking:** add "MBC benchmark integration" as a task in the iteration run_log once MBC ships. Do not block v1 sprint on it.

#### 3.2.9 Code execution integration — REVISED r3

**Codex caught:** r2 made hosted Anthropic code-execution beta the preferred default. But:
- Inventory §3 says that path is **"not wired"** in Hank today.
- AI-excel-addin explicitly **replaced** hosted `code_execution_20260120` with local `code_execute` subprocess per `docs/planning/LAUNCH_BACKLOG.md:27`.
- `risk_module/providers/completion.py:174` uses `client.messages.create`, not beta code-exec plumbing.

**r3 fix: local subprocess is the default.** Matches production Hank. Hosted beta deferred.

##### r3 option ranking (reversed from r2)

**Option A (preferred r3): Local `code_execute` subprocess via AI-excel-addin**
- Uses `AI-excel-addin/agent_gateway/code_execution/` — same stack as production.
- Python subprocess in isolated venv. Pre-installed: numpy, pandas, scipy, math, `portfolio_math`.
- Matches how Hank actually executes code in production → zero divergence between benchmark and prod behavior.
- Timeout + stdout/stderr capture + error handling already production-hardened.

**Option B (fallback): Docker backend via same `agent_gateway`**
- Same interface, heavier isolation. Use if subprocess has leakage issues.

**Option C (deferred): Anthropic hosted beta**
- Not a v1 target. Wire in later as spike if benchmark + production have reason to converge on it.
- Also noted: hosted beta may have different library set, different timeouts, different stdout handling — would introduce benchmark-vs-production divergence.

##### Wrapper shape (Option A, local subprocess) — REVISED r4

**Codex caught in r3:** import path `execute_code` doesn't exist. Actual package exports (`AI-excel-addin/packages/agent-gateway/agent_gateway/code_execution/__init__.py`) are:
- `build_code_execution` — factory that returns a configured code-execution tool
- backends (Docker, subprocess) as separate submodules
- config object

Low-level helper is internal at `_helpers.py:300` and **requires a backend + config + session work dir** — not a trivial `execute_code(code)` call.

**Result shape (verified per Codex):** `{"stdout", "stderr", "return_code", "images", "timed_out", "duration_ms", "truncated"}` — NOT the `{"stdout", "return_value", "error"}` I specified in r3.

##### r4 wrapper shape

```python
# harness/hank_code_execution.py
import asyncio, json
from model_library.agent import Tool, ToolOutput

# Real API per AI-excel-addin/packages/agent-gateway/agent_gateway/code_execution/__init__.py
from agent_gateway.code_execution import build_code_execution
from agent_gateway.code_execution.config import CodeExecutionConfig
from agent_gateway.code_execution.backends import SubprocessBackend  # r4 default

# Module-level factory — one instance reused across questions.
_BACKEND = SubprocessBackend(...)  # config args verified Day 1 against actual module signature
_CONFIG = CodeExecutionConfig(
    timeout_seconds=30,
    # other config fields per real CodeExecutionConfig class — verify Day 1
)
_EXECUTOR = build_code_execution(backend=_BACKEND, config=_CONFIG)
# Session work dir per-run; re-initialized between benchmark runs.

class HankCodeExecution(Tool):
    name = "hank_code_execution"
    description = (
        "Execute Python code in a sandboxed subprocess. Use for numerical reasoning, "
        "arithmetic verification, DCF calculations (model build is deferred), "
        "or any computation you want to make auditable. Pre-installed: numpy, pandas, scipy, math, "
        "portfolio_math. Output = captured stdout."
    )
    parameters = {
        "code": {"type": "string", "description": "Python code to execute. Use print() for output; return values are not captured."},
        "timeout_seconds": {"type": "integer", "description": "Optional timeout override (default 30s).", "default": 30},
    }
    required = ["code"]

    async def execute(self, args, state, logger):
        try:
            # _EXECUTOR is the callable-or-object built by build_code_execution.
            # Exact invocation signature verified Day 1 (could be _EXECUTOR.run(code), _EXECUTOR(code=..., work_dir=...), etc.)
            result = await asyncio.to_thread(
                _EXECUTOR.run,  # placeholder — verify Day 1
                code=args["code"],
                timeout_seconds=args.get("timeout_seconds", 30),
            )
            # Real result shape: stdout, stderr, return_code, images, timed_out, duration_ms, truncated
            out_parts = []
            if result.get("stdout"):
                out_parts.append(result["stdout"])
            if result.get("stderr") and result.get("return_code", 0) != 0:
                out_parts.append(f"STDERR: {result['stderr']}")
            if result.get("timed_out"):
                out_parts.append(f"TIMED OUT after {result.get('duration_ms', '?')}ms")
            if result.get("truncated"):
                out_parts.append("(output truncated)")
            error_str = result.get("stderr") if result.get("return_code", 0) != 0 else None
            return ToolOutput(output="\n".join(out_parts) if out_parts else "(no output)",
                              error=error_str)
        except Exception as e:
            return ToolOutput(output=f"{type(e).__name__}: {e}", error=str(e))
```

**Day 1 verifications (concrete):**
1. Confirm package name — might be `agent_gateway` standalone or nested under `AI_excel_addin.packages.agent_gateway` depending on install path.
2. Confirm exact `SubprocessBackend.__init__` args + `CodeExecutionConfig` fields.
3. Confirm `build_code_execution(...)` return type and how to invoke (callable? `.run(code)`? `.execute(...)`?).
4. Confirm session work dir handling — do we create/cleanup per-question or one for the full run?
5. Confirm pre-installed packages — numpy/pandas/scipy confirmed via inventory, but verify availability in subprocess backend specifically.
6. Smoke test: `_EXECUTOR.run(code="print(1+1)")` returns `{"stdout": "2\n", "return_code": 0, ...}`.

All Day 1 verifications gate Day 2 Hank wrapper build per timeline §7.

**What doesn't work in r4 (acknowledging):**
- Return-value capture. Real API returns stdout only per Codex-verified result shape. If agent wants a value, it must `print()` it. System prompt should reflect this.
- `return_value` field in r3 was wrong.

##### Attribution concern (Q13, retained)

Adding code execution to Config A while Config B doesn't have it introduces a capability delta beyond "wrapper architecture." Commercial narrative addresses this honestly:

- **r4 honest framing:** *"Hank's v1 architecture — including local code-execution subprocess — beats raw Opus on its harness-native tools by X pp."* (Modeling studio deferred per r4 §3.2.8 — re-add when MBC track ships.)
- **Not:** *"Hank's prompt alone beats raw Opus."*

If we want pure-wrapper-attribution later, Config C (Config A minus code execution) can be a decomposition exercise in v1.5. For v1, code execution is in because it's part of Hank.

**r3 additional advantage over r2:** using the same code-execution path as production means delta results transfer 1:1 to production behavior. Hosted-beta results might not.

### 3.3 Raw-Opus baseline fidelity (Config B)

#### 3.3.1 Config B = harness defaults, unchanged

Config B is the **simplest possible setup**: run the harness as the README documents, with the Vals SDK + `get_custom_model` path, model = `anthropic/claude-opus-4-7-...`. No Hank code touches Config B at all.

Implementation: `configs/config_b_raw_opus.py` is a 15-line file that re-exports `get_custom_model` from the vendored `finance_agent.custom_model` unchanged, only overriding the model name. This forces byte-level identity with what Anthropic would have used to produce their 64.4% number, modulo:

- Model version (exact Opus 4.7 snapshot — see §6 Q5 — we use whatever the Vals model-library registry routes to).
- Tavily / SEC-API key quota (shouldn't affect score unless we hit rate limits).
- LLM sampling non-determinism (temperature=0 per `run_agent.py:78` default).

#### 3.3.2 Acceptance criterion

**Primary:** our Config B on public 50 must score **64.4% ± 3pp** vs Anthropic's published number.

- Tolerance of ±3pp is wider than pure sampling noise would give (σ on n=50 with p=0.64 is ~7pp, so 95% CI is ~±13pp — but the judge and harness are fully deterministic modulo LLM sampling, so in practice we expect smaller variance).
- Tighter tolerance risks a false negative; wider tolerance hides harness bugs.
- If Config B is outside this band, **Config A delta claims are suspect** (stated in sprint plan §9) and we investigate before trusting numbers.

#### 3.3.3 Debug steps if Config B diverges

Ordered by likelihood:

1. **Model snapshot mismatch.** Check `model_library/config/all_models.json` for which Opus 4.7 version `anthropic/claude-opus-4-7` resolves to; confirm it matches Anthropic's release card. (§6 Q5.)
2. **Judge model mismatch.** Our `RunParameters.eval_model` might default to something other than GPT-5.2. Hard-code to match published methodology.
3. **Mode-of-3 vs single-pass.** Confirm `heavyweight_factor=3` or equivalent is set.
4. **Tavily / SEC API quota exhaustion.** If tool calls fail, the agent can't retrieve — affects score. Check error rate across traces.
5. **`MAX_END_DATE` drift.** `tools.py:16` hard-codes `2025-04-07`. Confirm this matches the benchmark's anchor.
6. **Prompt drift.** `prompt.py`'s text may have changed between Anthropic's run and ours. Diff against Anthropic's methodology doc if available (likely not).
7. **Max-turns / context-window cutoffs.** Default `max_turns=50`, `max_tokens=32000`. Confirm these match Anthropic's run.
8. **Temperature.** Default 0.0 is deterministic-ish but Anthropic MAY have used thinking mode. Check Opus 4.7 release notes.

If all 8 check out and we still diverge ≥3pp, document the divergence in the result writeup and proceed with a caveat — it becomes a methodology footnote, not a blocker.

### 3.4 Scoring calibration + logging

#### 3.4.1 Local judge vs hosted judge

**Decision: use Vals hosted judge.** Reasons:

- The sprint plan (§2.6) mandates matching Vals methodology exactly. Re-implementing GPT-5.2 as judge with mode-of-3 locally is (a) ~$15 in marginal GPT-5.2 calls vs free-via-Vals-quota, (b) a source of methodology drift, (c) engineering work we don't need.
- Per Vals docs (web-fetched), judging is platform-side with `RunParameters(eval_model="...", heavyweight_factor=3)`. Nothing to build.
- The only case for a local judge is if we run out of VALS_API_KEY quota or the platform is slow. In that case we stub locally (§3.4.2 next).

#### 3.4.2 Stub judge for dry-running

Before VALS_API_KEY arrives we need to validate the wrapper end-to-end. `harness/scoring_stub.py` provides a local stub that:
- Takes `final_answer` + the `Rubric` column from `public.csv`.
- Sends a single GPT-5.2 call (or Claude if no OpenAI key) with the rubric → returns pass/fail per criterion → aggregated pass rate.
- Clearly labeled "stub — not Vals judge" in logs; never used for reported numbers.

This is **not** a re-implementation of the Vals judge; it's a smoke-test tool so Day 1–2 aren't blocked by platform registration.

#### 3.4.3 Per-question trace schema

One JSON record per question, appended as a line to `results/<ts>/config_<x>/traces.jsonl`:

```json
{
  "question_id": "q001",
  "question": "How has US Steel addressed its planned merger...",
  "config": "A" | "B",
  "model": "anthropic/claude-opus-4-7-20260401",
  "timestamp_start": "2026-04-21T15:01:23.456Z",
  "timestamp_end": "2026-04-21T15:03:08.912Z",
  "duration_seconds": 105.456,
  "total_turns": 12,
  "stop_reason": "done_tool" | "max_turns" | "error",
  "tool_usage": {"edgar_search": 3, "hank_get_financials": 2, "hank_earnings_transcript": 1, "hank_code_execution": 1, "submit_final_result": 1},
  "tool_call_count": 11,
  "error_count": 0,
  "final_answer": "<full string submitted>",
  "final_answer_sources": [{"url": "...", "name": "..."}],
  "final_error": null | {"type": "...", "message": "..."},
  "aggregated_tokens": {"input": 187453, "output": 12789, "cost_usd": 0.38},
  "question_type": "Market Analysis",
  "agent_log_dir": "vendor/finance-agent/logs/finance/anthropic_claude-opus-4-7/2026-04-21_15-01-23_abc123",
  "judge_score": null,      // populated post-run from run.json
  "judge_pass": null,       // true/false from rubric aggregation
  "judge_failures": []      // list of failed rubric criteria
}
```

Produced by `trace_logger.py`, which subscribes to `AgentResult` post-run. The Vals SDK `run.json` has `test_results` with per-question scores; we join on `question_id`.

#### 3.4.4 Aggregation

`scripts/aggregate_results.py` slices:

- Overall pass rate (both configs).
- Per-question-category pass rate (9 categories from `Question Type` column).
- Per-filing-type pass rate (derivable from question text or by post-hoc tagging — see §6 Q6).
- Head-to-head: list of questions where Config A wins and Config B loses (and vice-versa), with stop reasons.
- Token + cost + duration distributions per config.

Output: `results/<ts>/summary.md` (human-readable) + `summary.json` (machine-readable).

### 3.5 Two-config execution methodology

#### 3.5.1 Isolation — identical inputs, different processes

- **Same `public.txt`, same `public.csv`, same rubric.** Both configs read from the same files in the vendored harness.
- **Different processes.** `run_config_a.sh` and `run_config_b.sh` are separate shell scripts. Each loads a different `.env` suffix (`.env.config_a`, `.env.config_b`) so keys don't leak. Each invokes a different `run_name` so Vals platform keeps runs separate.
- **Same model.** Both use `anthropic/claude-opus-4-7` — this is pinned in both config files.
- **Same judge.** `RunParameters(eval_model=...)` is identical between configs.
- **Different tool sets.** Config A has 25 tool classes (20 Hank + 4 harness-native + Hank submit) per r4 §3.2.3, Config B has 5 — by design.
- **Different system prompts.** Config A has Hank-prompt, Config B has `INSTRUCTIONS_PROMPT` — by design.
- **Order:** run Config B first, then Config A. Rationale: Config B establishes the baseline we sanity-check before trusting Config A delta. If Config B diverges from 64.4%, we don't run Config A until debugged.

#### 3.5.2 Order-independence

Concern: does running A first affect B (or vice versa)? Possible contamination vectors:

- **Vals platform caching of completions.** Unknown if Vals caches per-question responses; safer to assume not, but confirm via a sanity-check re-run of Config B after Config A and compare to first Config B run (see §5.2).
- **Tavily / SEC-API caches.** These may return slightly different results on re-fetch due to real-world content change. Mitigation: pin dates in queries where possible (though our system prompt already anchors to 2025-04-07).
- **Hank wrapper DB/file side-effects.** Should be zero — we run with `DATABASE_URL` unset + no user_email. If any wrapper tool writes to disk, that's a wrapper bug (we audit via `lsof` or `strace` in dry-run phase).

#### 3.5.3 Determinism + reproducibility

What is reproducible:
- Harness commit SHA, model-library version, all API versions (pinned in `vendor/finance-agent/uv.lock` + Hank repo lockfile).
- `temperature=0`, `max_tokens=32000`, `max_turns=50` — all locked in config files.
- System prompts (frozen in config files, checked in).
- Tool list (frozen in config files).

What is NOT reproducible:
- LLM sampling non-determinism (even at T=0, Anthropic's model can produce slightly different tokens).
- Web-search results (Tavily returns change).
- Timing-dependent tool retries (rare).

This is acceptable: the sprint plan §9 success criteria explicitly says *"LLM non-determinism is expected; methodology should still be auditable."* We audit via: commit SHAs + pinned deps + full per-turn logs + published system prompts.

### 3.6 Iteration hygiene — NEW r2

**Context:** per sprint plan §3.4 (revised 2026-04-20), first Config A run is a baseline measurement, not a publish candidate. Expected iteration cycle: 8 weeks with weekly Config A reruns, architectural fixes between runs, decision gate at Week 8.

This section defines the discipline to prevent overfitting during iteration.

#### 3.6.1 What counts as legitimate iteration

**Allowed (architectural fixes):**
- **Tool additions**: discovering the agent couldn't answer a class of question because a tool was missing → add the tool.
- **Tool quality fixes**: `hank_get_financials` returned empty for a filing our corpus is missing → backfill the corpus.
- **Tool description sharpening**: agent chose the wrong tool because the description was ambiguous → tighten the description (applies to the category, not the specific question).
- **Prompt structure improvements**: agent systematically misroutes between tool categories → sharpen the category guidance in the system prompt.
- **Agent loop fixes**: agent wastes turns on a pattern (e.g., retrying failed searches) → fix the retry logic.
- **Infrastructure fixes**: Tavily rate limits causing spurious failures → upgrade tier or add retry.

**NOT allowed (score-gaming):**
- Adding few-shot examples that target specific test questions.
- Adding prompt text that hints at the expected answer format for a specific question type seen in failures.
- Hard-coding special cases for specific tickers or filing combinations seen in failures.
- Creating tool aliases that exist only to win on benchmark questions.
- Tuning hyperparameters (temperature, max_turns) based on which value scores higher on public 50.

**The test:** would this change improve Hank's behavior on production user workflows that have nothing to do with this benchmark? If yes → legitimate. If no → score-gaming.

#### 3.6.2 Run history discipline

Every Config A rerun is tracked in `results/<run_ts>/run_log.md` with:
- Timestamp of the run
- Git SHA of Hank repo at run time
- Git SHA of vendor harness at run time (should be constant unless we intentionally update)
- Exact model snapshot
- **Delta-from-previous-run**: what changed since the last run? PR references, specific commits, specific tool additions.
- Overall score, delta vs Config B, per-category breakdown
- Specific questions that flipped (pass↔fail) since the last run — with spot analysis

This creates a transparent audit trail. At publish time, the run log is part of the methodology writeup.

#### 3.6.3 Config B rerun cadence

Config B (raw Opus 4.7) baseline is a moving target over 8 weeks because:
- Anthropic may update the Opus 4.7 snapshot
- Vals platform may change judge behavior
- Tavily / SEC-API behavior may drift

**Cadence: rerun Config B at every major Config A rerun** (weekly at minimum). Cost: ~$50 per rerun. Preserves apples-to-apples comparison.

If Config B score drifts more than ±3pp between reruns without any platform-side change, that's a methodology issue worth investigating (probably harness or API drift).

#### 3.6.4 Private 337 engagement

**Week 4-5:** initiate Vals AI licensing conversation for private test set access. Timing:
- Don't start on Day 1 (no signal yet; looks premature)
- Don't wait until Week 7 (licensing takes 2-4 weeks)
- Week 4-5 = we have 3+ weeks of data showing iteration trajectory — credible engagement pitch

**Private 337 run happens only once, at publish time.** Not used for iteration. That's why it's the "unassailable" number — we've never seen it, can't have tuned to it.

#### 3.6.5 Non-benchmark regression tests

As we change Hank's architecture for benchmark reasons, we verify the changes don't regress production behavior:

- Smoke tests on Hank's existing scenario tools (stress, MC, optimize, hedge) with real portfolios
- Unit tests on the changed MCP tools
- Manual dogfood check: a team member runs their own portfolio through Hank after each architectural change, reports papercuts

If an architectural change improves Config A score but regresses production behavior, revert the change. Benchmark gains at the cost of product quality are not gains.

#### 3.6.6 The publish discipline

Decision gate at Week 8 follows sprint plan §3.4 (revised) exactly:
- Score ≥ 95% + delta ≥ 25pp → hero publish
- Score ≥ 92% + delta ≥ 25pp → SOTA-claim publish
- Score 88-92% → extend 4 weeks with a specific architectural hypothesis
- Score 80-88% → publish delta story only, engage Vals private 337, continue iteration
- Score < 80% or delta < 15pp → HOLD, deeper architectural rework

**Publish readiness also requires:**
- Private 337 conversation in-flight (credibility of a pending independent validation)
- Run log + methodology writeup complete
- Non-benchmark regression suite passing
- Consensus from ≥2 reviewers (not just the sprint owner) on the final Config A architecture

---

## 4. File-by-file implementation

This section is what Codex will pick over hardest. Each subsection = one new file or one surgical change, with function signatures spelled out. No code is written; this is the spec.

### 4.1 Harness vendor setup

**`evals/vals-finance-agent/vendor/finance-agent/`**

- Created via `git clone https://github.com/vals-ai/finance-agent.git` at a specific SHA. We pin to whatever `main` is on Day 1 — the plan doc records the SHA.
- Inside, we additionally `uv venv --python 3.12 && uv sync --dev && uv tool install .` in a sandbox venv. The `.venv/` is gitignored.
- **No modifications** to vendor files. If we need a tweak, we fork with a separate commit in a Hank-owned branch, recorded in the `README.md`.

**`evals/vals-finance-agent/.gitignore`:**
```
vendor/finance-agent/.venv/
vendor/finance-agent/logs/
vendor/finance-agent/.env
results/
configs/suites.json
configs/.env.*
```

### 4.2 Config A — Hank wrapper

#### 4.2.1 `harness/hank_model.py`

Entry point replacing `finance_agent.custom_model.get_custom_model`. Signature **must match** the Vals SDK contract (see §3.1.3):

```python
async def get_custom_model(
    model_name: str,
    parameters: dict[str, Any],
    *_args: object,
    **_kwargs: object,
) -> CustomCallable: ...
```

Internals:
1. Validate `model_name` starts with `anthropic/claude-opus-4-7` (Config A pin).
2. Build `llm` via `get_registry_model(model_name, ...)` — same as vendor.
3. Build Hank tool list via `_build_hank_tools(llm)` (§4.2.3).
4. Build Hank agent via `_build_hank_agent(llm, tools, params)` (§4.2.2).
5. Return `custom_call` closure.

Closure:
```python
async def custom_call(test_input, files, context, question_id, run_id):
    prompt = HANK_INSTRUCTIONS_PROMPT.format(question=test_input)  # see §4.2.2
    agent = _build_hank_agent(llm, tools, params)                  # fresh per-question
    result = await agent.run([TextInput(text=prompt)], question_id=question_id, run_id=run_id)
    trace_logger.write(result, question_id, config="A")            # §4.4
    return OutputObject.from_agent_result(result, count_tool_metadata=True)
```

#### 4.2.2 Hank system prompt (`HANK_INSTRUCTIONS_PROMPT`) — r4

Draft for the r4/r5 25-tool catalog (§3.2.3). Codex review requested on tool-category guidance + citation-discipline language.

```
You are Hank, a senior financial analyst. Hank does not hedge. Hank says the thing.

You are given a question and you need to answer it using the tools provided.
You will not be able to interact with the user or ask clarifications.

You should answer all questions as if the current date is April 07, 2025.

You have access to 25 tools organized by category (r4 — modeling studio deferred):

HARNESS-NATIVE TOOLS (4):
- edgar_search, parse_html_page, retrieve_information — SEC full-text search + HTML fetch + keyword retrieval
- web_search (Tavily) — web fallback for non-SEC sources

HANK EDGAR TOOLS (9) — structured filing data:
- hank_get_filings — find the right filing (metadata)
- hank_get_financials — full XBRL extract (income / balance / cash flow)
- hank_get_metric, hank_get_metric_series — specific XBRL facts + time series
- hank_list_metrics, hank_search_metrics — discover metrics
- hank_get_filing_sections — parsed MD&A / Risk Factors / etc.
- hank_extract_filing_file, hank_list_extraction_schemas — custom-schema extraction

HANK FMP TOOLS (8) — profile, fundamentals, transcripts, market context:
- hank_company_profile — company profile (CEO, industry, market cap, share count)
- hank_stock_fundamentals — fundamentals + valuation + quality signals
- hank_earnings_transcript — per-speaker Q&A + prepared remarks
- hank_compare_peers — peer comparison
- hank_market_context — market snapshot
- hank_events_calendar — earnings / splits / IPOs
- hank_get_news — news flow
- hank_sector_overview — sector P/E + performance

HANK REGISTRY TOOLS (2):
- hank_get_quotes(tickers: list) — multi-ticker quote
- hank_stock_risk_analysis — volatility / beta / factor-exposure analysis for a single stock or ETF

HANK CODE EXECUTION (1):
- hank_code_execution — Python sandbox for auditable arithmetic + building calculations step-by-step

SUBMIT (1):
- submit_final_result — ONLY way to terminate with an answer

TOOL-SELECTION GUIDANCE:
- Filing-grounded QUANTITATIVE questions (revenue, EPS, margins, cash flow): prefer
  hank_get_financials (structured XBRL). Use hank_get_metric_series for trends.
- Filing NARRATIVE (MD&A, Risk Factors, strategy): hank_get_filing_sections.
  Fall back to edgar_search + parse_html_page if not parsed.
- Earnings-call questions (guidance, Q&A, management tone): hank_earnings_transcript.
- Company profile (market cap, CEO, share count): hank_company_profile + hank_stock_fundamentals.
- Peer comparison: hank_compare_peers.
- Volatility / beta / factor-exposure questions: hank_stock_risk_analysis.
- FINANCIAL MODELING questions (DCF, build-a-projection, WACC, terminal value, target price):
  Use hank_code_execution to build the calculation step-by-step with auditable Python. Pull
  required inputs (revenue, margins, etc.) via hank_get_financials or hank_get_metric_series,
  feed them into your Python calculation, `print()` the results, and cite the input values +
  your computed outputs in the final answer. (A dedicated modeling studio tool is deferred
  from v1; code execution is the primary path.)
- Arithmetic / numerical reasoning: always prefer hank_code_execution over mental math.
  Note: code execution captures stdout only — use `print()` for any output you want to see.
- Web-wide search (non-SEC sources): web_search (Tavily).
- NO PORTFOLIO CONTEXT: this session has no connected portfolio. Portfolio-state tools
  are not exposed. Focus on filing, fundamentals, transcript tools.

CITATION DISCIPLINE:
- Every quantitative claim MUST be supported by a retrieved passage.
- If you cannot find supporting evidence, state "Insufficient evidence to answer with
  confidence" rather than fabricating. A refusal is better than a wrong citation.
- Provide sources at the end in this exact format:
  {
      "sources": [
          {"url": "https://example.com", "name": "Source description"},
          ...
      ]
  }

REASONING + PRECISION:
- Include step-by-step reasoning, calculations, and justifications.
- Provide calculated answers to at least two decimal places (e.g. 18.78% rather than 19%).
- Do not round intermediate calculations.

When you have the final answer, call submit_final_result.

Question:
{question}
```

**Notes:**
- Date anchor, sources format, and precision rules retained verbatim from vendor's `INSTRUCTIONS_PROMPT` for judge-compatibility.
- Voice line condensed from `BRAND.md`.
- Tool-category section lists all 25 tools by category + naming convention (`hank_*` prefix).
- Modeling studio DEFERRED per r4 §3.2.8 — prompt routes financial-modeling questions to `hank_code_execution` instead.
- "No portfolio" hint prevents agent from trying to call portfolio-state tools (not exposed, but agent doesn't know that).

#### 4.2.3 Tool wrapper modules — REVISED r4

Per r4 §3.2.4, wrapper construction splits by tool source. **Three active adapter modules (+ one deferred):**

- `harness/hank_tools_registry.py` — registry-backed, for `get_quote` + `analyze_stock` ONLY (2 tools)
- `harness/hank_tools_edgar.py` — direct import from `Edgar_updater/mcp_server.py` (9 tools)
- `harness/hank_tools_fmp.py` — direct import from `fmp.server` (8 tools) — **NEW r4**
- `harness/hank_tools_model.py` — **DEFERRED from v1** pending MBC track (§3.2.8)

Plus: `harness/hank_code_execution.py` (§3.2.9) and `harness/hank_submit.py` (warn-not-block submit per Q8).

##### Tool spec table (r4 — 20 Hank tool specs with VERIFIED signatures)

r4 fixes Codex blocker #4 (spec signatures didn't match source). All specs below were verified against actual source (grepped in this edit session).

```python
# evals/vals-finance-agent/harness/hank_tool_specs.py
# Format: (source, origin_name, display_name, description, parameters, required)
# source ∈ {"registry", "edgar", "fmp"} (model deferred per r4)

HANK_TOOL_SPECS = [
    # === A. edgar-financials (9, source="edgar") ===
    # Verified against Edgar_updater/mcp_server.py signatures.
    # Example: get_filings takes (ticker, year, quarter) — NO form_type (Codex r3 caught this)
    ("edgar", "get_filings", "hank_get_filings",
     "Fetch SEC filing metadata for a ticker + fiscal period. Returns filing records.",
     {"ticker": {"type": "string"},
      "year": {"type": "integer"},
      "quarter": {"type": "integer"}},
     ["ticker"]),
    ("edgar", "get_financials", "hank_get_financials",
     "Fetch full structured XBRL extract (income / balance / cash flow) for a ticker + fiscal period. Prefer this over edgar_search for quantitative facts.",
     {"ticker": {"type": "string"},
      "year": {"type": "integer"},
      "quarter": {"type": "integer"},
      "full_year_mode": {"type": "boolean"},
      "source": {"type": "string", "enum": ["inline_xbrl", "financial_statements"]},
      "output": {"type": "string", "enum": ["inline", "file"]}},
     ["ticker"]),
    # ... 7 more edgar specs — each verified before commit Day 1 ...

    # === B. FMP (8, source="fmp") — VERIFIED r4 ===
    # Source: fmp.server module — signatures confirmed via grep in this edit.
    ("fmp", "fmp_profile", "hank_company_profile",
     "Company profile: industry, CEO, description, market cap, share count. Single-ticker lookup.",
     {"symbol": {"type": "string", "description": "Ticker symbol, e.g. 'AAPL'."}},
     ["symbol"]),
    ("fmp", "get_stock_fundamentals", "hank_stock_fundamentals",
     "Fundamentals + valuation metrics + quality signals for a ticker. Use for company overview, confirming share count, revenue, EPS context.",
     {"symbol": {"type": "string"}},  # real signature verified Day 1
     ["symbol"]),
    ("fmp", "get_earnings_transcript", "hank_earnings_transcript",
     "Earnings call transcript parsed per-speaker (prepared remarks + Q&A). Use for guidance / management-tone questions. Year AND quarter are required.",
     {"symbol": {"type": "string"}, "year": {"type": "integer"}, "quarter": {"type": "integer"}},
     ["symbol", "year", "quarter"]),  # real signature: fmp/server.py:1034 — all three required
    ("fmp", "compare_peers", "hank_compare_peers",
     "Peer comparison for relative-value questions. Pass a symbol; optionally provide comma-separated peer tickers OR a limit on auto-peer count.",
     {"symbol": {"type": "string"},
      "peers": {"type": "string", "description": "Comma-separated peer tickers, e.g. 'MSFT,GOOGL,META'. Optional. NOT an array — real downstream tool does peers.split(',')."},
      "limit": {"type": "integer", "default": 5, "description": "Max auto-peers if 'peers' omitted."},
      "format": {"type": "string", "enum": ["summary", "full"], "default": "summary"}},
     ["symbol"]),  # verified: fmp/server.py:883 compare_peers(symbol, peers=None, limit=5, format="summary"); fmp/tools/peers.py:358 calls peers.split(",")
    # ... 4 more FMP specs — each verified before commit Day 1 ...

    # === C. Registry (2, source="registry") — VERIFIED r4 ===
    ("registry", "get_quote", "hank_get_quotes",
     "Multi-ticker latest quotes. Takes list of tickers (plural).",
     {"tickers": {"type": "array", "items": {"type": "string"}, "description": "List of tickers."}},
     ["tickers"]),
    ("registry", "analyze_stock", "hank_stock_risk_analysis",
     "Volatility / beta / factor-exposure analysis for a single stock or ETF. Use for volatility / beta questions. (Real tool per mcp_tools/stock.py:64.)",
     {"ticker": {"type": "string"},
      "start_date": {"type": "string"},
      "end_date": {"type": "string"},
      "format": {"type": "string", "enum": ["summary", "full", "report", "agent"]}},
     ["ticker"]),
]
```

**Note on `...` in specs above:** placeholder for brevity in this plan doc. **Day 1-2 wrapper-building work: fill in every spec with the real signature grepped from source.** No placeholders in actual harness code.

##### Tool class construction — REVISED r4

```python
# evals/vals-finance-agent/harness/hank_tools.py
from .hank_tools_registry import _build_registry_adapter  # §3.2.4.A
from .hank_tools_edgar import _build_edgar_adapter        # §3.2.4.B
from .hank_tools_fmp import _build_fmp_adapter            # §3.2.4.C (NEW r4)
from .hank_code_execution import HankCodeExecution        # §3.2.9
from .hank_submit import HankSubmitFinalResult            # warn-not-block per Q8
from .hank_tool_specs import HANK_TOOL_SPECS

_BUILDERS = {
    "registry": _build_registry_adapter,
    "edgar":    _build_edgar_adapter,
    "fmp":      _build_fmp_adapter,  # NEW r4
}

HANK_TOOL_CLASSES = [
    _BUILDERS[source](origin, display, desc, params, req)
    for (source, origin, display, desc, params, req) in HANK_TOOL_SPECS
] + [HankCodeExecution, HankSubmitFinalResult]
```

##### `HankSubmitFinalResult` — REVISED r4 (warn, not block)

Per Codex should-fix #4 + Q8 → v1 shifts from hard-block to warn:

- Inherits `SubmitFinalResult.execute`.
- Regex check: does `final_result` contain a `"sources"` key with a non-empty list?
- **If missing: return `ToolOutput(output=final_result, done=True)` + `trace={"warning": "missing_sources"}`.** Submission is accepted; warning recorded in trace for failure analysis.
- **Rationale:** hard-block risks `max_turns=0` failures when model forgets format. Warn preserves the discipline signal without sabotaging correct-but-unformatted answers. If v1 analysis shows citation-format failures are rare, we can switch to hard-block in iteration.

##### `HankCodeExecution` specifics — r4 local subprocess default

- Wraps `agent_gateway.code_execution` package from AI-excel-addin via `build_code_execution(backend, config)` factory with `SubprocessBackend` (§3.2.9).
- Parameters: `code: str` (required), `timeout_seconds: int` (optional, default 30).
- **Returns per real API:** `{stdout, stderr, return_code, images, timed_out, duration_ms, truncated}`. Return values are NOT captured — agent must `print()` any output.

##### Tool description authoring — material workstream (reduced)

Per r4 20-Hank-tool catalog: ~20 descriptions × ~30 min each = ~10 hours. Can be seeded from existing MCP docstrings but should be tightened for benchmark context. Split across Days 1-3 per narrowed r4 timeline (§7).

#### 4.2.4 `harness/_build_hank_agent` helper — REVISED r4

Shape identical to vendor's `finance_agent.get_agent.get_agent`, except:
- **Tool list** (per r4 §3.2.3): 9 edgar + 8 FMP + 2 registry (`get_quote` → `hank_get_quotes` + `analyze_stock` → `hank_stock_risk_analysis`) + 1 code-exec + 4 harness-native + 1 `HankSubmitFinalResult` = **25 tool classes**.
- `name="hank_finance"` (distinguishes log dir from vendor).
- `config=AgentConfig(turn_limit=TurnLimit(max_turns=50), time_limit=None)` — same as vendor.
- `hooks=AgentHooks(before_query=_before_query, should_stop=_should_stop)` — same defaults as vendor (§3.1.4). We do NOT modify loop behavior.
- Tool imports: registry-backed (§3.2.4.A for `get_quote` + `analyze_stock`), Edgar direct-import (§3.2.4.B), FMP direct-import (§3.2.4.C — NEW r4). Model-engine DEFERRED (§3.2.4.D). **Three separate module imports assembled into the agent's tool list.**

### 4.3 Config B — raw Opus baseline

#### 4.3.1 `configs/config_b_raw_opus.py`

Ultra-thin re-export. Code (≤15 lines):

```python
# Config B: raw Claude Opus 4.7 with harness-default tools only.
# No Hank wrapper, no Hank prompt, no Hank tools.
# This reproduces Anthropic's published 64.4% baseline as a sanity check.

from finance_agent.custom_model import get_custom_model  # vendor unchanged
from finance_agent.tools import VALID_TOOLS

MODEL_NAME = "anthropic/claude-opus-4-7-<exact-snapshot>"  # §6 Q5
RUN_NAME_PREFIX = "hank_vals_run_config_b"
```

This file does nothing beyond pinning config. All execution uses vendor's `get_custom_model`.

### 4.4 Trace logger

#### 4.4.1 `harness/trace_logger.py`

Single public function `write(result: AgentResult, question_id: str, config: str, question: str, question_type: str) -> None`. Implementation:
- Reads `AgentResult` fields (all available — see `agent.py:38-146`).
- Writes one JSON line to `results/<run_ts>/config_<a|b>/traces.jsonl`.
- Schema per §3.4.3.
- Run timestamp determined by env var `HANK_VALS_RUN_TIMESTAMP` (set once in `run_config_*.sh`).
- Post-run, a separate script joins `traces.jsonl` with Vals's `run.json` (scores) to populate `judge_*` fields.

### 4.5 Scripts

#### 4.5.1 `scripts/run_config_b.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail
export HANK_VALS_RUN_TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "results/${HANK_VALS_RUN_TIMESTAMP}/config_b"

cd vendor/finance-agent
source .venv/bin/activate
# Load env for Config B (no Hank DB/FMP needed — just harness deps)
source ../../configs/.env.config_b

# Invoke via Vals SDK — NOT the CLI — so we get scoring.
python ../../harness/run_vals_suite.py \
    --config config_b_raw_opus \
    --suite-id "$VALS_SUITE_ID_PUBLIC_50" \
    --run-name "hank_vals_run_config_b_${HANK_VALS_RUN_TIMESTAMP}" \
    --model "anthropic/claude-opus-4-7-<snapshot>" \
    --parallelism 5 \
    --output "../../results/${HANK_VALS_RUN_TIMESTAMP}/config_b/run.json"
```

#### 4.5.2 `scripts/run_config_a.sh`

Identical to 4.5.1 but `--config config_a_hank`, `--model` per Config A pin (still `anthropic/claude-opus-4-7-<snapshot>`), and env sourced from `.env.config_a`.

#### 4.5.3 `harness/run_vals_suite.py`

The thing the shell scripts invoke — a small Python CLI wrapping `vals.sdk.suite.Suite`:

```python
# Pseudocode — exact API TBD from Vals docs (§6 Q1)
async def main():
    args = parse_args()
    from vals.sdk.suite import Suite
    suite = await Suite.from_id(args.suite_id)
    if args.config == "config_a_hank":
        from evals.vals_finance_agent.harness.hank_model import get_custom_model
    else:
        from finance_agent.custom_model import get_custom_model
    custom_call = await get_custom_model(args.model, {"temperature": 0.0, "max_tokens": 32000})
    run = await suite.run(
        model=custom_call,
        model_name=args.config,
        run_name=args.run_name,
        parameters=RunParameters(eval_model="openai/gpt-5.2", heavyweight_factor=3),
        wait_for_completion=True,
    )
    save_run_to_json(run, args.output)
```

**`Suite.from_id` is pseudocode** — the actual API may be `Suite.get(id=...)` or similar. This is §6 Q1.

#### 4.5.4 `scripts/dry_run.sh`

Runs 3 questions end-to-end against a tiny local suite (created from first 3 rows of `public.csv`) with the stub judge. Used Day 1-2 before VALS_API_KEY lands.

#### 4.5.5 `scripts/aggregate_results.py`

Reads `results/<ts>/config_a/run.json` + `results/<ts>/config_b/run.json` + both `traces.jsonl` files. Emits `results/<ts>/summary.md` (human) + `summary.json` (machine) with slices described in §3.4.4.

### 4.6 Documentation + README

#### 4.6.1 `evals/vals-finance-agent/README.md`

~2 pages covering:
- What this is + link back to `docs/planning/VALS_FINANCE_AGENT_RUN_PLAN.md` + this plan.
- Required env vars (link to `.env.example`).
- `make install` (venv + vendor install).
- How to dry-run.
- How to run Config A, Config B.
- How to read results.
- Known gotchas (DATABASE_URL unset, VALS_API_KEY gated, etc.).

#### 4.6.2 `evals/vals-finance-agent/.env.example`

Full list of required env vars with placeholder values. NOT committed with real values — `.env.config_a`, `.env.config_b` are gitignored.

---

## 5. Validation plan

### 5.1 Unit-level (Day 1 afternoon — before full run)

- [ ] `pytest evals/vals-finance-agent/tests/test_hank_tools.py` — each Hank tool wrapper exec'd with a synthetic arg, ToolOutput shape validated.
- [ ] `pytest evals/vals-finance-agent/tests/test_trace_logger.py` — AgentResult fixture → JSONL row, schema conforms to §3.4.3.
- [ ] `scripts/dry_run.sh` — 3 questions via stub judge, Config A + Config B complete without errors.

### 5.2 Config B fidelity (Day 3, before Config A) — REVISED r3

Per Codex should-fix #6: ±3pp on n=50 is too brittle for a hard halt (single 50-question run has σ ≈ 7pp noise). r3 softens from "halt" to "rerun signal":

- [ ] Run Config B on all 50 public questions.
- [ ] **Preferred:** re-run Config B a second time same-day to measure run-to-run variance. If 2 runs each ≥60% and within 3pp of each other AND their mean is within ±5pp of 64.4% → proceed to Config A.
- [ ] **Fast-path:** if single run scores within ±3pp of 64.4%, proceed (variance still recommended but optional).
- [ ] **Out-of-band (single-run >5pp from 64.4%):** **rerun Config B** (don't halt). If the second run is also out-of-band, debug per §3.3.3 before proceeding.
- [ ] **Clearly invalid (<50% or >80%):** halt and debug. Something's broken in the harness.
- [ ] Record run(s), commit SHA, model snapshot, judge config per run-log discipline (§3.6.2).

### 5.3 Config A validation (Day 3, after Config B passes fidelity)

- [ ] Run Config A on all 50 questions.
- [ ] Confirm 0 Hank-wrapper exceptions in `traces.jsonl` (all `final_error` entries = null OR are `MaxTurnsExceeded` only).
- [ ] Confirm `tool_usage` shows Hank tools being used (non-zero) — otherwise the wrapper isn't being exercised.
- [ ] Confirm `HankSubmitFinalResult` is emitting the "missing sources" rejection path on ≤10% of submissions (if >10%, the citation check may be too strict — see §6 Q8).

### 5.4 Head-to-head analysis (Day 4)

Per sprint plan §4 Day 4:
- [ ] Diff Config A vs Config B answers per question_id.
- [ ] Categorize each miss per failure taxonomy (retrieval, tool-use, reasoning, numerical, hallucination, ambiguous gold, citation refusal).
- [ ] Cross-config head-to-head table — where did wrapper help/hurt?
- [ ] Apply threshold-tier decision from sprint plan §3.4.

### 5.5 Reproducibility audit (Day 5)

- [ ] `git ls-files evals/vals-finance-agent/` shows exactly the expected files (no secrets leaked).
- [ ] `vendor/finance-agent/VERSION` file records pinned commit SHA.
- [ ] `configs/config_a_hank.py` + `configs/config_b_raw_opus.py` exist + pin all tunables.
- [ ] A second engineer can `make install && scripts/run_config_b.sh` (given their own keys) and reproduce Config B score within 3pp.

---

## 6. Open questions for Codex review

**These are explicit flags — do not hand-wave. Codex should push on any of these that affect the plan's validity.**

### Q1. Vals SDK test-suite entry point

**What I know:** `get_custom_model` signature verbatim from `custom_model.py:18-49`. Vals docs (web-fetched) confirm `Suite.run(model=...)` pattern. **What I don't know:** exact API to load a suite by ID. Pseudocode in §4.5.3 uses `Suite.from_id(args.suite_id)` which is a guess. Real API could be `Suite.get(suite_id)`, `Suite.load(suite_id)`, or require fetching via `vals.client.get_suite(...)`.

**Impact if wrong:** §4.5.3 `run_vals_suite.py` is stub-broken until resolved.

**Resolution path:** Day 1 after VALS_API_KEY lands — `python -c "from vals.sdk import suite; help(suite)"`. Before then, implement under `# TODO(Vals-API-shape)` comments.

### Q2. Single loop vs nested Hank loop

**I chose single loop (harness-driven) in §3.2.2.** Tradeoffs:
- **Single loop (chosen):** harness handles retries/truncation/logging; Hank tools are peer to native tools. Simpler. But Hank's agent-format flags (the 3-layer snapshot+flags pattern from Memory) are wasted — the harness agent doesn't know how to consume them.
- **Nested loop:** wrap an entire Hank agent (our own system prompt + planning) inside a single "ask Hank" tool that takes the question, internally loops 5-10 times, returns an answer. Presents as one turn to the harness. More code, more flexibility, but breaks the judge's "show your work" expectation (the harness only sees the one giant turn).

**Recommend Codex confirm: single loop is right for benchmark purposes.** Nested loop is a second experiment, not v1.

### Q3. Hank tool selection — RESOLVED r4

Per Codex r2 review: ~30 tools was too many AND contained mischaracterized tools (`get_factor_analysis`, `analyze_option_chain` required live IBKR, `get_quote` was plural not singular).

**r4 resolution: curated v1 core of 20 Hank tools + 5 native = 25 tool classes.** See §3.2.3:
- 9 edgar-financials (all) — direct import from `Edgar_updater/mcp_server.py`
- 8 FMP analytical (via §3.2.4.C direct-import from `fmp.server` — NOT registry-backed)
- 2 registry-backed: `get_quote` (display name `hank_get_quotes`, takes plural `tickers` list), `analyze_stock` (display name `hank_stock_risk_analysis`, for beta/volatility)
- 1 code-exec
- 4 harness-native retained + HankSubmit (warn, not block per Q8)

**Modeling studio deferred from v1 per r4 §3.2.8** — re-add when MBC track ships.

Dropped entirely: `get_factor_analysis`, `analyze_option_chain`, `analyze_option_strategy` (Codex blocker #4 from r2). Also dropped `hank_fmp_fetch`, `model_clear_cache`, `annotate_model_with_research`, `get_insider_trades`, `get_institutional_ownership`, `get_technical_analysis` — low-yield for filing Q&A; add in iteration if Week 2+ analysis surfaces specific gaps.

**Headroom preserved.** Starting curated rather than saturated.

### Q4. user_email handling

Hank MCP tools routinely take `user_email` and look up portfolio state. For benchmark runs there is no user. Two approaches:
- (a) Pass a **synthetic benchmark user** (`hank-bench@internal.local`) with an empty portfolio but valid row in DB. Pro: all tools work. Con: DB setup step for benchmark.
- (b) Pass `user_email=None` and rely on tools' no-user fallback paths. Pro: no DB. Con: some tools may error (need audit).

**Recommend Codex opinion.** Option (b) seems cleaner if the tools tolerate it. Needs a 20-minute audit of `mcp_tools/stock.py`, `mcp_tools/news_events.py`, `mcp_tools/metric_insights.py` to confirm.

### Q5. Exact Opus 4.7 model snapshot

Anthropic's published 64.4% number cites "Claude Opus 4.7". The Vals model registry routes `anthropic/claude-opus-4-7` to a specific snapshot in `model_library/config/all_models.json`. We need the exact snapshot string (e.g. `claude-opus-4-7-20260401`) and must pin it in both configs.

**Resolution path:** Day 1 — `python -c "from model_library.registry_utils import get_registry_model; ..."` to inspect, or grep `model-library` repo.

### Q6. Question categorization + filing-type tagging

`public.csv` has a `Question Type` column (9 categories). We can slice by that. But sprint plan §4 Day 3 also wants "by filing type" (10-K / 10-Q / 8-K / proxy / transcript). `public.csv` does NOT have this column.

**Options:**
- (a) Infer from question text via regex (`10-K`, `FY 2024`, `Q1 2024`, etc.) — noisy.
- (b) Tag manually — 50 questions, ~1 hour.
- (c) Drop filing-type slice for this sprint; category slice suffices.

**Recommend Codex opinion.** I lean (b) — tagging cost is low and the analysis value is high.

### Q7. Hank system prompt content

§4.2.2 has a draft prompt. Codex review: is the voice rule appropriate for a benchmark (might cause the judge to penalize overly assertive answers)? Is the citation-refusal rule too strict (we might refuse correct answers we can't cite)? Is the tool-selection guidance too prescriptive (robs the model of chain-of-thought flexibility)?

### Q8. Citation discipline enforcement — RESOLVED r4 (warn, not block)

Per r4 §4.2.3: `HankSubmitFinalResult` warns (doesn't block) on missing `"sources"` dict. First submission without sources is accepted; warning recorded in trace for failure analysis. Rationale: hard-block risks `max_turns=0` failures when model forgets format; warn preserves the discipline signal without sabotaging correct-but-unformatted answers.

**Open for iteration:** if v1 analysis shows citation-format failures are rare, switch to hard-block in Week 2+ iteration.

### Q9. Tavily / SEC-API rate limits + concurrency

Parallelism default is `--parallelism 5` in the scripts. 5 concurrent questions × 10 tool calls each = up to 50 concurrent API calls. Tavily free tier may throttle; sec-api.io tiering unknown.

**Resolution path:** Day 1 — hit rate limits with `parallelism=5` dry run; adjust down or pay for higher tier if needed.

### Q10. Trace logger timing — where in AgentResult lifecycle

`trace_logger.write(result, ...)` is called after `agent.run(...)` returns. But if we want mid-run telemetry (e.g. flagged a tool error for alerting), we need to subscribe to the loop. Model-library has `AgentHooks`, but not a "per-turn callback" hook by default.

**Two options:**
- (a) Post-run logging only (simpler, what I proposed). Failure mode: if we crash mid-run we lose data. But harness already writes per-turn to `logs/` so we can reconstruct.
- (b) Add `AgentHooks` with per-turn callback (more work, richer live telemetry).

**Recommend Codex opinion.** I lean (a) — per-turn logs exist in vendor's dir already; our jsonl is a summary.

### Q11. What if Vals platform is down during the sprint window

Single-point-of-failure risk. Mitigation: use stub judge (§3.4.2) for Day 1-2, platform for Day 3+. If platform is still down Day 3, document and report *"Hank Config A on stub judge + Config B on stub judge"* instead of the real Vals number. This is a lesser story but not a blocker for failure-mode analysis.

**Recommend Codex opinion on fallback posture.**

### Q12. Modeling studio integration — DEFERRED r4

**Codex caught in r3:** `build_model_from_ticker` doesn't exist. Real orchestrator is `BuildModelOrchestrator.build_and_annotate(handoff_id, user_id)` requiring a finalized handoff + user context.

**r4 decision: defer from v1.** Reasons:
- Modeling studio ticker-only path requires either a synthetic-handoff shim (2-3 days of benchmark-specific glue) OR the `ModelBuildContext` (MBC) bridge from the schema-unification track (~22.5 engineering days, active on `feat/thesis-living-artifact-plan-1`).
- MBC track is actively in-flight. Wait for it rather than build throwaway glue.
- v1 routes financial_modeling questions to `hank_code_execution` instead (§3.2.8).

**Re-add trigger:** when MBC track ships `build_model_from_mbc(mbc)` + model-engine MCP tools accept `model_build_context_id`. Revise §3.2.8 to wrap those. Expected: Week 4-6 of iteration if MBC lands in time, else v1.5.

### Q13. Code execution — RESOLVED r3

Codex caught: r2 made hosted Anthropic beta the preferred default. But hosted beta is "not wired" in Hank; AI-excel-addin explicitly replaced hosted `code_execution_20260120` with local `code_execute`.

**r4 resolution** (§3.2.9): **local subprocess is the default.** Via AI-excel-addin's `agent_gateway.code_execution` package — uses `build_code_execution(backend, config)` factory with `SubprocessBackend` + `CodeExecutionConfig`. Hosted beta deferred to later optional spike.

**Attribution:** still acknowledged honestly in the writeup — *"Hank's full production architecture — including local code-execution subprocess — beats raw Opus on harness-native tools by X pp."* (Modeling studio deferred per r4 §3.2.8.) Config C (Config A minus code exec) can run as decomposition exercise in v1.5 if the delta story needs pure-wrapper attribution.

**r3 advantage over r2:** using same code-exec path as production means delta transfers 1:1 to production behavior.

**Day-1 verification:** confirm exact import path for the code-execution service in AI-excel-addin's module layout.

### Q14. Portfolio-tool noise with broad tool exposure — NEW r2

Per §3.2.3, we exclude portfolio-state tools entirely. But there's a legitimate alternative: include them with "no portfolio context" safeguards (let them return empty gracefully on no-user mode) and trust the agent to not call them on filing Q&A questions. This preserves the "test full Hank" philosophy but adds noise.

**Tradeoff:**
- Include: truly tests full Hank, but agent may waste 1-3 turns discovering portfolio tools return empty.
- Exclude: cleaner, fewer wasted turns, but slightly narrower-than-production Hank.

**Codex opinion requested.** I lean EXCLUDE for v1 (current plan), but flag as a future experiment.

### Q15. `analyze_stock` no-DB mode — RESOLVED r3 (with Day-1 verification gate)

**Resolution:** Day-1 smoke test is a hard prerequisite for Config A execution. Procedure:

```python
# Day 1, first Hank-tool smoke test (before Day 2 wrapper build):
from risk_module.agent.registry import get_registry
entry = get_registry()["analyze_stock"]
result = entry.callable(ticker="AAPL", user_email=None)
# Expected: agent-format envelope returned, no DB connection required, no side-effect writes.
```

**If passes:** proceed with registry-backed adapter for `analyze_stock` and all other FMP analytical tools (same pattern).

**If fails** (3 FMP tools is the high-risk subset per inventory):
- **Option (a):** targeted fixes in the FMP tool source — let FMP analytical tools tolerate `user_email=None` cleanly. Estimate: 1-2 days. This is real Hank architecture work (benefits production too), not score-gaming.
- **Option (b):** synthetic-user DB row at start of Config A run — creates `hank-bench@internal.local` with empty portfolio, drops at run end. Cleaner isolation than no-DB mode but requires DB provisioning.
- **Decision default:** Option (a). Cleaner, no DB coupling, benefits production Hank.

Beyond `analyze_stock` (registry-backed), Day-1 smoke tests cover: `fmp_profile`, `get_stock_fundamentals`, `get_earnings_transcript`, `compare_peers`, `get_market_context`, `get_events_calendar`, `get_news`, `get_sector_overview` (all via `fmp.server` direct-import), and `get_quote` (registry). All 10 FMP+registry tools verified before Day 2 wrapper build.

### Q16. Agent registry `_unwrap()` and `BLOCKED_PARAMS` — RESOLVED r3

**Codex clarified** via direct code read: `_unwrap` (`registry.py:70-72`) is a **one-level `__wrapped__` peel**, NOT a recursive full unwrap. However, **the registry already stores the unwrapped callable** via `_register` (line 75-90 — calls `_unwrap` at registration time). So:

- `entry.callable` in `AgentFunction` is ALREADY unwrapped. Wrapper code should use `entry.callable` directly, not call `_unwrap` again.
- `BLOCKED_PARAMS` (`registry.py:35`) defines safe-default overrides that the wrapper MUST apply: `{"backfill_path": None, "output": "inline", "debug_inference": False}`.

**r3 adapter code** (§3.2.4.A) handles both correctly:
```python
entry = _registry[registered_name]
raw_fn = entry.callable  # already unwrapped; use directly
# Merge args with BLOCKED_PARAMS + user_email default; filter to accepted kwargs.
merged = {**args, **auto_user_email, **BLOCKED_PARAMS}
filtered = {k: v for k, v in merged.items() if k in inspect.signature(raw_fn).parameters}
```

**No further Day-1 audit needed** beyond the smoke tests in Q15.

**Edge case noted:** if a future registry entry has decorators like `@log_error_handling` that `_unwrap`'s single peel doesn't penetrate, the adapter will see the wrapped version. Mitigation: smoke tests in Q15 will surface any tool returning unexpected error envelopes. Fix in the tool source if surfaced.

---

## 7. Timeline — REVISED r2

**Framing change (2026-04-20):** Week 1 is the sprint (baseline + first iteration wave). Weeks 2-8 are architectural iteration with weekly reruns. Week 8 = decision gate per sprint plan §3.4 (revised). Stretch to Week 12 if score plateaus in 88-92% band with a credible hypothesis for closing the gap.

### Week 1 — Sprint (baseline + initial iteration)

**Day 0 (pre-sprint):**
- [ ] Kick off Vals platform registration (can take days).
- [ ] Procure: Anthropic key, Tavily key, SEC-API key (FMP already available).
- [ ] Confirm `agent_gateway.code_execution` package imports successfully from AI-excel-addin install (§3.2.9 local subprocess path, r4 default).

**Day 1 — Environment + vendor setup (~6 hours):**
- [ ] Create `evals/vals-finance-agent/` tree per §4 layout.
- [ ] Clone harness at pinned SHA into `vendor/finance-agent/`.
- [ ] `make install` (uv venv, sync).
- [ ] Raw-harness smoke test.
- [ ] Write `configs/config_b_raw_opus.py` (§4.3.1).
- [ ] Resolve §6 Q1 (Suite.from_id API), §6 Q5 (exact model snapshot), §6 Q15 (analyze_stock no-DB live-verify), §6 Q16 (_unwrap behavior audit).

**Day 2 — Hank wrapper skeleton + Edgar adapters (~1 day, narrowed per r4):**
- [ ] Write `harness/hank_tool_specs.py` — 20 spec entries with real parameters + descriptions (per §4.2.3).
- [ ] Write `harness/hank_tools_edgar.py` — 9 edgar adapters + `_build_edgar_adapter` factory (§3.2.4.B).
- [ ] Write `harness/hank_tools_registry.py` — skeleton + `_build_registry_adapter` factory (§3.2.4.A). Populate once Q15 smoke tests pass.
- [ ] Write `harness/hank_model.py` — `get_custom_model` implementation.
- [ ] Write `harness/trace_logger.py`.
- [ ] Dry-run 3 Edgar-only questions Config B with stub judge — harness integration sanity check.
- [ ] **~50% of tool description authoring** (edgar + code-exec + submit).

**Day 3 — FMP direct-import adapters + full wrapper + dry-run (~1 day):**
- [ ] Build `harness/hank_tools_fmp.py` — 8 FMP direct-import adapters (Q15 smoke tests first).
- [ ] Populate `harness/hank_tools_registry.py` with 2 registry-backed adapters (`get_quote`, `analyze_stock`).
- [ ] (Modeling studio deferred per r4 §3.2.8 — no model adapter module built in v1 sprint.)
- [ ] Write `harness/hank_code_execution.py` (§3.2.9 local subprocess wrapper).
- [ ] Write `harness/hank_submit.py` (warn-not-block).
- [ ] Write `harness/scoring_stub.py` + `scripts/dry_run.sh`.
- [ ] Dry-run 3 questions full Config A + Config B with stub judge. Fix errors.
- [ ] **Remaining ~50% of tool description authoring** (FMP + registry).
- [ ] Resolve §6 Q4 (user_email handling — largely pre-resolved by Q15 smoke tests).

**Day 4 — First full baseline runs (~4 hours compute + review):**
- [ ] Run Config B full 50 **twice** (variance measurement per §5.2 r3). Confirm in-band per softened fidelity check.
- [ ] Run Config A full 50 — **baseline**, not publish candidate.
- [ ] `scripts/aggregate_results.py` → `summary.md`.

**Day 5 — Baseline failure-mode analysis (~1 day):**
- [ ] Categorize misses per failure taxonomy (retrieval, tool-use, reasoning, numerical, hallucination, refusal, ambiguous).
- [ ] Head-to-head: questions where Config A and B diverge — extract patterns.
- [ ] **Architectural gap list** — top 5-10 specific, actionable architectural changes that would close visible failures.
- [ ] Initialize `results/<run_ts>/run_log.md` per §3.6.2.
- [ ] Write initial `docs/research/vals-finance-agent-baseline.md` — baseline score, failure analysis, gap list.
- [ ] Commit `evals/vals-finance-agent/` tree.
- [ ] Prioritize gap list → Week 2 architectural work.
- [ ] Founder readout: baseline number + iteration plan.

### Weeks 2-4 — First iteration wave (low-hanging fruit)

Expected gains: largest pp movement of the iteration period. Typical fixes:
- Missing tools identified from Day 4 gap list
- Tool description sharpening (agent picks wrong tool for a class of questions)
- Prompt routing clarifications
- Corpus backfill (Edgar_updater missing filings)

**Each week ends with:**
- [ ] Config A rerun (architectural changes applied)
- [ ] Config B rerun (baseline drift check)
- [ ] `run_log.md` update with delta-from-previous-run
- [ ] Score trajectory tracked against 92% target

### Week 4-5 — Vals AI licensing engagement begins

- [ ] Initiate conversation with Vals AI for private 337 test access.
- [ ] Run in parallel with continued architecture iteration.
- [ ] Licensing timeline estimated 2-4 weeks.

### Weeks 5-7 — Second iteration wave (harder gaps)

Diminishing returns kick in. Expected fixes:
- Tool orchestration issues (agent routes between tools suboptimally on multi-step questions)
- Code execution quality (Python snippets need better structure for complex calculations)
- Citation discipline calibration (§6 Q8 — warn vs block)

**Per week:** same cadence as Weeks 2-4 (Config A + B rerun, run_log, trajectory check).

### Week N — Modeling studio integration (CONDITIONAL, if MBC ships)

Deferred from v1 Day 1 per §3.2.8. Triggered when MBC track delivers `build_model_from_mbc(mbc)` + model-engine MCP tool support for `model_build_context_id`.

**Trigger preconditions:**
- MBC track merged (per `MODEL_BUILD_CONTEXT_PLAN.md` sub-phase G)
- `build_model_from_mbc(mbc)` importable + smoke-tested
- MCP tools (`model_summarize`, `model_find`, `model_values`, `model_scenario`) verified to take `file_path` + `item_ids` per Codex-verified signatures
- A benchmark-side synthetic-MBC constructor built (takes ticker, derives defaults)

**Integration steps:**
- [ ] Build `harness/hank_tools_model.py` — 5 model-engine adapters (`hank_model_build` + 4 extraction tools).
- [ ] Build `harness/hank_model_build_adapter.py` — synthetic-MBC from ticker for benchmark use.
- [ ] Update `HANK_TOOL_SPECS` table (§4.2.3) to include model-engine source. Tool count: 25 → 30.
- [ ] Update system prompt (§4.2.2) to route financial_modeling questions through `hank_model_build` → `hank_model_summarize` → `hank_model_values` workflow.
- [ ] Fresh Config A + Config B rerun to isolate the modeling-studio delta.

**Expected impact:**
- 4 of 50 questions target (Q12, Q30, Q31, Q43 — the "Financial Modeling / Projections" category).
- Realistic upside: 2-4pp on total Config A score.
- Best case: all 4 flip from miss to pass = +8pp. Unlikely but possible.

**Attribution:** delta = (Week-N Config A score) − (pre-integration Config A score). Directly measures the modeling studio contribution. Document in run_log as a named architectural milestone.

**If MBC doesn't ship before Week 8:** defer modeling studio integration entirely from v1; revisit in v1.5. Non-blocking for the primary publish decision.

### Week 8 — Decision gate

- [ ] Config A + B final rerun.
- [ ] Apply sprint plan §3.4 (revised) thresholds → publish / extend / hold decision.
- [ ] If publishing: publish methodology writeup + run history + failure analysis + architecture description.
- [ ] If extending: 4-week extension with specific architectural hypothesis; reassess Week 12.
- [ ] If holding: deeper rework plan; sequence Vals Finance Agent rerun after that work stabilizes.

### Weeks 9-12 (conditional) — Extended iteration or private 337 prep

- If publish triggered at Week 8: engage Vals AI private 337, run when access lands, publish confirmation number.
- If extension triggered: hypothesis-driven architecture work, Week 12 final decision gate.
- If hold triggered: treat Vals Finance Agent as paused; sequence after the deeper rework completes.

### Non-benchmark regression cadence

Per §3.6.5: after each weekly architectural change batch, run non-benchmark regression tests (existing scenario tool tests, smoke tests, dogfood checks). Budget: ~2 hours/week. If regressions appear, revert.

---

## 8. Glossary (quick reference for reviewers)

- **Harness** = `vals-ai/finance-agent` repo, the Vals-provided test runner.
- **Vendor** = our pinned copy of the harness at `evals/vals-finance-agent/vendor/finance-agent/`.
- **Config A** = Hank wrapper (r4 — modeling studio DEFERRED). Hank prompt + 20 Hank tools (9 edgar + 8 FMP + 2 registry + 1 code-exec) + 4 native + Hank submit = 25 tool classes. Opus 4.7.
- **Config B** = raw Opus 4.7, harness defaults only. Reproduces Anthropic's 64.4%.
- **Judge** = GPT-5.2 via Vals-platform-hosted scoring. Mode-of-3.
- **Suite** = Vals-platform object wrapping the 50 public questions + rubrics + eval config.
- **`custom_call`** = Vals SDK's per-question callback that returns `OutputObject`.
- **`OutputObject`** = Vals SDK type; `from_agent_result(AgentResult)` is the common constructor.
- **`AgentResult`** = `model_library.agent.AgentResult`; has `final_answer` (string), `turns`, `stop_reason`, etc.

---

## 9. Next steps after this plan is approved

1. Codex review → iterate to PASS.
2. Codex implementation per file-by-file §4.
3. Execute per §7 timeline.
4. Deliverables per §1.

*End of plan.*
