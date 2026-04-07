"""Tenant-scoped tools for the agentic chatbot."""

from langchain_core.tools import tool

from services.reranker import rerank_documents
from services.vectorstore import get_vectorstore


def create_tools(namespace: str) -> list:
    """Create a set of tools scoped to a specific tenant's Pinecone namespace."""

    @tool
    def search_knowledge_base(query: str) -> str:
        """Search the faculty's knowledge base.
        Use this tool to find information about courses, curriculum, tuition,
        forms, schedules, announcements, admission, and any faculty-related topics.
        You can call this multiple times with different keywords if the first
        search doesn't find what you need."""
        vectorstore = get_vectorstore(namespace)
        docs = vectorstore.similarity_search(query, k=10)
        if not docs:
            return "No relevant documents found for this query."

        reranked = rerank_documents(query, docs, top_k=4)
        return _format_results(reranked)

    @tool
    def search_by_category(query: str, category: str) -> str:
        """Search the knowledge base filtered by document category.
        Use this when you know which type of document to look for.
        Categories: curriculum, form, announcement, schedule, general, spreadsheet.
        Example: search_by_category("ค่าเทอม", "curriculum")"""
        vectorstore = get_vectorstore(namespace)
        docs = vectorstore.similarity_search(
            query,
            k=10,
            filter={"doc_category": category},
        )
        if not docs:
            return f"No documents found in category '{category}' for this query."

        reranked = rerank_documents(query, docs, top_k=4)
        return _format_results(reranked)

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

    return [search_knowledge_base, search_by_category, calculate]


def _format_results(docs: list) -> str:
    """Format reranked documents into a readable string for the agent."""
    results = []
    for i, doc in enumerate(docs, 1):
        source = doc.metadata.get("source_filename", doc.metadata.get("source", "unknown"))
        page = doc.metadata.get("page", "")
        category = doc.metadata.get("doc_category", "")
        header = f"[{i}] Source: {source}"
        if page and page != "N/A":
            header += f" (page {page})"
        if category:
            header += f" [{category}]"
        results.append(f"{header}\n{doc.page_content}")
    return "\n\n---\n\n".join(results)
