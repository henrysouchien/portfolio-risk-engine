# V2.P10 — Research MCP Server Split

**Status:** SCOPED 2026-05-02 — implementation pending
**Trigger:** Surfaced during V2.P2 Slice C.2 live testing — citation discipline machinery (Slices A+B+C+C.1+C.2) all shipped, but routinely fails to fire because corpus tools live in deferred-tier `portfolio-mcp` server.
**Effort:** ~1-2 weeks for full split; ~2-3 days for quick-win subset
**Cross-repo:** AI-excel-addin (gateway, MCP catalog, channel tiers) + risk_module (mcp_tools/ source) + agent-gateway-dist (PyPI publish)

---

## Why now

Across today's Slice C.2 testing + the F56 fix history, a clear pattern emerged: **the corpus tools' "deferred-tier" status is the bottleneck for citation discipline**, and stacking workarounds (F56 auto-load, prompt nudges, C.4) treats the symptom rather than the architectural cause.

**Symptom stack tracing back to one root cause:**

| Symptom | Workaround | What it really wants |
|---|---|---|
| Hank routes corpus queries to `get_filings` (edgar-financials) instead of `filings_search` (portfolio-mcp) | F56 auto-load + tool description rewrites | corpus tools always-loaded |
| F56 doesn't fire in TUI because it requires `mode=research` flag the TUI doesn't pass | **F59** (would file: TUI mode flag fix) | corpus tools always-loaded |
| Slice A's citation envelope only fires for portfolio-mcp tools, not edgar-financials | **C.4** (cross-MCP citation discipline) | corpus tools always-loaded with envelope contract universal |
| F58 (entity resolution): BM25 misses euphemistic disclosures — needs query-expansion logic | F58 fix paths | unrelated (real corpus search gap) |
| F57 (universe alias gap): GOOG/GOOGL share-class aliasing | F57 fix | unrelated (universe selection gap) |

