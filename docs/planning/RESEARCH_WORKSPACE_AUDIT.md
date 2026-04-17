# Research Workspace Audit: Design Preview vs. Implementation

**Date:** 2026-04-14
**Design preview:** `~/.gstack/projects/henrysouchien-risk_module/designs/research-workspace-20260403/research-workspace-preview.html`
**Product spec:** `docs/planning/EQUITY_RESEARCH_WORKSPACE_SPEC.md`
**Status:** Phases 1-4 shipped. This audit compares the shipped UI against the original design preview HTML and product spec.

---

## Methodology

Compared the HTML design preview (4 mockup views: Exploration, Document Reading, Thread, Research List) and the product spec interaction model against every shipped frontend component in `frontend/packages/ui/src/components/research/`.

---

## A. Visual / Design Gaps

| # | Element | Design Preview | Current Implementation | Severity |
|---|---------|---------------|----------------------|----------|
| V1 | **Ticker tape** | Top bar: `PORTFOLIO +0.47% TODAY · S&P 500 -0.23% · 3 WATCH · 2 TAX HARVEST` | Missing entirely | Medium |
| V2 | **Dateline** | `APRIL 3, 2026 · VALE SA · EXPLORING` in Geist Mono uppercase | Missing — no date/ticker/stage header in workspace | Medium |
| V3 | **Tab bar style** | Flat text tabs, Geist Mono 11px, active = `--text` + 2px `--accent` bottom border | Rounded pill buttons with borders + bg fills + lucide icons | High |
| V4 | **Two-author distinction** | User: dim bullet `●` before text, no left rail. Agent: 1px `--accent` gold left rail | Both have 2px left borders (user = muted, agent = accent). User gets full border too — loses the flat/peer distinction | Medium |
| V5 | **Inline metric strips** | Rich horizontal metric cells (EV/EBITDA, P/E, FCF Yield) with Geist Mono, border separators, colored values | Not rendered — agent responses are plain markdown | High |
| V6 | **Inline tables** | Styled peer comparison tables (ticker highlight, numeric alignment, Geist Mono) | Not rendered — markdown tables only (no special formatting) | High |
| V7 | **Action links** | "Start thread: Ownership →" / "Open in tab: 10-K §2.1 →" with gold arrows, 12px | Only "Open in reader" button exists (for tool calls with sourcePath/sourceId). No "Start thread" links | High |
| V8 | **Agent panel flags** | `⚑ Valuation at 5-year low` / `○ Estimates stable` — flagged items list in panel | Missing — no proactive flag display in agent panel | Medium |
| V9 | **Agent panel mini charts** | Bar chart in panel (Institutional Ownership Change, 100px height, Geist Mono labels) | Missing — no visualization capability in agent panel | Low |
| V10 | **Exit ramps bar** | Bottom bar across full workspace width: "Size a position →", "Stress test →", "What-if →", "Compare to holdings →" | Missing entirely from all views | High |
| V11 | **Agent panel context line** | `Exploring · VALE SA` or `Reading · 10-K §2.1 Risk Factors` in Geist Mono 10px, `--accent` color, separate from header | Shows stage badge + ticker + document context — functional but uses Badge component, not the clean Geist Mono accent line | Low |
| V12 | **Pinned finding label** | `FINDING` in Geist Mono 9px uppercase, `--accent` gold color | Shows thread name as label (e.g., "Ownership"), not "FINDING" in accent | Low |
| V13 | **User notes in threads** | Distinct from conversation: 2px `--text-dim` left border, "Your note · Apr 3" label in Geist Mono 9px | Not implemented — no separate note content type distinct from chat messages | Medium |
| V14 | **Collapsed thread history** | "▸ 5 earlier exchanges · See full thread" — compressed older content | Missing — all messages shown flat, no collapsing | Low |
| V15 | **Document agent highlights** | `--accent-dim` bg + 2px accent left border + inline "⚑ Agent: New cost estimate — $1.1B increase..." note | HighlightLayer exists with accent styling, but no inline `⚑ Agent:` annotation note below highlights | Medium |
| V16 | **Research list format** | Dense table: Ticker (bold), Company, Stage (color-coded badge), Strategy, Conviction (●●○○○ dots), Threads count, Updated timestamp, Flag dot | Card grid with minimal info (ticker, label, stage badge, company name, "Open" button). No conviction dots, strategy, thread count, updated date, or flag indicators | High |

---

## B. Interaction Gaps

