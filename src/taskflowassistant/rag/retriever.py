"""Wraps the vectorstore as a retriever, then as a LangChain tool the agent
can call to search the TaskFlow knowledge base.
"""

from langchain_classic.tools.retriever import create_retriever_tool
from langchain_core.tools import BaseTool

from taskflowassistant.rag.vectorstore import get_vectorstore


def get_retriever_tool() -> BaseTool:
    """Build the 'search_knowledge_base' tool for the agent."""
    # async_mode=True: the agent only ever calls this tool via ainvoke(),
    # which needs PGVector's async engine/session, not the sync one.
    retriever = get_vectorstore(async_mode=True).as_retriever(search_kwargs={"k": 4})

    return create_retriever_tool(
        retriever,
        name="search_knowledge_base",
        description=(
            "Search the TaskFlow knowledge base for documentation, help articles, "
            "and FAQs about how TaskFlow works. Use this for questions about "
            "TaskFlow features or policies — not for anything about a specific "
            "task, team, or person, which the other tools handle."
        ),
    )
