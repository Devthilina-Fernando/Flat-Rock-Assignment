import json
from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential
from app.config import get_settings
from app.rag.knowledge_base_loader import query_knowledge_base
from app.utils.logging_config import get_logger

logger = get_logger(__name__)

RAG_MODEL = "gpt-4o"

RAG_ENRICHMENT_PROMPT = """You are a senior procurement compliance analyst at a UK enterprise technology firm.
You have received extracted vendor onboarding data and retrieved relevant policy passages from your internal knowledge base.

Your tasks:
1. Identify compliance gaps — list flags for each issue found.
   Use these exact flag names where applicable:
   - CATEGORY_NOT_APPROVED — vendor category is on the Not Approved list
   - CATEGORY_TIER_3_ENHANCED_DUE_DILIGENCE — vendor is in a Tier 3 category
   - INSURANCE_EXPIRED — public liability or PI insurance expiry date is in the past
   - INSURANCE_EXPIRING_SOON — any insurance expiring within 60 days of today (2026-05-04)
   - INSURANCE_BELOW_MINIMUM_PL — public liability coverage below required minimum
   - INSURANCE_BELOW_MINIMUM_PI — professional indemnity coverage below required minimum for IT/professional services
   - MISSING_DPA — vendor processes/accesses personal data but no DPA confirmed
   - MISSING_ISO27001_OR_CYBER_ESSENTIALS_PLUS — IT vendor contract >£15,000 lacks required security certification
   - PAYMENT_TERMS_EXCEED_LIMIT — payment terms exceed Net 60 days
   - HIGH_VALUE_CONTRACT_BOARD_APPROVAL — annual contract value OR total lifetime value exceeds £500,000
   - MISSING_BANK_DETAILS — no sort code and no IBAN found

2. List positive confirmations (what the vendor DOES meet).

3. Assign a category tier: TIER_1, TIER_2, TIER_3, NOT_APPROVED, or UNKNOWN.

4. Write a brief enrichment note summarising the overall compliance position.

Be precise. Only flag issues that are clearly evidenced by the policy passages and extracted data.
"""


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def _call_openai(client: OpenAI, messages: list) -> dict:
    response = client.chat.completions.create(
        model=RAG_MODEL,
        messages=messages,
        temperature=0,
        response_format={"type": "json_object"},
        max_tokens=2048,
    )
    return json.loads(response.choices[0].message.content)


def _run_rag_queries(extraction: dict) -> list[dict]:
    """Run 4 targeted ChromaDB queries and collect results."""
    services = extraction.get("services", {})
    compliance = extraction.get("compliance", {})
    banking = extraction.get("banking", {})
    company = extraction.get("company", {})

    service_category = services.get("service_category") or "unknown"
    service_desc = services.get("service_description") or "unknown"
    contract_value = services.get("contract_value_gbp") or 0
    payment_terms = services.get("payment_terms_days") or 0
    pl_amount = compliance.get("public_liability_amount_gbp") or 0
    pi_amount = compliance.get("professional_indemnity_amount_gbp") or 0
    insurance_expiry = compliance.get("insurance_expiry_date") or ""
    has_dpa = compliance.get("has_gdpr_dpa")
    company_name = company.get("company_name") or ""

    queries = [
        (
            f"Vendor category: {service_category}. Services: {service_desc}. "
            f"Is this category approved? Which tier does it belong to?",
            5,
        ),
        (
            f"Compliance requirements for {service_category} vendor with contract value £{contract_value}. "
            f"Payment terms {payment_terms} days. What documents and certifications are mandatory?",
            5,
        ),
        (
            f"Insurance requirements: public liability £{pl_amount:,.0f}, professional indemnity £{pi_amount:,.0f}, "
            f"insurance expiry {insurance_expiry}, contract value £{contract_value:,.0f}, "
            f"vendor category {service_category}. Are minimum coverage amounts met?",
            5,
        ),
        (
            f"Data protection requirements for vendor providing {service_desc}. "
            f"DPA signed: {has_dpa}. When is a Data Processing Agreement required?",
            4,
        ),
    ]

    logger.info("Running RAG queries against knowledge base",
                company=company_name, query_count=len(queries),
                service_category=service_category, contract_value=contract_value)

    all_chunks: list[dict] = []
    seen_texts: set[str] = set()
    for i, (query_text, n) in enumerate(queries, 1):
        logger.info("ChromaDB query", query_num=i, total=len(queries), n_results=n,
                    query_preview=query_text[:80])
        chunks = query_knowledge_base(query_text, n_results=n)
        new_chunks = [c for c in chunks if c["text"] not in seen_texts]
        for chunk in new_chunks:
            seen_texts.add(chunk["text"])
        all_chunks.extend(new_chunks)
        logger.info("ChromaDB query complete", query_num=i, hits=len(chunks),
                    new_unique=len(new_chunks), total_unique_so_far=len(all_chunks))

    logger.info("RAG queries complete", total_unique_chunks=len(all_chunks))
    return all_chunks


def enrich_with_rag(extraction: dict) -> dict:
    """
    Run RAG queries against the policy knowledge base and enrich the extraction
    with validation_flags, category_tier, and enrichment_notes.
    Returns the updated extraction dict.
    """
    company_name = extraction.get("company", {}).get("company_name", "unknown")
    logger.info("RAG enrichment agent started", company=company_name, model=RAG_MODEL)

    settings = get_settings()
    client = OpenAI(api_key=settings.openai_api_key)

    chunks = _run_rag_queries(extraction)
    if not chunks:
        logger.warning("No RAG chunks retrieved — skipping enrichment, "
                       "knowledge base may not be loaded", company=company_name)
        extraction["rag_validation_flags"] = []
        extraction["rag_enrichment_notes"] = "RAG unavailable — knowledge base may not be loaded."
        extraction["category_tier"] = "UNKNOWN"
        return extraction

    logger.info("Building RAG prompt", company=company_name,
                policy_chunks=len(chunks),
                sources=list({c["source_file"] for c in chunks}))

    policy_context = "\n\n---\n\n".join(
        f"[Source: {c['source_file']}]\n{c['text']}" for c in chunks
    )

    messages = [
        {"role": "system", "content": RAG_ENRICHMENT_PROMPT},
        {
            "role": "user",
            "content": (
                f"EXTRACTED VENDOR DATA:\n{json.dumps(extraction, indent=2)}\n\n"
                f"RETRIEVED POLICY PASSAGES:\n{policy_context}\n\n"
                "Return JSON with keys: validation_flags (array), positive_confirmations (array), "
                "category_tier (string), enrichment_notes (string)."
            ),
        },
    ]

    logger.info("Calling OpenAI for RAG compliance check", company=company_name,
                model=RAG_MODEL)
    result = _call_openai(client, messages)
    logger.info("OpenAI RAG call complete", company=company_name)

    extraction["rag_validation_flags"] = result.get("validation_flags", [])
    extraction["rag_enrichment_notes"] = result.get("enrichment_notes", "")
    extraction["category_tier"] = result.get("category_tier", "UNKNOWN")

    logger.info("RAG enrichment agent complete",
                company=company_name,
                category_tier=extraction["category_tier"],
                flags=extraction["rag_validation_flags"],
                positive_confirmations=result.get("positive_confirmations", []),
                chunks_used=len(chunks))
    return extraction
