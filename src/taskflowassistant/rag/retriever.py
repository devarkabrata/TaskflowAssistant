"""Wraps the vectorstore as a retriever, then as a LangChain tool the agent
can call to search the TaskFlow knowledge base.
"""

from functools import lru_cache

from langchain_core.documents import Document
from langchain_core.tools import BaseTool, tool

from taskflowassistant.rag.vectorstore import get_vectorstore

_NO_RESULTS_MESSAGE = "No results found in the TaskFlow knowledge base for that query."


def _format_docs(docs: list[Document]) -> str:
    """Join retrieved docs into one string for the model to read.

    `create_retriever_tool`'s own built-in implementation does this the same
    way (join with "\\n\\n") EXCEPT for the empty-list case: joining zero
    docs produces an empty string, which Gemini tolerates as a tool result
    but Groq's stricter OpenAI-compatible schema rejects outright (a real
    "for 'role:tool' ... minimum number of items is 1" 400 error, reproduced
    against a real "no matches" search). A clear "not found" message instead
    is both a valid non-empty tool result for every provider, and more
    useful to the model than a silently empty one.
    """
    if not docs:
        return _NO_RESULTS_MESSAGE
    return "\n\n".join(doc.page_content for doc in docs)


@lru_cache(maxsize=1)
def get_retriever_tool() -> BaseTool:
    """Build the 'search_knowledge_base' tool for the agent.

    Cached: `get_vectorstore(async_mode=True)` is itself cached (see
    rag/vectorstore.py), so the only thing rebuilt here without caching
    would be the `as_retriever(...)` wrapper and the tool closure — cheap
    individually, but there's no reason to redo either on every chat message
    either, since neither depends on any per-request state (this is the
    shared knowledge-base search, not scoped to a specific caller/token like
    the MCP tools in agent/tools_registry.py are).
    """
    # async_mode=True: the agent only ever calls this tool via ainvoke(),
    # which needs PGVector's async engine/session, not the sync one.
    retriever = get_vectorstore(async_mode=True).as_retriever(search_kwargs={"k": 4})

    @tool
    async def search_knowledge_base(query: str) -> str:
        """Search the TaskFlow knowledge base for documentation, help articles,
        and FAQs about how TaskFlow works. Use this for questions about
        TaskFlow features or policies — not for anything about a specific
        task, team, or person, which the other tools handle.
        """
        docs = await retriever.ainvoke(query)
        return _format_docs(docs)

    return search_knowledge_base
