# V2.P2 Slice A — Backend Citation Envelope (Implementation Plan, R7)

**Status:** SHIPPED 2026-05-01 — R7 PASS after 7 Codex review rounds

## Ship summary

Plan PASSed Codex review at R7 after 6 prior FAIL iterations (R1–R3 caught architectural pivots: Path C `_event_only` sentinel over an SSE-only event, sub-agent path deferred to A.5, read/excerpt tools deferred until risk_module enriches their results with citation primitives. R4–R6 caught coverage and wiring gaps: SDK MCP tool namespacing, dedup-only emission, transcript replay filter site, missing pre-deploy pytest gate. R7 was paperwork only.)

**Commits:**
- AI-excel-addin `e14f5e9` — gateway-package: `_event_only` block sentinel + parallel-tool extras message-ordering fix.
- AI-excel-addin `d71ab75` — Slice A app code: `citations.py` (Source + SourceRegistry + 4-tool extractors + canonical_tool_name + citation_envelope_hook), runtime.py wire-in, research/policy.py prompt block, server_policies.py 8-corpus-tools registration, 47 unit tests + 1 integration test.
- agent-gateway-dist `df24be3` — published as `ai-agent-gateway==0.14.0` to PyPI.
- risk_module `cac57f92` — plan doc + F55 follow-up.

**Live-verified 2026-05-01** via `python -m api.dev.chat_cli chat --mode research`:
- MSFT cloud-revenue question → `[S1]`-`[S5]` referenced correctly.
- Cross-tool parallel call (`filings_search` + `transcripts_search`) → `[S1]`-`[S10]` interleaved cleanly across both tools, source_envelope blocks on SSE.
- Same source reused under same Sn within a turn.

**Latent bug fixed during testing**: parallel tool calls were interleaving hook-returned `text` blocks between `tool_result` blocks in the next-turn user message, violating Anthropic's "tool_use immediately followed by tool_result" constraint. Fix defers all hook extras to end of message. Theoretically reachable via `trade_journal_hook` for parallel trades but unhit pre-Slice-A.

**Slice A.5 follow-ups** (deferred, each gated on a real prereq):
- 4 read/excerpt tools — needs risk_module to enrich `*_read` and `*_source_excerpt` payloads with `document_id`/citation primitives + new core helper for `DocumentMetadata` lookup by `file_path`.
- `load_document` — needs `source_id` ↔ `document_id` namespace reconciliation in `actions/research.py`.
- Sub-agent registry propagation — parent doesn't auto-receive sub-agent sources; needs explicit post-`run_agent` snapshot block.
- SDK live corpus citation path — `portfolio-mcp` blocked in SDK deferred tier; needs `loaded_mcp_servers` threading into SDK config.

**F55 filed**: corpus list-arg Pydantic schema rejects bare-string inputs from LLM. Defensive parsing in MCP wrappers + better error messages. ~1-2h, not Slice A blocking.

---

## Original R7 plan (preserved below for reference)

**R7 status when written:** R7 DRAFT — addressing Codex R6 FAIL (2 paperwork deltas)
**Spec source:** `docs/planning/V2_P2_CITATION_FIRST_QA_PLAN.md` (MVP scoping)
**Slice scope:** Backend-only. No frontend, no CLI render (Slice C), no validator gate (Slice B). Parent runtime only. 4 corpus tools.
**Effort:** 5-6 days
**Cross-repo:** AI-excel-addin only — `agent-gateway` package change + hook + prompt. NO risk_module change in Slice A.

---

## R7 changelog vs R6 (Codex R6 FAIL summary + responses)

| Codex R6 finding | R7 response |
|---|---|
| **Repo-root tests not in any pre-deploy gate** — pre-publish pytest only runs gateway-package tests; CI workflow `agent-gateway-tests.yml` also only covers package; service_restart catches startup failures but not assertion failures | **Add Step 2.5 — explicit repo-root pytest gate** before `service_restart`: `PYTHONPATH=api python3 -m pytest tests/agent/shared/test_citations.py tests/agent/interactive/ tests/test_server_policy_drift.py tests/test_research_context_policy.py`. |
| **§4 missing planned repo-root test files** — `tests/agent/interactive/...` referenced in steps 6/9 but not in §4 file list; also `tests/test_research_context_policy.py` for the research-prompt snapshot test in step 7 | **Add to §4** the missing test paths. |

---

## R6 changelog vs R5 (Codex R5 FAIL summary + responses)

| Codex R5 finding | R6 response |
|---|---|
| **Register ALL 8 corpus tools in `known_read_tools`**, not just the 4 envelope-covered ones — `mcp_server.py:1850` advertises 8, and `test_server_policy_drift.py:568` asserts policy ≡ live tools; partial registration breaks the test | **Add all 8 corpus tools** to `MCP_SERVER_POLICIES["portfolio-mcp"].known_read_tools` (`filings_search`, `filings_list`, `filings_read`, `filings_source_excerpt`, `transcripts_search`, `transcripts_list`, `transcripts_read`, `transcripts_source_excerpt`). Citation extractors stay scoped to the 4 Slice A tools. Update `_EXPECTED_TOOLS` in the drift test. |
| **Pre-publish pytest gate must hit gateway-package suite, not repo-root** — repo-root tests aren't picked up by `cd packages/agent-gateway && python3 -m pytest`; R5's Step 8 SDK filter test was placed at the repo root | **Move the three `_event_only` filter tests UNDER `packages/agent-gateway/tests/`** so they're in the pre-publish gate. (Citation extractor / hook integration tests stay at repo root — they exercise AI-excel-addin code, not gateway-package code.) |
| **Dedup typo regression** — §6 test plan still said "dedup-only no-op" even though §5 was fixed | Fix §6 wording. |
| **Citation prompt is shared with SDK path** — `build_sdk_system_prompt()` flattens via `build_research_prompt_text()` (`system_prompt.py:1139`); SDK users will see the citation block but corpus tools may be unavailable | **Add explicit fallback sentence** to the citation block: "If corpus tools are unavailable in this runtime, do not fabricate `[Sn]` — emit `[unsourced: corpus tools unavailable]` and answer from non-corpus tools." Cheaper than provider-gating; works in both modes. |

