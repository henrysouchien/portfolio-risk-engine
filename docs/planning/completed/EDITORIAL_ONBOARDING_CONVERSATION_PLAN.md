# Editorial Onboarding Conversation Plan

**Status**: Codex PASS (R13, 2026-04-13)
**Created**: 2026-04-13
**Depends on**: Phase 1 sub-phases B5 (skill prompt + MCP tool), B6 (auto-seeder), F1b (margin annotations)
**Estimated effort**: ~5 hours (single day)

---

## 1. Problem

Phase 1 builds the editorial memory infrastructure: persistence, read/write paths, auto-seeding from portfolio composition, and the `update_editorial_memory` MCP tool. But the analyst only updates memory **reactively** — when the user happens to mention a preference. There is no **proactive interview**.

The design doc (`OVERVIEW_EDITORIAL_PIPELINE_DESIGN.md`, lines 348-360) specifies a conversational onboarding flow where the analyst interviews the user. Success criterion #5: "The onboarding conversation takes < 2 minutes and produces a usable editorial_memory."

The auto-seeder deliberately leaves intent fields empty — `time_horizon`, `primary_goals`, `experience_level`, `concerns` — because portfolio composition cannot reveal them. Only conversation can fill those gaps. Without a proactive trigger, those fields stay empty until the user volunteers the information unprompted. That could be never.

---

## 2. Design Decisions

### 2.1 Trigger mechanism: `onboarding_status` field on `editorial_memory`

The trigger is a field inside the `editorial_memory` JSONB blob, not a separate DB column. This keeps the schema unchanged and lets the analyst skill prompt read and write the onboarding state in the same place it reads everything else.

Two states:
- `"onboarding_status": "complete"` → onboarding done, no nudge, no interview
- Anything else (absent, `null`, `"pending"`) → user needs onboarding

This means the only "skip" signal is an explicit `"complete"`. Any user without that field — whether auto-seeded, chat-created, or pre-existing — gets the onboarding flow. This handles all edge cases: pre-existing rows from chat writes, auto-seeded users, race conditions.

The auto-seeder (`auto_seed_from_portfolio` in `core/overview_editorial/memory_seeder.py`) sets `"onboarding_status": "pending"` on auto-seeded memory for clarity, but the trigger logic does not depend on this — it only checks for `!= "complete"`.

The founder's `"onboarding_status": "complete"` is set via the founder bootstrap script (`scripts/seed_founder_editorial_memory.py`, Phase 1 B5) — NOT in the shared seed file. The seed file (`config/editorial_memory_seed.json`) is the global fallback for users with no DB row and must NOT have `onboarding_status: "complete"` (that would skip onboarding for all new users). Seed-fallback users have no `onboarding_status` → `!= "complete"` → gets onboarding flow.

### 2.2 Delivery surface: analyst skill prompt + margin annotation nudge

Two complementary surfaces:

**A. Skill prompt (primary mechanism):** The analyst skill prompt (`config/skills/morning-briefing.md`, created in Phase 1 B5) gets a new "Onboarding interview" section. When the analyst reads `editorial_memory` in context and sees `onboarding_status` is NOT `"complete"` (absent, null, or `"pending"`), it opens the interview on the user's first message. The analyst uses judgment — it does not blindly run through a script. It adapts based on what the auto-seeder already inferred.

**B. Margin annotation (nudge):** The editorial pipeline emits a `MarginAnnotation` of type `"ask_about"` when the brief is generated for a user whose `onboarding_status != "complete"`. The annotation says: "I want to make sure your briefing leads with what you actually care about. Quick conversation?" with a `prompt` field that, when clicked, sends an opening message to the chat. This uses the existing `MarginAnnotation` model and the `overviewBriefStore` → `ChatMargin` flow already planned in Phase 1 F1b.

