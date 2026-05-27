# Skill Alignment Audit: `filing-source-selection` ↔ `filing-extractor`

**Status:** Working document. Surfaced from 2026-05-22 Vals q025 investigation.
Not yet a shipping plan — captured for a focused architectural session.

**Repos:**
- Skills live in `AI-excel-addin/api/memory/workspace/notes/skills/`
- Tests live in `AI-excel-addin/tests/`

---

## TL;DR

Two skills with overlapping section-routing responsibilities produced conflicting signals on a regulatory-risk question (Vals q025 PCTY FY24 10-K). The agent (Hank) loaded both skills, then followed the more-concrete schema-based routing in `filing-extractor` and missed sections that `filing-source-selection`'s intent-based source pack would have included.

The simplest fix is **content alignment** (add Item 1 to `risk_factors` schema's routing when the intent is `regulatory_risk`). The bigger question is **whether the two skills' section-routing responsibilities should structurally diverge** (single source of truth) or remain duplicated with explicit precedence rules.

This doc captures the audit so the architectural decision can be made in a focused session.

---

## How this surfaced

Vals q025 — *"Summarize the regulatory risks Paylocity's (NASDAQ: PCTY) lists in its FY 2024 10-K."*

7 of 8 correctness checks passed 3/3. The failing check expected an enumeration of named statutes: FTC rules, HIPAA, CCPA/CPRA, BIPA, state breach notification laws.

Investigation:
1. **Corpus has the statutes**: all 6 are in a single sentence at char 42854 of PCTY FY2024 10-K.
2. **Search returned the right section**: `filings_search` ranked PCTY FY2024 **Item 1 (Business)** in the top 2 hits for both queries Hank ran.
3. **Hank read Item 1A only**: `filings_read` was called with `char_start=56245, char_end=121472` (Item 1A Risk Factors). Item 1 covers chars 6089–56244 and was not read.
4. **Item 1 is the only place 4 of the statutes appear**: Federal Trade Commission, state breach notification, CPRA, and BIPA each appear exactly once in the 10-K, all in the Item 1 paragraph. They do NOT appear anywhere in Item 1A.
5. **Both skills were loaded by Hank**: `invoke_skill: filing-source-selection` (turn 1, 25KB content) and `invoke_skill: filing-extractor` (turn 3, 13KB content).
6. **Both skills' PROSE says to read Item 1 + Item 1A for regulatory_risk**, but `filing-extractor`'s concrete routing tables route the `risk_factors` schema to Item 1A only.

---

## The two skills' purposes (current scope, in design intent)

### `filing-source-selection` — Routing / Discovery
- Inputs: question, ticker, period
- Classifies the question into one of 9 intents: `regulatory_risk`, `risk_factor`, `concentration_risk`, `revenue_disaggregation`, `debt_terms`, `security_offering_terms`, `proxy_governance`, `non_gaap_reconciliation`, `deal_terms`, `generic_filing_question`
- For each intent, produces a **source pack**: the sections required for synthesis
- Owns the **intent → section** mapping

### `filing-extractor` — Extraction
- Inputs: a filing section (file path), one or more schemas
- Has 4 extraction schemas defining WHAT entities to extract: `risk_factors`, `forward_guidance`, `capital_allocation`, `liquidity_leverage`
- Each schema lists entity types (e.g., `risk_factors` extracts `risk_factor`, `risk_change`, `mitigation_action`)
- Owns the **schema → entities** mapping
- **Also currently does schema → section routing** (this is the scope creep — see Audit)

### Intended handoff
```
Question → filing-source-selection (intent + source pack)
        → filing-extractor (schemas on the source-pack sections)
        → final answer
```

`filing-extractor`'s Step 1 says: *"Verify the source pack selected by filing-source-selection or infer the required sections from the question."* But there's no structured passed-state — the source pack is implicit in the agent's context, not data passed between skills.

---

## The conflict (q025-anchored)

| Layer | Routing | For regulatory_risk question |
|---|---|---|
| `filing-source-selection` (intent → sections) | intent = `regulatory_risk` | source pack = **Item 1 + Item 1A** |
| `filing-extractor` (schema → sections) | schema = `risk_factors` (closest) | sections = **Item 1A only** |

There is no `regulatory_risk` schema in `filing-extractor`. The agent maps the intent to the closest schema (`risk_factors`), which routes to Item 1A only.

**Both skills' prose** says to read Item 1 + Item 1A. **`filing-extractor`'s concrete routing tables** say Item 1A only. The agent follows the concrete routing.

---

## Full audit: intent ↔ schema cross-reference

| `filing-source-selection` intent | Source pack | `filing-extractor` schema (closest) | Schema's section routing | Aligned? |
|---|---|---|---|---|
| `regulatory_risk` | **Item 1 + Item 1A** + privacy/cyber risk factors | `risk_factors` | Item 1A only | **✗ MISMATCH** (Item 1 missing) |
| `risk_factor` | Item 1A | `risk_factors` | Item 1A only | ✓ Aligned |
| `concentration_risk` | Financial statement notes + concentration-risk tables | none directly; if routed to `risk_factors` | Item 1A only | **✗ MISMATCH** (different sections) |
| `revenue_disaggregation` | Notes to financial statements, revenue note, segment note, tables | no schema | — | filing-extractor not the right tool |
| `debt_terms` | Debt note and debt tables | no schema | — | filing-extractor not the right tool |
| `security_offering_terms` | Prospectus supplement, 8-K, certificate of designations, indenture | no schema | — | filing-extractor not the right tool |
| `proxy_governance` | DEF 14A | no schema | — | filing-extractor not the right tool |
| `non_gaap_reconciliation` | Reconciliation table in MD&A, earnings release, shareholder letter, exhibit | `forward_guidance` partially | Item 7 MD&A | △ Partial overlap |
| `deal_terms` | 8-K, 425, merger agreement, primary materials | no schema | (8-K earnings is `forward_guidance`-coded) | △ Partial |
| `generic_filing_question` | Corpus search | none | — | N/A |

`filing-extractor` schemas without intent counterparts (routed via `guidance-extraction` skill, not in conflict here):
- `forward_guidance`, `capital_allocation`, `liquidity_leverage` → Item 7 MD&A

**Two concrete misalignments to address:**
1. `regulatory_risk` intent → `risk_factors` schema is missing Item 1 (the q025 case)
2. `concentration_risk` intent shouldn't default to `risk_factors` schema (different source pack entirely)

---

## Architectural question (the bigger one)

The conflict exists because **section-routing is duplicated** across two skills. Two ways to resolve:

### Option A — Alignment (content-level fix, no architecture change)

Both skills keep their current responsibilities; both still do section routing. Update `filing-extractor`'s schema routing to match `filing-source-selection`'s intent source packs for overlap cases.

Concrete minimal edit:
```
- For `10-K`:
  - `risk_factors`: use `get_filing_sections` to fetch Item 1A as file-backed output.
    If the upstream filing-source-selection intent is `regulatory_risk`, ALSO
    fetch Item 1 (Business — governmental regulation) so the named-statute
    enumeration is in evidence. Item 1A alone cannot satisfy `regulatory_risk`.
```

Plus a test (`test_filing_extractor_schema_routing_aligns_with_source_selection_intent`) that asserts the alignment holds and breaks if future edits drift.

**Pros:** smallest blast radius; no scope change; one surgical edit + test.
**Cons:** doesn't fix the structural reason the conflict happened (duplicate routing); future intents that map imperfectly to schemas could create new conflicts.

### Option B — Restructure / scope discipline

`filing-extractor` removes its section-routing tables entirely. Schemas define WHAT entities to extract; section selection comes from `filing-source-selection` (or an explicit caller-supplied source pack).

Each skill stays in its lane:
- `filing-source-selection`: intent → source pack (sections)
- `filing-extractor`: schema → entities (extraction)

**Pros:** removes the conflict by removing the duplication; scope boundaries become clean; future intent additions don't create new conflicts.
**Cons:** larger refactor; touches multiple skills (`metric-trend-analysis`, `acquisition-strategy-analysis` chain through these); requires updating tests; needs Codex review on the broader refactor plan.

### Option C (raised then declined) — Centralization in one skill
- Initially proposed as "single source of truth in filing-source-selection."
- User reframed correctly: the issue isn't centralization (the skills have different purposes); the issue is that `filing-extractor` has scope creep into section routing. Not centralize; just stop one skill from doing the other's job.
- Effectively the same as Option B in practice.

---

## Hank's actual q025 trace (evidence)

Gateway session: `sess_a6b9233` (PCTY q025 in `static_public_20260522T162730Z_final_postship` run)

| Turn | Tool | Result |
|---|---|---|
| 1 | `invoke_skill: filing-source-selection` | 25,254 bytes (full markdown content loaded into parent agent context) |
| 2 | `filings_search` × 2, `filings_list` | 8 hits including PCTY FY2024 Item 1 (rank −18.96) AND Item 1A (rank −17.33) |
| 3 | `invoke_skill: filing-extractor` | 13,430 bytes |
| 4 | `filings_search` × 2 (second query), `filings_list` | Same coverage; query 2 reranks Item 1A above Item 1 |
| 5 | `filings_read` on PCTY 10-K **char 56245–121472 (Item 1A only)** | 66,206 bytes content (Item 1A in full) |
| 6 | Synthesis | Answer cites HIPAA + GDPR + CCPA (mentioned in Item 1A); missing FTC, CPRA, BIPA, state breach notification (in Item 1 only) |

Key observation: **all thinking blocks returned 0 chars** — the agent's reasoning between tool calls is opaque. We cannot directly observe why Hank picked Item 1A over Item 1 despite both skills' prose telling him to read both.

---

## Invocation mode context (relevant background)

Both skills were loaded via `invoke_skill` — the parent agent's tool that returns the skill's markdown content as a tool response (~25KB for filing-source-selection, ~13KB for filing-extractor). This is **text injection mode**, not sub-agent execution.

In `invoke_skill` mode, the parent agent reads the skill content and applies it with its own judgment. The skill is advisory text in the parent's context. F136 ("rule in context ≠ rule followed") applies.

Both skills also have sub-agent metadata in their frontmatter (`agent_callable: true`, `max_turns`, `timeout`) — meaning they CAN run as dedicated sub-agents via the agents-mcp `agent_run` endpoint. In that mode, a dedicated sub-agent loop executes the skill's workflow with its own tool budget. F136 is less applicable because the sub-agent is single-purpose.

The Vals harness uses `invoke_skill` mode. The sub-agent mode wasn't exercised in q025.

This means: even if the skill content is perfect, `invoke_skill` mode is the weakest enforcement layer in the stack (versus tool-layer signals or dedicated sub-agents).

---

## Test-fitting concern (separate finding)

`filing-source-selection` has **5+ accumulated "read Item 1 + Item 1A for regulatory_risk" emphasis lines** (lines 36, 71, 99, 109, 122, 170). The accumulation suggests prior failure-mode patching that didn't address the actual conflict — the patches kept adding emphasis instead of fixing the conflict in `filing-extractor`.

Should be consolidated to ONE canonical statement during the alignment work.

---

## Open questions for the architectural session

1. **Alignment vs Restructure**: Option A (3-line edit + alignment test) is fastest but doesn't fix the duplicate-routing root cause. Option B is the structural fix. Which is the right move for the longer term?

2. **Scope discipline as a general principle**: Are there other skills with similar scope creep (one skill doing another's job)? Worth a broader audit of skill responsibilities?

3. **Structured handoff between skills**: The current handoff between filing-source-selection and filing-extractor is implicit (source pack lives in agent context, not passed data). Should there be a structured passed-state mechanism (e.g., a return shape that downstream skills consume)?

4. **`invoke_skill` vs `agent_run` for these workflows**: For complex multi-step skills like filing-source-selection → filing-extractor, would running them as dedicated sub-agents improve compliance with their own directives? Trade-off: latency + cost increase.

5. **Tool-layer enforcement (the q030/q050/q048 pattern)**: Could the section-routing alignment be enforced at the tool layer (e.g., `filings_search` emits a `coverage_hint` when same-ticker hits span multiple top-ranked sections)? Tool-layer enforcement bypasses F136.

6. **Test convention**: Where should skill-alignment tests live? `tests/test_skill_templates.py` is the existing home; `tests/test_skill_alignment.py` could be a new file dedicated to cross-skill agreements.

---

## Recommended next steps for the architectural session

1. **Decide on Option A vs B** based on appetite for refactor depth.
2. **If A**: ship the 3-line edit + alignment test; rerun q025 to verify.
3. **If B**: plan the restructure (which skills to touch, test deltas, migration order); Codex review the plan; ship in stages.
4. **Either way**: address the test-fitting accumulation in `filing-source-selection`. Consolidate the 5+ emphasis lines to ONE canonical statement.
5. **Tool-layer angle**: investigate whether `filings_search` could emit cross-section coverage hints (parallel to today's tool-layer fixes for q030/q050/q048). Independent of A/B choice.

---

## Cross-references

- Vals run that surfaced this: `evals/vals-finance-agent/results/static_public_20260522T162730Z_final_postship/`
- q025 classification entry (current): `evals/vals-finance-agent/config_d_classifications.json` (q025: `answer_completeness_variance` — needs another update after this architectural work lands)
- Vals recap with the broader May-20→22 arc: `docs/research/vals-finance-agent/config-d-2026-05-20-recap.md`
- Related lesson memory: `feedback_verify_rule_closes_question_before_keeping.md` (the q048 misdiagnosis lesson is relevant — applies same caution to this architectural work)
- Skill files (canonical paths):
  - `AI-excel-addin/api/memory/workspace/notes/skills/filing-source-selection.md`
  - `AI-excel-addin/api/memory/workspace/notes/skills/filing-extractor.md`
  - Tests: `AI-excel-addin/tests/test_skill_templates.py`, `AI-excel-addin/tests/test_benchmark_mode.py`
