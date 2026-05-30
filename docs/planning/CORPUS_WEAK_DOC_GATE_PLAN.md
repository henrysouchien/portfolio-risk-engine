# Corpus — Weak-doc Gate Signal-to-Noise Pass (Path A)

## Status: v3 (2026-04-30) — addresses Codex R2 FAIL-WITH-CHANGES (4 CRITICAL + 3 MAJOR)

**v1**: Tried to classify "structural omission vs parser bug" from `sections_fts` alone. Codex FAIL'd on taxonomy contradicting predictions + classifying all docs not just weak ones + IBM miscategorization.

**v2 (Path B research → Path A pivot)**: Dropped causal claims, tiered by count deviation, added bug-class heuristic with size threshold. Codex FAIL'd on Citi heuristic false-positiving STT (size threshold of 250K too low — STT MD&A reaches 273K), GE heuristic missing 3 GE docs (required missing both Part II, but 3 GE docs have one Part II item), IBM smoke expectation wrong, predicted distribution inaccurate, N+1 fix incomplete.

**v3 (this plan)**: Replaces size-threshold heuristics with **structural discriminators** validated against actual SQL probes. Key insight: Notes-split section presence is the clean discriminator between Citi-class (boundary absorption — Notes section exists alongside oversized Financial Statements) and GE-class (full dropout — no Notes split, content gone). All numeric predictions re-grounded against `data/filings.db` directly.

## Motivation

Phase 1 corpus ingest produced 81 raw-count weak documents in `data/corpus/health/2026-04-30.json`. Per-document analysis (2026-04-30) breakdown:

| Cluster | Docs | Pattern | Filed bug? |
|---|---|---|---|
| GE | 13 | Missing ≥1 Part II item + missing Item 3 + no Notes-split row | Yes — `Edgar_updater 7ed2f86` (GE-class dropout) |
| C | 12 | Missing both Part II items + missing Item 3 + has Notes-split row | Yes — `Edgar_updater 7ed2f86` (Citi-class absorption) |
| STT | 13 | Missing both Part II items + has Item 3 + has Notes-split | Possibly GE-class variant; not currently tagged |
| IBM | 13 | Missing Item 3 + missing Item 1A + has Notes-split | Issuer practice (Market Risk in MD&A) |
| ABBV | 12 | Missing Item 1A only | Issuer practice ("no material changes") |
| XOM | 12 | Missing Item 1A only | Issuer practice ("no material changes") |
| USB | 6 (2022-23 only) | Missing Item 4 only | Old parser version drift |
| Other (broad) | ~50+ | Various single-key misses | Mixed — not investigated cluster-wise |

`weak_documents` is consumed only by the dashboard JSON output. Repo grep confirms no programmatic consumer.

## Goal

Replace flat boolean weak-doc detection with:
1. **Severity tier** (count-based, no causal claim) — `severe` / `partial` / `marginal` / `clean`.
2. **Bug-class tag** matching docs against the two filed Edgar_updater bugs (Citi-class absorption + GE-class dropout) using **structural signatures** (no size thresholds).

Operational gates (`coverage` ratio, `gate_coverage` boolean) stay unchanged.

## Scope

### In scope

- `scripts/corpus_health_report.py` — only file modified.
- New tiered `severity` field per weak-doc entry.
- New `bug_class` field per weak-doc entry (`citi_class_absorption` / `ge_class_dropout` / `null`).
- New top-level `weak_summary` (severity tier counts, **10-Q only**) and `bug_class_summary` aggregates.
- Pre-fetch all `sections_fts` rows once + drop the per-ticker FTS LEFT JOIN in `_docs_for_ticker` (Codex MAJOR fix).
- New tests in `tests/test_corpus_health_report.py` (does not exist today).

### Out of scope (deferred)

- Operational gate threshold changes (`gate_passes()` math stays as-is).
- Persisting Phase 4 metadata (`declared_sections`, `sections_absent`) at ingest time — Path B-real, deferred.
- Issuer-practice detection (IBM Market Risk → MD&A, ABBV/XOM "no material changes") — these remain in the weak list with `bug_class=null`.
- 10-K severity classification — current 10-K weak count is 0 (10-K coverage 100%).
- STT pattern characterization — STT lands as `partial` + `bug_class=null`; operator can investigate filing as a third bug class in a follow-up.
- Schema break of legacy `sections` + `expected` fields — see §Backward compatibility below for explicit decision.