The margin annotation is a nudge, not a gate. If the user ignores it and asks a normal question, the analyst skill prompt detects `onboarding_status != "complete"` and weaves the interview into the natural conversation flow — it does not block the user from getting an answer.

### 2.3 Conversation flow: skill prompt driven, not scripted

The skill prompt provides the analyst with:
- The opening line
- A decision tree for follow-ups (risk, returns, trading, "I don't know")
- Instructions to acknowledge what the auto-seeder already inferred
- Instructions on what fields to fill and when to call `update_editorial_memory`
- Completion criteria

The conversation is **not** a rigid wizard. The analyst reads the auto-seeded memory for profile inference and uses live portfolio tools for specific numbers, then acknowledges what it sees ("You've got 15 positions, AAPL at 22% of the book — I'm reading this as concentrated single-name exposure with a growth tilt. What actually matters to you when you look at this?") and asks follow-up questions to fill the intent gaps.

### 2.4 Field mapping

| Field | Auto-seeder fills? | Interview fills? |
|-------|-------------------|-----------------|
| `investor_profile.style` | Yes (from position types) | Refines if user disagrees |
| `investor_profile.risk_tolerance` | Yes (from volatility) | Refines |
| `investor_profile.time_horizon` | No | Yes |
| `investor_profile.experience_level` | No | Yes (inferred from how they talk) |
| `investor_profile.primary_goals` | No | Yes |
| `investor_profile.concerns` | No | Yes |
| `editorial_preferences.lead_with` | Yes (from top signals) | Refines |
| `editorial_preferences.care_about` | Yes | Refines |
| `editorial_preferences.less_interested_in` | No | Yes |
| `editorial_preferences.sophistication` | No | Yes (inferred from vocabulary) |

### 2.5 When `update_editorial_memory` is called

Once, at the end of the interview. Not after each answer. Rationale: the interview is 2-3 exchanges. One call with the final blob is cleaner than three incremental updates that each invalidate the brief cache. How the blob is built depends on the path — see §3.1 prompt completion rules (merge into auto-seeded memory if `pending`, start clean if seed-fallback).

Exception: if the user says "that's enough" mid-interview, the analyst calls `update_editorial_memory` with whatever it has so far and sets `onboarding_status` to `"complete"`. Partial onboarding is better than no onboarding.

### 2.6 Completion criteria

The analyst sets `"onboarding_status": "complete"` when ANY of:
- It has filled `primary_goals` and at least one of `time_horizon` or `concerns`
- The user says "that's enough" / "let's move on" / "I don't know" to the opening question
- The user has given 3+ substantive answers

The analyst does NOT require all fields. The design doc says "< 2 minutes and produces a usable editorial_memory." Usable means the policy layer has enough signal to differentiate this user's brief from the default.

---

## 3. Files to Modify

### 3.1 `config/skills/morning-briefing.md` (created in Phase 1 B5)

Add a new section after "Maintaining editorial_memory":

