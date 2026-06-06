# Build Process — Step by Step

This document describes the order in which the Northwind Expense Review system was built, and the reasoning behind each step.

---

## Step 1 — Project Scaffold and Configuration

**Files created:** `backend/__init__.py`, `backend/config.py`, `.env`, `requirements.txt`

The first step was locking down the environment. `config.py` loads all settings from `.env` using `python-dotenv` and resolves every path as an absolute `Path` object relative to the project root. This means the server can be started from any working directory without path-resolution bugs.

Key decision: all configurable values (model slugs, retrieval thresholds, paths) go in `.env`, not hardcoded. This makes the system easy to retune without touching source code.

---

## Step 2 — Database Schema

**Files created:** `backend/database.py`, `backend/models.py`

SQLAlchemy ORM models were defined before any service logic. Getting the schema right early prevents painful migrations later. The five tables:

```
employees
    └── submissions
            └── line_items
                    └── overrides
policy_chunks  (separate — no FK to submissions)
```

`policy_chunks` stores metadata about every indexed policy chunk (doc_id, section, source file, chroma_id). This allows BM25 retrieval to be rebuilt from SQLite on startup without reading ChromaDB.

---

## Step 3 — Policy Indexer

**Files created:** `backend/services/policy_indexer.py`

The policy indexer was built before the retrieval service because retrieval depends on having data in ChromaDB and SQLite.

**Chunking pipeline:**

1. Read each PDF with `pdfplumber` (not PyMuPDF — dependency conflict in this environment)
2. Split full PDF text on `Document: XXX-NNN` regex headers into per-policy sub-documents
3. Chunk each sub-document at ~450 tokens with one-paragraph overlap
4. Propagate the current section header as metadata for each chunk
5. Embed with `BAAI/bge-small-en-v1.5` (384-dim, runs locally, no API cost)
6. Upsert to ChromaDB with `doc_id`, `source_file`, `section_header` metadata
7. Store chunk text + metadata in SQLite `policy_chunks` table (for BM25)

**Why sub-document splitting before chunking:** Without it, a naive chunker creates chunks that mix TEP-003 alcohol rules with REC-001 records retention rules in the same vector. Sub-document isolation ensures every chunk is semantically coherent within a single policy.

**Idempotency:** The indexer checks if `PolicyChunk` rows already exist in SQLite and skips re-indexing. This means startup is fast after the first run (~0.3s vs ~30–60s).

Result: **90 chunks across 31 distinct policy documents** from 8 PDFs.

---

## Step 4 — Hybrid Retrieval Service

**Files created:** `backend/services/retrieval.py`

With data indexed, the retrieval service was built next. It provides a single `retrieve(query, top_k)` function that combines two signals:

**Dense retrieval:** Encode the query with the same embedding model → query ChromaDB for nearest neighbours by cosine similarity.

**Sparse retrieval (BM25):** On first call, load all `PolicyChunk` rows from SQLite, build a `BM25Okapi` index in memory. Score the same query by term frequency.

**Fusion:** Apply Reciprocal Rank Fusion (RRF, k=60) to merge both ranked lists. Normalize scores to [0, 1] by dividing by the theoretical maximum (`2/k = 0.0333`). Return the top-k chunks sorted by fused score.

The BM25 index is lazy-initialized on first retrieval call (not at startup) to keep startup time predictable.

---

## Step 5 — Receipt Extractor

**Files created:** `backend/services/llm_client.py`, `backend/services/receipt_extractor.py`

`llm_client.py` was built as a thin `httpx`-based wrapper around the OpenRouter API. Four functions:
- `chat()` — plain text call
- `chat_json()` — text call, parses JSON from response (strips markdown fences)
- `chat_vision()` — encodes image as base64, sends as multipart vision message
- `chat_vision_json()` — vision + JSON parse

`receipt_extractor.py` detects the file type and dispatches accordingly:

```
.pdf  → pdfplumber extracts text
         if text < 30 chars → treat as scanned → vision LLM
         else → text LLM with extraction prompt
.jpg/.png/.webp → base64 encode → vision LLM
.txt → read directly → text LLM
```

The extraction prompt requests a fixed JSON schema: `vendor`, `date`, `amount`, `currency`, `category`, `description`, `party_size`, `alcohol_present`, `line_items[]`, `notes`.

---

## Step 6 — Policy Reviewer

**Files created:** `backend/services/reviewer.py`

The reviewer wraps retrieval + LLM into two public functions:

**`review_line_item()`:**
1. Build a category-enriched retrieval query from the expense data
2. Retrieve top-6 policy chunks
3. Format chunks as numbered excerpts in the prompt
4. Call the reasoning LLM with a structured system prompt (see [Prompt Engineering](prompt-engineering.md))
5. Parse and validate the JSON verdict
6. Apply soft confidence downgrade if retrieval score is below the threshold

**`answer_policy_question()`:**
1. Retrieve top-6 chunks for the question
2. **Hard refuse** if `max_score < RETRIEVAL_MIN_CONFIDENCE` — no LLM call, no hallucination risk
3. Otherwise prompt the LLM with policy excerpts and return a grounded answer

---

## Step 7 — FastAPI Routers and Startup

**Files created:** `backend/routers/employees.py`, `backend/routers/submissions.py`, `backend/routers/line_items.py`, `backend/routers/policy_qa.py`, `backend/startup.py`, `backend/main.py`

The routers were wired up after all services were functional so they could be tested end-to-end immediately.

`startup.py` runs on app lifespan start:
1. `init_db()` — creates all SQLAlchemy tables if they don't exist
2. `seed_employees()` — reads `data/submissions/*/employee_info.json` and upserts employees
3. `index_policies()` — skips if chunks already in SQLite, otherwise runs the full indexer

`main.py` mounts the `frontend/` directory as static files and adds a catch-all route that serves `index.html` for any unmatched path (SPA routing).

---

## Step 8 — Frontend

**Files created:** `frontend/index.html`

The entire frontend is a single HTML file (~700 lines) using Tailwind CSS from CDN and vanilla JavaScript. No Node.js, no build step, no bundler. FastAPI serves it as a static file.

Features implemented:
- Hash-based routing (`#submissions`, `#employees`, `#qa`)
- Submissions list with employee and status filters
- Submission detail with drag-and-drop upload zone
- Color-coded line items table (green / yellow / red)
- Line item detail modal with verdict, reasoning, verbatim citation blockquotes, confidence bar
- Override modal with reviewer name, comment, and verdict dropdown
- Policy Q&A chat with suggested questions and refusal display
- Employee management with add-employee form
- Policy index status indicator (top-right corner)

---

## Step 9 — Testing

**Files created:** `test_smoke.py`, `eval/harness.py`

`test_smoke.py` is an 8-check end-to-end script that verifies the entire pipeline from a fresh server start:
- Employees seeded
- Policy index built (90 chunks)
- Submission creation
- Receipt upload + AI review
- Alcohol correctly rejected (Franklin BBQ, verdict=rejected, confidence=1.0)
- TEP-003 cited in the rejection
- Q&A answers a policy question
- Q&A refuses an out-of-scope question

`eval/harness.py` is a more structured evaluation tool that accepts a JSON test-case file and reports accuracy metrics across verdict, category, citation, and refusal dimensions.
