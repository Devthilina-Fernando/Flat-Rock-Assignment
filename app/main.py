import asyncio
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from app.config import get_settings
from app.utils.logging_config import configure_logging, get_logger
from app.db.base import Base
from app.db.session import engine

logger = get_logger(__name__)

_FRONTEND = os.path.join(os.path.dirname(__file__), "..", "frontend", "index.html")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    configure_logging()
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables initialised")

    try:
        from app.rag.knowledge_base_loader import load_knowledge_base
        load_knowledge_base()
        logger.info("Knowledge base loaded into ChromaDB")
    except Exception as e:
        logger.warning("Knowledge base load failed — RAG will be unavailable", error=str(e))

    # Register the running event loop in the event bus so any thread can publish
    from app.services.event_bus import set_loop
    set_loop(asyncio.get_running_loop())

    # ── Gmail poller (optional) ────────────────────────────────────────────
    _poller = None
    settings = get_settings()
    if settings.gmail_enabled:
        if os.path.exists(settings.gmail_credentials_file):
            from app.services.gmail_poller import GmailPoller
            _poller = GmailPoller()
            _poller.start()
            logger.info("Gmail poller started",
                        credentials=settings.gmail_credentials_file,
                        interval=settings.gmail_poll_interval)
        else:
            logger.warning("GMAIL_ENABLED=true but credentials file not found — skipping",
                           path=settings.gmail_credentials_file)
    else:
        logger.info("Gmail poller disabled (set GMAIL_ENABLED=true to enable)")

    yield

    if _poller is not None:
        _poller.stop()
        _poller.join(timeout=5)
        logger.info("Gmail poller stopped")
    logger.info("Shutting down")


app = FastAPI(
    title="Vendor Onboarding Agent",
    description="Agentic AI system for automated vendor/supplier onboarding document processing",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

from app.api import health, webhooks, vendors, review, events  # noqa: E402

app.include_router(health.router)
app.include_router(webhooks.router, prefix="", tags=["intake"])
app.include_router(vendors.router, prefix="/vendors", tags=["vendors"])
app.include_router(review.router, prefix="/review", tags=["review"])
app.include_router(events.router)


@app.get("/", include_in_schema=False)
def serve_frontend():
    with open(_FRONTEND, encoding="utf-8") as f:
        return HTMLResponse(f.read())
