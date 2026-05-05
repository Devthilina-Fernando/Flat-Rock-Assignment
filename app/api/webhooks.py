from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.services.orchestrator import run_pipeline
from app.utils.logging_config import get_logger

logger = get_logger(__name__)
router = APIRouter()


@router.post("/process/manual", tags=["processing"])
async def process_manual(
    file: UploadFile = File(...),
    sender_email: str = Form(default="test@example.com"),
    db: Session = Depends(get_db),
):
    """Upload a vendor document and run the full pipeline synchronously."""
    file_bytes = await file.read()
    logger.info("Manual upload received", filename=file.filename,
                content_type=file.content_type, bytes=len(file_bytes),
                sender_email=sender_email)

    extraction = run_pipeline(
        file_bytes=file_bytes,
        filename=file.filename or "upload.txt",
        content_type=file.content_type or "text/plain",
        sender_email=sender_email,
        db=db,
    )
    return extraction
