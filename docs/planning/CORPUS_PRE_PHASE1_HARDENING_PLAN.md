# Corpus — Pre-Phase-1 Hardening Milestone

## Status: v2 — rebased 2026-04-28 against actual Edgar_updater parser state (Phase 3+4 shipped, Phase 5 PAUSED)

Coordination plan for upstream parser improvements + corpus plumbing required before scaling V2.P1 corpus ingestion to Phase 1's 50-100 ticker universe.

**v2 revision motivation:** v1 (drafted 2026-04-24) assumed the original layered section parser plan (L1+L2+L3+L4+L5) was the active architecture and that L2 would deliver XBRL-anchored financial-statement coverage. Reality check on 2026-04-28 found:

- **Phase 3 (layered architecture, no L2) SHIPPED 2026-04-25** — L1+L3+L3'+L4+L5; produces `source`/`confidence`/`detection_stats`.
- **Phase 4 (TOC-first parser) SHIPPED 2026-04-26** — adds `state`/`declaration_type`/`sections_found`/`sections_absent`/`sections_missing`; default-on per commit `1ca0ff5`; schema bumped v7→v8.
- **Phase 5 (XBRL boundary refinement, contains L2 emitter) PAUSED 2026-04-27** — original AES motivation already fixed by Phase 4; dry-run found 3 algorithm issues; refinement deltas too small to justify cost. Re-trigger conditions (langextract/kpi_extractor anchoring failures, new AES-class case, downstream feature needing precise boundary) — none corpus-driven today.
- **L2 was never wired** — `xbrl_role` candidate emitter doesn't exist in shipped code; `l2_skipped_reason` hardcoded `None` everywhere; threading `(cik, accession, sec_headers)` to parser today does nothing functional.

v2 drops L2-dependent gates, loosens Track 4 thresholds to Phase 4 measured floor, marks Track 3 plumbing as forward-compat-only, and acknowledges 7 of our 25 validation tickers hit known parser bugs that aren't fixed yet.

Codex review of this plan deferred until Phase 4 in-flight bugs (money-center bank TOC variant for JPM/BAC/WFC; Intel-style `<td>` heading splits) land — this is a sequencing/coordination doc, not an implementation spec.

## Goal

Validate the end-to-end corpus chain against a diversified ticker set under the **current** Phase 3+4 parser, with revised gates that match what's actually shipped, before Phase 1 scales to 50-100 tickers.

## Context

**Entry state (2026-04-28):**