| # | Interaction | Design Spec | Current | Severity |
|---|------------|-------------|---------|----------|
| I1 | **Thread creation from conversation** | "Start thread →" link on interesting agent exchanges → branches topic into new named tab | Not implemented — user must use "+" button in tab bar and name thread manually | High |
| ~~I2~~ | ~~**Thread input**~~ | ~~Threads have message input at bottom of reader area~~ | ~~Threads are read-only — agent panel is the sole input channel~~ | ~~RESOLVED~~ — Open Question #1 explicitly resolved: "When a Thread or Document tab is active, reader has NO input (read-only); agent panel is the sole conversation channel." HTML preview predates this resolution. Current implementation is correct. |
| I3 | **Document → thread creation** | "Start thread: Environmental liability →" exit ramp from document reading | Not implemented — no path from document tab to thread creation | Medium |
| I4 | **Exit ramps to scenario tools** | Click exit ramp → opens What-If / Stress Test / Monte Carlo with research context (ticker, weight, scenario) | Not implemented — no connection between research workspace and scenario tools | High |
| I5 | **"Select text" tip in agent panel** | "Tip: Select text to ask about it" contextual hint when reading a document | Missing — AskAboutThis button appears in toolbar but no guiding hint in panel | Low |
| I6 | **Agent proactive flagging** | Agent surfaces notable items (⚑ flags) independently in the panel when entering a research file | Not implemented — agent only responds to user-initiated messages | Medium |

---

## C. Functional Gaps

| # | Feature | Design Spec | Current | Severity |
|---|---------|-------------|---------|----------|
| F-R1 | **Rich data rendering in chat** | Metric strips, comparison tables, charts rendered inline when agent surfaces financial data | All agent output rendered as markdown via MarkdownRenderer. No structured data components | High |
| F-R2 | **Research list filtering/sorting** | Filterable by stage, sortable by any column | Alpha-sort by ticker only, no stage filter, no column sort | Medium |
| F-R3 | **Conviction dots** | Visual ●●●○○ display in research list and file metadata | Not shown anywhere in the UI | Low |
| F-R4 | **Stage color-coding** | Exploring = blue (`--chart-blue`), Diligence = gold (`--accent`), Decision = green (`--up`) | Generic outline badge with no color differentiation by stage | Low |
| F-R5 | **Handoff report UX** | Analyst-report style with InsightSection for thesis, NamedSectionBreak per section, narrative prose, evidence strips, source citations | Raw field dump via HandoffSectionRenderer — already tracked as F25 in TODO.md | High |

---

## Priority Tiers

### Tier 1 — Critical (experience doesn't match the design intent)

These gaps break the core interaction model. The design is an "IDE for equity research" — without these, it's a chat window with tabs.

| # | Gap | Why critical |
|---|-----|-------------|
| V10 + I4 | **Exit ramps** | The entire "research → action" bridge is missing. The design spec calls this out as a core pattern — every result leads somewhere |
| V5 + V6 + F-R1 | **Rich inline data** | Metric strips and peer tables in conversation are the visual proof the agent did real work. Markdown tables are generic |
| V7 + I1 | **"Start thread" action links** | Thread creation from conversation flow is how threads "emerge from exploration" (spec §"How threads form"). Manual "+" creation breaks this |
| ~~I2~~ | ~~**Thread input**~~ | ~~RESOLVED~~ — not a gap. Architecture decision: agent panel is the sole input on thread/document tabs |
| V16 | **Research list as table** | Card grid doesn't convey density, status at a glance, or support the "what's my research pipeline" scan |

### Tier 2 — Important (significant design fidelity gaps)

| # | Gap |
|---|-----|
| V3 | Tab bar styling (pills → flat underline + accent border) |
| V4 | Two-author visual distinction (dim bullet vs. gold rail, not two border colors) |
| V13 | User notes (separate from chat messages, own rail color + label) |
| I3 | Document → thread creation |
| V15 | Agent highlight inline annotations (⚑ Agent: notes) |
| F-R5 | Handoff report UX (F25 — already tracked) |

### Tier 3 — Polish

| # | Gap |
|---|-----|
| V1 | Ticker tape top bar |
| V2 | Dateline (date + ticker + stage) |
| V8 + I6 | Agent proactive flagging (⚑ items in panel) |
| V9 | Mini charts in agent panel |
| V11 | Agent panel context line styling |
| V12 | Pinned finding label ("FINDING" in accent) |
| V14 | Collapsed thread history |
| V15 | "Select text" tip |
| F-R2 | Research list filtering/sorting |
| F-R3 | Conviction dots |
| F-R4 | Stage color-coding |

---

## Cross-references

- **F25** (TODO.md Lane E): Handoff report view design pass — overlaps with F-R5 above
- **F33** (TODO.md Lane E): Build Model should be agent-mediated — related to exit ramp architecture
- **DESIGN.md**: All visual decisions (fonts, colors, spacing) should reference the design system
- **Design preview HTML**: The authoritative visual reference for all mockup views

---

## Notes

- The *functional* pipeline (file CRUD, threads, chat, diligence, document reading, annotations, handoff) is solid. The gaps are primarily in **visual fidelity** and **interaction design** — the design preview established a specific look and interaction flow that the implementation diverged from during build.
- Many of the visual gaps (V3, V4, V5, V6, V7) are concentrated in ConversationFeed and ResearchTabBar — two components that affect every view.
- The exit ramps gap (V10 + I4) is both a design and architecture issue — it requires wiring research context into the scenario tool navigation system.
