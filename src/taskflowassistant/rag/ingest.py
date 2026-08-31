"""Ingestion pipeline: load knowledge-base docs, chunk them, embed them, and
persist them into the vectorstore (Supabase pgvector).

Run with: uv run python -m taskflowassistant.rag.ingest
(or the `taskflow-ingest` console script)

Re-running this is safe to do after adding/editing files in
data/knowledge_base — it just adds more chunks to the same collection.
"""

from langchain_text_splitters import RecursiveCharacterTextSplitter

from taskflowassistant.connection.config import config
from taskflowassistant.rag.loader import load_documents
from taskflowassistant.rag.vectorstore import get_vectorstore


def main() -> None:
    documents = load_documents()
    if not documents:
        print(f"No documents found under {config['KNOWLEDGE_BASE_DIR']!r} — nothing to ingest.")
        return

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=config["CHUNK_SIZE"],
        chunk_overlap=config["CHUNK_OVERLAP"],
    )
    chunks = splitter.split_documents(documents)

    vectorstore = get_vectorstore()
    vectorstore.add_documents(chunks)

    print(
        f"Ingested {len(chunks)} chunks from {len(documents)} documents into "
        f"the '{config['PGVECTOR_COLLECTION_NAME']}' collection."
    )


if __name__ == "__main__":
    main()
