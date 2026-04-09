# LLM Briefing Experiment — Validate Editorial Judgment Before Building Pipeline

**Status:** VALIDATED (Phase 1 complete)
**Created:** 2026-04-02
**Validated:** 2026-04-07
**Depends on:** None (uses existing infrastructure only)
**Related:** `OVERVIEW_EDITORIAL_PIPELINE_DESIGN.md` (the full pipeline this validates)

## Validation Results (2026-04-07)

All three changes implemented. The AI produces sharp editorial briefings with correct alert/default mode detection, editorial memory-driven lead selection, and structured block output.

**Key findings:**
- Editorial judgment is strong — AI correctly picks ALERT state, leads with the right risk gap, frames the "worst combination" (beta + underperformance).
- `editorial_memory` meaningfully shapes output — surfaces events matching `care_about`, respects `less_interested_in`, uses the briefing philosophy tone.
- Skill-based workflow (morning-briefing.md) produces better output than the embedded system prompt version — denser guidance, output quality examples teach the voice, emergent multi-skill chaining (AI suggests `risk-review` as follow-up).
- UI blocks work end-to-end but are better used sparingly — prose carries the editorial weight, blocks useful only for the hero metric. Left enabled for continued testing.
- Design artifacts (GeneratedArtifact, MetricStrip, etc.) belong in the Overview pipeline, not chat.

**Architecture decision:** briefing workflow moved from embedded system prompt to skill file (`workspace/notes/skills/morning-briefing.md`). System prompt retains only the user profile data (`_build_editorial_memory_section`). Skills are now version-controlled.

**Next steps:**
- Run daily briefings for 1-2 weeks to test consistency across portfolio states (alert vs quiet days, surprise moves, post-trade).
- Optional: add "Morning Briefing" sidebar button (Change 3, convenience only).
- When ready: proceed to full Overview Editorial Pipeline (OVERVIEW_EDITORIAL_PIPELINE_DESIGN.md).

## Purpose

Before building the 4-generator editorial pipeline, test whether the LLM can make good editorial judgments by giving it the tools + editorial_memory and asking it to compose a morning briefing. This answers the core question: **can the AI pick the right lead story?**

If yes, the deterministic pipeline becomes a performance optimization (fast path).
If no, we know exactly where the judgment fails and can design scoring weights to compensate.

## What Exists Already

| Component | Status | Location |
|-----------|--------|----------|
| `/analyst` route | Shipped | `frontend/.../AnalystApp.tsx` — chat-first UI |
| 42+ MCP tools | Available | Gateway provides all portfolio/FMP/IBKR tools |
| `:::ui-blocks` protocol | Shipped | `parseMessageContent()` in `@risk/chassis`, BlockRenderer |
| Available blocks | metric-card, insight-banner, section-header, status-cell | block-registry.tsx |
| System prompt (ui-blocks) | Shipped | `AI-excel-addin/api/tools.py` `_build_ui_blocks_section()` |
| `context_enricher` hook | Available but not wired | `GatewayConfig.context_enricher` in `app_platform/gateway/proxy.py` |
| editorial_memory seed | Committed | `config/editorial_memory_seed.json` |
| Gateway proxy config | No enricher | `routes/gateway_proxy.py` — `GatewayConfig` has no `context_enricher` |

## What To Build

### Change 1: Wire context_enricher in gateway_proxy.py (~20 lines)

Add a `context_enricher` function to `routes/gateway_proxy.py` that injects briefing context into the chat payload:

```python
def _enrich_context(request: Request, user: dict, context: dict) -> dict:
    """Inject editorial_memory and briefing purpose into gateway context."""
    import json
    from pathlib import Path

    # Load editorial_memory for this user
    # Phase 1: static seed file. Phase 2: from user_editorial_state DB table.
    seed_path = Path(__file__).parent.parent / "config" / "editorial_memory_seed.json"
    if seed_path.exists():
        context["editorial_memory"] = json.loads(seed_path.read_text())

    return context
```

Wire it into the GatewayConfig:

```python
_config = GatewayConfig(
    gateway_url=lambda: os.getenv("GATEWAY_URL", ""),
    api_key=lambda: os.getenv("GATEWAY_API_KEY", ""),
    ssl_verify=lambda: _parse_ssl_verify(os.getenv("GATEWAY_SSL_VERIFY", "")),
    context_enricher=_enrich_context,
)
```

The gateway already merges enriched context into the upstream payload (proxy.py:201). The AI-excel-addin gateway can read `context.editorial_memory` and use it in the system prompt.

### Change 2: Briefing system prompt section in AI-excel-addin (~50 lines)

Add `_build_briefing_section()` to `AI-excel-addin/api/tools.py`, gated on `context.editorial_memory` being present:

