import uuid
from datetime import datetime, timezone
from typing import Literal
from pydantic import BaseModel, Field


class CompanyIdentifiers(BaseModel):
    company_name: str | None = None
    trading_name: str | None = None
    company_registration_number: str | None = None
    vat_number: str | None = None
    country_of_incorporation: str | None = None


class ContactDetails(BaseModel):
    primary_contact_name: str | None = None
    primary_contact_email: str | None = None
    primary_contact_phone: str | None = None
    company_address_line1: str | None = None
    company_address_city: str | None = None
    company_address_postcode: str | None = None
    company_address_country: str | None = None


class BankingDetails(BaseModel):
    bank_name: str | None = None
    account_holder_name: str | None = None
    sort_code: str | None = None
    account_number: str | None = None
    iban: str | None = None
    swift_bic: str | None = None


class ComplianceDocuments(BaseModel):
    has_gdpr_dpa: bool | None = None
    has_iso_27001: bool | None = None
    has_cyber_essentials: bool | None = None
    has_cyber_essentials_plus: bool | None = None
    has_public_liability_insurance: bool | None = None
    public_liability_amount_gbp: float | None = None
    insurance_expiry_date: str | None = None
    has_professional_indemnity: bool | None = None
    professional_indemnity_amount_gbp: float | None = None
    has_cyber_liability: bool | None = None
    cyber_liability_amount_gbp: float | None = None
    has_employer_liability: bool | None = None
    employer_liability_amount_gbp: float | None = None
    has_modern_slavery_declaration: bool | None = None
    has_supplier_code_of_conduct: bool | None = None


class ServiceDetails(BaseModel):
    service_category: str | None = None
    service_description: str | None = None
    contract_value_gbp: float | None = None
    contract_start_date: str | None = None
    contract_end_date: str | None = None
    payment_terms_days: int | None = None
    currency: str | None = "GBP"


class VendorExtraction(BaseModel):
    extraction_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source_filename: str = ""
    source_document_type: Literal["pdf", "image", "csv", "txt", "unknown"] = "unknown"
    extracted_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    company: CompanyIdentifiers = Field(default_factory=CompanyIdentifiers)
    contact: ContactDetails = Field(default_factory=ContactDetails)
    banking: BankingDetails = Field(default_factory=BankingDetails)
    compliance: ComplianceDocuments = Field(default_factory=ComplianceDocuments)
    services: ServiceDetails = Field(default_factory=ServiceDetails)

    field_confidence_scores: dict[str, float] = Field(default_factory=dict)
    overall_confidence_score: float = 0.0

    rag_validation_flags: list[str] = Field(default_factory=list)
    rag_enrichment_notes: str | None = None
    category_tier: str | None = None

    routing_decision: Literal["AUTO_APPROVE", "FLAG_FOR_REVIEW"] | None = None
    routing_reason: str | None = None
    routing_flags: list[str] = Field(default_factory=list)
    review_priority: Literal["HIGH", "MEDIUM", "LOW"] | None = None


class VendorRecordResponse(BaseModel):
    id: str
    company_name: str
    service_category: str | None
    contract_value_gbp: float | None
    overall_confidence_score: float | None
    status: str
    created_at: str
    routing_flags: str | None
    category_tier: str | None

    class Config:
        from_attributes = True


class VendorListResponse(BaseModel):
    items: list[VendorRecordResponse]
    total: int
    page: int
    page_size: int
