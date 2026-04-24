# Corpus Markdown Convention

This document is the Phase 0 file-format spec for the document corpus.

Why:
- `docs/planning/CORPUS_ARCHITECTURE.md` defines the architecture-level rationale.
- `docs/planning/CORPUS_IMPL_PLAN.md` Block A defines the implementation tasks.
- This file is the validator-friendly convention that A2-A4 implement.

## Scope

Phase 0 sources:
- `edgar`
- `fmp_transcripts`

Reserved for future sources:
- `quartr`

Phase 0 form coverage:
- Filings: `10-K`, `10-Q`, `8-K`
- Transcripts: `TRANSCRIPT`
- Deferred to Phase 1: `DEF 14A`

## Directory Layout

Canonical layout from architecture doc §4.1:

```text
data/filings/{source}/{ticker}/{form_type}_{fiscal_period}_{content_hash}.md
```

Examples:

```text
data/filings/edgar/MSFT/10-K_2025-FY_a3f9b211.md
data/filings/edgar/MSFT/10-Q_2025-Q3_4d7c1a2e.md
data/filings/edgar/MSFT/8-K_2025-02-14_8c2d9f10.md
data/filings/fmp_transcripts/MSFT/TRANSCRIPT_2025-Q1_1f2e3d4c.md
data/filings/quartr/MSFT/DECK_2025-Q1_deadbeef.md
```

Rules:
- `source` is a top-level provenance directory.
- `ticker` is already canonicalized by the caller.
- The filename is content-addressable and immutable.
- Any content change, including frontmatter-only changes, produces a new hash and new filename.

## YAML Frontmatter

Every corpus markdown file begins with YAML frontmatter:

```yaml
---
document_id: edgar:0000789019-25-000073
ticker: MSFT
source: edgar
form_type: 10-K
content_hash: a3f9b211
...
---
```

The frontmatter block is authoritative structured metadata for the file.

### Required Fields

| Field | Type | Notes |
| --- | --- | --- |
| `document_id` | `str` | `{source}:{canonical_source_id}` |
| `ticker` | `str` | Canonical ticker from SymbolResolver |
| `source` | `str` | `edgar` \| `fmp_transcripts` \| `quartr` |
| `form_type` | `str` | `10-K` \| `10-Q` \| `8-K` \| `TRANSCRIPT` \| future `DECK` |
| `content_hash` | `str` | 8 lowercase hex chars in finalized files; placeholder during canonical hashing |

### Optional Fields

Optional fields may be omitted or set to `null`.

| Field | Type | Notes |
| --- | --- | --- |
| `cik` | `str` | Zero-padded 10-digit SEC CIK |
| `company_name` | `str` | Issuer name |
| `fiscal_period` | `str` | `YYYY-FY` \| `YYYY-QN` \| `YYYY-MM-DD` |
| `filing_date` | `str` | ISO-8601 date |
| `period_end` | `str` | ISO-8601 date |
| `source_url` | `str` | Stable landing URL |
| `source_url_deep` | `str \| null` | Direct HTML/PDF URL when available |
| `source_accession` | `str \| null` | SEC accession when applicable |
| `extraction_pipeline` | `str` | Example: `edgar_updater@0.5.0` |
| `extraction_model` | `str` | Example: `claude-haiku-4-5-20251001` |
| `extraction_at` | `str` | ISO-8601 timestamp |
| `extraction_status` | `str` | Default `complete`; reserved: `partial`, `failed`, `orphaned` |
| `sector` | `str` | GICS sector when available |
| `industry` | `str` | GICS industry when available |
| `sector_source` | `str` | Default taxonomy is `GICS` |
| `exchange` | `str` | Listing exchange |
| `supersedes` | `str \| null` | `document_id` of amended document |
| `supersedes_source` | `str \| null` | `sec_header` \| `heuristic` \| `llm_extraction` \| `manual` |
| `supersedes_confidence` | `str \| null` | `high` \| `medium` \| `low` |

Rules:
- No free-form extension fields without a schema update.
- `document_id` is source identity, not content identity.
- `content_hash` matches the filename suffix.
- `supersedes` metadata is ingestion-authored and immutable once written.

## `document_id` Formats

Phase 0 source identity formats:

- EDGAR filings: `edgar:<accession>`
- FMP transcripts: `fmp_transcripts:<ticker>_<YYYY-QN>`
- Future Quartr decks: `quartr:<deck-id>`

Examples:

```text
edgar:0000789019-25-000073
fmp_transcripts:MSFT_2025-Q1
quartr:deck_123456
```

## Canonical `content_hash`

`content_hash` is derived from the full canonical markdown file: frontmatter plus body.

Canonical-form convention:
- Define `CANONICAL_HASH_PLACEHOLDER = "0000000000000000"` (16 zeros).
- Assemble the full file with that literal in the `content_hash` field.
- Compute SHA-1 of the full assembled text.
- Store the first 8 lowercase hex chars as `content_hash`.
- Replace only the frontmatter `content_hash` value with the 8-char result.

This makes the file round-trip verifiable:
1. Read the finalized file.
2. Replace the stored `content_hash` value in frontmatter with `0000000000000000`.
3. SHA-1 the full file text.
4. Compare the first 8 hex chars to the stored value.

Implication:
- Any body edit changes the hash.
- Any frontmatter edit changes the hash.
- Metadata-only promotions, such as changing `supersedes_confidence`, produce a new filename.

## Canonical Section Taxonomy

### Filings

Filings use level-2 section headings:

```markdown
## SECTION: {canonical header}
```

### 10-K

Canonical sections inherited from Edgar_updater `_CANONICAL_HEADERS`:

```text
Item 1. Business
Item 1A. Risk Factors
Item 1B. Unresolved Staff Comments
Item 2. Properties
Item 3. Legal Proceedings
Item 5. Market for Registrant's Common Equity
Item 7. Management's Discussion and Analysis
Item 7A. Quantitative and Qualitative Disclosures About Market Risk
Item 8. Financial Statements and Supplementary Data
Item 9A. Controls and Procedures
```

### 10-Q

Canonical sections:

```text
Item 1. Financial Statements
Item 2. Management's Discussion and Analysis
Item 3. Quantitative and Qualitative Disclosures About Market Risk
Item 4. Controls and Procedures
Part II, Item 1A. Risk Factors
```

### 8-K

8-K files are item-specific. Canonical section headers remain the SEC item labels present in the filing, for example:

```text
Item 1.01. Entry into a Material Definitive Agreement
Item 2.02. Results of Operations and Financial Condition
Item 5.02. Departure of Directors or Certain Officers
```

Rules:
- Missing sections are omitted, not stubbed.
- Tables remain markdown tables.
- DEF 14A / proxy-statement taxonomy is deferred to Phase 1.

### Transcripts

Transcripts use a fixed top-level structure:

```markdown
## PREPARED REMARKS

### SPEAKER: Satya Nadella (CEO)
...

## Q&A SESSION

### SPEAKER: Amy Hood (CFO)
...
```

Rules:
- Top-level sections are always `## PREPARED REMARKS` and `## Q&A SESSION`.
- Each speaker turn is a `### SPEAKER: {name}` heading.
- Append ` ({role})` only when a role is known.
- `Q:` / `A:` inline prefixes may appear in body text, but the heading structure is canonical.

## References

For rationale and broader system context, see:
- `docs/planning/CORPUS_ARCHITECTURE.md`
- `docs/planning/CORPUS_IMPL_PLAN.md`
