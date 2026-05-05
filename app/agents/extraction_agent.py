import json
import uuid
from datetime import datetime, timezone
from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential
from app.config import get_settings
from app.utils.logging_config import get_logger

logger = get_logger(__name__)

EXTRACTION_MODEL = "gpt-4o"
MAX_TEXT_CHARS = 48_000  # chunk threshold
CHUNK_SIZE = 44_000
CHUNK_OVERLAP = 2_000

SYSTEM_PROMPT = """You are an expert procurement document analyst for a UK-based enterprise technology firm.
Your task is to extract vendor/supplier onboarding information from documents.

Rules:
1. Extract ONLY information explicitly stated in the document. Do not infer or fabricate.
2. For any field not present in the document, return null — never guess.
3. UK company registration numbers are 8 digits (e.g., 12345678).
   UK VAT numbers follow format GB + 9 digits (e.g., GB 123 4567 89).
   UK sort codes follow XX-XX-XX pattern. Account numbers are 8 digits.
4. Dates must be returned in ISO 8601 format (YYYY-MM-DD) where the full date is known.
5. Monetary values must be numeric (no currency symbols). Assume GBP unless stated.
6. For boolean compliance fields: return true only if the document explicitly confirms
   presence/possession of that certificate/agreement.
7. For each field you extract, provide a confidence score between 0.0 and 1.0:
   - 1.0: Explicitly and unambiguously stated
   - 0.7–0.9: Stated but requires minor interpretation
   - 0.4–0.6: Inferred or partially stated
   - 0.0–0.3: Very uncertain or conflicting information
8. contract_value_gbp should be the annual value in GBP as a number.
9. payment_terms_days should be an integer (e.g., 30 for Net 30).
"""

SCHEMA_DESCRIPTION = """
Return a JSON object with EXACTLY this structure (use null for missing fields):
{
  "company": {
    "company_name": string | null,
    "trading_name": string | null,
    "company_registration_number": string | null,
    "vat_number": string | null,
    "country_of_incorporation": string | null
  },
  "contact": {
    "primary_contact_name": string | null,
    "primary_contact_email": string | null,
    "primary_contact_phone": string | null,
    "company_address_line1": string | null,
    "company_address_city": string | null,
    "company_address_postcode": string | null,
    "company_address_country": string | null
  },
  "banking": {
    "bank_name": string | null,
    "account_holder_name": string | null,
    "sort_code": string | null,
    "account_number": string | null,
    "iban": string | null,
    "swift_bic": string | null
  },
  "compliance": {
    "has_gdpr_dpa": boolean | null,
    "has_iso_27001": boolean | null,
    "has_cyber_essentials": boolean | null,
    "has_cyber_essentials_plus": boolean | null,
    "has_public_liability_insurance": boolean | null,
    "public_liability_amount_gbp": number | null,
    "insurance_expiry_date": string | null,
    "has_professional_indemnity": boolean | null,
    "professional_indemnity_amount_gbp": number | null,
    "has_cyber_liability": boolean | null,
    "cyber_liability_amount_gbp": number | null,
    "has_employer_liability": boolean | null,
    "employer_liability_amount_gbp": number | null,
    "has_modern_slavery_declaration": boolean | null,
    "has_supplier_code_of_conduct": boolean | null
  },
  "services": {
    "service_category": string | null,
    "service_description": string | null,
    "contract_value_gbp": number | null,
    "contract_start_date": string | null,
    "contract_end_date": string | null,
    "payment_terms_days": integer | null,
    "currency": string | null
  },
  "field_confidence_scores": {
    "company.company_name": number,
    "company.company_registration_number": number,
    "company.vat_number": number,
    "contact.primary_contact_email": number,
    "contact.primary_contact_name": number,
    "contact.company_address_postcode": number,
    "banking.sort_code": number,
    "banking.account_number": number,
    "banking.account_holder_name": number,
    "services.service_category": number,
    "services.contract_value_gbp": number,
    "services.payment_terms_days": number,
    "compliance.has_public_liability_insurance": number,
    "compliance.public_liability_amount_gbp": number,
    "compliance.insurance_expiry_date": number
  }
}
"""


