from app.utils.logging_config import get_logger
from app.services.pdf_extractor import extract_text_from_pdf
from app.services.image_extractor import extract_text_from_image
from app.services.csv_extractor import extract_text_from_csv

logger = get_logger(__name__)


def _extract_plain_text(file_bytes: bytes) -> str:
    for enc in ("utf-8", "latin-1", "cp1252"):
        try:
            return file_bytes.decode(enc)
        except UnicodeDecodeError:
            continue
    return ""


_MIME_MAP = {
    "application/pdf": ("pdf", extract_text_from_pdf),
    "image/png": ("image", extract_text_from_image),
    "image/jpeg": ("image", extract_text_from_image),
    "image/jpg": ("image", extract_text_from_image),
    "image/tiff": ("image", extract_text_from_image),
    "image/bmp": ("image", extract_text_from_image),
    "text/csv": ("csv", extract_text_from_csv),
    "application/vnd.ms-excel": ("csv", extract_text_from_csv),
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ("csv", extract_text_from_csv),
    "text/plain": ("txt", _extract_plain_text),
}


def load_document(file_bytes: bytes, content_type: str, filename: str) -> tuple[str, str]:
    """Return (extracted_text, document_type)."""
    ct = content_type.lower().split(";")[0].strip()
    logger.info("Loading document", filename=filename, content_type=ct,
                bytes=len(file_bytes))

    # Try registered MIME types
    if ct in _MIME_MAP:
        doc_type, extractor = _MIME_MAP[ct]
        logger.info("Extracting via MIME type", mime=ct, doc_type=doc_type)
        text = extractor(file_bytes)
        logger.info("Extraction via MIME complete", doc_type=doc_type, chars=len(text))
        return text, doc_type

    # Fallback: infer from filename extension
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    logger.info("MIME type not in map, trying extension fallback",
                content_type=ct, ext=ext, filename=filename)

    if ext == "pdf":
        text = extract_text_from_pdf(file_bytes)
        logger.info("Extracted via extension (.pdf)", chars=len(text))
        return text, "pdf"
    if ext in ("png", "jpg", "jpeg", "tiff", "bmp"):
        text = extract_text_from_image(file_bytes)
        logger.info("Extracted via extension (image)", ext=ext, chars=len(text))
        return text, "image"
    if ext in ("csv", "xls", "xlsx"):
        text = extract_text_from_csv(file_bytes)
        logger.info("Extracted via extension (csv/excel)", ext=ext, chars=len(text))
        return text, "csv"
    if ext == "txt":
        text = _extract_plain_text(file_bytes)
        logger.info("Extracted via extension (.txt)", chars=len(text))
        return text, "txt"
    if ext == "docx":
        text = _extract_docx(file_bytes)
        logger.info("Extracted via extension (.docx)", chars=len(text))
        return text, "txt"

    # Final fallback: try decoding as plain text (handles application/octet-stream
    # and any other unrecognised MIME type where the file is actually readable text)
    text = _extract_plain_text(file_bytes)
    if text.strip():
        logger.warning("Falling back to plain-text extraction",
                       content_type=ct, filename=filename, chars=len(text))
        return text, "txt"

    logger.warning("Unsupported file type — could not extract text",
                   content_type=ct, filename=filename)
    return "", "unknown"


def _extract_docx(file_bytes: bytes) -> str:
    try:
        import docx
        import io
        doc = docx.Document(io.BytesIO(file_bytes))
        return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    except Exception as e:
        logger.error("DOCX extraction failed", error=str(e))
        return ""
