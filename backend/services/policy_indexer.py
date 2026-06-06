"""
Policy PDF ingestion: parse → chunk → embed → store in ChromaDB.
Also maintains a BM25 index (in-memory) for hybrid retrieval.
"""
import re
import logging
from pathlib import Path
from typing import Optional

import pdfplumber
import chromadb
from sentence_transformers import SentenceTransformer

from backend import config
from backend.database import SessionLocal, PolicyChunk

log = logging.getLogger(__name__)

# ── Globals populated once at startup ─────────────────────────────────────────
_embedder: Optional[SentenceTransformer] = None
_chroma_client: Optional[chromadb.PersistentClient] = None
_collection: Optional[chromadb.Collection] = None
COLLECTION_NAME = "policy_chunks"


def _get_embedder() -> SentenceTransformer:
    global _embedder
    if _embedder is None:
        log.info("Loading embedding model %s …", config.EMBEDDING_MODEL)
        _embedder = SentenceTransformer(config.EMBEDDING_MODEL)
    return _embedder


def get_collection() -> chromadb.Collection:
    global _chroma_client, _collection
    if _collection is None:
        _chroma_client = chromadb.PersistentClient(path=config.CHROMA_PATH)
        _collection = _chroma_client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )
    return _collection


# ── PDF text extraction ────────────────────────────────────────────────────────

def extract_pdf_text(path: Path) -> str:
    pages = []
    with pdfplumber.open(path) as pdf:
        for pg in pdf.pages:
            t = pg.extract_text()
            if t:
                pages.append(t)
    return "\n\n".join(pages)


# ── Document-ID detection ──────────────────────────────────────────────────────

_DOC_ID_RE = re.compile(r'\bDocument:\s*([\w-]+)', re.IGNORECASE)
_ANY_ID_RE = re.compile(r'\b(?:TEP|COC|REC|SEC|SUS|HR|FIN|POL|GOV|ETH|VEN|BCP|LEG|PRIV|PROC|BC|FAC|HRP)-\d+\b')


def extract_doc_ids(text: str) -> list[str]:
    declared = _DOC_ID_RE.findall(text)
    return list(dict.fromkeys(declared)) if declared else []


# ── Chunking ──────────────────────────────────────────────────────────────────

def _approx_tokens(text: str) -> int:
    return len(text.split())


def chunk_document(text: str, source_file: str, doc_id: str, max_tokens: int = 450) -> list[dict]:
    """
    Split policy text into overlapping chunks, keeping the current section header.
    Returns list of {text, source_file, doc_id, section_header, chunk_index}.
    """
    paragraphs = [p.strip() for p in re.split(r'\n{2,}', text) if p.strip()]

    chunks: list[dict] = []
    current_paras: list[str] = []
    current_tokens = 0
    section_header = ""

    def flush():
        nonlocal current_paras, current_tokens
        if current_paras:
            body = "\n\n".join(current_paras)
            chunks.append({
                "text": body,
                "source_file": source_file,
                "doc_id": doc_id,
                "section_header": section_header,
                "chunk_index": len(chunks),
            })
        # keep last paragraph for overlap
        if len(current_paras) > 1:
            last = current_paras[-1]
            current_paras = [last]
            current_tokens = _approx_tokens(last)
        else:
            current_paras = []
            current_tokens = 0

    header_re = re.compile(r'^(?:\d+[\.\d]*\s+\w|\s*[A-Z][A-Z\s]{3,40}$)')

    for para in paragraphs:
        toks = _approx_tokens(para)
        if header_re.match(para) and toks < 20:
            section_header = para

        if current_tokens + toks > max_tokens and current_paras:
            flush()

        current_paras.append(para)
        current_tokens += toks

    flush()
    return chunks


# ── Full ingestion pipeline ────────────────────────────────────────────────────

def _split_into_sub_documents(text: str) -> list[tuple[str, str]]:
    """
    Each policy PDF may contain several policies (TEP-001, TEP-002 …).
    Split on 'Document: XXX-NNN' headers and return [(doc_id, text)] pairs.
    """
    parts = re.split(r'(?=\bDocument:\s*[\w-]+)', text)
    results = []
    for part in parts:
        if not part.strip():
            continue
        m = _DOC_ID_RE.search(part[:200])
        did = m.group(1) if m else "UNKNOWN"
        results.append((did, part))
    return results or [("UNKNOWN", text)]


def index_policies(force: bool = False) -> int:
    """
    Index all policy PDFs into ChromaDB.
    Returns number of chunks added.
    """
    collection = get_collection()
    db = SessionLocal()

    try:
        existing = db.query(PolicyChunk).count()
        if existing > 0 and not force:
            log.info("Policy index already has %d chunks — skipping.", existing)
            return existing

        if force:
            collection.delete(where={"source_file": {"$ne": "__none__"}})
            db.query(PolicyChunk).delete()
            db.commit()

        embedder = _get_embedder()
        policy_dir = config.POLICIES_DIR
        pdf_files = sorted(policy_dir.glob("*.pdf"))
        log.info("Indexing %d policy PDFs …", len(pdf_files))

        all_chunks: list[dict] = []
        for pdf_path in pdf_files:
            raw_text = extract_pdf_text(pdf_path)
            sub_docs = _split_into_sub_documents(raw_text)
            for doc_id, doc_text in sub_docs:
                chunks = chunk_document(doc_text, pdf_path.name, doc_id)
                all_chunks.extend(chunks)

        if not all_chunks:
            log.warning("No chunks extracted from policies.")
            return 0

        texts = [c["text"] for c in all_chunks]
        log.info("Embedding %d chunks …", len(texts))
        embeddings = embedder.encode(texts, batch_size=32, show_progress_bar=False, normalize_embeddings=True)

        ids, docs, metas, embeds = [], [], [], []
        db_rows = []
        for i, (chunk, emb) in enumerate(zip(all_chunks, embeddings)):
            cid = f"chunk_{i}"
            ids.append(cid)
            docs.append(chunk["text"])
            metas.append({
                "source_file": chunk["source_file"],
                "doc_id": chunk["doc_id"],
                "section_header": chunk.get("section_header", ""),
                "chunk_index": chunk["chunk_index"],
            })
            embeds.append(emb.tolist())
            db_rows.append(PolicyChunk(
                source_file=chunk["source_file"],
                doc_id=chunk["doc_id"],
                chunk_index=chunk["chunk_index"],
                text=chunk["text"],
                chroma_id=cid,
            ))

        # Upsert in batches
        batch_size = 100
        for start in range(0, len(ids), batch_size):
            end = start + batch_size
            collection.upsert(
                ids=ids[start:end],
                documents=docs[start:end],
                metadatas=metas[start:end],
                embeddings=embeds[start:end],
            )

        db.bulk_save_objects(db_rows)
        db.commit()
        log.info("Indexed %d policy chunks.", len(all_chunks))
        return len(all_chunks)

    finally:
        db.close()
