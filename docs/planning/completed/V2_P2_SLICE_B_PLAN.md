# V2.P2 Slice B — Citation Validator Gate (Implementation Plan, R11)

> Archived 2026-05-04 under `docs/planning/completed/` after shipped status verification.

**Status:** SHIPPED 2026-05-02 — R10 PASS + R11 OAuth amendment

## R11 amendment (post-R10-PASS, post-implementation): OAuth support added

| Trigger | R11 response |
|---|---|
| Live verification on dev gateway revealed `ANTHROPIC_AUTH_MODE=oauth` and empty `ANTHROPIC_API_KEY` — original `JudgeClient(api_key=...)` design couldn't run Path 3 in the live environment | Extend `JudgeClient` to accept `auth_mode: Literal["api","oauth"]` + `api_key: str \| None` + `auth_token: str \| None`. Constructor uses the matching credential per mode; raises `ValueError` if the active mode's credential is missing. `_build_judge_client_factory(settings)` reads new env vars `OPERATOR_ANTHROPIC_AUTH_MODE`, `OPERATOR_ANTHROPIC_AUTH_TOKEN`, `OPERATOR_ANTHROPIC_API_KEY`, with fallback chain to gateway env (`ANTHROPIC_AUTH_MODE`, `ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_API_KEY`). Returns None (preserves `judge_auth_missing` semantic) only when the resolved credential for the active mode is missing. Logs active mode on first invocation. **Verified: `anthropic==0.93.0` supports `Anthropic(auth_token=...)` and `AsyncAnthropic(auth_token=...)`.** Live verification on dev gateway (OAuth mode) now unblocked. |

## R11.1 follow-up: OAuth Claude Code fingerprint required

Initial R11 implementation passed `auth_token` to `AsyncAnthropic` but Anthropic API rejected requests with HTTP 401: `'OAuth authentication is currently not supported.'` Cause: Anthropic only accepts OAuth tokens from clients that present the Claude Code CLI fingerprint. Mirrored from `agent_gateway/providers/anthropic.py:336-350,422-423`:

- `default_headers` — `X-Api-Key=Omit()` to suppress, `anthropic-beta` with `claude-code-20250219,oauth-2025-04-20,fine-grained-tool-streaming-2025-05-14`, `user-agent=claude-cli/2026.3.14`, `x-app=cli`
- System prompt prepend — `"You are Claude Code, Anthropic's official CLI for Claude."` block at start of every request when `auth_mode=oauth`

After fingerprint fix: zero 401s in gateway logs across live verification turns; Path 3 `full_scan` judge calls succeed (judge_called=true, judge_path="full_scan", warning_codes=[], violation_count=4 per turn). Shipped in AI-excel-addin commit `92830bc` (citation_judge.py + test fixture updated to mock `Omit` sentinel).

---

## R10 changelog vs R9 (Codex R9 FAIL summary + responses)

| Codex R9 finding | R10 response |
|---|---|
| Line 821 still mentions `SQLite store` in implementation directive | Drop the "'s SQLite store" qualifier — telemetry section now describes the JSONL log as a sibling of `cost_tracker.py`. |
| §8 review brief still says R8 / "If R8 PASSes" | Updated to R10 framing. |
| Validator-internal-error event lacks `warning_codes` while normal + timeout events have it | Add `"warning_codes": []` for parity. |

---

## R9 changelog vs R8 (Codex R8 FAIL summary + responses)

| Codex R8 finding | R9 response |
|---|---|
| Line 146 still references direct `anthropic.Anthropic().messages.create()` in discovery table | Reframe as injected `JudgeClient` factory wrapping the SDK; helpers don't construct SDK directly. |
| Lines 451, 829, 919 mention SQLite outside changelog/history (still in implementation directives) | Drop SQLite-migration language from implementation sections; future migration explicitly out of scope. |
| Timeout event in `drain()` lacks `warning_codes` while normal event has it — inconsistent consumer-side | Add `warning_codes: ["validation_timeout"]` to timeout event for parity. |

---

## R8 changelog vs R7 (Codex R7 FAIL summary + responses)

| Codex R7 finding | R8 response |
|---|---|
| Double `client = judge_factory()` typo in §3.4.2 helper pseudocode | Remove duplicate. |
| §5 Step 4 still says "direct `anthropic.Anthropic` client" — contradicts §3.4.1 injected factory | Update Step 4 to reference injected `JudgeClient` / `judge_factory`. |
| §3.4.1 line 413 says "SQLite or `cost_tracker.py` (TBD)" — plan otherwise consistently chooses JSONL | Change to JSONL. |
| §8 review brief is stale ("review R2 concerns", "If R2 PASSes") | Update review brief framing. |

---

## R7 changelog vs R6 (Codex R6 FAIL summary + responses, preserved)

## R7 changelog vs R6 (Codex R6 FAIL summary + responses)

| Codex R6 finding | R7 response |
|---|---|
| **`_validate_and_emit` omits `warning_codes` in emitted event** despite `ValidationResult.warning_codes` populated | **Add `"warning_codes": result.warning_codes` to the emitted event in §3.6.1.** |
| **Stale `_maybe_call_judge` budget guard text** in §3.4.2 and §7.4 contradicts R6's hoisted gating | **Rewrite `_maybe_call_judge` description** — now a thin call+parse helper, no budget decision. Update §7.4 to reflect that budget gating is in `validate_response`. |

---

## R6 changelog vs R5 (Codex R5 FAIL summary + responses, preserved)

## R6 changelog vs R5 (Codex R5 FAIL summary + responses)

| Codex R5 finding | R6 response |
|---|---|
| **Budget-exhausted confirm path silently erases regex flags** — `_judge_confirm_flags` returns `[]` on budget exhaustion, and caller unconditionally sets `unsourced = []`, making budget exhaustion look like "judge confirmed no violations" | **Hoist budget check to `validate_response`**: compute `judge_available = factory is not None AND budget_remaining > 0` once at top. Decision tree treats `judge_available=False` (whether from missing factory or exhausted budget) as the same regex-only path → `unsourced` retains regex-flagged candidates → they surface as violations in the combine step. `judge_called` is set only when a judge call actually ran. Also adds `validator_warning_codes` (e.g., `["judge_budget_exhausted"]` or `["judge_auth_missing"]`) to the `citation_validation` event so consumers can distinguish skip-reasons. |

---

## R5 changelog vs R4 (Codex R4 FAIL summary + responses, preserved)

## R5 changelog vs R4 (Codex R4 FAIL summary + responses)

| Codex R4 finding | R5 response |
|---|---|
| **`validate_response` signature missing `judge_client_factory` + `daily_budget_usd` params** — wrapper passes them but signature doesn't accept; `_maybe_call_judge` calls `judge_factory()` unguarded → `NoneType` call when auth missing | **Thread the params through**: `validate_response(text, registry_snapshot, *, mode, qualitative_density_threshold, judge_client_factory: Optional[Callable[[], JudgeClient]] = None, daily_budget_usd: float = 5.0)`. Pass into `_judge_confirm_flags` / `_judge_full_scan`. Both judge paths check `if judge_factory is None: return None` before calling — preserves regex-only behavior with `judge_auth_missing` semantics. |
| **`compact_unit` rematches inside decimal stable references**: `Section 5.2B` → `2B` matches; `Note 3.2bn` → `2bn` matches | **Add pre-number guard**: `(?<![\w.])\d+` so the integer part can't start mid-decimal or mid-word. Combined with the existing stable-reference lookbehind (`(?<!Item\s)...`), this fully blocks `Section 5.2B`, `Note 3.2bn`, etc. Tests added for these cases. |

---

## R4 changelog vs R3 (Codex R3 FAIL summary + responses, preserved)

## R4 changelog vs R3 (Codex R3 FAIL summary + responses)

