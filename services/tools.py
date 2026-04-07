"""Tenant-scoped tools for the agentic chatbot."""

from langchain_core.tools import tool

from services.reranker import rerank_documents
from services.vectorstore import get_vectorstore

# Top-level tool factories are called once per request to bind tenant namespace.


def create_tools(namespace: str) -> list:
    """Create a set of tools scoped to a specific tenant's Pinecone namespace."""

    @tool
    async def search_knowledge_base(query: str) -> str:
        """Search the faculty's knowledge base.
        Use this tool to find information about courses, curriculum, tuition,
        forms, schedules, announcements, admission, and any faculty-related topics.
        You can call this multiple times with different keywords if the first
        search doesn't find what you need."""
        vectorstore = get_vectorstore(namespace)
        docs = await vectorstore.asimilarity_search(query, k=10)
        if not docs:
            return "No relevant documents found for this query."

        reranked = rerank_documents(query, docs, top_k=4)
        results = []
        for i, doc in enumerate(reranked, 1):
            source = doc.metadata.get("source_filename", doc.metadata.get("source", "unknown"))
            page = doc.metadata.get("page", "")
            header = f"[{i}] Source: {source}"
            if page and page != "N/A":
                header += f" (page {page})"
            results.append(f"{header}\n{doc.page_content}")

        return "\n\n---\n\n".join(results)

    @tool
    def calculate(expression: str) -> str:
        """Evaluate a math expression. Use for tuition totals, GPA calculations,
        credit sums, or any numeric computation.
        Examples: '21000 * 8', '(3.5 + 4.0) / 2', '144 - 36'"""
        allowed_names = {"abs": abs, "round": round, "min": min, "max": max}
        try:
            result = eval(expression, {"__builtins__": {}}, allowed_names)
            return str(result)
        except Exception as e:
            return f"Calculation error: {e}"

    return [search_knowledge_base, calculate]
