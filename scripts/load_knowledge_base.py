"""One-time script to embed and load all policy documents into ChromaDB."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.rag.knowledge_base_loader import load_knowledge_base

total = load_knowledge_base(force_reload=True)
print(f"Knowledge base loaded: {total} chunks stored in ChromaDB.")