---

## R5 changelog vs R4 (Codex R4 FAIL summary + responses)

| Codex R4 finding | R5 response |
|---|---|
| **SDK corpus tools not actually loaded** — `portfolio-mcp` is deferred in all tiers, blocked in SDK mode (`agent_sdk.py:93,122`); my SDK namespaced-tool test was theoretical | **Scope SDK live corpus citation OUT of Slice A.** Slice A targets the Anthropic provider path (the active dev gateway). SDK-mode citation discipline becomes Slice A.5 (along with the wider `loaded_mcp_servers` SDK-config thread). Tests for canonical name handling stay (forward-compat for when SDK is wired up) but no live SDK corpus integration test claim. |
| **`portfolio-mcp` server policy missing corpus tools** — they fall through to approval-required (`tool_catalog.py:783,811`); preexisting bug | **Add the 4 Slice A corpus tools** (`filings_search`, `transcripts_search`, `filings_list`, `transcripts_list`) to `MCP_SERVER_POLICIES["portfolio-mcp"].known_read_tools` at `server_policies.py:206`. Update policy snapshot test. (Codex suggested ideally all 8 — Slice A adds the 4 we cover; remaining 4 land with Slice A.5.) |
| **Test plan typo** at Step 5 — said "dedup-only no-op" but design is always-emit | **Fix wording**: "dedup-only emits per-call map with `fresh_sources=[]`". |
| **Regex `mcp__[^_]+__` is brittle** — should match the existing SDK helper at `sdk_runner.py:148` which uses `split("__", 2)` | **Use `split("__", 2)`** — robust to any server-name form, matches existing convention. |
| **Publish script does NOT run tests** before uploading | **Add explicit pre-publish step**: `cd packages/agent-gateway && python3 -m pytest` before running `./scripts/publish_agent_gateway.sh --minor --yes`. |

---

## R4 changelog vs R3 (Codex R3 FAIL summary + responses)

| Codex R3 finding | R4 response |
|---|---|
| **SDK MCP tool names are `mcp__<server>__<tool>` namespaced** (`sdk_runner.py:440`); R3's exact-name dispatch silently no-ops for SDK MCP corpus calls | **Add `canonical_tool_name(tool_name)`** helper that strips `mcp__<server>__` prefix → bare `filings_search`. Extractor dispatch uses canonical name; `produced_by_tool` keeps the raw name for telemetry. Adds SDK tests for namespaced names. |
| **Dedup-only calls emit nothing** — LLM gets no per-call map when all hits are reuses; consumers get no `sources_for_call` mapping | **Always emit per-call text block + envelope** for citation-bearing calls. Track `sources_for_call: list[Source]` (fresh ∪ reused) per upsert batch. Text block lists ALL relevant Sn for this call. SSE envelope adds `sources_for_call` alongside `fresh_sources` and `registry_snapshot`. |
| **Transcript replay path also copies `final_tool_result_blocks` as model-bound content** (`transcript.py:56,104`) — `_event_only` filter missing there | **Add filter to `_tool_result_blocks_from_event`**. Maintains the gateway-level invariant: `_event_only=True` blocks NEVER reach a model API call, including replay/reconstruction. |
| **Release path** — manual pyproject bump in source is wrong; the publish script handles it via dist | **Use `./scripts/publish_agent_gateway.sh --minor --yes`** instead of manual version bump. Plan no longer lists pyproject.toml as a touched file. |
| Stronger deferred-tool prompt language | "Do not use `*_read` / `*_source_excerpt` as cited evidence in Slice A; use search/list to establish cited evidence, then read/excerpt only for orientation or verification." |

---

## R3 changelog vs R2 (Codex R2 FAIL summary + responses)

R2 had four critical / major issues, plus three structural fixes Codex asked for:

| Codex R2 finding | R3 response |
|---|---|
| **Custom `source_envelope` block round-trips to Anthropic API and would be rejected** (`runner.py:2797,2807,2811`) | **Path C accepted.** Add minimum-invasive `_event_only: bool` sentinel to extra blocks; filter in `runner.py` so event-only blocks don't enter `tool_results_content` for the next turn. ~6-line gateway-package change. Bumps `agent-gateway` version. |
| **SDK `additionalContext` JSON-dumps non-text blocks → polluted LLM context** (`sdk_runner.py:387-394`) | Same `_event_only` filter applied in `_format_additional_context` — event-only blocks excluded from additionalContext entirely. |
| **Sub-agent registry shared but parent doesn't auto-see sub-agent sources** (`runner.py:830,1002`) | **Sub-agent path deferred to Slice A.5.** Slice A scopes to parent runtime only. Hook is a no-op when `ctx.session_id` indicates sub-agent (matches `sub{idx}:{parent_sid}` pattern, `runner.py:54`). Tested. |
| **`run_label=_resolve_run_label(ctx)` not derivable from ToolResultContext** | Removed. Slice A doesn't need run_label since sub-agent is deferred. Detection of sub-agent is a single `ctx.session_id` prefix check. |
| **Risk_module enrichment isn't one-line; `*_read` doesn't open corpus DB; `*_source_excerpt` selected columns omit citation fields; no `DocumentMetadata` lookup by file_path exists** | **`*_read` and `*_source_excerpt` deferred to Slice A.5.** Slice A scopes to the 4 tools that already echo full citation primitives natively: `filings_search`, `transcripts_search`, `filings_list`, `transcripts_list`. No risk_module change. |
| **`load_document.source_id` ≠ corpus `document_id`; namespace not reconciled** (`actions/research.py:242`) | **`load_document` deferred to Slice A.5** until namespace is reconciled. |
| **`upsert` should return `(source, created)` not `src.index >= _len_before`** | Fixed in §3.3. |

