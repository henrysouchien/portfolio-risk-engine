# UI Polish — Follow-up Quirks & Issues

> **Captured**: 2026-04-17 during live walkthrough of dev build (Chrome, `localhost:3000`).
> **Scope**: Visual/interaction quirks and voice inconsistencies noticed on Overview, Risk, Stress Test, Research list, and the MSFT research workspace. Not functional regressions — backend is healthy, navigation works, data loads.
> **Related**: Lane E (F35 entry in `docs/TODO.md`). Carry-over / repeat of earlier tickets where noted.

---

## Global / Cross-View

### G1. Hash routing silently resolves to wrong view
- **Where**: Navigating directly to `http://localhost:3000/#stress` loads the **Risk** view, not Stress Test. Clicking the sidebar item updates the URL to `#scenarios/stress-test` (the real route).
- **Why it hurts**: Deep-links from editorial cards, bookmarks, and future agent-generated URLs rely on the short form. Silent fallback to Risk is confusing.
- **Suggested fix**: Add aliases for top-level scenario verbs (`#stress`, `#whatif`, `#montecarlo`, `#optimize`, `#taxharvest`) → canonical `#scenarios/*`. Mirror the existing `#factors` → `#risk` legacy alias pattern (`parseHash` + localStorage migration, `cd0a7c5d`).
- **Severity**: medium — erodes trust in deep-linking.

### G2. Top strip "Updated" state transition is abrupt
- **Where**: Top editorial strip. First render: `UPDATED LIVE` (green). Briefing later resolves to: `UPDATED 12:19 PM` (timestamp, neutral color).
- **Why it hurts**: The word "LIVE" disappearing mid-load reads like a data-freshness regression, not a transition to "last-refresh stamp."
- **Suggested fix**: Decide the semantic. Options: (a) keep `LIVE` and only swap to timestamp if data goes stale, (b) always show timestamp once data is resolved and drop `LIVE` entirely, (c) add a subtle fade/crossfade. Pick one — the current mix looks like two states fighting.
- **Severity**: low — cosmetic, but eye-catching.

### G3. "BXMT Risk Load" card in right rail shows a number with no label
- **Where**: Overview right rail, under "ABOUT BXMT RISK LOAD": body text reads "BXMT still sits inside the book's main concentration pocket." and then a floating `-66.0%` with no accompanying label.
- **Why it hurts**: Ambiguous — is it a beta? YTD? Factor contribution? The rest of the briefing is explicit about units.
- **Suggested fix**: Label the number (e.g., `Rate 2Y beta: -66.0%` or whatever the generator intends). If the generator knows the metric name, thread it through. If not, drop the raw number.
- **Severity**: medium — violates the "every number has context" rule.

---

## Research List (`#research`)

### R1. Breaks briefing voice
- **Where**: Research list landing. Shows "Research Files" header + ticker/label form, then a stage/sort filter, then a narrative line ("6 active research files. VALE, AAPL, and TEST are in exploration..."), then a table.
- **Why it hurts**: Every other primary view leads with a diagnosis-first hero ("Performance is lagging...", "Composite risk score is 90/100..."). Research drops the analyst voice and becomes a file manager.
- **Suggested fix**: Add a hero banner answering "What's ready for a decision this week?" — something like:
  > "MSFT diligence is 60% drafted with no flagged evidence; VALE has two open threses running pair vs macro. Two files haven't moved since Apr 13."
  Generator lives naturally in the editorial pipeline; the briefing already has the signal via `EditorialState` + diligence section counts.
- **Severity**: medium — it's the one view that breaks the voice contract.

### R2. "Research Files" header not uppercase
- **Where**: List view main heading.
- **Why it hurts**: Sidebar rail labels (`PORTFOLIO`, `ANALYSIS`, `SCENARIOS`, `EDITORIAL NOTES`, `ANALYST NOTE`) and section anchors (`CONCENTRATION`, `PERFORMANCE`, `MARKET CONTEXT`) are all uppercase. Mixed-case "Research Files" is the only top-of-page label that breaks the pattern.
- **Suggested fix**: Either uppercase to `RESEARCH FILES` or swap to the narrative-hero treatment from R1 (hero + no generic heading).
- **Severity**: low — visual.

### R3. `TEST` file leftover in list
- **Where**: Bottom row of research list — stage `EXPLORING`, 0 threads, Apr 13.
- **Why it hurts**: Leaks dev state into the product. Would be embarrassing in a live demo.
- **Suggested fix**: Delete it. Also consider a hard rule: research file tickers must match a real instrument (or a namespaced `demo:*` prefix) before they can be created.
- **Severity**: low.

---

## Research Workspace — MSFT file (`#research/MSFT`)

### W1. Raw tool-output JSON bleeds into conversation feed
- **Where**: Main thread panel, analyst turns. Example content rendered inline:
  ```
  START THREAD: {"STATUS": "SUCCESS", "SYMBOL": "MSFT", ...}
  START THREAD: {"STATUS": "SUCCESS", "ENDPOINT": "KEY ...
  ```
