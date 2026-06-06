import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, selectinload

from backend.database import get_db, LineItem, Override
from backend.models import LineItemOut, OverrideCreate, OverrideOut

router = APIRouter(prefix="/api/line_items", tags=["line_items"])


def _load_item(db: Session, item_id: str) -> LineItem:
    item = (
        db.query(LineItem)
        .options(selectinload(LineItem.overrides))
        .filter(LineItem.id == item_id)
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="Line item not found")
    return item


@router.get("/{item_id}", response_model=LineItemOut)
def get_line_item(item_id: str, db: Session = Depends(get_db)):
    return _load_item(db, item_id)


@router.post("/{item_id}/override", response_model=OverrideOut, status_code=201)
def create_override(item_id: str, data: OverrideCreate, db: Session = Depends(get_db)):
    item = _load_item(db, item_id)
    override = Override(
        id=str(uuid.uuid4()),
        line_item_id=item_id,
        reviewer=data.reviewer,
        original_verdict=item.verdict,
        new_verdict=data.new_verdict,
        comment=data.comment,
        created_at=datetime.utcnow(),
    )
    # Update the line item's verdict to reflect the override
    item.verdict = data.new_verdict
    db.add(override)
    db.commit()
    db.refresh(override)
    return override
