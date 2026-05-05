from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.db import crud
from app.schemas.vendor import VendorListResponse, VendorRecordResponse

router = APIRouter()


@router.get("", response_model=VendorListResponse)
def list_vendors(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    category: str | None = Query(None),
    status: str | None = Query(None),
    db: Session = Depends(get_db),
):
    items, total = crud.get_vendors(db, page=page, page_size=page_size,
                                    category=category, status=status)
    return VendorListResponse(
        items=[VendorRecordResponse.model_validate(v) for v in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{vendor_id}")
def get_vendor(vendor_id: str, db: Session = Depends(get_db)):
    v = crud.get_vendor(db, vendor_id)
    if not v:
        raise HTTPException(status_code=404, detail="Vendor not found")
    return {
        "id": v.id, "status": v.status, "created_at": v.created_at,
        "source_filename": v.source_filename,
        "company_name": v.company_name, "trading_name": v.trading_name,
        "company_registration_number": v.company_registration_number,
        "vat_number": v.vat_number, "country_of_incorporation": v.country_of_incorporation,
        "primary_contact_name": v.primary_contact_name,
        "primary_contact_email": v.primary_contact_email,
        "company_address_postcode": v.company_address_postcode,
        "company_address_country": v.company_address_country,
        "bank_name": v.bank_name, "account_holder_name": v.account_holder_name,
        "sort_code": v.sort_code, "account_number": v.account_number,
        "iban": v.iban, "swift_bic": v.swift_bic,
        "service_category": v.service_category, "service_description": v.service_description,
        "contract_value_gbp": v.contract_value_gbp,
        "contract_start_date": v.contract_start_date, "contract_end_date": v.contract_end_date,
        "payment_terms_days": v.payment_terms_days, "currency": v.currency,
        "has_gdpr_dpa": v.has_gdpr_dpa, "has_iso_27001": v.has_iso_27001,
        "has_cyber_essentials": v.has_cyber_essentials,
        "has_public_liability_insurance": v.has_public_liability_insurance,
        "public_liability_amount_gbp": v.public_liability_amount_gbp,
        "insurance_expiry_date": v.insurance_expiry_date,
        "has_professional_indemnity": v.has_professional_indemnity,
        "professional_indemnity_amount_gbp": v.professional_indemnity_amount_gbp,
        "category_tier": v.category_tier,
        "overall_confidence_score": v.overall_confidence_score,
        "rag_validation_flags": v.rag_validation_flags,
        "rag_enrichment_notes": v.rag_enrichment_notes,
        "routing_flags": v.routing_flags,
    }