- **Why it hurts**: F26 previously cleaned up `tool_call` payloads into the compact "Used {tool_name}" pill — that works, I see `Used fmp_profile` / `Used fmp_fetch` rendering correctly. But there's a **second** message type prefixed `START THREAD:` that is still dumping raw JSON. Looks like a different contentType path the F26 fix didn't cover.
- **Suggested fix**: Trace the `START THREAD:` renderer. Either (a) collapse behind the same "Show details" affordance F26 introduced, or (b) suppress entirely if the thread was already created and the creation artifact is captured on the right rail.
- **Severity**: high — it's the single most un-analyst-like element on the page. Carry-over regression-class of F26.

### W2. Thread tab names are messy
- **Where**: Thread tab bar at the top of the workspace.
- **What I saw**: `EXPLORE | DILIGENCE 0/9 | THREAD 1 | VALUATION DEEP DIVE | DELETE-TEST | THREAD 3 | THREAD 5 | + THREAD`.
- **Why it hurts**:
  - `THREAD 1` / `THREAD 3` / `THREAD 5` — default names, gaps suggest deletions but the numbers stuck.
  - `DELETE-TEST` — debug leftover.
  - `VALUATION DEEP DIVE` — clearly renamed, proves inline rename exists somewhere.
- **Suggested fix**: (a) auto-name threads by first user message topic (LLM summarize → 3-4 words), (b) compact unused numeric IDs on delete so the sequence stays 1/2/3, (c) clean up `DELETE-TEST` now.
- **Severity**: medium — everyday cognitive load in the core workflow.

### W3. "DILIGENCE 0/9" when stage = DILIGENCE reads contradictory
- **Where**: Thread tab bar + breadcrumb header ("... DILIGENCE").
- **Why it hurts**: A file marked stage=Diligence with 0/9 sections drafted suggests either (a) stage auto-promoted before work started, or (b) pre-population didn't write sections. Either way the copy fights itself.
- **Suggested fix**: Either (a) don't auto-promote to DILIGENCE until ≥1 section is DRAFT/CONFIRMED, or (b) show "DILIGENCE (pre-population pending)" copy until fills arrive. Related to F24 (pre-pop not filling FMP fields) — fixing F24 may naturally resolve this.
- **Severity**: medium — trust-impacting.

### W4. Conviction dots have no label or tooltip
- **Where**: Under the direction/strategy row — `CONVICTION ○ ● ● ● ○`.
- **Why it hurts**: Reader has to count dots to infer 3/5. No label, no hover tooltip I could find. Standard rating UI gives both.
- **Suggested fix**: Add `3 / 5 — moderate` (or whatever tier names the product uses) next to the dots. Tooltip on each dot optional.
- **Severity**: low.

### W5. Left thread panel vs. right "Research Analyst" rail overlap in purpose
- **Where**: MSFT workspace.
- **What I saw**: Left column = conversation feed with "YOU" / "ANALYST" turns + timestamps. Right rail = "RESEARCH ANALYST" panel with its own analyst messages, timestamps, workspace scan, and running content. Both display analyst turns. The mental model — which panel is "the active thread" vs "cross-thread summary" — is not signaled.
- **Why it hurts**: When they show similar content at similar visual weight, the reader cross-reads and loses track. This is a fundamental layout question, not a cosmetic one.
- **Suggested fix**: Design call needed. Options:
  1. Right rail becomes purely cross-thread summary + pinned findings (no analyst-voice messages of its own).
  2. Left column becomes purely user+analyst turns for the active thread; right rail handles pinning, findings, workspace scan, quick-actions.
  3. Make the visual hierarchy obvious: right rail at half weight (muted text, smaller type) with a clear "Workspace" header that differs from the thread header.
- **Severity**: high — this is structural, and it's the single biggest reason the Research workspace doesn't feel "diagnosis-first" the way Overview and Risk do.

### W6. Progress dots `○○○○○` next to "GENERAL RESEARCH"
- **Where**: Breadcrumb row `RESEARCH FILE MSFT · PAIR · GENERAL RESEARCH · ○○○○○`.
- **Why it hurts**: Five dots, all empty, no label. Could be conviction (but that's shown again below), could be workflow progress, could be section completeness. Not discoverable.
- **Suggested fix**: Label or remove. If this is a workflow progress indicator, add "STAGE PROGRESS" or similar inline label.
- **Severity**: low.

---

## Priority triage

| Priority | Items | Why |
|----------|-------|-----|
| **P1 — ship first** | W1 (JSON bleed), W5 (panel overlap), G1 (hash routing) | Highest cognitive/structural cost. W1 is a regression-class miss. W5 is the structural reason Research feels weaker. G1 quietly breaks deep links. |
| **P2 — before broader launch** | R1 (briefing voice), W2 (thread names), W3 (diligence 0/9), G3 (floating %), R3 (TEST file cleanup) | Voice + data-context consistency. Each is independent; cumulatively they drag the briefing feel. |
| **P3 — cosmetic** | R2 (header case), G2 (LIVE→timestamp), W4 (conviction label), W6 (progress dots) | Polish, not blockers. |

---

## Not covered here

- Bugs already tracked (F24 pre-population, F30 Build Model) — those are upstream `ai-excel-addin` issues. Mentioned only where they touch W3.
- Performance (F21) — no perceptible lag this session; separate audit.
- Editorial streaming UX (F22) — same, separate plan.
- Mobile/cross-browser (6E) — desktop Chrome only.

## Suggested next step

Batch P1 items into a single plan-review → Codex-implement cycle (per the plan-first workflow in CLAUDE.md). P2 can fan out across independent tickets in Lane E. P3 can piggyback onto the next design audit sweep.
