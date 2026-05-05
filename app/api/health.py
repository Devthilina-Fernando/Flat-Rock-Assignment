from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.db.session import get_db

router = APIRouter(tags=["health"])


@router.get("/health")
def health_check(db: Session = Depends(get_db)):
    db_ok = False
    chroma_ok = False
    openai_ok = False

    try:
        db.execute(__import__("sqlalchemy").text("SELECT 1"))
        db_ok = True
    except Exception:
        pass

    try:
        from app.rag.chroma_client import get_chroma_collection
        col = get_chroma_collection()
        _ = col.count()
        chroma_ok = True
    except Exception:
        pass

    try:
        from app.config import get_settings
        settings = get_settings()
        if settings.openai_api_key and settings.openai_api_key.startswith("sk-"):
            openai_ok = True
    except Exception:
        pass

    overall = "ok" if all([db_ok, chroma_ok, openai_ok]) else "degraded"

    return {
        "status": overall,
        "components": {
            "database": "ok" if db_ok else "error",
            "chromadb": "ok" if chroma_ok else "error",
            "openai": "ok" if openai_ok else "error",
        },
    }