| Codex R3 finding | R4 response |
|---|---|
| **Judge-factory `None` handling broken** — wrapper at line 455 used `self._judge_factory = judge_client_factory or _default_judge_factory` which discards `None` and re-enables default judge path | **Drop the `or` fallback.** Preserve `None` through the constructor; wrapper checks `if self._judge_factory is None` and skips judge calls entirely (regex-only path with `judge_auth_missing` warning). |
| **Sentence boundary regex applies digit guard to `!` and `?`** — `Q3.`, `$5.0!` not handled correctly | **Refine pattern**: `(?<!\d)\.|\.(?!\d)|[!?]|\n`. Period gets the digit guard on EITHER side; `!`/`?`/`\n` always terminate. Tests cover `1.5x`, `$33.9B`, `Q3.`, `$5.0!`. |
| **Compact/currency regex edge cases**: `Item 7B`/`Form 10K` false-match compact_unit; `3.2bn` doesn't match (changelog claimed it did); `$3.2T` splits into `$3`+`2T` because currency suffixes omit `T` | **Multi-fix**: (a) add `T/t` to currency/paren suffixes (`[BMKTbmkt]`); (b) extend compact_unit to include `bn/mn/mm` lowercase units; (c) add negative lookbehind for stable-reference prefixes (`Item|Form|Section|Part|Chapter|Note`) to prevent `Item 7B`/`Form 10K` false positives. |
| **Stale "SSE-only" persistence text** at §3.5 line 424 and §7.14 line 796 contradicts §3.9's R3 acknowledgement | **Sweep both sites** to align with the persistence acknowledgement. |
| **Stale `validator_error`** appears where field should be `validator_error_code` | **Sweep**. |
| **`detect_fabricated_indexes` signature mismatch** — declared with `registry_snapshot` at §3.1 line 121, called with `registered_indexes` at §3.3 line 230 | **Fix declaration**: `detect_fabricated_indexes(text: str, registered_indexes: set[str])` — matches the call site. |
| **Provider gate rationale wrong** — only `agent-sdk` actually uses SDK runner; `openai` and `codex` go through generic `AgentRunner` with `text_delta` + `turn_complete` | **Reframe as scope choice**: keep Anthropic-only for Slice B, but document explicitly that the gate is a blast-radius decision (Anthropic is the live dev gateway path; OpenAI/Codex AgentRunner paths are mechanically compatible but unverified for prompt adherence + validator latency budget). Slice B.5 may extend the allowlist after telemetry on Anthropic confirms behavior. |

---

## R3 changelog vs R2 (Codex R2 FAIL summary + responses, preserved)

## R3 changelog vs R2 (Codex R2 FAIL summary + responses)

| Codex R2 finding | R3 response |
|---|---|
| **`validate_response` signature still takes live `registry`** (§3.1, decision-tree pseudocode at §3.3) — contradicts the wrapper call that passes `registry_snapshot=...` | **Fix signature throughout**: `validate_response(text, registry_snapshot: list[Source], ...)`. Remove all internal `registry.snapshot()` calls. `detect_fabricated_indexes(text, registered_indexes: set[str])`. |
| **Provider gating wrong** — current code says skip `agent-sdk`; but `AGENT_PROVIDER` also supports `openai` and `codex` per `credentials.py:32` | **Flip to positive list**: `if provider_name != "anthropic": return event_log, None`. SDK + OpenAI + Codex all skip; only Anthropic AgentRunner gets the wrapper. |
| **Drain timeout silently cancels** — no `citation_validation` event emitted, indistinguishable from "validator disabled" or "no event bug" | **Emit timeout event**: on drain timeout, append `{"type": "citation_validation", "violations": [], "validator_error_code": "validation_timeout", "turn": <n>, ...}` BEFORE flush_pending_terminal. |
| **`extract_sn_refs` falsely matches `S1` inside `[unsourced: claim about S1]`** | **Skip unsourced blocks**: when iterating `BRACKET_BLOCK_PATTERN`, check if the inner text starts with `unsourced` (case-insensitive); if so, skip Sn extraction for that block (still detected separately by `UNSOURCED_PATTERN`). |
| **Sentence-window decimal handling fails on earlier decimals** — e.g., `[S1] Valuation was 1.5x revenue and EBITDA was $5M` starts the `$5M` window after `1.5x`'s decimal, losing `[S1]` | **Regex-based sentence boundary** that ignores periods between digits: `re.compile(r'(?<![\d])[.!?\n]')` — only treats periods as boundaries when not preceded by a digit. Also tracks the previous boundary by walking right-to-left with the same constraint. |
| **Regex `1.5B` (no $, no space) not matched**; `($5M)` boundary issue with `\b` after optional `)` | **Add compact-unit regex** for unit-suffixed bare numbers (`1.5B`, `250M`, `3.2bn`); fix parenthetical boundary to remove `\b` after optional closing paren. |
| **Event persistence** — `server.py:696` writes every non-heartbeat event to transcript; plan claims SSE-only is wrong | **Acknowledge persistence in §3.5**: `citation_validation` events are persisted in chat transcripts by default. Slice B accepts this — validation results are part of the chat record. Slice D may filter the field at render time if it duplicates UI-rendered overlays. |
| **Stale text I missed during R2 patches**: line 641 still has `_event_only: true`, line 679 still has `logs/citation_validation/`, line 264 still says SQLite/TBD | **Sweep and fix all three.** |
| `OPERATOR_ANTHROPIC_API_KEY` missing → should skip judge with `judge_auth_missing`, not crash | **Add graceful fallback** in `_build_judge_client_factory`: missing key → return None factory; wrapper checks and falls back to regex-only with `judge_auth_missing` warning logged once per session. |

---

## R2 changelog vs R1 (Codex R1 FAIL summary + responses, preserved)

(Original R2 changelog preserved below for context.)

## R2 changelog vs R1 (Codex R1 FAIL summary + responses)

