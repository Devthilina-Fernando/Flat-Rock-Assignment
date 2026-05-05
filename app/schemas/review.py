from typing import Literal
from pydantic import BaseModel


class ReviewDecision(BaseModel):
    decision: Literal["APPROVE", "REJECT", "REQUEST_MORE_INFO"]
    reviewer_notes: str | None = None
    corrected_fields: dict | None = None


class ReviewQueueItemResponse(BaseModel):
    id: str
    company_name: str | None
    service_category: str | None
    contract_value_gbp: float | None
    sender_email: str | None
    routing_reason: str | None
    routing_flags: str | None
    review_priority: str | None
    overall_confidence_score: float | None
    status: str
    created_at: str
    raw_extraction_json: str | None = None

    class Config:
        from_attributes = True


class ReviewListResponse(BaseModel):
    items: list[ReviewQueueItemResponse]
    total: int
    page: int
    page_size: int


class ReviewStatsResponse(BaseModel):
    total: int
    pending: int
    approved: int
    rejected: int
    pending_by_priority: dict[str, int]
