"""Loads source documents from data/knowledge_base for RAG ingestion.

Supports .txt, .md, and .pdf files. A PDF becomes one Document per page;
.txt/.md files become one Document each. Any other extension is skipped.
"""

from pathlib import Path

from langchain_community.document_loaders import PyPDFLoader, TextLoader
from langchain_core.documents import Document

from taskflowassistant.connection.config import config

_TEXT_SUFFIXES = {".txt", ".md"}


def load_documents() -> list[Document]:
    """Load every .txt/.md/.pdf file under KNOWLEDGE_BASE_DIR into Documents."""
    knowledge_base_dir = Path(config["KNOWLEDGE_BASE_DIR"])
    documents: list[Document] = []

    for file_path in sorted(knowledge_base_dir.rglob("*")):
        if not file_path.is_file():
            continue

        if file_path.suffix == ".pdf":
            documents.extend(PyPDFLoader(str(file_path)).load())
        elif file_path.suffix in _TEXT_SUFFIXES:
            documents.extend(TextLoader(str(file_path), encoding="utf-8").load())
        # any other extension (images, .gitkeep, etc.) is silently skipped

    return documents