def _build_user_prompt(filename: str, doc_type: str, sender_email: str, text: str) -> str:
    return f"""Document filename: {filename}
Document type: {doc_type}
Sender email: {sender_email}

{SCHEMA_DESCRIPTION}

--- DOCUMENT CONTENT ---
{text}
--- END DOCUMENT ---

Extract all vendor onboarding information from the above document.
Return valid JSON matching the schema above exactly. Use null for any field not found.
"""


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def _call_openai(client: OpenAI, messages: list) -> dict:
    response = client.chat.completions.create(
        model=EXTRACTION_MODEL,
        messages=messages,
        temperature=0,
        response_format={"type": "json_object"},
        max_tokens=4096,
    )
    return json.loads(response.choices[0].message.content)


def _merge_extractions(extractions: list[dict]) -> dict:
    """Merge multi-chunk extractions: keep highest-confidence value per field."""
    if len(extractions) == 1:
        return extractions[0]

    merged = extractions[0].copy()
    all_scores: dict[str, float] = dict(extractions[0].get("field_confidence_scores", {}))

    for ext in extractions[1:]:
        scores = ext.get("field_confidence_scores", {})
        for section in ("company", "contact", "banking", "compliance", "services"):
            src = ext.get(section, {})
            dst = merged.get(section, {})
            for field, val in src.items():
                key = f"{section}.{field}"
                new_score = scores.get(key, 0.0)
                old_score = all_scores.get(key, 0.0)
                if val is not None and new_score > old_score:
                    dst[field] = val
                    all_scores[key] = new_score
            merged[section] = dst

    merged["field_confidence_scores"] = all_scores
    return merged


def extract_vendor_data(
    file_bytes_or_text: str,
    filename: str,
    doc_type: str,
    sender_email: str,
) -> dict:
    """
    Run the extraction agent on document text.
    Returns a flat dict ready to be overlaid onto a VendorExtraction.
    """
    logger.info("Extraction agent started", filename=filename, doc_type=doc_type,
                sender_email=sender_email, chars=len(file_bytes_or_text),
                model=EXTRACTION_MODEL)

    settings = get_settings()
    client = OpenAI(api_key=settings.openai_api_key)
    text = file_bytes_or_text

    if len(text) > MAX_TEXT_CHARS:
        chunks = []
        start = 0
        while start < len(text):
            end = min(start + CHUNK_SIZE, len(text))
            chunks.append(text[start:end])
            start += CHUNK_SIZE - CHUNK_OVERLAP

        logger.info("Document exceeds single-chunk limit — splitting",
                    total_chars=len(text), chunk_count=len(chunks),
                    chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP)
        extractions = []
        for i, chunk in enumerate(chunks):
            logger.info("Calling OpenAI for chunk", chunk=i + 1, total=len(chunks),
                        chunk_chars=len(chunk))
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": _build_user_prompt(
                    filename, doc_type, sender_email, chunk
                )},
            ]
            result = _call_openai(client, messages)
            extractions.append(result)
            logger.info("Chunk extraction complete", chunk=i + 1, total=len(chunks))

        logger.info("Merging chunk extractions", chunks=len(extractions))
        raw = _merge_extractions(extractions)
        logger.info("Merge complete")
    else:
        logger.info("Single-chunk extraction", chars=len(text))
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _build_user_prompt(
                filename, doc_type, sender_email, text
            )},
        ]
        logger.info("Calling OpenAI", model=EXTRACTION_MODEL)
        raw = _call_openai(client, messages)
        logger.info("OpenAI call complete")

    raw["extraction_id"] = str(uuid.uuid4())
    raw["source_filename"] = filename
    raw["source_document_type"] = doc_type
    raw["extracted_at"] = datetime.now(timezone.utc).isoformat()

    company_name = raw.get("company", {}).get("company_name")
    scores = raw.get("field_confidence_scores", {})
    logger.info("Extraction agent complete", filename=filename, doc_type=doc_type,
                company_name=company_name,
                extraction_id=raw["extraction_id"],
                fields_extracted=sum(1 for v in scores.values() if v and v > 0))
    return raw
