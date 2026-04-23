# Docs Link Check — Fix main CI Failures

## Context

The `Docs Link Check` GitHub Actions workflow has been failing on every push to `main` since ~PR #5 (first observed failure 2026-04-22, most recent run `24811970676` after PR #7 merge). Lychee reports **22 broken links across 7 markdown files**. No links are exclusion-list URLs — all 22 are genuine failures. This plan fixes all 22 so CI goes green and stays there.

> **Revision history**
> - **R0** → initial draft.
> - **R1** → applied Codex review findings (thread `019db812-26bb-7fa0-b79a-1ccd7b24c908`): corrected Category B undercount (13 → 14), dropped stale `(line N)` prose (source line numbers had moved; `orchestrator.py:757` is now at L792+, `actions/overview_brief.py:31` is blank, etc.), switched lychee `--exclude-path` to regex form (`^docs/_archive/`) per lychee's documented RE semantics, repointed `WORKFLOW_PATTERNS.md` pointer to the real current path `investment_tools/docs/completed/WORKFLOW_PATTERNS.md`, corrected README_WEB_APP_PLATFORM line number (126 → 128), and expanded the observability rewrite block to concrete per-row templates.
> - **R2** → Codex nits on R1: tightened wording ("literal diffs" → "concrete rewrite templates"), fixed two residual stale phrases in prose (old `investment_tools/docs/WORKFLOW_PATTERNS.md` path, "glob addition" → "regex addition").

Failures cluster into three distinct root causes, each with its own right fix. Nothing architectural; this is markdown hygiene plus one workflow-config tweak.

## Root causes (from lychee output + file inspection)

### A. Broken cross-refs inside `docs/_archive/` (7 errors, 3 source files)

Archive markdown files link to peer archive files that were moved/deleted when the archive was reshuffled. These archive files are deprecated — not actively maintained — and existing lychee config already excludes `docs/third-party/**` and `docs/planning/**` on the same logic.

| Source file | Broken link targets |
|---|---|
| `docs/_archive/guides/README_WEB_APP_PLATFORM.md` (L128) | `./LICENSE` |
| `docs/_archive/third-party/VERCEL_AI_SDK_FULL_INTEGRATION_GUIDE.md` (L680–682) | `./CHAT_SYSTEM.md`, `./FRONTEND_ARCHITECTURE.md`, `./STREAMING_CHAT_INTEGRATION_SUMMARY.md` |
| `docs/_archive/third-party_VERCEL_AI_SDK_FULL_INTEGRATION_GUIDE.md` (L680–682) | same three (flat-file duplicate that lives next to the `third-party/` folder) |

**Fix:** add a `docs/_archive/` pattern to lychee's `--exclude-path` list. Per lychee's docs, `--exclude-path` values are **regular expressions**, not globs, so the pattern is `^docs/_archive/` (anchored). This matches both the sub-directories under `docs/_archive/` and the flat-file duplicate at `docs/_archive/third-party_VERCEL_AI_SDK_FULL_INTEGRATION_GUIDE.md` since its path starts with `docs/_archive/`. Keeping the existing `docs/third-party/**` + `docs/planning/**` entries untouched — they work today, so changing them is out of scope for this fix.

### B. Absolute `/Users/henrychien/…` hrefs baked into markdown (14 errors, 3 source files)

Markdown links of shape `[text](/Users/henrychien/Documents/Jupyter/risk_module/path/to/file.py:49)`. Only resolve on your laptop; CI reports `Error building URL … To resolve root-relative links in local files, provide a root dir`. The `:49` suffix also trips lychee's URL parser (looks like a port). All target files confirmed to exist in-repo except the vals-bench one.

| Source file | Line | Current href (abbreviated) | Target confirmed |
|---|---|---|---|
| `docs/ops/EDITORIAL_ARBITER_MODEL_BENCHMARK.md` | 12 | `…/scripts/benchmark_editorial_arbiter.py:1` | ✓ |
| | 13 | `…/tests/core/overview_editorial/eval_scenarios` (dir) | ✓ |
| | 15 | `…/tests/core/overview_editorial/test_eval_scenarios.py:1` | ✓ |
| | 17 | `…/core/overview_editorial/llm_arbiter.py:49` | ✓ |
| `docs/ops/EDITORIAL_PIPELINE_OBSERVABILITY.md` | 27, 36 | `…/actions/overview_brief.py:31` (×2) | ✓ |
| | 28, 37 | `…/core/overview_editorial/llm_arbiter.py:49` (×2) | ✓ |
| | 29 | `…/core/overview_editorial/editorial_state_store.py:91` | ✓ |
| | 30 | `…/core/overview_editorial/memory_seeder.py:36` | ✓ |
| | 43 | `…/core/overview_editorial/orchestrator.py:757` | ✓ |
| | 52 | `…/core/overview_editorial/llm_arbiter.py:118` | ✓ |
| | 53 | `…/core/overview_editorial/editorial_state_store.py:27` | ✓ |
| `docs/research/vals-finance-agent-day1-verifications.md` | 145 | `…/risk_module-vals-bench/agent/registry.py:64` | different repo, **no public URL** |

