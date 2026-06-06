"""
Hybrid retrieval: dense (ChromaDB cosine) + sparse (BM25) fused with RRF.
The BM25 index is rebuilt from the SQLite corpus on first access.
"""
import logging
from typing import Optional

from rank_bm25 import BM25Okapi

from backend.services.policy_indexer import get_collection, _get_embedder
from backend.database import SessionLocal, PolicyChunk
from backend import config

log = logging.getLogger(__name__)

_bm25: Optional[BM25Okapi] = None
_bm25_chunks: list[dict] = []   # parallel list to bm25 corpus


def _build_bm25() -> tuple[BM25Okapi, list[dict]]:
    db = SessionLocal()
    try:
        rows = db.query(PolicyChunk).all()
        chunks = [{"chroma_id": r.chroma_id, "text": r.text, "doc_id": r.doc_id, "source_file": r.source_file} for r in rows]
    finally:
        db.close()

    if not chunks:
        return None, []

    corpus = [c["text"].lower().split() for c in chunks]
    bm25 = BM25Okapi(corpus)
    log.info("Built BM25 index over %d chunks.", len(chunks))
    return bm25, chunks


def _get_bm25() -> tuple[Optional[BM25Okapi], list[dict]]:
    global _bm25, _bm25_chunks
    if _bm25 is None:
        _bm25, _bm25_chunks = _build_bm25()
    return _bm25, _bm25_chunks


def invalidate_bm25():
    global _bm25, _bm25_chunks
    _bm25 = None
    _bm25_chunks = []


def retrieve(query: str, top_k: int | None = None, doc_id_filter: str | None = None) -> list[dict]:
    """
    Hybrid retrieval: returns list of dicts with keys
    {text, doc_id, source_file, section_header, score, rank_dense, rank_sparse}.
    """
    top_k = top_k or config.RETRIEVAL_TOP_K
    fetch_k = min(top_k * 3, 50)

    collection = get_collection()
    embedder = _get_embedder()

    # ── Dense retrieval ───────────────────────────────────────────────────────
    query_emb = embedder.encode(query, normalize_embeddings=True).tolist()
    where_filter = {"doc_id": {"$ne": "__none__"}}
    if doc_id_filter:
        where_filter = {"doc_id": doc_id_filter}

    n_in_collection = collection.count()
    if n_in_collection == 0:
        return []

    dense_res = collection.query(
        query_embeddings=[query_emb],
        n_results=min(fetch_k, n_in_collection),
        include=["documents", "metadatas", "distances"],
    )
    dense_ids = dense_res["ids"][0]
    dense_metas = dense_res["metadatas"][0]
    dense_docs = dense_res["documents"][0]
    dense_dists = dense_res["distances"][0]

    # Build dense id→rank map
    dense_rank: dict[str, int] = {cid: rank for rank, cid in enumerate(dense_ids)}
    id_to_data: dict[str, dict] = {}
    for cid, meta, doc, dist in zip(dense_ids, dense_metas, dense_docs, dense_dists):
        id_to_data[cid] = {
            "text": doc,
            "doc_id": meta.get("doc_id", ""),
            "source_file": meta.get("source_file", ""),
            "section_header": meta.get("section_header", ""),
            "dense_score": 1.0 - dist,   # cosine similarity
        }

    # ── Sparse (BM25) retrieval ───────────────────────────────────────────────
    bm25, bm25_chunks = _get_bm25()
    sparse_rank: dict[str, int] = {}
    if bm25 and bm25_chunks:
        tokenized = query.lower().split()
        scores = bm25.get_scores(tokenized)
        top_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:fetch_k]
        for rank, idx in enumerate(top_indices):
            cid = bm25_chunks[idx]["chroma_id"]
            sparse_rank[cid] = rank
            if cid not in id_to_data:
                id_to_data[cid] = {
                    "text": bm25_chunks[idx]["text"],
                    "doc_id": bm25_chunks[idx]["doc_id"],
                    "source_file": bm25_chunks[idx]["source_file"],
                    "section_header": "",
                    "dense_score": 0.0,
                }

    # ── RRF fusion ────────────────────────────────────────────────────────────
    k = 60
    rrf: dict[str, float] = {}
    for cid, rank in dense_rank.items():
        rrf[cid] = rrf.get(cid, 0.0) + 1.0 / (k + rank)
    for cid, rank in sparse_rank.items():
        rrf[cid] = rrf.get(cid, 0.0) + 1.0 / (k + rank)

    sorted_ids = sorted(rrf, key=rrf.__getitem__, reverse=True)[:top_k]

    # Normalize RRF scores to [0, 1] using theoretical max (2/k when ranked #1 in both indices)
    theoretical_max = 2.0 / k
    results = []
    for rank, cid in enumerate(sorted_ids):
        d = id_to_data[cid]
        norm_score = min(1.0, rrf[cid] / theoretical_max)
        results.append({
            "text": d["text"],
            "doc_id": d["doc_id"],
            "source_file": d["source_file"],
            "section_header": d.get("section_header", ""),
            "score": norm_score,
            "rank": rank,
        })

    return results


def max_score(results: list[dict]) -> float:
    if not results:
        return 0.0
    return max(r["score"] for r in results)
