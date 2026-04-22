# Research Workspace E2E Dogfood Test

**Date:** 2026-04-16
**Prereqs:** Backend running (port 5001), frontend running (port 3000), research workspace MCP available.
**Ticker:** MSFT (US-domiciled, files 10-K not 20-F, has EDGAR coverage via langextract)

---

## Phase 1: Bootstrap + Explore

1. Create or open the MSFT research file via MCP or UI
2. Send: "What's the bull case for MSFT at current prices?" — verify:
   - Streaming response completes
   - Response renders with inline data (tables, bold text, lists)
   - Metric strip appears if agent surfaces pipe-delimited metrics (EV/EBITDA | P/E | FCF Yield)
3. Send: "Pull up institutional ownership changes and insider trades for the last quarter" — verify:
   - Tool calls render as compact "Used get_institutional_ownership" / "Used get_insider_trades"
   - "Open in reader" links appear if tool calls have sourceId/sourcePath
4. On the agent's ownership response, click "Start thread →" — verify:
   - Thread tab opens in the tab bar with a suggested name (e.g., "Ownership")
   - Seeded message appears in the thread with the original exchange
   - Agent panel shows "Thread · Ownership" context + cross-reference links to other threads

## Phase 2: Document Reading

5. Send: "Pull up the risk factors from MSFT's latest 10-K" — verify:
   - Agent calls `get_filing_sections` or similar
   - "Open in reader" button appears on the tool call message
6. Click "Open in reader" — verify:
   - Document tab opens with filing prose at readable width (max 640px, 15px text)
   - Paragraph numbers shown in left margin
   - Section selector dropdown appears in the toolbar
7. Select a passage (e.g., about AI competition or regulatory risk) — verify:
   - "Ask about this" button appears in the toolbar
   - "Start thread →" button appears next to it
   - Agent panel shows "Tip: select text in the reader to ask about it here."
8. Click "Ask about this" — verify:
   - Quoted text appears as a draft in the agent panel input
   - Agent panel context shows "Reading · {section name}"
9. If extractions exist, verify:
   - Agent highlights render with accent-dim background
   - Inline "Agent" annotation notes appear below highlighted paragraphs

## Phase 3: Diligence

10. From the Explore tab, click "Form thesis →" in the exit ramps — verify:
    - File stage changes to "Diligence" in the dateline and top bar
    - Diligence tab appears in tab bar with "0/9" progress label
    - Pre-population starts (amber banner: "Pre-populating sections in parallel...")
11. Wait for pre-population to complete — verify:
    - Sections go from EMPTY to DRAFT
    - Opening take generates with a synthesis of the research so far
    - Section badges show DRAFT status
12. Open a section (e.g., Business Overview or Risks) — verify:
    - "Research links" block appears with contextual links:
      - "See {ThreadName} thread →" if a thread matches by keyword
      - "See Item {N} →" if source_refs point to filing sections
    - Server draft data shows (company name, key metrics, etc.)
    - Working notes textarea is editable
13. Click a research link (filing section or thread) — verify it navigates correctly:
    - Filing link: opens document tab at the referenced section
    - Thread link: switches to the matching thread tab
14. Set metadata in the dateline bar — verify:
    - Direction: click "Long" → top bar updates to show "LONG"
    - Strategy: click "Value" → top bar shows "VALUE"
    - Conviction: click dot 3 → shows 3 filled dots
    - Research list (when navigated back) reflects these values

## Phase 4: Report + Exit Ramps

15. Click "Finalize Report" on the diligence tab — verify:
    - Handoff tab ("Report") opens
    - Version history sidebar shows the new version with "Finalized" status
    - Main panel shows structured report:
      - **Thesis** section with InsightSection styling
      - **Report Snapshot** — 4-column grid (Sources, Catalysts, Risks, Assumptions counts)
      - **Decision Lens** — direction/strategy/stage/conviction tiles + narrative summary
      - **Decision Log** — metadata change history (or empty placeholder)
      - **Sources** section with numbered source cards
      - Per-section content (Company, Thesis, Business Overview, Catalysts, Risks, etc.)
16. Navigate to Explore tab — verify exit ramps at bottom:
    - "Size a position →", "Stress test →", "Compare to holdings →", "Generate trades →"
    - "Open report →" (appears because handoff exists)
17. Click "Size a position →" — verify:
    - Navigates to Scenarios view → What-If tool
    - MSFT ticker is pre-filled in the what-if context
    - Suggested weight delta is based on conviction level
18. Navigate back to research, click "Compare to holdings →" — verify:
    - Agent panel input gets pre-filled with comparison prompt
    - Prompt reads: "Compare MSFT to our current holdings and flag the closest analogs or overlaps."

## Phase 5: Compare + List View

19. Navigate to `#research` list view — verify:
    - Dense table format with columns: File, Stage, Strategy, Direction, Conviction, Threads, Updated, Action
    - MSFT row shows updated strategy/direction/conviction values
    - Stage badge is outlined (not filled pill) with correct color
    - Thread count reflects actual threads created during test
    - Insight summary at top: "N active research files..."
20. Select MSFT and one other file (e.g., VALE) using "Compare" buttons — verify:
    - Compare card updates: "MSFT selected. Pick one more file to compare."
    - After second selection: "MSFT vs VALE."
    - "Open comparison" button activates
21. Click "Open comparison" — verify:
    - URL changes to `#research/compare/{id},{id}`
    - Side-by-side layout renders:
      - Overview cards (ticker, stage badges, direction/strategy, threads/flags, latest report status)
      - Thesis statements (or "No report thesis captured yet.")
      - Catalysts, Risks, Assumptions lists
      - Decision Log for each file
    - "Back to files" button returns to list view
    - "Open {ticker}" links navigate to individual workspace

---

## Agent-testable steps (via research workspace MCP, no browser needed)

Steps 1-4, 10-14 can be run by a Claude agent session using the research workspace MCP tools directly:
- File creation/listing: `POST /api/research/content/files`
- Chat: `POST /api/research/content/chat` (streaming)
- Thread creation: `POST /api/research/content/threads`
- Diligence activation: `POST /api/research/content/diligence/activate`
- Pre-population: `POST /api/research/content/diligence/prepopulate`
- Section updates: `PATCH /api/research/content/diligence/sections/{key}`
- Metadata updates: `PATCH /api/research/content/files/{id}`

## Browser-required steps

Steps 5-9 (document reading UI), 15-18 (report + exit ramps), 19-21 (compare + list interactions) require visual verification via Chrome automation or manual testing.

---

## Known issues to watch for

- **F24**: Diligence pre-population may show "—" for sector/industry/fiscal_year_end even though FMP profile has data (upstream ai-excel-addin mapping bug)
- **F30**: Build Model may fail on missing fiscal metadata (blocked by F24)
- **F33**: Build Model is a direct orchestrator call, not agent-mediated
- **Chunk load errors**: After code changes, hard-reload (Cmd+Shift+R) may be needed; if error boundary persists, navigate away and back