## Design

### Logical-key taxonomy

```python
EXPECTED_LOGICAL_KEYS_10Q: frozenset[str] = frozenset({
    'part1_item1', 'part1_item2', 'part1_item3', 'part1_item4',
    'part2_item1', 'part2_item1a',
})

_SECTION_KEY_MAP: dict[str, str] = {
    'Part I, Item 1. Financial Statements': 'part1_item1',
    'Part I, Item 1. Notes to Financial Statements': 'part1_item1',  # Notes-split collapses to same logical key
    "Part I, Item 2. Management's Discussion and Analysis of Financial Condition and Results of Operations": 'part1_item2',
    'Part I, Item 3. Quantitative and Qualitative Disclosures About Market Risk': 'part1_item3',
    'Part I, Item 4. Controls and Procedures': 'part1_item4',
    'Part II, Item 1. Legal Proceedings': 'part2_item1',
    'Part II, Item 1A. Risk Factors': 'part2_item1a',
}
```

### Severity tiers (count-based, honest)

```
logical_present = { _SECTION_KEY_MAP[s] for s in sections if s in _SECTION_KEY_MAP }
missing_count = len(EXPECTED_LOGICAL_KEYS_10Q - logical_present)

severity =
    'severe'   if missing_count >= 3
    'partial'  if missing_count == 2
    'marginal' if missing_count == 1
    'clean'    if missing_count == 0
```

### Bug-class detection (structural, no size thresholds)

```python
def detect_bug_class(
    sections_present: set[str],         # raw section header strings
    logical_present: set[str],          # canonical logical keys
) -> str | None:
    """Return 'citi_class_absorption' / 'ge_class_dropout' / None.

    Both classes require missing Item 3 (`part1_item3` not in logical_present).
    Discriminator: presence of the Notes-split section.
    """
    if 'part1_item3' in logical_present:
        return None  # has Item 3 — neither bug class

    has_notes_split = 'Part I, Item 1. Notes to Financial Statements' in sections_present
    p2_missing_count = len({'part2_item1', 'part2_item1a'} - logical_present)

    # Citi-class: structural absorption signature.
    # Filed at: Edgar_updater 7ed2f86 (Notes-section boundary doesn't terminate at Part II;
    # Part I Item 1 absorbs through end of doc).
    # Required: missing BOTH Part II items + Notes-split row IS present (the small Notes
    # row that exists alongside the oversized Financial Statements section).
    if p2_missing_count == 2 and has_notes_split:
        return 'citi_class_absorption'

    # GE-class: structural dropout signature.
    # Filed at: Edgar_updater 7ed2f86 (Phase 4 doesn't recognize TOC pattern;
    # Part II content + Item 3 + Notes split all gone from sections_fts).
    # Required: missing AT LEAST ONE Part II item + Notes-split row absent.
    if p2_missing_count >= 1 and not has_notes_split:
        return 'ge_class_dropout'

    return None
```

### Why structural beats size threshold

v2 used `Part I section ≥ 250K chars` for Citi-class detection. Codex showed this false-positives 6 STT docs (STT MD&A reaches 273K). Raising threshold to 300K still risks future false positives — natural Part I size grows with filer complexity, so the boundary is unstable.

