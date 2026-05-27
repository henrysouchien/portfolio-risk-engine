# F123 — Corpus health-report bug-class detector update

**Status:** APPROVED — Codex v2 PASS (2026-05-20). Two non-blocking notes folded.

**Author:** Henry / Claude

**Date opened:** 2026-05-20

**TODO entry:** `docs/TODO.md` F123

**Source plan:** `docs/TODO_COMPLETED.md` 2026-05-20 F50 closeout (filed F123 there)

---

## 1. Problem

`scripts/corpus_health_report.py::detect_bug_class()` (lines 373-386)
flags 28 docs as `citi_class_absorption` (12 Citi) or `ge_class_dropout`
(3 GE + 13 ABT) based on Part II Items 1/1A absence. After upstream's
2026-05-08 sectioner fix (Edgar_updater CHANGES.md line 862,
`parser_version=9741c772`) + the F50 reingest on 2026-05-20 (`logs/corpus/f50_live_2026-05-20.jsonl`,
28/28 complete), these docs now carry the new Part II Items 2/5/6 when
disclosed. Absence of Items 1/1A is **legitimate non-disclosure**
(Citi/ABT/GE choose not to restate Legal Proceedings + Risk Factors
each 10-Q when no material change), not a parse failure.

The detector heuristic was tuned to the OLD sectioner behavior where
Items 4-6 absorbed into Items 1/3, masking the absence of Items 1/1A.
Post-fix, the same heuristic produces 28 false positives, polluting
`bug_class_summary` in `data/corpus/health/YYYY-MM-DD.json` and adding
noise to the soak gate signal (F108 / `corpus_phase1_soak_check.py`).

**Verified by reading individual reingested docs**:

- `edgar:0000040545-24-000113` (GE 10-Q 2024 Q1): emits Part II Item
  1A + Item 6. Missing Item 1 (Legal Proceedings) + Item 3 (Market
  Risk). Detector returns `ge_class_dropout`.
- `edgar:0000831001-25-000154` (Citi 10-Q 2025): emits Notes-split +
  Part II Items 2 + 5 + 6. Missing Items 1 + 1A + Part I Item 3.
  Detector returns `citi_class_absorption`.

Both docs are on the post-fix parser. The new sections present prove
the sectioner is working; the heuristic just isn't checking for them.

## 2. Goal

Add a "post-fix sectioner is working" precondition to
`detect_bug_class()`: if the new sectioner has emitted **any** of Part
II Items 2-6 for a doc, treat absence of Items 1/1A as real disclosure,
not a parse miss.

Keep the old heuristic for the genuine pre-fix case (no Items 2-6 AND
missing 1/1A) so that any straggler not-yet-reingested docs OR future
producer regressions still surface.

## 3. Design

### 3.1 `_SECTION_KEY_MAP` extension

Current map at `corpus_health_report.py:35-43` covers 7 section
headers across Part I Items 1-4 + Part II Items 1/1A. Extend with the
5 Part II Items the upstream fix surfaces:

```python
_SECTION_KEY_MAP: dict[str, str] = {
    # ... existing entries ...
    'Part II, Item 2. Unregistered Sales of Equity Securities and Use of Proceeds': 'part2_item2',
    'Part II, Item 3. Defaults Upon Senior Securities': 'part2_item3',
    'Part II, Item 4. Mine Safety Disclosures': 'part2_item4',
    'Part II, Item 5. Other Information': 'part2_item5',
    'Part II, Item 6. Exhibits': 'part2_item6',
}
```

Adding entries here populates `logical_present` for the detector
without affecting `missing = EXPECTED_LOGICAL_KEYS_10Q - logical_present`
(the EXPECTED frozenset is **not** widened — see §3.4).

### 3.2 `detect_bug_class()` precondition

Add an early-return guard:

