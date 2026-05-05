import os
import uuid
from pathlib import Path
from openai import OpenAI
from app.config import get_settings
from app.rag.chroma_client import get_chroma_collection, reset_collection
from app.utils.logging_config import get_logger

logger = get_logger(__name__)

KB_DIR = Path(__file__).parent / "knowledge_base"
CHUNK_SIZE = 800       # characters per chunk
CHUNK_OVERLAP = 100    # character overlap between chunks
EMBED_MODEL = "text-embedding-3-small"
EMBED_BATCH = 50       # max documents per OpenAI embedding call


def _chunk_text(text: str, source_file: str) -> list[dict]:
    """Split text into overlapping chunks and attach metadata."""
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + CHUNK_SIZE, len(text))
        chunk = text[start:end].strip()
        if chunk:
            chunks.append({
                "id": str(uuid.uuid4()),
                "text": chunk,
                "source_file": source_file,
            })
        start += CHUNK_SIZE - CHUNK_OVERLAP
    return chunks


def _embed_texts(client: OpenAI, texts: list[str]) -> list[list[float]]:
    response = client.embeddings.create(model=EMBED_MODEL, input=texts)
    return [item.embedding for item in response.data]


def load_knowledge_base(force_reload: bool = False) -> int:
    """
    Load all policy documents from the knowledge_base directory into ChromaDB.
    Returns total number of chunks stored.
    """
    collection = get_chroma_collection()

    # Skip if already populated and not forcing reload
    if not force_reload and collection.count() > 0:
        logger.info("Knowledge base already loaded", chunks=collection.count())
        return collection.count()

    logger.info("Loading knowledge base into ChromaDB...")
    reset_collection()
    collection = get_chroma_collection()

    settings = get_settings()
    openai_client = OpenAI(api_key=settings.openai_api_key)

    all_chunks: list[dict] = []
    for filepath in sorted(KB_DIR.glob("*.txt")):
        text = filepath.read_text(encoding="utf-8")
        chunks = _chunk_text(text, filepath.name)
        all_chunks.extend(chunks)
        logger.info("Chunked policy doc", file=filepath.name, chunks=len(chunks))

    if not all_chunks:
        logger.warning("No knowledge base documents found in", path=str(KB_DIR))
        return 0

    # Batch embed
    texts = [c["text"] for c in all_chunks]
    embeddings: list[list[float]] = []
    for i in range(0, len(texts), EMBED_BATCH):
        batch = texts[i : i + EMBED_BATCH]
        embeddings.extend(_embed_texts(openai_client, batch))
        logger.info("Embedded batch", start=i, end=i + len(batch))

    # Upsert into ChromaDB
    collection.upsert(
        ids=[c["id"] for c in all_chunks],
        documents=[c["text"] for c in all_chunks],
        embeddings=embeddings,
        metadatas=[{"source_file": c["source_file"]} for c in all_chunks],
    )

    total = collection.count()
    logger.info("Knowledge base loaded", total_chunks=total)
    return total


def query_knowledge_base(query: str, n_results: int = 4) -> list[dict]:
    """
    Embed query and retrieve top-n matching policy chunks.
    Returns list of {text, source_file, distance} dicts.
    """
    settings = get_settings()
    openai_client = OpenAI(api_key=settings.openai_api_key)
    collection = get_chroma_collection()

    if collection.count() == 0:
        logger.warning("ChromaDB collection is empty — RAG unavailable")
        return []

    embeddings = _embed_texts(openai_client, [query])
    results = collection.query(
        query_embeddings=embeddings,
        n_results=min(n_results, collection.count()),
        include=["documents", "metadatas", "distances"],
    )

    chunks = []
    for doc, meta, dist in zip(
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0],
    ):
        chunks.append({
            "text": doc,
            "source_file": meta.get("source_file", "unknown"),
            "distance": dist,
        })
    return chunks
