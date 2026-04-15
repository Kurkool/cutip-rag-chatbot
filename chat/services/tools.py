"""Tenant-scoped tools for the agentic chatbot."""

import ast
import logging
import operator
from typing import Callable

from langchain_core.tools import tool

logger = logging.getLogger(__name__)

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

def create_tools(namespace: str) -> tuple[list, Callable[[], list[dict]]]:
    """Create tools scoped to a tenant's Pinecone namespace. Returns (tools, get_sources)."""
    collected_sources: list[dict] = []  # Per-request, not global

    @tool
    async def search_knowledge_base(query: str) -> str:
        """Search the faculty's knowledge base.
        Use this tool to find information about courses, curriculum, tuition,
        forms, schedules, announcements, admission, and any faculty-related topics.
        You can call this multiple times with different keywords if the first
        search doesn't find what you need."""
        try:
            from chat.services.search import search_with_sources
            result, sources = await search_with_sources(query, namespace)
            collected_sources.extend(sources)
            return result
        except Exception as e:
            logger.exception("search_knowledge_base failed")
            return f"Search error: {type(e).__name__} — {e}"

    @tool
    async def search_by_category(query: str, category: str) -> str:
        """Search the knowledge base filtered by document category.
        Use this when you know which type of document to look for.
        Categories: curriculum, form, announcement, schedule, general, spreadsheet.
        Example: search_by_category("ค่าเทอม", "curriculum")"""
        try:
            from chat.services.search import search_with_sources
            result, sources = await search_with_sources(query, namespace, category=category)
            collected_sources.extend(sources)
            return result
        except Exception as e:
            logger.exception("search_by_category failed")
            return f"Search error: {type(e).__name__} — {e}"

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

    def get_sources() -> list[dict]:
        """Return sources collected during this request's tool calls."""
        return list(collected_sources)

    return [search_knowledge_base, search_by_category, calculate, fetch_webpage], get_sources


def _safe_eval(node: ast.AST) -> float:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _SAFE_OPS:
        return _SAFE_OPS[type(node.op)](_safe_eval(node.left), _safe_eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _SAFE_OPS:
        return _SAFE_OPS[type(node.op)](_safe_eval(node.operand))
    raise ValueError(f"Unsupported expression: {ast.dump(node)}")
