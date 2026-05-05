import uuid
from datetime import datetime, timezone
from sqlalchemy import Boolean, Column, Float, Integer, String, Text
from app.db.base import Base


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uuid() -> str:
    return str(uuid.uuid4())


class VendorRecord(Base):
    __tablename__ = "vendor_records"

    id = Column(String, primary_key=True, default=_uuid)
    extraction_id = Column(String, unique=True, nullable=False)
    source_filename = Column(String)

    # Company identity
    company_name = Column(String, nullable=False)
    trading_name = Column(String)
    company_registration_number = Column(String)
    vat_number = Column(String)
    country_of_incorporation = Column(String)

    # Contact
    primary_contact_name = Column(String)
    primary_contact_email = Column(String)
    company_address_postcode = Column(String)
    company_address_country = Column(String)

    # Banking
    bank_name = Column(String)
    account_holder_name = Column(String)
    sort_code = Column(String)
    account_number = Column(String)
    iban = Column(String)
    swift_bic = Column(String)

    # Services
    service_category = Column(String)
    service_description = Column(Text)
    contract_value_gbp = Column(Float)
    contract_start_date = Column(String)
    contract_end_date = Column(String)
    payment_terms_days = Column(Integer)
    currency = Column(String, default="GBP")

    # Compliance flags
    has_gdpr_dpa = Column(Boolean)
    has_iso_27001 = Column(Boolean)
    has_cyber_essentials = Column(Boolean)
    has_public_liability_insurance = Column(Boolean)
    public_liability_amount_gbp = Column(Float)
    insurance_expiry_date = Column(String)
    has_professional_indemnity = Column(Boolean)
    professional_indemnity_amount_gbp = Column(Float)

    # RAG & confidence (stored as JSON strings)
    rag_validation_flags = Column(Text)       # JSON array
    rag_enrichment_notes = Column(Text)
    category_tier = Column(String)
    overall_confidence_score = Column(Float)
    field_confidence_scores = Column(Text)    # JSON object
    routing_flags = Column(Text)              # JSON array

    # Status & audit
    status = Column(String, default="ACTIVE")
    created_at = Column(String, nullable=False, default=_now)

    raw_extraction_json = Column(Text)


class ReviewQueueItem(Base):
    __tablename__ = "review_queue"

    id = Column(String, primary_key=True, default=_uuid)
    extraction_id = Column(String, unique=True, nullable=False)

    # Denormalised display fields
    company_name = Column(String)
    service_category = Column(String)
    contract_value_gbp = Column(Float)
    sender_email = Column(String)

    # Routing context
    routing_reason = Column(String)
    routing_flags = Column(Text)              # JSON array
    review_priority = Column(String)
    overall_confidence_score = Column(Float)

    raw_extraction_json = Column(Text)

    # Queue management
    status = Column(String, default="PENDING")

    # Decision
    decision = Column(String)
    reviewer_notes = Column(Text)
    corrected_fields = Column(Text)           # JSON object

    # Audit
    created_at = Column(String, nullable=False, default=_now)
    source_filename = Column(String)
