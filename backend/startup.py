"""
On server start:
1. Create DB tables
2. Seed employees from the sample submissions' employee_info.json files
3. Index policy PDFs (if not already done)
4. Create necessary directories
"""
import json
import logging
from pathlib import Path

from backend.database import init_db, SessionLocal, Employee
from backend.services import policy_indexer
from backend.services.retrieval import invalidate_bm25
from backend import config

log = logging.getLogger(__name__)


def seed_employees():
    """Load all employee_info.json files from sample submissions into the DB."""
    db = SessionLocal()
    try:
        submissions_dir = config.SUBMISSIONS_DIR
        if not submissions_dir.exists():
            log.warning("Submissions dir not found: %s", submissions_dir)
            return

        seeded = 0
        for subm_dir in sorted(submissions_dir.iterdir()):
            info_path = subm_dir / "employee_info.json"
            if not info_path.exists():
                continue
            data = json.loads(info_path.read_text(encoding="utf-8"))
            emp_id = data.get("employee_id") or data.get("id")
            if not emp_id:
                continue
            existing = db.query(Employee).filter(Employee.id == emp_id).first()
            if existing:
                continue  # already seeded

            emp = Employee(
                id=emp_id,
                name=data.get("name", ""),
                grade=data.get("grade", 0),
                title=data.get("title", ""),
                department=data.get("department", ""),
                manager_id=data.get("manager_id"),
                home_base=data.get("home_base", ""),
            )
            db.add(emp)
            seeded += 1

        db.commit()
        if seeded:
            log.info("Seeded %d employees.", seeded)
        else:
            log.info("All sample employees already in DB.")
    finally:
        db.close()


def ensure_directories():
    config.UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    Path(config.CHROMA_PATH).mkdir(parents=True, exist_ok=True)


def run_startup():
    log.info("Running startup checks …")
    ensure_directories()
    init_db()
    seed_employees()

    db = SessionLocal()
    try:
        from backend.database import PolicyChunk
        n_chunks = db.query(PolicyChunk).count()
    finally:
        db.close()

    if n_chunks == 0:
        log.info("Policy index empty — indexing now (this may take a minute) …")
        n = policy_indexer.index_policies(force=False)
        invalidate_bm25()
        log.info("Policy indexing complete: %d chunks.", n)
    else:
        log.info("Policy index has %d chunks — skipping re-index.", n_chunks)

    log.info("Startup complete.")
