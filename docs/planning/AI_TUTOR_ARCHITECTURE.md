# AI-Powered Course Tutor – High-Level Architecture  

_Last updated: 2025-07-28_

---

## 1. Objective
Deliver a 24 / 7 "GPT Teacher" that answers learners’ questions using **only** curated course material (docs, slides, transcripts, etc.) while keeping operating cost ≈ $30–40 / month.

---

## 2. Content Ingestion Pipeline
| Source | Extraction Tool | Output Location | Notes |
|--------|-----------------|-----------------|-------|
| Google Docs | Drive API `files.export` → Markdown | `s3://course-content/docs/` | Export on nightly cron |
| Kartra memberships / pages | Kartra API or headless Playwright crawl | `s3://course-content/docs/` | Clean HTML → MD |
| Word Docs (.docx) | `pandoc` / `python-docx` | `s3://course-content/docs/` | |
| PDFs / slides | `pdftotext` per-page | `s3://course-content/slides/` | Store original PDF alongside |
| Videos (Descript / YouTube) | Whisper / Descript transcript → chunk ≈ 300 words | `s3://course-content/transcripts/` | JSON with `start_seconds` field |

Each extracted file includes a **YAML header** with metadata:
```yaml
---
title: "Back-propagation Walk-through"
source_type: video_transcript
asset_url: "https://cdn.example.com/05_backprop.mp4"
start_seconds: 300          # optional
slug: backprop
abstract: |
  Step-by-step derivation of weight updates using chain rule …
tags: [neural-nets, gradients]
---
```

A nightly job (GitHub Actions or Lambda) refreshes all exports and rebuilds **`index.json`** containing `path`, `title`, `tags`, `abstract`, and pointer fields (`asset_url`, `start_seconds`, `page`).

---

## 3. Storage Layout (`s3://course-content/`)
```
index.json                        # global metadata index
/docs/03_chain-rule.md
/slides/05_backprop-slides.pdf
/transcripts/05_backprop_chunk-03.txt
/videos/05_backprop.mp4           # optional, or external CDN/Descript link
```

---

## 4. Retrieval Service (AWS Lambda)
### Functions exposed to GPT (function-calling schema)
1. **search_docs(query, top_k=5)**  
   • Loads `index.json`, fast fuzzy match on `title + tags + abstract` (miniFuse or vector search later).  
   • Returns array `{ path, score }`.

2. **read_doc(path)**  
   • Range-gets object from S3.  
   • Returns raw Markdown/text chunk.

3. **get_asset_link(path, line?)** _(optional)_  
   • Converts metadata into deep link (`video_url?t=seconds` or `pdf_url#page=N`).

All endpoints are idempotent, CORS-enabled, and cost pennies per million calls.

---

## 5. Generation Layer
| Step | Model | Purpose |
|------|-------|---------|
| Retrieval embedding _(optional upgrade)_ | `text-embedding-3-small` | Produce vector for `search_docs` when corpus grows |
| Routing / quick answers | `gpt-3.5-turbo` | Detect FAQ duplicates or simple definitions |
| Full explanation | `gpt-4o` (or `gpt-4-turbo`) | Compose detailed, cited answer using retrieved chunks |

Flow:
```
User Q → GPT (3.5) router →
   ↳ trivial?  yes → answer with cached / 3.5
                 no  → call search_docs
                          ↳ read_doc(s)
                          ↳ (get_asset_link)
                     send to GPT-4o → answer + links
```

Cache layer (Redis) stores top-1000 Q&A pairs and `index.json` in memory.

---

## 6. Cost Model (100 students, 1 000 answers / month)
| Item | Qty / month | Unit Cost | Total |
|------|-------------|-----------|-------|
| S3 storage & traffic | 5 GB | $0.25 / GB | $1.25 |
| Lambda retrieval | 10 k requests | $0.20 / 1M | <$0.01 |
| Embedding search | 1 k × 60 tok | $0.00002 / 1K tok | ~$1.20 |
| gpt-3.5 routing | 1 k × 1 K tok | $0.0005 / 1K tok | $0.50 |
| gpt-4o answers | 1 k × 2 K tok | ~$0.01 | $10 |
| Buffer / monitoring | — | — | $3 |
| **Estimated monthly total** | | | **≈ $16** |

Even with doubled usage (<$32) stays within the $40 target.

---

## 7. Roll-Out Phases
1. **Pilot (Module 1 only)**  
   • Manual export to S3.  
   • No embeddings; keyword `index.json` search.  
   • Track costs & unanswered queries.

2. **Full Course Migration**  
   • Automate Drive & Kartra exports via GitHub Actions.  
   • Add Whisper batch job for all videos.

3. **Vector Search Upgrade**  
   • Move `search_docs` to Pinecone / OpenSearch when corpora > 2 k chunks.

4. **Feature Enhancements**  
   • Quiz generation (`generate_quiz(topic)`)  
   • Progress tracking & adaptive suggestions.

---

## 8. Maintenance Checklist
- [ ] Nightly ingestion job succeeds (Slack alert on failure).  
- [ ] `index.json` diff <5 % chunk churn (flags accidental duplicates).  
- [ ] GPT answers cite at least one `asset_url` 90 % of the time.  
- [ ] Monthly cost report < $40; trigger routing tweaks otherwise.

---

## 9. Security & Privacy
- All S3 objects set to **private**, served via CloudFront signed URLs.  
- Chat logs anonymised; stored 30 days then purged.  
- No PII in retrieval calls or prompts.

---

## 10. Open Questions
- Do we need multilingual support v1?  
- Should video transcripts include speaker ID metadata?  
- Access control for premium tiers (JWT vs signed URL)?

---

**End of Document** 