Other R3 changes:
- §3 redesigned around the `_event_only` sentinel and the 4-tool scope.
- Sub-agent test becomes a "no-op assertion" rather than a "registry sharing" test.
- Extractors lean on `SearchHit.asdict()` and `DocumentMetadata.asdict()` shape directly — both fully populated by the existing corpus code.

---

## 1. Goal (unchanged)

Make every citation-bearing tool result carry a stable, structured citation envelope that the LLM can reference as `[Sn]` in its text output, AND surface that envelope on the SSE stream so downstream consumers (Slice C dev CLI, Slice D React UI) render chips without recomputing source identity.

**Slice A scope:**
- 4 corpus tools (search + list, both filings and transcripts).
- Parent runtime only.
- **Anthropic provider path** — live target. The current dev gateway uses Anthropic.
- Anthropic-side SSE `source_envelope` block delivered via `final_tool_result_blocks`.
- Canonical-name handling is implemented (forward-compat for SDK); SDK plumbing for `_event_only` filter is in (avoids polluting `additionalContext` with envelopes).

**Out of Slice A:**
- **SDK live corpus citation** — Slice A.5. `portfolio-mcp` (where corpus tools live) is in the deferred tier and is blocked in SDK mode (`agent_sdk.py:93,122`). Threading `loaded_mcp_servers` into SDK config is the prereq.
- `filings_read` / `transcripts_read` / `filings_source_excerpt` / `transcripts_source_excerpt` — Slice A.5 (gated on risk_module corpus DB resolver helper + result enrichment).
- `load_document` — Slice A.5 (gated on `source_id` ↔ `document_id` namespace reconciliation in `actions/research.py:242`).
- Sub-agent citation propagation to parent — Slice A.5 (needs explicit post-`run_agent` snapshot block mechanism).
- Validator gate — Slice B.
- CLI / React rendering — Slice C / D.

---

## 2. Discovery summary (verified)

| Concern | Where | Notes |
|---|---|---|
| Hook contract | `runner.py:112-128` (`ToolResultContext`); `runner.py:2265-2283` (Anthropic call); `sdk_runner.py:400-432` (SDK call) | Hook returns `Sequence[Dict]` extra blocks. Anthropic appends to `final_tool_result_blocks` (SSE event payload, line 2278-2282) AND extends them into `tool_results_content` for next turn (lines 2797, 2807). SDK injects them via `additionalContext`. |
| **Round-trip path** | `runner.py:2797`, `2807`, `2811`, `1750` (Anthropic flow) | After hook, all extra_blocks go BOTH to SSE event AND to next-turn user message sent to Anthropic. **This is the round-trip Codex flagged. R3 fix: `_event_only` sentinel filtered at lines 2797/2807.** |
| Anthropic block normalization | `providers/anthropic.py:525,593` | Non-`tool_result` content blocks pass through unchanged. So custom block types reach the API and get rejected. Confirms the round-trip is the failure mode. |
| SDK additionalContext | `sdk_runner.py:387-394` | Text blocks → verbatim text. Non-text blocks → `json.dumps(block, default=str)`. **R3 fix: filter `_event_only` blocks from this loop.** |
| `final_tool_result_blocks` SSE payload | `runner.py:2278-2282` | `[result_entry, *extra_blocks]` is the canonical post-hook payload landed in `tool_complete_event`. Slice C/D consumer surface (Anthropic). |
| Sub-agent session detection | `runner.py:54` | Sub-agent sessions are `f"sub{call_index}:{parent_sid}"`. Detection via `ctx.session_id.startswith("sub")` or similar (verified by reading `runner.py:42-66`). |
| Citation primitives — `SearchHit` | `core/corpus/types.py:7-26` | Complete: `document_id`, `ticker`, `source`, `form_type`, `fiscal_period`, `filing_date`, `section`, `snippet`, `char_start`, `char_end` (section-scoped), `source_url`, `source_url_deep`, `is_superseded`, `rank`. |
| Citation primitives — `DocumentMetadata` | `core/corpus/types.py:39-50` | `document_id`, `ticker`, `form_type`, `fiscal_period`, `filing_date`, `is_superseded`, `file_path`, `source_url`. Document-grain. Sufficient for citation. |
| Corpus tool result shape (search) | `mcp_tools/corpus/filings.py:84-97`, `mcp_tools/corpus/transcripts.py:?` (mirror) | `{status: 'success', hits: [asdict(SearchHit), ...], applied_filters, total_matches, has_superseded_matches, has_low_confidence_supersession, query_warnings}`. |
| Corpus tool result shape (list) | `mcp_tools/corpus/filings.py:247-251` | `{status: 'success', count, documents: [asdict(DocumentMetadata), ...]}`. |
| Concurrent tool dispatch | `runner.py:2769` (`asyncio.gather`) | Hits the parallel-dispatch path only for batches of `run_agent`. Normal tools serial within a turn. R3 lock still warranted because sub-agent (deferred) shares the registry by closure if/when re-introduced. |
| Frontend stream consumer | `useResearchChat.ts:93` (risk_module) | Consumes only `text_delta`. New SSE block types in `final_tool_result_blocks` are safe. |
| Dev CLI consumer | `chat_cli.py:768-797` | Reads `tool_call_complete.result` summary; doesn't currently read `final_tool_result_blocks`. Slice C will. New blocks are safe. |
| Research-mode prompt cache | `api/research/policy.py:63-78` (Anthropic cached blocks); `api/agent/shared/system_prompt.py:1139-1144` (SDK flat text via `build_research_prompt_text`) | Adding cached block at end preserves prefix. SDK is byte-stable text. |