```markdown
## Onboarding interview

When `editorial_memory.onboarding_status` is NOT `"complete"` (absent, null, or
`"pending"`), this user hasn't been through the onboarding interview yet. Run a short interview to
fill the gaps. Conversation, not a form.

**Read the existing memory AND portfolio context.** The auto-seeder inferred
`investor_profile.style` and `editorial_preferences.lead_with` from composition, but
the memory does not contain raw portfolio stats. Use the live portfolio context
available in your chat tools (positions, risk) for specific numbers. Lead with what
you see:

> "You've got [N] positions, [top ticker] at [weight]% of the book, and the portfolio
> runs about [volatility]% annual vol. I'm reading this as [use investor_profile.style
> from memory — e.g., 'concentrated single-name exposure with a growth tilt']. Before
> I start building your morning briefing — what actually matters to you when you look
> at this?"

Use real numbers from portfolio tools. If the memory has `onboarding_status: "pending"`
(auto-seeded), you can also reference `investor_profile.style` from the memory as a
starting point. But if `onboarding_status` is absent (seed-fallback — no auto-seed has
run yet), do NOT trust the memory profile — it's the shared default, not this user's
inference. In that case, derive everything from live portfolio tools only.

**Follow-ups based on response:**
- Risk → "What keeps you up at night — the [top ticker] concentration, sector exposure,
  or a broad drawdown?"
- Returns → "Are you measuring against SPY, or is this about absolute return and income?"
- Trading → "How often are you making moves — weekly, quarterly, or mostly sitting?"
- "I don't know" → "Fair enough. I'll lead with concentration and risk for now and adjust
  once I see what you actually look at." Then set `onboarding_status` to `"complete"` —
  this IS a valid completion. Call `update_editorial_memory` with what you have.

**What you're filling:**
- `investor_profile.time_horizon` (long_term / medium_term / short_term)
- `investor_profile.primary_goals` (capital_appreciation, income, preservation, trading)
- `investor_profile.concerns` (concentration_risk, drawdown, factor_exposure, etc.)
- `investor_profile.experience_level` (infer from how they talk — don't ask directly)
- `editorial_preferences.less_interested_in` (what they explicitly dismiss)
- `editorial_preferences.sophistication` (infer from vocabulary and specificity)

**Completion:** After 2-3 exchanges, build the final memory blob and call
`update_editorial_memory` with `onboarding_status: "complete"`. Usable beats
comprehensive — one or two filled intent fields is enough.

**How to build the blob depends on which path you're on:**
- If `onboarding_status == "pending"` (auto-seeded): the memory in context IS
  user-specific. Merge your findings into it.
- If `onboarding_status` is absent (seed-fallback): the memory in context is the
  shared default — do NOT merge into it. Start a clean memory with only what you
  learned from the conversation + what you can infer from live portfolio tools.
  Set `version: 1` and populate only the fields you have evidence for.

**If the user asks a normal question first:** Answer it. Then: "One thing — I want to
make sure your morning briefing leads with what you actually care about. Quick question:
what matters most when you look at this portfolio?" If they wave it off, call
`update_editorial_memory` with `onboarding_status: "complete"` (using the same
path-dependent merge rules above) and move on.

**Don't nag.** If the user declines ("no thanks", "not now", "skip"), call
`update_editorial_memory` with `onboarding_status: "complete"` immediately. An explicit
decline is final — do not re-offer. If they just ignore the topic and ask other questions,
answer normally. The nudge annotation stays until they engage or decline, but you don't
bring it up again after one natural offer per session.
```

### 3.2 `core/overview_editorial/memory_seeder.py` (created in Phase 1 B6)

Modify `_build_seed_prompt()` to include `"onboarding_status": "pending"` in the required output fields. One line change to the prompt string.

Add fallback injection in `auto_seed_from_portfolio()` after Pydantic validation, before `seed_editorial_memory_if_missing`:

```python
# After Pydantic validation, before seed_editorial_memory_if_missing:
if "onboarding_status" not in seeded_memory:
    seeded_memory["onboarding_status"] = "pending"
```

This ensures every auto-seeded user gets flagged for onboarding regardless of LLM compliance.

### 3.3 `actions/overview_brief.py` (created in Phase 1 B4)

Add onboarding nudge logic after brief composition. When the brief is composed for a user whose `editorial_memory` does not have `onboarding_status == "complete"`, append a `MarginAnnotation` to the brief's `margin_annotations` list. Insert this after the brief is composed and before `compute_changed_slots()`:

```python
# In get_brief(), after brief composition, before diff computation:
if context.editorial_memory.get("onboarding_status") != "complete":
    new_brief.margin_annotations.append(MarginAnnotation(
        anchor_id="onboarding_nudge",
        type="ask_about",
        content="I want to make sure your briefing leads with what you actually care about. Quick conversation?",
        prompt="What should my morning briefing focus on?",
        changed_from_previous=False,
    ))
```