```python
_POST_FIX_PART2_KEYS = frozenset({'part2_item2', 'part2_item3', 'part2_item4', 'part2_item5', 'part2_item6'})

def detect_bug_class(sections_present: set[str], logical_present: set[str]) -> str | None:
    if 'part1_item3' in logical_present:
        return None

    # Post-fix sectioner check: if any of the new Part II Items 2-6 is
    # present, the upstream sectioner is producing post-2026-05-08 output
    # and absence of Items 1/1A is real disclosure, not a parse miss.
    if logical_present & _POST_FIX_PART2_KEYS:
        return None

    has_notes_split = 'Part I, Item 1. Notes to Financial Statements' in sections_present
    p2_missing_count = len({'part2_item1', 'part2_item1a'} - logical_present)
    # ... rest unchanged ...
```

Reasoning for "any of 2-6" rather than a single canonical marker:
`Part II, Item 6. Exhibits` is essentially universal (every 10-Q
includes exhibits in some form), but defensiveness is cheap — `any
present` handles edge cases where Items 2-5 appear without Item 6
(unlikely but possible in unusual filings) and future producer
behavior changes.

### 3.3 What stays the same

- `EXPECTED_LOGICAL_KEYS_10Q` does **NOT** change. Adding part2_item2-6
  to the map only enriches `logical_present`; the existing `missing =
  EXPECTED - logical_present` computation in `_classify_doc()` is
  unaffected (Part II Items 2-6 are optional, not expected).
- `citi_class_absorption` and `ge_class_dropout` stay as named bug
  classes. They retain meaning for legitimate parse misses (e.g., if a
  future producer regression breaks the new sectioner, the heuristic
  will trigger again).
- `untagged_weak` bucket continues to catch any other severity-tagged
  weak docs.

### 3.4 Decision rejected: widening `EXPECTED_LOGICAL_KEYS_10Q`

Tempting alternative: add part2_item2-6 to `EXPECTED_LOGICAL_KEYS_10Q`
so they show up in `missing_logical_keys` per doc. **Rejected**:

- Per Form 10-Q: Items 2-5 are **conditional** — inapplicable or
  negative items "may be omitted" so most issuers skip them most
  quarters. Item 6 (Exhibits) is technically required but its
  surfacing in the new sectioner is not yet reliable enough across
  header variants to use as a health expectation.
- The "missing" / "severity" computation feeds `weak_summary` /
  `weak_documents` / `bug_class_summary` (in `_classify_doc()` →
  `weak_docs_for_ticker` → report assembly at
  `scripts/corpus_health_report.py:120`). Widening EXPECTED would
  reclassify ~all corpus 10-Qs as "partial"/"severe" because most
  legitimately omit Items 2-5.
- `gate_coverage` itself does NOT read `weak_summary` (it uses
  per-form `coverage[].ratio` + transcript thresholds, see
  `scripts/corpus_health_report.py:258`), but the `weak_summary`
  signal IS surfaced in the health-snapshot payload, so widening
  would still noisily impact operator dashboards.
- We only need Items 2-6 visible to `detect_bug_class()`, not to the
  weak-doc severity gate. Map extension achieves that with zero
  knock-on effect.

## 4. Files changed

1. **`scripts/corpus_health_report.py`** (~7 LOC):
   - `_SECTION_KEY_MAP` += 5 new entries (§3.1).
   - `_POST_FIX_PART2_KEYS` frozenset constant.
   - `detect_bug_class()` early-return guard (§3.2).

