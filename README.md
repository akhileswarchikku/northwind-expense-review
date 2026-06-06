# Northwind Expense Review — AI Engineer Case Study

An **AI-assisted expense pre-review system** for Northwind Logistics.  
Finance reviewers upload receipts, receive per-line-item policy verdicts with cited clauses, override decisions with a full audit trail, and ask ad-hoc questions about the policy library — all from a browser.

---

## Table of Contents

1. [What It Does](#what-it-does)
2. [Live Demo / Screenshots](#live-demo--screenshots)
3. [Quick Start](#quick-start)
4. [Project Structure](#project-structure)
5. [Architecture](#architecture)
6. [How the Review Pipeline Works](#how-the-review-pipeline-works)
7. [Policy Library](#policy-library)
8. [Sample Submissions](#sample-submissions)
9. [API Reference](#api-reference)
10. [Evaluation Harness](#evaluation-harness)
11. [Design Decisions & Tradeoffs](#design-decisions--tradeoffs)
12. [Cost Estimate](#cost-estimate)
13. [Deployment](#deployment)
14. [What I'd Do Next](#what-id-do-next)

### Deep-dive docs

| Document | What it covers |
|---|---|
| [docs/build-process.md](docs/build-process.md) | Step-by-step build order — what was built first, why, and how each piece connects |
| [docs/challenges-and-fixes.md](docs/challenges-and-fixes.md) | Every real bug hit during development, root cause, and exact fix |
| [docs/prompt-engineering.md](docs/prompt-engineering.md) | How all three LLM prompts are structured and how hallucinations are prevented |
| [docs/retrieval-design.md](docs/retrieval-design.md) | Hybrid retrieval internals — RRF formula, chunking strategy, confidence threshold |

---

## What It Does

| Capability | Detail |
|---|---|
| **Receipt ingestion** | Upload PDF, JPG, PNG, or TXT receipts. Text PDFs parsed locally; images and scanned PDFs sent to a vision LLM. |
| **Per-line-item verdicts** | Each receipt gets a verdict — **Compliant ✓**, **Flagged ⚠**, or **Rejected ✗** — with full reasoning and verbatim policy citations. |
| **Policy-grounded citations** | The system quotes the exact clause (e.g. TEP-003 §3.1) that drives each decision. No hallucinated rules. |
| **Confidence scores** | Every verdict carries a 0–100% confidence score. Low-confidence items are visually flagged for extra human attention. |
| **Override + audit trail** | Any verdict can be overridden by a reviewer with a comment. All overrides are stored permanently and visible in the UI. |
| **Submission history** | Browse all past submissions by employee, date, or status. State persists across server restarts (SQLite). |
| **Policy Q&A** | Ask free-form questions about the policy library and get cited, grounded answers — or a clear refusal if the question is out of scope. |
| **Employee management** | 5 sample employees are seeded on startup. New employees can be added directly from the UI. |

---

## Live Demo / Screenshots

### 1. Submissions List

![Submissions list with employee and status filters](screenshots/01_submissions_list.png)

The landing page lists every expense submission across all employees. Each row shows the employee name, trip purpose, date range, number of receipts, and an overall status badge. The status rolls up from the worst verdict among all line items — if even one item is rejected, the whole submission shows **Rejected**. The filter bar on the left lets reviewers narrow by employee or status (Pending / Compliant / Flagged / Rejected), so a finance manager can instantly pull up every flagged submission waiting for their attention without scrolling through clean ones.

---

### 2. Submission Detail — Mixed Verdicts Side by Side

![Submission detail for James Walker's Austin trip showing Torchy's (compliant) and Franklin BBQ (rejected)](screenshots/02_submission_detail_mixed.png)

This is the detail view for **James Walker's Austin research trip**. The top card shows the employee profile (grade, department, home base) and trip context — information the AI uses when applying policies. The line items table below shows two receipts reviewed in the same trip:

| Receipt | Amount | Verdict | Confidence |
|---|---|---|---|
| Torchy's Tacos (lunch) | $18.40 | **Compliant ✓** | 100% |
| Franklin Barbecue (dinner with drinks) | $94.30 | **Rejected ✗** | 100% |

The confidence bar fills green for high-confidence verdicts and amber/red for uncertain ones. A reviewer can immediately see which items need their attention without opening each one.

---

### 3. Alcohol Policy Rejection — Verbatim Policy Citations

![Detail modal for Franklin Barbecue showing rejected verdict with three TEP-003 citations quoted verbatim](screenshots/03_alcohol_rejection_detail.png)

Clicking **Details** on the Franklin Barbecue line item opens this modal. This is the most important screen in the system — it shows exactly how the AI arrived at its verdict:

- **Verdict:** Rejected — shown with a red badge and 100% confidence
- **Reasoning:** 2–3 sentences explaining that the employee was on solo travel and the receipt includes alcoholic beverages (beer and wine), which are non-reimbursable under TEP-003 §3.1 regardless of the meal amount
- **Policy Citations:** Three verbatim excerpts from the actual policy documents, each in a blockquote:
  - **TEP-002 §6** — general alcohol reimbursement conditions
  - **TEP-003 §3.1** — the specific solo-travel alcohol prohibition
  - **TEP-003 §7.1** — a worked example from the policy confirming the rule applies here

Every quote is pulled directly from the source PDF — the AI cannot fabricate a citation because the retrieval pipeline only provides real chunks, and the system prompt explicitly prohibits quoting text not in the provided excerpts.

---

### 4. Over-Cap Rejection — Dollar Limit Violation

![Detail modal for Alinea dinner showing $148.20 rejected against the $75/person dinner cap](screenshots/04_over_cap_rejection.png)

This modal shows **Priya Patel's Alinea dinner** on her Chicago vendor visit — a different kind of rejection from the alcohol case. The meal total was $148.20 for a solo dinner, which exceeds the **$75 per-person dinner cap** for solo travel under TEP-002 §2. The AI:

- Identifies this as a solo meal (no external clients listed in the trip purpose)
- Retrieves TEP-002's per-meal cap table and applies the correct tier (Chicago is Tier 2, cap stays $75)
- Rejects with 95% confidence and cites the exact dollar figure from the policy
- Does **not** flag it as a client entertainment expense (which has a higher $150 cap) because the trip context makes clear no clients were present

This demonstrates the system correctly applies context — the same restaurant on a client dinner would be compliant.

---

### 5. Compliant Item — Clean Expense Passes All Checks

![Detail modal for Torchy's Tacos showing compliant verdict at 100% confidence](screenshots/05_compliant_item.png)

For contrast, this modal shows the **Torchy's Tacos lunch** from the same Austin trip — $18.40, well under the $35 solo lunch cap, no alcohol, within the trip dates. The verdict is **Compliant** at 100% confidence. The reasoning confirms the amount is within the per-person lunch cap for a Tier 2 city and no prohibited items are present. Policy citations point to TEP-002 §2 confirming the cap. The system is not a rejection machine — it correctly clears straightforward expenses so reviewers only spend time on genuine edge cases.

---

### 6. Policy Q&A — Grounded Answer with Citation

![Policy Q&A tab showing a question about dinner caps answered with a verbatim TEP-002 citation](screenshots/06_qa_answer_with_citation.png)

The **Policy Q&A** tab lets any reviewer ask a free-form question about the policy library and get a cited, precise answer. In this example, the question is:

> *"What is the per-person dinner cap for solo travel, and how does it change in Tier 1 cities?"*

The system:
1. Runs hybrid retrieval (BM25 + dense embeddings) over all 90 policy chunks
2. Finds TEP-002 §2 as the most relevant excerpt
3. Returns a structured answer quoting the exact figures: $75 base / $93.75 in Tier 1 cities (+25%)
4. Shows the verbatim blockquote from TEP-002 so the reviewer can verify the source

The answer is never fabricated — if the policy chunks don't contain the answer, the system refuses rather than guessing.

---

### 7. Policy Q&A — Out-of-Scope Refusal

![Policy Q&A refusing "Who built the Eiffel Tower?" with a clear explanation](screenshots/07_qa_refusal.png)

When asked a question with no relevant policy content — here, *"Who built the Eiffel Tower?"* — the system returns a clean refusal rather than hallucinating an answer. This is driven by the retrieval confidence score: if the top-ranked policy chunk scores below the minimum threshold (0.18 on a normalized 0–1 scale), the system refuses before even calling the LLM. The refusal message explains that the question appears to be outside the scope of the Northwind policy library and suggests rephrasing if it was intended as a policy question. This is critical for reviewer trust — a system that sometimes makes things up is worse than one that clearly admits the limits of its knowledge.

---

## Quick Start

### Prerequisites

- Python 3.10+ (tested on 3.14 with Anaconda `LLM` environment)
- An [OpenRouter](https://openrouter.ai) API key

### 1 — Clone and configure

```bash
git clone <your-repo-url>
cd Northwood
```

Create a `.env` file in the project root (or edit the existing one):

```env
# Required
OPENROUTER_API_KEY=sk-or-v1-...

# Models (any OpenRouter slug works)
EXTRACTION_MODEL=google/gemini-2.5-flash
REASONING_MODEL=google/gemini-2.5-flash

# Paths (defaults work if you run from project root)
POLICIES_DIR=./data/policies
SUBMISSIONS_DIR=./data/submissions
DB_PATH=./data/northwind.db

# Retrieval tuning
RETRIEVAL_TOP_K=6
RETRIEVAL_MIN_CONFIDENCE=0.18
EMBEDDING_MODEL=BAAI/bge-small-en-v1.5
```

### 2 — Install dependencies

```bash
# Using conda (recommended)
conda run -n LLM pip install -r requirements.txt

# Or with any Python 3.10+ venv
pip install -r requirements.txt
```

### 3 — Start the server

```bash
# From the project root
conda run -n LLM uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

On first run the server will:
1. Create the SQLite database at `data/northwind.db`
2. Seed the 5 sample employees from `data/submissions/*/employee_info.json`
3. Download the embedding model (`BAAI/bge-small-en-v1.5`, ~120 MB) if not cached
4. Index all policy PDFs into ChromaDB — **~30–60 seconds, one time only**

You will see:
```
INFO:  Policy index has 90 chunks — skipping re-index.
INFO:  Application startup complete.
```

Open **http://localhost:8000** in your browser.

### 4 — Run the smoke test (optional, server must be running)

```bash
conda run -n LLM python test_smoke.py
```

Expected output:
```
  ✓  Employees seeded — 5 found
  ✓  Policy index built — 90 chunks
  ✓  Create submission
  ✓  Upload + review receipt
  ✓  Alcohol correctly rejected — verdict=rejected conf=1.00
  ✓  TEP-003 cited
  ✓  Q&A answers policy question
  ✓  Q&A refuses out-of-scope

  8/8 checks passed
```

---

## Project Structure

```
Northwood/
│
├── backend/                        # FastAPI application
│   ├── main.py                     # App entry point, lifespan startup
│   ├── config.py                   # Loads .env settings
│   ├── database.py                 # SQLAlchemy models + DB init
│   ├── models.py                   # Pydantic API schemas
│   ├── startup.py                  # Seed employees, index policies
│   │
│   ├── routers/
│   │   ├── employees.py            # GET/POST/PUT employees
│   │   ├── submissions.py          # Create submissions, upload receipts
│   │   ├── line_items.py           # Get item details, submit overrides
│   │   └── policy_qa.py            # Policy Q&A, index status/rebuild
│   │
│   └── services/
│       ├── llm_client.py           # OpenRouter HTTP client (text + vision)
│       ├── policy_indexer.py       # PDF → chunks → embeddings → ChromaDB
│       ├── retrieval.py            # Hybrid BM25 + dense retrieval, RRF fusion
│       ├── receipt_extractor.py    # Extract structured data from receipts
│       └── reviewer.py             # Generate verdicts and Q&A answers
│
├── frontend/
│   └── index.html                  # Single-page app (Tailwind CDN + vanilla JS)
│
├── eval/
│   └── harness.py                  # Evaluation harness (see section below)
│
├── data/
│   ├── policies/                   # 8 policy PDFs (31 distinct policy documents)
│   ├── submissions/                # 5 sample submission folders
│   ├── northwind.db                # SQLite database (created on first run)
│   ├── chroma_db/                  # ChromaDB vector store (created on first run)
│   └── uploads/                    # Uploaded receipt files
│
├── .env                            # API keys and config (not committed)
├── requirements.txt
├── test_smoke.py                   # Quick end-to-end smoke test
└── README.md
```

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│  Browser  —  Vanilla JS + Tailwind CSS (single index.html, no build) │
│                                                                        │
│   Submissions List  │  Submission Detail  │  Employees  │  Policy Q&A │
│                     │                     │             │              │
│   Filter by emp /   │  Employee card      │  Employee   │  Free-text   │
│   date / status     │  Trip context       │  list +     │  question    │
│   Click → detail    │  Upload receipts    │  add form   │  input       │
│                     │  Line item table    │             │              │
│                     │  ✓ ⚠ ✗ badges      │             │  Cited answer│
│                     │  Details modal      │             │  or refusal  │
│                     │  Override modal     │             │              │
└──────────┬──────────────────────────────────────────────────────────-─┘
           │  REST / JSON over HTTP
┌──────────▼────────────────────────────────────────────────────────────┐
│  FastAPI Backend                                                        │
│                                                                        │
│  POST /api/submissions/{id}/receipts   ← main pipeline trigger        │
│  POST /api/line_items/{id}/override    ← audit trail                  │
│  POST /api/policy/qa                   ← grounded Q&A                 │
│                                                                        │
│  ┌─────────────────────────────────────────────────────────────────┐  │
│  │  Review Pipeline  (runs per uploaded receipt file)              │  │
│  │                                                                  │  │
│  │  1. receipt_extractor                                            │  │
│  │     PDF text  ──────────────────────────────► structured JSON   │  │
│  │     Image / scanned PDF ──► vision LLM ────► structured JSON   │  │
│  │     .txt ──────────────────────────────────► structured JSON   │  │
│  │                                                                  │  │
│  │  2. retrieval  (hybrid)                                          │  │
│  │     query = category + description + grade + flags              │  │
│  │     dense  ──► BAAI/bge-small-en-v1.5 ──► ChromaDB cosine     │  │
│  │     sparse ──► BM25 (rank-bm25)                                │  │
│  │     fusion ──► Reciprocal Rank Fusion (k=60) ──► top-6 chunks │  │
│  │                                                                  │  │
│  │  3. reviewer  (LLM)                                              │  │
│  │     system prompt + employee ctx + trip ctx + 6 policy chunks   │  │
│  │     ──► Gemini 2.5 Flash (JSON mode) ──► verdict JSON          │  │
│  │     { verdict, reasoning, policy_citations[], confidence,flags } │  │
│  └─────────────────────────────────────────────────────────────────┘  │
│                                                                        │
│  ┌──────────────┐   ┌────────────────┐   ┌────────────────────────┐  │
│  │  SQLite DB   │   │   ChromaDB     │   │  Sentence Transformers │  │
│  │              │   │                │   │  BAAI/bge-small-en-v1.5│  │
│  │  employees   │   │  90 policy     │   │  384-dim embeddings    │  │
│  │  submissions │   │  chunks with   │   │  runs locally, free    │  │
│  │  line_items  │   │  metadata:     │   └────────────────────────┘  │
│  │  overrides   │   │  doc_id,       │                               │
│  │  policy_     │   │  section,      │   ┌────────────────────────┐  │
│  │  chunks      │   │  source_file   │   │  OpenRouter API        │  │
│  │              │   │                │   │  google/gemini-2.5-    │  │
│  │  persists    │   │  persisted to  │   │  flash                 │  │
│  │  across      │   │  data/         │   │  - receipt extraction  │  │
│  │  restarts    │   │  chroma_db/    │   │  - policy review       │  │
│  └──────────────┘   └────────────────┘   │  - policy Q&A          │  │
│                                           │  - vision (images)     │  │
│                                           └────────────────────────┘  │
└───────────────────────────────────────────────────────────────────────┘
```

---

## How the Review Pipeline Works

Every uploaded receipt goes through three stages:

### Stage 1 — Extraction

| File type | Method |
|---|---|
| `.pdf` (text-based) | `pdfplumber` extracts raw text; LLM parses into structured JSON |
| `.pdf` (scanned/image) | Falls back to vision LLM (Gemini Flash) if text < 30 chars |
| `.jpg` / `.png` / `.webp` | Sent directly to vision LLM as base64 |
| `.txt` | Read directly; LLM parses into structured JSON |

Extracted fields: `vendor`, `date`, `amount`, `currency`, `category`, `description`, `party_size`, `alcohol_present`, `line_items[]`, `notes`

### Stage 2 — Policy Retrieval

A **category-enriched query** is built from the extracted data, e.g.:
```
"meals expense policy per-meal cap per-person limit dinner grade 4 alcohol solo travel"
```

This query runs through **hybrid retrieval**:
- **Dense**: BAAI/bge-small-en-v1.5 embeddings → ChromaDB cosine similarity
- **Sparse**: BM25 (rank-bm25) over all policy chunk text
- **Fusion**: Reciprocal Rank Fusion (RRF, k=60) — top-6 chunks returned

RRF scores are normalized to [0, 1] for threshold comparison.

### Stage 3 — LLM Review

The reviewer LLM receives:
- Full employee profile (grade, department, home base)
- Trip context (purpose, dates — critical for solo vs client travel)
- Extracted receipt data
- Top-6 retrieved policy chunks (verbatim)

It returns structured JSON (enforced via JSON-mode):

```json
{
  "verdict": "rejected",
  "reasoning": "The employee was on solo travel and the receipt includes alcoholic beverages...",
  "policy_citations": [
    {
      "doc_id": "TEP-003",
      "section": "3.1. Solo travel",
      "quote": "Any alcoholic beverage purchased while traveling on business without external clients present...",
      "relevance": "This clause directly prohibits the beer and wine charges on this receipt."
    }
  ],
  "confidence": 0.95,
  "flags": ["alcohol on solo travel"]
}
```

**Verdict rules:**
- `compliant` — expense clearly meets policy, no material issues
- `flagged` — potential violation or ambiguity requiring human judgement
- `rejected` — clear policy violation that should not be reimbursed

**Confidence rules:**
- `0.9–1.0` — unambiguous rule + clear facts
- `0.6–0.9` — rule present, some interpretation required
- `0.3–0.6` — weak or missing relevant policy context
- `< 0.3` — almost no relevant policy found (triggers low-confidence flag)

---

## Policy Library

The 8 policy PDFs in `data/policies/` contain **31 distinct policy documents**, identified by their `Document: XXX-NNN` headers.

| PDF file | Contains |
|---|---|
| `policy1.pdf` | TEP-001 (T&E Overview), TEP-002 (Meals & Entertainment), TEP-003 (Alcohol), TEP-004 (Lodging) |
| `policy2.pdf` | TEP-005 (Air Travel), TEP-006 (Ground Transportation), TEP-007 (Receipt Requirements), TEP-008 (Per-Diem Rates) |
| `policy3.pdf` | TEP-009 (Employee Grades), TEP-010 (Corporate Card), TEP-012 (Gifts & Entertainment) |
| `policy4.pdf` | TEP-013 (International Travel), TEP-014 (Conference Attendance), SEC-301 (Travel Risk) |
| `policy5.pdf` | COC-001 (Code of Conduct), HRP-015, HR-104, HR-208 |
| `policy6.pdf` | REC-001 (Records Retention), LEG-101, PRIV-101, LEG-203 |
| `policy7.pdf` | SEC-201 (Data Classification), SEC-202, FAC-005, SEC-204 |
| `policy8.pdf` | SUS-001 (Sustainability), PROC-002, HR-302, BC-001 |

**T&E relevant policies** (TEP-001 through TEP-014) are in `policy1.pdf`–`policy4.pdf`.  
**Noise policies** (data classification, records retention, sustainability, code of conduct) exist as realistic irrelevant content to test retrieval precision.

### Key policy rules (for understanding test cases)

| Policy | Key rule |
|---|---|
| TEP-002 §2 | Breakfast $25 / Lunch $35 / Dinner $75 per person. +25% in Tier 1 cities. |
| TEP-002 §4 | Client entertainment: Lunch $80 / Dinner $150 per person. Requires VP approval >$100/person. |
| TEP-003 §2 | Alcohol only reimbursable during sanctioned client entertainment (external attendee + VP approval + ≤$50/person). |
| TEP-003 §3.1 | **Solo travel: zero alcohol reimbursement, regardless of amount.** |
| TEP-004 §3 | Lodging caps: Tier 1 (NYC, SF, Boston, etc.) $350/night; Tier 2 (Chicago, Denver, Austin, etc.) $250/night; Tier 3 $175/night. |
| TEP-005 §2 | Economy class default for all domestic flights. Business class only on international ≥10h with VP approval. |
| TEP-009 | Grade ladder 1–10. Grade 4 = Senior Specialist, Grade 5 = Manager, Grade 6 = Senior Manager, Grade 7 = Director. |

---

## Sample Submissions

Five sample submissions are included in `data/submissions/`. They span a deliberate range:

| Folder | Employee | Trip | Expected result |
|---|---|---|---|
| `01_clean_denver/` | Sarah Chen (Grade 5) | Client review in Denver | All compliant — baseline clean submission |
| `02_clean_boston_conf/` | Marcus Rivera (Grade 7) | AWS re:Inforce conference in Boston | All compliant — conference with registration fee |
| `03_dinner_over_cap/` | Priya Patel (Grade 4) | Vendor site visit in Chicago | Alinea dinner ($148.20) over the $75 cap → **Rejected** |
| `04_alcohol_solo_travel/` | James Walker (Grade 6) | Solo carrier research in Austin | Franklin BBQ dinner with beer + wine → **Rejected** (TEP-003) |
| `05_receipt_mismatch/` | Linda Foster (Grade 5) | Client QBR in Seattle | Contains date/context mismatch → **Flagged** |

To test all five: create a new submission for each employee in the UI and upload all receipts from the corresponding `receipts/` folder.

---

## API Reference

All endpoints return JSON. Base URL: `http://localhost:8000`

### Employees

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/employees` | List all employees |
| `GET` | `/api/employees/{id}` | Get one employee |
| `POST` | `/api/employees` | Create employee |
| `PUT` | `/api/employees/{id}` | Update employee |

### Submissions

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/submissions` | List all submissions (filter: `?employee_id=&status=`) |
| `GET` | `/api/submissions/{id}` | Get submission with all line items |
| `POST` | `/api/submissions` | Create new submission |
| `DELETE` | `/api/submissions/{id}` | Delete submission |
| `POST` | `/api/submissions/{id}/receipts` | Upload receipt files (multipart), runs review pipeline |

### Line Items & Overrides

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/line_items/{id}` | Get line item with override history |
| `POST` | `/api/line_items/{id}/override` | Submit a reviewer override |

### Policy

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/policy/qa` | Ask a question about the policy library |
| `GET` | `/api/policy/index/status` | Check indexing status and chunk count |
| `POST` | `/api/policy/index/rebuild` | Force re-index all policy PDFs |

### Example — Upload receipts

```bash
curl -X POST http://localhost:8000/api/submissions/{id}/receipts \
  -F "files=@receipt1.pdf" \
  -F "files=@receipt2.jpg"
```

### Example — Policy Q&A

```bash
curl -X POST http://localhost:8000/api/policy/qa \
  -H "Content-Type: application/json" \
  -d '{"question": "What is the dinner cap for solo travel?"}'
```

Response:
```json
{
  "answer": "The per-person dinner cap for solo travel is $75.",
  "citations": [{"doc_id": "TEP-002", "section": "2. Per-meal caps", "quote": "Dinner $75"}],
  "confidence": 1.0,
  "refused": false,
  "refusal_reason": null
}
```

---

## Evaluation Harness

The harness at `eval/harness.py` accepts a JSON file of test cases, submits them through the live API, and reports accuracy metrics.

### Running it

```bash
# Server must be running on localhost:8000
conda run -n LLM python eval/harness.py \
  --api http://localhost:8000 \
  --test-cases eval/test_cases.json \
  --out eval/results.json
```

### Test cases format (`eval/test_cases.json`)

```json
{
  "test_cases": [
    {
      "id": "tc_alcohol_solo",
      "employee": {"id": "NW-03488"},
      "trip": {
        "purpose": "Solo research trip to Austin",
        "start": "2025-03-18",
        "end": "2025-03-20"
      },
      "receipts": [
        {
          "filename": "receipts/05_dinner_franklin.pdf",
          "expected_verdict": "rejected",
          "expected_category": "meals",
          "expected_citation_doc": "TEP-003",
          "notes": "Contains alcohol on solo travel"
        }
      ],
      "qa_tests": [
        {
          "question": "Can I expense alcohol when traveling alone?",
          "should_refuse": false,
          "should_cite": "TEP-003"
        },
        {
          "question": "What is the capital of France?",
          "should_refuse": true
        }
      ]
    }
  ]
}
```

### Metrics reported

| Metric | What it measures |
|---|---|
| `verdict_accuracy` | % of line items where AI verdict matches expected verdict |
| `category_accuracy` | % of items where category classification is correct |
| `citation_hit_rate` | % of items where the expected policy document appears in citations |
| `refusal_accuracy` | % of Q&A tests where refusal/answer behaviour is correct |
| `mean_confidence` | Average confidence score across all reviewed items |
| `low_confidence_rate` | % of verdicts with confidence < 0.4 (potential calibration issue) |

**Why these metrics:**  
Verdict accuracy is the primary correctness signal. Citation hit rate specifically tests retrieval faithfulness — a correct verdict citing the wrong policy is a hallucination risk that will erode reviewer trust. Refusal accuracy tests the "honest I don't know" property the brief specifically called out. Confidence calibration catches systematic overconfidence, which is dangerous in an automated review system.

---

## Design Decisions & Tradeoffs

### 1. Retrieval — Hybrid BM25 + Dense with RRF

**What:** For each expense item, a category-enriched query is built (e.g. `"meals expense policy per-meal cap per-person limit dinner grade 4 alcohol solo travel"`), then run through both dense and sparse retrievers, fused with Reciprocal Rank Fusion (k=60).

**Why:** Dense embeddings miss exact term matches (`"$75"`, `"TEP-003"`, `"solo travel"`); BM25 misses semantic similarity (`"alcohol"` ↔ `"alcoholic beverages"`). RRF is robust to score scale differences and requires no tuning.

**Tradeoff:** BM25 index is rebuilt in-memory from SQLite on cold start (~0.5s for 90 chunks). Fine at this scale. At 10k submissions/day with large policy libraries, move to Elasticsearch or Weaviate for persistent keyword + vector search.

---

### 2. Chunking — Sub-document splitting with section headers

**What:** Each PDF is first split on `Document: XXX-NNN` headers into per-policy sub-documents (e.g. TEP-002, TEP-003). Each sub-document is then chunked at ~450 tokens with one-paragraph overlap, and the current section header is propagated as metadata.

**Why:** Without sub-document isolation, a naive chunker would mix TEP-003 alcohol rules with REC-001 retention schedules in the same chunk, destroying retrieval precision. Sub-document isolation ensures every chunk is semantically coherent.

**Tradeoff:** Some cross-reference context is lost at chunk boundaries (e.g. TEP-002 referring to TEP-003). This is acceptable because the LLM context holds 6 chunks, which typically covers the full relevant policy (most T&E policies fit in 2–3 chunks).

---

### 3. Model selection — Gemini 2.5 Flash for extraction and review

**What:** Both receipt extraction and policy review use `google/gemini-2.5-flash` via OpenRouter. The same model handles vision for image/scanned receipts.

**Why over alternatives:**
- Gemini Flash has native vision support — no separate OCR service needed
- 1M token context window — can hold all policy excerpts comfortably
- Strong JSON-mode compliance — critical for structured verdict output
- Low cost (~$0.15/1M input tokens as of June 2026)

**Tradeoff:** For highly ambiguous cases (amount exactly at cap, unclear party size, ambiguous business purpose), a stronger model (Gemini Pro, Claude Sonnet) would produce better reasoning. Production approach: route items with confidence < 0.5 to a stronger model, paying ~10x more only for the hard cases.

---

### 4. Confidence and verdict calibration

Three verdict tiers:
- **`compliant`** — expense clearly within policy, no flags
- **`flagged`** — amount near cap, missing context (solo vs client), or policy context thin. Human must decide.
- **`rejected`** — unambiguous violation (alcohol on solo travel, amount far over cap, explicitly prohibited item)

The system biases toward `flagged` over `rejected` when evidence is mixed — a false negative (human reviews a flagged item) is far cheaper than a false positive (legitimate expense incorrectly rejected, employee frustrated).

If retrieval confidence is below the threshold (`RETRIEVAL_MIN_CONFIDENCE = 0.18`), the LLM verdict confidence is soft-downgraded and a `low_retrieval_confidence` flag is added. The Q&A endpoint hard-refuses at this threshold.

---

### 5. Persistence — SQLite + ChromaDB

SQLite handles all relational data. ChromaDB (persistent mode) stores the policy vector index. Both write to `data/` and survive server restarts.

**Tradeoff:** SQLite is single-writer; won't scale past ~200 concurrent requests. For 10k submissions/day (avg ~0.12 req/s), it's fine. At higher concurrency, migrate to **PostgreSQL + pgvector** — one dependency that replaces both SQLite and ChromaDB.

---

### 6. Frontend — Vanilla JS + Tailwind CDN

No Node.js, no bundler, no build step. The entire frontend is a single `index.html` served by FastAPI. Deployment is just: copy the repo, set the env var, run uvicorn.

**Tradeoff:** Managing complex state in vanilla JS is painful beyond ~3000 lines. For a real product, use React + Vite. The current implementation is scoped to the demo requirements.

---

## Cost Estimate

### Per submission (6 receipts, ~400 tokens each)

| Step | Tokens | Cost |
|---|---|---|
| Extraction (6 receipts × ~800 input tokens) | 4,800 | ~$0.00072 |
| Review (6 items × ~2,500 input tokens) | 15,000 | ~$0.00225 |
| Embeddings | — | $0 (local) |
| **Total per submission** | | **~$0.003** |

At **10,000 submissions/day**: ~$30/day in LLM costs.

### Scaling to 10,000 submissions/day

1. **Async pipeline** — Move receipt upload + review to a task queue (Celery + Redis or FastAPI `BackgroundTasks`). Return immediately with a "processing" status; poll for completion.
2. **GPU embeddings** — sentence-transformers already supports batching; add a GPU node for ~10x throughput.
3. **pgvector migration** — Replace ChromaDB + SQLite with PostgreSQL + pgvector. Single dependency, scales horizontally with read replicas.
4. **Embedding cache** — Policy chunks are static. Cache their embeddings; only re-embed on policy updates.
5. **Model tiering** — Route high-confidence extractions to a cheaper/faster model; reserve Gemini Flash for ambiguous cases.
6. **Rate limiting + retry** — Add exponential backoff on OpenRouter calls with a circuit breaker.

---

## Deployment

### Local (covered above)

```bash
conda run -n LLM uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

### Docker

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

```bash
docker build -t northwind-expense .
docker run -p 8000:8000 --env-file .env -v $(pwd)/data:/app/data northwind-expense
```

> Mount `data/` as a volume so the SQLite DB and ChromaDB index persist between container restarts.

### Cloud (Render / Railway / Fly.io)

1. Push the repo to GitHub
2. Create a new web service pointing at the repo
3. Set `OPENROUTER_API_KEY` as an environment secret
4. Set start command: `uvicorn backend.main:app --host 0.0.0.0 --port $PORT`
5. Attach a persistent disk mounted at `/app/data`

---

## What I'd Do Next

1. **Streaming responses** — Stream LLM reasoning tokens to the browser so reviewers see the verdict being built in real time rather than waiting for the full round trip (~3–8s).

2. **Async review pipeline** — Return the submission immediately with a "processing" status; process receipts in the background; update via WebSocket or polling. Eliminates the UI freeze during upload.

3. **Duplicate detection** — Flag when two receipts in one submission have the same vendor + amount + date (likely a duplicate expense claim).

4. **Richer audit trail** — Track manager approval/rejection as a separate step after AI pre-review + override. Full state machine: `pending → reviewed → approved/rejected`.

5. **Fine-tuning feedback loop** — Log every override as `(policy_chunks, receipt_text, AI_verdict, human_verdict)`. Use this signal to fine-tune the reviewer prompt or train a smaller local model.

6. **pgvector migration** — Replace the ChromaDB + SQLite split with a single PostgreSQL + pgvector instance. Simplifies ops and enables atomic transactions across relational and vector data.

7. **Multi-tenant with auth** — Add OAuth2 (e.g. Google Workspace) for reviewer login, and namespace employees + submissions by company/team.

8. **Policy versioning** — Track when a policy document changes, re-index only the changed chunks, and note which policy version was in effect when each verdict was made.

---

## Environment Variables Reference

| Variable | Required | Default | Description |
|---|---|---|---|
| `OPENROUTER_API_KEY` | ✅ | — | OpenRouter API key |
| `OPENROUTER_APP_TITLE` | | `Northwind Expense Review` | Shown in OpenRouter dashboard |
| `OPENROUTER_HTTP_REFERER` | | `http://localhost:8000` | Shown in OpenRouter dashboard |
| `EXTRACTION_MODEL` | | `google/gemini-2.5-flash` | Model for receipt parsing (must support vision) |
| `REASONING_MODEL` | | `google/gemini-2.5-flash` | Model for policy review and Q&A |
| `EMBEDDING_MODEL` | | `BAAI/bge-small-en-v1.5` | Local sentence-transformers model |
| `POLICIES_DIR` | | `./data/policies` | Path to policy PDF folder |
| `SUBMISSIONS_DIR` | | `./data/submissions` | Path to sample submissions folder |
| `DB_PATH` | | `./data/northwind.db` | SQLite database path |
| `RETRIEVAL_TOP_K` | | `6` | Policy chunks retrieved per query |
| `RETRIEVAL_MIN_CONFIDENCE` | | `0.18` | Normalized RRF score threshold for Q&A refusal |

---

## Tech Stack

| Layer | Technology |
|---|---|
| Web framework | [FastAPI](https://fastapi.tiangolo.com/) |
| Database | [SQLite](https://sqlite.org/) via [SQLAlchemy](https://www.sqlalchemy.org/) |
| Vector store | [ChromaDB](https://www.trychroma.com/) (persistent) |
| Embeddings | [sentence-transformers](https://www.sbert.net/) — `BAAI/bge-small-en-v1.5` (local, free) |
| Sparse retrieval | [rank-bm25](https://github.com/dorianbrown/rank_bm25) |
| PDF parsing | [pdfplumber](https://github.com/jsvine/pdfplumber) |
| LLM API | [OpenRouter](https://openrouter.ai/) → `google/gemini-2.5-flash` |
| Frontend | Vanilla JS + [Tailwind CSS](https://tailwindcss.com/) (CDN, no build step) |
| HTTP client | [httpx](https://www.python-httpx.org/) |