**Fix for files in `docs/ops/`:** rewrite each href as a repo-relative path from the markdown file (`../../scripts/...`, `../../core/...`, `../../actions/...`, `../../tests/...`). **Drop the `:LINE` suffix entirely** — don't preserve it in prose either. Reason: Codex review (R1) verified that the original line numbers have already drifted (`orchestrator.py:757` is now a function parameter; the warning sites referenced there have moved to L792/L813/L837/L856/L870/L881/L933 as code grew; `actions/overview_brief.py:31` is blank; `llm_arbiter.py:49` is `model_config`). Preserving stale line numbers in prose would leave the docs misleading after CI goes green. If a future author wants line-level click-through, they can add a `#L49` anchor at that point — out of scope for this cleanup.

**Fix for `vals-finance-agent-day1-verifications.md` L145:** sibling repo `risk_module-vals-bench` isn't published anywhere discoverable. Demote the link to plain backtick text: `` Verified against `agent/registry.py` (in the `risk_module-vals-bench` sibling repo):`` — no link, no stale line number.

### C. Cross-repo relative escape to missing file (1 error, 1 source file)

`docs/standards/AGENT_ORCHESTRATION_LESSONS.md:5` points `../../../investment_tools/docs/WORKFLOW_PATTERNS.md`. The target was moved to `investment_tools/docs/completed/WORKFLOW_PATTERNS.md` (Codex review R1 caught this — file exists locally at the new path). `investment_tools` has no discoverable public GitHub URL, so we still can't make it a click-through link from this repo's CI-checked markdown.

**Fix:** demote to plain backtick text but point at the **real current path**: `` **See also:** `investment_tools/docs/completed/WORKFLOW_PATTERNS.md` — broader multi-Claude orchestration patterns, research data quality, and documentation habits. `` (preserves the prose pointer, no dead link, path reflects reality).

## Files to modify

| File | Change |
|---|---|
| `.github/workflows/docs-link-check.yml` | Insert `--exclude-path "^docs/_archive/"` between the two existing excludes (L31-32). Regex, not glob — per lychee docs. |
| `docs/ops/EDITORIAL_ARBITER_MODEL_BENCHMARK.md` | Rewrite 4 links (L12, 13, 15, 17) to repo-relative, drop `:LINE` from hrefs and from surrounding prose. |
| `docs/ops/EDITORIAL_PIPELINE_OBSERVABILITY.md` | Rewrite 9 links (L27, 28, 29, 30, 36, 37, 43, 52, 53) to repo-relative, drop `:LINE` from hrefs and from surrounding prose. |
| `docs/research/vals-finance-agent-day1-verifications.md` | Demote L145 link to plain backtick text. |
| `docs/standards/AGENT_ORCHESTRATION_LESSONS.md` | Demote L5 `WORKFLOW_PATTERNS.md` link to plain backtick text. |

