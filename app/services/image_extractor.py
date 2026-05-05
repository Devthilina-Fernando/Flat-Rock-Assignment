from app.utils.logging_config import get_logger

logger = get_logger(__name__)


def extract_text_from_image(file_bytes: bytes) -> str:
    """OCR an image attachment and return extracted text."""
    try:
        import pytesseract
        from PIL import Image, ImageEnhance
        import io

        img = Image.open(io.BytesIO(file_bytes))
        img = img.convert("L")
        img = ImageEnhance.Contrast(img).enhance(2.0)
        img = ImageEnhance.Sharpness(img).enhance(2.0)
        text = pytesseract.image_to_string(img, lang="eng")
        logger.info("Image OCR complete", chars=len(text))
        return text
    except Exception as e:
        logger.error("Image OCR failed", error=str(e))
        return ""