### 3.4 `config/editorial_memory_seed.json` (existing)

**No change.** This file is the global fallback for ANY user with no DB row — it is NOT founder-specific. Do NOT add `onboarding_status` to it. Users on seed fallback have no `onboarding_status` → `!= "complete"` → gets onboarding. This is correct.

### 3.5 `scripts/seed_founder_editorial_memory.py` (created in Phase 1 B5)

Set `"onboarding_status": "complete"` on the founder's memory row. Since `seed_editorial_memory_if_missing` uses `ON CONFLICT DO NOTHING`, rerunning the bootstrap script will not update an existing row. Two options:

1. **If the founder row already exists** (Phase 1 B5 already ran the bootstrap): use `set_editorial_memory` to update the existing row. Add a one-off migration step or a `--update-founder` flag to the bootstrap script that reads the current memory, adds `onboarding_status: "complete"`, and writes it back via `set_editorial_memory`.
2. **If the founder row does not yet exist** (fresh deploy): add `"onboarding_status": "complete"` to the seed dict before calling `seed_editorial_memory_if_missing`.

The bootstrap script should handle both cases — check if the row exists, then insert or update accordingly.

### 3.6 `models/overview_editorial.py` (created in Phase 1 B1)

**No change needed.** `EditorialMemory` Pydantic model already accepts arbitrary fields (JSONB blob with loose validation). Verify `onboarding_status` passes through without error.

---

## 4. User Flow

### New user:
1. User connects brokerage or imports CSV
2. `auto_seed_from_portfolio()` fires (Phase 1 B6 hook) — may complete before or after step 3
3. User opens Overview — brief generated, nudge appears (trigger: `onboarding_status != "complete"`)

**Two sub-paths depending on auto-seed timing:**

- **Path A (auto-seed done):** Memory has `onboarding_status: "pending"` + user-specific profile. Analyst references both live tools and auto-seeded `investor_profile.style`.
- **Path B (auto-seed pending — CSV race):** Gateway falls back to shared seed (no `onboarding_status`). Nudge still appears. Analyst uses live portfolio tools ONLY (shared seed profile is not user-specific). If analyst writes via `update_editorial_memory` before auto-seed finishes, the seeder's DO NOTHING no-ops cleanly.

4. User clicks nudge (or opens chat) — analyst sees `onboarding_status != "complete"`
5. Analyst opens interview using live portfolio data (+ auto-seeded inference if `onboarding_status == "pending"`)
6. 2-3 exchanges (< 2 minutes)
7. Analyst calls `update_editorial_memory` with final blob + `onboarding_status: "complete"` (merge if Path A, clean blob if Path B)
8. Next brief uses enriched memory — nudge disappears

### User who skips the nudge:
- `onboarding_status: "pending"` persists, nudge annotation stays on Overview
- If user opens chat with a normal question, analyst answers first, then makes one natural offer per session
- If user explicitly declines ("no thanks", "skip"), analyst sets `onboarding_status: "complete"` immediately
- If user just never engages with the interview topic, the nudge persists but the analyst doesn't push beyond one offer per session

### Founder (bootstrap-seeded):
- `onboarding_status: "complete"` set by `scripts/seed_founder_editorial_memory.py` → no nudge, no interview
- Normal editorial memory maintenance via ongoing chat

---

## 5. Implementation Order

1. Modify `_build_seed_prompt()` in `memory_seeder.py` — add `onboarding_status: "pending"` to required output (~30 min)
2. Add `onboarding_status` fallback injection in `auto_seed_from_portfolio()` (~15 min)
3. Add onboarding nudge annotation logic in `actions/overview_brief.py` (~30 min)
4. Write the "Onboarding interview" section in the analyst skill prompt (~1 hour)
5. Write backend tests (~2 hours)
6. Manual smoke test with a test user (~30 min)

**Total: ~5 hours.**

---

## 6. Test Requirements

**Backend tests (11 tests):**

