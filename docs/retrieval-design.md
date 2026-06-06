# Retrieval System Design

How policy chunks are indexed, retrieved, and ranked — and the reasoning behind each decision.

---

## Why Hybrid Retrieval

The system uses two retrieval methods in parallel and fuses their results.

**Dense retrieval (semantic):** Encodes the query and all policy chunks as embedding vectors. Finds chunks that are *semantically similar* even when exact words don't match. Example: the query `"alcohol on solo business travel"` matches TEP-003's `"alcoholic beverage purchased while traveling on business without external clients"` because the embeddings are close in vector space, even though no exact phrase matches.

**Sparse retrieval (keyword, BM25):** Finds chunks that contain the *exact terms* from the query. Excels at matching specific numbers (`"$75"`, `"$350/night"`), policy codes (`"TEP-003"`), and technical phrases (`"Tier 1 city"`).

**Why both are needed:**

| Query term | Dense finds | BM25 finds |
|---|---|---|
| "alcohol on solo travel" | TEP-003 §3.1 (semantic match) | May miss (different words) |
| "what is the $75 cap" | May miss (number not semantic) | TEP-002 §2 (exact match) |
| "TEP-003 alcohol rule" | ✓ (policy name + topic) | ✓ (exact code match) |

Neither method alone achieves the recall needed for robust policy retrieval. Hybrid retrieval covers both cases.

---

## Reciprocal Rank Fusion (RRF)

RRF is the fusion algorithm. It takes two ranked lists and produces a single merged ranking.

**Formula:**

```
RRF_score(chunk) = 1/(k + rank_dense) + 1/(k + rank_sparse)
```

Where:
- `rank_dense` = position of chunk in the dense ranked list (0-indexed)
- `rank_sparse` = position in the BM25 ranked list
- `k = 60` (smoothing constant — prevents top ranks from dominating too heavily)

**Why RRF over weighted average:**
- Dense and sparse scores are on completely different scales. Dense scores are cosine similarities [0, 1]. BM25 scores are term-frequency-based and can be any positive float. Averaging them directly would require carefully tuned weights.
- RRF only cares about *rank*, not the raw score value. It's robust to score-scale differences and requires no tuning beyond `k`.
- Changing `k` shifts how much top-1 is rewarded vs top-10. `k=60` is the standard default that works well across domains.

**Score normalization:**

Raw RRF scores sit in `[0, 2/k]`. When a chunk ranks #1 in both lists: `1/(60+0) + 1/(60+0) = 2/60 ≈ 0.0333`. This is the theoretical maximum.

To make scores interpretable as a confidence signal (and comparable to the `RETRIEVAL_MIN_CONFIDENCE` threshold), scores are normalized to [0, 1]:

```python
theoretical_max = 2.0 / k  # ≈ 0.0333
norm_score = min(1.0, rrf[cid] / theoretical_max)
```

A normalized score of `1.0` means the chunk ranked first in both dense and sparse retrieval — maximum confidence. A score of `0.5` means it ranked first in one and much lower in the other. A score near `0.0` means it barely appeared in either list.

---

## Sub-document Chunking

### The problem with naive chunking

Each policy PDF contains 3–5 distinct policy documents separated by `Document: XXX-NNN` headers. A naive chunker that splits the full PDF at fixed token intervals creates chunks that cross policy boundaries — mixing TEP-002 meal caps with TEP-003 alcohol rules in the same chunk. This destroys retrieval precision.

**Example of what naive chunking produces (bad):**

```
Chunk 47:
...A dinner receipt for solo travel must not exceed $75 per person. (TEP-002 §2)

Document: TEP-003 — Alcohol Reimbursement Policy

3.1 Solo Travel
Any alcoholic beverage purchased...
```

This chunk would be retrieved for queries about both meal caps and alcohol — making it appear relevant for one when the query is about the other.

### The fix: two-phase chunking

1. **Phase 1 — Sub-document split:** Split the full PDF text on `Document: [A-Z]+-\d+` regex. Each segment is one policy document.
2. **Phase 2 — Token chunking:** Apply `~450 token` chunking with one-paragraph overlap *within* each sub-document only.
3. **Metadata propagation:** Track which `Document: XXX-NNN` sub-document each chunk came from. Propagate the most recent section header (e.g. `"3.1 Solo Travel"`) as metadata.

Result: every chunk belongs to exactly one policy document. Retrieval results are clean.

### Chunk size selection — 450 tokens

- **Too small (< 200 tokens):** Chunks lose context. A clause that refers to a table defined two paragraphs earlier becomes meaningless in isolation.
- **Too large (> 600 tokens):** Each chunk covers too much ground, reducing retrieval precision. The similarity score gets diluted by off-topic content within the same chunk.
- **450 tokens** hits the sweet spot for T&E policy text, which tends to have medium-length paragraphs with one rule per paragraph.

---

## RETRIEVAL_MIN_CONFIDENCE Threshold

The `RETRIEVAL_MIN_CONFIDENCE = 0.18` threshold controls two behaviors:

1. **Q&A hard refusal:** If `max_score < 0.18`, refuse the Q&A question without calling the LLM.
2. **Verdict soft downgrade:** If `max_score < 0.18` during a review, downgrade the returned confidence score proportionally and add a `low_retrieval_confidence` flag.

**Why 0.18:**

After normalizing RRF scores to [0, 1], a score of 0.18 corresponds to a chunk that ranked approximately 6th–8th in one index and didn't appear at all in the other. In practice, this reliably separates:

- **Above 0.18:** Chunks with clear topical relevance to the query (e.g. TEP-002 appearing for a meals query)
- **Below 0.18:** Chunks that appeared due to coincidental BM25 term matches with low semantic similarity (e.g. a sustainability policy chunk matching "travel" in a query about air travel caps)

This value was determined empirically by observing the score distribution across the 5 sample submissions. A higher threshold (e.g. 0.3) caused too many refusals for edge-case policy questions. A lower threshold (e.g. 0.05) allowed out-of-scope questions to receive hallucinated answers.

---

## BM25 Index Lifecycle

The BM25 index is not persisted to disk. It is rebuilt from SQLite in memory on the first retrieval call after startup. This is intentional:

- `rank-bm25` does not have a native serialization format
- Rebuilding 90 chunks takes ~0.05 seconds — negligible
- SQLite is already the authoritative store for chunk text; BM25 is derived data

If the policy index is rebuilt (via `POST /api/policy/index/rebuild`), `invalidate_bm25()` is called to clear the cached index, ensuring the next retrieval call rebuilds from the new chunks.

---

## Embedding Model Selection

**Model:** `BAAI/bge-small-en-v1.5`

| Property | Value |
|---|---|
| Dimensions | 384 |
| Size on disk | ~120 MB |
| Inference cost | Free (runs locally via sentence-transformers) |
| MTEB retrieval score | 51.7 (competitive with much larger models) |
| License | MIT |

**Why not a larger model (e.g. `text-embedding-3-large`):**
- OpenAI embedding API adds per-query cost and network latency
- Policy chunks are embedded once at indexing time; only queries are embedded at runtime
- For 90 chunks, 384-dim embeddings are more than sufficient — larger dimensions add no meaningful retrieval improvement at this scale

**Why not `bge-large` (768-dim):**
- 2x the vector size, 4x the memory, with marginal improvement on short policy text
- `bge-small` retrieval quality was verified to correctly surface TEP-003 alcohol clauses for alcohol-related queries, which is the hardest retrieval case in this domain
