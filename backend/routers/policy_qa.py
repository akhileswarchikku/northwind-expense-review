from fastapi import APIRouter
from backend.models import PolicyQARequest, PolicyQAResponse, IndexStatusResponse
from backend.services import reviewer, policy_indexer
from backend.database import SessionLocal, PolicyChunk

router = APIRouter(prefix="/api/policy", tags=["policy"])


@router.post("/qa", response_model=PolicyQAResponse)
async def policy_qa(req: PolicyQARequest):
    result = await reviewer.answer_policy_question(req.question)
    return PolicyQAResponse(**result)


@router.get("/index/status", response_model=IndexStatusResponse)
def index_status():
    db = SessionLocal()
    try:
        count = db.query(PolicyChunk).count()
        doc_ids = [r[0] for r in db.query(PolicyChunk.doc_id).distinct().all()]
        return IndexStatusResponse(indexed=count > 0, chunk_count=count, doc_ids=sorted(doc_ids))
    finally:
        db.close()


@router.post("/index/rebuild")
async def rebuild_index():
    n = policy_indexer.index_policies(force=True)
    # Invalidate BM25 cache so it rebuilds from fresh DB data
    from backend.services.retrieval import invalidate_bm25
    invalidate_bm25()
    return {"message": f"Indexed {n} chunks", "chunk_count": n}