- V2.P1 corpus Phase 0 shipped 2026-04-24 (PRs #14 + #15 + #17). 10-ticker canary, 161 tests, Q1-Q5 canary queries passing. Q6/Q9-surface explicitly DEFERRED per F43.
- Edgar_updater layered architecture (Phase 3) + TOC-first parser (Phase 4) shipped 2026-04-25/26, default-on. Schema v8.
- Phase 5 (XBRL boundary refinement) paused 2026-04-27. L2 emitter never wired in shipped code. Source-side AES bug already fixed by Phase 4 (item_7A=1,787 words; item_8=42,488 words — both correct).
- S&P 500 audit baseline (pre-Phase-4 flip, 2026-04-23): 10-K fully-OK 83.7%, 10-Q 63.1%, 37 zero-matched. Post-Phase-4 flip (measured but not yet re-audited as of v2): 10-K 94.4%, 10-Q 82.4%, zero-matched 0.

**Exit state (revised):**

- Track 3 corpus plumbing landed as forward-compat (no functional change today; ready when Phase 5 unpauses).
- Phase 4 in-flight bugs landed (money-center bank TOC variant; Intel-style `<td>` splits) so JPM + BK + MS + WFC + INTC + GE + HON in our validation set don't carry expected-failure baselines.
- 25-ticker validation re-ingest confirms section coverage meets the **revised Phase 4 floor** (≥93% 10-K / ≥80% 10-Q OK rates; 0 zero-matched) without canary regressions.
- Validation report committed; green light for Phase 1 corpus scaling.

## Scope

### In scope

- **Track 1 monitoring** — track in-flight Phase 4 fixes (money-center bank TOC; Intel-style `<td>` splits) without driving them; landing reduces validation-set expected failures.
- **Track 3 corpus plumbing** — extend `core/corpus/filings.py::parse_filing_sections` wrapper to thread `(cik, accession, sec_headers)` through to upstream parser. **Forward-compat only** — kwargs are ignored by current parser (`del sec_headers`; cik/accession used only for shadow-validation `filing_key`). Lands cheaply, no functional change today, ready when Phase 5 unpauses. Bridge `corpus_ingest_accession.py` does NOT need plumbing — it goes through `get_filing_sections_cached` which doesn't accept those kwargs and won't until Phase 5 §3 ships.
- **Track 4 validation re-ingest** — 25-ticker validation set re-ingest; canary regression; coverage measurement; spot-check; report.
- **Phase 1 ticker universe (50-100) selection** — separate from this milestone but referenced; T2.4 in the original plan.

### Out of scope — parked

**Bucket A drops (no longer in scope):**

- L2-anchored financial-statement coverage (`source="xbrl_role"`) — Phase 5 paused; not shipping.
- Schema/SearchHit additions for XBRL provenance — Bucket C concern, deferred.
- Edgar_updater-side `PLAN-targeted-corpus-prewarm-strategy` finalization (T2.1 + T2.2 in v1) — edgar_updater workstream on its own cadence; corpus picks tickers independently.

**Bucket B — langextract extraction quality improvements.** Ships in Edgar_updater on its own cadence, not consumed by corpus today:
- `PLAN-coalesce-matched-subsections`
- `PLAN-capital-allocation-subsection-widen-and-covenant-sweep`
- `PLAN-langextract-schema-expansion` Phase 3

**Bucket C — corpus architecture extension.** Deferred to a separate plan when prioritized:
- Surfacing KPIs, langextract facts, and structured tables in `SearchHit` / corpus query surface.
- Adding `source` + `confidence` columns to `documents` + `sections_fts` + `SearchHit` to carry per-section provenance from Phase 3 (data is available upstream now; just not flowing into corpus schema).
- **F44** — markdown↔HTML offset map for byte-precise source-passage highlighting in source-view UI (filed 2026-04-28 at commit `4982b405`). Architecturally independent of any parser phase.
- Amendment surfacing (Q6 canary, F43 path) — low user-value per F43 downgrade.

**Phase 5 unpause.** Not on this milestone's path. Triggers when Bucket C gets prioritized OR a downstream consumer (langextract, kpi_extractor) reports XBRL-anchoring failures.

## Tracks

### Track 1 — Upstream Edgar_updater status (monitor, don't drive)

**Shipped, default-on:**

- ✅ Phase 3 layered architecture (`4eebf0a`, 2026-04-25) — L1 anchor + L3 narrowed + L3' permissive + L4 wording variants + L5 diagnostics. Schema v5.
- ✅ Phase 4 TOC-first parser (`0593bfd` impl, `d87cc32` v8 patches, `1ca0ff5` flag flip + schema v7→v8, 2026-04-26).

**In flight (another Claude session):**

- 🟡 Phase 4 money-center bank TOC variant — JPM 10-Q `part1_item1` not declared by TOC parser. Plan drafted. Affects JPM (and likely BAC, C, WFC, GS) in our validation set. Reduces 1 expected-failure ticker when landed.

**Open / not yet filed:**

- ⚠️ Phase 4 Intel-style `<td>` cell heading splits — affects ~20+ S&P 500 filers with iXBRL TOCs that put "Item 1." + "Business" in separate `<td>` cells, plus body headings split across `<span>`s. Hits 6 of our 25 validation tickers (BK, MS, WFC, INTC, GE, HON). **File as a separate Phase 4 follow-up bug in Edgar_updater TODO** if not already covered by the in-flight money-center fix. Highest leverage Phase 4 work for our hardening — would lift validation pass rate from 18/25 → 24/25.

**Paused indefinitely:**

- ⏸️ Phase 5 XBRL boundary refinement (`a32e2c8`, paused 2026-04-27). Plan committed as v3 PASS but implementation paused. Re-trigger conditions: downstream extractor anchoring failures, new AES-class case, downstream feature needing precise boundary. None corpus-driven.

**Filed bug, closed as duplicate (one-line trace):**

- `c851b60` filed 2026-04-27 about `get_filing_sections_cached` not threading `(cik, accession, sec_headers)`. Closed as duplicate of Phase 5 plan §3 ("Plumbing closure") on 2026-04-28 — lands when Phase 5 unpauses.

### Track 2 — Phase 1 ticker universe (corpus-driven)

| # | Task | File | Status |
|---|------|------|--------|
| ~~T2.1~~ | ~~Finalize `PLAN-targeted-corpus-prewarm-strategy` v1 draft~~ | Edgar_updater workstream | **DROPPED from v2** — not corpus blocker |
| ~~T2.2~~ | ~~Codex review → PASS~~ | — | **DROPPED from v2** |
| ✅ T2.3 | Pick 25 ticker validation set | This plan, **Appendix A** | DONE 2026-04-27, committed `551f549d` |
| T2.4 | Define 50-100 ticker Phase 1 universe | TBD plan doc | Phase 1 kickoff (post-hardening) |

**Effort:** T2.4 ~1 day when ready, not gated by hardening completion.

### Track 3 — Corpus plumbing (risk_module) — forward-compat only

| # | Task | File | Notes |
|---|------|------|-------|
| T3.1 | Extend `parse_filing_sections` wrapper to accept + thread `(cik, accession, sec_headers)` to upstream parser | `core/corpus/filings.py::parse_filing_sections` (line 203) + `filings_source_excerpt` callsite (line 141) | Wrapper signature change only; upstream parser ignores all 3 kwargs today (verified: `del sec_headers` at `section_parser.py:319`; `cik`/`accession` used only for shadow-validation `filing_key` at line 404). |
| ~~T3.2~~ | ~~Extend bridge `corpus_ingest_accession.py`~~ | ~~`scripts/corpus_ingest_accession.py`~~ | **DROPPED from v2** — bridge calls `get_filing_sections` → `get_filing_sections_cached`; cached path doesn't accept the kwargs. Lands when Phase 5 unpauses. Bridge stays as-is. |
| T3.3 | Unit tests — wrapper threads kwargs to upstream; missing kwargs default cleanly to None; no regression on existing callers | `tests/test_filings_tools.py` | Forward-compat assertion only. |
| T3.4 | Smoke test — live JPM 10-Q via `filings_source_excerpt` returns full sections (Phase 4 TOC-anchored, NOT XBRL-anchored) | manual verify | Confirm Phase 4 coverage matches expectations; doesn't validate L2 (won't fire). |