1. `auto_seed_from_portfolio` output always includes `onboarding_status: "pending"` — even if LLM output omits it
2. Shared seed file (`editorial_memory_seed.json`) does NOT have `onboarding_status` — verify absence (seed-fallback users must get onboarding)
3. Brief generation for user with `onboarding_status: "pending"` includes the `MarginAnnotation` nudge with `anchor_id="onboarding_nudge"`
4. Brief generation for user with `onboarding_status: "complete"` does NOT include the nudge
5. Brief generation for user with no `onboarding_status` field DOES include the nudge (absent ≠ complete)
6. Brief generation for pre-existing row created via `set_editorial_memory` (no `onboarding_status`) DOES include the nudge
7. `update_editorial_memory` with `onboarding_status: "complete"` persists correctly and clears the nudge on next brief
8. Founder bootstrap script (`seed_founder_editorial_memory.py`) produces a row with `onboarding_status: "complete"`
9. Gateway enricher passes `onboarding_status` through to chat context (part of JSONB blob — verify round-trip)
10. Seed-fallback path (no DB row) → editorial_memory has no `onboarding_status` → brief DOES include nudge
11. Seed-fallback onboarding completion: when `update_editorial_memory` is called on a seed-fallback user, the persisted memory does NOT contain shared seed defaults (e.g., founder's `investor_profile.style` from `editorial_memory_seed.json`) — only fields from the conversation + live tools

**Manual integration tests (5 scenarios):**

1. **Path A**: Open chat with `onboarding_status: "pending"` in context — analyst opens interview referencing auto-seeded profile + live tools
2. **Path A continued**: Answer "I care about risk" — analyst follows up with the risk branch
3. **Path B**: Open chat with NO `onboarding_status` (seed-fallback) — analyst opens interview using live portfolio tools ONLY (does not reference shared seed profile as user-specific)
4. **Early exit (decline)**: Say "that's enough" mid-interview — analyst calls `update_editorial_memory` with partial results and `onboarding_status: "complete"`
5. **Early exit (I don't know)**: Answer "I don't know" to the opening question — analyst calls `update_editorial_memory` with `onboarding_status: "complete"` + minimal blob (no shared seed defaults carried over) and does not continue the interview

---

## 7. Acceptance Gates

1. New user who connects a brokerage or imports CSV sees an onboarding nudge in the chat margin on first Overview load (nudge appears even before auto-seed completes — seed-fallback has no `onboarding_status`, which triggers the nudge)
2. Clicking the nudge starts a conversation where the analyst uses live portfolio data (and auto-seeded inference if available) to open the interview
3. Conversation takes < 2 minutes and produces a usable `editorial_memory` — ideally `primary_goals` + one of `time_horizon`/`concerns`, but partial is acceptable (user can say "that's enough" or "I don't know" at any point → `onboarding_status: "complete"` with whatever was gathered)
4. After onboarding completes, nudge disappears and analyst does not re-prompt
5. Founder (with existing seed) never sees an onboarding prompt
6. User who declines the interview gets `onboarding_status: "complete"` immediately — no re-prompting

---

## 8. Risks

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| LLM analyst ignores the skill prompt and doesn't run the interview | Medium | Test with real chat; if too subtle, make instruction more forceful |
| User finds the interview annoying | Low | Explicit decline → immediate complete; one natural offer per session max; nudge is passive |
| `onboarding_status` field conflicts with `EditorialMemory` validation | Low | Model uses loose validation (`extra="allow"`) — verify in tests |
| Auto-seeder LLM doesn't include `onboarding_status` in output | Low | Fallback injection in Python ensures it's always present |

---

## 9. Rollback

Remove the "Onboarding interview" section from the skill prompt. Remove the nudge annotation logic from `actions/overview_brief.py`. Remove the `onboarding_status` injection from `memory_seeder.py`. No schema changes to revert — the field lives inside the JSONB blob.
