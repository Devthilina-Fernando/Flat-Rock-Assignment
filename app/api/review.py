from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.db import crud
from app.schemas.review import (
    ReviewDecision,
    ReviewListResponse,
    ReviewQueueItemResponse,
    ReviewStatsResponse,
)

router = APIRouter()


@router.get("/stats", response_model=ReviewStatsResponse)
def review_stats(db: Session = Depends(get_db)):
    return ReviewStatsResponse(**crud.get_review_stats(db))


@router.get("", response_model=ReviewListResponse)
def list_review_items(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    priority: str | None = Query(None),
    status: str | None = Query(None),
    db: Session = Depends(get_db),
):
    items, total = crud.get_review_items(db, page=page, page_size=page_size,
                                         priority=priority, status=status)
    return ReviewListResponse(
        items=[ReviewQueueItemResponse.model_validate(i) for i in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{review_id}", response_model=ReviewQueueItemResponse)
def get_review_item(review_id: str, db: Session = Depends(get_db)):
    item = crud.get_review_item(db, review_id)
    if not item:
        raise HTTPException(status_code=404, detail="Review item not found")
    return ReviewQueueItemResponse.model_validate(item)


@router.post("/{review_id}/decide")
def decide(review_id: str, body: ReviewDecision, db: Session = Depends(get_db)):
    import json, uuid
    item = crud.get_review_item(db, review_id)
    if not item:
        raise HTTPException(status_code=404, detail="Review item not found")
    if item.status != "PENDING":
        raise HTTPException(status_code=409, detail=f"Item already processed: {item.status}")

    # For APPROVE: create the vendor record FIRST so that if it fails the
    # review item status stays PENDING and the user can safely retry.
    if body.decision == "APPROVE":
        raw = json.loads(item.raw_extraction_json or "{}")
        if body.corrected_fields:
            for dotted_key, value in body.corrected_fields.items():
                parts = dotted_key.split(".", 1)
                if len(parts) == 2:
                    raw.setdefault(parts[0], {})[parts[1]] = value
        raw["routing_decision"] = "AUTO_APPROVE"
        raw["extraction_id"] = str(uuid.uuid4())  # fresh ID — avoids unique-constraint clash
        crud.create_vendor_record(db, raw)

    updated = crud.decide_review_item(
        db, review_id,
        decision=body.decision,
        reviewer_notes=body.reviewer_notes,
        corrected_fields=body.corrected_fields,
    )

    if body.decision == "APPROVE":
        return {"status": "approved", "message": "Vendor record created"}
    return {"status": updated.status.lower(), "decision": body.decision}
