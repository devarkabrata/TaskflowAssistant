"""Embeddings + vectorstore setup for RAG.

Uses Supabase's Postgres (with the pgvector extension) as the vector store
rather than a local on-disk store — this whole app is deployed on Render,
whose default disk is wiped on every redeploy, so embedded data has to live
in a separate managed database to actually persist.

Both `get_embeddings()` and `get_vectorstore()` are `@lru_cache`d: neither
depends on anything per-request (no `taskflow_token`, no per-message state),
so building either fresh on every chat message just meant redoing an
embeddings-client + Postgres connection-pool setup (including PGVector's own
`CREATE EXTENSION IF NOT EXISTS vector` check) for no reason. Caching them
means each is built once per process and its connection pool is reused for
every request after that — the same principle as `connection/config.py`'s
own `get_config()`.
"""

from functools import lru_cache

from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_postgres import PGVector

from taskflowassistant.connection.config import config


@lru_cache(maxsize=1)
def get_embeddings() -> GoogleGenerativeAIEmbeddings:
    """Construct the embedding model used to turn text into vectors."""
    return GoogleGenerativeAIEmbeddings(
        model=config["GEMINI_EMBEDDING_MODEL"],
        google_api_key=config["GEMINI_API_KEY"],
    )


def _to_psycopg_url(url: str) -> str:
    """langchain-postgres needs a `postgresql+psycopg://` URL (psycopg3), but
    Supabase's dashboard hands you a plain `postgresql://` one — normalize it
    so pasting Supabase's connection string in as-is just works."""
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


@lru_cache(maxsize=2)
def get_vectorstore(async_mode: bool = False) -> PGVector:
    """Construct the PGVector store, backed by Supabase Postgres.

    `create_extension=True` means it runs `CREATE EXTENSION IF NOT EXISTS
    vector` itself the first time it connects — no manual SQL setup needed
    beyond having a valid Postgres connection string in `SUPABASE_DB_URL`.
    Cached (see module docstring), so that check — and the connection pool
    it sets up — only happens once per `async_mode` value, not once per
    chat message.

    `async_mode` matters because PGVector only sets up one engine (sync OR
    async) at construction time, not both — hence caching per-value
    (`maxsize=2`) rather than a single cached instance:
    - `async_mode=False` (default): for `rag/ingest.py`, a plain sync script
      that calls sync methods like `add_documents()`.
    - `async_mode=True`: for the retriever tool (`rag/retriever.py`), which
      runs inside the agent's `ainvoke()` call and needs `asimilarity_search`.
    """
    return PGVector(
        embeddings=get_embeddings(),
        connection=_to_psycopg_url(config["SUPABASE_DB_URL"]),
        collection_name=config["PGVECTOR_COLLECTION_NAME"],
        use_jsonb=True,
        create_extension=True,
        async_mode=async_mode,
        # Supabase's connection pooler runs in transaction mode, which doesn't
        # support server-side prepared statements — disable psycopg3's
        # automatic use of them so queries don't break against the pooler.
        engine_args={"connect_args": {"prepare_threshold": None}},
    )