**Effort:** ~0.5 day coding + tests. Plan-first workflow per CLAUDE.md applies — draft plan → Codex review → implement.

**Why ship at all if forward-compat:**
- Cheap insurance — when Phase 5 eventually unpauses (likely triggered by Bucket C), corpus is ready without follow-up coordination.
- Wrapper signature lockup — any future caller that adds the kwargs gets them threaded for free.
- Spec compliance with Edgar_updater's reserved kwarg interface.

### Track 4 — Validation re-ingest (risk_module) — gates revised against Phase 4 floor

| # | Task | Depends on | Exit criteria (revised v2) |
|---|------|-----------|---------------------------|
| T4.1 | Re-ingest 25 validation tickers via bridge using current Phase 4-shipped parser | T3.1-T3.3 + bridge run | New markdown under `CORPUS_ROOT`; `documents` UPSERTed; `sections_fts` rebuilt; reconciler clean |
| T4.2 | Canary regression — Q1-Q5 canary queries still PASS | T4.1 | 5/5 pass; no false-negative drift |
| T4.3 | Coverage measurement — per-doc section count vs Phase 4 expected; aggregate match rate per form type | T4.1 | **≥93% 10-K** (post-Phase-4 measured: 94.4%) / **≥80% 10-Q** (post-Phase-4 measured: 82.4%) match expected sections |
| T4.4 | Spot-check `filings_source_excerpt` on Phase-4-handled sections — AES `item_8` (~42K words, NOT 50K), MSFT/AAPL Item 7 MD&A, EQH Item 7 MD&A | T4.1 | Returns verbatim text; no `ExcerptUnavailableError` on non-blocked tickers; AES `item_8` ≥30K (Phase 4 baseline, not Phase-5 ≥50K) |
| T4.5 | Document expected-failure baseline — JPM 10-Q `part1_item1` (Phase 4 money-center bug) + 6 Intel-style splits (BK, MS, WFC, INTC, GE, HON) flagged in report as known-failure, NOT new findings | T4.1 | Report distinguishes "regression vs Phase 0" from "expected failure pending in-flight Phase 4 fix" |
| T4.6 | Write + commit validation report capturing: section coverage matrix, canary regression results, expected vs unexpected failures, ticker-universe confirmation for Phase 1 | T4.2-T4.5 | Report committed; green light decision for Phase 1 kickoff |