```python
def _build_briefing_section(editorial_memory: dict) -> str:
    prefs = editorial_memory.get("editorial_preferences", {})
    philosophy = editorial_memory.get("briefing_philosophy", {})

    return f"""\
## Morning Briefing Mode

You have access to the user's editorial memory — what they care about and how
they want to be briefed. Use this to guide what you lead with and emphasize.

### What this user cares about
- Lead with: {', '.join(prefs.get('lead_with', ['risk warnings']))}
- Cares about: {', '.join(prefs.get('care_about', []))}
- Less interested in: {', '.join(prefs.get('less_interested_in', []))}
- Sophistication: {prefs.get('sophistication', 'high')}

### Briefing philosophy
- Default state: {philosophy.get('default_state', 'Performance vs benchmark + income progress')}
- Alert state: {philosophy.get('alert_state', 'Lead with risk framework gaps')}
- Depth: {philosophy.get('depth', 'High-level takeaways')}
- Tone: {philosophy.get('tone', 'Analyst briefing')}

### When composing a briefing
1. Call get_positions() to see the portfolio state + flags
2. Call get_risk_analysis() or get_risk_score() to check risk framework
3. Call get_performance() for benchmark comparison + income
4. Call get_portfolio_events_calendar() for upcoming events
5. Decide: is this an alert state (risk gaps) or default state (system working)?
6. Compose the briefing using :::ui-blocks for metrics, prose for insights
7. End with 1-2 recommended actions (exit ramps to scenario tools)

### Briefing structure
- Lead with a one-sentence verdict (alert or default)
- 3-6 key metrics as metric-card blocks
- 1 paragraph explaining what matters and why
- Upcoming events if any are within 7 days
- 1-2 "what to do next" recommendations
"""
```

Wire into `build_system_prompt()`:

```python
editorial_memory = context.get("editorial_memory")
if channel_context == "web" and editorial_memory:
    sections.append(_build_briefing_section(editorial_memory))
```

### Change 3: "Morning Briefing" button in AnalystApp sidebar (optional, ~30 lines)

Add a button to the analyst sidebar that sends a pre-composed message to the chat: "Compose my morning briefing." This is a convenience — the user can also just type it. But the button makes it feel like a feature, not a chat prompt.

```tsx
// In AnalystSidebar
<button onClick={() => sendMessage("Compose my morning briefing for today.")}>
  Morning Briefing
</button>
```

## What This Tests

| Question | How we'll know |
|----------|---------------|
| Can the AI pick the right lead story? | Open the briefing daily. Does it match what you would have picked? |
| Does editorial_memory change the output? | Compare briefing with vs without the memory context. |
| Is the two-mode model right (alert vs default)? | Does the AI correctly identify "on fire" vs "system working"? |
| Are the tools sufficient? | Does the AI call the right tools, or does it need data it can't get? |
| Is the output quality good enough? | Would you read this every morning, or does it feel generic? |

## What This Does NOT Test

- Deterministic scoring (the pipeline's weighted additive formula)
- Generator modularity (pluggable architecture)
- Caching / performance (every briefing is a fresh LLM call)
- Multi-user personalization (one user, one memory)
- Frontend slot rendering (briefing is chat artifacts, not Overview components)

## Implementation Effort

| Component | Files | Effort |
|-----------|-------|--------|
| context_enricher wiring | `routes/gateway_proxy.py` | ~20 lines |
| Briefing system prompt | `AI-excel-addin/api/tools.py` | ~50 lines |
| Sidebar button (optional) | `AnalystApp.tsx` | ~30 lines |
| **Total** | **2-3 files** | **~100 lines, <1 hour with CC** |

## Success Criteria

1. You open the analyst view, hit "Morning Briefing," and the AI produces a briefing you'd actually read.
2. The lead story matches what you'd have picked manually.
3. On a day something goes wrong, the AI leads with the risk gap, not performance.
4. On a quiet day, it shows benchmark comparison + income, not noise.

## What Happens After

- **AI is great at editorial selection** → The deterministic pipeline (OVERVIEW_EDITORIAL_PIPELINE_DESIGN.md) becomes a performance optimization. The scoring weights can be derived from what the LLM consistently picks.
- **AI is mediocre** → We know where judgment fails. Design scoring weights to compensate. The pipeline's deterministic path is the primary selection engine, LLM is the secondary enhancer.
- **AI is bad** → Rethink the premise. Maybe editorial selection requires domain rules, not AI judgment. Rare outcome given the tool access, but possible.

## Relationship to Full Pipeline

This experiment is a **lightweight prototype** that runs entirely in the chat/artifact system. It validates the core premise (AI can make good editorial judgments) before investing in the full pipeline infrastructure. The full pipeline (OVERVIEW_EDITORIAL_PIPELINE_DESIGN.md) is still the target architecture — this experiment de-risks it.

```
  THIS EXPERIMENT                    FULL PIPELINE (after validation)
  ──────────────                     ────────────────────────────────
  Chat + artifacts                   Overview page components
  LLM selects + renders              Deterministic scoring + LLM enhance
  ~100 lines, 2-3 files              ~35-40 tests, 6-8 files
  Proves: can AI judge?              Builds: production editorial system
  1 user (founder)                   Multi-user with editorial_memory
  Fresh LLM call each time           Cached selection + fresh values
```