| Codex R1 finding | R2 response |
|---|---|
| **§7.1 lifecycle isn't mechanically solved** — `event_log.append()` is sync; EventLog closes on terminal events; `iter_from` returns immediately on close; "await in append" can't work | **Switch to runner-wrapper + event-log-wrapper combo per Codex suggestion.** Event-log wrapper captures text and registry snapshot at `turn_complete`, stores `stream_complete` instead of forwarding, exposes `async drain()`. New thin `RunnerWithCitationValidation` wraps the runner: `await inner.run(...)` → `await wrapper.drain(timeout=N)` → `wrapper.flush_pending_terminal()`. |
| **SDK mode has no `turn_complete` event** (`sdk_runner.py` emits only `text_delta` + `stream_complete`); validator never fires there | **Slice B scoped Anthropic-only.** SDK path documented as Slice B.5 (parallel with Slice A.5 SDK live corpus). Wrapper is no-op when `provider_name == "agent-sdk"`. |
| **Registry snapshot timing wrong** — async validation can see sources created after the text was generated | **Snapshot captured synchronously at `turn_complete` interception**, before scheduling validation. `validate_response` accepts `registry_snapshot: list[Source]`, not the live registry. |
| **TAG_PATTERN regex doesn't match `[S1, S2]`** | **Rewrite tag extraction**: bracket-content parser that finds all `S\d+` inside any `[...]` block, plus separate `[unsourced...]` detection. Handles `[S1, S2]`, `[S1][S2]`, mixed malformed brackets. |
| **Wrapper must clear buffered text on `stream_retry`** (research wrapper at `api/research/runtime.py:189-206` already does this) | **Add `stream_retry` handler** that clears buffer. Mirrors research wrapper. |
| **Sub-agent reasoning wrong** — sub-agents get fresh EventLog instances (`runner.py:812-817`); parent wrapper doesn't see sub-agent text. No `_is_sub_agent_session` check needed at wrapper layer. | **Drop the `_is_sub_agent_session` check from the wrapper.** Document that sub-agent text validation is structurally impossible at this layer (Slice A.5 will design propagation). |
| **`_event_only` rationale wrong** — Slice A's filter applies to hook-returned extra blocks, not arbitrary event-log events. Standalone event-log events aren't pulled into next model request. | **Drop the `_event_only` field** from `citation_validation`. Update §3.5 explanation: standalone event-log events are SSE-only by construction; no filter needed. |
| **Telemetry location wrong** — repo `logs/` is gitignored (`.gitignore:22`); existing app convention is `api/logs/` (`api/main.py:27`) or SQLite (`api/logs/cost_tracker.py:43-130`) | **Move telemetry to `api/logs/citation_validation.jsonl`**, sibling to `cost_tracker.py` SQLite. JSONL chosen over SQLite for grep-ability during early FP-rate analysis; can migrate to SQLite once schema stabilizes. |
| **Cost cap deferral violates CLAUDE.md** "don't defer to dodge friction" | **Ship cost cap in Slice B**: `CITATION_VALIDATION_BUDGET_USD_PER_DAY` env var (default $5/day), enforced at judge-call site; falls back to regex-only when budget exceeded. |
| **Judge auth bypasses BYOK/OAuth** — direct `anthropic.Anthropic()` doesn't go through provider path | **Route judge through existing provider abstraction.** The validator gets a judge-client factory injected at `_build_chat_runtime`; default factory uses operator credentials (`get_provider_config()`), not user BYOK. Decision rationale: validator cost is operator-side institutional-trust spend, not user-billed. Documented in §7. |
| **`response_format={"type":"json_object"}` doesn't exist in `anthropic==0.93.0`** | **Drop `response_format`**; use prompt-level "Output JSON only" instruction + defensive parse with fail-open. |
| **Regex too narrow for finance** — missing `($5M)`, `-$5M`, `1.5 trillion`, `200 bps`, `2:1` | **Expand `QUANT_PATTERN`** to cover negative/parenthetical currency, spelled-out units (billion/trillion/million/bn/mm), basis points, ratios. Scientific notation deprioritized. |
| **Tag window only scans after number** — misses "According to [S1], revenue was $33.9B" | **Scan full sentence**, not just post-number window. |
| **System-generated text after `turn_complete`** — budget-limit text at `runner.py:2626-2649`, max-turns text at `runner.py:2469-2483` confuse buffer | **Wrapper detects `budget_exceeded` and `max_turns_reached` events** and excludes any text appended after them from validation. |
| Pseudocode signature mismatch | Fix |
| Tests shouldn't write real files; use `tmp_path` | Fix |
| `validator_error` shouldn't expose `str(exc)` to SSE | Emit short code; log sanitized detail server-side |
| Manual Path 3 verification not deterministic | Assert on `judge_path == "full_scan"`, not violation count |

---
**Spec source:** `docs/planning/V2_P2_CITATION_FIRST_QA_PLAN.md` (master, Path 2 ordering)
**Depends on:** Slice A SHIPPED 2026-05-01 (`SourceRegistry`, citation envelope hook, `[Sn]` protocol)
**Effort:** 3-5 days
**Cross-repo:** AI-excel-addin only. NO `agent-gateway` package change.

---

## 1. Goal

Catch the LLM when it hallucinates — make a quantitative claim with no source, or reference a fabricated `[Sn]` that doesn't exist in the per-turn `SourceRegistry`. Surface violations to the user via a non-blocking overlay (soft mode); position for a strict-mode flip once telemetry shows acceptable false-positive rate.

**Three failure modes Slice B catches:**

| # | Failure | Detection mechanism |
|---|---|---|
| 1 | Quantitative claim with no `[Sn]` (fact fabrication) | Regex finds claim, looks for `[Sn]` in same sentence; LLM judge confirms uncertain cases |
| 2 | `[S99]` reference not in registry (citation fabrication) | One-line check against `registered_indexes` (set built from snapshot) |
| 3 | Wrong attribution — `[S1]` cited but S1 is about something else | **Out of scope** — needs semantic verification of source content; future slice |

