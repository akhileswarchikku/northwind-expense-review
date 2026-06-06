import json
import logging
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, Query
from sqlalchemy.orm import Session, selectinload

from backend.database import get_db, Employee, Submission, LineItem
from backend.models import SubmissionCreate, SubmissionOut
from backend.services import receipt_extractor, reviewer
from backend import config

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/submissions", tags=["submissions"])


def _load_submission(db: Session, sid: str) -> Submission:
    sub = (
        db.query(Submission)
        .options(
            selectinload(Submission.employee),
            selectinload(Submission.line_items).selectinload(LineItem.overrides),
        )
        .filter(Submission.id == sid)
        .first()
    )
    if not sub:
        raise HTTPException(status_code=404, detail="Submission not found")
    return sub


@router.get("", response_model=List[SubmissionOut])
def list_submissions(
    employee_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    q = db.query(Submission).options(
        selectinload(Submission.employee),
        selectinload(Submission.line_items).selectinload(LineItem.overrides),
    )
    if employee_id:
        q = q.filter(Submission.employee_id == employee_id)
    if status:
        q = q.filter(Submission.status == status)
    return q.order_by(Submission.created_at.desc()).all()


@router.get("/{submission_id}", response_model=SubmissionOut)
def get_submission(submission_id: str, db: Session = Depends(get_db)):
    return _load_submission(db, submission_id)


@router.post("", response_model=SubmissionOut, status_code=201)
def create_submission(data: SubmissionCreate, db: Session = Depends(get_db)):
    emp = db.query(Employee).filter(Employee.id == data.employee_id).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    sub = Submission(
        id=str(uuid.uuid4()),
        employee_id=data.employee_id,
        trip_purpose=data.trip_purpose,
        trip_dates_start=data.trip_dates_start,
        trip_dates_end=data.trip_dates_end,
        status="pending",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(sub)
    db.commit()
    return _load_submission(db, sub.id)


@router.delete("/{submission_id}", status_code=204)
def delete_submission(submission_id: str, db: Session = Depends(get_db)):
    sub = db.query(Submission).filter(Submission.id == submission_id).first()
    if not sub:
        raise HTTPException(status_code=404, detail="Submission not found")
    db.delete(sub)
    db.commit()


@router.post("/{submission_id}/receipts", response_model=SubmissionOut)
async def upload_receipts(
    submission_id: str,
    files: List[UploadFile] = File(...),
    db: Session = Depends(get_db),
):
    """Upload one or more receipt files, extract data, and run the review pipeline."""
    sub = _load_submission(db, submission_id)
    emp = sub.employee

    # Save uploaded files
    upload_dir = config.UPLOADS_DIR / submission_id
    upload_dir.mkdir(parents=True, exist_ok=True)

    saved_paths: list[Path] = []
    for f in files:
        dest = upload_dir / (f.filename or f"receipt_{uuid.uuid4()}")
        with dest.open("wb") as buf:
            shutil.copyfileobj(f.file, buf)
        saved_paths.append(dest)

    # Extract + review each receipt
    employee_dict = {
        "id": emp.id,
        "name": emp.name,
        "grade": emp.grade,
        "title": emp.title,
        "department": emp.department,
        "home_base": emp.home_base,
    }

    for path in saved_paths:
        try:
            extracted = await receipt_extractor.extract_receipt(path)
        except Exception as exc:
            log.error("Extraction failed for %s: %s", path.name, exc)
            extracted = {
                "vendor": None, "date": None, "amount": None,
                "currency": "USD", "category": "other",
                "description": "Extraction error", "party_size": None,
                "alcohol_present": False, "line_items": [], "notes": str(exc),
                "file_type": "unknown", "raw_text": "",
            }

        try:
            verdict_data = await reviewer.review_line_item(
                item_data=extracted,
                employee=employee_dict,
                trip_purpose=sub.trip_purpose,
                trip_start=sub.trip_dates_start,
                trip_end=sub.trip_dates_end,
            )
        except Exception as exc:
            log.error("Review failed for %s: %s", path.name, exc)
            verdict_data = {
                "verdict": "flagged",
                "reasoning": f"Review error — manual check required. ({exc})",
                "policy_citations": [],
                "confidence": 0.1,
                "flags": ["review_error"],
            }

        li = LineItem(
            id=str(uuid.uuid4()),
            submission_id=submission_id,
            filename=path.name,
            file_type=extracted.get("file_type", "unknown"),
            raw_text=extracted.get("raw_text", ""),
            vendor=extracted.get("vendor"),
            date=extracted.get("date"),
            amount=extracted.get("amount"),
            currency=extracted.get("currency", "USD"),
            category=extracted.get("category"),
            description=extracted.get("description"),
            verdict=verdict_data.get("verdict"),
            reasoning=verdict_data.get("reasoning"),
            confidence=verdict_data.get("confidence"),
            policy_citations=json.dumps(verdict_data.get("policy_citations", [])),
            flags=json.dumps(verdict_data.get("flags", [])),
            created_at=datetime.utcnow(),
        )
        db.add(li)

    # Update submission status
    sub.updated_at = datetime.utcnow()
    _update_submission_status(db, sub)
    db.commit()

    return _load_submission(db, submission_id)


def _update_submission_status(db: Session, sub: Submission):
    items = db.query(LineItem).filter(LineItem.submission_id == sub.id).all()
    if not items:
        sub.status = "pending"
        return
    verdicts = {li.verdict for li in items}
    if "rejected" in verdicts:
        sub.status = "needs_review"
    elif "flagged" in verdicts:
        sub.status = "needs_review"
    else:
        sub.status = "reviewed"