**Effort:** ~1-2 days.

## Known-failure tickers in 25-ticker validation set (v2 addition)

7 of 25 validation tickers (28%) are known to hit unfixed Phase 4 parser bugs. These are **expected failure baselines** in the validation report, NOT new findings or regressions:

| Ticker | Issue class | Phase 4 status |
|---|---|---|
| JPM | Money-center bank TOC variant — `part1_item1` (10-Q Financial Statements) not declared by Phase 4 TOC parser | In-flight fix (another Claude session) |
| BK | Intel-style `<td>` cell splits in TOC headings | Filing pending — track for Phase 4 follow-up |
| MS | Intel-style `<td>` cell splits | Filing pending |
| WFC | Intel-style `<td>` cell splits | Filing pending |
| INTC | Intel-style `<td>` cell splits + body `<span>` splits | Filing pending |
| GE | Intel-style `<td>` cell splits | Filing pending |
| HON | Intel-style `<td>` cell splits | Filing pending |

**Net validation expectation:** 18-of-25 clean pass + 7 expected failures with documented root cause. Not a Phase 1 blocker. After in-flight Phase 4 fixes land + Intel-style follow-up ships, expectation flips to 24-25/25.

**Action:** before T4.5, verify the Intel-style `<td>` split bug is filed in Edgar_updater TODO. If not, file it as a focused entry following the same self-contained format as the 2026-04-27 cached-path bug entry.

## Sequencing diagram (revised v2)

```
Now (2026-04-28)
  ├─ Track 1: monitor in-flight JPM Phase 4 fix
  │  └─ File Intel-style <td> split bug if not filed
  ├─ Track 3: plan-first → Codex → implement forward-compat wrapper
  └─ Track 2 / T2.4: Phase 1 universe selection (parallel, post-hardening)

Days +1 to +3
  └─ Track 4: re-ingest → canary regression → coverage report → green light
       │
       ▼
  Phase 1 kickoff (corpus scales to 50-100 ticker universe)
```

**Critical path = Track 4** (~1-2 days). Track 3 plumbing parallelizes. Phase 4 in-flight bugs improve baseline but don't block Track 4 — expected failures get documented, not blocked.

## Phase 1 entry gates (revised v2)

Before kicking off Phase 1 corpus ingest:

- [ ] T3.1-T3.3 — Forward-compat plumbing merged + tests passing
- [ ] T3.4 — Live smoke test on JPM/EQH/AES via `filings_source_excerpt` confirms Phase 4 coverage matches Track 4 expected output
- [ ] T4.2 — No canary regressions (Q1-Q5 still pass post re-ingest)
- [ ] T4.3 — Coverage gates met (≥93% 10-K / ≥80% 10-Q / 0 zero-matched)
- [ ] T4.5 — 7 known-failure tickers documented as expected baselines
- [ ] T4.6 — Validation re-ingest report committed with green light
- [ ] T2.4 — Phase 1 ticker universe defined (separate, but pulls from same diverse-sector logic as Appendix A)

**Removed from v1 gates:**
- ~~Phase 5 / L2 validation~~ — never shipping until Bucket C trigger.
- ~~`item_8.source="xbrl_role"`~~ — field not populated by current parser.
- ~~AES `item_8 ≥50K words`~~ — Phase 4 already correct at ~42K.
- ~~`PLAN-targeted-corpus-prewarm-strategy` Codex PASS~~ — edgar_updater workstream, not corpus blocker.

## Risk register (revised v2)