No archive file edits (they're excluded wholesale).

## Not in scope

- Restoring or reconciling archive cross-refs (archive is deprecated content, not maintained).
- Finding a public URL for `investment_tools/docs/completed/WORKFLOW_PATTERNS.md` — the "see also" pointer as plain text is good enough; if the `investment_tools` repo is later published or synced, it can be re-linked.
- Publishing `risk_module-vals-bench` publicly so the link can be restored.
- Adding a pre-commit hook that rejects `/Users/` hrefs (mentioned as future-work hedge; defer — current lychee CI now catches regressions once green).

## Execution path

Per CLAUDE.md `Mandatory Plan-First Workflow`:

1. **This plan** — complete.
2. **Codex plan review** — send this plan doc to Codex for review; iterate until PASS. Given mechanical scope (doc rewrites + one workflow regex addition), expect a short review cycle (likely R1 PASS or one round of nits). Worth doing even for mechanical work because the plan is the contract for implementation.
3. **Implement via Codex** — send approved plan to Codex; Codex makes all 5 file edits as described.
4. **Local verification** (see below) before committing.
5. **Single commit** — `docs(link-check): fix 22 broken links + exclude _archive`. Push to a feature branch; PR; confirm `Docs Link Check` CI goes green; merge.

## Verification

Local, before commit:

```bash
# Install lychee if not present
brew install lychee  # or: cargo install lychee

# Run the same args as the GitHub Action
lychee --offline --no-progress --verbose \
  --exclude-path "docs/third-party/**" \
  --exclude-path "docs/planning/**" \
  --exclude-path "^docs/_archive/" \
  "./**/*.md"
```

Expected: `🚫 Errors  0` (down from 22). Successful count should stay at ~105; excluded count will rise as archive `.md` files get pulled into the excluded bucket.

Post-push:
- `gh run watch` on the PR and on the merge-to-main push; confirm `Docs Link Check` job is green both times.
- Spot-check one of the rewritten links on the PR diff in GitHub's UI (click through to confirm it resolves to the intended file — e.g. `docs/ops/EDITORIAL_ARBITER_MODEL_BENCHMARK.md` link to `core/overview_editorial/llm_arbiter.py`).

## Reference — rewrite templates (for the Codex implementation brief)

### `docs/ops/EDITORIAL_ARBITER_MODEL_BENCHMARK.md`

File lives at depth 2, so repo root is `../../`. All 4 hrefs get dropped of their `:LINE` suffix and rewritten as repo-relative.

```diff
- - Harness: [scripts/benchmark_editorial_arbiter.py](/Users/henrychien/Documents/Jupyter/risk_module/scripts/benchmark_editorial_arbiter.py:1)
+ - Harness: [scripts/benchmark_editorial_arbiter.py](../../scripts/benchmark_editorial_arbiter.py)

- - Fixtures: the 5 pinned eval scenarios in [tests/core/overview_editorial/eval_scenarios](/Users/henrychien/Documents/Jupyter/risk_module/tests/core/overview_editorial/eval_scenarios)
+ - Fixtures: the 5 pinned eval scenarios in [tests/core/overview_editorial/eval_scenarios](../../tests/core/overview_editorial/eval_scenarios)

-   - same pinned generators and policy logic used by [test_eval_scenarios.py](/Users/henrychien/Documents/Jupyter/risk_module/tests/core/overview_editorial/test_eval_scenarios.py:1)
+   - same pinned generators and policy logic used by [test_eval_scenarios.py](../../tests/core/overview_editorial/test_eval_scenarios.py)

-   - same schema and system prompt as [core/overview_editorial/llm_arbiter.py](/Users/henrychien/Documents/Jupyter/risk_module/core/overview_editorial/llm_arbiter.py:49)
+   - same schema and system prompt as [core/overview_editorial/llm_arbiter.py](../../core/overview_editorial/llm_arbiter.py)
```

### `docs/ops/EDITORIAL_PIPELINE_OBSERVABILITY.md`

Same depth (`../../`). 9 href rewrites in total (two producers appear on both a catalog row and a timing row — they get the same rewrite in both places). Literal diffs below.

```diff
- | `overview_brief_generated` | `usage.jsonl` | [actions/overview_brief.py](/Users/henrychien/Documents/Jupyter/risk_module/actions/overview_brief.py:31) | Every cache hit or cold brief generation | …
+ | `overview_brief_generated` | `usage.jsonl` | [actions/overview_brief.py](../../actions/overview_brief.py) | Every cache hit or cold brief generation | …

- | `overview_brief_enhanced` | `usage.jsonl` | [core/overview_editorial/llm_arbiter.py](/Users/henrychien/Documents/Jupyter/risk_module/core/overview_editorial/llm_arbiter.py:49) | Every arbiter attempt, including parse failure | …
+ | `overview_brief_enhanced` | `usage.jsonl` | [core/overview_editorial/llm_arbiter.py](../../core/overview_editorial/llm_arbiter.py) | Every arbiter attempt, including parse failure | …

- | `editorial_memory_updated` | `usage.jsonl` | [core/overview_editorial/editorial_state_store.py](/Users/henrychien/Documents/Jupyter/risk_module/core/overview_editorial/editorial_state_store.py:91) | Manual memory update or successful auto-seed insert | …
+ | `editorial_memory_updated` | `usage.jsonl` | [core/overview_editorial/editorial_state_store.py](../../core/overview_editorial/editorial_state_store.py) | Manual memory update or successful auto-seed insert | …

- | `editorial_memory_auto_seed_skipped` | `usage.jsonl` | [core/overview_editorial/memory_seeder.py](/Users/henrychien/Documents/Jupyter/risk_module/core/overview_editorial/memory_seeder.py:36) | Auto-seed exits without inserting | …
+ | `editorial_memory_auto_seed_skipped` | `usage.jsonl` | [core/overview_editorial/memory_seeder.py](../../core/overview_editorial/memory_seeder.py) | Auto-seed exits without inserting | …

- | `kind="editorial"`, `name="overview_brief_generation"` | `timing.jsonl` | [actions/overview_brief.py](/Users/henrychien/Documents/Jupyter/risk_module/actions/overview_brief.py:31) | Cold brief generation only | …
+ | `kind="editorial"`, `name="overview_brief_generation"` | `timing.jsonl` | [actions/overview_brief.py](../../actions/overview_brief.py) | Cold brief generation only | …

- | `kind="editorial"`, `name="overview_brief_arbiter"` | `timing.jsonl` | [core/overview_editorial/llm_arbiter.py](/Users/henrychien/Documents/Jupyter/risk_module/core/overview_editorial/llm_arbiter.py:49) | Every arbiter attempt | …
+ | `kind="editorial"`, `name="overview_brief_arbiter"` | `timing.jsonl` | [core/overview_editorial/llm_arbiter.py](../../core/overview_editorial/llm_arbiter.py) | Every arbiter attempt | …

- - data gather failures from [core/overview_editorial/orchestrator.py](/Users/henrychien/Documents/Jupyter/risk_module/core/overview_editorial/orchestrator.py:757)
+ - data gather failures from [core/overview_editorial/orchestrator.py](../../core/overview_editorial/orchestrator.py)

- - arbiter parse warnings from [core/overview_editorial/llm_arbiter.py](/Users/henrychien/Documents/Jupyter/risk_module/core/overview_editorial/llm_arbiter.py:118)
+ - arbiter parse warnings from [core/overview_editorial/llm_arbiter.py](../../core/overview_editorial/llm_arbiter.py)

- - editorial state fallback warnings from [core/overview_editorial/editorial_state_store.py](/Users/henrychien/Documents/Jupyter/risk_module/core/overview_editorial/editorial_state_store.py:27)
+ - editorial state fallback warnings from [core/overview_editorial/editorial_state_store.py](../../core/overview_editorial/editorial_state_store.py)
```

Note the mechanical pattern: each rewrite replaces `(/Users/henrychien/Documents/Jupyter/risk_module/PATH:LINE)` → `(../../PATH)`. No `(line N)` prose is added — the line numbers have drifted (see Category B fix note above), so stale ones would mislead readers.

### `docs/research/vals-finance-agent-day1-verifications.md` L145

```diff
- Verified against [agent/registry.py](/Users/henrychien/Documents/Jupyter/risk_module-vals-bench/agent/registry.py:64):
+ Verified against `agent/registry.py` (in the `risk_module-vals-bench` sibling repo):
```

### `docs/standards/AGENT_ORCHESTRATION_LESSONS.md` L5

```diff
- **See also:** [`investment_tools/docs/WORKFLOW_PATTERNS.md`](../../../investment_tools/docs/WORKFLOW_PATTERNS.md) — broader multi-Claude orchestration patterns, research data quality, and documentation habits.
+ **See also:** `investment_tools/docs/completed/WORKFLOW_PATTERNS.md` — broader multi-Claude orchestration patterns, research data quality, and documentation habits.
```

### `.github/workflows/docs-link-check.yml`

```diff
           args: >-
             --offline
             --no-progress
             --verbose
             --exclude-path "docs/third-party/**"
+            --exclude-path "^docs/_archive/"
             --exclude-path "docs/planning/**"
             "./**/*.md"
```

The new entry uses an anchored regex (`^docs/_archive/`) per lychee's documented `--exclude-path` semantics (regex, not glob). Existing `docs/third-party/**` / `docs/planning/**` entries are left alone — they're working in production today; re-styling them to regex is a separate cleanup.

## Commit message

```
docs(link-check): fix 22 broken links + exclude _archive

- exclude ^docs/_archive/ from lychee (regex per lychee docs, matches
  third-party/planning policy; archive is deprecated, not maintained —
  fixes 7 stale cross-refs)
- rewrite 14 absolute /Users/henrychien/... hrefs in docs/ops/ and
  docs/research/ to repo-relative; drop :LINE suffix entirely (lychee URL
  parser rejects it AND the line numbers have drifted in source, so
  preserving them in prose would mislead)
- repoint 1 stale cross-repo pointer in docs/standards/ from
  investment_tools/docs/WORKFLOW_PATTERNS.md to
  investment_tools/docs/completed/WORKFLOW_PATTERNS.md (plain text; no
  public URL for click-through)
- demote 1 sibling-repo link in docs/research/ to plain text
  (risk_module-vals-bench has no public URL)

Restores green CI on main. Verified locally: lychee --offline 0 errors
(was 22).
```