**Non-goals**
- Hard block (Path A) — toggleable via config flag, defaults to soft mode (overlay)
- Frontend rendering of overlays — Slice C/D
- Sub-agent text validation — same gating as Slice A; defer to Slice A.5
- Wrong-attribution detection (#3) — separate problem class; Slice F or later

---

## 2. Discovery summary

| Concern | Where | Notes |
|---|---|---|
| `text_delta` emission | `agent-gateway/agent_gateway/runner.py:1822-1828` | Each LLM token chunk goes to `event_log` via `_append({"type": "text_delta", "text": ...})`. Accumulator at `result.full_text:1827`. Direct stream — no existing intercept point. |
| Turn-complete moment | `agent-gateway/agent_gateway/runner.py:2576-2588` | After `_append_assistant_message_event`, runner emits `{"type": "turn_complete", "turn": N, "usage": ...}`. `turn.full_text` (line 2592) is the accumulated assistant text. **No existing `on_turn_complete` callback** in runner. |
| Event-log wrapping pattern | `api/research/runtime.py:194-227` (`ResearchPersistenceEventLog`) | Existing pattern: wrap `EventLog`, intercept on `append()`, pass-through or transform. Wrapped via `wrap_event_log_for_research(log, research_turn)` in `runtime.py:578,607`. **Slice B reuses this wrapping pattern** — no agent-gateway change needed. |
| `SourceRegistry` access | `api/agent/shared/citations.py` (Slice A) | Created per-runtime in `_build_chat_runtime`, captured by `_combined_tool_result_hook` closure. Has `.snapshot() -> list[Source]` accessor. Captured by Slice B's wrapper in the same closure. |
| Existing SSE consumers | `frontend/packages/connectors/.../useResearchChat.ts:93` (handles `text_delta` only); `api/dev/chat_cli.py` (event-type dispatch, falls through `[unhandled]`) | New event types are safe — both ignore unknown types. |
| Anthropic SDK availability | `requirements.txt` (already pinned) | Haiku calls go through the injected `JudgeClient` factory (§3.4.1) — operator credentials, separate from user BYOK, single auth surface. The factory itself wraps the Anthropic SDK; helpers do not construct SDK clients directly. |
| Telemetry layer | `api/agent/shared/hooks.py:300-315` (`update_model_log_hook`) writes per-tool JSON; existing `cost_tracker` records billing | Slice B logs violations via a sibling pattern (write to `api/logs/citation_validation.jsonl`) for later FP-rate analysis. |

---

## 3. Design

### 3.1 Validator module structure

Extend `api/agent/shared/citations.py` (Slice A's module) with validator components:

```python
# New types (extend Slice A)
@dataclass(frozen=True)
class Violation:
  span_start: int          # char offset in response text
  span_end: int
  claim_text: str          # the offending span verbatim
  reason: str              # "no_citation" | "fabricated_index" | "judge_flagged"
  detector: str            # "regex" | "judge"
  fabricated_index: str | None = None  # populated when reason == "fabricated_index"
  cited_indexes: list[str] | None = None  # populated when violations involves cited Sn

@dataclass(frozen=True)
class ValidationResult:
  violations: list[Violation]
  total_claims_detected: int
  total_sources_in_registry: int
  judge_called: bool
  judge_path: str | None     # "confirm" | "full_scan" | None
  warning_codes: list[str]   # R6: e.g. ["judge_auth_missing"], ["judge_budget_exhausted"]
  duration_ms: int
```

Three new functions:

```python
def detect_fabricated_indexes(text: str, registered_indexes: set[str]) -> list[Violation]:
  """Finds [Sn] references in text not present in registry. O(n) regex pass.
  Catches failure mode #2."""

def detect_unsourced_quantitative_claims(text: str) -> list[CandidateClaim]:
  """Regex over numeric patterns, returns candidates with their position
  and the [Sn] (or [unsourced]) tag found in the same sentence (or None)."""

async def validate_response(
  text: str,
  registry_snapshot: list[Source],   # R3: snapshot, not live registry (Codex R2 critical)
  *,
  mode: str = "full_hybrid",     # "regex_only" | "regex_with_confirmation" | "full_hybrid"
  qualitative_density_threshold: float = 0.02,
  judge_client_factory: Optional[Callable[[], "JudgeClient"]] = None,  # R5: thread through
  daily_budget_usd: float = 5.0,                                       # R5: thread through
) -> ValidationResult:
  """Runs the hybrid pipeline (regex → optional Haiku judge) and returns violations."""
```

### 3.2 Regex patterns

Combined pattern for quantitative-claim detection (R2 expanded per Codex R1 finance-coverage gap):

```python
# R4 fix per Codex R3: T/t added to currency suffix; compact_unit extended with bn/mn/mm;
# stable-reference negative lookbehind prevents Item 7B / Form 10K / Section 5.2 / Part II false matches.

_STABLE_REF_PREFIX = r"(?<!Item\s)(?<!Form\s)(?<!Section\s)(?<!Part\s)(?<!Chapter\s)(?<!Note\s)(?<!Rule\s)"

QUANT_PATTERN = re.compile(
  r"(?P<paren_currency>\(\$\d[\d,]*(?:\.\d+)?[BMKTbmkt]?\))"  # ($5M), ($3.2T)
  r"|(?P<currency>-?\$\d[\d,]*(?:\.\d+)?[BMKTbmkt]?\b)"       # $33.9B, -$5M, $3.2T (R4: T added)
  r"|(?P<compact_unit>" + _STABLE_REF_PREFIX +
    r"(?<![\w.])"                                              # R5: also block mid-decimal/mid-word starts (Section 5.2B, Note 3.2bn)
    r"\d+(?:\.\d+)?(?:bn|mn|mm|[BMKTbmkt])\b(?!\w))"           # 1.5B, 250M, 3.2T, 3.2bn
  r"|(?P<spelled>\d+(?:\.\d+)?\s+(?:billion|trillion|million)\b)"  # 1.5 billion, 3.5 trillion
  r"|(?P<percent>[+-]?\d+(?:\.\d+)?%)"                        # 22%, +250%, -3.5%
  r"|(?P<bps>\d+(?:\.\d+)?\s*bps\b)"                          # 200 bps
  r"|(?P<multiple>\d+(?:\.\d+)?x)\b"                          # 13x, 2.5x
  r"|(?P<ratio>\d+(?::|\s+to\s+)\d+)"                         # 2:1, 3 to 1
  r"|(?P<formatted>\d{1,3}(?:,\d{3})+\b)",                    # 64,552
  re.IGNORECASE,
)
```

**Notes**:
- `compact_unit` excludes its hits when preceded by `Item|Form|Section|Part|Chapter|Note|Rule` + space. Prevents `Item 7B`, `Form 10K`, `Section 5.2`, `Part II` etc. from false-matching as financial claims.
- `currency` includes T/t to handle `$3.2T`. Without this, `$3.2T` would split as `$3` (currency) + `2T` (compact_unit), causing two violations for one claim.
- `compact_unit` does NOT double-match `$1.5B` because the `$` is consumed by `currency` first.

Tests must cover: `Item 7B`, `Form 10K`, `Section 5.2`, `Section 5.2B` (R5: must NOT match `2B`), `Note 3.2bn` (R5: must NOT match `2bn`), `$3.2T`, `3.2bn` standalone, `1.5B` standalone, `$1.5B` (no double match), `($5M)`, `(-$5M)`, plus the original cases.

**Deliberately excludes:**
- Bare digits without currency/percent/multiple/comma/spelled-unit/bps/ratio marker (e.g., "Item 7", "5 hyperscalers", "Q3 2026")
- 4-digit years (`\b\d{4}\b`)
- Scientific notation (`1.5e9`) — deprioritized per Codex R1; rare in finance prose

False-negative trade-off: misses claims like "revenue of 100" (no unit at all). Acceptable.

**Tag extraction (R2 fix per Codex R1 critical):** parser handles `[S1]`, `[S1, S2]`, `[S1, S2, S3]`, `[S1][S2]`, `[unsourced: reason]`, malformed brackets:

```python
SN_REF_PATTERN = re.compile(r'\bS\d+\b')                    # finds individual Sn anywhere
UNSOURCED_PATTERN = re.compile(r'\[unsourced[^\]]*\]')      # whole-bracket match
BRACKET_BLOCK_PATTERN = re.compile(r'\[([^\]]*)\]')         # any bracketed content

def extract_sn_refs(text: str) -> list[tuple[str, int]]:
  """Returns [(sn_label, position), ...] for every S\d+ inside any bracket block,
  EXCEPT blocks whose content starts with 'unsourced' (R3 fix per Codex R2:
  prevents false-matching `S1` inside `[unsourced: claim about S1]`)."""
  refs = []
  for block_match in BRACKET_BLOCK_PATTERN.finditer(text):
    inner = block_match.group(1)
    if inner.lstrip().lower().startswith("unsourced"):
      continue  # this is an [unsourced: ...] block; UNSOURCED_PATTERN handles it separately
    for sn_match in SN_REF_PATTERN.finditer(inner):
      refs.append((sn_match.group(0), block_match.start() + 1 + sn_match.start()))
  return refs

def has_unsourced_marker(window_text: str) -> bool:
  return bool(UNSOURCED_PATTERN.search(window_text))
```

**Sentence-window helper (R3 fix per Codex R2 §sentence-decimal): scans the FULL sentence containing the claim, ignoring period-between-digits (e.g., `1.5x`)**. Catches "According to [S1], revenue was $33.9B." AND "[S1] Valuation was 1.5x revenue and EBITDA was $5M".

```python
# Boundary regex (R4 fix per Codex R3 §sentence-boundary):
#   - period: terminal only when NOT between digits (so 1.5x and $33.9B don't split)
#   - ! and ?: always terminal (Q3., $5.0! both end sentences cleanly)
#   - \n: always terminal
_SENTENCE_BOUNDARY = re.compile(r"(?<!\d)\.|\.(?!\d)|[!?]|\n")

def find_sentence_window(text: str, claim_start: int, claim_end: int) -> tuple[int, int]:
  # Find previous boundary by walking right-to-left
  start = 0
  for m in _SENTENCE_BOUNDARY.finditer(text[:claim_start]):
    start = m.end()
  # Find next boundary after claim_end
  next_match = _SENTENCE_BOUNDARY.search(text, claim_end)
  end = next_match.start() if next_match else len(text)
  end = min(end, claim_end + 200)  # cap at 200 chars to avoid runaway sentences
  return start, end

def claim_is_sourced(text: str, claim_start: int, claim_end: int) -> tuple[bool, list[str]]:
  s, e = find_sentence_window(text, claim_start, claim_end)
  window = text[s:e]
  if has_unsourced_marker(window):
    return True, []  # explicitly unsourced — valid per protocol
  refs = extract_sn_refs(window)
  return bool(refs), [r[0] for r in refs]
```

### 3.3 Decision tree (hybrid)

```python
async def validate_response(
  text, registry_snapshot,
  *,
  mode="full_hybrid",
  qualitative_density_threshold=0.02,
  judge_client_factory=None,        # R5: threaded through (Codex R4 critical)
  daily_budget_usd=5.0,
):
  t0 = time.time()

  # Step 1: fabricated-index check (always runs, regardless of mode)
  registered_indexes = {f"S{src.index}" for src in registry_snapshot}
  fab_violations = detect_fabricated_indexes(text, registered_indexes)

  # Step 2: regex quantitative-claim scan
  candidates = detect_unsourced_quantitative_claims(text)
  unsourced = [c for c in candidates if c.tag is None]

  # Step 3: hybrid escalation — judge paths require non-None factory AND remaining budget
  # R6 fix per Codex R5: hoist budget check so budget-exhausted state is indistinguishable
  # from missing-auth at the decision-tree level — both fall through to regex-only,
  # preserving regex-flagged candidates in `unsourced` so they surface as violations.
  judge_path = None
  judge_called = False
  judge_violations: list[Violation] = []
  warning_codes: list[str] = []

  judge_available = judge_client_factory is not None
  if not judge_available:
    warning_codes.append("judge_auth_missing")
  elif _get_judge_spend_today_usd() >= daily_budget_usd:
    judge_available = False
    warning_codes.append("judge_budget_exhausted")

  if mode == "regex_only" or not judge_available:
    pass  # regex-only path; `unsourced` candidates retained → become violations below

  elif mode == "regex_with_confirmation" and unsourced:
    judge_path = "confirm"
    judge_called = True
    judge_violations = await _judge_confirm_flags(
      text, unsourced, judge_factory=judge_client_factory
    )
    unsourced = []  # judge took over

  elif mode == "full_hybrid":
    if unsourced:
      judge_path = "confirm"
      judge_called = True
      judge_violations = await _judge_confirm_flags(
        text, unsourced, judge_factory=judge_client_factory
      )
      unsourced = []
    elif _looks_qualitative(text, threshold=qualitative_density_threshold):
      judge_path = "full_scan"
      judge_called = True
      judge_violations = await _judge_full_scan(
        text, registry_snapshot, judge_factory=judge_client_factory
      )

  # Combine — `unsourced` retains regex-flagged violations only when judge was unavailable
  # or skipped (judge_auth_missing or budget-exhausted); these surface as regex violations
  all_violations = fab_violations + [
    Violation(
      span_start=c.start, span_end=c.end, claim_text=c.text,
      reason="no_citation", detector="regex"
    ) for c in unsourced
  ] + judge_violations

  return ValidationResult(
    violations=all_violations,
    total_claims_detected=len(candidates),
    total_sources_in_registry=len(registry_snapshot),
    judge_called=judge_called,                    # R6: only True when a judge call actually ran
    judge_path=judge_path,
    warning_codes=warning_codes,                  # R6: surfaces judge_auth_missing / judge_budget_exhausted
    duration_ms=int((time.time() - t0) * 1000),
  )
```

Both `_judge_confirm_flags` and `_judge_full_scan` take `judge_factory` only — budget + auth gating is hoisted to `validate_response` (R6 fix):

```python
async def _judge_confirm_flags(text, candidates, *, judge_factory):
  # judge_factory is guaranteed non-None and budget guaranteed available by caller (R6)
  client = judge_factory()
  ...
```

### 3.4 LLM judge — auth, prompts, budget

#### 3.4.1 Auth (R2 fix per Codex R1 §judge-auth)

Direct `anthropic.Anthropic()` calls bypass the gateway's BYOK/OAuth credential path. R2 routes the judge through a **factory injected at `_build_chat_runtime`**:

```python
def _build_judge_client_factory(settings) -> Optional[Callable[[], JudgeClient]]:
  """Returns a factory the wrapper calls to get a Haiku-bound client.
  Returns None if OPERATOR_ANTHROPIC_API_KEY is unset — validator gracefully falls
  back to regex-only with a one-time `judge_auth_missing` warning logged
  (R3 fix per Codex R2 §judge-missing-key).

  Default uses operator credentials (not user BYOK) — validator cost is
  operator-side institutional-trust spend, not user-billed."""

  api_key = settings.operator_anthropic_api_key
  if not api_key:
    log.warning(
      "OPERATOR_ANTHROPIC_API_KEY unset — citation_validation falling back to "
      "regex-only mode (judge_auth_missing). Set the env var to enable hybrid."
    )
    return None

  def factory() -> JudgeClient:
    return JudgeClient(
      api_key=api_key,                                         # explicitly NOT user BYOK
      model="claude-haiku-4-5-20251001",
      timeout=settings.citation_validation_judge_timeout_s,    # default 5s
    )
  return factory
```

The wrapper checks `if self._judge_factory is None` before any judge call and falls back to regex_only behavior, ensuring graceful degradation when credentials are missing.

`JudgeClient` is a thin wrapper around the existing Anthropic SDK that:
- Uses operator API key (env: `OPERATOR_ANTHROPIC_API_KEY`, separate from user BYOK)
- Owns the prompt + parse logic
- Records cost to `api/logs/citation_validation.jsonl` (see §3.8 + §7.7)

**Decision rationale**: validator runs on every Hank turn. Charging users for institutional-trust validation is wrong UX; the operator absorbs the cost. Documented as Slice B's billing model.

#### 3.4.2 Daily cost cap

R2 ships the cost cap (Codex R1 said don't defer); R6 hoisted budget gating to `validate_response`. The judge helpers themselves are thin call+parse — no internal budget check (R7 fix per Codex R6).

`_get_judge_spend_today_usd()` is called once at the top of `validate_response` (per the decision tree in §3.3); the helper aggregates today's `judge_call_cost_usd` from `api/logs/citation_validation.jsonl`. If it returns ≥ `daily_budget_usd`, `validate_response` sets `judge_available=False` and adds `judge_budget_exhausted` to `warning_codes` — the regex-only path then runs with `unsourced` retained.

```python
def _get_judge_spend_today_usd() -> float:
  """Sum judge_call_cost_usd from today's entries in api/logs/citation_validation.jsonl."""
  ...

async def _judge_confirm_flags(text, candidates, *, judge_factory):
  # R7: caller (validate_response) guarantees judge_factory is non-None and budget is available
  try:
    client = judge_factory()
    return await client.judge(prompt)
  except Exception as exc:
    log.warning("judge call failed: %s; falling back to regex-only for this turn", exc)
    return []
```

`_get_judge_spend_today_usd()` reads from `api/logs/citation_validation.jsonl` (today's entries) and sums `judge_call_cost_usd`. Cheap O(N-entries-today). (Future migration to a different store is out of scope for Slice B.)

#### 3.4.3 Path 2a — confirm regex flags (small, fast)

```
You are a citation auditor for a financial research assistant. The response
below was flagged by a regex for a potentially unsourced quantitative claim.
Determine whether the flagged span is:
(a) a load-bearing financial claim that should cite a source, or
(b) a stable reference (item number, date, identifier, list count) that
    doesn't require citation.

Response:
"""
{response_text}
"""

Flagged span: "{claim_text}" at chars {span_start}-{span_end}

Output JSON only:
{"verdict": "claim" | "reference", "reason": "<one short clause>"}
```

Sent to `claude-haiku-4-5-20251001` via injected `judge_client_factory`. Expected: ~150 input + ~30 output tokens. ~$0.0002 per call. <1s latency. **No `response_format` parameter** (not available in `anthropic==0.93.0` per Codex R1) — relies on prompt-level "Output JSON only" + defensive parse.

**Path 2b — full scan on qualitative-heavy responses** (larger, conditional):

```
You are a citation auditor. The available registered sources are:
{source_table}     # e.g., [S1] MSFT FY26 Q2 10-Q (cloud_revenue), ...

The assistant's response below contains assertions. For each factual claim
(quantitative OR qualitative) that depends on data, identify the [Sn] that
cites it. If no [Sn] is present, return as a violation. Ignore claims that
are non-assertional (questions, "let me search", section headers).

Response:
"""
{response_text}
"""

Output JSON only:
{
  "violations": [
    {"claim": "...", "reason": "...", "approx_span": [start, end]}
  ]
}
```

Sent to Haiku. Expected: ~500 input + ~200 output. ~$0.002 per call. ~2s latency.

### 3.5 SSE event shape

New event type `citation_validation` emitted into the SSE stream by the wrapper (per §3.6.1, between turn_complete and the eventual stream_complete):

```json
{
  "type": "citation_validation",
  "schema_version": 1,
  "turn": 3,
  "violations": [
    {
      "span_start": 142,
      "span_end": 148,
      "claim_text": "$19B",
      "reason": "no_citation",
      "detector": "regex"
    },
    {
      "span_start": 220,
      "span_end": 226,
      "claim_text": "[S99]",
      "reason": "fabricated_index",
      "detector": "regex",
      "fabricated_index": "S99"
    }
  ],
  "violation_count": 2,
  "total_claims_detected": 5,
  "total_sources_in_registry": 7,
  "judge_called": true,
  "judge_path": "confirm",
  "warning_codes": [],
  "duration_ms": 850,
  "soft_mode": true
}
```

When the judge is unavailable, the event surfaces the reason via `warning_codes`:
- `["judge_auth_missing"]` — `OPERATOR_ANTHROPIC_API_KEY` unset; regex-only path
- `["judge_budget_exhausted"]` — daily budget reached; regex-only path
- `["validation_timeout"]` — drain timeout fired (also signals via `validator_error_code`)

**No `_event_only` field needed**: Slice A's `_event_only` filter applies only to hook-returned extra blocks at `runner.py:2797`, `sdk_runner.py:387`, `transcript.py:56`, none of which pull from the event_log. The `citation_validation` event flows event-log → SSE → transcript persistence path; it's never round-tripped into the next-turn user message because nothing pulls EventLog entries into model-bound payloads.

**Persisted in transcripts** (R3 acknowledgement per Codex R2 §event-persistence): `server.py:696` writes every non-heartbeat event to chat transcript by default. Slice B accepts this — validation results are part of the chat record, useful for audit and post-hoc FP-rate analysis. Slice D's React UI may filter the field at render time if it duplicates UI-rendered overlays.

### 3.6 Wrapper architecture (runner + event-log)

Per Codex R1 §1, the wrapper has TWO layers:

#### 3.6.1 Event-log wrapper

New module `api/agent/shared/citation_validation_event_log.py`:

```python
class CitationValidationEventLog:
  """Wraps EventLog. On turn_complete, snapshots text + registry synchronously
  and schedules validation. On stream_complete, BUFFERS the terminal event
  instead of forwarding (the runner wrapper drains pending validations and
  flushes the buffered terminal). On stream_retry, clears the text buffer."""

  def __init__(
    self,
    inner: Any,
    registry: SourceRegistry,
    *,
    mode: str = "full_hybrid",
    qualitative_density_threshold: float = 0.02,
    judge_client_factory: Callable[[], Any] | None = None,
    daily_budget_usd: float = 5.0,
  ) -> None:
    self._inner = inner
    self._registry = registry
    self._mode = mode
    self._density_threshold = qualitative_density_threshold
    # R4 fix per Codex R3 critical: preserve None to enable judge_auth_missing fallback.
    # Do NOT use `judge_client_factory or _default_factory` — that would discard None
    # and silently re-enable a default judge path even when auth is missing.
    self._judge_factory = judge_client_factory  # may be None — wrapper checks before calling
    self._daily_budget_usd = daily_budget_usd
    self._buffer = ""              # accumulates text_delta payloads
    self._current_turn = 0
    self._pending_tasks: list[asyncio.Task] = []
    self._buffered_terminal: Optional[dict] = None
    self._system_generated_text_after: Optional[int] = None  # turn after which to skip validation

  def append(self, event: dict) -> Optional[Any]:
    event_type = event.get("type")

    # System-generated text exclusion (Codex R1 §16)
    if event_type in ("budget_exceeded", "max_turns_reached"):
      self._system_generated_text_after = self._current_turn
      return self._inner.append(event)

    # Buffer terminal events instead of forwarding immediately (Codex R1 §1)
    if event_type in ("stream_complete", "error"):
      if self._buffered_terminal is None:
        self._buffered_terminal = dict(event)
        # Don't forward yet — runner wrapper's drain() will flush after pending validation
        return None
      return self._inner.append(event)

    # text_delta accumulation (skip if system-generated)
    if event_type == "text_delta":
      if self._system_generated_text_after is None:
        text = event.get("text") or ""
        if isinstance(text, str):
          self._buffer += text
      return self._inner.append(event)

    # stream_retry — clear buffer for failed-turn text (Codex R1 §wrapper-retry)
    if event_type == "stream_retry":
      self._buffer = ""
      return self._inner.append(event)

    # turn_complete — capture snapshot synchronously, schedule async validation
    if event_type == "turn_complete":
      self._current_turn = event.get("turn", self._current_turn + 1)
      buffered_text = self._buffer
      self._buffer = ""
      registry_snapshot = self._registry.snapshot()  # SYNC capture (Codex R1 §3)

      # Skip validation if system-generated text contaminated this turn
      if self._system_generated_text_after is not None:
        return self._inner.append(event)

      task = asyncio.create_task(
        self._validate_and_emit(buffered_text, self._current_turn, registry_snapshot)
      )
      self._pending_tasks.append(task)
      return self._inner.append(event)

    return self._inner.append(event)

  async def drain(self, timeout: float = 5.0) -> None:
    """Await all pending validation tasks. Called by runner wrapper before flushing
    terminal event. Caps at `timeout` seconds; remaining tasks are cancelled and a
    timeout event is emitted (R3 fix per Codex R2 §drain-timeout-silent)."""
    if not self._pending_tasks:
      return
    pending = [t for t in self._pending_tasks if not t.done()]
    if not pending:
      return
    try:
      await asyncio.wait_for(asyncio.gather(*pending, return_exceptions=True), timeout=timeout)
    except asyncio.TimeoutError:
      log.warning("citation_validation drain timed out after %ss; %d tasks pending",
                  timeout, len(pending))
      for task in pending:
        if not task.done():
          task.cancel()
      # Emit a single timeout event so consumers can distinguish "validator
      # timed out" from "validator never ran" or "no event bug"
      self._inner.append({
        "type": "citation_validation",
        "schema_version": 1,
        "turn": self._current_turn,
        "violations": [],
        "violation_count": 0,
        "validator_error_code": "validation_timeout",
        "warning_codes": ["validation_timeout"],     # R9: parity with normal-event field for consistent consumer handling
        "pending_task_count": len(pending),
      })

  def flush_pending_terminal(self) -> None:
    """Forward the buffered terminal event after drain(). Idempotent."""
    if self._buffered_terminal is None:
      return
    terminal = self._buffered_terminal
    self._buffered_terminal = None
    self._inner.append(terminal)

  async def _validate_and_emit(
    self, text: str, turn: int, registry_snapshot: list[Source]
  ) -> None:
    try:
      result = await validate_response(
        text=text,
        registry_snapshot=registry_snapshot,    # snapshot, not live registry (Codex R1 §3)
        mode=self._mode,
        qualitative_density_threshold=self._density_threshold,
        judge_client_factory=self._judge_factory,
        daily_budget_usd=self._daily_budget_usd,
      )
    except Exception as exc:
      log.warning("citation_validation failed (graceful): %s", exc)
      self._inner.append({
        "type": "citation_validation",
        "schema_version": 1,
        "turn": turn,
        "violations": [],
        "violation_count": 0,
        "validator_error_code": "validator_internal_error",  # short code, not str(exc) (Codex R1 §minor)
        "warning_codes": [],                                  # R10: parity with normal + timeout events
      })
      return

    self._inner.append({
      "type": "citation_validation",
      "schema_version": 1,
      "turn": turn,
      "violations": [_violation_to_dict(v) for v in result.violations],
      "violation_count": len(result.violations),
      "total_claims_detected": result.total_claims_detected,
      "total_sources_in_registry": result.total_sources_in_registry,
      "judge_called": result.judge_called,
      "judge_path": result.judge_path,
      "warning_codes": result.warning_codes,    # R7: thread judge_auth_missing / judge_budget_exhausted to consumer
      "duration_ms": result.duration_ms,
      "soft_mode": True,
    })

    _log_validation_telemetry(turn, result)

  # Pass-through delegation for non-intercepted events
  def close(self, error: str | None = None) -> None:
    self._inner.close(error)

  async def iter_from(self, after_seq: int = 0):
    async for entry in self._inner.iter_from(after_seq):
      yield entry

  @property
  def entries(self):
    return self._inner.entries

  @property
  def closed(self):
    return self._inner.closed
```

#### 3.6.2 Runner wrapper

New module `api/agent/shared/citation_validation_runner.py`:

```python
class RunnerWithCitationValidation:
  """Thin wrapper around AgentRunner. Awaits inner run(), then drains pending
  validation tasks, then flushes the buffered terminal event. Preserves the
  AgentRunner external interface."""

  def __init__(self, inner_runner: Any, event_log_wrapper: CitationValidationEventLog,
               *, drain_timeout: float = 5.0) -> None:
    self._inner = inner_runner
    self._event_log_wrapper = event_log_wrapper
    self._drain_timeout = drain_timeout

  async def run(self, *args, **kwargs) -> Any:
    try:
      result = await self._inner.run(*args, **kwargs)
    finally:
      # Always drain + flush, even on exception, so users get partial validation results
      await self._event_log_wrapper.drain(timeout=self._drain_timeout)
      self._event_log_wrapper.flush_pending_terminal()
    return result

  # Delegate attribute access for any external `runner.foo` calls (e.g., resume handlers)
  def __getattr__(self, name: str) -> Any:
    return getattr(self._inner, name)
```

### 3.7 Wire-in

In `api/agent/interactive/runtime.py`, the wrapper requires Anthropic provider AND modifies both event_log and runner construction:

```python
def _build_validation_wrapper_pair(
    event_log, source_registry, *, settings, provider_name: str,
) -> tuple[Any, Optional[CitationValidationEventLog]]:
  """Returns (wrapped_event_log, wrapper_handle_or_None). Handle is None if disabled."""
  if not settings.citation_validation_enabled:
    return event_log, None
  if provider_name != "anthropic":
    # R4 scope choice (per Codex R3 §provider-gate-rationale):
    #   `agent-sdk` is mechanically incompatible — sdk_runner.py emits no turn_complete event.
    #   `openai` and `codex` go through generic AgentRunner with text_delta + turn_complete
    #   (mechanically compatible per runner.py:1822, 2584), but their prompt-adherence to
    #   [Sn] format and validator latency budget are unverified.
    # Slice B ships Anthropic-only as a blast-radius decision. Slice B.5 may extend the
    # allowlist after Anthropic telemetry confirms behavior.
    log.info("citation_validation skipped for non-anthropic provider: %s", provider_name)
    return event_log, None

  wrapper = CitationValidationEventLog(
    inner=event_log,
    registry=source_registry,
    mode=settings.citation_validation_mode,           # "full_hybrid"
    qualitative_density_threshold=settings.qualitative_density_threshold,  # 0.02
    judge_client_factory=_build_judge_client_factory(settings),
    daily_budget_usd=settings.citation_validation_budget_usd_per_day,      # 5.0
  )
  return wrapper, wrapper


# In _build_chat_runtime, after:
#   research_event_log = wrap_event_log_for_research(event_log, research_turn)
# Add:
#   wrapped_log, validation_wrapper = _build_validation_wrapper_pair(
#       research_event_log, source_registry, settings=..., provider_name=provider_name,
#   )
#
# Then in the runner builder, after constructing AgentRunner:
#   if validation_wrapper is not None:
#     runner = RunnerWithCitationValidation(runner, validation_wrapper)
```

Settings live in env (defaults: `CITATION_VALIDATION_ENABLED=true`, `CITATION_VALIDATION_MODE=full_hybrid`, `CITATION_VALIDATION_QUALITATIVE_THRESHOLD=0.02`, `CITATION_VALIDATION_BUDGET_USD_PER_DAY=5.0`).

### 3.8 Telemetry log

R2 fix per Codex R1 §telemetry-location: write to `api/logs/citation_validation.jsonl` (sibling of `api/logs/cost_tracker.py:43-130`), NOT repo-root `logs/` (gitignored at `.gitignore:22`).

```json
{
  "timestamp": "2026-05-02T19:30:00Z",
  "session_id": "abc",
  "turn": 3,
  "violation_count": 2,
  "judge_called": true,
  "judge_path": "confirm",
  "judge_call_cost_usd": 0.0002,
  "total_claims": 5,
  "duration_ms": 850,
  "violations": [{"reason": "no_citation", "detector": "regex"}, ...]
}
```

Used to: (a) tune density threshold via observed FP rate, (b) source for `_get_judge_spend_today_usd()` budget enforcement, (c) input to FP-rate-acceptable decision before flipping to strict mode.

JSONL is chosen for grep-ability during early FP-rate analysis. Slice B does not migrate the store; a future slice may revisit if entry volume justifies.

### 3.9 Backward compatibility

- Existing consumers ignore unknown SSE event types → safe
- The `citation_validation` event is NOT a hook-returned extra block, so Slice A's `_event_only` filter doesn't apply (and isn't needed). The event flows only through the event-log → SSE path; there's no automatic round-trip into the next-turn user message
- **Persisted in chat transcripts** by default (R3 acknowledgement per Codex R2 §event-persistence): `server.py:696` writes every non-heartbeat event to transcript. Slice B accepts this — validation results are part of the chat record, useful for audit. Slice D may filter at render time if it duplicates UI-rendered overlays
- Validator failures degrade gracefully — emit empty `citation_validation` with `validator_error_code` short string, never block the response

---

## 4. Files touched

**New (AI-excel-addin)**
- `api/agent/shared/citation_validation_event_log.py` — event-log wrapper with drain/flush_pending_terminal. ~150 LOC (up from R1 ~100 due to lifecycle additions).
- `api/agent/shared/citation_validation_runner.py` — runner wrapper that awaits inner.run() then drains. ~40 LOC.
- `api/agent/shared/citation_judge.py` — `JudgeClient` + prompts + budget guard + cost tracking. ~150 LOC (up from R1 ~120).
- `tests/agent/shared/test_citation_validator.py` — regex, hybrid decision tree, judge mocks via factory. ~280 LOC.
- `tests/agent/shared/test_citation_validation_event_log.py` — wrapper integration including drain, flush, terminal-event buffering, stream_retry, system-generated text exclusion. ~150 LOC (up from R1 ~80).
- `tests/agent/shared/test_citation_validation_runner.py` — runner-wrapper drain semantics, timeout, exception path. ~80 LOC.

**Edited (AI-excel-addin)**
- `api/agent/shared/citations.py` — extend with `Violation`, `ValidationResult`, `validate_response` (snapshot-based), `detect_fabricated_indexes`, `detect_unsourced_quantitative_claims`, `_looks_qualitative`, tag-extraction helpers. ~200 LOC delta (up from R1 ~150).
- `api/agent/interactive/runtime.py` — wire `_build_validation_wrapper_pair` + runner-wrapper application. Anthropic-only path; SDK is no-op. ~20 LOC delta (up from R1 ~10).
- `tests/agent/interactive/test_citation_integration.py` — end-to-end Anthropic-mode validation with terminal-event ordering. ~60 LOC delta.

**Untouched**
- `packages/agent-gateway/` — no gateway-package change.
- `mcp_tools/corpus/` (risk_module) — no corpus tool change.
- Frontend, dev CLI — Slice C/D will surface the new event.

---

## 5. Step-by-step implementation

| # | Step | Verification |
|---|---|---|
| 1 | Implement `Violation` + `ValidationResult` dataclasses + `detect_fabricated_indexes` (one-line regex over `[Sn]` minus `registry_snapshot`). | Unit tests: empty text, no Sn references, valid Sn references, single fabricated, multi-fabricated. |
| 2 | Implement `detect_unsourced_quantitative_claims` with `QUANT_PATTERN` + `find_tag_in_window`. | Unit tests: 8 cases — currency sourced, currency unsourced, percent sourced/unsourced, multiple, comma-formatted, year (should NOT trigger), section number (should NOT trigger). |
| 3 | Implement `_looks_qualitative` density heuristic. | Unit tests: short text returns False; high-density returns False; low-density returns True. |
| 4 | Implement `_judge_confirm_flags` and `_judge_full_scan` in `citation_judge.py` against the injected `JudgeClient` / `judge_factory` from §3.4.1 (NOT direct `anthropic.Anthropic` — see §3.4.1 rationale). Mock the factory in tests. | Unit tests with mocked judge responses: confirm-claim → keep flag; confirm-reference → drop flag; full-scan returns violations parsed correctly. |
| 5 | Implement `validate_response` orchestrator. | Unit tests: regex_only mode skips judge; regex_with_confirmation calls judge on flags only; full_hybrid hits all three paths based on input. |
| 6 | Implement `CitationValidationEventLog` wrapper. | Unit tests: text_delta accumulation correct; turn_complete fires validation task; pass-through for other events; graceful failure on validator exception. |
| 7 | Wire into `_build_chat_runtime`. | Integration test: build runtime, simulate text_delta + turn_complete sequence, assert `citation_validation` event emitted with correct payload. |
| 8 | Add telemetry logging to `api/logs/citation_validation.jsonl`. | Unit test for log shape (using `tmp_path` per Codex R1 §minor); live verification creates a file. |
| 9 | Live dev-chat verification with three scenarios: clean response (no violations), response with intentional unsourced number (regex flag), response with qualitative claims (judge full scan). | Manual: inspect `--raw` output for `citation_validation` event in each case. |

---

## 6. Test plan

**Unit (`tests/agent/shared/test_citation_validator.py`)**
- `detect_fabricated_indexes`: 5 cases.
- `detect_unsourced_quantitative_claims`: 12 cases (4 currency, 3 percent, 1 multiple, 1 formatted, 3 should-not-trigger).
- `find_tag_in_window`: same-sentence + cross-sentence + missing.
- `_looks_qualitative`: 4 density bands.
- `_judge_confirm_flags`: 3 cases (claim verdict, reference verdict, parse error).
- `_judge_full_scan`: 3 cases (clean, single violation, multiple).
- `validate_response`: mode matrix (3 modes × 3 input types = 9 cases).

**Wrapper (`tests/agent/shared/test_citation_validation_event_log.py`)**
- text_delta accumulation across multiple chunks.
- turn_complete fires validation, emits event.
- Multi-turn: each turn validated independently, registry shared.
- Validator exception path: emits empty event with `validator_error_code`.
- Pass-through verification for unrelated event types.

**Integration (`tests/agent/interactive/test_citation_integration.py`)**
- Build runtime with citation validator wired in.
- Simulate `filings_search` tool call → text_delta sequence with `[S1]`, `$33.9B [S1]`, `$19B` (unsourced) → turn_complete.
- Assert `citation_validation` event emitted with one violation for `$19B`.

**Live (manual)**
- Three dev_chat_cli scenarios:
  - Clean: corpus question with proper citations (expect zero violations).
  - Hallucinated number: ask question that may push LLM to extrapolate (expect at least one regex flag).
  - Qualitative: ask "what is Microsoft's strategic position in cloud" type question (expect judge full-scan).

---

## 7. Risks and open questions

| # | Risk / question | Mitigation |
|---|---|---|
| 7.1 | **Lifecycle race with terminal events** (R2 fix per Codex R1 critical) — `EventLog.append()` is sync; closes on `stream_complete`/`error`. | **Solved**: event-log wrapper buffers terminal events instead of forwarding (§3.6.1); runner wrapper awaits `drain(timeout=5s)` then `flush_pending_terminal()` after `inner.run()` completes (§3.6.2). The 5s drain timeout protects against runaway judge calls. |
| 7.2 | **Path 3 tail latency** ~2s on qualitative-heavy turns | Path 3 only fires when regex finds 0 claims AND text is qualitative-heavy AND >30 words. Drain timeout caps the wait. Telemetry tracks judge-call rate; if >30%, retune density threshold. |
| 7.3 | **Haiku judge returns malformed JSON** | Prompt-level "Output JSON only" + defensive `json.loads` with try/except. On parse failure, fail open (no judge violations, regex-only path). No `response_format` parameter (not in `anthropic==0.93.0` per Codex R1). |
| 7.4 | **Daily cost cap** (R2 fix per Codex R1: ship in B, don't defer) | `CITATION_VALIDATION_BUDGET_USD_PER_DAY=5.0` env var. R6 fix: budget check hoisted to `validate_response` (single check at start of validation pipeline) — when `_get_judge_spend_today_usd() >= daily_budget_usd`, sets `judge_available=False` + `warning_codes=["judge_budget_exhausted"]`, falls back to regex-only with `unsourced` retained as violations. Per-turn worst case ~$0.002 (Path 3). |
| 7.5 | **Sub-agent text validation** (R2 fix per Codex R1: sub-agents get fresh EventLog at `runner.py:812-817`) | Wrapper structurally cannot see sub-agent text (separate EventLog instances). Slice A.5 will design sub-agent text propagation if needed. Slice B's wrapper has NO `_is_sub_agent_session` check (was wrong in R1). |
| 7.6 | **Regex FP on stable references** | R2 patterns exclude 4-digit years + bare digits. Path 2 confirm step strips remaining FPs via judge. Telemetry tracks FP rate. |
| 7.7 | **Judge cost-tracking integration** | Slice B ships JSONL at `api/logs/citation_validation.jsonl` for grep-ability + simple budget queries. Future slice may revisit the store; not in scope here. |
| 7.8 | **Settings management** | Env vars: `CITATION_VALIDATION_ENABLED`, `_MODE`, `_QUALITATIVE_THRESHOLD`, `_BUDGET_USD_PER_DAY`, `_JUDGE_TIMEOUT_S`, `OPERATOR_ANTHROPIC_API_KEY`. No new config file. |
| 7.9 | **Validator must fail open** — failures NEVER affect user response | All validation paths wrapped in try/except. `validator_error_code` (short string, NOT raw `str(exc)` per Codex R1 §minor) emitted on internal failure; raw detail logged server-side. Drain timeout enforces upper bound on wait. |
| 7.10 | **Strict mode flip** | Out of scope for Slice B. Requires (a) ≥7 days of telemetry showing FP rate <5%, (b) UX design for block path. |
| 7.11 | **Judge auth bypasses BYOK/OAuth** (R2 fix per Codex R1) | Operator credentials, not user BYOK. `OPERATOR_ANTHROPIC_API_KEY` env var. Validator cost is operator-side institutional-trust spend. Documented in §3.4.1. |
| 7.12 | **System-generated text after `turn_complete`** (R2 fix per Codex R1) — `runner.py:2626-2649` (budget) and `2469-2483` (max-turns) append text without a real LLM turn | Wrapper detects `budget_exceeded`/`max_turns_reached` events and excludes any subsequent text from validation (`_system_generated_text_after`). |
| 7.13 | **Quantitative claim with `[unsourced: ...]`** (Codex R1 question) — does the protocol allow this? | Yes — protocol-compliant per Slice A's prompt block. Treated as VALID by the validator (claim_is_sourced returns True if `[unsourced: ...]` is in the sentence window). The user can audit the explicit unsourced reasoning rather than getting a hidden hallucination. |
| 7.14 | **`citation_validation` event persistence** | **Yes, persisted in chat transcripts** (R3 acknowledgement per Codex R2): `server.py:696` writes every non-heartbeat event to transcript by default. Slice B accepts this — validation results are useful for audit and post-hoc FP-rate analysis. Timeout events also persisted; cheap to filter at render time later if noisy. |

---

## 8. Codex R10 review brief

When sending R10 to Codex:
- Cwd: `/Users/henrychien/Documents/Jupyter/AI-excel-addin`
- Sandbox: `read-only`
- Reasoning: high
- R10 is the final paperwork pass. The R10 changelog (top of plan) lists 3 fixes per Codex R9: SQLite reference removed at line 821, R8/R9 stale labels updated to R10, validator-internal-error event got `warning_codes: []` for parity.

Specific things to verify:
1. Schema parity across all three `citation_validation` event variants — normal, timeout, validator-internal-error — all include `warning_codes`.
2. No remaining `SQLite` references outside changelog/history.
3. No remaining `anthropic.Anthropic(` references outside changelog/history or §3.4.1 rationale.
4. R10 changelog labels are correct.

If R10 PASSes, please say so unambiguously — I want to send to Codex for implementation next.

**Output format** same as prior reviews.