2. **`tests/test_corpus_health_report.py`** — both new detector tests
   AND existing real-data fixture updates (Codex v1 catch). The
   existing test file uses the same local prod corpus as
   `corpus_health_report.py`, so the F50 reingest + F123 detector
   change flip several assertions in concert:

   **New detector tests** (parametrize where natural):
   - `test_detect_bug_class_skips_when_post_fix_part2_items_present` —
     missing `part2_item1` and `part2_item1a`, but `part2_item6`
     present → returns `None`.
   - **Citi-like suppression** (Codex v1 case A):
     notes-split present + BOTH `part2_item1` / `part2_item1a`
     missing + Part II 2-6 present → returns `None` (would otherwise
     trigger `citi_class_absorption`).
   - **GE-like suppression** (Codex v1 case B — note: GE/ABT shape
     is often missing ONE of `part2_item1`/`1a`, not both):
     no notes-split + ONLY ONE of `part2_item1`/`1a` missing + Part II
     2-6 present → returns `None` (would otherwise trigger
     `ge_class_dropout`).
   - **Negative regression** — citi pattern with NO Items 2-6 present
     → still returns `'citi_class_absorption'` (legit pre-fix case
     stays flagged).
   - **Negative regression** — ge pattern with NO Items 2-6 present
     → still returns `'ge_class_dropout'`.

   **Existing fixtures to update** (`tests/test_corpus_health_report.py`):
   - Line 39 — `test_section_header_normalization`:
     `assert report._normalize_section_to_key('Part II, Item 6. Exhibits') is None`
     → assert it now maps to `'part2_item6'`. Add assertions for the
     other 4 new map entries (Items 2, 3, 4, 5) for parity.
   - Lines 166-168 — real-data smoke `bug_class_summary` thresholds:
     `>= 10` for Citi + GE → expect `== 0` post-F123. `untagged_weak >=
     200` may also shift slightly (the 28 reclassified docs flow into
     other severity buckets but remain weak-with-no-bug-class) —
     widen the threshold if needed during implementation.
   - Lines 177-180 — `expected_docs` mapping for GE/Citi docs:
     `('GE', 'partial', 'ge_class_dropout')` → `('GE', 'partial', None)`,
     and same for the Citi doc. Severity stays the same; only
     `bug_class` flips to `None`. Apply to all GE + Citi rows; IBM /
     ABBV / XOM / STT / USB rows already have `bug_class=None` and
     stay unchanged.

3. **`tests/scripts/test_corpus_health_report.py`** — no changes
   needed (Codex v1 confirmed). That file covers Phase 2 manifest /
   gate behavior, not the bug-class detector.

## 5. Verification

After implementation:

1. `pytest tests/test_corpus_health_report.py tests/scripts/test_corpus_health_report.py -x` — all new + existing pass.
2. **Bulk verification** — re-run `python3 scripts/corpus_health_report.py
   --universe data/corpus/universe.json --db data/filings.db --out
   /tmp/f123_health_post_2026-05-20.json` then check:
   ```python
   import json
   d = json.load(open('/tmp/f123_health_post_2026-05-20.json'))
   print(d['bug_class_summary'])
   # Expect: citi_class_absorption=0, ge_class_dropout=0
   # (untagged_weak may shift as the 28 reclassified docs flow in)
   ```
3. **Targeted verification** (Codex v1 recommendation — cheap, catches
   stale header/map drift better than one manual spot-check): walk
   the 28 doc IDs in `logs/corpus/f50_affected_2026-05-20.txt`,
   programmatically reclassify each via `report._classify_doc()`,
   assert (a) `bug_class is None` for all 28, (b) at least one of
   `_POST_FIX_PART2_KEYS` is in the doc's `logical_present`:

   ```python
   from scripts import corpus_health_report as report
   import sqlite3
   con = sqlite3.connect('data/filings.db')
   con.row_factory = sqlite3.Row
   all_sections = report._all_section_rows(con)
   ids = [l.strip() for l in open('logs/corpus/f50_affected_2026-05-20.txt') if l.strip()]
   for doc_id in ids:
       headers = all_sections.get(doc_id, [])
       cls = report._classify_doc(doc_id, '10-Q', headers)
       assert cls['bug_class'] is None, (doc_id, cls)
       # Optionally also check post-fix marker presence
       # Filter None so the set diff message is clean (Codex v2 note)
       logical = {k for k in (report._normalize_section_to_key(h) for h in headers) if k}
       assert logical & report._POST_FIX_PART2_KEYS, (doc_id, sorted(h for h in headers))
   print(f'All {len(ids)} docs verified bug_class=None with post-fix Part II markers')
   ```

