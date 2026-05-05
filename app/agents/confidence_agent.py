import re
from datetime import date
from app.utils.logging_config import get_logger

TODAY = date.today()

logger = get_logger(__name__)

# Weighted fields for overall confidence calculation
FIELD_WEIGHTS: dict[str, float] = {
    "company.company_name": 0.15,
    "company.company_registration_number": 0.12,
    "company.vat_number": 0.03,
    "company.country_of_incorporation": 0.02,
    "contact.primary_contact_email": 0.06,
    "contact.primary_contact_name": 0.04,
    "contact.company_address_postcode": 0.03,
    "banking.sort_code": 0.10,
    "banking.account_number": 0.10,
    "banking.account_holder_name": 0.06,
    "services.service_category": 0.08,
    "services.contract_value_gbp": 0.07,
    "services.payment_terms_days": 0.04,
    "compliance.has_public_liability_insurance": 0.03,
    "compliance.public_liability_amount_gbp": 0.03,
    "compliance.insurance_expiry_date": 0.04,
}

# Format validators: (regex_or_callable, bonus_if_match, penalty_if_mismatch)
_SORT_CODE_RE = re.compile(r"^\d{2}-\d{2}-\d{2}$")
_ACCOUNT_NO_RE = re.compile(r"^\d{8}$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_UK_POSTCODE_RE = re.compile(
    r"^[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}$", re.IGNORECASE
)
_UK_COMPANY_RE = re.compile(r"^\d{8}$")
_UK_VAT_RE = re.compile(r"^GB\s?\d{3}\s?\d{4}\s?\d{2}$", re.IGNORECASE)

FORMAT_VALIDATORS = [
    ("banking.sort_code", _SORT_CODE_RE, 0.10, -0.30),
    ("banking.account_number", _ACCOUNT_NO_RE, 0.10, -0.30),
    ("contact.primary_contact_email", _EMAIL_RE, 0.05, -0.20),
    ("contact.company_address_postcode", _UK_POSTCODE_RE, 0.05, 0.0),
    ("company.company_registration_number", _UK_COMPANY_RE, 0.10, -0.30),
    ("company.vat_number", _UK_VAT_RE, 0.05, 0.0),
]

# Critical flags that force FLAG_FOR_REVIEW regardless of confidence
CRITICAL_FLAGS = {
    "CATEGORY_NOT_APPROVED",
    "INSURANCE_EXPIRED",
    "PAYMENT_TERMS_EXCEED_LIMIT",
}


def _get_nested(extraction: dict, dotted_key: str):
    """Get value from nested dict using dot-notation key."""
    parts = dotted_key.split(".")
    obj = extraction
    for part in parts:
        if not isinstance(obj, dict):
            return None
        obj = obj.get(part)
    return obj


def calculate_confidence(extraction: dict) -> dict:
    """
    Calculate overall and per-field confidence scores.
    Applies format validation bonuses/penalties.
    Returns updated extraction dict with overall_confidence_score set.
    """
    company_name = extraction.get("company", {}).get("company_name", "unknown")
    logger.info("Calculating confidence score", company=company_name)

    raw_scores: dict[str, float] = extraction.get("field_confidence_scores", {})

    weighted_sum = 0.0
    total_weight = 0.0
    zero_fields = []

    for field, weight in FIELD_WEIGHTS.items():
        score = raw_scores.get(field, 0.0)
        value = _get_nested(extraction, field)
        if value is None:
            score = 0.0
            zero_fields.append(field)
        weighted_sum += score * weight
        total_weight += weight

    base_confidence = weighted_sum / total_weight if total_weight > 0 else 0.0

    if zero_fields:
        logger.info("Fields scoring zero (null or missing)", fields=zero_fields)

    # Apply format validation adjustments
    adjustments = 0.0
    format_bonuses = []
    format_penalties = []
    for field, pattern, bonus, penalty in FORMAT_VALIDATORS:
        value = _get_nested(extraction, field)
        if value is None:
            continue
        val_str = str(value).strip()
        if pattern.match(val_str):
            adjustments += bonus
            format_bonuses.append(field)
        elif penalty != 0.0:
            adjustments += penalty
            format_penalties.append(field)

    overall = max(0.0, min(1.0, base_confidence + adjustments))
    extraction["overall_confidence_score"] = round(overall, 4)

    logger.info("Confidence score calculated",
                company=company_name,
                base_confidence=round(base_confidence, 4),
                format_adjustments=round(adjustments, 4),
                overall_confidence=round(overall, 4),
                format_bonuses=format_bonuses,
                format_penalties=format_penalties)
    return extraction


