import json
import uuid
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from app.db.models import ReviewQueueItem, VendorRecord


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Vendor Records ─────────────────────────────────────────────────────────────

def create_vendor_record(db: Session, extraction: dict) -> VendorRecord:
    comp = extraction.get("company", {})
    contact = extraction.get("contact", {})
    banking = extraction.get("banking", {})
    services = extraction.get("services", {})
    compliance = extraction.get("compliance", {})

    record = VendorRecord(
        id=str(uuid.uuid4()),
        extraction_id=extraction.get("extraction_id", str(uuid.uuid4())),
        source_filename=extraction.get("source_filename", ""),
        company_name=comp.get("company_name") or "Unknown",
        trading_name=comp.get("trading_name"),
        company_registration_number=comp.get("company_registration_number"),
        vat_number=comp.get("vat_number"),
        country_of_incorporation=comp.get("country_of_incorporation"),
        primary_contact_name=contact.get("primary_contact_name"),
        primary_contact_email=contact.get("primary_contact_email"),
        company_address_postcode=contact.get("company_address_postcode"),
        company_address_country=contact.get("company_address_country"),
        bank_name=banking.get("bank_name"),
        account_holder_name=banking.get("account_holder_name"),
        sort_code=banking.get("sort_code"),
        account_number=banking.get("account_number"),
        iban=banking.get("iban"),
        swift_bic=banking.get("swift_bic"),
        service_category=services.get("service_category"),
        service_description=services.get("service_description"),
        contract_value_gbp=services.get("contract_value_gbp"),
        contract_start_date=services.get("contract_start_date"),
        contract_end_date=services.get("contract_end_date"),
        payment_terms_days=services.get("payment_terms_days"),
        currency=services.get("currency", "GBP"),
        has_gdpr_dpa=compliance.get("has_gdpr_dpa"),
        has_iso_27001=compliance.get("has_iso_27001"),
        has_cyber_essentials=compliance.get("has_cyber_essentials"),
        has_public_liability_insurance=compliance.get("has_public_liability_insurance"),
        public_liability_amount_gbp=compliance.get("public_liability_amount_gbp"),
        insurance_expiry_date=compliance.get("insurance_expiry_date"),
        has_professional_indemnity=compliance.get("has_professional_indemnity"),
        professional_indemnity_amount_gbp=compliance.get("professional_indemnity_amount_gbp"),
        rag_validation_flags=json.dumps(extraction.get("rag_validation_flags", [])),
        rag_enrichment_notes=extraction.get("rag_enrichment_notes"),
        category_tier=extraction.get("category_tier"),
        overall_confidence_score=extraction.get("overall_confidence_score", 0.0),
        field_confidence_scores=json.dumps(extraction.get("field_confidence_scores", {})),
        routing_flags=json.dumps(extraction.get("routing_flags", [])),
        status="ACTIVE",
        raw_extraction_json=json.dumps(extraction),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def get_vendors(db: Session, page: int = 1, page_size: int = 20,
                category: str | None = None, status: str | None = None):
    q = db.query(VendorRecord)
    if category:
        q = q.filter(VendorRecord.service_category.ilike(f"%{category}%"))
    if status:
        q = q.filter(VendorRecord.status == status)
    total = q.count()
    items = q.offset((page - 1) * page_size).limit(page_size).all()
    return items, total


def get_vendor(db: Session, vendor_id: str) -> VendorRecord | None:
    return db.query(VendorRecord).filter(VendorRecord.id == vendor_id).first()


# ── Review Queue ───────────────────────────────────────────────────────────────

def create_review_item(db: Session, extraction: dict, sender_email: str = "") -> ReviewQueueItem:
    item = ReviewQueueItem(
        id=str(uuid.uuid4()),
        extraction_id=extraction.get("extraction_id", str(uuid.uuid4())),
        company_name=extraction.get("company", {}).get("company_name"),
        service_category=extraction.get("services", {}).get("service_category"),
        contract_value_gbp=extraction.get("services", {}).get("contract_value_gbp"),
        sender_email=sender_email,
        routing_reason=extraction.get("routing_reason"),
        routing_flags=json.dumps(extraction.get("routing_flags", [])),
        review_priority=extraction.get("review_priority", "MEDIUM"),
        overall_confidence_score=extraction.get("overall_confidence_score", 0.0),
        raw_extraction_json=json.dumps(extraction),
        status="PENDING",
        source_filename=extraction.get("source_filename", ""),
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def get_review_items(db: Session, page: int = 1, page_size: int = 20,
                     priority: str | None = None, status: str | None = None):
    q = db.query(ReviewQueueItem)
    if priority:
        q = q.filter(ReviewQueueItem.review_priority == priority)
    if status:
        q = q.filter(ReviewQueueItem.status == status)
    else:
        q = q.filter(ReviewQueueItem.status == "PENDING")
    q = q.order_by(
        ReviewQueueItem.review_priority.asc(),
        ReviewQueueItem.created_at.asc()
    )
    total = q.count()
    items = q.offset((page - 1) * page_size).limit(page_size).all()
    return items, total


def get_review_item(db: Session, review_id: str) -> ReviewQueueItem | None:
    return db.query(ReviewQueueItem).filter(ReviewQueueItem.id == review_id).first()


def decide_review_item(db: Session, review_id: str, decision: str,
                       reviewer_notes: str | None = None,
                       corrected_fields: dict | None = None) -> ReviewQueueItem | None:
    item = get_review_item(db, review_id)
    if not item:
        return None
    item.decision = decision
    item.reviewer_notes = reviewer_notes
    item.corrected_fields = json.dumps(corrected_fields) if corrected_fields else None
    item.status = "APPROVED" if decision == "APPROVE" else (
        "REJECTED" if decision == "REJECT" else "INFO_REQUESTED"
    )
    db.commit()
    db.refresh(item)
    return item


def get_review_stats(db: Session) -> dict:
    total = db.query(ReviewQueueItem).count()
    pending = db.query(ReviewQueueItem).filter(ReviewQueueItem.status == "PENDING").count()
    approved = db.query(ReviewQueueItem).filter(ReviewQueueItem.status == "APPROVED").count()
    rejected = db.query(ReviewQueueItem).filter(ReviewQueueItem.status == "REJECTED").count()
    high = db.query(ReviewQueueItem).filter(
        ReviewQueueItem.review_priority == "HIGH",
        ReviewQueueItem.status == "PENDING"
    ).count()
    medium = db.query(ReviewQueueItem).filter(
        ReviewQueueItem.review_priority == "MEDIUM",
        ReviewQueueItem.status == "PENDING"
    ).count()
    low = db.query(ReviewQueueItem).filter(
        ReviewQueueItem.review_priority == "LOW",
        ReviewQueueItem.status == "PENDING"
    ).count()
    return {
        "total": total, "pending": pending, "approved": approved,
        "rejected": rejected,
        "pending_by_priority": {"HIGH": high, "MEDIUM": medium, "LOW": low},
    }