## 6. Backward compatibility

- **Persisted data:** historical `data/corpus/health/*.json` snapshots
  are not rewritten; existing files continue to show the pre-fix
  counts as a record of the pre-fix detector behavior.
- **Soak gate thresholds:** `corpus_phase1_soak_check.py` thresholds
  use `max_average_errors`, `max_drift_per_run`, etc. — none of them
  read `bug_class_summary` directly. Soak gate behavior is unchanged
  (and actually slightly cleaner now that false positives don't
  inflate signal).
- **Upstream INVALIDATIONS.yaml:** `Edgar_updater/INVALIDATIONS.yaml`
  Citi-class + GE-class entries remain in the upstream invalidation
  feed as the historical record of what was fixed. Consumer-side
  reaction to those entries (queueing reingest for matching docs) is
  unaffected.

## 7. Risks

1. **Hiding a real regression.** If the new sectioner regresses such
   that Items 2-6 are emitted but Items 1/1A get parse-absorbed again,
   the new guard would hide that. Mitigation: low probability (Items
   1/1A have been parsed correctly through multiple sectioner versions
   pre-2026-05-08; the regression would have to be a new bug
   specifically affecting Items 1/1A only); detectable separately by
   diffing `weak_summary` distributions across health snapshots.
2. **Map header strings drifting from producer output.** If
   Edgar_updater changes the exact section header text (e.g., `Part
   II, Item 6.` → `Part II, Item 6 (Exhibits)`), my entries in
   `_SECTION_KEY_MAP` would no longer match. Producer-side stability
   on these headers has been good historically. If drift happens, the
   detector silently regresses to flagging again. Mitigation: §5
   verification re-runs would catch a sudden count spike; could add a
   future test fixture pinning the exact strings against a real corpus
   doc.

## 8. Out of scope (explicit)

- Renaming the bug classes (`citi_class_absorption` /
  `ge_class_dropout`) — they're tied to INVALIDATIONS.yaml semantics
  upstream, renaming would create cross-repo coordination overhead for
  marginal clarity benefit.
- Expanding `EXPECTED_LOGICAL_KEYS_10Q` (see §3.4).
- Surfacing per-doc `bug_class` in MCP read APIs (separate concern
  if ever needed).

## 9. Rollout

1. Implement per §4.
2. Run `pytest tests/test_corpus_health_report.py tests/scripts/test_corpus_health_report.py -x`.
3. Re-run `corpus_health_report.py` locally; verify
   `bug_class_summary.citi_class_absorption` and
   `.ge_class_dropout` drop to 0.
4. Commit on `main` (per `feedback_commit_to_main_default`).
5. Remove F123 from `docs/TODO.md`; add to `TODO_COMPLETED.md`.

## 10. Open questions — resolved in Codex v1 review

1. **Discriminator scope?** Use **any of Part II 2-6** in
   `logical_present` (Codex v1 confirmed via local DB sampling: 1,596
   total Edgar 10-Qs; 1,573 have at least one recognized Item 2-6;
   the 23 with zero Items 2-6 do NOT match the old bug-class trigger
   conditions, so the guard is safe).
2. **Constant location?** Keep `_POST_FIX_PART2_KEYS` at module
   scope (discoverable, single-source).
3. **`part1_item3 → None` regression test?** Not strictly required
   (existing parametrized cases cover it). Add a named case if it's
   cheap — judgment call during impl.
4. **Signature shape?** Keep `sections_present` in the signature.
   The notes-split check needs the raw header because the producer
   collapses `'Part I, Item 1. Notes to Financial Statements'` to
   `part1_item1` (collides with regular Financial Statements). The
   `has_notes_split` distinction is by-design at the raw-header
   level.