---

## 3. Design

### 3.1 `_event_only` sentinel (gateway-package change)

**One field added to the extra-block return contract.** A block with `_event_only: True` is excluded from:
- Anthropic next-turn `tool_results_content` (`runner.py:2797`, `2807`).
- SDK `additionalContext` formatting (`sdk_runner.py:387-394`).
- **Transcript replay reconstruction** (`transcript.py:56` `_tool_result_blocks_from_event` and downstream consumers like `reconstruct_messages_for_task` at `transcript.py:104`). Without this filter, replay/recovery paths re-feed `final_tool_result_blocks` as model-bound user content and a custom block type gets sent to Anthropic.

It IS included in:
- Anthropic `final_tool_result_blocks` SSE event payload (`runner.py:2278-2282`) — visible to SSE consumers.
- SDK SSE-equivalent path (deferred — see §1 out-of-scope).

**Patch in `agent_gateway/runner.py`:**

```python
# ~ line 2796
result_entry, used_name, extra_blocks = result_or_exc
tool_results_content.append(result_entry)
tool_results_content.extend(b for b in extra_blocks if not b.get("_event_only"))  # changed
tools_used.append(used_name)
```

Same change at `~ line 2807`. Two-line edit.

**Patch in `agent_gateway/sdk_runner.py:387-394`:**

```python
for block in extra_blocks:
  if block.get("_event_only"):     # added
    continue
  block_type = str(block.get("type") or "")
  if block_type == "text":
    text = str(block.get("text") or "").strip()
    if text:
      parts.append(text)
    continue
  parts.append(json.dumps(block, default=str))
```

Three-line addition. Backward-compatible — existing hooks return blocks without `_event_only`, treated as model-bound (current behavior).

**Patch in `agent_gateway/transcript.py:56` (`_tool_result_blocks_from_event`):**

```python
def _tool_result_blocks_from_event(event: dict[str, Any]) -> list[dict[str, Any]]:
  blocks = list(event.get("final_tool_result_blocks") or [])
  return [b for b in blocks if not (isinstance(b, dict) and b.get("_event_only"))]
```

One-line filter. Same invariant: `_event_only=True` blocks NEVER reach a model API call, including replay/reconstruction.

