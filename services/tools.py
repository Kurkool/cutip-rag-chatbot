"""Tenant-scoped tools for the agentic chatbot."""

import ast
import operator

from langchain_core.documents import Document
from langchain_core.tools import tool

from services.reranker import rerank_documents
from services.vectorstore import get_vectorstore

# Safe math operators (no eval!)
_SAFE_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
}

_MAX_RESULT_CHARS = 2000  # Truncate per document to fit LINE limits


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
        """Evaluate a math expression safely. Use for tuition totals, GPA calculations,
        credit sums, or any numeric computation.
        Examples: '21000 * 8', '(3.5 + 4.0) / 2', '144 - 36'"""
        try:
            result = _safe_eval(ast.parse(expression, mode="eval").body)
            return str(result)
        except Exception as e:
            return f"Calculation error: {e}"

    @tool
    def fetch_webpage(url: str) -> str:
        """Fetch and read a web page as text. Use when search results contain
        a URL or link that might have additional relevant information."""
        import httpx
        try:
            response = httpx.get(
                f"https://r.jina.ai/{url}",
                timeout=15,
                headers={"Accept": "text/plain"},
            )
            response.raise_for_status()
            return response.text[:3000]
        except Exception as e:
            return f"Failed to fetch {url}: {e}"

    return [search_knowledge_base, search_by_category, calculate, fetch_webpage]


def _safe_eval(node: ast.AST) -> float:
    """Evaluate an AST math expression without using eval()."""
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _SAFE_OPS:
        return _SAFE_OPS[type(node.op)](_safe_eval(node.left), _safe_eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _SAFE_OPS:
        return _SAFE_OPS[type(node.op)](_safe_eval(node.operand))
    raise ValueError(f"Unsupported expression: {ast.dump(node)}")


def _format_results(docs: list[Document]) -> str:
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
        content = doc.page_content[:_MAX_RESULT_CHARS]
        results.append(f"{header}\n{content}")
    return "\n\n---\n\n".join(results)