| Risk | Likelihood | Mitigation |
|---|---|---|
| Phase 4 in-flight bug fixes change parser output shape | low | Phase 4 is additive (new fields, no removals); existing tests catch regression. |
| Intel-style `<td>` split bug doesn't get filed in Edgar_updater | med | Block T4.5 on confirming the bug is filed; otherwise file it explicitly during validation. |
| Re-ingest reveals more Phase 4 failures than the 7 known | med | T4.5 documents whatever fails; un-expected failures escalate to Edgar_updater as new bug entries. |
| Phase 4 default-on flip caused undetected regression | low | T4.2 canary regression check on Q1-Q5; if regression, fail fast. |
| Forward-compat plumbing breaks existing source-excerpt path | med | T3.3 unit tests + T3.4 live smoke; keep wrapper backward-compatible (None defaults). |
| Phase 5 unpauses mid-validation | low | Doesn't affect Track 4; bridge stays as-is until Phase 5 §3 cached-path threading ships. |

## Estimated calendar (revised v2)

~3-5 days end-to-end:
- 0.5 day Track 3 plan-first + Codex review
- 0.5 day Track 3 implementation + tests
- 1-2 days Track 4 re-ingest + measurement + report
- Track 1 monitoring runs in parallel; doesn't gate

Down from v1's 2-3 weeks (which assumed a multi-week upstream parser ship was on the critical path). Most upstream work is already shipped.

## Success criteria (revised v2)

1. Corpus plumbing landed as forward-compat — wrapper threads parser kwargs without breaking existing callers.
2. Validation re-ingest on 25 diverse tickers confirms Phase 4 floor coverage on the 18 clean tickers; 7 expected-failure tickers documented with root cause + status.
3. Canary Q1-Q5 still pass after re-ingest.
4. Validation report committed; green light for Phase 1 corpus scaling to 50-100 tickers.

## References

- `docs/planning/CORPUS_ARCHITECTURE.md` — V2.P1 architecture (Codex PASS R7, 2026-04-21)
- `docs/planning/CORPUS_IMPL_PLAN.md` — Phase 0 implementation plan (Codex PASS R14, 2026-04-22)
- `docs/planning/CORPUS_PHASE0_CHECKPOINT.md` — Phase 0 ship signal (G4 at `c167043d`)
- `Edgar_updater/docs/plans/PLAN-section-parser-layered-architecture.md` — original layered plan (Phase 3 portion shipped)
- `Edgar_updater/docs/plans/PLAN-section-parser-phase4-toc-first.md` — Phase 4 plan (shipped, default-on)
- `Edgar_updater/docs/plans/PLAN-section-parser-phase5-xbrl-refinement.md` — Phase 5 plan (paused 2026-04-27)
- `Edgar_updater/docs/explorations/parser_audit_20260423.md` — pre-Phase-4 S&P 500 audit baseline
- `Edgar_updater/docs/TODO.md` — current parser bugs (JPM Phase 4 TOC, Intel-style splits, Phase 5 pause status)
- `docs/TODO.md` F42, F43, F44 — corpus-side follow-ups (filings parser issuer-class drops, amendment routing, source-passage highlighting)
- v1 of this plan: commit `551f549d` 2026-04-27 (superseded by this v2)

---

## Appendix A — 25 ticker validation set (T2.3, locked 2026-04-27)

10 Phase 0 carries + 15 new = **25 tickers total**.

