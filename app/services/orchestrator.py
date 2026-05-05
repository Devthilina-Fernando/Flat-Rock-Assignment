"""
End-to-end pipeline: document text → extraction → RAG → confidence → routing → persistence.
"""
from sqlalchemy.orm import Session
from app.agents.extraction_agent import extract_vendor_data
from app.agents.rag_agent import enrich_with_rag
from app.agents.confidence_agent import calculate_confidence, determine_routing
from app.db import crud
from app.services.document_loader import load_document
import app.services.event_bus as event_bus
from app.utils.logging_config import get_logger

logger = get_logger(__name__)


def run_pipeline(
    file_bytes: bytes,
    filename: str,
    content_type: str,
    sender_email: str,
    db: Session,
) -> dict:
    """Synchronous pipeline. Returns the final extraction dict."""
    logger.info("Pipeline started", filename=filename, content_type=content_type,
                sender_email=sender_email)

    try:
        # ── Step 1: Text extraction ──────────────────────────────────────────
        logger.info("[1/6] Extracting text from document", filename=filename,
                    content_type=content_type, bytes=len(file_bytes))
        text, doc_type = load_document(file_bytes, content_type, filename)
        if not text.strip():
            raise ValueError(f"No text could be extracted from {filename}")
        logger.info("[1/6] Text extraction complete", filename=filename,
                    doc_type=doc_type, chars=len(text))

        # ── Step 2: GPT-4o field extraction ─────────────────────────────────
        logger.info("[2/6] Running GPT-4o extraction agent", filename=filename,
                    doc_type=doc_type, chars=len(text))
        extraction = extract_vendor_data(
            file_bytes_or_text=text,
            filename=filename,
            doc_type=doc_type,
            sender_email=sender_email,
        )
        logger.info("[2/6] Extraction complete",
                    company=extraction.get("company", {}).get("company_name"),
                    extraction_id=extraction.get("extraction_id"))

        # ── Step 3: RAG policy enrichment ────────────────────────────────────
        logger.info("[3/6] Running RAG policy enrichment",
                    company=extraction.get("company", {}).get("company_name"))
        extraction = enrich_with_rag(extraction)
        logger.info("[3/6] RAG enrichment complete",
                    category_tier=extraction.get("category_tier"),
                    rag_flags=extraction.get("rag_validation_flags"))

        # ── Step 4: Confidence scoring ───────────────────────────────────────
        logger.info("[4/6] Calculating confidence score")
        extraction = calculate_confidence(extraction)
        logger.info("[4/6] Confidence score calculated",
                    overall_confidence=extraction.get("overall_confidence_score"))

        # ── Step 5: Routing decision ─────────────────────────────────────────
        logger.info("[5/6] Determining routing decision",
                    confidence=extraction.get("overall_confidence_score"),
                    category_tier=extraction.get("category_tier"))
        extraction = determine_routing(extraction)
        logger.info("[5/6] Routing decided",
                    decision=extraction.get("routing_decision"),
                    reason=extraction.get("routing_reason"),
                    flags=extraction.get("routing_flags"),
                    priority=extraction.get("review_priority"))

        # ── Step 6: Persist to database ──────────────────────────────────────
        logger.info("[6/6] Persisting result to database",
                    routing_decision=extraction.get("routing_decision"))
        if extraction["routing_decision"] == "AUTO_APPROVE":
            record = crud.create_vendor_record(db, extraction)
            logger.info("[6/6] Vendor saved to vendor_records (AUTO_APPROVED)",
                        company=extraction.get("company", {}).get("company_name"),
                        record_id=record.id)
        else:
            item = crud.create_review_item(db, extraction, sender_email=sender_email)
            logger.info("[6/6] Vendor saved to review_queue (FLAG_FOR_REVIEW)",
                        company=extraction.get("company", {}).get("company_name"),
                        priority=extraction.get("review_priority"),
                        flags=extraction.get("routing_flags"),
                        review_id=item.id)

        logger.info("Pipeline complete", filename=filename,
                    decision=extraction.get("routing_decision"),
                    company=extraction.get("company", {}).get("company_name"))

        event_bus.publish({
            "type": "pipeline_complete",
            "company": (extraction.get("company") or {}).get("company_name", "Unknown"),
            "decision": extraction.get("routing_decision", "UNKNOWN"),
            "filename": filename,
            "sender": sender_email,
            "confidence": extraction.get("overall_confidence_score"),
            "priority": extraction.get("review_priority"),
        })

        return extraction

    except Exception as e:
        logger.error("Pipeline FAILED", filename=filename, error=str(e),
                     error_type=type(e).__name__)
        raise