**Three of those four wants the same thing**: corpus tools should be in the always-tier so the LLM picks them by default. The current architecture co-locates corpus tools with portfolio-management tools in `portfolio-mcp`, forcing the entire server into deferred-tier (because portfolio-management tools are large, expensive, mutating, and shouldn't all be loaded by default). The corpus tools — small, narrative, read-only — get pulled into deferred-tier as collateral damage.

**The architectural correction**: separate corpus tools (and other research-workflow tools currently in portfolio-mcp) into their own MCP server. Make that server always-tier across all channels. Eliminate the workarounds.

---

## Current state — `portfolio-mcp` is a catch-all

`portfolio-mcp` currently serves ~120 tools spanning multiple concerns. Inventory by category:

### Should stay in `portfolio-mcp`

These mutate portfolio state, affect external systems, or carry high token-cost schemas — defer-tier is correct:

- **Portfolio mgmt**: create_portfolio, list_portfolios, list_accounts, account_activate, account_deactivate, list_baskets, get_basket, create_basket, update_basket, delete_basket, create_basket_from_etf
- **Risk analysis**: get_risk_analysis, get_risk_profile, get_risk_score, set_risk_profile, run_stress_test, run_optimization, run_monte_carlo, run_whatif, run_backtest, get_efficient_frontier, get_factor_analysis, get_factor_recommendations, manage_qualitative_factor, manage_stress_scenarios
- **Trading**: preview_trade, execute_trade, cancel_order, get_orders, preview_basket_trade, execute_basket_trade, preview_option_trade, execute_option_trade, preview_rebalance_trades, preview_futures_roll, execute_futures_roll, preview_patch_ops, apply_patch_ops, suggest_tax_loss_harvest
- **Position mgmt**: get_positions, get_quote, get_performance, get_income_projection, get_leverage_capacity, get_target_allocation, set_target_allocation, get_allocation_presets, monitor_hedge_positions, check_exit_signals
- **Brokerage**: initiate_brokerage_connection, complete_brokerage_connection, list_supported_brokerages, list_connections, manage_brokerage_routing, fetch_provider_transactions, refresh_transactions, wait_for_sync, list_transactions, inspect_transactions, transaction_coverage, list_flow_events, list_income_events
- **Document ingest** (portfolio-side): import_portfolio, delete_portfolio, update_portfolio_accounts, import_transaction_file, manage_instrument_config, manage_ticker_config, manage_proxy_cache, list_ingestion_batches
- **Stock/option/futures analysis**: analyze_stock, analyze_option_chain, analyze_option_strategy, analyze_basket, get_futures_curve, industry_peer_comparison, compare_scenarios, get_trading_analysis, get_price_target

### Should move to `research-mcp` (NEW)

Read-only, narrative, low token cost, foundational for V2.P2 citation discipline:

- **Corpus search** (V2.P1): filings_search, transcripts_search, filings_list, transcripts_list, filings_read, transcripts_read, filings_source_excerpt, transcripts_source_excerpt
- **Research workflow**: get_research_brief, list_research_files, list_research_files, list_ingestion_batches, ingest_document, load_document, read_research_thread, start_research, get_mcp_context, get_model_build_context, get_model_insights
- **Diligence flow**: activate_diligence, get_diligence_state, prepopulate_diligence, update_diligence_section
- **Process templates**: get_process_template, list_process_templates, set_process_template
- **Thesis tracking**: thesis_create, thesis_list, thesis_read, thesis_run_scorecard, thesis_latest_scorecard, thesis_update_section, thesis_upsert_link, thesis_remove_link, thesis_list_links, thesis_append_decisions_log, thesis_list_decisions_log
- **Editorial / annotations**: create_annotation, update_action_status, get_action_history, record_workflow_action, update_editorial_memory
- **Handoff artifacts**: get_handoff, finalize_handoff, new_handoff_version
- **News / events** (research-flavored): get_portfolio_news, get_portfolio_events_calendar, export_holdings
- **Universe normalizer** (research-side ingest): normalizer_activate, normalizer_list, normalizer_sample_csv, normalizer_stage, normalizer_test
- **Build model** (could split — model build orchestration uses research data): build_model

### Honest categorization tension

Some tools straddle (e.g., `analyze_stock` reads research data but produces analysis output). Two options:

1. **Strict split** — every tool lives in exactly one server based on dominant concern. Some judgment calls; expect ambiguity around `analyze_stock`, `compare_scenarios`, `industry_peer_comparison`.
2. **Cross-listing** — a tool can be advertised in both servers if it serves both surfaces. Higher token cost (schema duplicated) but no wrong answers for ambiguous tools.

**Lean strict split.** Token cost matters; ambiguous tools go to whichever server is most-used by their typical caller pattern. Bias toward research-mcp for read-only tools that surface data the citation envelope can attach to.

---

## Target architecture

### Three MCP servers (instead of two)

| Server | Tier | Purpose |
|---|---|---|
| **portfolio-mcp** | defer | Portfolio mgmt + risk + trading + brokerage + position mgmt. ~80 tools after split. |
| **research-mcp** (NEW) | **always** | Corpus + research workflow + diligence + thesis + editorial + process templates. ~40 tools. |
| **edgar-financials, fmp-mcp, model-engine** | unchanged | External data + modeling. |

### CHANNEL_TIERS update (per `tool_catalog.py:39-58`)

```python
CHANNEL_TIERS: Dict[Optional[str], Dict[str, Set[str]]] = {
  None: {  # Excel add-in
    "always": {"model-engine", "edgar-financials", "research-mcp"},  # ADD research-mcp
    "defer": {"portfolio-mcp", "fmp-mcp", "roam-research", "drive-mcp", ...},
  },
  "web": {
    "always": {"fmp-mcp", "edgar-financials", "research-mcp"},  # ADD research-mcp
    "defer": {"model-engine", "portfolio-mcp", ...},
  },
  "telegram": {
    "always": {"fmp-mcp", "edgar-financials", "research-mcp"},  # ADD research-mcp
    "defer": {"model-engine", "portfolio-mcp", ...},
  },
  "cli": {
    "always": {"fmp-mcp", "edgar-financials", "research-mcp"},  # ADD research-mcp
    "defer": {"model-engine", "portfolio-mcp", ...},
  },
}
```

Result: corpus tools (and the rest of research-mcp) are universally always-loaded. F56 auto-load no longer needed; F59 (TUI mode flag) becomes moot; C.4 (cross-MCP citation discipline) becomes optional.

### Token cost analysis

`research-mcp`'s ~40 tools should add roughly:
- ~40 tools × ~250 tokens per tool schema = ~10,000 tokens added to system prompt always-loaded
- That's a 1-time cache write per session; cached on subsequent turns
- Anthropic's prompt caching makes this near-free after first turn

Compare to the cost of having Hank skip corpus tools (citation envelope never fires → analyst-grade output without citations → V2.P2 product value lost).

**Token cost of always-loading research-mcp is acceptable. The cost of NOT always-loading it is V2.P2 product value being unreliable.**

### Slice A citation envelope contract

Slice A's `source_envelope` extractors are tied to specific tool names (`filings_search`, `transcripts_search`, `filings_list`, `transcripts_list` from portfolio-mcp). After the split, these tools live in research-mcp.

**Two options:**
1. **Update extractors** to look for the same tool names regardless of server prefix. Slice A's extractor logic is keyed by tool name (per the implementation), so this should be a no-op if the renaming preserves names.
2. **Re-prefix tools** as `research-mcp__filings_search` etc. and update extractors to match.

Lean **option 1** — preserve tool names, update server hosting. The MCP protocol has tool names; the server prefix is implementation detail.

---

## Migration plan

Phased rollout to minimize risk:

### Phase 1 — Stand up `research-mcp` server (parallel to portfolio-mcp)

- Create new MCP server at `mcp_tools/research_mcp/` (or wherever the source lives)
- Move **just the 8 corpus tools** initially (filings_search, transcripts_search, filings_list, transcripts_list, filings_read, transcripts_read, filings_source_excerpt, transcripts_source_excerpt)
- Register in `CHANNEL_TIERS` always-tier across all channels
- portfolio-mcp keeps the same tools registered (cross-listed) for back-compat during transition
- Deploy + verify both surfaces work

**Validation:** Hank in TUI without `mode=research` flag should now have corpus tools in always-tier; citation envelope should fire on default queries.

### Phase 2 — Move research workflow tools

- Move research workflow tools (get_research_brief, list_research_files, ingest_document, load_document, read_research_thread, start_research, etc.)
- Move diligence flow tools (activate_diligence, get_diligence_state, prepopulate_diligence, update_diligence_section)
- Move process templates + thesis tracking
- Update consumers (gateway, agent registry, dev CLI tooling)
- Remove cross-listing from portfolio-mcp

**Validation:** Existing flows still work end-to-end. No regression in any V2.P9 plan tests.

### Phase 3 — Backwards compatibility

- Old code referencing `mcp__portfolio-mcp__filings_search` should keep working — server-name aliases at the gateway dispatcher level
- Deprecation warnings for old prefixes, soft-fail to new prefix
- Document the new namespace prefix in user-facing docs

**Validation:** Search for all `mcp__portfolio-mcp__filings_*` and `mcp__portfolio-mcp__transcripts_*` references across all repos; verify all still work post-split.

### Phase 4 — Documentation + ecosystem cleanup

- Update CLAUDE.md, AGENTS.md, README.md references
- Update docs in `docs/planning/CORPUS_ARCHITECTURE.md` — corpus tools now in research-mcp
- Update docs in `docs/planning/V2_P2_*` plans — citation envelope source server
- File deferred items: F56 (auto-load) → can be retired; F59 (TUI mode) → moot; C.4 (cross-MCP citations) → optional now

---

## Quick-win alternative — Phase 1 only

If the full split is too much scope, Phase 1 alone (just the 8 corpus tools to `research-mcp`, leave the rest in portfolio-mcp) delivers most of the V2.P2 win:

- Citation envelope tools always-loaded
- LLM picks them by default
- F56 / F59 / C.4 workarounds unblocked
- ~2-3 days vs 1-2 weeks
- Lower risk

Tradeoff: research workflow + diligence + thesis tools stay in portfolio-mcp's deferred tier. Their use cases are less hot than corpus search; the deferral cost is acceptable for the foreseeable future. Phase 2-4 can come later if/when the same routing pattern surfaces for those tools.

**Lean quick-win for ship.** Full split is the long-term right answer but Phase 1 captures 80% of the value at 20% of the cost.

---

## Backwards compatibility

### What might break

- **Code referencing `mcp__portfolio-mcp__filings_search`** etc. across all consumers (gateway dispatcher, agent registry, tests, docs)
- **MCP client connections** — clients connect to `portfolio-mcp` by name; new `research-mcp` requires explicit registration in MCP config files
- **Tool dispatcher routing** — the gateway maps tool names to server connections; needs the alias layer
- **Tests** — search across the codebase for `portfolio-mcp` namespace references; ~50-100 sites

### Mitigation

- **Server-name aliasing** at gateway dispatcher level — old prefix still routes, deprecation warning logged
- **Migration script** to update tool registrations and config files
- **Pre-deploy grep** to find any missed references before publishing

### What can't break (load-bearing)

- Citation envelope contract (Slice A schema) — must preserve `source_envelope` block shape
- Slice A extractor logic — must continue to fire on the 4 corpus tools regardless of server hosting them
- Agent registry tool definitions — names + categories preserved

---

## Risk register

| Risk | Severity | Mitigation |
|---|---|---|
| Token cost of always-loading research-mcp inflates input cost | Medium | Anthropic prompt caching; expected ~10K tokens added per session, cached after first turn |
| MCP server-name aliasing breaks edge cases | Medium | Phase 3 explicitly handles back-compat; deprecation warnings; pre-deploy grep |
| Slice A extractor breaks on tool-name resolution | Low | Slice A keys by tool name not server name; tool names preserved across move |
| Existing V2.P9 tests reference old server names | Low | Find-and-replace with deprecation alias support |
| External consumers (e.g., Cursor, custom agents) reference `mcp__portfolio-mcp__` | Low | Document migration in release notes; alias layer keeps them working |
| New `research-mcp` server adds operational complexity | Low | Same boilerplate as portfolio-mcp; can reuse most infrastructure |

---

## Out of scope

- Migrating other MCP servers (edgar-financials, fmp-mcp) — those are external; not our concern
- Re-architecting the MCP protocol or tool catalog format — only changing server categorization
- Adding new tools — pure refactor of existing tool homes
- Changing tool implementations — only their server-of-residence

---

## Acceptance

### Phase 1 (quick win)

1. New `research-mcp` server stands up + registers in CHANNEL_TIERS always-tier across all channels
2. 8 corpus tools (filings_*, transcripts_*) accessible via both `mcp__portfolio-mcp__` (back-compat) and `mcp__research-mcp__` (new)
3. TUI test (no `mode=research` flag, no prompt nudge): natural-language corpus query produces `[Sn]` citations + Sources footer
4. F56 auto-load can be retired (or kept as belt-and-suspenders); F59 (TUI mode flag) no longer needed
5. Existing V2.P2 + V2.P9 tests pass

### Full split (Phase 2-4)

6. portfolio-mcp shrinks to ~80 tools (portfolio mgmt + risk + trading)
7. research-mcp grows to ~40 tools (corpus + research workflow + diligence + thesis + editorial)
8. All cross-listings removed; portfolio-mcp no longer advertises research tools
9. Docs sweep complete (CORPUS_ARCHITECTURE.md, V2_P2_*.md, CLAUDE.md, AGENTS.md, README.md)
10. F56 + F59 + C.4 follow-ups closed as moot

---

## What this enables

- **V2.P2 reaches its target audience** — citation discipline is the default, not an opt-in
- **Future research tools** (any new corpus surface, transcript layer, deck integration) inherit always-tier by default
- **F56/F59/C.4 retire** — the workaround stack collapses
- **Cleaner mental model** — portfolio-mcp = portfolio operations; research-mcp = research workflow
- **Path forward for other categorization corrections** — if `model-engine` should split, or `fmp-mcp` should split, the precedent is set

---

## Files this plan would touch (preview)

### risk_module
- `mcp_tools/corpus/` → `mcp_tools/research/` (or new sibling `mcp_tools/research_mcp/`)
- `mcp_server.py` — server registration, tool advertisement
- `agent/registry.py:1500-1507` — corpus tool category (already research)
- `docs/planning/CORPUS_ARCHITECTURE.md` — server name updates
- `docs/planning/V2_P2_CITATION_FIRST_QA_PLAN.md` — server name updates
- `docs/planning/V2_P10_RESEARCH_MCP_SPLIT_PLAN.md` — this file (status updates as phases ship)

### AI-excel-addin
- `api/agent/shared/tool_catalog.py:39-58` — CHANNEL_TIERS update
- `api/agent/shared/server_policies.py` — registered tool list update
- `api/agent/interactive/runtime.py` — F56 fix block can be retired post-Phase-1
- Gateway dispatcher routing — new server name + back-compat alias
- TUI / dev CLI consumers — update server name references

### agent-gateway-dist
- New version published if MCP-side changes (likely yes for tool catalog updates)

---

## Sequencing call

**Lean Phase 1 (quick win) ASAP** — 2-3 days of work, captures the V2.P2 product value, eliminates the workaround stack symptomatically. Phase 2-4 (full split) when there's time for the broader cleanup.

This is also a good Codex-review-friendly project: scope is clearly delineated, contracts are preserved, the win is measurable (citation envelope fires reliably without workarounds).
