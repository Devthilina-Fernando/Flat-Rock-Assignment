import io
import fitz  # PyMuPDF
from app.utils.logging_config import get_logger

logger = get_logger(__name__)


def extract_text_from_pdf(file_bytes: bytes) -> str:
    """Extract all text from a PDF. Falls back to OCR for image-only pages."""
    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
    except Exception as e:
        logger.error("Failed to open PDF", error=str(e))
        return ""

    pages_text: list[str] = []
    for page_num, page in enumerate(doc):
        text = page.get_text("text").strip()
        if text:
            pages_text.append(f"[Page {page_num + 1}]\n{text}")
        else:
            # Image-only page — attempt OCR via pytesseract
            ocr_text = _ocr_page(page)
            if ocr_text:
                pages_text.append(f"[Page {page_num + 1} — OCR]\n{ocr_text}")

    doc.close()
    result = "\n\n".join(pages_text)
    logger.info("PDF extracted", pages=len(pages_text), chars=len(result))
    return result


def _ocr_page(page: fitz.Page) -> str:
    try:
        import pytesseract
        from PIL import Image, ImageEnhance

        pix = page.get_pixmap(dpi=200)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        img = img.convert("L")
        img = ImageEnhance.Contrast(img).enhance(2.0)
        return pytesseract.image_to_string(img, lang="eng")
    except Exception as e:
        logger.warning("OCR failed for page", error=str(e))
        return ""