| # | Ticker | Sector | Role | Status |
|---|--------|--------|------|--------|
| 1 | AAPL | Tech (mega-cap) | Healthy baseline | Phase 0 |
| 2 | MSFT | Tech (cloud) | Healthy baseline | Phase 0 |
| 3 | GOOG | Tech (search/ads) | Healthy baseline | Phase 0 |
| 4 | META | Tech (social/AI) | Healthy baseline | Phase 0 |
| 5 | NVDA | Semis (modern) | Sector breadth, modern iXBRL pattern | New |
| 6 | **INTC** | Semis (legacy + ext) | **Intel-style `<tr>` heading failure class** | New |
| 7 | **JPM** | Bank (mega) | **JPM-style anchor-linked TOC failure class** | Phase 0 |
| 8 | BAC | Bank (mega) | JPM-class confirmation pair | New |
| 9 | WFC | Bank (mega) | Audit zero-matched filing class | New |
| 10 | MS | Capital markets | Audit zero-matched filing class | New |
| 11 | BK | Custody bank | Audit zero-matched + custody disclosure shape | New |
| 12 | **EQH** | Insurance (life/holding) | **EQH-style insurance issuer failure class** | Phase 0 |
| 13 | MET | Insurance (life) | EQH-class confirmation pair | New |
| 14 | BRK-B | Conglomerate (insurance hybrid) | Cross-class — conglomerate disclosure + insurance | Phase 0 |
| 15 | GE | Industrial conglomerate | Audit zero-matched filing class | New |
| 16 | HON | Industrial | Audit zero-matched filing class | New |
| 17 | XOM | Energy (integrated) | Healthy baseline | Phase 0 |
| 18 | **AES** | Utility (power) | **AES-style silent boundary misattribution class (Item 7A absorbs 44K words)** | New |
| 19 | TGT | Retail (general) | Healthy baseline | Phase 0 |
| 20 | MCD | Retail (restaurants) | Audit zero-matched filing class | New |
| 21 | JNJ | Healthcare (pharma + devices) | Sector breadth | New |
| 22 | UNH | Health insurance | Sector breadth + insurance overlap | New |
| 23 | PLD | REIT (industrial real estate) | Real estate disclosure shape | New |
| 24 | T | Telecom | Subscriber-based metric disclosure shape | New |
| 25 | DUOT | Microcap | Small-filer stress test | Phase 0 |

### Coverage matrix — parser-failure classes (≥1 per class required)

| Class | Primary | Confirmation |
|---|---|---|
| JPM-style anchor TOC | JPM | BAC, WFC |
| Intel-style `<tr>` headings | INTC | (zero-matched bucket: WFC, MS, BK, GE, HON, MCD overlap) |
| AES-style silent boundary | AES | (BRK-B is partial cross-test for conglomerate boundaries) |
| EQH-style insurance | EQH | MET, BRK-B (insurance-side), UNH (health insurance variant) |

### Sectors covered (13 across 25 tickers)

Tech (5), Banks (4), Capital markets (1), Insurance (3), Conglomerate (1), Industrial (2), Energy (1), Utility (1), Retail (2), Healthcare (2), REIT (1), Telecom (1), Microcap (1).

### Deliberately NOT included (defer to later phases)

- **ADRs / foreign private issuers** — separate filing patterns, defer to Phase 2 weighted sample.
- **52/53-week fiscal year filers** — covered later if observed in Tier 1.
- **Multi-file iXBRL exotic cases** — call out for issuer-specific testing once parser baseline confirmed.
- **Non-S&P 500 names** (except DUOT for microcap stress).
- **Other zero-matched audit names** (C, IBM, USB) — close cousins to BAC/INTC/WFC, redundant for validation purposes.

---

## v1→v2 changelog

- **Status:** v1 → v2; rebase date 2026-04-28
- **Track 1:** restructured around Edgar_updater's actual Phase 3/4/5 sequencing (vs original layered L1-L5 framing). Phase 3+4 SHIPPED, Phase 5 PAUSED, in-flight bugs called out.
- **Track 2:** T2.1 + T2.2 dropped (edgar_updater workstream, not corpus blocker). T2.3 marked complete.
- **Track 3:** reframed as forward-compat only. T3.2 (bridge plumbing) dropped — bridge goes through `get_filing_sections_cached` which doesn't accept the kwargs and won't until Phase 5 unpauses.
- **Track 4:** acceptance criteria revised against Phase 4 measured floor (94.4% 10-K / 82.4% 10-Q / 0 zero-matched). Dropped: AES `item_8 ≥50K`, JPM 10-Q `part1_item1` as gate, L2 source-field assertions. Added T4.5 expected-failure baseline documentation step.
- **New section:** "Known-failure tickers in 25-ticker validation set" — 7 of 25 expected to fail under current Phase 4 with documented root cause.
- **Bucket C:** F44 (markdown↔HTML offset map for source highlighting) added as parked item.
- **Calendar:** ~2-3 weeks → ~3-5 days. Most upstream work is already shipped.
- **References:** added Phase 4 plan, Phase 5 plan, parser audit, F44.
- **Appendix A:** unchanged from v1.