**Package version + release**: use `./scripts/publish_agent_gateway.sh --minor --yes` (the script reads/bumps the dist repo's `pyproject.toml`, syncs source → dist, publishes to PyPI as `ai-agent-gateway`). Then `pip install --upgrade ai-agent-gateway` on the gateway host and `service_restart` the gateway service. Source `pyproject.toml` is NOT manually bumped — that's a deploy-script concern, not a code touch.

**Test**: in the gateway-package's own test suite, add a unit test asserting:
- Hook returning `[{"type": "text", "text": "x"}, {"type": "source_envelope", "_event_only": True, "data": "y"}]` results in `tool_results_content` extension containing only the text block, while `final_tool_result_blocks` (or its emitted form) carries both.
- Same on SDK side.

### 3.2 Citation envelope schema

New module `api/agent/shared/citations.py`:

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class Source:
  index: int                  # Sn, 1-based, registry-stable
  document_id: str            # primary key — deterministic, re-resolvable
  source_kind: str            # "filing" | "transcript"
  ticker: str
  form_type: str | None       # "10-K", "10-Q", "8-K"; None for transcripts
  fiscal_period: str
  filing_date: str
  section: str | None
  char_start: int | None      # section-scoped per corpus convention
  char_end: int | None
  source_url: str | None
  source_url_deep: str | None
  snippet: str | None
  produced_by_tool: str       # tool_name that produced it (telemetry)
```

Dedup key: `(document_id, section, char_start, char_end)`. Document-grain `*_list` results land at `(doc_id, None, None, None)`.

### 3.3 Per-runtime source registry

```python
class SourceRegistry:
  """Append-only, dedup-by-key. One instance per parent runtime."""

  def __init__(self) -> None:
    self._lock = asyncio.Lock()
    self._by_key: dict[tuple[str, str | None, int | None, int | None], Source] = {}
    self._ordered: list[Source] = []

  async def upsert(self, partial: dict[str, Any]) -> tuple[Source, bool]:
    """Return (source, created). `created=True` if newly assigned, `False` if dedup hit."""
    key = (partial["document_id"], partial.get("section"), partial.get("char_start"), partial.get("char_end"))
    async with self._lock:
      existing = self._by_key.get(key)
      if existing is not None:
        return existing, False
      next_index = len(self._ordered) + 1
      source = Source(index=next_index, **partial)
      self._by_key[key] = source
      self._ordered.append(source)
      return source, True

  def snapshot(self) -> list[Source]:
    return list(self._ordered)
```

`upsert` returns `(source, created)` per Codex R2 fix. Lock ensures atomicity even if future scope re-introduces concurrent paths.

**Lifetime**: created in `_build_chat_runtime` (`runtime.py:374-630`) at the top of the `with memory_scope_for_user(...)` block. Captured by `_combined_tool_result_hook` closure. One per built runtime → one per request lifetime. Fresh on each `_build_chat_runtime` call.

### 3.4 Per-tool extractors (Slice A scope: 4 tools)

Module `api/agent/shared/citations.py` exposes:

```python
def canonical_tool_name(tool_name: str) -> str:
  """Strip SDK MCP namespace prefix `mcp__<server>__` to bare tool name.
  Matches the existing helper convention at sdk_runner.py:148."""
  if tool_name.startswith("mcp__"):
    parts = tool_name.split("__", 2)
    if len(parts) == 3:
      return parts[2]
  return tool_name

def extract_sources(tool_name: str, result: Any) -> list[dict[str, Any]]:
  """Return list of partial Source dicts (no index assigned). Empty if non-citation.
  Dispatches by canonical_tool_name(tool_name) so SDK namespaced names also resolve."""
```

The `produced_by_tool` field on each `Source` keeps the **raw** tool name (with `mcp__<server>__` prefix when present) for telemetry — useful for distinguishing which gateway path produced the citation. Dispatch uses the canonical (stripped) form.

Coverage:

| Tool | Source primitive | Field mapping |
|---|---|---|
| `filings_search` | `result["hits"][*]` | `source_kind="filing"`, all SearchHit fields direct |
| `transcripts_search` | `result["hits"][*]` | `source_kind="transcript"`, `form_type=None`, all other SearchHit fields direct |
| `filings_list` | `result["documents"][*]` | `source_kind="filing"`, all DocumentMetadata fields; `section/char_start/char_end/snippet/source_url_deep=None` |
| `transcripts_list` | `result["documents"][*]` | `source_kind="transcript"`, `form_type=None`, all other DocumentMetadata fields |

Returns empty list when:
- Tool name not in dispatch table.
- `ctx.error is not None`.
- `result.get("status") != "success"`.
- `hits` / `documents` missing or empty.

### 3.5 Hook integration

```python
async def citation_envelope_hook(
  ctx: ToolResultContext,
  registry: SourceRegistry,
) -> list[dict[str, Any]]:
  # Slice A: parent only. Sub-agent path is no-op (Slice A.5 will lift this).
  if _is_sub_agent_session(ctx.session_id):
    return []
  if ctx.error is not None:
    return []

  partials = extract_sources(ctx.tool_name, ctx.result)
  if not partials:
    return []

  fresh: list[Source] = []
  sources_for_call: list[Source] = []
  for partial in partials:
    enriched = {**partial, "produced_by_tool": ctx.tool_name}
    src, created = await registry.upsert(enriched)
    sources_for_call.append(src)
    if created:
      fresh.append(src)

  # Always emit a per-call text block when there are sources, even if all dedup —
  # the LLM needs the Sn map for THIS call's hits whether or not they're new.
  llm_text_block = {
    "type": "text",
    "text": _format_llm_source_map(sources_for_call, fresh, ctx.tool_name),
  }
  sse_envelope_block = {
    "type": "source_envelope",
    "_event_only": True,                   # ← keeps it out of next-turn message + SDK additionalContext + transcript replay
    "schema_version": 1,
    "tool_name": ctx.tool_name,
    "tool_call_id": ctx.tool_call_id,
    "sources_for_call": [_source_to_dict(s) for s in sources_for_call],
    "fresh_sources": [_source_to_dict(s) for s in fresh],
    "registry_snapshot": [_source_to_dict(s) for s in registry.snapshot()],
  }
  return [llm_text_block, sse_envelope_block]
```

`_format_llm_source_map(sources_for_call, fresh, tool_name)` distinguishes new vs reused Sn in the human-readable text:

```
[citation envelope] sources from filings_search:
- [S1] document_id=edgar:msft:10K:2026-01-28, ticker=MSFT, form_type=10-K,
  fiscal_period=FY2026-Q2, section="cloud_revenue"  (NEW)
- [S2] document_id=edgar:msft:10K:2026-01-28, section="risk_factors"  (NEW)
- [S5] document_id=edgar:goog:10Q:2025-10-30, section="ai_overview"  (reused from earlier turn)
```

Always emitting (even on all-dedup) means consumers always have a per-call mapping, and the LLM is reminded of stable indexes.

**`_is_sub_agent_session` implementation**: `ctx.session_id.startswith("sub")` and `":" in ctx.session_id` per `runner.py:54` pattern (verified). Three-line helper.

**`_format_llm_source_map` example output:**

```
[citation envelope] new sources from filings_search:
- [S1] document_id=edgar:msft:10K:2026-01-28, ticker=MSFT, form_type=10-K,
  fiscal_period=FY2026-Q2, filing_date=2026-01-28, section="cloud_revenue"
- [S2] document_id=edgar:msft:10K:2026-01-28, ticker=MSFT, form_type=10-K,
  fiscal_period=FY2026-Q2, filing_date=2026-01-28, section="risk_factors"
```

### 3.6 Hook chain integration

In `runtime.py:461-468`:

```python
# Above the closure:
source_registry = SourceRegistry()  # ← NEW

async def _combined_tool_result_hook(ctx):
  if research_turn is not None:
    persist_research_tool_result(research_turn, ctx)
  citation_blocks = await citation_envelope_hook(ctx, source_registry)
  annotate_result_hook(ctx)
  if ce_bundle:
    ce_bundle.sanitize_hook(ctx)
  update_model_log_hook(ctx)
  trade_blocks = await trade_journal_hook(ctx) or []
  return [*citation_blocks, *trade_blocks]
```

`citation_envelope_hook` runs early — before `annotate_result_hook` so warnings layer on top. Citation hook does NOT mutate `ctx.result` or `ctx.result_entry`, so ordering relative to `annotate_result_hook` is independent (no clobbering risk).

### 3.7 System prompt addition

New cached block in `api/research/policy.py` appended to `build_research_prompt_stack`:

```python
_CITATION_GUIDANCE_BLOCK = '''## Citation discipline

When you call corpus tools (`filings_search`, `transcripts_search`, \
`filings_list`, `transcripts_list`), each call's result is followed by a \
`[citation envelope]` text block listing the source indexes assigned for \
that call:

```
[citation envelope] new sources from filings_search:
- [S1] document_id=edgar:msft:10K:2026-01-28, ticker=MSFT, form_type=10-K,
  fiscal_period=FY2026-Q2, filing_date=2026-01-28, section="cloud_revenue"
- [S2] document_id=goog:10Q:2025-10-30, ticker=GOOG, form_type=10-Q,
  fiscal_period=FY2025-Q3, filing_date=2025-10-30, section="ai_overview"
```

**Every quantitative or factual claim in your response must end with one or \
more `[Sn]` labels** referencing those indexes, where each `Sn` matches \
exactly the index from the envelope. Reuse the same `Sn` for follow-up \
claims from the same source — indexes are stream-stable across the turn. \
Do not invent new `[Sn]` labels — use only what envelopes provide.

**Worked example**:

> Microsoft cloud revenue grew 22% year-over-year in Q3 [S1], reaching \
> $33.9B [S1]. Management cited Copilot adoption as the primary driver \
> [S2], with paid seats reaching 20M (up 250% YoY) [S2].

If you cannot find a source for a claim, mark it `[unsourced: <reason>]` \
where `<reason>` is a one-clause explanation (e.g., \
`[unsourced: general industry knowledge]`). Do not fabricate citations. \
If corpus tools are unavailable in this runtime (no `filings_*` or \
`transcripts_*` tools listed in your catalog), do NOT fabricate `[Sn]` \
labels — emit `[unsourced: corpus tools unavailable]` and answer from \
available non-corpus tools.

**Slice A scope notice**: do not use `*_read` / `*_source_excerpt` as cited \
evidence. Use `*_search` and `*_list` to establish cited evidence; reach \
for `*_read` / `*_source_excerpt` only for orientation or verification \
context that does not need an `[Sn]` label.'''
```

Worked example in first cut (per Codex R1 minor). Last paragraph documents the Slice A scope so the LLM doesn't try to cite read/excerpt tools that don't yet have envelopes.

### 3.8 Backward compatibility

- Tools without extractors → hook is no-op, no extra blocks.
- Sub-agent runs → hook is no-op (Slice A scope).
- Existing hook contracts → blocks without `_event_only` field treated as model-bound (current behavior). Backward-compat preserved for trade-journal etc.
- SSE: new `source_envelope` block in `final_tool_result_blocks` is `_event_only=True` — only in SSE, never in API messages, never in SDK additionalContext.
- Frontend hook reads only `text_delta`; unaffected.
- Dev CLI: new fields safe.
- Cached prompt prefix preserved.

---

## 4. Files touched

**Edited (AI-excel-addin — gateway package)**
- `packages/agent-gateway/agent_gateway/runner.py` — `_event_only` filter at lines 2797, 2807. ~2 LOC delta.
- `packages/agent-gateway/agent_gateway/sdk_runner.py` — `_event_only` filter in `_format_additional_context`. ~3 LOC delta.
- `packages/agent-gateway/agent_gateway/transcript.py` — `_event_only` filter in `_tool_result_blocks_from_event`. ~1 LOC delta.
- `packages/agent-gateway/tests/` — unit tests for the three filter sites (`runner.py` next-turn extension, `sdk_runner.py` additionalContext, `transcript.py` replay reconstruction). Tests live UNDER the package suite so they hit the pre-publish pytest gate. ~80 LOC.

**Sync + publish (AI-excel-addin → external)**
- `./scripts/publish_agent_gateway.sh --minor --yes` — handles dist sync, version bump on dist's pyproject, PyPI publish as `ai-agent-gateway`.
- Gateway host: `pip install --upgrade ai-agent-gateway` then `service_restart` (services-mcp).

**New (AI-excel-addin)**
- `api/agent/shared/citations.py` — `Source`, `SourceRegistry`, `extract_sources`, `citation_envelope_hook`, `_format_llm_source_map`, `_is_sub_agent_session`. ~180 LOC.
- `tests/agent/shared/test_citations.py` — extractor + registry + hook tests. ~250 LOC.

**Edited (AI-excel-addin)**
- `api/agent/interactive/runtime.py` — instantiate `SourceRegistry`, chain `citation_envelope_hook` into `_combined_tool_result_hook`. ~10 LOC delta.
- `api/research/policy.py` — add `_CITATION_GUIDANCE_BLOCK`, append to `build_research_prompt_stack`. ~30 LOC delta.
- `api/agent/shared/server_policies.py:206` — add ALL 8 corpus tools (`filings_search`, `filings_list`, `filings_read`, `filings_source_excerpt`, `transcripts_search`, `transcripts_list`, `transcripts_read`, `transcripts_source_excerpt`) to `MCP_SERVER_POLICIES["portfolio-mcp"].known_read_tools` so they don't hit approval-required at `tool_catalog.py:783,811`. ~8 LOC delta. Citation extractors stay scoped to the 4 Slice A tools (search + list); the read/excerpt tools are policy-classified now but envelope-covered in Slice A.5.
- `tests/test_server_policy_drift.py` — update `_EXPECTED_TOOLS` to include all 8 corpus tools (matches the live `mcp_server.py:1850` registration).
- `tests/agent/interactive/test_citation_integration.py` (new) — Anthropic-mode integration tests asserting hook chain behavior (see Steps 6, 9). ~120 LOC.
- `tests/test_research_context_policy.py` — snapshot test for the citation guidance block in `build_research_prompt_text` (Step 7). ~30 LOC delta if file exists; new file ~50 LOC otherwise.

**Untouched**
- `mcp_tools/corpus/` (risk_module) — no change in Slice A.
- `core/corpus/` (risk_module) — no change in Slice A.
- Frontend, dev CLI — no change in Slice A.

---

## 5. Step-by-step implementation

| # | Step | Repo | Verification |
|---|---|---|---|
| 1 | Add `_event_only` filter at three sites: `runner.py:2797,2807`, `sdk_runner.py:_format_additional_context`, `transcript.py:_tool_result_blocks_from_event`. | AI-excel-addin/packages/agent-gateway | Three new gateway-package unit tests, one per site: hook returning mixed `[text, event_only]` blocks → next-turn extension / additionalContext / replay-reconstructed messages all contain only text; SSE `final_tool_result_blocks` contains both. |
| 2a | Pre-publish: `cd packages/agent-gateway && python3 -m pytest`. The publish script does NOT run tests on its own; we add this gate. | AI-excel-addin/packages/agent-gateway | All gateway tests pass. |
| 2b | Run `./scripts/publish_agent_gateway.sh --minor --yes`. Then `pip install --upgrade ai-agent-gateway` on gateway host. **Do NOT restart yet** — Step 2.5 runs first. | dist + PyPI | New gateway package on PyPI; gateway-host pip install succeeds. |
| 2.5 | **Repo-root pre-deploy pytest gate** (added in R7): `PYTHONPATH=api python3 -m pytest tests/agent/shared/test_citations.py tests/agent/interactive/ tests/test_server_policy_drift.py tests/test_research_context_policy.py`. Catches assertion failures the package-level pytest and service-start checks miss. | AI-excel-addin | All listed tests pass. |
| 2.6 | `service_restart` the gateway via services-mcp. | services-mcp | `service_status` PASS. |
| 3 | Implement `Source` + `SourceRegistry` in `api/agent/shared/citations.py`. | AI-excel-addin | Unit tests: empty, single insert, dedup hit returns `(existing, False)`, fresh insert returns `(new, True)`, lock correctness under simulated concurrent gather. |
| 4 | Implement `canonical_tool_name` + `extract_sources` for the 4 tools using fixture payloads. Coverage includes both bare names (`filings_search`) and SDK MCP-namespaced names (`mcp__portfolio-mcp__filings_search`). | AI-excel-addin | Unit tests: 4 tools × 3 cases (happy, empty, error) × 2 name forms (bare + namespaced) = 24 cases. |
| 5 | Implement `citation_envelope_hook` returning `[text_block, _event_only source_envelope_block]`. Always emit per-call map (fresh ∪ reused). Include `_is_sub_agent_session` no-op path. | AI-excel-addin | Unit tests: extra_blocks shape; sub-agent ctx → empty; error ctx → empty; non-citation tool → empty; ALL-fresh emits with full `fresh_sources`; ALL-dedup emits per-call map with `fresh_sources=[]` and reused-only `sources_for_call`; mixed fresh+dedup emits both populated correctly. |
| 6 | Wire into `_build_chat_runtime`. | AI-excel-addin | Integration test: build runtime, simulate two sequential tool calls (search then list), assert `extra_blocks` shape on each, assert registry indexes are stream-stable. |
| 7 | Add `_CITATION_GUIDANCE_BLOCK` with worked example to `policy.py`. | AI-excel-addin | Snapshot test on `build_research_prompt_text`. |
| 8 | SDK `_event_only` filter test: synthesize a hook return with `[text, _event_only source_envelope]`, route through `_format_additional_context`, assert text-only output. **Test lives at `packages/agent-gateway/tests/`** so it hits the pre-publish gate (Step 2a). (Live SDK corpus integration is Slice A.5 — `portfolio-mcp` is deferred in SDK mode per `agent_sdk.py:93,122`.) | AI-excel-addin/packages/agent-gateway | New unit test in `packages/agent-gateway/tests/test_sdk_runner_event_only.py` exercising the filter, not a live tool flow. |
| 9 | Anthropic-mode integration test: tool call → `final_tool_result_blocks` includes both blocks; next-turn `messages` payload (intercept on the provider) does NOT include the `source_envelope` block. | AI-excel-addin | New test asserting the `_event_only` filter in the round-trip path. |
| 10 | Sub-agent no-op test: simulate a sub-agent session_id (`"sub0:abc123"`), assert hook returns `[]`. | AI-excel-addin | Unit test. |
| 11 | Live dev-chat verification with research mode + corpus question on MSFT and GOOG. Capture transcripts. | AI-excel-addin | Eyeball `[Sn]` adherence; confirm same document → same Sn; cache_read_input_tokens stable on second turn. |

---

## 6. Test plan

**Gateway-package unit (`packages/agent-gateway/tests/`)** — these run in the pre-publish pytest gate
- `_event_only` filter on Anthropic next-turn messages (`runner.py` filter at lines 2797, 2807).
- `_event_only` filter on SDK additionalContext (`sdk_runner.py:_format_additional_context`).
- `_event_only` filter on transcript replay (`transcript.py:_tool_result_blocks_from_event`).

**AI-excel-addin unit (`tests/agent/shared/test_citations.py`)**
- `SourceRegistry`: empty, single insert, dedup, sequential indexing, concurrent gather race.
- `extract_sources`: 4 tools × 3 cases × 2 name forms (bare + namespaced) = 24 cases.
- `citation_envelope_hook`: shape, sub-agent no-op, error no-op, non-citation no-op, ALL-dedup emits per-call map with `fresh_sources=[]` and reused-only `sources_for_call`, fresh+dedup mix populates both.
- `_format_llm_source_map`: deterministic, distinguishes NEW vs reused, escaping safe.
- `_is_sub_agent_session`: parent vs sub-agent session_id detection.
- `canonical_tool_name`: bare names pass through, `mcp__<server>__<tool>` strips correctly, hyphenated server names handled.

**AI-excel-addin integration (`tests/agent/interactive/`)**
- Anthropic path: full hook chain → `final_tool_result_blocks` includes both blocks; intercepted next-turn message does NOT include `source_envelope`.
- Sub-agent: hook returns empty for sub-agent session_id.
- (SDK live corpus integration deferred to Slice A.5.)

**Live (manual)**
- MSFT and GOOG corpus questions through `python -m api.dev.chat_cli chat --mode research`. Eyeball:
  - LLM uses `[Sn]` correctly.
  - Same document → same Sn across the response.
  - Indexes start at S1 and increment.
- Cache: second turn `cache_read_input_tokens` reflects prefix hit.

---

## 7. Risks and open questions

| # | Risk / question | Mitigation |
|---|---|---|
| 7.1 | LLM ignores `[Sn]` instructions despite prompt + worked example. | Worked example IS in first cut. Live verification in Step 11. If poor adherence: tighten prompt with 2 more examples; do NOT escalate to validator gate. |
| 7.2 | Cache prefix breakage from prompt addition. | Append cached block at end of stack. Verify with pre/post `cache_read_input_tokens`. SDK path is byte-stable text. |
| 7.3 | Source dedup grain — section vs document vs char range. | Key `(document_id, section, char_start, char_end)`. `*_list` results: `(doc_id, None, None, None)` document-grain. |
| 7.4 | Cross-runtime registry leakage. | Constructed fresh per `_build_chat_runtime` invocation. No singleton. Tested. |
| 7.5 | Sub-agent registry. | Slice A: hook is no-op for sub-agents. No leakage, no auto-propagation. Slice A.5 will design parent-visible snapshot block. |
| 7.6 | `_event_only` field collision with future block consumers. | Underscore-prefixed convention matches `_runner_warning`. No current usage. Documented in gateway-package release notes. |
| 7.7 | Gateway-package change blast radius. | 5 LOC across two files. Backward-compatible (blocks without `_event_only` keep current behavior). Unit-tested. Sync + PyPI bump per `docs/DEPLOY_CHECKLIST.md`. |
| 7.8 | Concurrent dispatch + asyncio.Lock placement. | Lock around `upsert` only. `extract_sources` runs outside lock — pure transformation, no shared state. Tested with simulated 50-concurrent upsert mix. |
| 7.9 | Token cost of new prompt block. | ~400 tokens (~0.0004 input cost on Opus 4.7 cached). Acceptable. |
| 7.10 | LLM tries to cite from `*_read` / `*_source_excerpt` tools (out of Slice A scope). | Prompt §3.7 explicitly tells the LLM these aren't citation-tracked yet and to use `*_search` / `*_list` for evidence base. Live verification confirms. |
| 7.11 | Slice C/D consumer parsing of `source_envelope` block. | Block is structured JSON with fixed `schema_version: 1` field. Slice C/D plans reference this schema. |
| 7.12 | Anthropic API rejects `_event_only` field on a block sent in the next turn (paranoia check). | The whole point of the filter is that `_event_only` blocks NEVER go to the API. Belt+suspenders: `_event_only` keys can also be stripped before any API send if defense-in-depth needed (one extra line). |

---

## 8. What this enables for Slice A.5, Slice B, Slice C, Slice D

- **Slice A.5**: extends Slice A to `*_read` / `*_source_excerpt` (after risk_module enrichment + `get_document_metadata_by_file_path` core helper) + `load_document` (after namespace reconciliation) + sub-agent registry propagation. Same envelope schema, more tools.
- **Slice B (validator gate)**: walks LLM `text_delta` events, scans for `[Sn]` references and `[unsourced]` flags, validates against `registry.snapshot()`. Builds on Slice A registry contract.
- **Slice C (dev CLI render)**: consumes `source_envelope` block from `final_tool_result_blocks`; renders inline chips when `[Sn]` appears in `text_delta`.
- **Slice D (React UI)**: consumes `source_envelope` block; renders chips + sidebar source list. Same schema.

---

## 9. Codex R7 review brief

When sending R7 to Codex:
- Cwd: `/Users/henrychien/Documents/Jupyter/AI-excel-addin`
- Sandbox: `read-only`
- Reasoning: high
- Specific concerns:
  1. `_event_only` filter placement at `runner.py:2797,2807` — are there OTHER call sites that extend `extra_blocks` into model-bound payloads that I missed?
  2. SDK filter at `sdk_runner.py:387` — same question, are there other SDK-side carriers I missed?
  3. Does `final_tool_result_blocks` ever get re-used as model-bound content downstream (e.g., on resume / replay paths)? If yes, the `_event_only` filter may need to apply there too.
  4. `_is_sub_agent_session` heuristic via `ctx.session_id.startswith("sub")` — is this reliable? Walk through `runner.py:42-66` and `tool_handlers.py:1035`.
  5. Concurrent dispatch: confirm Slice A scope (no sub-agents, normal tools serial within a turn) means we can drop the lock if we want. R3 keeps it for forward-compat with Slice A.5.
  6. Anything else.

PASS/FAIL plus structured findings.