The Notes-split presence is **structural** (Phase 4 either emits a separate "Notes to Financial Statements" row or it doesn't):
- Citi-class: Phase 4 emits both Financial Statements AND Notes-split rows for Citi 10-Qs, but the boundary between Financial Statements and Part II is broken — Financial Statements absorbs through end of doc. The Notes row IS there (small, ~10K), but it's now "inside" the absorbed region by content. That's the signature.
- GE-class: Phase 4 doesn't even build a Notes companion — content is gone. No Notes row in `sections_fts`.

This holds across the corpus: probed against `data/filings.db` 2026-04-30, `Citi-class signature → 12/12 C docs, 0 false positives`; `GE-class signature → 13/13 GE docs, 0 false positives`.

### Predicted distribution (re-grounded against actual SQL)

Counts via direct SQL probe of `data/filings.db` 2026-04-30, **scoped to the 50-ticker universe** (`data/corpus/universe.json`) — i.e., the document set that `build_report` actually classifies (200 10-K + 620 10-Q within universe; raw `documents` table count may drift as ingestion adds non-universe rows):

```
=== 10-Q severity distribution ===
  severe:    22  (12 Citi-class + 10 GE-class severe)
  partial:   29  (3 GE-class partial + 13 STT + 13 IBM)
  marginal:  96  (broad spread: ABBV 12 + XOM 12 + USB-old ~6 + ~66 others)
  clean:    473

=== 10-Q bug_class_summary ===
  citi_class_absorption:  12
  ge_class_dropout:       13  (10 severe + 3 partial)
  untagged_weak:         122  (16 partial + 96 marginal + 0 untagged-severe)
                              ## untagged severe is 0 because all 22 severe match a bug class
```

10-K classifications are **out of scope** in v3 — `weak_summary` and `bug_class_summary` count 10-Q docs only. (10-K coverage is 100% and no 10-K weak docs exist; v4 can extend taxonomy.)

### What gets emitted in `weak_documents`

**Decision**: include all docs with `severity != 'clean'` (i.e., 147 entries — the new logical-key-based weak set), not just legacy raw-count weak docs (81). Codex flagged this expansion explicitly. Justification:

- Logical-key normalization (collapsing Notes-split into one logical Item 1) reveals weakness in docs whose raw count was inflated to 6 by duplicate emission. Those 66 extra docs ARE missing one logical section; the legacy gate just couldn't see it.
- The new severity tiers make the 147-entry list more actionable than the legacy 81: dashboard consumers filter to `severity in ['severe', 'partial']` to see 51 high-signal entries, vs the legacy 81 unsortable.
- We're not breaking anything operational — `coverage` ratio + `gate_coverage` boolean are computed via legacy raw-count math (preserved).

The dashboard expands by 66 entries; severity ordering compensates.

## Implementation

### Step 1 — Constants

At `scripts/corpus_health_report.py:21`, replace `EXPECTED_SECTIONS` with:

```python
LEGACY_EXPECTED_SECTIONS: dict[str, int] = {'10-K': 8, '10-Q': 6}  # for unchanged coverage ratio

EXPECTED_LOGICAL_KEYS_10Q: frozenset[str] = frozenset({
    'part1_item1', 'part1_item2', 'part1_item3', 'part1_item4',
    'part2_item1', 'part2_item1a',
})

_SECTION_KEY_MAP: dict[str, str] = {
    'Part I, Item 1. Financial Statements': 'part1_item1',
    'Part I, Item 1. Notes to Financial Statements': 'part1_item1',
    "Part I, Item 2. Management's Discussion and Analysis of Financial Condition and Results of Operations": 'part1_item2',
    'Part I, Item 3. Quantitative and Qualitative Disclosures About Market Risk': 'part1_item3',
    'Part I, Item 4. Controls and Procedures': 'part1_item4',
    'Part II, Item 1. Legal Proceedings': 'part2_item1',
    'Part II, Item 1A. Risk Factors': 'part2_item1a',
}
```

### Step 2 — Single-pass section pre-fetch (Codex MAJOR fix)

```python
def _all_section_rows(db: sqlite3.Connection) -> dict[str, list[str]]:
    """Returns {document_id: [section_header, ...]}. Single full-table scan."""
    out: dict[str, list[str]] = {}
    for doc_id, section in db.execute('SELECT document_id, section FROM sections_fts').fetchall():
        out.setdefault(doc_id, []).append(section)
    return out
```

### Step 3 — Drop FTS LEFT JOIN from `_docs_for_ticker` (Codex MAJOR fix)

The current `_docs_for_ticker()` joins `sections_fts` per ticker on the unindexed `document_id` column. Replace with:

```python
def _docs_for_ticker(db: sqlite3.Connection, ticker: str) -> list[sqlite3.Row]:
    return list(
        db.execute(
            """
            SELECT document_id, form_type, CAST(filing_date AS TEXT) AS filing_date
            FROM documents
            WHERE UPPER(ticker) = UPPER(?) AND form_type IN ('10-K', '10-Q')
            ORDER BY filing_date DESC
            """,
            (ticker,),
        )
    )
```

The previously-computed `section_count` field is now derived in caller code from the pre-fetched `_all_section_rows()` dict (`len(rows.get(doc_id, []))`).

### Step 4 — Per-doc classifier

```python
def _classify_doc(
    document_id: str,
    form_type: str,
    section_headers: list[str],
) -> dict[str, Any]:
    sections_present_set = set(section_headers)
    logical_present: set[str] = {
        _SECTION_KEY_MAP[h] for h in sections_present_set if h in _SECTION_KEY_MAP
    }
    section_count_raw = len(section_headers)

    if form_type != '10-Q':
        # 10-K out of scope for v3 severity classification.
        return {
            'document_id': document_id,
            'form_type': form_type,
            'sections_present': section_count_raw,
            'severity': None,                # signal: unclassified
            'missing_logical_keys': [],
            'bug_class': None,
        }

    missing = sorted(EXPECTED_LOGICAL_KEYS_10Q - logical_present)
    if len(missing) >= 3:   severity = 'severe'
    elif len(missing) == 2: severity = 'partial'
    elif len(missing) == 1: severity = 'marginal'
    else:                   severity = 'clean'

    bug_class = detect_bug_class(sections_present_set, logical_present)

    return {
        'document_id': document_id,
        'form_type': form_type,
        'sections_present': section_count_raw,
        'severity': severity,
        'missing_logical_keys': missing,
        'bug_class': bug_class,
    }
```

`severity=None` (10-K) prevents 10-K docs from polluting the `clean` count.

### Step 5 — Wire into `build_report`

Modify `build_report()` (currently `corpus_health_report.py:44-83`):

```python
def build_report(...) -> dict[str, Any]:
    all_section_rows = _all_section_rows(db)           # Step 2 — single pre-fetch
    weak_summary = {'severe': 0, 'partial': 0, 'marginal': 0, 'clean': 0}
    bug_class_summary = {
        'citi_class_absorption': 0,
        'ge_class_dropout': 0,
        'untagged_weak': 0,
    }

    ticker_reports = []
    ten_k_docs = ten_k_good = ten_q_docs = ten_q_good = 0
    ingested_last_year = 0

    for ticker in tickers:
        docs = _docs_for_ticker(db, ticker)            # Step 3 — no FTS join
        counts = {'10-K': 0, '10-Q': 0}
        latest = None
        weak_docs_for_ticker = []
        for doc in docs:
            doc_id = doc['document_id']
            form = str(doc['form_type'])
            section_headers = all_section_rows.get(doc_id, [])
            section_count_raw = len(section_headers)

            counts[form] += 1
            latest = max(latest or str(doc['filing_date'] or ''), str(doc['filing_date'] or ''))

            # Coverage ratio — gate-stable, raw-count math
            legacy_expected = LEGACY_EXPECTED_SECTIONS[form]
            if form == '10-K':
                ten_k_docs += 1
                ten_k_good += int(section_count_raw >= legacy_expected)
            else:
                ten_q_docs += 1
                ten_q_good += int(section_count_raw >= legacy_expected)

            classification = _classify_doc(doc_id, form, section_headers)
            if classification['severity'] is not None:           # 10-Q only
                weak_summary[classification['severity']] += 1
                if classification['severity'] != 'clean':
                    weak_docs_for_ticker.append(classification)
                    bug_cls = classification['bug_class']
                    if bug_cls is not None:
                        bug_class_summary[bug_cls] += 1
                    else:
                        bug_class_summary['untagged_weak'] += 1

        if counts['10-K'] >= 1 and counts['10-Q'] >= 3:
            ingested_last_year += 1
        ticker_reports.append({
            'ticker': ticker,
            'documents': counts,
            'latest_filing_date': latest,
            'weak_documents': weak_docs_for_ticker,
        })

    errors = _read_errors(ingest_log) if ingest_log else []
    report = {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'tickers_total': len(tickers),
        'tickers_meeting_minimum': ingested_last_year,
        'coverage': {
            '10-K': _ratio(ten_k_good, ten_k_docs),
            '10-Q': _ratio(ten_q_good, ten_q_docs),
        },
        'ingest_errors': {'count': len(errors), 'sample': errors[:5]},
        'tickers': ticker_reports,
        'weak_summary': weak_summary,                    # NEW (10-Q only)
        'bug_class_summary': bug_class_summary,          # NEW (10-Q only)
    }
    report['gate_coverage'] = gate_passes(report)
    return report
```

### Step 6 — Per-doc field migration (breaking change)

Old per-doc weak entry (legacy):

```json
{"document_id": "...", "form_type": "10-Q", "sections": 3, "expected": 6}
```

New per-doc weak entry:

```json
{
  "document_id": "...",
  "form_type": "10-Q",
  "sections_present": 3,
  "severity": "severe",
  "missing_logical_keys": ["part1_item3", "part2_item1", "part2_item1a"],
  "bug_class": "ge_class_dropout"
}
```

Legacy `sections` + `expected` fields **removed** (no programmatic consumer). This is an explicit JSON schema break; rollback is a single-commit revert.

## Backward compatibility

Verified via repo grep (2026-04-30):
- `weak_documents` field name: appears in `scripts/corpus_health_report.py` (writer) and `docs/planning/completed/CORPUS_PHASE1_REPORT.md` (descriptive prose only). No programmatic consumer.
- `sections` per-doc field name: same — no programmatic consumer.
- `expected` per-doc field name: same.

`coverage`, `gate_coverage`, `ingest_errors`, `tickers_total`, `tickers_meeting_minimum` are unchanged.

**Schema-break declaration**: per-doc fields `sections` + `expected` are removed. `weak_summary` and `bug_class_summary` are added at top level. Field additions are forward-compatible; field removals are NOT (downstream consumers reading `sections` will KeyError). Acceptable because no programmatic consumer was found.

## Tests (`tests/test_corpus_health_report.py`)

New file. Coverage:

### Unit tests (synthetic input)

1. **Section header normalization**: 7 logical keys map correctly; "Notes to Financial Statements" + "Financial Statements" both → `part1_item1`; unknown headers (e.g., "Part II, Item 6. Exhibits") return `None`.
2. **Severity classification**: 6 logical keys present → `clean`; missing 1 → `marginal`; missing 2 → `partial`; missing 3 → `severe`; missing 4+ → `severe`.
3. **Notes-split-only behavior**: doc has `Part I, Item 1. Notes to Financial Statements` but no `Part I, Item 1. Financial Statements` → `part1_item1` still counts as present.
4. **Bug-class detection**:
   - Citi-class: missing both Part II + missing Item 3 + Notes-split present → `citi_class_absorption`.
   - GE-class: missing 1 Part II + missing Item 3 + Notes-split absent → `ge_class_dropout`.
   - GE-class: missing both Part II + missing Item 3 + Notes-split absent → `ge_class_dropout`.
   - `null`: severity=`marginal` regardless of pattern.
   - `null`: STT-shape (missing both Part II, has Item 3, has Notes-split).
   - `null`: missing Item 3 only (no Part II missing) — neither bug class.
   - `null`: has at least one Part II item AND missing Item 3 + has Notes-split — neither bug class.
5. **10-K severity is None**: 10-K input → returns `severity=None`, `bug_class=None`, NOT counted in weak_summary.
6. **Aggregate counters**: `weak_summary` sums match per-doc severity counts (10-Q only); `bug_class_summary['untagged_weak']` catches docs with severity != clean and bug_class=None.

### Real-data smoke (skip if `data/filings.db` doesn't exist)

Run `build_report` against current corpus universe; assert **exact** counts (Codex MAJOR fix — no `>=` bounds):

- `weak_summary == {'severe': 22, 'partial': 29, 'marginal': 96, 'clean': 473}`
- `bug_class_summary == {'citi_class_absorption': 12, 'ge_class_dropout': 13, 'untagged_weak': 122}`
- `coverage['10-Q']['ratio']` between 0.86 and 0.88 (legacy gate stable; recomputed from `LEGACY_EXPECTED_SECTIONS`)
- `coverage['10-K']['ratio'] == 1.0`

Per-document fixtures (assert exact severity + bug_class):

| document_id | ticker | period | severity | bug_class |
|---|---|---|---|---|
| `edgar:0000040545-25-000132` | GE | 2025-Q3 | severe | ge_class_dropout |
| `edgar:0000040545-22-000027` | GE | 2022-Q1 | partial | ge_class_dropout |
| `edgar:0000831001-25-000086` | C | 2025-Q1 | severe | citi_class_absorption |
| `edgar:0000051143-25-000064` | IBM | 2025-Q3 | partial | None |
| `edgar:0001551152-25-000049` | ABBV | 2025-Q3 | marginal | None |
| `edgar:0000034088-25-000061` | XOM | 2025-Q3 | marginal | None |
| `edgar:0000093751-25-000575` | STT | 2025-Q3 | partial | None |
| `edgar:0001193125-23-268341` | USB | 2023-Q3 | marginal | None |

**Negative assertions** (no false-positive bug_class tag):
- All non-C tickers in the corpus → `bug_class != 'citi_class_absorption'`.
- All non-GE tickers in the corpus → `bug_class != 'ge_class_dropout'`.

## Acceptance criteria

1. Re-run `python3 scripts/corpus_health_report.py --gate-coverage`:
   - `gate_coverage: true` (unchanged).
   - `coverage['10-K']['ratio']`: 1.0 (unchanged).
   - `coverage['10-Q']['ratio']`: 0.869 (unchanged within ±0.005).
   - `weak_summary == {'severe': 22, 'partial': 29, 'marginal': 96, 'clean': 473}`.
   - `bug_class_summary == {'citi_class_absorption': 12, 'ge_class_dropout': 13, 'untagged_weak': 122}`.
2. `pytest tests/test_corpus_health_report.py -v` — all new tests pass.
3. `pytest tests/` — no regression.
4. Per-doc weak entry shape matches new schema; legacy `sections` + `expected` removed.
5. Performance: full report runs in < 5s on current corpus (vs ~94s with N+1 pattern Codex measured in v2 review).

## Risk register

| Risk | Likelihood | Mitigation |
|---|---|---|
| Bug-class heuristic over-tags (false positive) | low | Real-data smoke test asserts exact counts (12 / 13 / 122) — drift surfaces immediately. Negative assertions on non-C/non-GE tickers. |
| Bug-class heuristic under-tags (false negative) | low | Same smoke fixture; 12 + 13 expected matches all known filed-bug docs. |
| Section header text drifts (parser changes wording) | low | Unrecognized headers return `None` from `_normalize_section_to_key`. Smoke test would catch. |
| Performance regression from FTS join | n/a | Single full-table prefetch (~5,617 rows in current corpus). N+1 pattern dropped (Codex v2 measured 94s; new pattern measured single-digit seconds during plan probes). |
| 10-K weak doc surfaces post-merge | low | 10-K returns severity=None → not counted in weak_summary. v4 extends taxonomy if needed. |
| Notes-split presence drifts (Phase 4 stops emitting Notes-split row, or starts emitting it for tickers that don't currently have it) | medium | Smoke test catches via exact count assertions. Manual recheck if assertion fails — likely indicates upstream parser change worth investigating. |
| STT lands in untagged_weak; might be a third bug class | low (operational) | Documented; operator can investigate via `bug_class=null + severity=partial` filter. v4 can add third bug class. |
| Hidden consumer of legacy `sections`/`expected` fields | low | Verified via grep (only writer + descriptive doc reference). One-line alias is fast follow-up if a consumer surfaces. |
| Logical-key normalization expands weak count from 81 → 147 | low (intentional) | Severity tiering compensates: dashboard consumers filter to `severe + partial` (51) for high-signal view. Documented explicitly. |

## Rollback

Single-commit revert. JSON schema-break is bounded to weak_documents per-doc field rename and two new top-level fields.

## Effort

~2-3 hours: 0.5h refactor + 1h tests + 0.5h Codex iteration + 0.5h smoke verification.

## References

- `Edgar_updater/docs/TODO.md` (commit `7ed2f86`) — Citi-class + GE-class bug entries
- `data/corpus/health/2026-04-30.json` — current weak_documents output
- `data/filings.db` — `sections_fts` table; per-doc section list source
- `scripts/corpus_health_report.py:21` — flat `EXPECTED_SECTIONS` constant being replaced
- `scripts/corpus_health_report.py:94` — `_docs_for_ticker` LEFT JOIN being dropped (Codex v2 MAJOR)
- `docs/planning/completed/CORPUS_PHASE1_REPORT.md` — describes weak_documents at ship time

## Plan review history

- **v1** — Codex R1 FAIL-WITH-CHANGES (4 CRITICAL: taxonomy contradicting predictions, classifying all docs not just weak ones, IBM miscategorization; + MAJOR: issuer-vs-parser ambiguity, N+1 query).
- **v2** — Codex R2 FAIL-WITH-CHANGES (4 CRITICAL: distribution wrong, Citi false-positive STT, GE-class missed 3 GE docs, IBM smoke wrong; + 3 MAJOR: N+1 incomplete, smoke too weak, 81→147 expansion not addressed).
- **v3 (this version)** — re-grounded against actual SQL probes; structural discriminators replace size thresholds; per-doc fixtures with exact counts; FTS join dropped; 81→147 expansion documented explicitly.