def determine_routing(extraction: dict) -> dict:
    """
    Apply the routing decision tree.
    Sets routing_decision, routing_reason, routing_flags, review_priority.
    """
    company_name = extraction.get("company", {}).get("company_name", "unknown")
    confidence = extraction.get("overall_confidence_score", 0.0)
    rag_flags: list[str] = extraction.get("rag_validation_flags", [])
    category_tier = extraction.get("category_tier", "UNKNOWN")
    services = extraction.get("services", {})
    banking = extraction.get("banking", {})
    compliance = extraction.get("compliance", {})

    contract_value = services.get("contract_value_gbp") or 0.0
    payment_terms = services.get("payment_terms_days") or 0

    logger.info("Determining routing", company=company_name,
                confidence=confidence, category_tier=category_tier,
                contract_value=contract_value, payment_terms=payment_terms,
                rag_flags=rag_flags)

    routing_flags: list[str] = list(rag_flags)  # start with RAG flags
    flag_reasons: list[str] = []
    priority = "LOW"

    # ── 1. Critical flags force review ──────────────────────────────────────
    for flag in CRITICAL_FLAGS:
        if flag in routing_flags:
            flag_reasons.append(flag)

    # ── 2. Category checks ───────────────────────────────────────────────────
    if category_tier == "NOT_APPROVED":
        if "CATEGORY_NOT_APPROVED" not in routing_flags:
            routing_flags.append("CATEGORY_NOT_APPROVED")
        flag_reasons.append("CATEGORY_NOT_APPROVED")
        priority = "HIGH"
    elif category_tier == "TIER_3":
        if "CATEGORY_TIER_3_ENHANCED_DUE_DILIGENCE" not in routing_flags:
            routing_flags.append("CATEGORY_TIER_3_ENHANCED_DUE_DILIGENCE")
        flag_reasons.append("CATEGORY_TIER_3_ENHANCED_DUE_DILIGENCE")
        priority = "MEDIUM"

    # ── 3. Contract value threshold ──────────────────────────────────────────
    if contract_value > 100_000:
        flag = "HIGH_VALUE_CONTRACT_BOARD_APPROVAL"
        if flag not in routing_flags:
            routing_flags.append(flag)
        flag_reasons.append(flag)
        priority = "HIGH"

    # ── 4. Payment terms ─────────────────────────────────────────────────────
    if payment_terms > 60:
        flag = "PAYMENT_TERMS_EXCEED_LIMIT"
        if flag not in routing_flags:
            routing_flags.append(flag)
        flag_reasons.append(flag)

    # ── 5. Banking completeness ──────────────────────────────────────────────
    has_banking = bool(banking.get("sort_code") or banking.get("iban"))
    if not has_banking:
        flag = "MISSING_BANK_DETAILS"
        if flag not in routing_flags:
            routing_flags.append(flag)
        flag_reasons.append(flag)

    # ── 6. Insurance issues ──────────────────────────────────────────────────
    # Direct date check on extracted insurance_expiry_date (catches cases RAG misses)
    expiry_str = compliance.get("insurance_expiry_date")
    if expiry_str and "INSURANCE_EXPIRED" not in routing_flags:
        try:
            expiry_date = date.fromisoformat(expiry_str[:10])
            if expiry_date < TODAY:
                routing_flags.append("INSURANCE_EXPIRED")
                flag_reasons.append("INSURANCE_EXPIRED")
        except ValueError:
            pass

    if "INSURANCE_EXPIRED" in routing_flags:
        priority = "HIGH"
        if "INSURANCE_EXPIRED" not in flag_reasons:
            flag_reasons.append("INSURANCE_EXPIRED")
    if "INSURANCE_EXPIRING_SOON" in routing_flags and priority == "LOW":
        priority = "LOW"

    # ── 7. Missing critical documents → at least MEDIUM ─────────────────────
    medium_triggers = {"MISSING_BANK_DETAILS", "MISSING_DPA",
                       "INSURANCE_BELOW_MINIMUM_PL", "INSURANCE_BELOW_MINIMUM_PI"}
    if routing_flags and medium_triggers.intersection(routing_flags) and priority == "LOW":
        priority = "MEDIUM"

    # ── 8. Confidence gate ───────────────────────────────────────────────────
    if confidence < 0.60:
        flag = "LOW_CONFIDENCE_EXTRACTION"
        if flag not in routing_flags:
            routing_flags.append(flag)
        flag_reasons.append(flag)
        if priority == "LOW":
            priority = "MEDIUM"

    # ── 9. Determine final decision ──────────────────────────────────────────
    blocking_flags = set(routing_flags) - {"INSURANCE_EXPIRING_SOON"}
    auto_approve_conditions = (
        confidence >= 0.80
        and len(blocking_flags) == 0
        and category_tier in ("TIER_1", "TIER_2")
        and has_banking
    )

    logger.info("Evaluating auto-approve conditions",
                company=company_name,
                confidence_ok=confidence >= 0.80,
                no_blocking_flags=len(blocking_flags) == 0,
                tier_ok=category_tier in ("TIER_1", "TIER_2"),
                has_banking=has_banking,
                blocking_flags=list(blocking_flags))

    if auto_approve_conditions:
        extraction["routing_decision"] = "AUTO_APPROVE"
        extraction["routing_reason"] = f"High confidence ({confidence:.2f}), all policy checks passed"
        extraction["routing_flags"] = routing_flags
        extraction["review_priority"] = None
        logger.info("Routing decision: AUTO_APPROVE", company=company_name,
                    confidence=confidence, category_tier=category_tier)
    else:
        extraction["routing_decision"] = "FLAG_FOR_REVIEW"
        primary_reason = flag_reasons[0] if flag_reasons else "REVIEW_REQUIRED"
        extraction["routing_reason"] = primary_reason
        extraction["routing_flags"] = routing_flags
        extraction["review_priority"] = priority
        logger.info("Routing decision: FLAG_FOR_REVIEW", company=company_name,
                    primary_reason=primary_reason, all_flags=routing_flags,
                    priority=priority)

    return extraction
